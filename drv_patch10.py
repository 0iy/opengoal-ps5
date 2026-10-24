#!/usr/bin/env python3
"""Driver patch 10 (diagnostic): cache-flush bytes and calls per call site (source line)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_flush_sites" in s:
    print("already patched")
    raise SystemExit
anchor = "#define ps5_flush_gpu_data(address, bytes) PS5_CACHE_MEASURE(ps5_flush_gpu_data, address, bytes)"
assert s.count(anchor) == 1, s.count(anchor)
new = """static unsigned ps5_fsite_line[48];
static unsigned long long ps5_fsite_calls[48], ps5_fsite_bytes[48];
static void
ps5_flush_site(unsigned line, size_t bytes)
{
   for (unsigned i = 0; i < 48; ++i) {
      if (ps5_fsite_line[i] == line || !ps5_fsite_line[i]) {
         ps5_fsite_line[i] = line;
         __atomic_fetch_add(&ps5_fsite_calls[i], 1, __ATOMIC_RELAXED);
         __atomic_fetch_add(&ps5_fsite_bytes[i], bytes, __ATOMIC_RELAXED);
         return;
      }
   }
}
unsigned
ps5_driver_flush_sites(unsigned *lines, unsigned long long *calls, unsigned long long *bytes)
{
   unsigned n = 0;
   for (unsigned i = 0; i < 48 && ps5_fsite_line[i]; ++i, ++n) {
      lines[i] = ps5_fsite_line[i];
      calls[i] = __atomic_load_n(&ps5_fsite_calls[i], __ATOMIC_RELAXED);
      bytes[i] = __atomic_load_n(&ps5_fsite_bytes[i], __ATOMIC_RELAXED);
   }
   return n;
}
#define ps5_flush_gpu_data(address, bytes) (ps5_flush_site(__LINE__, (bytes)), PS5_CACHE_MEASURE(ps5_flush_gpu_data, address, bytes))"""
open(P, "w", encoding="utf-8").write(s.replace(anchor, new))
print("flush site counters added")
