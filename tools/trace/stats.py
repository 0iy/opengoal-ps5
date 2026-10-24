#!/usr/bin/env python3
"""Convert a ps5 trace_<n>.bin (shim tracer) into Chrome/Perfetto JSON and print a per-frame breakdown.

usage: ps5 perf trace stats trace.bin [out.json | -]      ("-" = statistics only)
Open the JSON in https://ui.perfetto.dev or chrome://tracing.
Draw decomposition (nested events): 10 draw wrapper (glfix) > 11 real GL call (Mesa) > 122 driver entry > 121 hand-over to prep workers."""
import bisect
import collections
import json
import struct
import sys

NAMES = {1: "frame", 10: "draw (glfix wrapper)", 11: "real GL draw call", 121: "gate2_run (job hand-over)", 122: "driver draw_vbo",
         100: "wait batch-retire", 101: "wait frame-complete", 102: "wait flip", 103: "wait async-collect",
         110: "forced drain", 111: "batch submit", 112: "backpressure wait", 113: "submit_lock (full wait)", 114: "deferred draw refused", 115: "eligibility reject", 131: "  prepare_constant", 132: "  prepare_texture", 133: "  flush_descriptor_table", 134: "  copy_descriptors", 135: "  retain_resources", 136: "  multidraw_eligible"}
GLCALLS = ["glTexImage2D", "glTexSubImage2D", "glTexImage1D", "glTexSubImage1D", "glClear", "glBlitFramebuffer", "glGenerateMipmap",
           "glReadPixels", "glFinish", "glFlush", "glFramebufferTexture2D", "glMapBufferRange", "glUnmapBuffer", "glCopyTexSubImage2D"]
for i, n in enumerate(GLCALLS):
    NAMES[200 + i] = n


def load(path):
    b = open(path, "rb").read()
    magic, count, ver, tsc_per_ns, tsc0, ns0 = struct.unpack_from("<8sIIdQQ", b, 0)
    assert magic == b"PS5TRC01", magic
    evs = list(struct.iter_unpack("<QQIIQ", b[40:40 + count * 32]))
    return evs, tsc_per_ns, tsc0, ns0


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else path + ".json"
    evs, k, tsc0, ns0 = load(path)

    def is_ns(ev):
        return ev >= 100 and ev != 121 and ev != 122 or ev in (121, 122)

    tids = {}
    rows = []
    for tsc, dur, ev, tid, a in evs:
        if ev >= 100:  # driver and GL-call events carry CLOCK_MONOTONIC ns
            t, d = tsc, dur
        else:  # shim events carry the TSC
            t = ns0 + (tsc - tsc0) / k
            d = dur if ev == 1 else dur / k
        tids.setdefault(tid, len(tids) + 1)
        rows.append((t, d, ev, tid, a))
    if out != "-":
        trace = []
        for t, d, ev, tid, a in rows:
            start = t - d if ev == 1 else t
            trace.append({"name": NAMES.get(ev, "ev%d" % ev), "ph": "X", "ts": (start - ns0) / 1000.0, "dur": d / 1000.0, "pid": 1,
                          "tid": tids[tid], "args": {"a": a}})
        for tid, n in tids.items():
            trace.append({"name": "thread_name", "ph": "M", "pid": 1, "tid": n, "args": {"name": "thread %x" % tid}})
        json.dump({"traceEvents": trace}, open(out, "w"))
        print("wrote", out, len(evs), "events,", len(tids), "threads")

    frames = sorted((t, d, a, tid) for t, d, ev, tid, a in rows if ev == 1)
    if len(frames) < 3:
        print("not enough frames")
        return
    render_tid = collections.Counter(tid for *_, tid in frames).most_common(1)[0][0]
    print("render thread: %x" % render_tid)
    rr = sorted(r for r in rows if r[3] == render_tid and r[2] != 1)
    times = [r[0] for r in rr]
    per = []
    for i in range(1, len(frames)):
        t_end, interval, fno, _ = frames[i]
        lo = bisect.bisect_left(times, t_end - interval)
        hi = bisect.bisect_left(times, t_end)
        agg, cnt = collections.Counter(), collections.Counter()
        for t, d, ev, tid, a in rr[lo:hi]:
            agg[ev] += d
            cnt[ev] += 1
        per.append((interval, fno, agg, cnt))
    n = len(per)
    avg = lambda e: sum(p[2][e] for p in per) / n / 1e6
    print("frames %d, average frame %.2f ms (%.1f fps)" % (n, sum(p[0] for p in per) / n / 1e6, 1e9 / (sum(p[0] for p in per) / n)))
    print("%-28s %10s %8s" % ("event (render thread)", "ms/frame", "calls"))
    for e in sorted({e for _, _, a, _ in per for e in a}):
        print("%-28s %10.2f %8.1f" % (NAMES.get(e, e), avg(e), sum(p[3][e] for p in per) / n))
    if avg(11) > 0:
        print("draw decomposition per frame (ms): glfix pre/post %.2f | Mesa state tracker %.2f | driver state build %.2f | job hand-over %.2f (of which collect-spin %.2f) | rest of frame %.2f"
              % (avg(10) - avg(11), avg(11) - avg(122), avg(122) - avg(121), avg(121), avg(103), sum(p[0] for p in per) / n / 1e6 - avg(10)))
        calls = sum(p[3][10] for p in per) / n
        print("per draw (us): total %.1f | glfix %.1f | Mesa %.1f | driver %.1f | hand-over %.1f" %
              (avg(10) * 1000 / calls, (avg(10) - avg(11)) * 1000 / calls, (avg(11) - avg(122)) * 1000 / calls,
               (avg(122) - avg(121)) * 1000 / calls, avg(121) * 1000 / calls))
    for ev, label in ((114, "deferred draw refused (flags: 1 multi, 2 blitter, 4 not eligible | mode<<8 | index_size<<16)"), (115, "eligibility reject bits (1 input, 2 shader, 4 query, 8 framebuffer, 16 depth, 32 vertex, 64 texture)")):
        h = collections.Counter(a for t, d, e, tid, a in rows if e == ev)
        if h:
            print(label, "per frame:", [("%x" % a, round(c / n, 2)) for a, c in h.most_common(8)])
    print("worst 6 frames:")
    for interval, fno, agg, cnt in sorted(per, reverse=True)[:6]:
        top = ", ".join("%s %.1f" % (NAMES.get(e, e), v / 1e6) for e, v in agg.most_common(5) if e not in (11, 121, 122))
        print("  frame %d  %.1f ms  [%s]" % (fno, interval / 1e6, top))
    forced = collections.Counter()
    for t, d, ev, tid, a in rows:
        if ev in (110, 113):
            forced[(ev, a)] += d
    if forced:
        print("full waits by caller (event, address, total ms):", [(e, "%x" % a, round(v / 1e6, 1)) for (e, a), v in forced.most_common(8)])


main()
