#!/usr/bin/env python3
"""Fast build / deploy / run loop for the PS5 app (replaces the slow PowerShell chain).

  ps5.py build                  incremental engine+app build in WSL (skips work when nothing changed)
  ps5.py deploy                 upload the new eboot.bin only (one FTP session)
  ps5.py run [game] [seconds]   close the app, launch it (optionally straight into a game), print the UDP log;
                                returns as soon as the fps line count / crash is seen, or at the timeout
  ps5.py kill                   close the app
  ps5.py go [game] [seconds]    build + deploy + run
  ps5.py log [regex]            grep the full log file on the console
"""
from ps5cfg import PS5_IP
import ftplib, io, os, re, socket, subprocess, sys, threading, time

IP = PS5_IP
TITLE = "LAPY77001"
HERE = os.path.dirname(os.path.abspath(__file__))
WSL_HERE = "/mnt/" + HERE[0].lower() + HERE[2:].replace("\\", "/") if os.name == "nt" else HERE


def t():
    return time.strftime("%H:%M:%S")


def ftp():
    f = ftplib.FTP()
    f.connect(IP, 2121, timeout=15)
    f.login()
    f.voidcmd("TYPE I")
    return f


def ftp_put(f, remote, data):
    f.storbinary("STOR " + remote, io.BytesIO(data))


def console_up():
    """False when the console does not answer (rest mode, crashed or off): scripts stop instead of hanging."""
    try:
        socket.create_connection((IP, 2323), timeout=3).close()
        return True
    except OSError:
        return False


def shell(cmd, idle=0.25, limit=3.0):
    """Run one command on the PS5 shell (port 2323); returns its output."""
    try:
        s = socket.create_connection((IP, 2323), timeout=5)
    except OSError:  # shsrv not loaded: callers fall back to the ELF loader
        return ""
    s.settimeout(idle)
    try:
        s.recv(65536)  # banner / prompt
    except OSError:
        pass
    s.sendall((cmd + "\n").encode())
    out, end = b"", time.time() + limit
    while time.time() < end:
        try:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
        except OSError:
            if out:
                break
    s.close()
    return out.decode("ascii", "replace")


class Udp:
    """Collects the app's UDP broadcast log on port 9999 in a background thread."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", 9999))
        self.sock.settimeout(0.2)
        self.lines, self.stop = [], False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.stop:
            try:
                data, _ = self.sock.recvfrom(4096)
                self.lines.append(data.decode("utf-8", "replace").rstrip())
            except OSError:
                pass

    def wait_for(self, pattern, timeout, start=0):
        rx, end = re.compile(pattern), time.time() + timeout
        while time.time() < end:
            for i in range(start, len(self.lines)):
                if rx.search(self.lines[i]):
                    return i
            time.sleep(0.05)
        return -1

    def close(self):
        self.stop = True


def is_running():
    out = shell("ps", 0.2, 1.5)
    return TITLE in out or not out.strip()  # a silent shell (frozen by rest mode) is treated as "maybe running"


def kill(udp=None):
    if not is_running():
        return "not running"
    f = ftp()
    ftp_put(f, "/data/kill_app.txt", TITLE.encode())
    f.quit()
    own = udp is None
    udp = udp or Udp()
    mark = len(udp.lines)
    with open(os.path.join(HERE, "m1", "killapp.elf"), "rb") as fh:
        elf = fh.read()
    s = socket.create_connection((IP, 9021), timeout=5)
    s.sendall(elf)
    s.close()
    i = udp.wait_for(r"killapp", 4, mark)
    res = udp.lines[i] if i >= 0 else "no reply"
    for _ in range(20):  # wait until the process is really gone
        if not is_running():
            break
        time.sleep(0.15)
    if own:
        udp.close()
    return res


def wsl(script):
    return subprocess.run(["wsl", "-e", "bash", "-c", script], capture_output=True, text=True)


def build():
    t0 = time.time()
    H = WSL_HERE
    r = wsl(f"""set -u
