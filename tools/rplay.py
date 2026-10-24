#!/usr/bin/env python3
"""Remote test run without the debug channel (console reachable over FTP / the ELF loader only).

python rplay.py [--deploy] [--cfg name=value ...]
  kills the app, optionally deploys, sets /data/opengoal/config files (empty value deletes the file), launches the app,
  presses Play through inject.txt (the game then starts in a fresh process), plays through the Jak 3 new-game menus and
  prints the fps / gpu lines of the gameplay phase."""
from ps5cfg import PS5_IP
import ftplib, io, os, socket, sys, time, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
IP = PS5_IP
args = sys.argv[1:]
spec = importlib.util.spec_from_file_location("p", os.path.join(HERE, "console.py"))
P = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(P)
except SystemExit:
    pass


def ftp():
    f = ftplib.FTP()
    f.connect(IP, 2121, timeout=30)
    f.login()
    f.voidcmd("TYPE I")
    return f


def tail(n=120000):
    f = ftp()
    p = "/data/opengoal/log/ps5.log"
    sz = f.size(p)
    b = io.BytesIO()
    f.retrbinary("RETR " + p, b.write, rest=max(0, sz - n))
    f.quit()
    t = b.getvalue().decode("utf-8", "replace")
    i = t.rfind("opengoal-ps5: start")
    return t[i:].splitlines() if i >= 0 else t.splitlines()


def put(path, text):
    f = ftp()
    f.storbinary("STOR " + path, io.BytesIO(text.encode()))
    f.quit()


def launch_app():
    put("/data/launch_app.txt", "LAPY77001")
    s = socket.create_connection((IP, 9021), timeout=8)
    s.sendall(open(os.path.join(os.path.dirname(HERE), "payloads", "launchapp.elf"), "rb").read())
    s.close()


P.is_running = lambda: True
P.kill(P.Udp())
time.sleep(4)
if "--deploy" in args:
    for attempt in range(5):
        try:
            P.deploy()
            break
        except ftplib.error_perm:  # "Text file busy": the old process still runs
            P.kill(P.Udp())
            time.sleep(6)
f = ftp()
for i, a in enumerate(args):
    if a == "--cfg":
        k, _, v = args[i + 1].partition("=")
        if v == "":
            try:
                f.delete("/data/opengoal/config/" + k)
            except Exception:
                pass
        else:
            f.storbinary("STOR /data/opengoal/config/" + k, io.BytesIO(v.encode()))
f.quit()

put("/data/opengoal/config/ps5.cfg", "resolution=" + os.environ.get("PS5_RES", "0") + chr(10) + "refresh=60" + chr(10) + "last_game=2" + chr(10) + "lang=0" + chr(10))  # launcher settings can be changed by stray presses
launch_app()
for _ in range(40):
    time.sleep(3)
    if any("launcher: GL" in l for l in tail(30000)):
        break
time.sleep(9)
NL = chr(10)
# the game runs in a fresh process: press Play (retry, a press can get lost while the launcher starts) until it logs "launching"
started = False
for attempt in range(3):
    put("/data/opengoal/config/inject.txt", NL.join(["m remote-play", "w 1500", "p 4000 300 500"]) + NL)
    for _ in range(12):   # the game is a fresh process: its log segment starts with "launching <game>"
        time.sleep(4)
        if any(l.startswith("launching") for l in tail(60000)):
            started = True
            break
    if started:
        break
if not started:
    sys.exit("the game did not start from the launcher (Play press lost); not sending the in-game menu presses")
time.sleep(50)
seq = ["m remote-play-ingame"]
for _ in range(4):
    seq += ["p 1000 150 3000", "p 4000 150 4000"]
seq += ["p 4000 150 12000", "m gameplay"]
put("/data/opengoal/config/inject.txt", NL.join(seq) + NL)
time.sleep(60)

L = tail(200000)
i = max((k for k, l in enumerate(L) if l.startswith("mark: gameplay")), default=0)
sel = [l[:1200] for l in L[i:] if l.startswith(("fps:", "glcalls", "slowdraws:", "CRASH"))]
print("\n".join(sel[:60]))
