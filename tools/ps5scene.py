#!/usr/bin/env python3
"""Scripted test scenes for the console game: load a scene through the GOAL REPL, let it settle, measure, report in a few lines.

  ps5scene.py list                       scenes
  ps5scene.py run NAME [NAME ...|all]    run scenes (starts the game with the REPL listener when needed); [--label TEXT]
  ps5scene.py compare [NAME]             latest two results per scene, side by side

Results are appended to out/scenes/results.jsonl. Jak 2 scenes only for now (Jak 1 and 3 use other continue names and objects).
Needs WSL goalc (see ps5repl.py) and the console game started with config/debugrepl.txt (this script sets it and restarts the game)."""
import json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps5live as L
import ps5repl as R

OUT = os.path.join(ROOT, "out", "scenes", "results.jsonl")
LEVELINFO = os.environ.get("PS5_GOALC_DIR", "$HOME/ingame_full") + "/goal_src/jak2/engine/level/level-info.gc"
CONTINUE = lambda n: '(start (quote play) (get-continue-by-name *game-info* "%s"))' % n
TRAFFIC = lambda lvl, dens: ('(begin (send-event *traffic-manager* (quote set-target-level) %s) '
                             '(send-event *traffic-manager* (quote set-density-factor) %s))' % (lvl, dens))


def waypoints(names):
    """(x, y, z) in game units of the named continue points, read from the Jak 2 level-info source."""
    src = R.wsl("cat %s" % LEVELINFO)
    out = []
    for n in names:
        m = re.search(r':name "%s".*?:trans \(new \'static \'vector :x ([-\d.]+) :y ([-\d.]+) :z ([-\d.]+)' % re.escape(n), src, re.S)
        if m:
            out.append(tuple(float(v) for v in m.groups()))
    return out


def teleport(p, lift=60000.0):
    return ('(let ((v (new (quote stack-no-clear) (quote vector)))) (set-vector! v %.1f %.1f %.1f 1.0) '
            '(move-to-point! (-> *target* control) v))' % (p[0], p[1] + lift, p[2]))


ENTER_BIKE = '(send-event *target* (quote change-mode) (quote pilot) #f (vehicle-type %s))'
# Fly the piloted hover bike on a circle: its position is set every frame (collision off, no crashes into buildings), so it
# sweeps over the city at a steady speed. Units: radius/height are game units (4096 per metre), rate in degrees per frame.
DRIVE_DEF = ("(defun ps5-orbit ((cx float) (cz float) (radius float) (height float) (rate float)) "
             "(let ((veh (the-as vehicle (handle->process (-> *target* pilot vehicle))))) (when veh (let* ((rb (-> veh rbody)) "
             "(a (* rate (the float (-> *display* base-clock frame-counter))))) "
             "(set-vector! (-> rb state position) (+ cx (* radius (cos (degrees a)))) height (+ cz (* radius (sin (degrees a)))) 1.0) "
             "(set-vector! (-> rb state lin-velocity) 0.0 0.0 0.0 0.0) (set-vector! (-> rb state lin-momentum) 0.0 0.0 0.0 0.0)))) 0)")


def drive_run():
    x, y, z = waypoints(["ctysluma-start"])[0]
    return ('(process-spawn-function process (lambda :behavior process () (dotimes (i 3600) (ps5-orbit %.1f %.1f (meters 400.0) %.1f 0.12) '
            '(suspend)) (none)) :name "ps5-orbit")' % (x, z, y + 150000.0))


# The REPL link drops while the drive process runs (cause not found): such scenes only read the log afterwards and the next run restarts the game.

TOUR = ["ctygena-start", "ctygenb-start", "ctygenc-start", "ctysluma-start", "ctyslumb-start", "ctyslumc-start", "ctyport-start"]
# each step: ("goal", expr, seconds to wait after) | ("tour", seconds per stop); measuring starts after the last "settle"
SCENES = {
    "city_idle": dict(steps=[("goal", CONTINUE("ctysluma-start"), 25)], measure=20,
                      doc="city start point, default traffic"),
    "city_traffic": dict(steps=[("goal", CONTINUE("ctysluma-start"), 25), ("goal", TRAFFIC("1.0", "3.0"), 15)], measure=20,
                         doc="city start point, traffic at maximum target level and density 3"),
    "zoomer_fly": dict(steps=[("goal", CONTINUE("ctysluma-start"), 25), ("goal", TRAFFIC("1.0", "3.0"), 10),
                              ("goal", ENTER_BIKE % "bikea", 6), ("goal", DRIVE_DEF, 1),
                              ("goal", drive_run, 0)], measure=40, restart_after=True, verify_move=True,
                       doc="traffic at maximum, Jak on a hover bike flown at about 50 m/s in a 400 m circle above the city for 40 s (REPL link drops, game restarts next run)"),
    "city_tour": dict(steps=[("goal", CONTINUE("ctysluma-start"), 25), ("goal", TRAFFIC("1.0", "3.0"), 10)], tour=5, measure=0,
                      doc="traffic at maximum, teleport across 7 city districts (5 s each): streaming and many models"),
}


DIRTY = False  # the previous scene left the REPL link unusable


def say(msg):
    print(msg, flush=True)


