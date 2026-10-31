#!/usr/bin/env python3
"""Run GOAL code inside the game on the console through goalc (DECI2 REPL), with small output.

  ps5repl.py up [game]       start goalc in WSL (kept running), connect to the console game, compile the game code once
  ps5repl.py eval 'EXPR'     evaluate GOAL code in the running game; prints only the new output, cleaned (default 25 lines)
  ps5repl.py status          is goalc running, is the target connected, are the game symbols loaded
  ps5repl.py stop            stop goalc

Needs the console game started with the REPL listener: `echo 1 > /data/opengoal/config/debugrepl.txt` (the app then adds -debug,
or -debug-mem for Jak 1/3) and a game restart; ps5scene.py does that. Do NOT open a TCP connection to port 8113 to probe it:
the game accepts the first connection of a run only for goalc's handshake after a restart (a probe makes `(lt)` fail once).
Console address: PS5_IP or .ps5_ip in the repository root. goalc and the game data live in WSL at ~/ingame_full (override: PS5_GOALC_DIR)."""
import os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIFO, OUT, PROJ = "/tmp/gc.in", "/tmp/gc.out", os.environ.get("PS5_GOALC_DIR", "$HOME/ingame_full")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOISE = re.compile(r"^\s*(\[\s*\d+%\]|\[Debugger\]|\[Listener\] Closed|\d+\s+#x[0-9a-f]+\s+-?[\d.]+\s+-?\d+\s*$)")


def wsl(cmd, data=None, timeout=60):
    r = subprocess.run(["wsl", "-e", "bash", "-lc", cmd], input=data, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace")


def ip():
    v = os.environ.get("PS5_IP")
    return v or open(os.path.join(ROOT, ".ps5_ip")).read().strip()


def size():
    s = wsl("stat -c %%s %s 2>/dev/null || echo 0" % OUT).strip()
    return int(s or 0)


def running():
    return wsl("pgrep -x goalc | head -1").strip() != ""


def start_daemon(game):
    wsl("pkill -x goalc; rm -f %s; mkfifo %s; cd %s && (setsid nohup bash -c 'tail -f %s | ./build/goalc/goalc -g %s --user-auto "
        "--disable-ansi --proj-path %s' > %s 2>&1 &); sleep 2" % (FIFO, FIFO, PROJ, FIFO, game, PROJ, OUT))  # sleep: an instant exit of the wsl call can take the detached goalc down
    t = time.time()
    while time.time() - t < 40:
        if "(lt)" in ANSI.sub("", wsl("cat %s" % OUT)):
            return
        time.sleep(1)
    raise SystemExit("goalc did not start (see %s in WSL)" % OUT)


def send(expr):
    wsl("cat > %s" % FIFO, (expr.replace("\n", " ") + "\n").encode())


def run(expr, wait=4.0, limit=60.0):
    """Send a form, wait until the output stays quiet for `wait` seconds, return the new cleaned lines."""
    off = size()
    send(expr)
    t0, last, lastsize = time.time(), time.time(), off
    while time.time() - t0 < limit:
        time.sleep(0.5)
        n = size()
        if n != lastsize:
            lastsize, last = n, time.time()
        elif time.time() - last > wait and n > off:
            break
        elif time.time() - t0 > 12 and n == off:
            break
    raw = wsl("tail -c +%d %s" % (off + 1, OUT))
    return [l.rstrip() for l in ANSI.sub("", raw).replace("\r", "\n").split("\n") if l.strip() and not NOISE.match(l)]


def up(game="jak2"):
    if running() and wsl("cat /tmp/gc.game 2>/dev/null").strip() != game:  # goalc runs for another game
        wsl("pkill -x goalc; rm -f /tmp/gc.code")
    if not running():
        start_daemon(game)
        wsl("echo %s > /tmp/gc.game" % game)
    out = run('(lt "%s")' % ip(), wait=3, limit=30)
    ok = any("Got version" in l for l in out)
    if not ok:
        print("connect failed:\n" + "\n".join(out[-6:]))
        print("Is the game running with debugrepl.txt set? Restart the game once (a probe connection to 8113 also breaks it).")
        raise SystemExit(1)
    if not os.path.exists(flag(game)) or not wsl("test -f /tmp/gc.code && echo y").strip():
        out = run('(make-group "all-code")', wait=8, limit=400)
        if not any("Successfully built" in l for l in out):
            print("\n".join(out[-8:]))
            raise SystemExit("compile of the game code failed")
        wsl("touch /tmp/gc.code")
        open(flag(game), "w").write("1")
    print("connected to %s, game symbols loaded" % ip())


def flag(game):
    return os.path.join(os.environ.get("TEMP", "/tmp"), "ps5repl_%s.flag" % game)


def status():
    r = running()
    print("goalc: %s" % ("running" if r else "stopped"))
    if r:
        out = run('(format #t "ping ~D~%" 1)', wait=2, limit=15)
        print("target: " + ("connected" if any("ping 1" in l for l in out) else "not connected / symbols missing: " + (out[-1] if out else "no output")))


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    c = a[0]
    if c == "up": up(a[1] if len(a) > 1 else "jak2")
    elif c == "eval":
        out = run(a[1], wait=float(os.environ.get("WAIT", "3")))
        n = int(os.environ.get("LINES", "25"))
        print("\n".join(out[-n:]) if out else "(no output)")
    elif c == "status": status()
    elif c == "stop":
        wsl("pkill -x goalc"); print("stopped")
    else: print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
