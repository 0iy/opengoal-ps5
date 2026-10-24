#!/usr/bin/env python3
"""Driver patch 49: trace event 113 = ps5_screen_submit_lock (flush + wait for everything in flight), arg = caller address.
Uses the patch-47 hook only; no new static data."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_trace_hook(113" in s:
    print("already patched")
    raise SystemExit
old = """void
ps5_screen_submit_lock(struct pipe_screen *base)
{
#ifdef PS5_DEFERRED_DRAW_BATCH
   (void)base;
   simple_mtx_lock(&ps5_deferred_mutex);
   ps5_draw_batch_flush_locked();
   ps5_draw_batch_retire_locked(true);
#else"""
new = """__attribute__((noinline)) void
ps5_screen_submit_lock(struct pipe_screen *base)
{
#ifdef PS5_DEFERRED_DRAW_BATCH
   (void)base;
   const uintptr_t sl_ra = (uintptr_t)__builtin_return_address(0);
   simple_mtx_lock(&ps5_deferred_mutex);
   const int64_t sl_t0 = ps5_driver_trace_hook ? os_time_get_nano() : 0;
   ps5_draw_batch_flush_locked();
   ps5_draw_batch_retire_locked(true);
   if (sl_t0)
      ps5_driver_trace_hook(113, (unsigned long long)sl_t0, (unsigned long long)(os_time_get_nano() - sl_t0), (unsigned long long)sl_ra);
#else"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("ok")
