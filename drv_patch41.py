#!/usr/bin/env python3
"""Driver patch 41: a depth/stencil blit between different formats is rejected by the software path anyway ("software-blit
depth-stencil rejected", nothing is copied) - but only after it drained the GPU (5-6 ms every frame for the glow probe
depth copy). Reject before draining."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_blit_early_reject" in s:
    print("already patched")
    raise SystemExit

old = "   ps5_draw_batch_drain_buffer(info ? info->src.resource : NULL);\n   ps5_draw_batch_drain_buffer(info ? info->dst.resource : NULL);\n   if (PS5_ENABLE_MSAA4_CANDIDATE && info && info->src.resource &&"
new = """   if (info && info->src.resource && info->dst.resource && (info->mask & PIPE_MASK_ZS) &&
       info->src.format != info->dst.format && info->src.resource->nr_samples <= 1 &&
       info->dst.resource->nr_samples <= 1) {
      /* ps5_blit_early_reject: the software depth/stencil path below rejects different formats after a full GPU drain */
      static unsigned long long ps5_blit_early_rejects;
      if (!(ps5_blit_early_rejects++ & 0x3ff))
         printf("[ps5-gallium] software-blit depth-stencil rejected (format %u -> %u, early)\\n", info->src.format, info->dst.format);
      return;
   }
   ps5_draw_batch_drain_buffer(info ? info->src.resource : NULL);
   ps5_draw_batch_drain_buffer(info ? info->dst.resource : NULL);
   if (PS5_ENABLE_MSAA4_CANDIDATE && info && info->src.resource &&"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
