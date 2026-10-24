#!/usr/bin/env python3
"""OpenGOAL-PS5 import GUI (tkinter; macOS AppleScript fallback; plain text fallback). Stdlib only.
Pick your own Jak .iso files, the PS5 is found on the network, pc_import.py converts and sends them.
Test hooks: OGPS5_ENGINE, OGPS5_PORT, OGPS5_SCAN_PREFIX ("127.0.0."), OGPS5_LANG, OGPS5_NOTK=1 (force fallback)."""
import json, locale, os, queue, re, shutil, socket, struct, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

HOME = os.path.join(os.path.expanduser("~"), ".opengoal-ps5")
CFG = os.path.join(HOME, "config.json")
PORT = int(os.environ.get("OGPS5_PORT", "8080"))
DE = (os.environ.get("OGPS5_LANG") or (locale.getlocale()[0] or "")).lower().startswith("de")
GAMES = {"jak1": "Jak and Daxter", "jak2": "Jak II", "jak3": "Jak 3"}
DISCS = {  # same table as ps5shim/importer.cpp
    "SCUS-97124": ("jak1", "NTSC-U"), "SCES-50361": ("jak1", "PAL"), "SCPS-15021": ("jak1", "NTSC-J"), "SCPS-56003": ("jak1", "NTSC-K"),
    "SCUS-97265": ("jak2", "NTSC-U"), "SCES-51608": ("jak2", "PAL"), "SCPS-15057": ("jak2", "NTSC-J"), "SCKA-20010": ("jak2", "NTSC-K"),
    "SCUS-97330": ("jak3", "NTSC-U"), "SCUS-97516": ("jak3", "NTSC-U"), "SCES-52460": ("jak3", "PAL"), "SCKA-20040": ("jak3", "NTSC-K")}
TXT = {  # key: (en, de)
    "title": ("OpenGOAL-PS5: import your games", "OpenGOAL-PS5: Spiele importieren"),
    "drop": ("Choose your Jak .iso files (or drop them on the program)", "Jak-.iso-Dateien waehlen (oder auf das Programm ziehen)"),
    "browse": ("Browse...", "Durchsuchen..."), "ps5": ("PS5 address", "PS5-Adresse"), "find": ("Find PS5", "PS5 suchen"),
    "test": ("Test connection", "Verbindung testen"), "start": ("Start", "Starten"), "cancel": ("Cancel", "Abbrechen"),
    "finding": ("Searching the network...", "Suche im Netzwerk..."),
    "notfound": ("No PS5 found. Start OpenGOAL-PS5 on the console, or type its IP address.", "Keine PS5 gefunden. OpenGOAL-PS5 auf der Konsole starten oder die IP eintippen."),
    "found": ("PS5 found: ", "PS5 gefunden: "), "okconn": ("Connected: OpenGOAL-PS5 answers.", "Verbunden: OpenGOAL-PS5 antwortet."),
    "badconn": ("No answer. Is OpenGOAL-PS5 running on the console and is this computer on the same network?", "Keine Antwort. Laeuft OpenGOAL-PS5 auf der Konsole und ist der Computer im selben Netzwerk?"),
    "badip": ("Enter the PS5 IP address first (or press Find PS5).", "Zuerst die PS5-IP eintragen (oder PS5 suchen)."),
    "nogames": ("Add at least one valid game image first.", "Zuerst mindestens ein gueltiges Spiel-Image hinzufuegen."),
    "unknown": ("Not a Jak and Daxter disc image.", "Kein Jak-and-Daxter-Disc-Image."),
    "notiso": ("Not an ISO image (a .bin/.cue must be converted to .iso first).", "Kein ISO-Image (.bin/.cue zuerst in .iso umwandeln)."),
    "trunc": ("The file is smaller than the disc image says: incomplete copy.", "Die Datei ist kleiner als das Image angibt: unvollstaendige Kopie."),
    "dup": ("Another image for this game is already in the list.", "Fuer dieses Spiel ist schon ein Image in der Liste."),
    "ready": ("Ready to start", "Bereit"), "waiting": ("Waiting", "Wartet"), "done": ("Done", "Fertig"), "failed": ("Failed", "Fehlgeschlagen"),
    "cancelled": ("Cancelled", "Abgebrochen"), "left": ("left", "verbleibend"),
    "success": ("Ready: start the game on your PS5.", "Fertig: Starte jetzt das Spiel auf deiner PS5."),
    "partial": ("Some games failed. The others are ready on your PS5.", "Einige Spiele sind fehlgeschlagen. Die anderen sind auf deiner PS5 bereit."),
    "noengine": ("The import engine (pc_import.py) was not found next to this program. Download the full bundle again.", "Die Import-Engine (pc_import.py) wurde nicht gefunden. Das komplette Paket neu herunterladen."),
    "hint_conn": ("Check that OpenGOAL-PS5 is open on the console and that both are on the same network.", "Pruefe, ob OpenGOAL-PS5 auf der Konsole offen ist und beide im selben Netzwerk sind."),
    "hint_space": ("The console may be out of free disk space.", "Auf der Konsole ist eventuell zu wenig Speicher frei."),
    "hint_disc": ("The disc image may be damaged or not a supported version. Make a fresh copy of your disc.", "Das Image ist eventuell beschaedigt oder keine unterstuetzte Version. Erstelle eine neue Kopie deiner Disc."),
    "hint_any": ("Details are in the line above. You can start again.", "Details stehen in der Zeile oben. Du kannst erneut starten."),
    "phase_detect": ("Checking image", "Pruefe Image"), "phase_tools": ("Preparing tools", "Bereite Werkzeuge vor"),
    "phase_extract": ("Unpacking", "Entpacke"), "phase_decompile": ("Analysing game", "Analysiere Spiel"),
    "phase_compile": ("Building game", "Baue Spiel"), "phase_pack": ("Packing", "Packe"),
    "phase_upload": ("Sending to PS5", "Sende an PS5"), "phase_install": ("Installing on PS5", "Installiere auf PS5"),
    "phase_done": ("Done", "Fertig"), "phase_failed": ("Failed", "Fehlgeschlagen")}


