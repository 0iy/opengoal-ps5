#!/usr/bin/env python3
"""Slow-frame analysis of PS5 shim tracer binaries (read only; writes nothing).
usage: spikes_analyze.py [trace.bin ...]   (default: the 7 asyncmultidraw Jak 3 runs in perf_runs/)
Reports per run and pooled: slow frames (> 20 ms) and which events are present, single-wait duration histograms,
coincidence of async-collect (103) and batch-submit (111) spikes, and the phase of long waits modulo the scheduler tick."""
import bisect, collections, glob, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = ["q0", "q1", "q2", "q16x128", "r1440", "r4k", "s1_amd"]
NAMES = {100: "retire", 103: "collect", 111: "submit", 112: "backpr", 113: "sublock", 110: "drain", 102: "flip", 206: "genmip",
         203: "texsub2d", 204: "clear", 205: "blit", 202: "teximg1d"}  # 140 (worker job, patch 60) is reported separately
TICK = 7.87  # ms, measured scheduler period
SPIKE = 1.0  # ms: single event counted as a "spike"


def load(path):
    b = open(path, "rb").read()
    magic, count, ver, k, tsc0, ns0 = struct.unpack_from("<8sIIdQQ", b, 0)
    assert magic == b"PS5TRC01", magic
    rows = []
    for tsc, dur, ev, tid, a in struct.iter_unpack("<QQIIQ", b[40:40 + count * 32]):
        if ev >= 100:
            rows.append((tsc, dur, ev, tid, a))
        else:
            rows.append((ns0 + (tsc - tsc0) / k, dur if ev == 1 else dur / k, ev, tid, a))
    return rows


def frames_of(rows):
    fr = sorted((t, d, a) for t, d, ev, tid, a in rows if ev == 1)  # t = end of frame, d = interval
    ev_ = sorted((t, d, e) for t, d, e, tid, a in rows if e in NAMES)
    times = [e[0] for e in ev_]
    out = []
    for t_end, iv, fno in fr[1:]:
        lo, hi = bisect.bisect_left(times, t_end - iv), bisect.bisect_left(times, t_end)
        out.append((t_end, iv, ev_[lo:hi]))
    return out


def hist(vals, edges):
    h = collections.Counter(bisect.bisect_right(edges, v) for v in vals)
    return " ".join("%s:%d" % (("<%g" % edges[0]) if i == 0 else (">=%g" % edges[-1]) if i == len(edges) else "%g-%g" % (edges[i - 1], edges[i]), h[i])
                    for i in range(len(edges) + 1) if h[i])


