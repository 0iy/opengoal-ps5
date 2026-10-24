#!/usr/bin/env python3
"""Driver patch 42: ps5_flush_gpu_data was ~60 % of the Jak 2 render thread (sampling profile, 1900 draws/frame, ~11 flush
calls per draw). util_flush_inval_range does a clflushopt loop, an mfence, a second clflushopt of the last byte, another
mfence and a call_once per call. Replace it with one clflushopt loop and a single mfence (same ordering guarantee for the
GPU hand-over, a third of the fences)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_fast_flush" in s:
    print("already patched")
    raise SystemExit

old = "   util_flush_inval_range((void *)address, bytes);\n#ifdef PS5_DRAW_PROFILE\n   __atomic_fetch_add(&ps5_cpu_flush_calls"
new = "   ps5_fast_flush(address, bytes);\n#ifdef PS5_DRAW_PROFILE\n   __atomic_fetch_add(&ps5_cpu_flush_calls"
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

anchor = "__attribute__((noinline)) static void\nps5_flush_gpu_data(const void *address, size_t bytes)\n"
assert s.count(anchor) == 1
helper = """__attribute__((target("clflushopt"))) static void
ps5_clflushopt_loop(const void *address, size_t bytes)
{
   uintptr_t p = (uintptr_t)address & ~(uintptr_t)63;
   const uintptr_t end = (uintptr_t)address + bytes;
   for (; p < end; p += 64)
      __builtin_ia32_clflushopt((void *)p);
   __builtin_ia32_mfence();
}

/* ps5_fast_flush: clflushopt loop + one mfence; falls back to the Mesa helper on CPUs without clflushopt */
static void
ps5_fast_flush(const void *address, size_t bytes)
{
   static int has_opt = -1;
   if (has_opt < 0) {
      unsigned a = 7, b = 0, c = 0, d = 0;
      __asm__ volatile("cpuid" : "+a"(a), "=b"(b), "+c"(c), "=d"(d));
      has_opt = (a >= 0 && (b & (1u << 23))) ? 1 : 0; /* CPUID.7.0:EBX[23] = CLFLUSHOPT; Mesa's own detection reports it missing on the PS5 */
      printf("[ps5-gallium] clflushopt cpuid=%d mesa=%d\\n", has_opt, util_get_cpu_caps()->has_clflushopt ? 1 : 0);
   }
   if (has_opt)
      ps5_clflushopt_loop(address, bytes);
   else
      util_flush_inval_range((void *)address, bytes);
}

"""
s = s.replace(anchor, helper + anchor)
open(P, "w", encoding="utf-8").write(s)
print("ok")
