#!/usr/bin/env python3
"""Driver patch 46 (A/B): ps5_try_multi_draw_batch runs each glMultiDrawElements synchronously (own batch, full flush and
wait for everything in flight first). With PS5_NO_MULTIDRAW set it returns false so the sub-draws take the normal
deferred/async path instead."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_NO_MULTIDRAW" in s:
    print("already patched")
    raise SystemExit
old = """   if (num_draws < 2 || context->active_occlusion_query ||
       ps5_any_primitive_query(context) ||
       !ps5_agc_gate2_batch_begin || !ps5_agc_gate2_batch_end ||
       !ps5_multidraw_eligible(context, info, indirect, draws, num_draws))
      return false;
   /* Preserve copied inline uniforms"""
new = """   static int no_multidraw = -1;
   if (no_multidraw < 0)
      no_multidraw = getenv("PS5_NO_MULTIDRAW") != NULL;
   if (no_multidraw || num_draws < 2 || context->active_occlusion_query ||
       ps5_any_primitive_query(context) ||
       !ps5_agc_gate2_batch_begin || !ps5_agc_gate2_batch_end ||
       !ps5_multidraw_eligible(context, info, indirect, draws, num_draws))
      return false;
   /* Preserve copied inline uniforms"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("ok")
