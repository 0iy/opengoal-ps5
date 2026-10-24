#!/usr/bin/env python3
"""OpenGOAL-PS5 installer (Python 3 stdlib only; Windows, Linux, macOS).

Uploads the app to the PS5 over FTP (port 2121), writes default config, verifies sizes, optionally sends
payload ELFs to the loader (port 9021). Safe to re-run: files with matching size are skipped (eboot.bin and
param.json are always re-sent). Use --dry-run to see what would happen without writing anything.
"""
import argparse, ftplib, os, socket, sys
from concurrent.futures import ThreadPoolExecutor

APP_ID = "LAPY77001"
REMOTE_APP = "/data/homebrew/" + APP_ID
REMOTE_CFG = "/data/opengoal/config"
ALWAYS = ("eboot.bin", "param.json")  # same size does not prove same content

T = {
 "en": {
  "hello": "OpenGOAL-PS5 installer",
  "dry": "DRY RUN: nothing will be written to the console.",
  "ask_ip": "PS5 IP address (empty = search the network): ",
  "scan": "Searching your network for a PS5 (ports 9021/2121)...",
  "found": "Found: {}",
  "pick": "Which one? Number or IP: ",
  "none": "Nothing found. Type the IP shown in the PS5 network settings.",
  "svc_ok": "  [ok]   {} (port {})",
  "svc_no": "  [MISSING] {} (port {})",
  "step_loader": "Start the jailbreak exploit on the PS5 until the ELF loader listens on port 9021, then run this again.",
  "step_ftp": "Send 'ftpsrv-ps5.elf' to port 9021 (after kstuff-lite). Wait 5 seconds, then run this again.",
  "boot_order": "Boot order: exploit + ELF loader (9021) -> kstuff-lite -> ftpsrv (2121) -> ShadowMountPlus -> shsrv (2323).\nNever load OnionHEN before launching the app: the app would be refused.",
  "no_ftp_abort": "Cannot upload without FTP. Fix the step above and run the installer again.",
  "no_app": "App folder not found. Expected '{}' next to this script (with eboot.bin, sce_sys, assets).",
  "no_eboot": "eboot.bin is missing in {}. The download looks incomplete.",
  "upload": "Uploading {} files ({:.1f} MB) to {}",
  "skip": "  = {} (already there)",
  "sent": "  > {}  {}",
  "would": "  would send {}",
  "cfg_have": "Config {} already exists, left unchanged.",
  "cfg_new": "Created default config {}",
  "verify": "Verifying sizes on the console...",
  "verify_ok": "All {} files match.",
  "verify_bad": "{} file(s) differ or are missing: run the installer again.",
  "ask_payload": "Payload ELF to send to port 9021 (path, empty = done): ",
  "pl_onion": "Refused: OnionHEN must not be loaded before the app is launched.",
  "pl_sent": "Sent {} ({} bytes) to the loader.",
  "pl_missing": "File not found: {}",
  "done": "Done.",
  "next": "Next steps:\n  1. Make sure ShadowMountPlus is running (it mounts the app).\n  2. Start 'OpenGOAL-PS5' from the PS5 home screen.\n  3. The app shows a QR code. On your phone or PC open  http://{}:8080  and send your own game images (.iso).\n  Re-running this installer later is safe.",
  "ftp_err": "FTP error: {}",
  "bad_ip": "'{}' is not a valid IP address.",
 },
 "de": {
  "hello": "OpenGOAL-PS5 Installer",
  "dry": "TESTLAUF: Es wird nichts auf die Konsole geschrieben.",
  "ask_ip": "IP-Adresse der PS5 (leer = Netzwerk durchsuchen): ",
  "scan": "Suche im Netzwerk nach einer PS5 (Ports 9021/2121)...",
  "found": "Gefunden: {}",
  "pick": "Welche? Nummer oder IP: ",
  "none": "Nichts gefunden. Gib die IP aus den PS5-Netzwerkeinstellungen ein.",
  "svc_ok": "  [ok]      {} (Port {})",
  "svc_no": "  [FEHLT]   {} (Port {})",
  "step_loader": "Starte auf der PS5 den Jailbreak-Exploit, bis der ELF-Loader auf Port 9021 lauscht, und starte dieses Programm dann erneut.",
  "step_ftp": "Sende 'ftpsrv-ps5.elf' an Port 9021 (nach kstuff-lite). 5 Sekunden warten, dann dieses Programm erneut starten.",
  "boot_order": "Reihenfolge: Exploit + ELF-Loader (9021) -> kstuff-lite -> ftpsrv (2121) -> ShadowMountPlus -> shsrv (2323).\nOnionHEN niemals vor dem Start der App laden: die App wuerde abgelehnt.",
  "no_ftp_abort": "Ohne FTP kein Upload. Erledige den Schritt oben und starte den Installer neu.",
  "no_app": "App-Ordner nicht gefunden. Erwartet: '{}' neben diesem Skript (mit eboot.bin, sce_sys, assets).",
  "no_eboot": "eboot.bin fehlt in {}. Der Download ist unvollstaendig.",
  "upload": "Lade {} Dateien ({:.1f} MB) nach {} hoch",
  "skip": "  = {} (schon vorhanden)",
  "sent": "  > {}  {}",
  "would": "  wuerde senden: {}",
  "cfg_have": "Konfiguration {} existiert schon, bleibt unveraendert.",
  "cfg_new": "Standardkonfiguration angelegt: {}",
  "verify": "Pruefe Dateigroessen auf der Konsole...",
  "verify_ok": "Alle {} Dateien stimmen.",
  "verify_bad": "{} Datei(en) weichen ab oder fehlen: Installer erneut starten.",
  "ask_payload": "Payload-ELF fuer Port 9021 (Pfad, leer = fertig): ",
  "pl_onion": "Abgelehnt: OnionHEN darf nicht vor dem Start der App geladen werden.",
  "pl_sent": "{} ({} Bytes) an den Loader gesendet.",
  "pl_missing": "Datei nicht gefunden: {}",
  "done": "Fertig.",
  "next": "Naechste Schritte:\n  1. ShadowMountPlus muss laufen (es bindet die App ein).\n  2. Starte 'OpenGOAL-PS5' im PS5-Startbildschirm.\n  3. Die App zeigt einen QR-Code. Oeffne am Handy oder PC  http://{}:8080  und sende deine eigenen Spiele-Images (.iso).\n  Der Installer kann jederzeit erneut laufen.",
  "ftp_err": "FTP-Fehler: {}",
  "bad_ip": "'{}' ist keine gueltige IP-Adresse.",
 },
}
L = T["en"]


