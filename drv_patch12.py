#!/usr/bin/env python3
"""Driver patch 12: skip a CPU cache flush when the same address range was already published in this batch by ANY slot
(interleaved vertex data bound to several attribute slots was flushed once per attribute)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "cross-slot coverage" in s:
    print("already patched")
    raise SystemExit
old = """#ifdef PS5_GPU_PRESENT_BATCH
   if (batch && data && bytes && batch->data[slot] && batch->size[slot]) {"""
new = """#ifdef PS5_GPU_PRESENT_BATCH
   if (batch && data && bytes) {  /* cross-slot coverage: already published by another slot in this batch */
      const uintptr_t cs = (uintptr_t)data;
      if (bytes <= UINTPTR_MAX - cs) {
         const uintptr_t ce = cs + bytes;
         for (unsigned j = 0; j < ARRAY_SIZE(batch->data); ++j) {
            const uintptr_t b = (uintptr_t)batch->data[j];
            if (b && batch->size[j] && cs >= b && batch->size[j] <= UINTPTR_MAX - b && ce <= b + batch->size[j])
               return;
         }
      }
   }
   if (batch && data && bytes && batch->data[slot] && batch->size[slot]) {"""
assert s.count(old) == 1, s.count(old)
open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("cross-slot coverage added")
