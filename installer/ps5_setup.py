#!/usr/bin/env python3
"""OpenGOAL-PS5 console setup: finds the PS5, maps what runs on it, installs what is missing, starts the app. Python 3.7+, stdlib only.

  python ps5_setup.py [--ip ADDRESS] [--no-scan] [--with-kstuff] [--update] [--yes] [--dry-run] [--lang de|en] [--json]

Phases: DISCOVER (find the console) -> MAP (what answers: loader, FTP, shell, agent, app) -> PLAN (missing steps, computed from the live state)
-> INSTALL (payloads, agent, app upload, launch). The state is re-probed every 1 to 2 s during all phases. Run it again at any time: it only does
what the live state still needs. It never writes kernel flags, never restarts the console and never loads OnionHEN.
Exit codes: 0 done, 1 failed, 2 console not found / bad usage, 3 gave up waiting, 130 interrupted.

Port sources (read from upstream on 2026-10-24, nothing guessed):
  9021 ps5-payload-dev/elfldr main.c (int port = 9021); etaHEN README ("elf loader on port 9021")
  9020 ps5-payload-dev/elfldr README (BD-J loader on 9020); etaHEN README ("exploit elfldr 9020")
  2121 ps5-payload-dev/ftpsrv README ("accepts connection on port 2121"); banner "220-Welcome to ftpsrv.elf" (srv.c)
  2323 ps5-payload-dev/shsrv shsrv.c (int port = 2323); prompt "<cwd>$ " (sh.c)
  744 / 3232 / 1010(udp) Pharaoh2k/ps5debug-NG README ports table (command server / kernel log forwarder / discovery beacon)
  8080 ps5-payload-dev/websrv src/main.c (port = 8080); our app also uses 8080 and is told apart by GET /api/info ("install_api")
  1337 / 9081 / 9090 / 12800 / 8000 LightningMods/etaHEN README (FTP / klog / PKG installer / PKG installer WebUI / Discord RPC)
  10101 drakmor/ShadowMountPlus README (api_port default; the API binds to 127.0.0.1 unless api_bind_address is changed)
  9099 our agent (payloads/ogagent.c). OnionHEN: no upstream port found, it is recognised by process name only.
  UDP 9302 PS5 Remote Play discovery (DDP): "SRCH * HTTP/1.1" with protocol version 00030010, from streetpea/chiaki-ng lib/src/discovery.c.
  Sony Interactive Entertainment OUIs: IEEE https://standards-oui.ieee.org/oui/oui.txt (entries named "Sony Interactive Entertainment Inc.").
"""
import argparse, concurrent.futures as cf, hashlib, http.client as hc, ipaddress, json, locale, os, re, secrets, shutil, socket, subprocess, sys
import tempfile, threading, time, urllib.parse, urllib.request, zipfile
from collections import deque

APP_ID = "LAPY77001"
REMOTE_APP = "/data/homebrew/" + APP_ID
REMOTE_CFG = "/data/opengoal/config/ps5.cfg"
MANIFEST = ".og-manifest.json"
MARKER = b"OGAGENT_TOKEN:"
TOKEN_LEN = 32
LAST = ("param.json", "eboot.bin")  # sent last: an interrupted upload never leaves a launchable half-app
RELEASE_BASE = "https://github.com/0iy/opengoal-ps5/releases/latest/download"
DATA_FORMAT = 1  # layout of an installed game; keep equal to pc_import.DATA_FORMAT (tests check it)


