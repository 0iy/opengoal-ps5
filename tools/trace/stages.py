#!/usr/bin/env python3
"""Per-draw stage breakdown from driver trace event 130 (driver patch, see docs/PERFORMANCE.md). usage: ps5 perf trace stages trace.bin [trace2.bin ...]
Prints average and p95 microseconds per draw for each stage of ps5_draw_vbo_locked, per frame totals, and the share of the driver call."""
import sys

import struct

STAGES = ["bounds+index scan", "framebuffer", "state+variants+vertex desc", "prepare (consts, textures, flushes)",
          "gate2 setters+targets+depth", "gate2_run (hand-over)"]


def load(path):  # same format as stats.load (that module runs main() on import)
    b = open(path, "rb").read()
    magic, count, _ver, k, tsc0, ns0 = struct.unpack_from("<8sIIdQQ", b, 0)
    assert magic == b"PS5TRC01", magic
    return list(struct.iter_unpack("<QQIIQ", b[40:40 + count * 32])), k, tsc0, ns0


def main():
    for path in sys.argv[1:]:
        evs, _k, _t0, _ns0 = load(path)
        rows = [(a, dur) for _t, dur, ev, _tid, a in evs if ev == 130]
        frames = sum(1 for e in evs if e[2] == 1) or 1
        if not rows:
            print(path, ": no event 130 (driver patch 56 not applied, or trace not armed)")
            continue
        cols = [sorted(((a >> (10 * i)) & 1023) / 10.0 for a, _ in rows) for i in range(6)]
        tot = sorted(d / 1000.0 for _, d in rows)
        n = len(rows)
        print("%s: %d draws traced, %d frames, %.0f draws/frame" % (path, n, frames, n / frames))
        print("  %-38s %9s %9s %12s" % ("stage", "avg us", "p95 us", "ms/frame"))
        for name, c in zip(STAGES, cols):
            print("  %-38s %9.2f %9.2f %12.2f" % (name, sum(c) / n, c[int(n * 0.95)], sum(c) / frames / 1000.0))
        print("  %-38s %9.2f %9.2f %12.2f" % ("whole ps5_draw_vbo_locked", sum(tot) / n, tot[int(n * 0.95)], sum(tot) / frames / 1000.0))


if __name__ == "__main__":
    main()
