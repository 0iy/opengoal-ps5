#!/usr/bin/env python3
"""Driver patch 15: with PS5_NO_BUFFER_FLUSH set, skip the per-pass CPU cache flush of depth/stencil backing that the
GPU owns (no CPU staging, no external CPU access). ~13 MB of flushing per Jak 3 frame."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_depth_flush_needed" in s:
    print("already patched"); raise SystemExit
anchor = "struct ps5_batch_flush_cache {"
helper = """static bool
ps5_depth_flush_needed(const struct ps5_resource *depth)
{
   static int skip = -1;
   if (skip < 0)
      skip = getenv("PS5_NO_BUFFER_FLUSH") != NULL;
   return !skip || depth->external_cpu_access || depth->depth_staging_size;
}

"""
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)
old = "      const bool flush_depth_stencil = native.depth_control != 0;"
new = "      const bool flush_depth_stencil = native.depth_control != 0 && ps5_depth_flush_needed(depth);"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("depth flush toggle added")
