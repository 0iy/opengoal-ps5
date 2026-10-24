#!/usr/bin/env python3
"""Shim patch: skip glClear on the window framebuffer (FBO 0) after the first frames.

OpenGOAL clears the window framebuffer twice per frame and then draws over its whole draw region. On the PS5 the window
framebuffer is a scanout buffer, so that clear has to wait until the previous flip released the buffer (a vblank),
which aligns the start of every frame to the display and turns a 15-17 ms frame into 33 ms. The buffers keep their
black letterbox bars (nothing else ever draws there). /data/opengoal/config/keepwindowclear.txt restores the clears."""
import os

here = os.path.dirname(os.path.abspath(__file__))
g = os.path.join(here, "ps5shim", "glfix.cpp")
s = open(g, encoding="utf-8").read()
if "g_bound_draw_fbo" in s:
    print("already patched")
    raise SystemExit

old = """void w_BindFramebuffer(GLenum target, GLuint fbo) {
  load_real();
  if (fbo && !g_frame_fbo) g_frame_fbo = fbo;
  R.BindFramebuffer(target, fbo);
}"""
new = """GLuint g_bound_draw_fbo = 0;
uint64_t g_frames_seen = 0, g_window_clears_skipped = 0;
void w_BindFramebuffer(GLenum target, GLuint fbo) {
  load_real();
  if (fbo && !g_frame_fbo) g_frame_fbo = fbo;
  if (target == 0x8D40 /*GL_FRAMEBUFFER*/ || target == 0x8CA9 /*GL_DRAW_FRAMEBUFFER*/) g_bound_draw_fbo = fbo;
  R.BindFramebuffer(target, fbo);
}
bool keep_window_clear() {
  static int v = -1;
  if (v < 0) {
    struct stat st;
    v = stat("/data/opengoal/config/keepwindowclear.txt", &st) == 0;
  }
  return v == 1;
}"""
assert s.count(old) == 1
s = s.replace(old, new)

# the generated glClear wrapper
old = "void w_glClear(unsigned a) {\n  using Fn = void (*)(unsigned);"
assert s.count(old) == 1, s.count(old)
new = old + "\n  if (g_bound_draw_fbo == 0 && g_frames_seen > 8 && !keep_window_clear()) { ++g_window_clears_skipped; return; }"
s = s.replace(old, new)

old = "extern \"C\" void ps5_glfix_frame_end(double interval_ms) {\n"
assert s.count(old) == 1
s = s.replace(old, old + "  ++g_frames_seen;\n")
open(g, "w", encoding="utf-8").write(s)
print("ok")
