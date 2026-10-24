"""Perf suite: one game, several flag sets, each a full measurement round; prints the trace summary of each.

usage: ps5 perf suite <game> <seconds> <label> "<flags>" [<label> "<flags>" ...]
"""
import glob
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(os.path.dirname(TOOLS), "out", "perf_runs")
KEEP = re.compile(r"^frames|submit_lock|backpressure|batch submit|wait batch|wait async|wait flip|per draw|draw \(glfix|driver draw_vbo")


def main(argv):
    if len(argv) < 4 or len(argv) % 2:
        print(__doc__)
        return 2
    game, secs, rest = argv[0], argv[1], argv[2:]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for i in range(0, len(rest), 2):
        label, flags = rest[i], rest[i + 1].split()
        name = "%s_%s" % (game, label)
        subprocess.run([sys.executable, "-u", os.path.join(TOOLS, "perfround.py"), name, game, secs, "trace"] + flags,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        print("##### %s  flags: %s" % (name, " ".join(flags)))
        summary = os.path.join(RUNS, name + ".summary.txt")
        if os.path.exists(summary):
            for line in open(summary, encoding="utf-8"):
                if line.startswith("fps series"):
                    v = [float(x) for x in line.split()[2:]][-30:]
                    if v:
                        print("last-30 avg fps %.1f" % (sum(v) / len(v)))
        traces = sorted(glob.glob(os.path.join(RUNS, name + ".trace_*.bin")))
        if traces:
            r = subprocess.run([sys.executable, os.path.join(TOOLS, "trace", "stats.py"), traces[0], "-"],
                               capture_output=True, text=True, timeout=150, env=env)
            print("\n".join(l for l in (r.stdout + r.stderr).splitlines() if KEEP.search(l)))
    print("SUITEDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