def vkey(v):
    """'0.1.10' -> (0, 1, 10); compares versions without a dependency."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def local_version(path=None):
    """The release this script belongs to: the VERSION file next to it (in the bundle and in the GUI zip), else None."""
    try:
        with open(path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as f:
            v = f.readline().strip()
        return v if vkey(v) else None
    except OSError:
        return None


def latest_version(base=None):
    """The newest published release (tiny VERSION asset). None on any problem: an update check must never block or fail a setup."""
    try:
        with urllib.request.urlopen((base or os.environ.get("OGPS5_BASE", RELEASE_BASE)) + "/VERSION", timeout=4) as r:
            v = r.read(64).decode("ascii", "replace").strip()
        return v if re.fullmatch(r"\d+(\.\d+){1,3}", v) else None
    except (OSError, hc.HTTPException, ValueError):
        return None


def update_state(st, o):
    """Decides from the live /api/info answer and the release this script ships: 'update' | 'current' | 'newer' | 'busy' | None (unknown)."""
    app, tgt = st["app"], getattr(o, "target", None)
    if app is None or not tgt:
        return None
    have = app.get("app") or ""  # builds before 0.1.1 do not report a version
    if app.get("busy"):
        return "busy"
    if not vkey(have) or vkey(have) < vkey(tgt):
        return "update"
    return "current" if vkey(have) == vkey(tgt) else "newer"

PORTS = {"loader": 9021, "loader2": 9020, "ftp": 2121, "shsrv": 2323, "debug": 744, "dbg_klog": 3232, "web": 8080, "agent": 9099,
         "eta_ftp": 1337, "eta_klog": 9081, "eta_pkg": 9090, "eta_webui": 12800, "eta_rpc": 8000, "smp_api": 10101}
ETA = ("eta_ftp", "eta_klog", "eta_pkg", "eta_webui", "eta_rpc")
DDP_PORT, DDP_REQ = 9302, b"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n"

# "Sony Interactive Entertainment Inc." entries of the IEEE OUI list (first three bytes)
SONY_OUI = set("00041F 001315 0015C1 0019C5 001D0D 001FA7 00248D 00D9D1 00E421 04F778 0C7043 0CFE45 280DFC 2840DD 2C9E00 2CCC44 50B03B 54E6FD 5C843C "
               "5C9666 68286C 70662A 709E29 78C881 84E657 904748 98FA2E 9C37CB A8E3EE B40AD8 B41F4D BC3329 BC60A7 C0151B C84AA0 C863F1 D4F7D5 "
               "E86E3A EC748C F46412 F8461C F8D0AC FC0FE6 FCCA40".split())

# Pinned release assets: size and sha256 were read from the GitHub release API and re-computed on the downloaded files.
PAYLOADS = {
    "kstuff": dict(name="kstuff-lite v1.11", size=1737080, sha256="ab9a6cb4d3b1daf139d4d646e402b1cf569071acd64599c936d7a3a6164dc779",
                   url="https://github.com/EchoStretch/kstuff-lite/releases/download/v1.11/kstuff.elf", source="github.com/EchoStretch/kstuff-lite",
                   license="no license file published: fetched from the author's release, never bundled with this project"),
    "smp": dict(name="ShadowMountPlus 1.7beta7", size=2517288, sha256="a8f9d7f76e8749912508ade0cd5c78076b5bbf1271813c78c80c3d3d9d4777ee",
                url="https://github.com/drakmor/ShadowMountPlus/releases/download/1.7beta7/shadowmountplus.elf", source="github.com/drakmor/ShadowMountPlus",
                license="GPL-3.0"),
    "ftpsrv": dict(name="ftpsrv v0.21.1 (fallback)", size=191864, sha256="7d4b31c83eae4e056580482a3a074e1db25922efc74ac1e439473b45d71a5938",
                   url="https://github.com/ps5-payload-dev/ftpsrv/releases/download/v0.21.1/ftpsrv-ps5.elf", source="github.com/ps5-payload-dev/ftpsrv",
                   license="GPL-3.0"),
    "shsrv": dict(name="shsrv v0.20 (optional)", size=986184, sha256="fa4ccb2587bb61be317df0d001f668b17ebf9b4aafad87acf691b1fb8da0bd2d",
                  url="https://github.com/ps5-payload-dev/shsrv/releases/download/v0.20/shsrv-ps5.elf", source="github.com/ps5-payload-dev/shsrv",
                  license="GPL-3.0"),
}

T = {
    "en": {
        "title": "OpenGOAL-PS5 setup", "dry": "DRY RUN: nothing is sent to the console.",
        "scan": "Searching {} for the console...", "remembered": "Using the remembered address {}.", "found": "Console found: {}",
        "pick": "Which one? Number or address: ", "ask_ip": "PS5 address (shown in its network settings): ",
        "none": "No console found. Start the exploit and the ELF loader (port 9021) on the PS5, then run this again, or pass --ip ADDRESS.",
        "ambiguous": "Several consoles look possible and --yes cannot choose between them. Pass --ip ADDRESS.",
        "idle": "Nothing to do: OpenGOAL-PS5 already answers at http://{}",
        "updating": "Updating OpenGOAL-PS5 {} -> {}. Your games and saves stay on the console.", "update_unknown": "an older version",
        "uptodate": "OpenGOAL-PS5 {} is up to date. Nothing to do: it answers at http://{}",
        "newer_here": "The console has OpenGOAL-PS5 {}, newer than this installer ({}). Nothing was changed. Use --update to force.",
        "busy_update": "The console is busy with an import. Update again when it is finished. Nothing was changed.",
        "update_avail": "A newer OpenGOAL-PS5 is available: {} (this installer is {}). Update: run the one-line install again (see the README).",
        "reimport": "This update changes the game format. Import these games again (their old copy keeps working until you do): {}",
        "ask_kstuff": "The app is refused without kstuff-lite. Load kstuff-lite now (downloaded from the author's release, no license file)? [y/N] ",
        "no_kstuff": "kstuff does not look loaded and loading it was not allowed. Load kstuff-lite yourself or run again with --with-kstuff.",
        "w_loader": "Waiting for the ELF loader on port {}. On the PS5 start the exploit (or the loader); this continues by itself.",
        "w_agent": "Waiting for the agent on port {}. If nothing happens the loader did not start it: run the exploit again.",
        "w_smp": "ShadowMountPlus does not show up yet (it may run under another name); continuing.",
        "w_app": "Waiting for the app. If the PS5 shows an error (0x80020008), restart the jailbreak chain without OnionHEN and run this again.",
        "onion": "OnionHEN is loaded. It must not be loaded before the app is launched (error 0x80020008). If the app is refused, restart the jailbreak without it.",
        "locked": "Port {} answers with a token this computer does not know (an agent from an unknown run). Restart the exploit to clear it, then run this again.",
        "no_elf": "ogagent.elf not found. Expected payloads/ogagent.elf next to this script (build it with payloads/build.sh, or use the full release).",
        "marker": "ogagent.elf has no usable token marker (found {} times, need exactly 1). The file is not the matching agent build.",
        "hash_bad": "Refused {}: size or SHA-256 does not match the pinned release. Nothing was sent.",
        "no_app": "App folder not found and the release could not be fetched ({}). Pass --app DIR (the LAPY77001 folder with eboot.bin).",
        "up_fail": "Upload failed: {}", "giveup": "Gave up after {} s waiting for: {}", "launch_fail": "The app did not start. {}",
        "done": "Done. OpenGOAL-PS5 answers at http://{}", "next": "Next: add your games. Open the import window: {}",
        "stuck": "A suspended copy of the app blocks the start (launch code 0x8094000c). Close the game on the PS5 (home screen, Options, Close Game). If it stays, restart the jailbreak chain, then run this again.",
        "launch_rc": "The console refused the launch (code 0x{:08x}). Is ShadowMountPlus running and has it mounted the app?",
        "ask_import": "Open the game import window now? [y/N] ", "fw": "Firmware {} (only 13.60 is tested)",
        "noagent_done": "Files are on the console. Load ShadowMountPlus and kstuff yourself, then start OpenGOAL-PS5 from the home screen.",
    },
    "de": {
        "title": "OpenGOAL-PS5 Einrichtung", "dry": "TESTLAUF: Es wird nichts an die Konsole gesendet.",
        "scan": "Suche in {} nach der Konsole...", "remembered": "Verwende die gemerkte Adresse {}.", "found": "Konsole gefunden: {}",
        "pick": "Welche? Nummer oder Adresse: ", "ask_ip": "PS5-Adresse (steht in den Netzwerkeinstellungen): ",
        "none": "Keine Konsole gefunden. Starte auf der PS5 den Exploit und den ELF-Loader (Port 9021) und starte dies erneut, oder nutze --ip ADRESSE.",
        "ambiguous": "Mehrere Konsolen kommen infrage, --yes kann nicht waehlen. Nutze --ip ADRESSE.",
        "idle": "Nichts zu tun: OpenGOAL-PS5 antwortet schon unter http://{}",
        "updating": "OpenGOAL-PS5 wird aktualisiert: {} -> {}. Deine Spiele und Spielstaende bleiben auf der Konsole.", "update_unknown": "eine aeltere Version",
        "uptodate": "OpenGOAL-PS5 {} ist aktuell. Nichts zu tun: es antwortet unter http://{}",
        "newer_here": "Auf der Konsole ist OpenGOAL-PS5 {}, neuer als dieses Installationsprogramm ({}). Nichts geaendert. Mit --update erzwingen.",
        "busy_update": "Die Konsole ist mit einem Import beschaeftigt. Aktualisiere nach dem Ende erneut. Nichts geaendert.",
        "update_avail": "Eine neuere OpenGOAL-PS5 ist verfuegbar: {} (dieses Installationsprogramm ist {}). Aktualisieren: die Einzeiler-Installation erneut ausfuehren (siehe README).",
        "reimport": "Dieses Update aendert das Spielformat. Importiere diese Spiele erneut (die alte Kopie laeuft bis dahin weiter): {}",
        "ask_kstuff": "Ohne kstuff-lite wird die App abgelehnt. kstuff-lite jetzt laden (vom Release des Autors, ohne Lizenzdatei)? [j/N] ",
        "no_kstuff": "kstuff scheint nicht geladen und Laden war nicht erlaubt. Lade kstuff-lite selbst oder starte mit --with-kstuff erneut.",
        "w_loader": "Warte auf den ELF-Loader an Port {}. Starte auf der PS5 den Exploit (oder den Loader); es geht von selbst weiter.",
        "w_agent": "Warte auf den Agent an Port {}. Passiert nichts, hat der Loader ihn nicht gestartet: Exploit erneut ausfuehren.",
        "w_smp": "ShadowMountPlus ist noch nicht sichtbar (evtl. anderer Prozessname); es geht weiter.",
        "w_app": "Warte auf die App. Zeigt die PS5 einen Fehler (0x80020008), Jailbreak ohne OnionHEN neu starten und dies erneut ausfuehren.",
        "onion": "OnionHEN ist geladen. Es darf nicht vor dem Start der App geladen werden (Fehler 0x80020008). Wird die App abgelehnt, Jailbreak ohne es neu starten.",
        "locked": "Port {} antwortet mit einem unbekannten Token (Agent aus einem unbekannten Lauf). Exploit neu starten, dann dies erneut ausfuehren.",
        "no_elf": "ogagent.elf nicht gefunden. Erwartet: payloads/ogagent.elf neben diesem Skript (mit payloads/build.sh bauen oder das volle Release nutzen).",
        "marker": "ogagent.elf hat keine brauchbare Token-Marke ({} Treffer, genau 1 noetig). Die Datei ist nicht der passende Agent.",
        "hash_bad": "Abgelehnt: {}. Groesse oder SHA-256 passt nicht zum festgelegten Release. Es wurde nichts gesendet.",
        "no_app": "App-Ordner nicht gefunden, Release nicht ladbar ({}). Nutze --app ORDNER (der LAPY77001-Ordner mit eboot.bin).",
        "up_fail": "Upload fehlgeschlagen: {}", "giveup": "Nach {} s aufgegeben beim Warten auf: {}", "launch_fail": "Die App ist nicht gestartet. {}",
        "done": "Fertig. OpenGOAL-PS5 antwortet unter http://{}", "next": "Als Naechstes: Spiele hinzufuegen. Import-Fenster oeffnen: {}",
        "stuck": "Eine angehaltene Kopie der App blockiert den Start (Code 0x8094000c). Spiel auf der PS5 schliessen (Startbildschirm, Optionen, Spiel beenden). Bleibt sie, Jailbreak neu starten und dies erneut ausfuehren.",
        "launch_rc": "Die Konsole hat den Start abgelehnt (Code 0x{:08x}). Laeuft ShadowMountPlus und hat es die App eingebunden?",
        "ask_import": "Import-Fenster jetzt oeffnen? [j/N] ", "fw": "Firmware {} (nur 13.60 ist getestet)",
        "noagent_done": "Die Dateien liegen auf der Konsole. Lade ShadowMountPlus und kstuff selbst, dann starte OpenGOAL-PS5 im Startbildschirm.",
    },
}
LABELS = {  # row key: (en, de)
    "loader": ("ELF loader", "ELF-Loader"), "ftp": ("FTP", "FTP"), "shsrv": ("Shell", "Shell"), "debug": ("ps5debug", "ps5debug"),
    "agent": ("OpenGOAL agent", "OpenGOAL-Agent"), "app": ("OpenGOAL-PS5 app", "OpenGOAL-PS5-App"), "smp": ("ShadowMountPlus", "ShadowMountPlus"),
    "kstuff": ("kstuff", "kstuff"), "onion": ("OnionHEN", "OnionHEN"), "fw": ("Firmware", "Firmware"),
}
STEP_LABELS = {  # step: (en, de)
    "loader": ("wait for the ELF loader", "auf den ELF-Loader warten"), "agent": ("send the agent (ogagent.elf)", "Agent senden (ogagent.elf)"),
    "kstuff": ("load kstuff-lite", "kstuff-lite laden"), "smp": ("load ShadowMountPlus", "ShadowMountPlus laden"),
    "upload": ("upload the app", "App hochladen"), "launch": ("start the app", "App starten"),
    "ftpsrv": ("load ftpsrv (fallback)", "ftpsrv laden (Ausweichweg)"), "ftp_install": ("upload over FTP", "per FTP hochladen"),
}


class Fail(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


# ----------------------------------------------------------------------------------------------- small helpers
def home():
    return os.environ.get("OGPS5_HOME") or os.path.join(os.path.expanduser("~"), ".opengoal-ps5")


def system_lang():
    loc = (os.environ.get("LC_ALL") or os.environ.get("LANG") or (locale.getlocale()[0] or "")).lower()
    return "de" if loc.startswith("de") else "en"


def file_mode(rel):
    """eboot.bin and the .prx modules need the execute bit: without it the loader reports a missing .prx and the app hangs suspended."""
    return "0755" if rel == "eboot.bin" or rel.startswith("sce_module/") else "0644"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def patch_token(elf, token):
    """Replace the 32 bytes behind the marker with the token. Exactly one marker must exist; length and all other bytes stay identical."""
    if not re.fullmatch(r"[0-9A-Za-z]{%d}" % TOKEN_LEN, token):
        raise ValueError("token must be %d alphanumeric characters" % TOKEN_LEN)
    key = MARKER + b"x" * TOKEN_LEN
    n = elf.count(key)
    if n != 1:
        raise Fail(T["en"]["marker"].format(n))
    i = elf.index(key) + len(MARKER)
    out = elf[:i] + token.encode() + elf[i + TOKEN_LEN:]
    assert len(out) == len(elf)
    return out


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def fmt_mb(n):
    return "%.1f MB" % (n / 1048576)


# ----------------------------------------------------------------------------------------------- log (token masked)
class Log:
    secrets = []

    def __init__(self):
        self.f = None
        try:
            os.makedirs(home(), exist_ok=True)
            p = os.path.join(home(), "setup.log")
            if os.path.exists(p) and os.path.getsize(p) > 1 << 20:
                os.replace(p, p + ".old")
            self.f = open(p, "a", encoding="utf-8")
        except OSError:
            pass

    def close(self):
        if self.f:
            self.f.close()
            self.f = None

    def write(self, text):
        if not self.f:
            return
        for s in Log.secrets:
            text = text.replace(s, "*" * 8)
        try:
            self.f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
            self.f.flush()
        except OSError:
            pass


# ----------------------------------------------------------------------------------------------- UI (JSON events, line mode, ANSI live view)
class UI:
    """Base: every UI receives the same events. emit(type, **data)."""

    def __init__(self, lang, log, t0):
        self.lang, self.log, self.t0 = lang, log, t0

    def tr(self, key, *a):
        return T[self.lang][key].format(*a)

    def emit(self, typ, **d):
        if typ not in ("state", "now", "progress"):
            self.log.write("%s %s" % (typ, json.dumps(d, sort_keys=True, default=str)))
        self.handle(typ, d)

    def handle(self, typ, d):
        pass

    def ask(self, prompt):
        return input(prompt)

    def close(self):
        pass

    def say(self, key, *a, level="info"):
        self.emit("msg", level=level, key=key, text=self.tr(key, *a))


class JsonUI(UI):
    def handle(self, typ, d):
        sys.stdout.write(json.dumps(dict(d, type=typ, t=round(time.time() - self.t0, 2))) + "\n")
        sys.stdout.flush()

    def ask(self, prompt):
        raise EOFError


class LineUI(UI):
    def __init__(self, *a):
        UI.__init__(self, *a)
        self.last_prog = 0

    def out(self, text):
        print("[%6.1fs] %s" % (time.time() - self.t0, text))
        sys.stdout.flush()

    def handle(self, typ, d):
        if typ == "msg":
            self.out(("! " if d["level"] in ("warn", "bad") else "") + d["text"])
        elif typ == "change":
            self.out("%s: %s" % (d["label"], d["text"]))
        elif typ == "step":
            self.out("step %s: %s" % (d["id"], d["status"]))
        elif typ == "plan":
            self.out("plan: " + (", ".join(s["label"] for s in d["steps"]) or "nothing to do"))
        elif typ == "payload":
            self.out("%s - %s - %s" % (d["name"], d["source"], d["license"]))
        elif typ == "now" and d.get("first"):
            self.out(d["text"])
        elif typ == "progress" and time.time() - self.last_prog > 5:
            self.last_prog = time.time()
            self.out(d["text"])
        elif typ == "phase":
            self.out("== " + d["text"])


class TtyUI(UI):
    COL = {"ok": "32", "warn": "33", "bad": "31", "off": "90", "info": "0"}
    TAG = {"ok": " ok ", "warn": " !! ", "bad": " XX ", "off": " -- "}

    def __init__(self, *a, color=True):
        UI.__init__(self, *a)
        self.color = color
        self.lock = threading.RLock()
        self.rows, self.plan, self.notes, self.recent = {}, [], deque(maxlen=5), deque(maxlen=6)
        self.header, self.now, self.prog, self.phase, self.drawn, self.last = "", "", "", "", 0, 0
        if os.name == "nt":
            os.system("")  # switches the Windows console to ANSI mode

    def c(self, level, text):
        return "\x1b[%sm%s\x1b[0m" % (self.COL[level], text) if self.color else text

    def handle(self, typ, d):
        with self.lock:
            if typ == "header":
                self.header = d["text"]
            elif typ == "phase":
                self.phase = d["text"]
            elif typ == "state":
                self.rows = d["rows"]
            elif typ == "change":
                self.recent.appendleft("+%5.1fs %s: %s" % (time.time() - self.t0, d["label"], d["text"]))
            elif typ == "plan":
                self.plan = d["steps"]
            elif typ == "step":
                for s in self.plan:
                    if s["id"] == d["id"]:
                        s["status"] = d["status"]
            elif typ == "now":
                self.now = d["text"]
            elif typ == "progress":
                self.prog = d["text"]
            elif typ == "msg" and d["level"] in ("warn", "bad", "hint"):
                if d["text"] not in self.notes:
                    self.notes.append(d["text"])
            elif typ == "payload":
                self.notes.append("%s: %s, %s" % (d["name"], d["source"], d["license"]))
            if typ in ("now", "progress") and time.time() - self.last < 0.1:
                return
            self.render()

    def tick(self):
        with self.lock:
            self.render()

    def render(self):
        w = max(40, shutil.get_terminal_size((100, 30)).columns - 1)
        L = [self.c("info", "\x1b[1m" + self.header + "\x1b[0m") if self.color else self.header, self.phase, ""]
        for key, (label, level, text) in self.rows.items():
            L.append(" [%s] %-18s %s" % (self.c(level, self.TAG[level]), label, text))
        if self.plan:
            L.append("")
            for s in self.plan:
                mark = {"done": "done", "now": " >> ", "skip": "skip", "todo": "    "}[s["status"]]
                L.append("  [%s] %s" % (mark, s["label"]))
        if self.now:
            L += ["", " " + self.now]
        if self.prog:
            L.append(" " + self.prog)
        for n in self.notes:
            L.append(self.c("warn", " ! " + n))
        for r in self.recent:
            L.append(self.c("off", "   " + r))
        L = [x if len(re.sub(r"\x1b\[[0-9;]*m", "", x)) <= w else re.sub(r"\x1b\[[0-9;]*m", "", x)[:w] for x in L]
        buf = ("\x1b[%dA" % self.drawn if self.drawn else "") + "".join(x + "\x1b[K\n" for x in L) + "\x1b[J"
        sys.stdout.write(buf)
        sys.stdout.flush()
        self.drawn, self.last = len(L), time.time()

    def ask(self, prompt):
        with self.lock:
            self.drawn = 0  # leave the live view where it is and ask below it
            sys.stdout.write("\n")
        try:
            return input(prompt)
        finally:
            with self.lock:
                self.drawn = 0

    def close(self):
        with self.lock:
            self.render()


# ----------------------------------------------------------------------------------------------- local network parsing
def mask_prefix(mask):
    if mask.lower().startswith("0x"):
        return bin(int(mask, 16)).count("1")
    return ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen


def parse_ipconfig(text):
    out, pending = [], None
    for line in text.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        if not m:
            continue
        if "ipv4" in line.lower():
            pending = m.group(1)
        elif pending and "mask" in line.lower():
            try:
                out.append((pending, mask_prefix(m.group(1))))
            except ValueError:
                pass
            pending = None
    return out


def parse_ip_addr(text):
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", text)]


def parse_ifconfig(text):
    out = []
    for m in re.finditer(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)\b.*?(?:netmask\s+|Mask:)(0x[0-9a-fA-F]+|\d+\.\d+\.\d+\.\d+)", text):
        try:
            out.append((m.group(1), mask_prefix(m.group(2))))
        except ValueError:
            pass
    return out


def parse_arp(text):
    """ip -> upper-case colon MAC from Windows, Linux and macOS 'arp -a' output (macOS drops leading zeros). Broadcast and multicast entries are skipped."""
    out = {}
    for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\D+?((?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})(?![0-9a-fA-F:-])", text):
        mac = ":".join(p.zfill(2) for p in re.split(r"[:-]", m.group(2))).upper()
        if not int(mac[:2], 16) & 1:  # multicast bit set: broadcast and group addresses
            out[m.group(1)] = mac
    return out


def run_cmd(args, timeout=6):
    try:
        return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def normalize_networks(pairs, limit=6):
    """shortcut: a network wider than /24 is cut to the /24 around our address (a /16 scan is 65k hosts); smaller ones are scanned as they are."""
    nets, seen = [], set()
    for ip, pl in pairs:
        a = ipaddress.IPv4Address(ip)
        if a.is_loopback or a.is_link_local or a.is_multicast or pl >= 31:
            continue
        net = ipaddress.IPv4Network("%s/%d" % (ip, max(pl, 24)), strict=False)
        if net not in seen:
            seen.add(net)
            nets.append((net, a))
    return nets[:limit]


def local_networks():
    if sys.platform == "win32":
        pairs = parse_ipconfig(run_cmd(["ipconfig"]))
    else:
        pairs = parse_ip_addr(run_cmd(["ip", "-o", "-4", "addr"])) or parse_ifconfig(run_cmd(["ifconfig"]))
    if not pairs:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # picks the outgoing interface, sends nothing
            pairs = [(s.getsockname()[0], 24)]
        except OSError:
            pass
        finally:
            s.close()
    return normalize_networks(pairs)


# ----------------------------------------------------------------------------------------------- probing
NET_ERRORS = (OSError, hc.HTTPException)


def tcp_open(ip, port, timeout):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def sweep(hosts, ports, timeout=0.4, workers=300):
    jobs = [(h, p) for h in hosts for p in ports]
    out = {}
    with cf.ThreadPoolExecutor(min(workers, max(len(jobs), 1))) as ex:
        for (h, p), ok in zip(jobs, ex.map(lambda j: tcp_open(j[0], j[1], timeout), jobs)):
            if ok:
                out.setdefault(h, set()).add(p)
    dbg("sweep %d hosts x %d ports -> %s" % (len(hosts), len(ports), {h: sorted(v) for h, v in out.items()}))
    return out


def grab(ip, port, send=b"", wait=0.5, maxb=4096):
    """Connect, optionally send, read what arrives until the line goes quiet."""
    data = b""
    try:
        with socket.create_connection((ip, port), 1.5) as s:
            if send:
                s.sendall(send)
            end = time.time() + 3
            while len(data) < maxb and time.time() < end:
                s.settimeout(wait)
                try:
                    b = s.recv(2048)
                except socket.timeout:
                    break
                if not b:
                    break
                data += b
    except OSError:
        pass
    dbg("grab %s:%d sent=%dB got=%dB %r" % (ip, port, len(send), len(data), data[:80]))
    return data


def strip_telnet(b):
    return re.sub(rb"\xff[\xfb-\xfe].|\xff.", b"", b).decode("utf-8", "replace")


def shsrv_ps(ip, port):
    """Read-only process list over the shell payload. Only ps/ls/df/cat may ever be sent; strict 3 s limit."""
    cmd = b"ps"
    assert cmd.split()[0] in (b"ps", b"ls", b"df", b"cat")
    try:
        s = socket.create_connection((ip, port), 1.5)
    except OSError:
        return None
    text, end = b"", time.time() + 3
    try:
        s.settimeout(0.5)
        try:
            text += s.recv(2048)  # banner / first prompt
        except socket.timeout:
            pass
        s.sendall(cmd + b"\r\n")
        while time.time() < end and len(text) < 262144:
            try:
                b = s.recv(8192)
            except socket.timeout:
                if text.count(b"\n") > 1:
                    break
                continue
            if not b:
                break
            text += b
    except OSError:
        pass
    finally:
        s.close()
    names = []
    for line in strip_telnet(text).splitlines():
        parts = re.sub(r"^\S*\$\s+", "", line).split()  # drop a leading prompt
        if len(parts) >= 3 and parts[0].isdigit():
            names.append(parts[-1])
    return names or None


DEBUG = {"on": False, "log": None, "t0": 0.0}


def dbg(text):
    """--debug: one line per network action, to setup.log and to the debug file."""
    if DEBUG["on"] and DEBUG["log"]:
        DEBUG["log"].write("DBG %7.2fs %s" % (time.time() - DEBUG["t0"], text))


def http_call(ip, port, method, path, body=None, headers=None, timeout=6):
    c = hc.HTTPConnection(ip, port, timeout=timeout, blocksize=262144)
    t = time.time()
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        dbg("http %s %s:%d%s -> %d %dB %.0fms %s" % (method, ip, port, path.split("&token")[0][:120], r.status, len(data), (time.time() - t) * 1000, data[:100] if r.status >= 400 else ""))
        return r.status, {k.lower(): v for k, v in r.getheaders()}, data
    except Exception as e:
        dbg("http %s %s:%d%s FAILED %s: %s" % (method, ip, port, path[:120], type(e).__name__, e))
        raise
    finally:
        c.close()


def json_or_none(b):
    try:
        v = json.loads(b.decode("utf-8", "replace"))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def agent_status(ip, port, token):
    """(status dict | None, locked: bool)"""
    try:
        code, _, body = http_call(ip, port, "GET", "/v1/status", headers={"X-OG-Token": token or "-"}, timeout=3)
    except NET_ERRORS:
        return None, False
    if code == 200:
        d = json_or_none(body)
        return (d, False) if d is not None else (None, False)
    return None, code in (401, 403)


def agent_view(a):
    """Flatten GET /v1/status (ogagent.c layout: agent{}, system{}, paths{}, app{}); the flat layout of the contract text is read too."""
    ag, sy, pa, app = (a.get(k) if isinstance(a.get(k), dict) else {} for k in ("agent", "system", "paths", "app"))
    eb = pa.get("eboot_size", app.get("eboot_size"))
    eb = eb if isinstance(eb, int) and eb >= 0 else None
    return {"version": ag.get("version", a.get("version", "?")), "uptime": ag.get("uptime_s", a.get("uptime", "?")), "firmware": sy.get("firmware", a.get("firmware")),
            "eboot_size": eb, "installed": bool(app.get("installed", eb is not None)), "running": bool(app.get("running"))}


def identify(ip, ports, opened, token, ps_names=None, want_ps=False):
    """Fingerprint one host from banners. 'opened' is the set of open port numbers."""
    op = {k: ports[k] in opened for k in ports}
    st = {"open": op, "ftp_banner": "", "ftpsrv": False, "shell": False, "web_other": False, "app": None, "agent": None, "agent_locked": False,
          "procs": None, "procs_src": None, "av": None}
    if op["ftp"]:
        st["ftp_banner"] = grab(ip, ports["ftp"]).decode("latin-1").strip().replace("\r\n", " | ")[:90]
        st["ftpsrv"] = "ftpsrv" in st["ftp_banner"].lower()
    if op["shsrv"]:
        st["shell"] = "$" in strip_telnet(grab(ip, ports["shsrv"], wait=0.4))
    if op["web"]:
        try:
            code, _, body = http_call(ip, ports["web"], "GET", "/api/info", timeout=3)
            d = json_or_none(body) if code == 200 else None
            if d is not None and "install_api" in d:
                st["app"] = d
            else:
                st["web_other"] = True
        except NET_ERRORS:
            pass
    if op["agent"]:
        st["agent"], st["agent_locked"] = agent_status(ip, ports["agent"], token)
    if st["agent"] is not None:
        st["av"] = agent_view(st["agent"])
        st["procs"] = [(p.get("name") or "") + " " + (p.get("title") or "") for p in st["agent"].get("processes", []) if isinstance(p, dict)]
        st["procs_src"] = "agent"
    elif op["shsrv"]:
        names = shsrv_ps(ip, ports["shsrv"]) if want_ps else ps_names
        if names:
            st["procs"], st["procs_src"] = names, "shsrv"
    derive(st)
    return st


def derive(st):
    procs = " ".join(st["procs"] or []).lower()
    st["onion"] = "onion" in procs
    st["smp"] = "shadowmount" in procs or st["open"]["smp_api"]
    st["launched"] = APP_ID.lower() in procs or bool(st["av"] and st["av"]["running"])
    # a copy of the app that is suspended (never reached main): only the console can clear it
    st["stuck"] = any(isinstance(p, dict) and p.get("stopped") and (p.get("title") == APP_ID or p.get("name") == "eboot.bin") for p in ((st["agent"] or {}).get("processes") or []))
    st["loader"] = st["open"]["loader"]
    if "kstuff" in procs:
        st["kstuff"] = "yes"
    elif st["smp"] or st["app"] is not None:
        st["kstuff"] = "inferred"  # ShadowMountPlus needs kstuff-lite, and the app only runs with it
    else:
        st["kstuff"] = "unknown"  # kstuff cannot be read directly


def rows_from(st, ports, lang):
    """Ordered rows: key -> (label, level, text)."""
    lab = lambda k: LABELS[k][lang == "de"]
    r = {}
    r["loader"] = (lab("loader"), "ok" if st["loader"] else "bad", ("open on %d" % ports["loader"]) if st["loader"] else "closed (port %d)" % ports["loader"])
    if st["open"]["ftp"]:
        r["ftp"] = (lab("ftp"), "ok" if st["ftpsrv"] else "warn", st["ftp_banner"] or "open")
    else:
        r["ftp"] = (lab("ftp"), "off", "not running (optional)")
    r["shsrv"] = (lab("shsrv"), "ok" if st["shell"] else "off", "answers on %d" % ports["shsrv"] if st["shell"] else "not running (optional)")
    r["debug"] = (lab("debug"), "ok" if st["open"]["debug"] else "off", "open on %d" % ports["debug"] if st["open"]["debug"] else "not running (optional)")
    a = st["av"]
    if a is not None:
        r["agent"] = (lab("agent"), "ok", "v%s, up %ss" % (a["version"], a["uptime"]))
    elif st["agent_locked"]:
        r["agent"] = (lab("agent"), "bad", "answers, but with an unknown token")
    else:
        r["agent"] = (lab("agent"), "off", "not running")
    if st["app"] is not None:
        r["app"] = (lab("app"), "ok", "answers on %d%s" % (ports["web"], " (busy)" if st["app"].get("busy") else ""))
    elif st["launched"]:
        r["app"] = (lab("app"), "warn", "process started, web server not up yet")
    else:
        r["app"] = (lab("app"), "off", "web server other" if st["web_other"] else "not running")
    vis = st["procs"] is not None
    r["smp"] = (lab("smp"), "ok" if st["smp"] else ("warn" if vis else "off"), "seen" if st["smp"] else ("not in the process list" if vis else "unknown (needs agent or shell)"))
    r["kstuff"] = (lab("kstuff"), {"yes": "ok", "inferred": "ok", "unknown": "warn"}[st["kstuff"]],
                   {"yes": "process seen", "inferred": "inferred (ShadowMountPlus or the app runs)", "unknown": "unknown (cannot be read)"}[st["kstuff"]])
    if st["onion"]:
        r["onion"] = (lab("onion"), "bad", "LOADED: must not be loaded before the app")
    if a is not None and a["firmware"]:
        r["fw"] = (lab("fw"), "ok" if str(a["firmware"]).startswith("13.60") else "warn", str(a["firmware"]))
    return r


class Monitor(threading.Thread):
    """Re-probes the console every interval seconds and reports what changed."""

    def __init__(self, setup):
        threading.Thread.__init__(self, daemon=True)
        self.s, self.state, self.wake, self.stop_ev, self.n, self.rows, self.ps = setup, None, threading.Event(), threading.Event(), 0, {}, None

    def run(self):
        while not self.stop_ev.is_set():
            try:
                self.once()
            except Exception as e:  # a failed probe must never kill the monitor
                self.s.log.write("probe error %r" % (e,))
            self.wake.wait(self.s.args.interval)
            self.wake.clear()

    def once(self):
        s = self.s
        # once the agent answers, the ELF loader is only re-checked now and then (every connect is a, hopefully harmless, empty payload for it)
        quiet = {s.ports["loader"], s.ports["loader2"]} if self.state and self.state["agent"] and self.n % 10 else set()
        opened = sweep([s.ip], [p for p in s.ports.values() if p not in quiet], timeout=0.6, workers=len(s.ports)).get(s.ip, set())
        if quiet and self.state:
            opened |= {s.ports[k] for k in ("loader", "loader2") if self.state["open"][k]}
        st = identify(s.ip, s.ports, opened, s.token, self.ps, want_ps=self.n % 4 == 0)
        self.n += 1
        if st["procs_src"] == "shsrv":
            self.ps = st["procs"]
        st["t"] = time.time()
        if self.stop_ev.is_set():
            return
        rows = rows_from(st, s.ports, s.lang)
        for k, v in rows.items():
            if self.rows.get(k, (0, 0, 0))[1:] != v[1:] and (self.rows or v[1] != "off"):
                s.ui.emit("change", key=k, label=v[0], level=v[1], text=v[2])
        if st["onion"] and not (self.state and self.state["onion"]):
            s.ui.say("onion", level="warn")
        self.rows, self.state = rows, st
        s.ui.emit("state", rows=rows, probe_ms=int((time.time() - st["t"]) * 1000))

    def fresh(self, timeout=8):
        t = time.time()
        self.wake.set()
        while time.time() - t < timeout:
            if self.state and self.state["t"] > t:
                return self.state
            time.sleep(0.05)
        return self.state


# ----------------------------------------------------------------------------------------------- discovery
def ddp_probe(targets, port, wait=1.2):
    """Read-only Remote Play discovery (DDP SRCH). A hint only: ip -> {state, host-type, host-id, ...}."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        for t in targets:
            try:
                s.sendto(DDP_REQ, (t, port))
            except OSError:
                pass
        end = time.time() + wait
        while time.time() < end:
            s.settimeout(max(end - time.time(), 0.05))
            try:
                data, addr = s.recvfrom(2048)
            except (socket.timeout, OSError):
                break
            lines = data.decode("utf-8", "replace").splitlines()
            if not lines or not lines[0].startswith("HTTP/1.1"):
                continue
            h = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:]) if k}
            code = lines[0].split()[1] if len(lines[0].split()) > 1 else ""
            h["state"] = "ready" if code == "200" else "standby" if code == "620" else code
            found[addr[0]] = h
    finally:
        s.close()
    return found


