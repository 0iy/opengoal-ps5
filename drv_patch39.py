#!/usr/bin/env python3
"""Driver patch 39 (diagnostic): time the u_blitter calls inside the GPU depth/stencil and color clears."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_cs_depth_ns" in s:
    print("already patched")
    raise SystemExit

old = """      util_blitter_clear_depth_stencil(blitter, &surface, buffers, depth, stencil,
                                        left, bottom, right - left, top - bottom);"""
new = """      {
         const int64_t bt0 = os_time_get_nano();
         util_blitter_clear_depth_stencil(blitter, &surface, buffers, depth, stencil,
                                          left, bottom, right - left, top - bottom);
         ps5_cs_depth_ns += (unsigned long long)(os_time_get_nano() - bt0);
         ++ps5_cs_depth_n;
      }"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """         util_blitter_clear(blitter, context->framebuffer.width, context->framebuffer.height,
                            1, PIPE_CLEAR_COLOR0, &quantized, 0, 0, false);"""
new = """         const int64_t bt0 = os_time_get_nano();
         util_blitter_clear(blitter, context->framebuffer.width, context->framebuffer.height,
                            1, PIPE_CLEAR_COLOR0, &quantized, 0, 0, false);
         ps5_cs_color_ns += (unsigned long long)(os_time_get_nano() - bt0);
         ++ps5_cs_color_n;"""
assert s.count(old) == 1
s = s.replace(old, new)

old = "struct ps5_clear_stat {"
new = "static unsigned long long ps5_cs_depth_ns, ps5_cs_depth_n, ps5_cs_color_ns, ps5_cs_color_n;\nstruct ps5_clear_stat {"
assert s.count(old) == 1
s = s.replace(old, new)

old = "   memset(ps5_clear_stats, 0, sizeof ps5_clear_stats);\n   return w;"
new = """   w += snprintf(out + w, n - (size_t)w, " blitter: depth n=%llu %.2fms, color n=%llu %.2fms", ps5_cs_depth_n, ps5_cs_depth_ns / 1e6,
                 ps5_cs_color_n, ps5_cs_color_ns / 1e6);
   ps5_cs_depth_ns = ps5_cs_depth_n = ps5_cs_color_ns = ps5_cs_color_n = 0;
   memset(ps5_clear_stats, 0, sizeof ps5_clear_stats);
   return w;"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
