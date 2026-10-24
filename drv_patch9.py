#!/usr/bin/env python3
"""Driver patch 9 (diagnostic): count ps5_draw_batch_drain() calls per call site (each one invalidates every texture
publication, so all textures are flushed again on next use). Exported as ps5_driver_drain_counters()."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_drain_counters" in s:
    print("already patched")
    raise SystemExit
old = """static void
ps5_draw_batch_submit(void)
{"""
new = """static unsigned ps5_drain_lines[24], ps5_drain_hits[24];
static void
ps5_drain_count(unsigned line)
{
   for (unsigned i = 0; i < 24; ++i) {
      if (ps5_drain_lines[i] == line || !ps5_drain_lines[i]) {
         ps5_drain_lines[i] = line;
         __atomic_fetch_add(&ps5_drain_hits[i], 1, __ATOMIC_RELAXED);
         return;
      }
   }
}
unsigned
ps5_driver_drain_counters(unsigned *lines, unsigned *hits)
{
   unsigned n = 0;
   for (unsigned i = 0; i < 24 && ps5_drain_lines[i]; ++i, ++n) {
      lines[i] = ps5_drain_lines[i];
      hits[i] = __atomic_load_n(&ps5_drain_hits[i], __ATOMIC_RELAXED);
   }
   return n;
}
#define ps5_draw_batch_drain() (ps5_drain_count(__LINE__), ps5_draw_batch_drain())

static void
ps5_draw_batch_submit(void)
{"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("drain counters added")