def ensure_game(force=False):
    """goalc connected to a console game that listens for it; restart the game with the listener flag when needed."""
    if R.running() and not force:
        out = R.run('(format #t "ping ~D~%" 1)', wait=2, limit=15)
        if any("ping 1" in l for l in out):
            return
    try:
        if force:
            raise SystemExit
        R.up("jak2")
        return
    except SystemExit:
        pass
    say("restarting the game with the REPL listener ...")
    # a goalc that was linked to the previous game run refuses new code ("Compilation generated code, but wasn't
    # supposed to"): start it fresh and compile the game code again
    R.wsl("pkill -x goalc; rm -f /tmp/gc.code")
    try:
        os.remove(R.flag("jak2"))
    except OSError:
        pass
    f = L.ftp()
    try:
        import io
        f.storbinary("STOR /data/opengoal/config/debugrepl.txt", io.BytesIO(b"1"))
    finally:
        f.close()
    tool = os.path.join(ROOT, "tools", "ps5.py")
    subprocess.run([sys.executable, tool, "kill"], capture_output=True, timeout=60)
    subprocess.run([sys.executable, tool, "start", "jak2"], capture_output=True, timeout=90)
    t = time.time()
    while time.time() - t < 120:  # wait for gameplay frames; never open a TCP probe to the DECI2 port
        time.sleep(5)
        try:
            if len([1 for l in L.tail(60)[1].split("\n") if l.startswith("fps:") or " fps: " in l]) >= 3:
                break
        except Exception:
            pass
    time.sleep(5)
    R.up("jak2")


def goal(expr):
    out = R.run(expr, wait=2, limit=40)
    bad = [l for l in out if "Error" in l or "error" in l.lower() and "[error]" in l]
    if bad:
        raise SystemExit("GOAL error in scene step: " + " | ".join(bad[:2])[:300])


VEH_POS = ('(let ((p (-> (the-as vehicle (handle->process (-> *target* pilot vehicle))) rbody state position))) '
           '(format #t "PS5S pos ~M ~M ~M~%" (-> p x) (-> p y) (-> p z)))')


def vehicle_pos():
    for l in R.run(VEH_POS, wait=1.5, limit=15):
        m = re.search(r"PS5S pos ([-\d.]+) ([-\d.]+) ([-\d.]+)", l)
        if m:
            return tuple(float(v) for v in m.groups())
    return None


def measure(seconds, start_size):
    time.sleep(max(seconds, 0))
    size, txt = L.since(start_size)
    return L.summary_lines(size, txt, 0)


def run_scene(name, label):
    sc = SCENES[name]
    global DIRTY
    if DIRTY:
        ensure_game(force=True)
        DIRTY = False
    say("== %s: %s" % (name, sc["doc"]))
    for kind, expr, wait in sc["steps"]:
        goal(expr() if callable(expr) else expr)
        time.sleep(wait)
    if sc.get("verify_move"):  # the REPL works for a few seconds after the drive process starts: prove the vehicle moves
        a = vehicle_pos(); time.sleep(3); b = vehicle_pos()
        if not a or not b:
            say("WARNING: could not read the vehicle position (is Jak on the bike?)")
        else:
            d = sum((x - y) ** 2 for x, y in zip(a, b)) ** .5
            say("vehicle moved %.0f m in 3 s%s" % (d, "" if d > 30 else "  WARNING: barely moving"))
    start = L.log_size()
    if "tour" in sc:
        pts = waypoints(TOUR)
        if len(pts) < 3:
            raise SystemExit("could not read the continue points from level-info.gc")
        for p in pts:
            goal(teleport(p))
            time.sleep(sc["tour"])
    lines = measure(sc["measure"], start)
    DIRTY = bool(sc.get("restart_after"))
    text = "\n".join(lines)
    fps = re.search(r"fps  min (\d+)  p5 (\d+)  median (\d+)", text)
    cpu = re.search(r"cpu ms median ([\d.]+)", text)
    over = re.search(r"over 33 ms ([\d.]+)%", text)
    hot = re.search(r"hot buckets[^:]*: (.*)", text)
    res = dict(scene=name, label=label, time=time.strftime("%Y-%m-%d %H:%M:%S"),
               fps_min=int(fps.group(1)) if fps else None, fps_p5=int(fps.group(2)) if fps else None,
               fps_median=int(fps.group(3)) if fps else None, cpu_ms=float(cpu.group(1)) if cpu else None,
               over33_pct=float(over.group(1)) if over else None, hot=hot.group(1) if hot else "",
               crash="CRASH" in text)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(res) + "\n")
    say("fps min/p5/median %s/%s/%s  cpu %s ms  over33 %s%%%s" % (res["fps_min"], res["fps_p5"], res["fps_median"], res["cpu_ms"],
                                                                 res["over33_pct"], "  CRASH" if res["crash"] else ""))
    say("hot: " + (res["hot"] or "-"))
    return res


def compare(only=None):
    rows = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []
    for name in SCENES:
        if only and name != only:
            continue
        r = [x for x in rows if x["scene"] == name][-2:]
        if len(r) < 2:
            print("%s: %d result(s), need two" % (name, len(r)))
            continue
        a, b = r
        print("%s: fps median %s -> %s, p5 %s -> %s, cpu ms %s -> %s, over33 %s%% -> %s%% (%s -> %s)" % (
            name, a["fps_median"], b["fps_median"], a["fps_p5"], b["fps_p5"], a["cpu_ms"], b["cpu_ms"],
            a["over33_pct"], b["over33_pct"], a["label"] or a["time"], b["label"] or b["time"]))


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    label = ""
    if "--label" in a:
        i = a.index("--label"); label = a[i + 1]; del a[i:i + 2]
    if a[0] == "list":
        for n, s in SCENES.items():
            print("%-14s %s" % (n, s["doc"]))
    elif a[0] == "run":
        names = list(SCENES) if "all" in a[1:] else a[1:]
        bad = [n for n in names if n not in SCENES]
        if bad or not names:
            raise SystemExit("unknown scene(s): %s (see: list)" % bad)
        ensure_game()
        for n in names:
            run_scene(n, label)
    elif a[0] == "compare":
        compare(a[1] if len(a) > 1 else None)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
