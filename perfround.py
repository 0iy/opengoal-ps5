#!/usr/bin/env python3
"""One measurement round: sets the A/B flag files, runs a game, saves the full UDP log and the console log tail.

usage: perfround.py <label> <jak2|jak3> <seconds> [flag ...]
  flags: nomipcpu nomultidraw gputrace profile spinwait   (files in /data/opengoal/config; all of them are removed first)
Output: perf_runs/<label>.udp.log (every UDP log line of the run), perf_runs/<label>.console.log (tail of ps5.log), perf_runs/<label>.summary.txt
jak2 starts through autolaunch (ps5.py run); jak3 is driven into the new-game spawn scene like rplay.py."""
from ps5cfg import PS5_IP
import ftplib
import io
import os
import re
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
IP = PS5_IP
FLAGS = ["nomipcpu", "nomultidraw", "gputrace", "profile", "spinwait", "trace", "syncdebug", "asyncmultidraw", "asyncswap", "triplebuffer", "presentlog", "drawcost", "rtfastflush", "diag", "nomerge", "noasyncmultidraw", "shotscreen", "mergestats", "mipfast", "mipfast3", "waitus100", "workerdiag"]
label, game, secs = sys.argv[1], sys.argv[2], int(sys.argv[3])
want = set(sys.argv[4:])
for _r, _v in (("res1440", "1"), ("res4k", "2")):
    if _r in want:
        os.environ["PS5_RES"] = _v
        want.discard(_r)
out = os.path.join(HERE, "perf_runs")
os.makedirs(out, exist_ok=True)


def ftp():
    f = ftplib.FTP()
    f.connect(IP, 2121, timeout=30)
    f.login()
    f.voidcmd("TYPE I")
    return f


f = ftp()
for fl in FLAGS:
    try:
        f.delete("/data/opengoal/config/%s.txt" % fl)
    except Exception:
        pass
for fl in want:
    f.storbinary("STOR /data/opengoal/config/%s.txt" % fl, io.BytesIO({"profile": b"render", "trace": (b"100 7" if game == "jak3" else b"40 8")}.get(fl, b"1")))
f.quit()

lines = []
stop = threading.Event()


def listen():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 9999))
    s.settimeout(0.5)
    while not stop.is_set():
        try:
            d = s.recvfrom(4000)[0].decode("utf-8", "replace")
            lines.append("%s %s" % (time.strftime("%H:%M:%S"), d))
        except Exception:
            pass


t0 = time.time()
if game == "jak3":
    th = threading.Thread(target=listen, daemon=True)
    th.start()
    r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "rplay.py")], capture_output=True, text=True, timeout=600)
    time.sleep(max(0, secs - 60))
    stop.set()
    th.join()
    open(os.path.join(out, label + ".udp.log"), "w", encoding="utf-8").write("\n".join(lines))
else:
    r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "ps5.py"), "run", game, str(secs)], capture_output=True, text=True, timeout=secs + 200)
    src = os.path.join(HERE, "last_run.log")
    if os.path.exists(src):
        open(os.path.join(out, label + ".udp.log"), "wb").write(open(src, "rb").read())

f = ftp()
p = "/data/opengoal/log/ps5.log"
sz = f.size(p)
b = io.BytesIO()
f.retrbinary("RETR " + p, b.write, rest=max(0, sz - 3000000))
f.quit()
txt = b.getvalue().decode("utf-8", "replace")
i = txt.rfind("opengoal-ps5: start")
open(os.path.join(out, label + ".console.log"), "w", encoding="utf-8").write(txt[i:] if i >= 0 else txt)

f = ftp()
try:
    names = []
    f.retrlines("LIST /data/opengoal/log", lambda l: names.append(l.split()[-1]))
except Exception:
    names = []
for nme in names:
    base = nme.split("/")[-1]
    if base.startswith("trace_") and base.endswith(".bin"):
        bb = io.BytesIO()
        f.retrbinary("RETR /data/opengoal/log/" + base, bb.write)
        open(os.path.join(out, label + "." + base), "wb").write(bb.getvalue())
        try:
            f.delete("/data/opengoal/log/" + base)
        except Exception:
            pass
f.quit()

# summary: fps series and the key counters
log = open(os.path.join(out, label + ".udp.log"), encoding="utf-8", errors="replace").read().splitlines()
fps = [float(m.group(1)) for l in log for m in [re.search(r"fps: ([0-9.]+)", l)] if m]
cpu = [float(m.group(1)) for l in log for m in [re.search(r"thread cpu ([0-9.]+) ms", l)] if m]
with open(os.path.join(out, label + ".summary.txt"), "w", encoding="utf-8") as s:
    s.write("label %s game %s secs %d flags %s wall %.0f s\n" % (label, game, secs, sorted(want), time.time() - t0))
    s.write("fps series: %s\n" % " ".join("%.0f" % x for x in fps))
    s.write("thread cpu ms: %s\n" % " ".join("%.0f" % x for x in cpu))
    for key in ("waits per frame", "backpressure", "drain-buffer:", "present-wait", "threads:", "thread time per frame", "frametime:", "mip:", "clear:"):
        sel = [l for l in log if key in l][-3:]
        s.writelines(l[:400] + "\n" for l in sel)
print(open(os.path.join(out, label + ".summary.txt"), encoding="utf-8").read())
