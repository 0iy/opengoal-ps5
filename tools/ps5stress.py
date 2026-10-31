#!/usr/bin/env python3
"""Extreme-condition stress test for Jak 1, 2 and 3 on the console: load one continue point per level in a row (every load
streams a new level), let each settle, measure gameplay frames there, watch for crashes. Jak 2 also runs with traffic at maximum.

  ps5stress.py run [jak1 jak2 jak3] [--settle S] [--measure S] [--levels N]
  ps5stress.py report            last result per game from out/stress/results.jsonl

Each level: load, wait `settle` seconds (loading screen and streaming), then `measure` seconds of frames. Reported per game:
share of frames under 33 ms and under 20 ms (from the per-3-s fps samples and the slow-frame counters), worst frame, crashes.
Needs WSL goalc (ps5repl.py); restarts the game with the REPL listener (config/debugrepl.txt, removed again at the end)."""
import io, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps5live as L
import ps5repl as R

OUT = os.path.join(ROOT, "out", "stress", "results.jsonl")
SRC = os.environ.get("PS5_GOALC_DIR", "$HOME/ingame_full") + "/goal_src/%s/engine/level/level-info.gc"
SKIP = re.compile(r"^(title|demo|test|halfpipe|game|intro|training|vinroom)")
TRAFFIC = ('(begin (send-event *traffic-manager* (quote set-target-level) 1.0) '
           '(send-event *traffic-manager* (quote set-density-factor) 3.0))')


def say(m):
    print(m, flush=True)


def continues(game, n):
    """One '<level>-start' continue point per level, spread over the game, at most n."""
    names = re.findall(r':name "([a-z0-9-]+-start)"', R.wsl("cat " + SRC % game))
    seen, out = set(), []
    for x in names:
        lev = x.rsplit("-start", 1)[0]
        if SKIP.match(lev) or "test" in x or lev in seen:
            continue
        seen.add(lev)
        out.append(x)
    if len(out) > n:
        step = len(out) / n
        out = [out[int(i * step)] for i in range(n)]
    return out


def ftp_put(name, data):
    f = L.ftp()
    try:
        if data is None:
            try:
                f.delete("/data/opengoal/config/" + name)
            except Exception:
                pass
        else:
            f.storbinary("STOR /data/opengoal/config/" + name, io.BytesIO(data))
    finally:
        f.close()


def start_game(game):
    ftp_put("debugrepl.txt", b"1")
    R.wsl("pkill -x goalc; rm -f /tmp/gc.code")
    try:
        os.remove(R.flag(game))
    except OSError:
        pass
    tool = os.path.join(ROOT, "tools", "ps5.py")
    subprocess.run([sys.executable, tool, "kill"], capture_output=True, timeout=60)
    subprocess.run([sys.executable, tool, "start", game], capture_output=True, timeout=90)
    t = time.time()
    while time.time() - t < 150:  # wait for frames; never probe the DECI2 port
        time.sleep(5)
        try:
            if len([1 for l in L.tail(60)[1].split("\n") if l.startswith("fps:")]) >= 3:
                break
        except Exception:
            pass
    time.sleep(5)
    R.up(game)


def frame_stats(txt):
    """fps samples (3 s windows) and slow-frame counters of a log segment."""
    fps = [float(x) for x in re.findall(r"^fps: ([\d.]+)", txt, re.M)]
    over = re.findall(r"frametime: max ([\d.]+) ms, frames over 20 ms: (\d+), over 33 ms: (\d+) \(of (\d+)\)", txt)
    n = sum(int(o[3]) for o in over)
    o20 = sum(int(o[1]) for o in over)
    o33 = sum(int(o[2]) for o in over)
    worst = max([float(o[0]) for o in over] or [0])
    return dict(fps_min=min(fps or [0]), fps_median=sorted(fps)[len(fps) // 2] if fps else 0, frames=n,
                under33=100.0 * (n - o33) / n if n else None, under20=100.0 * (n - o20) / n if n else None,
                worst_ms=worst, crash="CRASH" in txt)


def run_game(game, settle, measure, nlev):
    say("== %s: starting with the REPL listener" % game)
    start_game(game)
    levels = continues(game, nlev)
    say("levels (%d): %s" % (len(levels), " ".join(levels)))
    per, total_txt = [], ""
    for c in levels:
        R.run('(start (quote play) (get-continue-by-name *game-info* "%s"))' % c, wait=2, limit=30)
        time.sleep(settle)
        if game == "jak2":
            R.run(TRAFFIC, wait=1, limit=15)
        start = L.log_size()
        time.sleep(measure)
        _, txt = L.since(start)
        total_txt += txt
        s = frame_stats(txt)
        s["level"] = c
        per.append(s)
        say("  %-26s fps min %4.0f median %4.0f  under33 %s%%  worst %5.1f ms%s" % (
            c, s["fps_min"], s["fps_median"], "%.1f" % s["under33"] if s["under33"] is not None else "-", s["worst_ms"],
            "  CRASH" if s["crash"] else ""))
        if s["crash"]:
            break
    tot = frame_stats(total_txt)
    res = dict(game=game, time=time.strftime("%Y-%m-%d %H:%M:%S"), levels=len(per), per_level=per, **tot)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(res) + "\n")
    say("%s total: %d frames, under 33 ms %.2f%%, under 20 ms %.2f%%, fps min %.0f, worst %.1f ms, crash %s" % (
        game, tot["frames"], tot["under33"] or 0, tot["under20"] or 0, tot["fps_min"], tot["worst_ms"], tot["crash"]))
    return res


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    opt = {"--settle": 14, "--measure": 10, "--levels": 14}
    for k in list(opt):
        if k in a:
            i = a.index(k)
            opt[k] = int(a[i + 1])
            del a[i:i + 2]
    if a[0] == "run":
        games = a[1:] or ["jak1", "jak2", "jak3"]
        try:
            for g in games:
                run_game(g, opt["--settle"], opt["--measure"], opt["--levels"])
        finally:
            ftp_put("debugrepl.txt", None)
    elif a[0] == "report":
        rows = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
        last = {}
        for r in rows:
            last[r["game"]] = r
        for g, r in last.items():
            print("%s %s: %d levels, %d frames, under 33 ms %.2f%%, under 20 ms %.2f%%, worst %.1f ms, crash %s" % (
                g, r["time"], r["levels"], r["frames"], r["under33"] or 0, r["under20"] or 0, r["worst_ms"], r["crash"]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
