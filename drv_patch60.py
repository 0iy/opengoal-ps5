#!/usr/bin/env python3
"""Driver patch 60 (agent spikes): scheduling and wait-policy switches for the async prep workers and the GPU completion wait.
Touches only platform/ps5_agc_native_runtime.c (root: env PS5_SRC, default ~/gl/src/ps5-opengl/src). Every switch is an environment
variable and defaults to the current behaviour. New static data: none (new settings are stack locals or function-local scalars
that already exist as a pattern; see docs/agent_spikes.md section 5).

  PS5_WAIT_US=<50..1000>        GPU completion wait (retire/backpressure/frame-complete) sleeps this many us instead of 1000.
                                One 'wait' is still counted per elapsed millisecond, so the 2000-wait (about 2 s) timeout is unchanged.
  PS5_WORKER_SLEEP_SPINS=<n>    prep worker: after n idle pause-spins sleep PS5_WORKER_SLEEP_US (default 50) per iteration instead of
                                spinning forever (0 = never sleep = current behaviour). A thread that sleeps is no longer a pure CPU hog.
  PS5_WORKER_RT="<type> <prio>" prep worker scheduling class via rtprio_thread(RTP_SET): type 2 realtime (round robin), 10 realtime
                                FIFO, 3 timeshare, 4 idle; prio 0 (best) to 31. DANGER: a spinning realtime thread can starve kernel
                                threads on its core; use only together with PS5_WORKER_SLEEP_SPINS or type 2 with a high prio number.
  PS5_WORKER_DIAG=<us>          diagnostic: for every prep job slower than <us> emit trace event 140 from the worker thread:
                                dur = job time, arg = worker | nivcsw_delta<<8 | nvcsw_delta<<24 | (shader pair created)<<40.
                                Tells a descheduled worker (nivcsw > 0) from a slow job (first use of a shader pair)."""
import os

root = os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src"))
P = os.path.join(root, "platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_wait_us" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


# 1. includes
rep("#include <sched.h>\n", "#include <sched.h>\n#include <sys/resource.h>\n")

# 2. GPU completion wait granularity
rep("""static unsigned runtime_completion_pause(int64_t *spin_deadline)
{""", """static unsigned ps5_wait_us(void)
{
    static int us = -1; /* function-local scalar, same pattern as ps5_sleep_wait_mode() */
    if (us < 0) {
        const char *e = getenv("PS5_WAIT_US");
        us = e ? atoi(e) : 1000;
        if (us < 50) us = 50;
        if (us > 1000) us = 1000;
    }
    return (unsigned)us;
}

static unsigned runtime_completion_pause(int64_t *spin_deadline)
{""")
rep("""    if (ps5_sleep_wait_mode()) {
        sceKernelUsleep(UINT32_C(1000));
        return 1;
    }
    /* spin instead of sleeping""", """    if (ps5_sleep_wait_mode()) {
        const unsigned us = ps5_wait_us();
        sceKernelUsleep(us);
        if (us >= 1000)
            return 1;
        /* short sleeps: count one wait per elapsed millisecond so the 2000-wait timeout keeps its meaning */
        now = os_time_get_nano();
        if (now - *spin_deadline < 1000000)
            return 0;
        *spin_deadline = now;
        return 1;
    }
    /* spin instead of sleeping""")

# 3. worker RT helper, placed before runtime_async_main
rep("""static void *runtime_async_main(void *argument)
{""", """#ifndef PS5_ASYNC_HOST_TEST
extern int rtprio_thread(int, int, void *);
#endif
static void runtime_async_apply_rt(unsigned worker)
{
#ifndef PS5_ASYNC_HOST_TEST
    const char *e = getenv("PS5_WORKER_RT");
    unsigned type = 0, prio = 0;
    if (!e || sscanf(e, "%u %u", &type, &prio) != 2)
        return;
    struct { unsigned short type, prio; } rp = { (unsigned short)type, (unsigned short)prio };
    const int rc = rtprio_thread(1 /* RTP_SET */, 0 /* this thread */, &rp);
    printf("[ps5-async-prep] rt type=%u prio=%u rc=%d worker=%u\\n", type, prio, rc, worker);
#else
    (void)worker;
#endif
}

static void *runtime_async_main(void *argument)
{""")

# 4. worker setup + idle policy + diagnostics
rep("""    unsigned idle_spins = 0;
    for (;;) {
        uint64_t consumed = atomic_load_explicit(&runtime_async_consumed, memory_order_relaxed);""",
    """    unsigned idle_spins = 0, idle60 = 0;
    const char *e60;
    const unsigned sleep_spins = (e60 = getenv("PS5_WORKER_SLEEP_SPINS")) ? (unsigned)atoi(e60) : 0;
    const unsigned sleep_us = (e60 = getenv("PS5_WORKER_SLEEP_US")) ? (unsigned)atoi(e60) : 50;
    const int64_t diag_ns = (e60 = getenv("PS5_WORKER_DIAG")) ? (int64_t)atoi(e60) * 1000 : 0;
    runtime_async_apply_rt(worker);
    for (;;) {
        uint64_t consumed = atomic_load_explicit(&runtime_async_consumed, memory_order_relaxed);""")
rep("""            /* ponytail: this development worker busy-spins on a spare core;
             * add an idle event only if the lock-free path proves useful. */
            {""", """            /* ponytail: this development worker busy-spins on a spare core;
             * add an idle event only if the lock-free path proves useful. */
            if (sleep_spins && ++idle60 > sleep_spins) {
                sceKernelUsleep(sleep_us); /* patch 60: bounded spin, then short sleeps */
                continue;
            }
            {""")
rep("""        struct runtime_async_job *job = &runtime_async_jobs[consumed % RUNTIME_ASYNC_JOBS];
        idle_spins = 0;
""", """        struct runtime_async_job *job = &runtime_async_jobs[consumed % RUNTIME_ASYNC_JOBS];
        idle_spins = 0;
        idle60 = 0;
""")
rep("""        runtime_async_output = job;
        int result = ps5_agc_gate2_run_sync();
        runtime_async_output = NULL;
""", """        runtime_async_output = job;
        struct rusage ru0, ru1;
        int64_t d0 = 0;
        unsigned pairs0 = 0;
        if (diag_ns) {
            getrusage(1 /* RUSAGE_THREAD */, &ru0);
            pairs0 = runtime_shader_pair_count;
            d0 = os_time_get_nano();
        }
        int result = ps5_agc_gate2_run_sync();
        runtime_async_output = NULL;
        if (diag_ns) {
            const int64_t d = os_time_get_nano() - d0;
            if (d >= diag_ns && ps5_driver_trace_hook && getrusage(1, &ru1) == 0) {
                unsigned long long inv = (unsigned long long)(ru1.ru_nivcsw - ru0.ru_nivcsw);
                unsigned long long vol = (unsigned long long)(ru1.ru_nvcsw - ru0.ru_nvcsw);
                ps5_driver_trace_hook(140, (unsigned long long)d0, (unsigned long long)d,
                                      (unsigned long long)worker | ((inv > 0xffff ? 0xffff : inv) << 8) |
                                      ((vol > 0xffff ? 0xffff : vol) << 24) |
                                      ((unsigned long long)(runtime_shader_pair_count != pairs0) << 40));
            }
        }
""")

open(P, "w", encoding="utf-8").write(s)
print("ok")
