#!/usr/bin/env python3
"""Driver patch 36: no 1 ms sleeps while waiting for the GPU.

runtime_completion_pause and runtime_gpu_present_finish slept sceKernelUsleep(1000) between polls; a wait that the GPU
satisfied after 50 us still cost 1-2 ms of render-thread time, ~20 such waits per frame. Now they spin (pause, then
sched_yield); timeouts stay at the same wall time (2 s). PS5_SLEEP_WAIT=1 restores the sleeps."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_sleep_wait_mode" in s:
    print("already patched")
    raise SystemExit

old = """static unsigned runtime_completion_pause(int64_t *spin_deadline)
{
    int64_t now = os_time_get_nano();
    if (!*spin_deadline)
        *spin_deadline = now + 200000;
    if (now < *spin_deadline) {
        __builtin_ia32_pause();
        return 0;
    }
    sceKernelUsleep(UINT32_C(1000));
    return 1;
}"""
new = """static int ps5_sleep_wait_mode(void)
{
    static int mode = -1;
    if (mode < 0)
        mode = getenv("PS5_SLEEP_WAIT") != NULL;
    return mode;
}

static unsigned runtime_completion_pause(int64_t *spin_deadline)
{
    int64_t now = os_time_get_nano();
    if (!*spin_deadline)
        *spin_deadline = now + 200000;
    if (now < *spin_deadline) {
        __builtin_ia32_pause();
        return 0;
    }
    if (ps5_sleep_wait_mode()) {
        sceKernelUsleep(UINT32_C(1000));
        return 1;
    }
    /* spin instead of sleeping: one 'wait' is counted per elapsed millisecond (the old timeout semantics) */
    *spin_deadline = now + 1000000;
    return 1;
}"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """        result = sceKernelUsleep(UINT32_C(1000));
        if (result != 0)
            return result;
    }
    return -1;"""
new = """        if (ps5_sleep_wait_mode()) {
            result = sceKernelUsleep(UINT32_C(1000));
            if (result != 0)
                return result;
        } else {
            /* poll again after ~20 us: a flip that completed early is seen early; a poll costs one syscall pair */
            const int64_t until = os_time_get_nano() + 20000;
            while (os_time_get_nano() < until)
                __builtin_ia32_pause();
        }
    }
    return -1;"""
assert s.count(old) == 1
s = s.replace(old, new)

# the present wait counted ~1 ms per iteration; with 20 us iterations raise the bound to keep ~2 s
old = "    for (unsigned waits = 0; waits <= 2000; ++waits) {\n        uint64_t status[16] = {0};\n        int result = runtime_video_api.get_flip_status"
new = "    for (unsigned waits = 0; waits <= 100000; ++waits) {\n        uint64_t status[16] = {0};\n        int result = runtime_video_api.get_flip_status"
assert s.count(old) == 1
s = s.replace(old, new)
old = "        if (waits == 2000)\n            return -1;\n        /* Vblank can wake before"
new = "        if (waits == 100000)\n            return -1;\n        /* Vblank can wake before"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
