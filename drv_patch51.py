#!/usr/bin/env python3
"""Driver patch 51: ps5_multidraw_eligible rejected every draw whose sampled texture is the same resource as a bound color
target, even when the sampled mip levels do not include the rendered level. glGenerateMipmap on the GPU renders level N+1 of
a texture while sampling level N of the same texture: each of those blits took the synchronous path with a full GPU wait
(about 15 per frame, ~5 ms per frame in Jak 3). Only reject when the sampled level range contains the render target level."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_levels_disjoint" in s:
    print("already patched")
    raise SystemExit
old = """         for (unsigned i = 0; i < context->framebuffer.nr_cbufs; ++i)
            if (texture == (const struct ps5_resource *)
                              context->framebuffer.cbufs[i].texture) {
               rejects |= BITFIELD_BIT(PS5_BATCH_REJECT_TEXTURE - 1);
               break;
            }"""
new = """         for (unsigned i = 0; i < context->framebuffer.nr_cbufs; ++i)
            if (texture == (const struct ps5_resource *)
                              context->framebuffer.cbufs[i].texture) {
               /* ps5_levels_disjoint: sampling other mip levels of the render target's texture is not an alias hazard */
               const unsigned rt_level = context->framebuffer.cbufs[i].level;
               const bool ps5_levels_disjoint = view->target != PIPE_BUFFER &&
                  (view->u.tex.last_level < rt_level || view->u.tex.first_level > rt_level);
               if (ps5_levels_disjoint)
                  continue;
               rejects |= BITFIELD_BIT(PS5_BATCH_REJECT_TEXTURE - 1);
               break;
            }"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("ok")