def score(st, mac, ddp):
    s, why = 0, []
    def add(n, text):
        nonlocal s
        s += n
        why.append(text)
    op = st["open"]
    if op["loader"]: add(5, "ELF loader")
    if op["loader2"]: add(2, "loader 9020")
    if st["agent"] is not None or st["agent_locked"]: add(4, "OpenGOAL agent")
    if st["app"] is not None: add(5, "OpenGOAL app")
    if st["ftpsrv"]: add(3, "ftpsrv")
    elif op["ftp"]: add(1, "FTP")
    if st["shell"]: add(3, "shsrv")
    if op["debug"]: add(1, "ps5debug")
    if any(op[k] for k in ETA): add(2, "etaHEN ports")
    if op["smp_api"]: add(1, "ShadowMountPlus API")
    if st["web_other"]: add(1, "web server")
    if mac and mac.replace(":", "")[:6] in SONY_OUI: add(4, "Sony MAC")
    if ddp and "ps5" in (ddp.get("host-type") or "").lower(): add(6, "Remote Play: PS5 %s" % ddp.get("state", ""))
    return s, why


def discover(setup):
    a = setup.args
    nets = [(ipaddress.IPv4Network(n, strict=False), None) for n in a.scan_net] if a.scan_net else local_networks()
    if not nets:
        return []
    names = ", ".join(str(n) for n, _ in nets)
    setup.ui.say("scan", names)
    hosts = [str(h) for n, me in nets for h in n.hosts() if me is None or h != me]
    hits = sweep(hosts, setup.ports.values())
    arp = parse_arp(run_cmd(["arp", "-a"])) if not a.scan_net else {}
    ddp = {}
    if a.ddp_port:
        ddp = ddp_probe(sorted({str(n.broadcast_address) for n, _ in nets}) + ["255.255.255.255"] + list(hits), a.ddp_port)
    cands = []
    for ip in sorted(set(hits) | set(ddp), key=lambda x: tuple(map(int, x.split(".")))):
        st = identify(ip, setup.ports, hits.get(ip, set()), setup.stored_token())
        sc, why = score(st, arp.get(ip), ddp.get(ip))
        if sc >= 3:
            cands.append({"ip": ip, "score": sc, "why": why, "mac": arp.get(ip), "name": (ddp.get(ip) or {}).get("host-name", "")})
    cands.sort(key=lambda c: -c["score"])
    return cands


