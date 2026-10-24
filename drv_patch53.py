#!/usr/bin/env python3
"""Driver patch 53 (agent multidraw): PS5_ASYNC_MULTIDRAW=1 queues every sub-draw of a glMultiDraw* into the current deferred batch.

Today a multi-draw either takes ps5_try_multi_draw_batch (ps5_screen_submit_lock = flush + wait for everything in flight, then its
own batch is retired before returning) or, with PS5_NO_MULTIDRAW, ps5_try_deferred_draw refuses it (num_draws != 1) and *flushes the
open batch* before util_draw_multi splits it into single draws. With the flag set each sub-draw goes through ps5_try_deferred_draw
as a single draw (own descriptor snapshot, own resource retention, same ps5_multidraw_eligible check) and the open batch is not
flushed at the multi-draw boundary. The first refused sub-draw (it flushes itself, exactly like a refused single draw) hands the
remaining sub-draws to util_draw_multi, i.e. the pre-patch path. Default (flag unset): unchanged.

Also adds trace event 116 "batch flush request" (arg = return address of the caller of ps5_draw_batch_submit: framebuffer change,
pipe flush, barriers) so the flush causes can be counted (see docs/agent_multidraw.md and multidraw_report.py).
No new static data except one function-local `static int` (the cached getenv)."""
import os

ROOT = os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src"))
P = os.path.join(ROOT, "gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_ASYNC_MULTIDRAW" in s:
    print("already patched")
    raise SystemExit

old = """#ifdef PS5_DEFERRED_DRAW_BATCH
   if (!context->legacy_primitive_conversion &&
       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))
      return;
#endif"""
new = """#ifdef PS5_DEFERRED_DRAW_BATCH
   {
      static int async_multidraw = -1; /* PS5_ASYNC_MULTIDRAW=1: sub-draws join the open batch, no flush, no full wait */
      if (async_multidraw < 0)
         async_multidraw = getenv("PS5_ASYNC_MULTIDRAW") != NULL;
      if (async_multidraw && num_draws > 1 && info && draws && !indirect &&
          !context->legacy_primitive_conversion) {
         for (unsigned i = 0; i < num_draws; ++i) {
            const unsigned id = drawid_offset + (info->increment_draw_id ? i : 0);
            if (!ps5_try_deferred_draw(base, info, id, NULL, &draws[i], 1)) {
               /* refused (it already flushed): the rest takes the pre-patch split path */
               util_draw_multi(base, info, id, NULL, &draws[i], num_draws - i);
               return;
            }
            if (context->last_draw_status)
               return;
         }
         return;
      }
   }
   if (!context->legacy_primitive_conversion &&
       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))
      return;
#endif"""
# fix53: after drv_patch52 the deferred-draw condition carries a !ps5_sync_dbg prefix
if s.count(old) != 1 and 'ps5_sync_dbg' in s:
    a = '   if (!context->legacy_primitive_conversion &&' + chr(10) + '       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))'
    b = '   if (!ps5_sync_dbg && !context->legacy_primitive_conversion &&' + chr(10) + '       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))'
    old = old.replace(a, b)
    new = new.replace(a, b)
    new = new.replace('if (async_multidraw && num_draws > 1', 'if (async_multidraw && !ps5_sync_dbg && num_draws > 1')
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

old = """static void
ps5_draw_batch_submit(void)
{
#ifdef PS5_DEFERRED_DRAW_BATCH
   simple_mtx_lock(&ps5_deferred_mutex);
   ps5_draw_batch_flush_locked();"""
new = """static void __attribute__((noinline))
ps5_draw_batch_submit(void)
{
#ifdef PS5_DEFERRED_DRAW_BATCH
   simple_mtx_lock(&ps5_deferred_mutex);
   if (ps5_driver_trace_hook) /* flush cause: caller address, matched with the next batch-submit event */
      ps5_driver_trace_hook(116, (unsigned long long)os_time_get_nano(), 0, (unsigned long long)(uintptr_t)__builtin_return_address(0));
   ps5_draw_batch_flush_locked();"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