S=$HOME/.ps5stamp; mkdir -p $S
# regenerate only when an input changed
[ {H}/apply_ps5_patches.py -nt $S/patches ] && {{ python3 {H}/apply_ps5_patches.py >/dev/null || exit 1; touch $S/patches; }}
if [ ! -f {H}/ps5shim/launcher_assets.cpp ] || [ {H}/gen_launcher_assets.py -nt {H}/ps5shim/launcher_assets.cpp ]; then python3 {H}/gen_launcher_assets.py {H}/ps5shim/launcher_assets.cpp || exit 1; fi
[ {H}/gen_ps5_ninja.py -nt $S/gen ] && {{ python3 {H}/gen_ps5_ninja.py >/dev/null || exit 1; touch $S/gen; }}
cd ~/ps5build && ninja -k 0 -j 16 2>&1 | grep -E 'FAILED|error:' | head -20
test -s libgk.a || {{ echo libgk.a missing; exit 1; }}
cmp -s libgk.a ~/ogapp/vendor/libgk.a || cp libgk.a ~/ogapp/vendor/libgk.a
[ ~/ogapp/vendor/libgk.a -nt ~/ogapp/build/eboot.elf ] && touch ~/ogapp/src/ogmain.cpp  # the app build does not track the archive
cmp -s {H}/ogapp_src/ogmain.cpp ~/ogapp/src/ogmain.cpp || cp {H}/ogapp_src/* ~/ogapp/src/
cd ~/ogapp && make 2>&1 | tee ~/ogapp_make.log | grep -E 'undefined symbol|error:|Build complete' | sort | uniq -c | head -20
""")
    out = (r.stdout + r.stderr).strip()
    ok = "Build complete" in out and "FAILED" not in out and "error:" not in out.replace("Build complete", "")
    print(out if not ok else "build ok", f"({time.time() - t0:.1f}s)")
    return ok


def deploy():
    t0 = time.time()
    data = subprocess.run(["wsl", "-e", "bash", "-c", "cat ~/ogapp/dist/LAPY77001/eboot.bin"], capture_output=True).stdout
    if len(data) < 1_000_000:
        print("eboot.bin missing or too small", len(data))
        return False
    import hashlib
    digest = hashlib.sha1(data).hexdigest()
    stamp = os.path.join(HERE, ".deployed_sha1")
    if os.path.exists(stamp) and open(stamp).read().strip() == digest and "--force" not in sys.argv:
        print("eboot.bin unchanged, upload skipped")
        return True
    f = ftp()
    try:
        f.cwd("/data/homebrew/LAPY77001")
    except ftplib.error_perm:
        print("app not installed on the console - run the installer first")
        return False
    ftp_put(f, "eboot.bin", data)
    f.quit()
    open(stamp, "w").write(digest)
    print(f"deployed eboot.bin {len(data) // 1024} KiB ({time.time() - t0:.1f}s)")
    return True


def run(game=None, seconds=30, keep=False):
    udp = Udp()
    print("kill:", kill(udp))
    if game:
        f = ftp()
        ftp_put(f, "/data/opengoal/config/autolaunch.txt", game.encode())
        f.quit()
    mark = len(udp.lines)
    out = shell(f"launch {TITLE}", 0.3, 3.0)
    if not out.strip():  # the shell payload is silent (frozen by rest mode): launch through the ELF loader instead
        f = ftp()
        ftp_put(f, "/data/launch_app.txt", TITLE.encode())
        f.quit()
        with open(os.path.join(HERE, "m1", "launchapp.elf"), "rb") as fh:
            elf = fh.read()
        ls = socket.create_connection((IP, 9021), timeout=5)
        ls.sendall(elf)
        ls.close()
        time.sleep(3)
    if "0x8094000a" in out:
        print("launch refused: no PS5 profile signed in - pick a profile on the console")
        udp.close()
        return False
    t0 = time.time()
    shown, fps = mark, 0
    crashed = False
    while time.time() - t0 < seconds:
        while shown < len(udp.lines):
            line = udp.lines[shown]
            shown += 1
            if line.startswith("fps:"):
                fps += 1
            if re.search(r"fps:|CRASH|glfix: draws|launching|audio|error|fail|prof:", line, re.I) and not line.startswith("stack["):
                print(t(), line)
            if "CRASH" in line:
                crashed = True
        if crashed:
            time.sleep(1.0)  # let the register / stack lines arrive
            for l in udp.lines[shown:]:
                if l.startswith(("ucontext", "stack[")):
                    print(t(), l)
            break
        time.sleep(0.1)
    print("app:", "CRASHED" if crashed else ("running" if is_running() else "NOT RUNNING"))
    with open(os.path.join(HERE, "last_run.log"), "w", encoding="utf-8") as lf:  # full UDP log of this run
        lf.write("\n".join(udp.lines))
    if not keep:
        print("kill:", kill(udp))
    udp.close()
    return not crashed


def shot(game, times):
    """Run `game`, save frames at the given seconds, fetch them as PNG, then close the app."""
    from PIL import Image
    f = ftp()
    ftp_put(f, "/data/opengoal/config/shot.txt", " ".join(str(x) for x in times).encode())
    f.quit()
    udp = Udp()
    kill(udp)
    f = ftp()
    ftp_put(f, "/data/opengoal/config/autolaunch.txt", game.encode())
    f.quit()
    mark = len(udp.lines)
    shell(f"launch {TITLE}", 0.3, 3.0)
    got = 0
    end = time.time() + max(times) + 40
    while got < len(times) and time.time() < end:
        if udp.wait_for(r"captured", 1, mark + got) >= 0:
            got += 1
        elif udp.wait_for(r"CRASH", 0.01, mark) >= 0:
            print("CRASHED")
            break
    fps = [l for l in udp.lines[mark:] if l.startswith("fps:")]
    print("fps:", " | ".join(l[4:30].strip() for l in fps[-6:]))
    kill(udp)
    udp.close()
    f = ftp()
    for i in range(got):
        b = io.BytesIO()
        f.retrbinary(f"RETR /data/opengoal/log/shot{i}.ppm", b.write)
        b.seek(0)
        out = os.path.join(HERE, f"shot{i}.png")
        Image.open(b).convert("RGB").resize((960, 540)).save(out)
        print("saved", out)
    f.quit()


def show_log(rx):
    f = ftp()
    b = io.BytesIO()
    f.retrbinary("RETR /data/opengoal/log/ps5.log", b.write)
    f.quit()
    lines = b.getvalue().decode("utf-8", "replace").splitlines()
    start = max((i for i, l in enumerate(lines) if "opengoal-ps5: start" in l), default=0)
    pat = re.compile(rx)
    for l in lines[start:]:
        if pat.search(l):
            print(l)


def main():
    a = sys.argv[1:] or ["help"]
    cmd = a[0]
    game = a[1] if len(a) > 1 and not a[1].isdigit() else None
    secs = int(next((x for x in a[1:] if x.isdigit()), 30))
    if cmd == "build":
        sys.exit(0 if build() else 1)
    elif cmd == "deploy":
        sys.exit(0 if deploy() else 1)
    elif cmd == "run":
        sys.exit(0 if run(game, secs) else 1)
    elif cmd == "kill":
        print(kill())
    elif cmd == "go":
        if not build():
            sys.exit(1)
        # the console may not be reachable for the upload while the old build runs: close it first
        print("kill:", kill())
        if not deploy():
            sys.exit(1)
        sys.exit(0 if run(game, secs) else 1)
    elif cmd == "start":
        sys.exit(0 if run(game, 4, keep=True) else 1)
    elif cmd in ("snap", "dbg"):
        import socket as _s
        try:
            _s.create_connection(("127.0.0.1", 9997), 1).close()
        except OSError:
            subprocess.Popen([sys.executable, os.path.join(HERE, "dbg.py"), "serve"], creationflags=0x08000008, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        sys.exit(subprocess.call([sys.executable, os.path.join(HERE, "dbg.py")] + (["shot"] + a[1:] if cmd == "snap" else a[1:])))
    elif cmd == "shot":
        shot(a[1], [float(x) for x in a[2:]] or [20.0])
    elif cmd == "log":
        show_log(a[1] if len(a) > 1 else ".")
    else:
        print(__doc__)


main()