# ----------------------------------------------------------------------------------------------- agent client
class Agent:
    def __init__(self, ip, port, token):
        self.ip, self.port, self.token = ip, port, token

    def call(self, method, path, query=None, body=None, length=None, timeout=20):
        q = "?" + urllib.parse.urlencode(query or {}, quote_via=urllib.parse.quote) if query else ""
        h = {"X-OG-Token": self.token}
        if isinstance(body, (bytes, bytearray)):
            length = len(body)
        if body is not None:
            h["Content-Length"] = str(length)
            h["Content-Type"] = "application/octet-stream"
        return http_call(self.ip, self.port, method, path + q, body=body, headers=h, timeout=timeout)

    def ok(self, method, path, query=None, body=None, length=None, accept=(), timeout=20):
        code, _, data = self.call(method, path, query, body, length, timeout)
        if not (200 <= code < 300 or code in accept):
            raise Fail("%s %s -> HTTP %d %s" % (method, path, code, data[:120].decode("utf-8", "replace")))
        return code, data

    def get_file(self, path):
        code, _, data = self.call("GET", "/v1/file", {"path": path})
        return data if code == 200 else None

    def put_file(self, path, src, size, mode):
        self.ok("PUT", "/v1/file", {"path": path, "size": size, "mode": mode}, src, size, timeout=120)

    def launch(self):
        """(accepted, launch code): the agent answers 500 with the code when the console refuses."""
        code, _, data = self.call("POST", "/v1/launch", {"title": APP_ID})
        j = json_or_none(data) or {}
        lc = j.get("launch", 0)
        return code == 200 or 0 < lc < 0x80000000, lc  # an older agent reports the new app id as a refusal

    def kill(self):
        self.ok("POST", "/v1/kill", {"title": APP_ID})

    def shutdown(self):
        try:
            self.call("POST", "/v1/shutdown", timeout=5)
        except NET_ERRORS:
            pass


