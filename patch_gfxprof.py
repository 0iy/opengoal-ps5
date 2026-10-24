#!/usr/bin/env python3
"""Diagnostic patch for jak-project (run in WSL): per-phase wall time of the OpenGL render loop, logged through ps5_log
every 180 frames: wait-for-dma, render_game_frame, imgui, frame limiter, swap, the rest."""
import os

import json
_REL = "game/graphics/pipelines/opengl.cpp"
P = os.path.join(os.path.expanduser("~/jak"), json.loads(os.environ.get("SYNC_FILE_MAP") or "{}").get(_REL, _REL))  # SYNC_FILE_MAP: see sync_upstream.py
s = open(P, encoding="utf-8").read()
if "__ps5__ gfxprof" in s:
    print("already patched")
    raise SystemExit

# helper after the includes
old = "#include <chrono>  // __ps5__\n" if "#include <chrono>  // __ps5__\n" in s else "#include <condition_variable>\n"
helper = r'''
// __ps5__ gfxprof: wall time of the phases of the render loop
void ps5_log(const char*, ...);
#include <chrono>
namespace {
struct Ps5Prof {
  double ns[8] = {};
  int frames = 0;
  std::chrono::steady_clock::time_point mark = std::chrono::steady_clock::now();
  void lap(int i) {
    const auto n = std::chrono::steady_clock::now();
    ns[i] += double(std::chrono::duration_cast<std::chrono::nanoseconds>(n - mark).count());
    mark = n;
  }
  void restart() { mark = std::chrono::steady_clock::now(); }
  void frame_done() {
    if (++frames == 180) {
      ps5_log("gfxprof/frame ms: wait-dma %.2f render-frame %.2f imgui %.2f limiter %.2f swap %.2f other %.2f", ns[0] / 1e6 / frames,
              ns[1] / 1e6 / frames, ns[2] / 1e6 / frames, ns[3] / 1e6 / frames, ns[4] / 1e6 / frames, ns[5] / 1e6 / frames);
      for (double& v : ns) v = 0;
      frames = 0;
    }
  }
};
Ps5Prof g_ps5prof;
}  // namespace
'''
assert s.count(old) == 1
s = s.replace(old, old + helper)

# laps
old = "  // wait for a copied chain.\n  bool got_chain = false;\n  {"
new = "  g_ps5prof.lap(5);  // __ps5__ gfxprof: everything since the previous frame's swap that is not below\n  // wait for a copied chain.\n  bool got_chain = false;\n  {"
assert s.count(old) == 1
s = s.replace(old, new)

old = "                                            [=] { return g_gfx_data->has_data_to_render; });\n  }\n"
new = old + "  g_ps5prof.lap(0);  // __ps5__ gfxprof\n"
assert s.count(old) == 1
s = s.replace(old, new)

old = "  // render debug\n  if (is_imgui_visible()) {"
new = "  g_ps5prof.lap(1);  // __ps5__ gfxprof: game render done\n  // render debug\n  if (is_imgui_visible()) {"
assert s.count(old) == 1
s = s.replace(old, new)

old = "  // actual vsync\n  g_gfx_data->debug_gui.finish_frame();"
new = "  g_ps5prof.lap(2);  // __ps5__ gfxprof: imgui\n  // actual vsync\n  g_gfx_data->debug_gui.finish_frame();"
assert s.count(old) == 1
s = s.replace(old, new)

old = "  {\n    auto p = scoped_prof(\"swap-buffers\");\n    SDL_GL_SwapWindow(m_window);\n  }\n"
new = "  g_ps5prof.lap(3);  // __ps5__ gfxprof: frame limiter\n" + old + "  g_ps5prof.lap(4);  // __ps5__ gfxprof: swap\n  g_ps5prof.frame_done();\n"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
