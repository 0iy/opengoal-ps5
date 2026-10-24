#!/usr/bin/env python3
"""Gaps in the render thread's instrumented activity per frame (read only). A gap = time between the end of one top-level event
(10 draw wrapper, 100 retire wait outside a draw, 102 flip, 200+ GL calls outside a draw, 110/113) and the start of the next.
Large gaps in slow frames with no wait event = game code (EE) or OS descheduling of the render thread.
usage: spikes_gaps.py [trace.bin ...]"""
import bisect, collections, glob, os, sys
sys.argv, args = sys.argv[:1], sys.argv[1:]
import importlib.util
spec = importlib.util.spec_from_file_location("sa", os.path.join(os.path.dirname(os.path.abspath(__file__)), "spikes_analyze.py"))
src = open(spec.origin).read().replace("\nmain()\n", "\n")
ns = {"__name__": "sa", "__file__": spec.origin}
exec(compile(src, spec.origin, "exec"), ns)
load, RUNS = ns["load"], ns["RUNS"]
HERE = os.path.dirname(os.path.abspath(__file__))
paths = args or [glob.glob(os.path.join(HERE, "perf_runs", "jak3_%s.trace_*.bin" % r))[0] for r in RUNS]
TOP = lambda e: e == 10 or e in (102, 110, 113) or 200 <= e < 214 or e == 100
slow_gap, norm_gap, n_slow, n_norm = [], [], 0, 0
for p in paths:
    rows = load(p)
    fr = sorted((t, d) for t, d, e, tid, a in rows if e == 1)
    top = sorted((t, d, e) for t, d, e, tid, a in rows if TOP(e))
    times = [x[0] for x in top]
    print("==", os.path.basename(p).split(".")[0])
    for t_end, iv in fr[1:]:
        lo, hi = bisect.bisect_left(times, t_end - iv), bisect.bisect_left(times, t_end)
        evs = top[lo:hi]
        # merge into busy intervals
        busy_end, gaps = t_end - iv, []
        for t, d, e in evs:
            if t > busy_end:
                gaps.append((t - busy_end, busy_end))
            busy_end = max(busy_end, t + d)
        gaps.append((t_end - busy_end, busy_end))
        g = max(gaps)
        if iv > 20e6:
            n_slow += 1
            slow_gap.append(g[0] / 1e6)
            if g[0] > 5e6:
                print("   slow %.1f ms: biggest gap %.1f ms at +%.1f ms into frame; gaps>1ms: %s" % (iv / 1e6, g[0] / 1e6, (g[1] - (t_end - iv)) / 1e6,
                      [round(x[0] / 1e6, 1) for x in gaps if x[0] > 1e6]))
        elif iv < 18e6:
            n_norm += 1
            norm_gap.append(g[0] / 1e6)
f = lambda v: "n=%d median %.1f p90 %.1f max %.1f" % (len(v), sorted(v)[len(v) // 2], sorted(v)[int(len(v) * .9)], max(v))
print("biggest render-thread gap per frame: slow frames", f(slow_gap), "| normal frames", f(norm_gap))

# exclusive classification of slow frames (>20 ms): worker stall (collect>=3), GPU wait (retire/backpressure>=2 ms), render-thread gap >= 10 ms, other
cls = collections.Counter(); lost = collections.Counter()
for p in paths:
    rows = load(p)
    fr = sorted((t, d) for t, d, e, tid, a in rows if e == 1)
    ev = sorted((t, d, e) for t, d, e, tid, a in rows if e in (100, 103, 111) or TOP(e))
    times = [x[0] for x in ev]
    for t_end, iv in fr[1:]:
        if iv <= 20e6:
            continue
        lo, hi = bisect.bisect_left(times, t_end - iv), bisect.bisect_left(times, t_end)
        s = collections.Counter()
        for t, d, e in ev[lo:hi]:
            if e in (100, 103, 111):
                s[e] += d
        busy_end, gap = t_end - iv, 0
        for t, d, e in ev[lo:hi]:
            if TOP(e):
                gap = max(gap, t - busy_end); busy_end = max(busy_end, t + d)
        gap = max(gap, t_end - busy_end)
        k = "worker stall (collect>=3ms)" if s[103] >= 3e6 else "GPU wait (retire>=2ms)" if s[100] >= 2e6 else "render-thread gap>=10ms (game code/OS)" if gap >= 10e6 else "other"
        cls[k] += 1; lost[k] += iv / 1e6 - 16.67
for k in cls: print("%-42s %2d frames, %4.0f ms lost" % (k, cls[k], lost[k]))