class CountingFile:
    def __init__(self, path, cb):
        self.f, self.cb, self.n = open(path, "rb"), cb, 0

    def read(self, n=-1):
        b = self.f.read(n)
        self.n += len(b)
        self.cb(len(b))
        return b

    def close(self):
        self.f.close()


# ----------------------------------------------------------------------------------------------- plan
AGENT_MIN_VERSION = 2  # 2: makes the /data/opengoal folders writable for the app (#5)


def agent_too_old(st):
    if not st.get("av"):
        return False
    v = st["av"].get("version")
    return st["agent"] is not None and not st.get("agent_locked") and not (str(v).isdigit() and int(v) >= AGENT_MIN_VERSION)


def make_plan(st, o, done):
    """Missing steps as a pure function of the live state, the options and the steps already run in this session."""
    if st["app"] is not None and not o.update and (update_state(st, o) != "update" or "upload" in done):
        return []
    steps = []
    if o.no_agent:
        if not st["loader"] and not st["open"]["ftp"]: steps.append("loader")
        for s in ("ftpsrv", "ftp_install"):
            if s not in done and not (s == "ftpsrv" and st["open"]["ftp"]): steps.append(s)
        return steps
    if st["agent"] is None or (agent_too_old(st) and "agent" not in done):
        if not st["loader"]: steps.append("loader")
        if "agent" not in done: steps.append("agent")
    visible = st["procs"] is not None
    if not (visible and st["smp"]) and "smp" not in done:
        if o.with_kstuff is True and st["kstuff"] == "unknown" and not st["onion"] and "kstuff" not in done:
            steps.append("kstuff")  # documented order: kstuff before ShadowMountPlus
        steps.append("smp")
    for s in ("upload", "launch"):
        if s not in done: steps.append(s)
    return steps


