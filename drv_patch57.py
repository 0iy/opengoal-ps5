#!/usr/bin/env python3
"""Driver patch 57 (drawcost): the prep workers flush every job's 16 KiB state page and its command words with Mesa's
util_flush_inval_range, i.e. one CLFLUSH per 64 byte line plus mfence per call (Mesa reports CLFLUSHOPT missing on the PS5,
the screen driver already works around that with a cpuid test in ps5_fast_flush). About 1250 jobs x 256 lines per frame.
Root: $PS5_SRC (default ~/gl/src/ps5-opengl/src), file platform/ps5_agc_native_runtime.c.

Env PS5_RT_FAST_FLUSH=1 (shim config file proposal: rtfastflush.txt), default off:
  - flush_gpu_data uses a CLFLUSHOPT loop + one mfence when cpuid says CLFLUSHOPT exists (else unchanged)
  - runtime_prepared_work_publish issues its three flushes without their own fences and fences once at the end
New static data: one function-local `static int` in runtime_fast_flush_enabled(). No arrays.
"""
import os

P = os.path.join(os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src")), "platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "PS5_RT_FAST_FLUSH" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


rep("""static void flush_gpu_data(const void *address, size_t bytes);
#include "ps5_cache_profile.h"
#ifdef PS5_DRAW_PROFILE
#define flush_gpu_data(address, bytes) PS5_CACHE_MEASURE(flush_gpu_data, address, bytes)
#endif
""", """static void flush_gpu_data(const void *address, size_t bytes);
#include "ps5_cache_profile.h"
#ifdef PS5_DRAW_PROFILE
#define flush_gpu_data(address, bytes) PS5_CACHE_MEASURE(flush_gpu_data, address, bytes)
#endif

/* PS5_RT_FAST_FLUSH=1 and the CPU has CLFLUSHOPT (cpuid.7.0:EBX[23]; Mesa's own detection misses it on the PS5). */
static int runtime_fast_flush_enabled(void)
{
    static int v = -1;
    if (v < 0) {
        unsigned a = 7, b = 0, c = 0, d = 0;
        __asm__ volatile("cpuid" : "+a"(a), "=b"(b), "+c"(c), "=d"(d));
        v = getenv("PS5_RT_FAST_FLUSH") != NULL && (b & (1u << 23)) ? 1 : 0;
    }
    return v;
}

__attribute__((target("clflushopt"))) static void
runtime_clflushopt_range(const void *address, size_t bytes)
{
    uintptr_t p = (uintptr_t)address & ~(uintptr_t)63;
    const uintptr_t end = (uintptr_t)address + bytes;
    for (; p < end; p += 64)
        __builtin_ia32_clflushopt((void *)p);
}

/* Fast mode: no fence (the caller fences once). Otherwise the ordinary fenced flush. */
static void runtime_flush_nofence(const void *address, size_t bytes)
{
    if (runtime_fast_flush_enabled())
        runtime_clflushopt_range(address, bytes);
    else if (bytes)
        flush_gpu_data(address, bytes);
}
""")
rep("""    flush_gpu_data(memory + 0x4000, 0x4000);
    flush_gpu_data(command->bottom, (size_t)(command->up - command->bottom) * 4);
    flush_gpu_data(command->down, (size_t)(command->top - command->down) * 4);
    return 0;""", """    runtime_flush_nofence(memory + 0x4000, 0x4000);
    runtime_flush_nofence(command->bottom, (size_t)(command->up - command->bottom) * 4);
    runtime_flush_nofence(command->down, (size_t)(command->top - command->down) * 4);
    if (runtime_fast_flush_enabled())
        __builtin_ia32_mfence();
    return 0;""")
rep("""    if (bytes)
        util_flush_inval_range((void *)address, bytes);
#else""", """    if (bytes) {
        if (runtime_fast_flush_enabled()) {
            runtime_clflushopt_range(address, bytes);
            __builtin_ia32_mfence();
        } else
            util_flush_inval_range((void *)address, bytes);
    }
#else""")
open(P, "w", encoding="utf-8").write(s)
print("ok")
