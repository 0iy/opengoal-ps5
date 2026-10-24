#!/usr/bin/env python3
"""ps5: one command line for building, deploying, measuring and testing OpenGOAL-PS5.

  ps5 build                         incremental engine and app build in WSL
  ps5 deploy [--force]              upload eboot.bin to the console
  ps5 run [game] [seconds]          restart the app (optionally straight into jak1/jak2/jak3) and print its log
  ps5 go [game] [seconds]           build, deploy, run
  ps5 start [game]                  start the app and leave it running
  ps5 kill                          close the app
  ps5 log [regex]                   grep the console log of the last start
  ps5 shot <game> [seconds ...]     run a game and fetch screenshots (PNG) into out/
  ps5 shots request|fetch ...       lower level screenshot requests (see tools/shotseries.py)
  ps5 dbg <command ...>             debug channel client (ping, ls, tail, press, ...)
  ps5 perf round <label> <game> <seconds> [flag ...]
  ps5 perf suite <game> <seconds> <label> "<flags>" ...
  ps5 perf trace stats|stages|mip|multidraw <trace.bin ...>
  ps5 qa [options]                  QA pipeline (--quick, --full, --analyze DIR, ...)
  ps5 setup [options]               find the console and install what is missing (installer/ps5_setup.py)
  ps5 import [options]              game import from the PC (installer/pc_import.py)
  ps5 upload <game> <iso>           upload an ISO through the console web page
  ps5 sync [options]                upstream sync (engine/sync_upstream.py)
  ps5 sym <ps5_log addr> <addr ...> resolve crash addresses to function names (WSL)
  ps5 test [options]                offline test suite (tests/run_all.py)
  ps5 doctor                        check the toolchain and the console connection

The console address comes from the PS5_IP environment variable or a git-ignored file named .ps5_ip in the repository root.
"""
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

CONSOLE = {"build", "deploy", "run", "go", "start", "kill", "log", "shot"}
TRACE = {"stats": "stats.py", "stages": "stages.py", "mip": "mip.py", "multidraw": "multidraw.py"}


def script(path, args):
    """Run a python script in its own process (several of them execute at import time)."""
    return subprocess.call([sys.executable, "-u", path] + list(args))


def perf(a):
    sub = a[0] if a else ""
    if sub == "round":
        return script(os.path.join(TOOLS, "perfround.py"), a[1:])
    if sub == "suite":
        import perf_suite
        return perf_suite.main(a[1:])
    if sub == "trace" and len(a) > 1 and a[1] in TRACE:
        return script(os.path.join(TOOLS, "trace", TRACE[a[1]]), a[2:])
    print("usage: ps5 perf round|suite|trace ... (ps5 help)")
    return 2


def sym(a):
    wsl_path = "/mnt/" + TOOLS[0].lower() + TOOLS[2:].replace("\\", "/") if os.name == "nt" else TOOLS
    cmd = ["python3", wsl_path + "/symlookup.py"] + a
    return subprocess.call((["wsl", "-e"] if os.name == "nt" else []) + cmd)


def doctor():
    import shutil
    import socket
    ok = True

    def line(good, name, note=""):
        nonlocal ok
        ok = ok and good
        print("%-4s %-34s %s" % ("ok" if good else "FAIL", name, note))

    for p in ("payloads/killapp.elf", "payloads/launchapp.elf", "payloads/scan.elf", "payloads/keepalive.elf",
              "driver/ps5-opengl.patch", "engine/ports/manifest.json", "installer/pc_import.py"):
        line(os.path.isfile(os.path.join(ROOT, p)), p)
    line(sys.version_info >= (3, 8), "python >= 3.8", sys.version.split()[0])
    for mod in ("numpy", "PIL"):
        try:
            __import__(mod)
            line(True, "python module " + mod)
        except ImportError:
            print("note %-34s needed only for qa and screenshots" % ("missing module " + mod))
    wsl = shutil.which("wsl") if os.name == "nt" else shutil.which("bash")
    line(bool(wsl), "WSL" if os.name == "nt" else "bash", "needed for build" if wsl else "needed for build, not found")
    import ps5cfg
    try:
        host = ps5cfg.ip()
    except SystemExit as e:
        print("note console address not set (%s)" % e)
        return 0 if ok else 1
    for port, name in ((2121, "FTP"), (9021, "ELF loader"), (2323, "shell (optional)")):
        try:
            socket.create_connection((host, port), timeout=3).close()
            line(True, "console %s port %d" % (name, port))
        except OSError:
            if port == 2323:
                print("note console %s port %d closed" % (name, port))
            else:
                line(False, "console %s port %d" % (name, port), "not reachable")
    return 0 if ok else 1


def main(argv):
    a = list(argv)
    if not a or a[0] in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd in CONSOLE:
        import console
        console.main(a)
        return 0
    if cmd == "perf":
        return perf(rest)
    if cmd == "qa":
        return script(os.path.join(TOOLS, "qa_pipeline.py"), rest)
    if cmd == "setup":
        return script(os.path.join(ROOT, "installer", "ps5_setup.py"), rest)
    if cmd == "import":
        return script(os.path.join(ROOT, "installer", "pc_import.py"), rest)
    if cmd == "upload":
        return script(os.path.join(TOOLS, "upload_iso_web.py"), rest)
    if cmd == "sync":
        return script(os.path.join(ROOT, "engine", "sync_upstream.py"), rest)
    if cmd == "test":
        return script(os.path.join(ROOT, "tests", "run_all.py"), rest)
    if cmd == "dbg":
        return script(os.path.join(TOOLS, "dbg.py"), rest)
    if cmd == "shots":
        return script(os.path.join(TOOLS, "shotseries.py"), rest)
    if cmd == "sym":
        return sym(rest)
    if cmd == "doctor":
        return doctor()
    print("unknown command: %s (ps5 help)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
