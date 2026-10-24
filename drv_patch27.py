#!/usr/bin/env python3
"""Driver patch 27 (experiment): prep workers yield the CPU while idle (PS5_WORKER_YIELD=<spin iterations before the
first sched_yield>, default off) so other threads (render, EE, audio) are not preempted by two permanently spinning workers."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "PS5_WORKER_YIELD" in s:
    print("already patched")
    raise SystemExit
old = """            /* ponytail: this development worker busy-spins on a spare core;
             * add an idle event only if the lock-free path proves useful. */
            __builtin_ia32_pause();
            continue;"""
new = """            /* ponytail: this development worker busy-spins on a spare core;
             * add an idle event only if the lock-free path proves useful. */
            {
                static int yield_after = -2;
                if (yield_after == -2) {
                    const char *e = getenv("PS5_WORKER_YIELD");
                    yield_after = e ? atoi(e) : -1;
                }
                if (yield_after >= 0 && ++idle_spins > (unsigned)yield_after) {
                    idle_spins = (unsigned)yield_after;
                    sched_yield();
                } else {
                    __builtin_ia32_pause();
                }
            }
            continue;"""
assert s.count(old) == 1
s = s.replace(old, new)
old = "    if (pin)\n        return NULL;\n    for (;;) {\n        uint64_t consumed = atomic_load_explicit(&runtime_async_consumed, memory_order_relaxed);"
new = "    if (pin)\n        return NULL;\n    unsigned idle_spins = 0;\n    for (;;) {\n        uint64_t consumed = atomic_load_explicit(&runtime_async_consumed, memory_order_relaxed);"
assert s.count(old) == 1
s = s.replace(old, new)
# a job found: restart the spin budget
old = "        struct runtime_async_job *job = &runtime_async_jobs[consumed % RUNTIME_ASYNC_JOBS];\n\n        runtime_draw_state = job->draw;"
new = "        struct runtime_async_job *job = &runtime_async_jobs[consumed % RUNTIME_ASYNC_JOBS];\n        idle_spins = 0;\n\n        runtime_draw_state = job->draw;"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
