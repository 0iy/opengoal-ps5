#!/usr/bin/env python3
"""Driver patch 11 (diagnostic): cache-flush bytes per caller (return address), exported for the slow-frame log."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_flush_callers" in s:
    print("already patched")
    raise SystemExit
old = """static void
ps5_flush_gpu_data(const void *address, size_t bytes)
{
   if (!bytes)
      return;
   __atomic_fetch_add(&ps5_flush_total_calls, 1, __ATOMIC_RELAXED);"""
new = """static uintptr_t ps5_fcaller_addr[48];
static unsigned long long ps5_fcaller_calls[48], ps5_fcaller_bytes[48];
unsigned
ps5_driver_flush_callers(uintptr_t *addr, unsigned long long *calls, unsigned long long *bytes)
{
   unsigned n = 0;
   for (unsigned i = 0; i < 48 && ps5_fcaller_addr[i]; ++i, ++n) {
      addr[i] = ps5_fcaller_addr[i];
      calls[i] = __atomic_load_n(&ps5_fcaller_calls[i], __ATOMIC_RELAXED);
      bytes[i] = __atomic_load_n(&ps5_fcaller_bytes[i], __ATOMIC_RELAXED);
   }
   return n;
}

__attribute__((noinline)) static void
ps5_flush_gpu_data(const void *address, size_t bytes)
{
   if (!bytes)
      return;
   {
      const uintptr_t ra = (uintptr_t)__builtin_return_address(0);
      for (unsigned i = 0; i < 48; ++i) {
         if (ps5_fcaller_addr[i] == ra || !ps5_fcaller_addr[i]) {
            ps5_fcaller_addr[i] = ra;
            __atomic_fetch_add(&ps5_fcaller_calls[i], 1, __ATOMIC_RELAXED);
            __atomic_fetch_add(&ps5_fcaller_bytes[i], bytes, __ATOMIC_RELAXED);
            break;
         }
      }
   }
   __atomic_fetch_add(&ps5_flush_total_calls, 1, __ATOMIC_RELAXED);"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("flush callers added")