# ----------------------------------------------------------------------------------------------- setup run
class Setup:
    def __init__(self, args, ui, log, table):
        self.args, self.ui, self.log, self.table = args, ui, log, table
        self.lang = ui.lang
        self.ports = dict(PORTS)
        for kv in filter(None, (args.ports or "").split(",")):
            k, _, v = kv.partition("=")
            self.ports[k] = int(v)
        self.ip, self.token, self.done, self.mon, self.agent = args.ip, None, set(), None, None
        self.t_start = time.time()

    # ---- config and token files
    def cfg_path(self):
        return os.path.join(home(), "config.json")

    def load_cfg(self):
        try:
            with open(self.cfg_path()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_ip(self, ip):
        c = self.load_cfg()
        c["ps5"] = ip
        try:
            os.makedirs(home(), exist_ok=True)
            with open(self.cfg_path(), "w") as f:
                json.dump(c, f)
        except OSError:
            pass

    def token_path(self):
        return os.path.join(home(), "agent.token")

    def stored_token(self):
        try:
            with open(self.token_path()) as f:
                return f.read().strip() or None
        except OSError:
            return None

    # ---- waiting
    def wait_for(self, pred, what, timeout, hint=None, soft=False):
        """Poll the live state until pred(state). After timeout seconds tell the user once what to do on the console and keep waiting.
        soft: return False at the timeout instead of waiting on. Gives up after --max-wait seconds (exit 3)."""
        t0, hinted, shown = time.time(), False, -1
        self.ui.emit("now", text=what, first=True)
        self.mon.wake.set()
        while True:
            st = self.mon.state
            if st and pred(st):
                self.ui.emit("now", text="")
                return True
            el = time.time() - t0
            if el > timeout and soft:
                self.ui.emit("now", text="")
                return False
            if el > timeout and not hinted and hint:
                hinted = True
                self.ui.emit("msg", level="hint", key=hint[0], text=self.ui.tr(*hint))
            if el > self.args.max_wait:
                raise Fail(self.ui.tr("giveup", int(el), what), 3)
            if int(el) != shown:
                shown = int(el)
                self.ui.emit("now", text="%s  %ds" % (what, el))
            time.sleep(0.15)

    # ---- payloads
    def fetch_payload(self, key):
        p = self.table[key]
        self.ui.emit("payload", name=p["name"], source=p["source"], license=p["license"], sha256=p["sha256"], size=p["size"])
        cache = os.path.join(home(), "payloads", "%s-%s.elf" % (key, p["sha256"][:12]))
        if os.path.isfile(cache) and os.path.getsize(cache) == p["size"] and sha256_file(cache) == p["sha256"]:
            return read_bytes(cache)
        tmp = tempfile.mkdtemp(prefix="ogps5-")  # private (0700) scratch directory
        try:
            dst, h, n = os.path.join(tmp, "dl.bin"), hashlib.sha256(), 0
            try:
                req = urllib.request.Request(p["url"], headers={"User-Agent": "opengoal-ps5-setup"})
                with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
                    for chunk in iter(lambda: r.read(1 << 16), b""):
                        n += len(chunk)
                        if n > p["size"]:
                            break
                        h.update(chunk)
                        f.write(chunk)
            except (OSError, hc.HTTPException) as e:
                raise Fail("download of %s failed: %s" % (p["name"], e))
            if n != p["size"] or h.hexdigest() != p["sha256"]:
                raise Fail(self.ui.tr("hash_bad", p["name"]))
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            shutil.move(dst, cache)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return read_bytes(cache)

    def send_elf(self, data, what):
        err = None
        for attempt in range(3):
            try:
                with socket.create_connection((self.ip, self.ports["loader"]), 6) as s:
                    s.sendall(data)
                    s.shutdown(socket.SHUT_WR)
                    s.settimeout(5)
                    try:
                        while s.recv(4096):
                            pass
                    except OSError:
                        pass
                self.ui.emit("sent", what=what, bytes=len(data))
                self.mon.wake.set()
                return
            except OSError as e:
                err = e
                time.sleep(1.5 * (attempt + 1))
        raise Fail("could not send %s to the loader: %s" % (what, err))

    def find(self, names, subdirs=("payloads", "tools", "")):
        here = os.path.dirname(os.path.abspath(__file__))
        for base in (here, os.path.dirname(here)):
            for sd in subdirs:
                for n in names:
                    p = os.path.join(base, sd, n)
                    if os.path.isfile(p):
                        return p
        return None

    # ---- steps
    def step_loader(self):
        self.wait_for(lambda s: s["loader"] or s["agent"] is not None, self.ui.tr("w_loader", self.ports["loader"]), 6, ("w_loader", self.ports["loader"]))

    def step_agent(self):
        elf_path = self.args.agent_elf or self.find(["ogagent.elf"])
        if not elf_path or not os.path.isfile(elf_path):
            raise Fail(self.ui.tr("no_elf"))
        self.token = secrets.token_hex(TOKEN_LEN // 2)
        Log.secrets.append(self.token)
        elf = patch_token(read_bytes(elf_path), self.token)
        os.makedirs(home(), exist_ok=True)
        fd = os.open(self.token_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self.token)  # kept so a killed run can resume with the agent still running
        if self.agent and agent_too_old(self.mon.fresh()):
            self.agent.shutdown()  # an older agent still holds the port
            self.wait_for(lambda s: s["agent"] is None, "old agent to exit", 10, soft=True)
        if self.agent:
            self.agent.token = self.token
        self.send_elf(elf, "ogagent.elf")
        self.wait_for(lambda s: s["agent"] is not None, "agent on port %d" % self.ports["agent"], 25, ("w_agent", self.ports["agent"]))

    def step_kstuff(self):
        self.send_elf(self.fetch_payload("kstuff"), "kstuff-lite")
        self.settle("kstuff-lite")

    def settle(self, what):
        """kstuff has no port to wait for: documented settle time, and the loader must stay up (a crash would close it)."""
        t0 = time.time()
        while time.time() - t0 < self.args.settle:
            self.ui.emit("now", text="%s: settling %ds / %ds" % (what, time.time() - t0, self.args.settle))
            time.sleep(0.5)
        self.ui.emit("now", text="")

    def step_smp(self):
        self.send_elf(self.fetch_payload("smp"), "ShadowMountPlus")
        if not self.wait_for(lambda s: s["smp"], "ShadowMountPlus in the process list", 60, soft=True):
            self.ui.say("w_smp", level="warn")

    def step_ftpsrv(self):
        self.send_elf(self.fetch_payload("ftpsrv"), "ftpsrv")
        self.wait_for(lambda s: s["open"]["ftp"], "FTP on port %d" % self.ports["ftp"], 20)

    def step_ftp_install(self):
        script = self.find(["install.py"], ("", "release_template"))
        if not script:
            raise Fail("install.py not found next to this script")
        cmd = [sys.executable, script, "--ip", self.ip, "--lang", self.lang, "--ftp-port", str(self.ports["ftp"]), "--loader-port", str(self.ports["loader"]),
               "--app", self.app_dir()]
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise Fail("install.py failed")
        self.ui.say("noagent_done")
        self.final = True

    def app_dir(self):
        if getattr(self, "_app", None):
            return self._app
        here = os.path.dirname(os.path.abspath(__file__))
        cands = [self.args.app] if self.args.app else [os.path.join(here, "app", APP_ID), os.path.join(here, APP_ID), os.path.join(home(), "release", "app", APP_ID), os.path.join(home(), "release", "OpenGOAL-PS5", "app", APP_ID),
                                                       os.path.join(os.path.dirname(here), "release", "OpenGOAL-PS5", "app", APP_ID)]
        for c in cands:
            if c and os.path.isfile(os.path.join(c, "eboot.bin")):
                self._app = c
                return c
        if self.args.app:
            raise Fail(self.ui.tr("no_app", self.args.app))
        self._app = fetch_release(self, os.environ.get("OGPS5_BASE", RELEASE_BASE))
        return self._app

    def step_upload(self):
        ag = self.agent
        app = self.app_dir()
        st = self.mon.fresh()
        a = st["av"] or {}
        files = local_tree(app)
        raw = ag.get_file(REMOTE_APP + "/" + MANIFEST)
        remote = (json_or_none(raw) or {}).get("files", {}) if raw else {}
        if not a.get("installed"):
            for k in LAST:  # these two gate "installed": never trust them from an interrupted run
                remote.pop(k, None)
        eboot_size = next(s for _, rel, s in files if rel == "eboot.bin")
        todo = []
        for path, rel, size in files:
            m = remote.get(rel)
            if m and m.get("size") == size and m.get("mode") == file_mode(rel) and m.get("sha256") == sha256_file(path) and not (rel == "eboot.bin" and a.get("eboot_size") not in (None, size)):
                continue
            todo.append((path, rel, size))
        fresh_install = not a.get("installed") or any(r == "eboot.bin" for _, r, _ in todo)
        restart = fresh_install or update_state(st, self.args) == "update"  # a new version always restarts the app, also when only assets changed
        if not todo:
            self.ui.emit("progress", text="app files already match (%d files)" % len(files), force=True)
        else:
            if (st["launched"] or st["app"] is not None) and restart:
                ag.kill()
                self.wait_for(lambda s: not s["launched"] and s["app"] is None, "app to close", 20, soft=True)
            self.upload_files(ag, todo, files, remote)
        self.ensure_cfg(ag)
        if fresh_install:
            scan = self.args.scan_elf or self.find(["scan.elf"])
            if scan and os.path.isfile(scan) and (self.mon.state["loader"]):
                self.send_elf(read_bytes(scan), "scan.elf")  # asks ShadowMountPlus for an immediate scan
                time.sleep(min(2.0, self.args.settle))

    def upload_files(self, ag, todo, files, remote):
        total = sum(s for _, _, s in todo)
        prog = {"bytes": 0, "files": 0, "t0": time.time(), "last": 0}
        lock = threading.Lock()
        have = dict(remote)  # rel -> manifest entry, flushed to the console as a resume point
        for _, r, _ in todo:
            have.pop(r, None)
        # no mkdir calls: PUT /v1/file creates missing parent folders itself (ogagent.c h_put)

        def report(force=False):
            now = time.time()
            if not force and now - prog["last"] < 0.25:
                return
            prog["last"] = now
            el = max(now - prog["t0"], 0.001)
            sp = prog["bytes"] / el
            eta = int((total - prog["bytes"]) / sp) if sp > 0 else 0
            self.ui.emit("progress", force=force, files=prog["files"], files_total=len(todo), bytes=prog["bytes"], total=total, speed=int(sp), eta=eta,
                         text="upload %d/%d files  %s / %s  %s/s  %ds left" % (prog["files"], len(todo), fmt_mb(prog["bytes"]), fmt_mb(total), fmt_mb(sp), eta))

        def count(n):
            with lock:
                prog["bytes"] += n
                report()

        def flush_manifest():
            data = json.dumps({"version": 1, "files": dict(have)}, sort_keys=True).encode()
            ag.ok("PUT", "/v1/file", {"path": REMOTE_APP + "/" + MANIFEST, "size": len(data), "mode": "0644"}, data)

        def send(item):
            path, rel, size = item
            mode = file_mode(rel)
            digest = sha256_file(path)
            for attempt in range(3):
                src = CountingFile(path, count)
                try:
                    ag.put_file(REMOTE_APP + "/" + rel, src, size, mode)
                    break
                except (NET_ERRORS, Fail) as e:
                    count(-src.n)
                    if attempt == 2:
                        raise Fail(self.ui.tr("up_fail", "%s (%s)" % (rel, e)))
                    time.sleep(1 + attempt)
                finally:
                    src.close()
            with lock:
                have[rel] = {"size": size, "sha256": digest, "mode": mode}
                prog["files"] += 1
                if prog["files"] % self.args.flush == 0:
                    flush_manifest()
                report()

        first = sorted([t for t in todo if os.path.basename(t[1]) not in LAST], key=lambda t: -t[2])
        last = sorted([t for t in todo if os.path.basename(t[1]) in LAST], key=lambda t: LAST.index(os.path.basename(t[1])))
        with cf.ThreadPoolExecutor(4) as ex:
            for f in [ex.submit(send, t) for t in first]:
                f.result()
        flush_manifest()
        for t in last:
            send(t)
        for _, rel, size in files:
            have.setdefault(rel, {"size": size, "sha256": sha256_file(os.path.join(self.app_dir(), *rel.split("/"))), "mode": file_mode(rel)})
        flush_manifest()
        report(True)
        st = self.mon.fresh()
        es = (st["av"] or {}).get("eboot_size")
        eb = next(s for _, r, s in files if r == "eboot.bin")
        if es is not None and es != eb:
            raise Fail(self.ui.tr("up_fail", "eboot.bin has %s bytes on the console, expected %d" % (es, eb)))

    def ensure_cfg(self, ag):
        # every run: the agent (v2) creates these and makes them 0777, also folders an older setup made 0755;
        # the app runs as another user and cannot create them itself under a 0755 /data/opengoal (#5)
        bad = []
        for d in ["log"] + ["config/OpenGOAL/" + g for g in ("jak1", "jak2", "jak3")] + ["jak1", "jak2", "jak3"]:
            _, data = ag.ok("POST", "/v1/mkdir", {"path": "/data/opengoal/" + d})
            mode = (json_or_none(data) or {}).get("mode")
            if isinstance(mode, int) and mode >= 0 and mode & 0o777 != 0o777:  # double check: an agent that cannot chmod
                bad.append("/data/opengoal/%s (%o)" % (d, mode))
        if bad:
            raise Fail("the app cannot write these folders: %s. Set them to 777 over FTP and run the setup again." % ", ".join(bad))
        if ag.get_file(REMOTE_CFG) is not None:
            return
        data = ("resolution=0\nrefresh=60\nlast_game=0\nlang=%d\n" % (1 if self.lang == "de" else 0)).encode()
        ag.ok("PUT", "/v1/file", {"path": REMOTE_CFG, "size": len(data), "mode": "0666"}, data)
        self.ui.emit("progress", text="created %s" % REMOTE_CFG, force=True)

    def step_launch(self):
        ag = self.agent
        if self.mon.fresh()["stuck"]:
            raise Fail(self.ui.tr("stuck"))
        for rnd in range(2):
            if not (self.mon.state["launched"] or self.mon.state["app"] is not None):
                ok, rc = ag.launch()
                if not ok:
                    self.ui.emit("msg", level="warn", key="launch_rc", text=self.ui.tr("launch_rc", rc & 0xFFFFFFFF))
                    if rc & 0xFFFFFFFF == 0x80020008:
                        self.ui.say("onion", level="warn")
            ok = self.wait_for(lambda s: s["app"] is not None or s["stuck"], self.ui.tr("w_app"), self.args.launch_timeout * (1 if rnd == 0 else 0.66), soft=True)
            st = self.mon.fresh()
            if st["stuck"]:
                raise Fail(self.ui.tr("stuck"))
            if ok:
                return
            if rnd == 0 and "kstuff" not in self.done and not st["onion"] and st["kstuff"] != "yes":
                if self.consent_kstuff():
                    self.step_kstuff()
                    self.done.add("kstuff")
                    continue
                self.ui.say("no_kstuff", level="warn")
        raise Fail(self.ui.tr("launch_fail", self.ui.tr("w_app")))

    def consent_kstuff(self):
        a = self.args
        if a.with_kstuff is not None:
            return bool(a.with_kstuff)
        if a.yes or a.json or not sys.stdin.isatty():
            return False
        try:
            ans = self.ui.ask(self.ui.tr("ask_kstuff")).strip().lower()
        except EOFError:
            return False
        return ans[:1] in ("y", "j")

    # ---- phases
    def find_console(self):
        a = self.args
        if a.ip:
            return a.ip
        self.ui.emit("phase", text="1/5 discover")
        mem = self.load_cfg().get("ps5") or os.environ.get("PS5_IP")
        if mem and not a.scan_net:
            hit = sweep([mem], self.ports.values(), timeout=0.8).get(mem)
            if hit:
                self.ui.say("remembered", mem)
                return mem
        cands = [] if a.no_scan else discover(self)
        for c in cands:
            self.ui.emit("candidate", **c)
        interactive = not (a.yes or a.json) and sys.stdin.isatty()
        if len(cands) == 1:
            self.ui.say("found", "%s (%s)" % (cands[0]["ip"], ", ".join(cands[0]["why"])))
            return cands[0]["ip"]
        if len(cands) > 1:
            if not interactive:
                if cands[0]["score"] > cands[1]["score"]:
                    return cands[0]["ip"]
                raise Fail(self.ui.tr("ambiguous"), 2)
            for i, c in enumerate(cands, 1):
                print("  %d) %s  %s  (%s)" % (i, c["ip"], c["name"], ", ".join(c["why"])))
            pick = self.ui.ask(self.ui.tr("pick")).strip()
            return cands[int(pick) - 1]["ip"] if pick.isdigit() and 1 <= int(pick) <= len(cands) else pick
        if mem and a.no_scan:
            return mem
        if interactive:
            typed = self.ui.ask(self.ui.tr("ask_ip")).strip()
            if typed:
                return typed
        raise Fail(self.ui.tr("none"), 2)

    def run(self):
        ui, a = self.ui, self.args
        ui.emit("header", text="%s   %s" % (ui.tr("title"), "(dry run)" if a.dry_run else ""))
        if a.dry_run:
            ui.say("dry")
        self.final = False
        self.ip = self.find_console()
        try:
            ipaddress.IPv4Address(self.ip)
        except ValueError:
            raise Fail("'%s' is not an IPv4 address" % self.ip, 2)
        self.token = self.stored_token()
        if self.token:
            Log.secrets.append(self.token)
        ui.emit("header", text="%s   %s%s" % (ui.tr("title"), self.ip, "   (dry run)" if a.dry_run else ""))
        ui.emit("phase", text="2/5 map the console state")
        self.mon = Monitor(self)
        self.mon.start()
        try:
            return self.drive()
        finally:
            self.mon.stop_ev.set()
            self.mon.wake.set()
            self.mon.join(5)

    def drive(self):
        ui, a = self.ui, self.args
        st = self.mon.fresh(15)
        if not a.no_agent:
            self.agent = Agent(self.ip, self.ports["agent"], self.token or "-")
        step_fn = {"loader": self.step_loader, "agent": self.step_agent, "kstuff": self.step_kstuff, "smp": self.step_smp, "upload": self.step_upload,
                   "launch": self.step_launch, "ftpsrv": self.step_ftpsrv, "ftp_install": self.step_ftp_install}
        planned = False
        a.target = local_version(getattr(a, "version_file", None))
        late = latest_version() if a.target else None
        if late and vkey(late) > vkey(a.target):
            ui.say("update_avail", late, a.target, level="warn")
        while True:
            st = self.mon.fresh()
            if st["agent_locked"] and st["agent"] is None:
                raise Fail(ui.tr("locked", self.ports["agent"]), 1)
            if (st["procs"] is not None and not st["smp"] and "kstuff" not in self.done and a.with_kstuff is None and st["kstuff"] == "unknown"
                    and not st["onion"] and not a.no_agent and "smp" not in self.done and not a.dry_run):
                a.with_kstuff = True if self.consent_kstuff() else False
                if a.with_kstuff is False:
                    ui.say("no_kstuff", level="warn")
            plan = make_plan(st, a, self.done)
            shown = [{"id": s, "label": STEP_LABELS[s][self.lang == "de"], "status": "todo"} for s in plan]
            if not planned:
                planned = True
                ui.emit("phase", text="3/5 plan")
                ui.emit("plan", steps=shown)
                us = update_state(st, a)
                if us == "update" and plan:
                    ui.say("updating", (st["app"].get("app") or ui.tr("update_unknown")), a.target)
                if not plan:
                    ws = "%s:%d" % (self.ip, self.ports["web"])
                    if us == "current":
                        ui.say("uptodate", a.target, ws)
                    elif us == "newer":
                        ui.say("newer_here", st["app"].get("app"), a.target, level="warn")
                    elif us == "busy":
                        ui.say("busy_update", level="warn")
                    else:
                        ui.say("idle", ws)
                    self.save_ip(self.ip)
                    ui.emit("done", url="http://%s:%d" % (self.ip, self.ports["web"]), changed=False)
                    return 0
                if a.dry_run:
                    return 0
                ui.emit("phase", text="4/5 install")
                self.preflight(plan)
            else:
                ui.emit("plan", steps=shown)
            if not plan:
                break
            sid = plan[0]
            ui.emit("step", id=sid, status="now")
            step_fn[sid]()
            if sid != "loader":
                self.done.add(sid)
            ui.emit("step", id=sid, status="done")
            if self.final:
                return 0
        return self.finish()

    def preflight(self, plan):
        """Everything that can be checked without touching the console, before the first byte is sent."""
        if "agent" in plan and not (self.args.agent_elf or self.find(["ogagent.elf"])):
            raise Fail(self.ui.tr("no_elf"))
        if "agent" in plan:
            patch_token(read_bytes(self.args.agent_elf or self.find(["ogagent.elf"])), "0" * TOKEN_LEN)
        if "upload" in plan or "ftp_install" in plan:
            self.app_dir()
        for key in ("kstuff", "smp", "ftpsrv"):
            if key in plan:
                self.fetch_payload(key)  # verified and cached now: a hash mismatch stops before anything is sent
        if self.mon.state["onion"]:
            self.ui.say("onion", level="warn")

    def finish(self):
        ui = self.ui
        st = self.mon.fresh()
        if st["app"] is None:
            raise Fail(ui.tr("launch_fail", ""))
        self.save_ip(self.ip)
        url = "http://%s:%d" % (self.ip, self.ports["web"])
        stale = sorted(g for g, f in (st["app"].get("formats") or {}).items() if isinstance(f, int) and f < DATA_FORMAT)
        if stale:
            ui.say("reimport", ", ".join(stale), level="warn")
        if st["agent"] is not None and self.agent:
            self.agent.shutdown()
            self.wait_for(lambda s: s["agent"] is None, "agent to stop", 10, soft=True)
        try:
            os.remove(self.token_path())
        except OSError:
            pass
        ui.say("done", "%s:%d" % (self.ip, self.ports["web"]))
        gui = self.find(["OpenGOAL-PS5-gui.py"], ("gui", "installer/gui"))
        one = "python \"%s\"" % gui if gui else "irm %s/bootstrap.ps1 | iex   (Windows)   or   curl -fsSL %s/bootstrap.sh | bash" % (RELEASE_BASE, RELEASE_BASE)
        ui.say("next", one)
        ui.emit("done", url=url, changed=True, import_cmd=one)
        if gui and not (self.args.yes or self.args.json) and sys.stdin.isatty():
            try:
                if self.ui.ask(ui.tr("ask_import")).strip().lower()[:1] in ("y", "j"):
                    subprocess.Popen([sys.executable, gui])
            except EOFError:
                pass
        return 0


def local_tree(app):
    out = []
    for d, _, fs in os.walk(app):
        for f in fs:
            p = os.path.join(d, f)
            rel = os.path.relpath(p, app).replace(os.sep, "/")
            if rel != MANIFEST:
                out.append((p, rel, os.path.getsize(p)))
    return sorted(out, key=lambda t: t[1])


def fetch_release(setup, base):
    """No app folder next to the script (the one-liner only unpacks the GUI): fetch OpenGOAL-PS5.zip from the release, check it against SHA256SUMS."""
    dest = os.path.join(home(), "release")
    tmp = tempfile.mkdtemp(prefix="ogps5-")
    try:
        try:
            sums = urllib.request.urlopen(base + "/SHA256SUMS", timeout=30).read().decode()
            m = re.search(r"^([0-9a-fA-F]{64})\s+\*?OpenGOAL-PS5\.zip\s*$", sums, re.M)
            if not m:
                raise Fail(setup.ui.tr("no_app", "SHA256SUMS has no OpenGOAL-PS5.zip"))
            z, h = os.path.join(tmp, "release.zip"), hashlib.sha256()
            with urllib.request.urlopen(base + "/OpenGOAL-PS5.zip", timeout=60) as r, open(z, "wb") as f:
                for c in iter(lambda: r.read(1 << 20), b""):
                    h.update(c)
                    f.write(c)
        except (OSError, hc.HTTPException) as e:
            raise Fail(setup.ui.tr("no_app", e))
        if h.hexdigest() != m.group(1).lower():
            raise Fail(setup.ui.tr("hash_bad", "OpenGOAL-PS5.zip"))
        shutil.rmtree(dest, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():  # refuse path escapes
                if os.path.isabs(name) or ".." in name.split("/"):
                    raise Fail("unsafe path in the release zip")
            zf.extractall(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for sub in ("", "OpenGOAL-PS5"):  # make_release.sh zips with the folder name, make_release.ps1 without
        c = os.path.join(dest, sub, "app", APP_ID)
        if os.path.isfile(os.path.join(c, "eboot.bin")):
            return c
    raise Fail(setup.ui.tr("no_app", "no app folder inside OpenGOAL-PS5.zip"))


# ----------------------------------------------------------------------------------------------- entry
def parse_args(argv):
    ap = argparse.ArgumentParser(description="Set up a jailbroken PS5 for OpenGOAL-PS5 (find it, install what is missing, start the app).")
    ap.add_argument("--ip", help="console address (skips the network search)")
    ap.add_argument("--no-scan", action="store_true", help="do not search the network (use --ip or the remembered address)")
    ap.add_argument("--with-kstuff", action="store_true", default=None, help="allow loading kstuff-lite when it is needed")
    ap.add_argument("--update", action="store_true", help="re-check and re-send app files even when the app already runs")
    ap.add_argument("--yes", "-y", action="store_true", help="never ask (kstuff still needs --with-kstuff)")
    ap.add_argument("--dry-run", action="store_true", help="probe and show the plan, send nothing")
    ap.add_argument("--lang", choices=("en", "de"))
    ap.add_argument("--json", action="store_true", help="print JSON events, one per line (implies --yes)")
    ap.add_argument("--app", help="the LAPY77001 folder (default: next to this script, else fetched from the release)")
    ap.add_argument("--agent-elf", help="path of ogagent.elf (default: payloads/ogagent.elf next to this script)")
    ap.add_argument("--no-agent", action="store_true", help="fallback: ftpsrv + install.py instead of the agent")
    ap.add_argument("--max-wait", type=float, default=900, help="seconds to wait for the console in one step before giving up (default 900)")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--debug", action="store_true", help="log every probe and request with timings (setup.log in the data folder, copy in ./ps5_setup_debug.log)")
    for h in ("--interval", "--settle"):
        ap.add_argument(h, type=float, default=1.5 if h == "--interval" else 20.0, help=argparse.SUPPRESS)
    ap.add_argument("--flush", type=int, default=25, help=argparse.SUPPRESS)
    ap.add_argument("--launch-timeout", type=float, default=45, help=argparse.SUPPRESS)
    ap.add_argument("--ports", help=argparse.SUPPRESS)
    ap.add_argument("--scan-net", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--ddp-port", type=int, default=DDP_PORT, help=argparse.SUPPRESS)
    ap.add_argument("--payload-table", help=argparse.SUPPRESS)
    ap.add_argument("--scan-elf", help=argparse.SUPPRESS)
    ap.add_argument("--version-file", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.json:
        a.yes = True
    return a


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    lang = a.lang or system_lang()
    log, t0 = Log(), time.time()
    if a.debug:
        DEBUG.update(on=True, log=log, t0=t0)
        dbg("args %s" % {k: v for k, v in vars(a).items() if k != "token"})
    if a.json:
        ui = JsonUI(lang, log, t0)
    elif sys.stdout.isatty():
        ui = TtyUI(lang, log, t0, color=not (a.no_color or os.environ.get("NO_COLOR")))
    else:
        ui = LineUI(lang, log, t0)
    table = PAYLOADS
    if a.payload_table:
        with open(a.payload_table) as f:
            table = {k: dict(PAYLOADS[k], **v) for k, v in json.load(f).items()}
    setup = Setup(a, ui, log, table)
    try:
        return setup.run()
    except Fail as e:
        ui.emit("error", text=str(e), code=e.code)
        if not a.json:
            ui.close()
            print("\nERROR: %s" % e, file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        ui.emit("error", text="interrupted", code=130)
        return 130
    finally:
        ui.close()
        log.close()
        if a.debug:
            try:
                import shutil
                shutil.copyfile(os.path.join(home(), "setup.log"), "ps5_setup_debug.log")
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
