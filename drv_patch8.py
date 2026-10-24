#!/usr/bin/env python3
"""Driver patch 8: always-on cache-flush counters (calls, bytes), exported for the slow-frame log."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
old = """static void
ps5_flush_gpu_data(const void *address, size_t bytes)
{
   if (!bytes)
      return;
   util_flush_inval_range((void *)address, bytes);
"""
new = """static uint64_t ps5_flush_total_calls, ps5_flush_total_bytes;
void
ps5_driver_flush_counters(uint64_t *calls, uint64_t *bytes)
{
   *calls = __atomic_load_n(&ps5_flush_total_calls, __ATOMIC_RELAXED);
   *bytes = __atomic_load_n(&ps5_flush_total_bytes, __ATOMIC_RELAXED);
}

static void
ps5_flush_gpu_data(const void *address, size_t bytes)
{
   if (!bytes)
      return;
   __atomic_fetch_add(&ps5_flush_total_calls, 1, __ATOMIC_RELAXED);
   __atomic_fetch_add(&ps5_flush_total_bytes, bytes, __ATOMIC_RELAXED);
   util_flush_inval_range((void *)address, bytes);
"""
if "ps5_driver_flush_counters" in s:
    print("already patched")
else:
    assert s.count(old) == 1, s.count(old)
    open(P, "w", encoding="utf-8").write(s.replace(old, new))
    print("flush counters added")
