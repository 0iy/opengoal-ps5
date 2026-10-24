#!/usr/bin/env python3
"""Read-only trace analysis for the multidraw/queue-depth work. usage: ps5 perf trace multidraw trace.bin   (never writes anything)
Prints per frame: batch submits, draws per batch, backpressure waits (count, mean/max single wait), full submit_lock waits, and
flush causes (trace event 116 caller address from driver patch 53, 114 = multi-draw/ineligible refusal, 113 = submit_lock)."""
import bisect, collections, struct, sys


def load(path):
    b = open(path, "rb").read()
    magic, count, ver, k, tsc0, ns0 = struct.unpack_from("<8sIIdQQ", b, 0)
    assert magic == b"PS5TRC01", "not a binary trace (%r)" % magic
    rows = []
    for tsc, dur, ev, tid, a in struct.iter_unpack("<QQIIQ", b[40:40 + count * 32]):
        if ev >= 100:
            t, d = tsc, dur
        else:
            t = ns0 + (tsc - tsc0) / k
            d = dur if ev == 1 else dur / k
        rows.append((t, d, ev, a))
    rows.sort()
    return rows


def main():
    rows = load(sys.argv[1])
    nfr = sum(1 for r in rows if r[2] == 1)
    ends = [t for t, d, ev, a in rows if ev == 1]
    draws = [t for t, d, ev, a in rows if ev == 10]
    sub = [t for t, d, ev, a in rows if ev == 111]
    bp = [d / 1e6 for t, d, ev, a in rows if ev == 112]
    sl = [d / 1e6 for t, d, ev, a in rows if ev == 113]
    print("frames %d | submits/frame %.1f | draws/batch %.2f | backpressure %.2f/frame, %.2f ms/frame, mean %.2f max %.2f ms | submit_lock %.2f/frame %.2f ms/frame" % (
        nfr, len(sub) / nfr, len(draws) / max(len(sub), 1), len(bp) / nfr, sum(bp) / nfr, sum(bp) / max(len(bp), 1), max(bp or [0]),
        len(sl) / nfr, sum(sl) / nfr))
    hist = collections.Counter(bisect.bisect(draws, sub[i]) - bisect.bisect(draws, sub[i - 1]) for i in range(1, len(sub)))
    print("draws between submits (0,1,2,3-4,5-8,9-16,17-64,65+):", [sum(v for k, v in hist.items() if lo <= k <= hi) for lo, hi in
          ((0, 0), (1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 64), (65, 10 ** 9))])
    cause, pending = collections.Counter(), None
    for t, d, ev, a in rows:
        if ev in (113, 114, 116):
            pending = (ev, a)
        elif ev == 111:
            cause[pending or (0, 0)] += 1
            pending = None
    print("submit causes per frame (event/arg; 116 arg = caller address, resolve with the driver .map/addr2line; 0 = full batch or other):")
    for (ev, a), n in cause.most_common(10):
        print("  ev%d %#x  %.1f/frame" % (ev, a & 0xffffffffffff, n / nfr))


if __name__ == "__main__":
    main()
