#!/usr/bin/env python3
"""Driver patch 50: trace events for draws that cannot take the deferred path (they fall to the synchronous path with a full
wait). 114 = ps5_try_deferred_draw gave up (arg bits: 0 num_draws!=1, 1 blitter running, 2 not eligible; mode<<8, index_size<<16),
115 = eligibility reject bits (INPUT, SHADER, QUERY, FRAMEBUFFER, DEPTH, VERTEX, TEXTURE)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_trace_hook(114" in s:
    print("already patched")
    raise SystemExit
old = """   if (!rejects)
      context->batch_eligible++;
   else
      for"""
new = """   if (rejects && ps5_driver_trace_hook)
      ps5_driver_trace_hook(115, (unsigned long long)os_time_get_nano(), 0, rejects);
   if (!rejects)
      context->batch_eligible++;
   else
      for"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
old = """       !ps5_my_elig) {
      ps5_draw_batch_flush_locked();
      goto out;
   }
   if (!draws[0].count) {"""
new = """       !ps5_my_elig) {
      if (ps5_driver_trace_hook)
         ps5_driver_trace_hook(114, (unsigned long long)os_time_get_nano(), 0,
            (num_draws != 1 ? 1ull : 0ull) |
            ((context->blitter && context->blitter->running && !context->deferred_blitter_draw) ? 2ull : 0ull) |
            (!ps5_my_elig ? 4ull : 0ull) | ((unsigned long long)(info ? info->mode : 0) << 8) |
            ((unsigned long long)(info ? info->index_size : 0) << 16));
      ps5_draw_batch_flush_locked();
      goto out;
   }
   if (!draws[0].count) {"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
