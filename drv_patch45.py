#!/usr/bin/env python3
"""Driver patch 45 (diagnostic): attribute full-pipeline waits. ps5_screen_submit_lock flushes the current batch and waits
for every batch in flight (a full GPU sync). Record the caller of each such wait (return address, count, wall time) and
export ps5_driver_submit_lock_sites() so the shim can print which call site costs how much."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_sl_site_addr" in s:
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
new = """static uintptr_t ps5_sl_site_addr[16];
static unsigned long long ps5_sl_site_n[16], ps5_sl_site_ns[16];
unsigned
ps5_driver_submit_lock_sites(uintptr_t *addr, unsigned long long *n, unsigned long long *ns)
{
   unsigned c = 0;
   for (unsigned i = 0; i < 16 && ps5_sl_site_addr[i]; ++i, ++c) {
      addr[i] = ps5_sl_site_addr[i];
      n[i] = __atomic_load_n(&ps5_sl_site_n[i], __ATOMIC_RELAXED);
      ns[i] = __atomic_load_n(&ps5_sl_site_ns[i], __ATOMIC_RELAXED);
   }
   return c;
}

__attribute__((noinline)) void
ps5_screen_submit_lock(struct pipe_screen *base)
{
#ifdef PS5_DEFERRED_DRAW_BATCH
   (void)base;
   const uintptr_t sl_ra = (uintptr_t)__builtin_return_address(0);
   simple_mtx_lock(&ps5_deferred_mutex);
   const int64_t sl_t0 = os_time_get_nano();
   ps5_draw_batch_flush_locked();
   ps5_draw_batch_retire_locked(true);
   for (unsigned i = 0; i < 16; ++i) {
      if (ps5_sl_site_addr[i] == sl_ra || !ps5_sl_site_addr[i]) {
         ps5_sl_site_addr[i] = sl_ra;
         ps5_sl_site_n[i]++;
         ps5_sl_site_ns[i] += (unsigned long long)(os_time_get_nano() - sl_t0);
         break;
      }
   }
#else"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("ok")
