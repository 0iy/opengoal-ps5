#!/usr/bin/env python3
"""Driver patch 13 (diagnostic): flush bytes by slot class (depth/texture/vertex/index) and batch/no-batch."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_flush_classes" in s:
    print("already patched")
    raise SystemExit
old = """static void
ps5_flush_batch_backing(struct ps5_batch_flush_cache *batch, unsigned slot,
                         const void *data, size_t bytes)
{"""
new = """static unsigned long long ps5_fclass_calls[4][2], ps5_fclass_bytes[4][2];
void
ps5_driver_flush_classes(unsigned long long calls[4][2], unsigned long long bytes[4][2])
{
   for (unsigned c = 0; c < 4; ++c)
      for (unsigned b = 0; b < 2; ++b) {
         calls[c][b] = __atomic_load_n(&ps5_fclass_calls[c][b], __ATOMIC_RELAXED);
         bytes[c][b] = __atomic_load_n(&ps5_fclass_bytes[c][b], __ATOMIC_RELAXED);
      }
}

static void
ps5_flush_batch_backing(struct ps5_batch_flush_cache *batch, unsigned slot,
                         const void *data, size_t bytes)
{
   {
      const unsigned cls = slot < 2 ? 0 : slot < 2 + PS5_MAX_TEXTURE_UNITS ? 1 :
                           slot < 2 + PS5_MAX_TEXTURE_UNITS + PIPE_MAX_ATTRIBS ? 2 : 3;
      __atomic_fetch_add(&ps5_fclass_calls[cls][batch ? 1 : 0], 1, __ATOMIC_RELAXED);
      __atomic_fetch_add(&ps5_fclass_bytes[cls][batch ? 1 : 0], bytes, __ATOMIC_RELAXED);
   }"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("flush classes added")
