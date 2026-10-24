#!/usr/bin/env python3
"""glGenerateMipmap cost split from a ps5 trace (agent mipcost).  usage: trace_mip.py trace.bin [trace.bin ...]
Per frame on the render thread: total glGenerateMipmap time (event 206), the part spent in backpressure waits (112)
inside those calls, the remaining CPU, batch submits (111, of which async-collect 103), blit draws (122 inside the calls),
call count; plus, if the trace has them, driver events 137 (ps5_generate_mipmap), 138 (ps5_blit_gpu_color),
139 (util_blitter_blit_generic), 140 (lazy flush, PS5_MIPFAST&1)."""
import bisect
import collections
import struct
import sys


def load(path):
    b = open(path, "rb").read()
    magic, count, ver, tsc_per_ns, tsc0, ns0 = struct.unpack_from("<8sIIdQQ", b, 0)
    assert magic == b"PS5TRC01", magic
    return list(struct.iter_unpack("<QQIIQ", b[40:40 + count * 32])), tsc_per_ns, tsc0, ns0


for path in sys.argv[1:]:
    evs, k, tsc0, ns0 = load(path)
    rows = []
    for tsc, dur, ev, tid, a in evs:  # events >= 100 carry CLOCK_MONOTONIC ns, shim events the TSC (see trace2json.py)
        rows.append((tsc, dur, ev, tid, a) if ev >= 100 else (ns0 + (tsc - tsc0) / k, dur if ev == 1 else dur / k, ev, tid, a))
    frames = [r for r in rows if r[2] == 1]
    rt = collections.Counter(r[3] for r in frames).most_common(1)[0][0]
    rr = sorted(r for r in rows if r[3] == rt and r[2] != 1)
    times = [r[0] for r in rr]
    nf = len(frames) - 1
    gm = [r for r in rr if r[2] == 206]
    acc = collections.Counter()
    for t, d, ev, tid, a in gm:
        acc["total"] += d
        for x in rr[bisect.bisect_left(times, t):bisect.bisect_right(times, t + d)]:
            if x[0] + x[1] <= t + d + 2000 and x[2] in (111, 103, 112, 122):
                acc[x[2]] += x[1] if x[2] != 122 else 1e6  # 122 counted as draws (x1e6 so /1e6 below gives a count)
    ms = lambda v: v / nf / 1e6
    print("%s: frames %d, calls/frame %.1f | glGenerateMipmap %.2f ms/frame = backpressure %.2f + CPU %.2f "
          "(batch submit %.2f, of which async-collect %.2f) | blit draws/frame %.1f"
          % (path.split("/")[-1], nf, len(gm) / nf, ms(acc["total"]), ms(acc[112]), ms(acc["total"] - acc[112]),
             ms(acc[111]), ms(acc[103]), ms(acc[122])))
    for ev, name in ((137, "generate_mipmap"), (138, "blit_gpu_color"), (139, "blit_generic"), (140, "lazy flush")):
        d = [r[1] for r in rr if r[2] == ev]
        if d:
            print("   event %d %-16s %.3f ms/frame, %.1f calls/frame, %.1f us/call" % (ev, name, sum(d) / nf / 1e6, len(d) / nf, sum(d) / len(d) / 1e3))