def T(k):
    return TXT[k][1 if DE else 0]


def load_cfg():
    try:
        return json.load(open(CFG))
    except Exception:
        return {}


def save_ip(ip):
    try:
        os.makedirs(HOME, exist_ok=True)
        json.dump({"ps5": ip}, open(CFG, "w"))
    except OSError:
        pass


# ---- ISO9660 detection (about 6 KB read, no hashing) ----
def detect_iso(path):
    """-> dict(ok=True, game, region, serial) or dict(ok=False, reason=<TXT key>)."""
    try:
        if not path.lower().endswith(".iso"):
            return {"ok": False, "reason": "notiso"}
        with open(path, "rb") as f:
            f.seek(16 * 2048)
            pvd = f.read(2048)
            if len(pvd) < 2048 or pvd[0] != 1 or pvd[1:6] != b"CD001":
                return {"ok": False, "reason": "notiso"}
            if struct.unpack_from("<I", pvd, 80)[0] * 2048 > os.path.getsize(path):
                return {"ok": False, "reason": "trunc"}
            lba, size = struct.unpack_from("<I", pvd, 158)[0], min(struct.unpack_from("<I", pvd, 166)[0], 262144)
            f.seek(lba * 2048)
            d = f.read(size)
            p = 0
            cnf = None
            while p < len(d):
                n = d[p]
                if n == 0:
                    p = (p // 2048 + 1) * 2048
                    continue
                if d[p + 33:p + 33 + d[p + 32]] == b"SYSTEM.CNF;1":
                    f.seek(struct.unpack_from("<I", d, p + 2)[0] * 2048)
                    cnf = f.read(min(struct.unpack_from("<I", d, p + 10)[0], 4096))
                    break
                p += n
        m = cnf and re.search(rb"cdrom0:\\?([A-Z]{4})_(\d{3})\.(\d{2})", cnf)
        serial = "%s-%s%s" % tuple(x.decode() for x in m.groups()) if m else ""
        if serial not in DISCS:
            return {"ok": False, "reason": "unknown"}
        return {"ok": True, "game": DISCS[serial][0], "region": DISCS[serial][1], "serial": serial}
    except (OSError, struct.error, IndexError):
        return {"ok": False, "reason": "notiso"}


# ---- PS5 discovery ----
def test_ps5(ip, timeout=2.0):
    try:
        with urlopen("http://%s:%d/api/status" % (ip, PORT), timeout=timeout) as r:
            return b'"version"' in r.read(65536)
    except Exception:
        return False


def local_prefixes():
    if os.environ.get("OGPS5_SCAN_PREFIX"):
        return [os.environ["OGPS5_SCAN_PREFIX"]]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent, only picks the local interface
        ip = s.getsockname()[0]
        s.close()
        return [ip.rsplit(".", 1)[0] + "."]
    except OSError:
        return []


def find_ps5():
    def one(ip):
        try:
            socket.create_connection((ip, PORT), 0.5).close()
        except OSError:
            return None
        return ip if test_ps5(ip) else None
    ips = [p + str(i) for p in local_prefixes() for i in range(1, 255)]
    with ThreadPoolExecutor(64) as ex:
        for r in ex.map(one, ips):
            if r:
                return r
    return None


# ---- engine ----
def find_engine():
    if os.environ.get("OGPS5_ENGINE"):
        return os.environ["OGPS5_ENGINE"]
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(3):
        f = os.path.join(d, "pc_import.py")
        if os.path.exists(f):
            return f
        d = os.path.dirname(d)
    return None


def parse_line(line):
    """One engine output line -> dict with at least 'phase', or None (log noise)."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        o = json.loads(line)
    except ValueError:
        return None
    return o if isinstance(o, dict) and "phase" in o else None


def fmt_eta(s):
    s = int(s)
    return "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def fmt_speed(b):
    return "%.1f MB/s" % (b / 1048576) if b >= 1048576 else ("%d KB/s" % (b / 1024) if b > 0 else "")


def status_text(o):
    ph = o["phase"]
    parts = [TXT.get("phase_" + ph, (ph, ph))[1 if DE else 0], "%d%%" % int(o.get("percent", 0))]
    if o.get("speed_bps"):
        parts.append(fmt_speed(o["speed_bps"]))
    if ph not in ("done", "failed") and o.get("eta_s", -1) >= 0:
        parts.append("%s %s" % (fmt_eta(o["eta_s"]), T("left")))
    if o.get("message") and ph != "done":
        parts.append(o["message"])
    return "   |   ".join(parts)


def hint(msg):
    m = (msg or "").lower()
    if re.search(r"connect|refused|time.?out|unreachable|no route|reset", m):
        return T("hint_conn")
    if re.search(r"space|disk|full", m):
        return T("hint_space")
    if re.search(r"iso|disc|serial|unknown|checksum|corrupt", m):
        return T("hint_disc")
    return T("hint_any")


def run_game(engine, game, iso, ip, on_line, stop):
    """Run the engine; on_line(dict) for each progress line. -> (exit_code, last_message)."""
    cmd = [sys.executable, "-u", engine, "--game", game, "--iso", iso, "--ps5", ip, "--port", str(PORT),
           "--tools-dir", os.path.join(HOME, "tools"), "--json-progress"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    last = ""
    tail = []

    def killer():
        while p.poll() is None:
            if stop.is_set():
                p.terminate()
                return
            time.sleep(0.2)
    threading.Thread(target=killer, daemon=True).start()
    for line in p.stdout:
        o = parse_line(line)
        if o:
            last = str(o.get("message") or last)
            on_line(o)
        elif line.strip():
            tail = (tail + [line.strip()])[-5:]
    p.wait()
    return p.returncode, last or (tail[-1] if tail else "")


def run_queue(engine, items, ip, on_line, on_game_end, stop):
    """items: list of (game, iso), run one after another. -> (#ok, #total, last failure message)."""
    ok = 0
    why = ""
    for i, (game, iso) in enumerate(items):
        if stop.is_set():
            break
        code, msg = run_game(engine, game, iso, ip, lambda o, i=i: on_line(i, o), stop)
        good = code == 0 and not stop.is_set()
        ok += good
        why = msg if not good else why
        on_game_end(i, good, msg)
    return ok, len(items), why


# ---- tkinter UI ----
def gui_tk(tk, ttk, filedialog, argv):
    BG, PANEL, TRACK, OR, FG, DIM, GRN, RED = "#14161a", "#202329", "#343840", "#ff8a00", "#ebebeb", "#969ba5", "#46c86e", "#eb5546"
    root = tk.Tk()
    root.title("OpenGOAL-PS5")
    root.configure(bg=BG)
    root.geometry("720x700")
    st = ttk.Style(root)
    st.theme_use("clam")
    for name, col in (("O", OR), ("E", RED)):
        st.configure(name + ".Horizontal.TProgressbar", troughcolor=TRACK, background=col, bordercolor=BG, lightcolor=col, darkcolor=col, thickness=8)
    ff = "Segoe UI" if os.name == "nt" else "Helvetica"

    def lab(parent, text="", fg=FG, size=10, bold=False, bg=BG, **kw):
        return tk.Label(parent, text=text, fg=fg, bg=bg, font=(ff, size, "bold" if bold else "normal"), anchor="w", **kw)

    def btn(parent, text, cmd, primary=False):
        return tk.Button(parent, text=text, command=cmd, bg=OR if primary else TRACK, fg="#141414" if primary else FG, relief="flat", bd=0,
                         padx=14, pady=6, activebackground=OR, highlightthickness=0)
    lab(root, T("title"), OR, 16, True).pack(fill="x", padx=20, pady=(14, 8))
    drop = tk.Frame(root, bg=PANEL, highlightbackground=OR, highlightthickness=2)
    drop.pack(fill="x", padx=20)
    lab(drop, T("drop"), FG, 10, True, PANEL).pack(pady=(14, 6))
    btn(drop, T("browse"), lambda: add_many(filedialog.askopenfilenames(filetypes=[("ISO", "*.iso")]))).pack(pady=(0, 14))
    cardsf = tk.Frame(root, bg=BG)
    cardsf.pack(fill="both", expand=True, padx=20, pady=10)
    row = tk.Frame(root, bg=BG)
    row.pack(fill="x", padx=20)
    lab(row, T("ps5"), DIM, width=12).pack(side="left")
    ip_var = tk.StringVar(value=load_cfg().get("ps5", ""))
    tk.Entry(row, textvariable=ip_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=16).pack(side="left", padx=6, ipady=4)
    net = lab(root, "", DIM, wraplength=680, justify="left")
    net.pack(fill="x", padx=20, pady=4)
    allbar = ttk.Progressbar(root, style="O.Horizontal.TProgressbar", maximum=100)
    allbar.pack(fill="x", padx=20, pady=(6, 4))
    result = lab(root, "", FG, 11, True, wraplength=680, justify="left")
    result.pack(fill="x", padx=20)
    brow = tk.Frame(root, bg=BG)
    brow.pack(fill="x", padx=20, pady=12)
    items, q, stop = [], queue.Queue(), threading.Event()
    state = {"running": False, "n": 1, "pct": {}}

    def add(path):
        path = os.path.abspath(path)
        if any(i["path"] == path for i in items):
            return
        info = detect_iso(path)
        err = "" if info["ok"] else T(info["reason"])
        if info["ok"] and any(i["ok"] and i["game"] == info["game"] for i in items):
            err = T("dup")
        f = tk.Frame(cardsf, bg=PANEL)
        f.pack(fill="x", pady=3)
        title = "%s   (%s, %s)" % (GAMES[info["game"]], info["region"], info["serial"]) if info["ok"] else os.path.basename(path)
        lab(f, title, FG, 10, True, PANEL).pack(fill="x", padx=10, pady=(6, 0))
        lab(f, os.path.basename(path), DIM, 8, False, PANEL).pack(fill="x", padx=10)
        bar = ttk.Progressbar(f, style="O.Horizontal.TProgressbar", maximum=100)
        bar.pack(fill="x", padx=10, pady=3)
        s = lab(f, err or T("ready"), RED if err else DIM, 9, False, PANEL)
        s.pack(fill="x", padx=10, pady=(0, 6))
        it = {"path": path, "ok": not err, "game": info.get("game"), "frame": f, "bar": bar, "st": s}
        items.append(it)
        x = lab(f, "x", DIM, 10, True, PANEL)
        x.place(relx=1.0, x=-18, y=4)
        x.bind("<Button-1>", lambda e, it=it: remove(it))

    def add_many(paths):
        for p in paths:
            add(p)

    def remove(it):
        if not state["running"]:
            it["frame"].destroy()
            items.remove(it)

    def do_find():
        net.config(text=T("finding"), fg=DIM)
        threading.Thread(target=lambda: q.put(("found", find_ps5())), daemon=True).start()

    def do_test():
        ip = ip_var.get().strip()
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
            net.config(text=T("badip"), fg=RED)
            return
        ok = test_ps5(ip)
        net.config(text=T("okconn") if ok else T("badconn"), fg=GRN if ok else RED)
        if ok:
            save_ip(ip)

    def go():
        ip = ip_var.get().strip()
        todo = [i for i in items if i["ok"]]
        if not todo:
            result.config(text=T("nogames"), fg=RED)
            return
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
            result.config(text=T("badip"), fg=RED)
            do_find()
            return
        engine = find_engine()
        if not engine:
            result.config(text=T("noengine"), fg=RED)
            return
        save_ip(ip)
        stop.clear()
        state.update(running=True, n=len(todo), pct={})
        start_b.config(state="disabled")
        cancel_b.config(state="normal")
        result.config(text="")
        for i in todo:
            i["bar"].config(style="O.Horizontal.TProgressbar", value=0)
            i["st"].config(text=T("waiting"), fg=DIM)

        def work():
            ok, n, why = run_queue(engine, [(i["game"], i["path"]) for i in todo], ip,
                                   lambda k, o: q.put(("line", todo[k], k, o)),
                                   lambda k, good, msg: q.put(("end", todo[k], k, good, msg)), stop)
            q.put(("all", ok, n, why))
        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            while True:
                m = q.get_nowait()
                if m[0] == "found":
                    if m[1]:
                        ip_var.set(m[1])
                        net.config(text=T("found") + m[1], fg=GRN)
                        save_ip(m[1])
                    else:
                        net.config(text=T("notfound"), fg=RED)
                elif m[0] == "line":
                    _, it, k, o = m
                    it["bar"].config(value=int(o.get("overall", 0)))
                    it["st"].config(text=status_text(o), fg=DIM)
                    state["pct"][k] = int(o.get("overall", 0))
                elif m[0] == "end":
                    _, it, k, good, msg = m
                    if good:
                        state["pct"][k] = 100
                        it["bar"].config(value=100)
                        it["st"].config(text=T("done"), fg=GRN)
                    elif stop.is_set():
                        it["st"].config(text=T("cancelled"), fg=DIM)
                    else:
                        it["bar"].config(style="E.Horizontal.TProgressbar")
                        it["st"].config(text=T("failed") + ": " + msg, fg=RED)
                elif m[0] == "all":
                    _, ok, n, why = m
                    state["running"] = False
                    start_b.config(state="normal")
                    cancel_b.config(state="disabled")
                    if stop.is_set():
                        result.config(text=T("cancelled"), fg=DIM)
                    elif ok == n:
                        result.config(text=T("success"), fg=GRN)
                    else:
                        result.config(text=(T("partial") if ok else T("failed")) + "\n" + hint(why), fg=RED)
                allbar.config(value=sum(state["pct"].values()) / max(1, state["n"]))
        except queue.Empty:
            pass
        root.after(100, poll)
    start_b = btn(brow, T("start"), go, True)
    start_b.pack(side="left")
    cancel_b = btn(brow, T("cancel"), stop.set)
    cancel_b.config(state="disabled")
    cancel_b.pack(side="left", padx=8)
    btn(brow, T("find"), do_find).pack(side="right")
    btn(brow, T("test"), do_test).pack(side="right", padx=8)
    try:  # optional real drag and drop, only if the user has tkinterdnd2 (tkinter has none built in)
        from tkinterdnd2 import DND_FILES
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", lambda e: add_many(root.tk.splitlist(e.data)))
    except Exception:
        pass
    add_many([a for a in argv if os.path.isfile(a)])
    if not ip_var.get():
        do_find()
    if os.environ.get("OGPS5_AUTOSTART"):
        root.after(500, go)
    root.after(100, poll)
    root.mainloop()


# ---- macOS AppleScript fallback (no tkinter) ----
def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def q_(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def gui_osascript(argv):
    files = [a for a in argv if os.path.isfile(a)]
    if not files:
        rc, out = osa('set fs to choose file with prompt "%s" of type {"iso"} with multiple selections allowed\nset o to ""\n'
                      'repeat with f in fs\nset o to o & POSIX path of f & linefeed\nend repeat\nreturn o' % q_(T("title")))
        if rc:
            return 1
        files = [ln for ln in out.splitlines() if ln]
    items, errs = [], []
    for f in files:
        i = detect_iso(f)
        if i["ok"] and all(g != i["game"] for g, _ in items):
            items.append((i["game"], f))
        else:
            errs.append("%s: %s" % (os.path.basename(f), T(i.get("reason", "dup"))))
    if errs:
        osa('display dialog "%s" buttons {"OK"}' % q_("\n".join(errs)))
    if not items:
        return 1
    ip = load_cfg().get("ps5") or ""
    if not (ip and test_ps5(ip)):
        ip = find_ps5()
    if not ip:
        rc, ip = osa('text returned of (display dialog "%s" default answer "" buttons {"OK"} default button "OK")' % q_(T("notfound")))
        if rc or not test_ps5(ip.strip()):
            osa('display dialog "%s" buttons {"OK"}' % q_(T("badconn")))
            return 1
        ip = ip.strip()
    save_ip(ip)
    engine = find_engine()
    if not engine:
        osa('display dialog "%s" buttons {"OK"}' % q_(T("noengine")))
        return 1
    last = {"t": 0, "ph": ""}

    def on_line(k, o):  # one notification per phase change or every 10 s: notifications are slow and noisy
        if o["phase"] != last["ph"] or time.time() - last["t"] > 10:
            last.update(t=time.time(), ph=o["phase"])
            osa('display notification "%s" with title "OpenGOAL-PS5 %s"' % (q_(status_text(o)), GAMES[items[k][0]]))
    ok, n, why = run_queue(engine, items, ip, on_line, lambda *a: None, threading.Event())
    osa('display dialog "%s" buttons {"OK"} with title "OpenGOAL-PS5"' % q_(T("success") if ok == n else (T("failed") + ": " + why + "\n" + hint(why))))
    return 0 if ok == n else 1


# ---- plain terminal fallback ----
def gui_text(argv):
    files = [a for a in argv if os.path.isfile(a)] or [x for x in input(T("drop") + "\n> ").split() if os.path.isfile(x)]
    items = []
    for f in files:
        i = detect_iso(f)
        if i["ok"]:
            items.append((i["game"], f))
        else:
            print(os.path.basename(f), T(i["reason"]))
    ip = load_cfg().get("ps5") or find_ps5() or input(T("ps5") + ": ").strip()
    if not items or not test_ps5(ip):
        print(T("badconn"))
        return 1
    save_ip(ip)
    engine = find_engine()
    if not engine:
        print(T("noengine"))
        return 1
    ok, n, why = run_queue(engine, items, ip, lambda k, o: print("\r%s: %s" % (items[k][0], status_text(o)), end="  ", flush=True),
                           lambda *a: print(), threading.Event())
    print(T("success") if ok == n else T("failed") + ": " + why + "\n" + hint(why))
    return 0 if ok == n else 1


def main(argv):
    if not os.environ.get("OGPS5_NOTK"):
        try:
            import tkinter as tk
            from tkinter import filedialog, ttk
        except ImportError:
            tk = None
        if tk:
            gui_tk(tk, ttk, filedialog, argv)
            return 0
    if sys.platform == "darwin" and shutil.which("osascript"):
        return gui_osascript(argv)
    return gui_text(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
