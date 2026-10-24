#!/usr/bin/env python3
"""Offline simulation of the AUTO controller. Extracts fsr_init / fsr_set_ladder_pos / fsr_frame_begin / fsr_frame_end and the
Ps5FsrState struct from the PATCHED OpenGLRenderer.{h,cpp} (same code the console runs), swaps the clock for a fake one, feeds
synthetic frame times and prints the ladder trace. Usage (WSL): python3 ctrl_sim.py <patched jak root, default ~/fsr_src>"""
import os, re, subprocess, sys, tempfile

root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/fsr_src")
d = os.path.join(root, "game/graphics/opengl_renderer")
h = open(f"{d}/OpenGLRenderer.h").read()
c = open(f"{d}/OpenGLRenderer.cpp").read()
st = h[h.index("  struct Ps5FsrState {"):h.index("  } m_fsr;") + len("  } m_fsr;")]
a = c.index("void OpenGLRenderer::fsr_init()")
b = c.index("// Render target for a scaled percent")
body = c[a:b].replace("ps5_fsr_now_us()", "g_now_us")
prog = r'''
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <string>
typedef unsigned GLuint; typedef int GLint;
struct Fbo {};
struct RenderOptions { bool save_screenshot=false; int msaa_samples=1, game_res_w=1920, game_res_h=1080; float pmode_alp_register=1.f; };
namespace lg { template <class... A> void info(const char* f, A...) { } template <class... A> void error(const char*, A...) {} }
long long g_now_us = 0;
float ps5_fsr_env_f(const char* name, float def) { const char* e = std::getenv(name); return (e && *e) ? (float)std::atof(e) : def; }
struct OpenGLRenderer {
''' + st + r'''
  void fsr_init(); void fsr_frame_begin(const RenderOptions&); void fsr_frame_end(); void fsr_set_ladder_pos(int, const char*);
};
''' + body.replace('lg::info("fsr: {}% -> {}% ({}) frame {}", f.ladder[f.lad], f.ladder[pos], why, f.frame);',
                   'printf("  t=%6.1fs frame %ld: %d%% -> %d%% (%s)\\n", g_now_us/1e6, f.frame, f.ladder[f.lad], f.ladder[pos], why);') + r'''
int main(int argc, char** argv) {
  double cpu = atof(argv[1]), gpu100 = atof(argv[2]);   // ms; gpu cost scales with pct^2
  double cpu2 = argc > 4 ? atof(argv[4]) : cpu, gpu2 = argc > 5 ? atof(argv[5]) : gpu100; // second phase
  int sec1 = argc > 3 ? atoi(argv[3]) : 60;
  setenv("PS5_RENDER_SCALE", "auto", 1); setenv("PS5_FSR_LOG", "0", 1);
  OpenGLRenderer r; RenderOptions o;
  const double V = 1000.0 / 60;
  int changes = 0, last = 100; long hist[4] = {0,0,0,0};
  for (long fr = 0; fr < 60 * 120; fr++) {
    bool p2 = fr >= 60L * sec1;
    r.fsr_frame_begin(o);
    int pct = r.m_fsr.pct;
    if (pct != last) { changes++; last = pct; }
    for (int i = 0; i < 4; i++) if (r.m_fsr.ladder[i] == pct) hist[i]++;
    double g = (p2 ? gpu2 : gpu100) * (pct / 100.0) * (pct / 100.0), cp = p2 ? cpu2 : cpu;
    double work = std::max(cp, g);
    if (pct != r.m_fsr.ladder[0] && r.m_fsr.settle >= 5) work += 8;   // hitch right after a change (target switch)
    double R = work * 0.9, P = std::ceil(work / V - 1e-9) * V;
    g_now_us += (long long)(P * 1000);
    r.m_fsr.t_end = r.m_fsr.t_begin + (long long)(R * 1000);
  }
  printf("  changes %d | frames at 100/83/67/50: %ld %ld %ld %ld | final %d%%\n", changes, hist[0], hist[1], hist[2], hist[3], last);
}
'''
with tempfile.TemporaryDirectory() as t:
    open(f"{t}/s.cpp", "w").write(prog)
    r = subprocess.run(["g++", "-std=c++20", "-O1", "-w", f"{t}/s.cpp", "-o", f"{t}/s"], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[:3000]); sys.exit(1)
    scen = [("light scene (cpu 8, gpu 9 at 100%)", ["8", "9"]),
            ("GPU bound heavy (cpu 8, gpu 26 at 100%)", ["8", "26"]),
            ("CPU bound (cpu 24, gpu 3): scaling cannot help", ["24", "3"]),
            ("heavy 30 s, then light (gpu 26 -> 9)", ["8", "26", "30", "8", "9"]),
            ("borderline (gpu 17.5 at 100%)", ["8", "17.5"])]
    for name, a in scen:
        print(name)
        print(subprocess.run([f"{t}/s"] + a, capture_output=True, text=True).stdout, end="")