def say(key, *a):
    print(L[key].format(*a))


def port_open(ip, port, timeout=0.6):
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False


def local_prefix():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0].rsplit(".", 1)[0]
    except OSError:
        return None
    finally:
        s.close()


def scan_lan():
    pre = local_prefix()
    if not pre:
        return []
    ips = [f"{pre}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(64) as ex:
        hits = list(ex.map(lambda ip: port_open(ip, 9021, 0.4) or port_open(ip, 2121, 0.4), ips))
    return [ip for ip, h in zip(ips, hits) if h]


def valid_ip(s):
    try:
        socket.inet_aton(s)
        return s.count(".") == 3
    except OSError:
        return False


def choose_ip(args):
    if args.ip:
        return args.ip
    typed = input(L["ask_ip"]).strip()
    if typed:
        return typed
    say("scan")
    found = scan_lan()
    if found:
        for i, ip in enumerate(found, 1):
            print(f"  {i}) {ip}")
        pick = input(L["pick"]).strip()
        return found[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(found) else pick
    say("none")
    return input(L["ask_ip"]).strip()


def local_files(app):
    out = []
    for d, _, fs in os.walk(app):
        for f in fs:
            p = os.path.join(d, f)
            out.append((p, os.path.relpath(p, app).replace(os.sep, "/"), os.path.getsize(p)))
    # eboot.bin / param.json last: an interrupted upload never leaves a launchable half-app
    out.sort(key=lambda t: (os.path.basename(t[1]) in ALWAYS, t[1]))
    return out


def remote_size(ftp, path):
    try:
        return ftp.size(path)
    except ftplib.all_errors:
        return None


def mkdirs(ftp, path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            ftp.mkd(cur)
        except ftplib.all_errors:
            pass  # exists already


def upload(ftp, local, remote, size, dry):
    if dry:
        say("would", remote)
        return
    done = [0]

    tty = sys.stdout.isatty()

    def cb(block):
        done[0] += len(block)
        if tty:
            sys.stdout.write(f"\r  > {remote}  {done[0] * 100 // max(size, 1)}%   ")
            sys.stdout.flush()

    with open(local, "rb") as fh:
        ftp.storbinary("STOR " + remote, fh, 262144, cb)
    if tty:
        sys.stdout.write("\r" + " " * 100 + "\r")
    say("sent", remote, f"({size / 1048576:.1f} MB)" if size > 1048576 else f"({size} B)")


def install(args, ip, app):
    ftp = ftplib.FTP()
    ftp.connect(ip, args.ftp_port, timeout=30)
    ftp.login()
    ftp.set_pasv(True)
    ftp.voidcmd("TYPE I")
    files = local_files(app)
    say("upload", len(files), sum(f[2] for f in files) / 1048576, REMOTE_APP)
    if not args.dry_run:
        mkdirs(ftp, REMOTE_APP)
        for d in sorted({os.path.dirname(r) for _, r, _ in files if os.path.dirname(r)}):
            mkdirs(ftp, f"{REMOTE_APP}/{d}")
    for local, rel, size in files:
        remote = f"{REMOTE_APP}/{rel}"
        if os.path.basename(rel) not in ALWAYS and remote_size(ftp, remote) == size:
            say("skip", rel)
            continue
        upload(ftp, local, remote, size, args.dry_run)
    cfg = REMOTE_CFG + "/ps5.cfg"
    if remote_size(ftp, cfg) is not None:
        say("cfg_have", cfg)
    else:
        lang = 1 if args.lang == "de" else 0
        data = f"resolution=0\nrefresh=60\nlast_game=0\nlang={lang}\n".encode()
        if args.dry_run:
            say("would", cfg)
        else:
            mkdirs(ftp, REMOTE_CFG)
            import io
            ftp.storbinary("STOR " + cfg, io.BytesIO(data))
            say("cfg_new", cfg)
    if args.dry_run:
        return True
    say("verify")
    bad = [rel for _, rel, size in files if remote_size(ftp, f"{REMOTE_APP}/{rel}") != size]
    try:
        ftp.quit()
    except ftplib.all_errors:
        pass
    if bad and not args.dry_run:
        for b in bad:
            print("  !", b)
        say("verify_bad", len(bad))
        return False
    if not args.dry_run:
        say("verify_ok", len(files))
    return True


def send_payload(ip, port, path, dry):
    if "onion" in os.path.basename(path).lower():
        say("pl_onion")
        return
    if not os.path.isfile(path):
        say("pl_missing", path)
        return
    data = open(path, "rb").read()
    if dry:
        say("would", path)
        return
    with socket.create_connection((ip, port), 10) as s:
        s.sendall(data)
    say("pl_sent", os.path.basename(path), len(data))


def main(argv=None):
    global L
    ap = argparse.ArgumentParser(description="OpenGOAL-PS5 installer")
    ap.add_argument("--ip")
    ap.add_argument("--lang", choices=("en", "de"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--app", help="folder with eboot.bin/sce_sys/assets (default: ./app/%s)" % APP_ID)
    ap.add_argument("--payload", action="append", default=[], help="ELF to send to the loader (repeatable)")
    ap.add_argument("--ftp-port", type=int, default=2121)
    ap.add_argument("--loader-port", type=int, default=9021)
    args = ap.parse_args(argv)
    if not args.lang:
        loc = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
        args.lang = "de" if loc.startswith("de") else "en"
    L = T[args.lang]
    say("hello")
    if args.dry_run:
        say("dry")
    here = os.path.dirname(os.path.abspath(__file__))
    app = args.app or next((p for p in (os.path.join(here, "app", APP_ID), os.path.join(here, APP_ID)) if os.path.isdir(p)), os.path.join(here, "app", APP_ID))
    if not os.path.isdir(app):
        say("no_app", app)
        return 2
    if not os.path.isfile(os.path.join(app, "eboot.bin")):
        say("no_eboot", app)
        return 2
    ip = choose_ip(args)
    if not valid_ip(ip):
        say("bad_ip", ip)
        return 2
    loader, ftp_up = port_open(ip, args.loader_port), port_open(ip, args.ftp_port)
    for name, port, ok in (("ELF loader", args.loader_port, loader), ("FTP", args.ftp_port, ftp_up)):
        say("svc_ok" if ok else "svc_no", name, port)
    if not ftp_up:
        say("step_ftp" if loader else "step_loader")
        say("boot_order")
        say("no_ftp_abort")
        return 1
    try:
        ok = install(args, ip, app)
    except (OSError, ftplib.Error) as e:
        say("ftp_err", e)
        return 1
    payloads = list(args.payload)
    if sys.stdin.isatty() and not args.payload and loader:
        while True:
            try:
                p = input(L["ask_payload"]).strip().strip('"')
            except EOFError:
                break
            if not p:
                break
            payloads.append(p)
    for p in payloads:
        send_payload(ip, args.loader_port, p, args.dry_run)
    say("done")
    if ok:
        say("next", ip)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
