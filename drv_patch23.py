#!/usr/bin/env python3
"""Driver patch 23 (diagnostic, PS5_GPU_TRACE=1): a poller thread timestamps the completion marker of every submitted
command group. The gaps between consecutive completions are the GPU time per group. PS5_NO_COMBINE=1 keeps every draw
its own group. ps5_driver_gputrace_report() formats the numbers for the app log."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_gputrace_report" in s:
    print("already patched")
    raise SystemExit

anchor = "/* Keep draw bodies and their dependency barriers. Fixed-framebuffer batches"
code = r'''
/* ---- GPU completion trace (diagnostic) ---- */
#include <pthread.h>
#include <stdatomic.h>
struct gputrace_item { volatile uint64_t *marker; uint32_t expected; uint32_t words; int64_t submit_ns; uint32_t draw_index; };
#define GPUTRACE_RING 8192u
static struct gputrace_item gputrace_ring[GPUTRACE_RING];
static _Atomic uint64_t gputrace_head, gputrace_tail;
static int gputrace_enabled = -1;
static pthread_t gputrace_thread;
static _Atomic int gputrace_started;
static uint32_t gputrace_frame_draw;
static pthread_mutex_t gputrace_lock = PTHREAD_MUTEX_INITIALIZER;
struct gputrace_stat { uint32_t draw_index, words; int64_t dt_ns; };
static struct gputrace_stat gputrace_top[12];
static int64_t gputrace_sum_ns, gputrace_groups;

static void gputrace_record(uint32_t draw_index, uint32_t words, int64_t dt)
{
    pthread_mutex_lock(&gputrace_lock);
    gputrace_sum_ns += dt;
    ++gputrace_groups;
    unsigned min_i = 0;
    for (unsigned i = 1; i < 12; ++i)
        if (gputrace_top[i].dt_ns < gputrace_top[min_i].dt_ns)
            min_i = i;
    if (dt > gputrace_top[min_i].dt_ns) {
        gputrace_top[min_i].dt_ns = dt;
        gputrace_top[min_i].draw_index = draw_index;
        gputrace_top[min_i].words = words;
    }
    pthread_mutex_unlock(&gputrace_lock);
}

static void *gputrace_main(void *unused)
{
    (void)unused;
    int64_t prev_done = 0;
    for (;;) {
        uint64_t tail = atomic_load_explicit(&gputrace_tail, memory_order_relaxed);
        if (tail >= atomic_load_explicit(&gputrace_head, memory_order_acquire)) {
            __builtin_ia32_pause();
            continue;
        }
        struct gputrace_item it = gputrace_ring[tail % GPUTRACE_RING];
        int64_t t0 = os_time_get_nano();
        int ok = 1;
        for (;;) {
            flush_gpu_data((const void *)it.marker, sizeof(*it.marker));
            if (*it.marker == it.expected)
                break;
            if (os_time_get_nano() - t0 > 300000000) {
                ok = 0;
                prev_done = 0;
                break;
            }
            __builtin_ia32_pause();
        }
        if (ok) {
            const int64_t done = os_time_get_nano();
            const int64_t start = prev_done > it.submit_ns ? prev_done : it.submit_ns;
            gputrace_record(it.draw_index, it.words, done - start);
            prev_done = done;
        }
        atomic_store_explicit(&gputrace_tail, tail + 1, memory_order_release);
    }
    return NULL;
}

static int gputrace_on(void)
{
    if (gputrace_enabled < 0)
        gputrace_enabled = getenv("PS5_GPU_TRACE") != NULL;
    return gputrace_enabled;
}

static void gputrace_push(volatile uint64_t *marker, uint32_t expected, uint32_t words)
{
    if (!gputrace_on())
        return;
    if (!atomic_exchange(&gputrace_started, 1))
        pthread_create(&gputrace_thread, NULL, gputrace_main, NULL);
    uint64_t head = atomic_load_explicit(&gputrace_head, memory_order_relaxed);
    if (head - atomic_load_explicit(&gputrace_tail, memory_order_acquire) >= GPUTRACE_RING - 1)
        return;
    struct gputrace_item *it = &gputrace_ring[head % GPUTRACE_RING];
    it->marker = marker;
    it->expected = expected;
    it->words = words;
    it->submit_ns = os_time_get_nano();
    it->draw_index = gputrace_frame_draw++;
    atomic_store_explicit(&gputrace_head, head + 1, memory_order_release);
}

/* called once per frame (swap): restart the per-frame group numbering */
void ps5_driver_gputrace_frame(void) { gputrace_frame_draw = 0; }

/* formats "groups=.. busy=.. ms top: #idx(words)=us ..." and resets the counters */
int ps5_driver_gputrace_report(char *out, size_t n)
{
    if (!gputrace_on() || !n)
        return 0;
    pthread_mutex_lock(&gputrace_lock);
    int w = snprintf(out, n, "groups=%lld busy=%.1f ms top:", (long long)gputrace_groups, gputrace_sum_ns / 1e6);
    for (int k = 0; k < 12; ++k) {
        unsigned best = 0;
        for (unsigned i = 1; i < 12; ++i)
            if (gputrace_top[i].dt_ns > gputrace_top[best].dt_ns)
                best = i;
        if (!gputrace_top[best].dt_ns || w >= (int)n - 40)
            break;
        w += snprintf(out + w, n - (size_t)w, " #%u(%uw)=%.0fus", gputrace_top[best].draw_index, gputrace_top[best].words,
                      gputrace_top[best].dt_ns / 1e3);
        gputrace_top[best].dt_ns = 0;
    }
    gputrace_sum_ns = 0;
    gputrace_groups = 0;
    memset(gputrace_top, 0, sizeof gputrace_top);
    pthread_mutex_unlock(&gputrace_lock);
    return w;
}

'''
assert s.count(anchor) == 1
s = s.replace(anchor, code + anchor)

old = "static unsigned runtime_batch_combine(void)\n{\n    unsigned groups = 0;"
new = "static unsigned runtime_batch_combine(void)\n{\n    unsigned groups = 0;\n    if (getenv(\"PS5_NO_COMBINE\"))\n        return runtime_batch_count;"
assert s.count(old) == 1
s = s.replace(old, new)

old = """    BATCH_SUBMIT_MARK(1);
#ifdef PS5_FRAME_SUSPEND
    if (attempted && runtime_defer_suspend"""
new = """    BATCH_SUBMIT_MARK(1);
    if (gputrace_on())
        for (unsigned i = 0; i < runtime_batch_count; ++i)
            if (runtime_batch_entries[i].submit.word_count)
                gputrace_push(runtime_batch_entries[i].marker, runtime_batch_entries[i].expected,
                              runtime_batch_entries[i].submit.word_count);
#ifdef PS5_FRAME_SUSPEND
    if (attempted && runtime_defer_suspend"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
