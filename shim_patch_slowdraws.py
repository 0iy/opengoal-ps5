#!/usr/bin/env python3
"""Shim patch (diagnostic): record, per frame, the longest gaps between GL draw calls (engine CPU or non-draw GL calls) and
the longest draw calls; in frames slower than 25 ms print the top events with their position in the frame."""
import os

here = os.path.dirname(os.path.abspath(__file__))
g = os.path.join(here, "ps5shim", "glfix.cpp")
s = open(g, encoding="utf-8").read()
if "ps5_glfix_frame_end" in s:
    print("glfix already patched")
else:
    old = """struct DrawTimer {
  uint64_t t0 = tsc();
  ~DrawTimer() { g_draw_cycles += tsc() - t0; ++g_draw_calls; }
};
"""
    new = """// ---- per-frame draw timeline (diagnostic) ----
struct SlowEv { double at_us, dur_us, gap_us; uint32_t idx; };
SlowEv g_slow[12];
double g_tsc_per_us = 0;
uint64_t g_cal_tsc = 0, g_cal_ns = 0, g_frame_tsc0 = 0, g_last_end_tsc = 0;
uint32_t g_ev_idx = 0;
void note_event(uint64_t t0, uint64_t t1) {
  if (g_tsc_per_us <= 0) {
    if (!g_cal_tsc) { g_cal_tsc = t0; g_cal_ns = now_ns(); }
    else if (now_ns() - g_cal_ns > 50000000ull) g_tsc_per_us = double(t1 - g_cal_tsc) / (double(now_ns() - g_cal_ns) / 1000.0);
    g_last_end_tsc = t1;
    return;
  }
  const double dur = double(t1 - t0) / g_tsc_per_us;
  const double gap = g_last_end_tsc ? double(t0 - g_last_end_tsc) / g_tsc_per_us : 0.0;
  g_last_end_tsc = t1;
  if (!g_frame_tsc0) g_frame_tsc0 = t0;
  const double big = dur > gap ? dur : gap;
  unsigned mn = 0;
  for (unsigned i = 1; i < 12; ++i)
    if ((g_slow[i].dur_us > g_slow[i].gap_us ? g_slow[i].dur_us : g_slow[i].gap_us) <
        (g_slow[mn].dur_us > g_slow[mn].gap_us ? g_slow[mn].dur_us : g_slow[mn].gap_us)) mn = i;
  const double mnv = g_slow[mn].dur_us > g_slow[mn].gap_us ? g_slow[mn].dur_us : g_slow[mn].gap_us;
  if (big > mnv) g_slow[mn] = {double(t0 - g_frame_tsc0) / g_tsc_per_us, dur, gap, g_ev_idx};
  ++g_ev_idx;
}
struct DrawTimer {
  uint64_t t0 = tsc();
  ~DrawTimer() { const uint64_t t1 = tsc(); g_draw_cycles += t1 - t0; ++g_draw_calls; note_event(t0, t1); }
};
"""
    assert s.count(old) == 1
    s = s.replace(old, new)
    s = s.rstrip() + """

// Called once per frame from SDL_GL_SwapWindow with the frame interval in ms; dumps the biggest gaps/draws of slow frames.
extern "C" void ps5_glfix_frame_end(double interval_ms) {
  static uint64_t last_dump = 0;
  const uint64_t n = now_ns();
  if (interval_ms > 25.0 && n - last_dump > 2000000000ull && g_tsc_per_us > 0) {
    last_dump = n;
    SlowEv e[12];
    std::memcpy(e, g_slow, sizeof e);
    std::sort(e, e + 12, [](const SlowEv& a, const SlowEv& b) { return a.at_us < b.at_us; });
    ps5_log("slowdraws: frame %.1f ms, %u draws; events (at ms, draw# before/in, gap ms, draw ms):", interval_ms, g_ev_idx);
    for (const SlowEv& x : e)
      if (x.dur_us > 0 || x.gap_us > 0) ps5_log("  slowdraws: at %7.2f  #%-4u gap %6.2f  draw %6.2f", x.at_us / 1000.0, x.idx, x.gap_us / 1000.0, x.dur_us / 1000.0);
  }
  std::memset(g_slow, 0, sizeof g_slow);
  g_ev_idx = 0;
  g_frame_tsc0 = 0;
  g_last_end_tsc = 0;
}
"""
    if "#include <algorithm>" not in s:
        s = s.replace("#include <cstdint>", "#include <algorithm>\n#include <cstdint>", 1)
    open(g, "w", encoding="utf-8").write(s)
    print("glfix patched")

p = os.path.join(here, "ps5shim", "ps5sdl.cpp")
t = open(p, encoding="utf-8").read()
if "ps5_glfix_frame_end" not in t:
    old = "    if (iv > max_interval) max_interval = iv;\n"
    assert t.count(old) == 1
    t = t.replace(old, "    ps5_glfix_frame_end(iv / 1e6);\n" + old)
    t = t.replace('extern "C" void ps5_loading_overlay(int w, int h);', 'extern "C" void ps5_glfix_frame_end(double);\nextern "C" void ps5_loading_overlay(int w, int h);', 1)
    open(p, "w", encoding="utf-8").write(t)
    print("sdl patched")
