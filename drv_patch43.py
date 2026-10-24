#!/usr/bin/env python3
"""Driver patch 43: wait-site accounting. Wall time the render thread spends waiting, per site:
0 batch retire (waiting for a submitted batch to complete), 1 frame complete (waiting for the frame's last marker),
2 flip (waiting for VideoOut flip status), 3 async collect (spinning for a prep worker job).
Exported as ps5_driver_wait_sites(ns[4], n[4]); the shim reads it per draw and per frame."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_wsite_add" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:60])
    s = s.replace(old, new)


rep('#include "util/os_time.h"\n/* Completion publication is now prompt.',
    '''#include "util/os_time.h"
/* ps5_wsite: wall time the render thread waits, per site (0 batch retire, 1 frame complete, 2 flip, 3 async collect) */
static unsigned long long ps5_wsite_ns[4], ps5_wsite_n[4];
static inline void ps5_wsite_add(unsigned site, int64_t t0)
{
    int64_t d = os_time_get_nano() - t0;
    if (d > 0) {
        __atomic_fetch_add(&ps5_wsite_ns[site], (unsigned long long)d, __ATOMIC_RELAXED);
        __atomic_fetch_add(&ps5_wsite_n[site], 1, __ATOMIC_RELAXED);
    }
}
void ps5_driver_wait_sites(unsigned long long *ns, unsigned long long *n)
{
    for (unsigned i = 0; i < 4; ++i) {
        ns[i] = __atomic_load_n(&ps5_wsite_ns[i], __ATOMIC_RELAXED);
        n[i] = __atomic_load_n(&ps5_wsite_n[i], __ATOMIC_RELAXED);
    }
}
/* Completion publication is now prompt.''')

rep('''    while (atomic_load_explicit(&job->ready, memory_order_acquire) != runtime_async_collected + 1)
        __builtin_ia32_pause();
    if (job->has_entry''',
    '''    if (atomic_load_explicit(&job->ready, memory_order_acquire) != runtime_async_collected + 1) {
        const int64_t wsite_t0 = os_time_get_nano();
        while (atomic_load_explicit(&job->ready, memory_order_acquire) != runtime_async_collected + 1)
            __builtin_ia32_pause();
        ps5_wsite_add(3, wsite_t0);
    }
    if (job->has_entry''')

rep('''    do {
        complete = 1;
        for (unsigned i = 0; i < pending->attempted; ++i) {''',
    '''    const int64_t wsite_t0 = os_time_get_nano();
    do {
        complete = 1;
        for (unsigned i = 0; i < pending->attempted; ++i) {''')
rep('''    } while (waits < 2000);
#ifdef PS5_DRAW_PROFILE
    if (pending->profile)
        poll_end''',
    '''    } while (waits < 2000);
    if (waits)
        ps5_wsite_add(0, wsite_t0);
#ifdef PS5_DRAW_PROFILE
    if (pending->profile)
        poll_end''')

rep('''            int64_t spin_deadline = 0;
            for (waits = 0; waits < 2000;) {
#ifdef PS5_DRAW_GPU_TIMESTAMPS''',
    '''            int64_t spin_deadline = 0;
            const int64_t wsite_t0 = os_time_get_nano();
            for (waits = 0; waits < 2000;) {
#ifdef PS5_DRAW_GPU_TIMESTAMPS''')
rep('''                waits += runtime_completion_pause(&spin_deadline);
            }
        }
        status[3] = *completion_marker;''',
    '''                waits += runtime_completion_pause(&spin_deadline);
            }
            if (waits)
                ps5_wsite_add(1, wsite_t0);
        }
        status[3] = *completion_marker;''')

rep('''        if (ps5_sleep_wait_mode()) {
            result = sceKernelUsleep(UINT32_C(1000));
            if (result != 0)
                return result;
        } else {''',
    '''        if (ps5_sleep_wait_mode()) {
            const int64_t wsite_t0 = os_time_get_nano();
            result = sceKernelUsleep(UINT32_C(1000));
            ps5_wsite_add(2, wsite_t0);
            if (result != 0)
                return result;
        } else {''')
open(P, "w", encoding="utf-8").write(s)
print("ok")
