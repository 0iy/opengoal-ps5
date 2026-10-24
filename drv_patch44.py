#!/usr/bin/env python3
"""Driver patch 44 (diagnostic A/B): ps5_generate_mipmap falls back to a CPU filter for small levels (the GPU blit path
rejects them) and that path drains the whole GPU pipeline (4 times per frame in Jak 2, ~13 ms per frame of waiting).
With PS5_MIP_SKIP_CPU set the CPU level is skipped (stale small mips) so the gain of removing the drain can be measured."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_MIP_SKIP_CPU" in s:
    print("already patched")
    raise SystemExit

old = """         if (mip_stat)
            ++mip_stat->cpu_levels;
         if (!ps5_mipmap_sync_cpu) {"""
new = """         if (mip_stat)
            ++mip_stat->cpu_levels;
         {
            static int skip_cpu_mip = -1;
            if (skip_cpu_mip < 0)
               skip_cpu_mip = getenv("PS5_MIP_SKIP_CPU") != NULL;
            if (skip_cpu_mip)
               continue;
         }
         if (!ps5_mipmap_sync_cpu) {"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("ok")