def main():
    paths = sys.argv[1:] or [glob.glob(os.path.join(HERE, "perf_runs", "jak3_%s.trace_*.bin" % r))[0] for r in RUNS]
    pool_wait = collections.defaultdict(list)
    wjobs = []
    pool_slow = []
    total_frames, total_s = 0, 0.0
    for p in paths:
        rows = load(p)
        wjobs += [(d / 1e6, a, t) for t, d, e, tid, a in rows if e == 140]
        fr = frames_of([r for r in rows if r[2] != 140])
        n = len(fr)
        secs = sum(f[1] for f in fr) / 1e9
        slow = [f for f in fr if f[1] > 20e6]
        vslow = [f for f in fr if f[1] > 33e6]
        total_frames += n
        total_s += secs
        print("== %s: %d frames %.2f s %.1f fps | >20 ms: %d (%.1f per 3 s) | >33 ms: %d | slow-frame ms lost vs 16.7: %.0f of %.0f" % (
            os.path.basename(p).split(".")[0], n, secs, n / secs, len(slow), len(slow) * 3 / secs, len(vslow),
            sum(f[1] / 1e6 - 16.67 for f in slow), sum(f[1] / 1e6 - 16.67 for f in fr if f[1] > 16.67e6)))
        for t_end, iv, evs in sorted(slow, key=lambda f: -f[1])[:8]:
            agg = collections.defaultdict(float)
            mx = collections.defaultdict(float)
            for t, d, e in evs:
                agg[NAMES[e]] += d / 1e6
                mx[NAMES[e]] = max(mx[NAMES[e]], d / 1e6)
            sp = {NAMES[e] for t, d, e in evs if d > SPIKE * 1e6}
            print("   %.1f ms  sum[%s]  max[%s]" % (iv / 1e6,
                  " ".join("%s %.1f" % kv for kv in sorted(agg.items(), key=lambda x: -x[1]) if kv[1] >= 0.3),
                  " ".join("%s %.1f" % kv for kv in sorted(mx.items(), key=lambda x: -x[1]) if kv[1] >= 1)))
            pool_slow.append((iv / 1e6, agg, sp))
        for t_end, iv, evs in fr:
            for t, d, e in evs:
                if d >= 0.5e6:
                    pool_wait[e].append((d / 1e6, ((t - evs[0][0]) / 1e6) if False else t))
    print("\n== pooled over %d frames, %.1f s" % (total_frames, total_s))
    # slow-frame table: which event carries the excess
    cols = ["retire", "collect", "submit", "backpr", "genmip", "sublock", "drain", "flip"]
    print("slow frames (>20 ms): %d; frames where event total >= 3 ms:" % len(pool_slow))
    for c in cols:
        have = [s for s in pool_slow if s[1].get(c, 0) >= 3]
        print("  %-8s %3d frames, mean %.1f ms in those" % (c, len(have), sum(s[1][c] for s in have) / len(have) if have else 0))
    both = sum(1 for s in pool_slow if s[1].get("collect", 0) >= 3 and s[1].get("submit", 0) >= 3)
    print("  collect>=3 and submit>=3 in the same slow frame: %d; collect only %d; submit only %d; neither %d" % (
        both, sum(1 for s in pool_slow if s[1].get("collect", 0) >= 3 and s[1].get("submit", 0) < 3),
        sum(1 for s in pool_slow if s[1].get("submit", 0) >= 3 and s[1].get("collect", 0) < 3),
        sum(1 for s in pool_slow if s[1].get("collect", 0) < 3 and s[1].get("submit", 0) < 3)))
    print("  slow frames with no single event >= 3 ms:", sum(1 for s in pool_slow if not any(v >= 3 for v in s[1].values())))
    edges = [0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20]
    print("\nsingle-event duration histogram (ms bins, events >= 0.5 ms, all frames):")
    for e in (103, 111, 112, 100, 206):
        v = [d for d, t in pool_wait[e]]
        print("  %-8s n=%4d max %.1f  %s" % (NAMES[e], len(v), max(v) if v else 0, hist(v, edges)))
    fine = collections.Counter(round(d * 4) / 4 for d, t in pool_wait[100])
    print("\nretire-wait (100) in 0.25 ms bins (steps of one 1 ms sleep + 0.2 ms spin + wake-up = ~1.2 ms mean sleep granularity, not 7.87):")
    print("  " + " ".join("%.2f:%d" % kv for kv in sorted(fine.items())))
    print("\nclusters at multiples of %.2f ms (events >= 3 ms; residue of d mod tick, tolerance 1 ms, 0 = exact multiple):" % TICK)
    for e in (103, 111, 112, 100, 206):
        v = [d for d, t in pool_wait[e] if d >= 3]
        near = [d for d in v if min(d % TICK, TICK - d % TICK) < 1.0]
        print("  %-8s n=%3d  within 1 ms of k*tick: %d (expected by chance %.0f%%)  residues: %s" % (
            NAMES[e], len(v), len(near), 100 * 2 / TICK, " ".join("%.1f" % (d % TICK) for d in sorted(v)[:40])))
    # long waits per second of trace (all runs), and co-occurrence in time within 2 ms between collect and submit spikes
    big = collections.defaultdict(list)
    for e in (103, 111):
        big[e] = sorted(t for d, t in pool_wait[e] if d >= 3)
    co = 0
    for t in big[103]:
        i = bisect.bisect_left(big[111], t - 12e6)
        if i < len(big[111]) and big[111][i] < t + 12e6:
            co += 1
    print("\nspikes >=3 ms: collect %d, submit %d; collect spikes with a submit spike within 12 ms: %d" % (len(big[103]), len(big[111]), co))
    print("long events (>= 3 ms) per 3 s: " + ", ".join("%s %.1f" % (NAMES[e], sum(1 for d, t in pool_wait[e] if d >= 3) * 3 / total_s) for e in (103, 111, 112, 100, 206)))
    if wjobs:  # patch 60 PS5_WORKER_DIAG: slow prep jobs; arg = worker | nivcsw<<8 | nvcsw<<24 | pair_created<<40
        print("\nslow prep jobs (event 140): %d" % len(wjobs))
        pre = sum(1 for d, a, t in wjobs if (a >> 8) & 0xffff)
        new = sum(1 for d, a, t in wjobs if (a >> 40) & 1)
        print("  preempted (nivcsw>0): %d, shader pair created: %d, neither: %d" % (pre, new, sum(1 for d, a, t in wjobs if not ((a >> 8) & 0xffff) and not (a >> 40) & 1)))
        for d, a, t in sorted(wjobs, reverse=True)[:12]:
            print("  %.1f ms worker %d nivcsw %d nvcsw %d pair %d" % (d, a & 0xff, (a >> 8) & 0xffff, (a >> 24) & 0xffff, (a >> 40) & 1))


main()
