#!/usr/bin/env python3
"""Shim patch: event tracer. A ring of 32-byte events (draws, GL calls, frames, driver waits/drains/submits) is recorded
for a window of seconds and dumped as /data/opengoal/log/trace_<n>.bin. Control file /data/opengoal/config/trace.txt:
"<start seconds after the first frame> <duration seconds>" (default "25 10"). Convert with trace2json.py (Chrome/Perfetto).
Event ids: 1 frame, 10 draw (tsc timeline); >=100 use CLOCK_MONOTONIC ns: 100..103 driver waits (retire, frame, flip, collect),
110 forced buffer drain (a = caller), 111 batch submit, 112 backpressure wait, 200+k GL call slot k."""
import os

here = os.path.dirname(os.path.abspath(__file__))
g = os.path.join(here, "ps5shim", "glfix.cpp")
s = open(g, encoding="utf-8").read()
if "TRACE_CORE" in s:
    print("glfix already patched")
else:
    NL = chr(10)
    inc = "#include <cstring>" + NL
    assert s.count(inc) == 1
    s = s.replace(inc, inc + NL.join(["#include <atomic>", "#include <cstdio>", "#include <pthread.h>", "#include <sys/mman.h>"]) + NL)
    # 1. tracer core right before the DrawTimer definition
    anchor = "struct DrawTimer {"
    assert s.count(anchor) == 1
    core = r'''// TRACE_CORE: event tracer (diagnostic)
struct TraceEv { uint64_t tsc, dur; uint32_t ev, tid; uint64_t a; };
TraceEv* g_tr = nullptr;
std::atomic<uint32_t> g_tr_n{0};
uint32_t g_tr_cap = 0;
std::atomic<int> g_tr_on{0};
uint64_t g_tr_tsc0 = 0, g_tr_ns0 = 0;
inline void trace_emit(uint32_t ev, uint64_t t0, uint64_t dur, uint64_t a) {
  if (!g_tr_on.load(std::memory_order_relaxed)) return;
  const uint32_t i = g_tr_n.fetch_add(1, std::memory_order_relaxed);
  if (i >= g_tr_cap) { g_tr_on.store(0, std::memory_order_relaxed); return; }
  g_tr[i] = {t0, dur, ev, static_cast<uint32_t>(reinterpret_cast<uintptr_t>(pthread_self())), a};
}
'''
    s = s.replace(anchor, core + anchor)
    # 2. draws
    old = "~DrawTimer() { const uint64_t t1 = tsc(); g_draw_cycles += t1 - t0; ++g_draw_calls; note_event(t0, t1, w0); }"
    assert s.count(old) == 1
    s = s.replace(old, "~DrawTimer() { const uint64_t t1 = tsc(); g_draw_cycles += t1 - t0; ++g_draw_calls; note_event(t0, t1, w0); trace_emit(10, t0, t1 - t0, g_ev_idx); }")
    # 3. GL calls
    old = "~GlCallTimer() { const uint64_t d = now_ns() - t0; GlCallStat& e = g_glcalls[slot]; ++e.n; e.ns += d; if (d > e.max_ns) e.max_ns = d; }"
    assert s.count(old) == 1
    s = s.replace(old, "~GlCallTimer() { const uint64_t d = now_ns() - t0; GlCallStat& e = g_glcalls[slot]; ++e.n; e.ns += d; if (d > e.max_ns) e.max_ns = d; trace_emit(200 + slot, t0, d, 0); }")
    # 4. control (called once per frame from SDL_GL_SwapWindow) at the end of the file's extern "C" area: append before last namespace close is
    #    fragile, so add a new extern "C" block at the end of the file
    s += r'''
// TRACE_CONTROL
extern "C" void (*ps5_driver_trace_hook)(unsigned, unsigned long long, unsigned long long, unsigned long long);
extern "C" void ps5_trace_driver_event(unsigned ev, unsigned long long t0, unsigned long long dur, unsigned long long a) {
  trace_emit(ev, t0, dur, a);
}
extern "C" void ps5_trace_frame_tick(uint64_t frame_no, uint64_t interval_ns) {
  static int state = 0;  // 0 not read, 1 waiting, 2 recording, 3 done, 4 disabled
  static uint64_t first_ns = 0;
  static unsigned start_s = 25, dur_s = 10, dump_no = 0;
  const uint64_t n = now_ns();
  if (state == 0) {
    first_ns = n;
    FILE* f = std::fopen("/data/opengoal/config/trace.txt", "r");
    if (!f) { state = 4; return; }
    unsigned a = 0, b = 0;
    if (std::fscanf(f, "%u %u", &a, &b) == 2) { start_s = a; dur_s = b; }
    std::fclose(f);
    state = 1;
    ps5_driver_trace_hook = ps5_trace_driver_event;
    ps5_log("trace: armed, start %u s after the first frame, %u s long", start_s, dur_s);
  }
  if (state == 1 && n - first_ns >= uint64_t(start_s) * 1000000000ull) {
    g_tr_cap = 1u << 21;
    void* m = mmap(nullptr, size_t(g_tr_cap) * sizeof(TraceEv), PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (m == MAP_FAILED) { ps5_log("trace: mmap failed"); state = 4; return; }
    g_tr = static_cast<TraceEv*>(m);
    g_tr_n.store(0);
    g_tr_tsc0 = tsc();
    g_tr_ns0 = now_ns();
    g_tr_on.store(1);
    state = 2;
    ps5_log("trace: recording");
  }
  if (state == 2) {
    trace_emit(1, tsc(), interval_ns, frame_no);
    if (!g_tr_on.load() || n - first_ns >= uint64_t(start_s + dur_s) * 1000000000ull) {
      g_tr_on.store(0);
      const uint32_t cnt = std::min<uint32_t>(g_tr_n.load(), g_tr_cap);
      char path[96];
      std::snprintf(path, sizeof path, "/data/opengoal/log/trace_%u.bin", dump_no++);
      FILE* f = std::fopen(path, "wb");
      if (f) {
        struct { char magic[8]; uint32_t count, ver; double tsc_per_ns; uint64_t tsc0, ns0; } h = {{'P', 'S', '5', 'T', 'R', 'C', '0', '1'}, cnt, 1,
          g_tsc_per_us > 0 ? g_tsc_per_us / 1000.0 : 2.0, g_tr_tsc0, g_tr_ns0};
        std::fwrite(&h, sizeof h, 1, f);
        std::fwrite(g_tr, sizeof(TraceEv), cnt, f);
        std::fclose(f);
      }
      ps5_log("trace: dumped %u events to %s", cnt, path);
      state = 3;
    }
  }
}
'''
    open(g, "w", encoding="utf-8").write(s)
    print("glfix patched")

p = os.path.join(here, "ps5shim", "ps5sdl.cpp")
t = open(p, encoding="utf-8").read()
if "ps5_trace_frame_tick" in t:
    print("sdl already patched")
else:
    old = "  prev_swap_t = t;\n"
    assert t.count(old) == 1
    t = t.replace(old, "  { static uint64_t fno = 0; ps5_trace_frame_tick(++fno, prev_swap_t ? t - prev_swap_t : 0); }\n  prev_swap_t = t;\n")
    anchor = 'extern "C" void ps5_loading_overlay(int w, int h);'
    assert t.count(anchor) == 1
    t = t.replace(anchor, anchor + '\nextern "C" void ps5_trace_frame_tick(uint64_t frame_no, uint64_t interval_ns);')
    open(p, "w", encoding="utf-8").write(t)
    print("sdl patched")
