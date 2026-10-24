#!/usr/bin/env python3
"""Dynamic internal resolution + FSR 1.0 (EASU + RCAS) for the jak-project OpenGL renderer. See docs/FSR.md.

Idempotent. Target tree: env FSR_SRC is REQUIRED (a jak-project root that contains game/: ~/fsr_src for tests, ~/jak for the live tree). Patches game/graphics/opengl_renderer/OpenGLRenderer.{h,cpp}. The GLSL comes from fsr/fsr.vert
and fsr/fsr.frag next to this script and is embedded in the C++ as string literals (no new files on the console).

Run-time switches (environment, set by ps5shim/appmain.cpp from ps5.cfg, see docs/FSR.md 'integration'):
  PS5_RENDER_SCALE  unset/100 = off (engine untouched), 0 or "auto" = dynamic, 33..99 = fixed percent (83 77 67 50 typical)
  PS5_FSR           0 = scaled rendering with the plain bilinear blit (A/B), default 1 = EASU(+RCAS)
  PS5_FSR_SHARP     0 = no RCAS pass, 1..10 = RCAS strength (10 = 0.2 stops, FSR default), default 7
  PS5_FSR_TARGET_MS controller target for render() time, default 16.0
  PS5_FSR_REFRESH   display refresh in Hz for the vsync-miss test, default 60
  PS5_FSR_MIN       lowest percent in AUTO, default 50
  PS5_FSR_PREWARM   1 (default) = allocate every AUTO render target at the first frame, 0 = lazily
  PS5_FSR_LOG       1 (default) = log scale changes and a status line every 300 frames
"""
import os

assert os.environ.get("FSR_SRC"), "set FSR_SRC to the jak-project root to patch (e.g. ~/fsr_src for a test copy, ~/jak for the live tree)"
ROOT = os.path.expanduser(os.environ["FSR_SRC"])
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(ROOT, "game", "graphics", "opengl_renderer")
HDR, CPP = os.path.join(D, "OpenGLRenderer.h"), os.path.join(D, "OpenGLRenderer.cpp")
h = open(HDR, encoding="utf-8").read()
c = open(CPP, encoding="utf-8").read()
if "ps5_fsr" in h and "ps5_fsr" in c:
    print("already patched")
    raise SystemExit
assert "ps5_fsr" not in h and "ps5_fsr" not in c, "half patched tree"


def rep(s, old, new):
    assert s.count(old) == 1, (s.count(old), old[:70])
    return s.replace(old, new)


vert = open(os.path.join(HERE, "fsr", "fsr.vert"), encoding="utf-8").read()
frag = open(os.path.join(HERE, "fsr", "fsr.frag"), encoding="utf-8").read()
assert ')FSRGLSL"' not in vert + frag

# ------------------------------------------------------------------ header
h = rep(h, "  GLuint screen_vao = 0;  // vertex array object for a screen-space draw\n", r'''  // __ps5__ ps5_fsr: dynamic internal resolution + FSR 1.0 (patch_fsr.py). All state is per renderer instance (no statics).
  struct Ps5FsrState {
    bool inited = false;
    int mode = 0;            // 0 off, 1 fixed, 2 auto
    int fixed_pct = 100;
    bool fsr_on = true;      // false: scaled rendering with the plain bilinear blit
    int sharp = 7;           // 0 = no RCAS, 1..10
    float target_ms = 16.0f;
    float refresh_hz = 60.0f;
    int min_pct = 50;
    bool prewarm = true, prewarmed = false, log = true;
    int ladder[4] = {100, 83, 67, 50};
    int ladder_n = 4;
    // current frame
    int pct = 100;           // percent chosen for this frame
    bool active = false;     // this frame renders below the window size (set in setup_frame)
    int win_x = 0, win_y = 0, win_w = 1, win_h = 1;  // draw region in window pixels
    // render target pool (100 percent uses the engine's own render_buffer)
    struct Slot {
      Fbo fbo;
      int pct = 0;
    } slots[4];
    // GL objects
    GLuint prog[2] = {0, 0};  // 0 EASU, 1 RCAS
    GLint loc[2][7] = {{-1, -1, -1, -1, -1, -1, -1}, {-1, -1, -1, -1, -1, -1, -1}};
    GLuint mid_fbo = 0, mid_tex = 0;
    int mid_w = 0, mid_h = 0;
    bool gl_failed = false;
    // controller
    long frame = 0;
    long long t_begin = 0, t_end = 0;  // microseconds, steady clock
    float sp[30], sr[30];
    int n = 0, settle = 0;
    int lad = 0;             // position in ladder
    int bad_windows = 0, good_windows = 0, up_wait_frames = 0;
    int backoff[4] = {6, 6, 6, 6};
    bool probing = false;
    int probe_windows = 0;
    long block_down_until = 0;
    long block_len = 1800;   // frames; doubles each time a down step proves useless
    bool verify = false;
    float r_before = 0;
  } m_fsr;
  void fsr_init();
  void fsr_frame_begin(const RenderOptions& settings);
  void fsr_frame_end();
  void fsr_set_ladder_pos(int pos, const char* why);
  Fbo* fsr_slot(int pct, int w, int h);
  bool fsr_build();
  bool fsr_present(const Fbo* src, int brightness_contrast_color, int brightness_contrast_alpha);

  GLuint screen_vao = 0;  // vertex array object for a screen-space draw
''')

# ------------------------------------------------------------------ cpp: helpers
helpers = r'''// ---------------------------------------------------------------- __ps5__ ps5_fsr
// Dynamic internal resolution + FSR 1.0. See docs/FSR.md. The renderer draws the world into a render FBO of
// game_res * pct / 100 and the final pass (do_pcrtc_effects) upscales it to the draw region of the window.
namespace {
const char* const kPs5FsrVert = R"FSRGLSL(@@VERT@@)FSRGLSL";
const char* const kPs5FsrFrag = R"FSRGLSL(@@FRAG@@)FSRGLSL";

long long ps5_fsr_now_us() {
  return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

float ps5_fsr_env_f(const char* name, float def) {
  const char* e = std::getenv(name);
  return (e && *e) ? (float)std::atof(e) : def;
}

GLuint ps5_fsr_compile(GLenum type, const std::string& src, const char* what) {
  GLuint s = glCreateShader(type);
  const char* p = src.c_str();
  glShaderSource(s, 1, &p, nullptr);
  glCompileShader(s);
  GLint ok = 0;
  glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok) {
    char err[1024];
    glGetShaderInfoLog(s, sizeof err, nullptr, err);
    lg::error("fsr: failed to compile {}: {}", what, err);
    glDeleteShader(s);
    return 0;
  }
  return s;
}
}  // namespace

void OpenGLRenderer::fsr_init() {
  auto& f = m_fsr;
  f.inited = true;
  const char* sc = std::getenv("PS5_RENDER_SCALE");
  if (sc && *sc) {
    if (!std::strcmp(sc, "auto") || !std::strcmp(sc, "0")) {
      f.mode = 2;
    } else {
      int v = std::atoi(sc);
      if (v >= 33 && v < 100) {
        f.mode = 1;
        f.fixed_pct = v;
      }
    }
  }
  f.fsr_on = ps5_fsr_env_f("PS5_FSR", 1.f) != 0.f;
  f.sharp = std::min(10, std::max(0, (int)ps5_fsr_env_f("PS5_FSR_SHARP", 7.f)));
  f.target_ms = ps5_fsr_env_f("PS5_FSR_TARGET_MS", 16.0f);
  f.refresh_hz = std::max(24.f, ps5_fsr_env_f("PS5_FSR_REFRESH", 60.f));
  f.min_pct = (int)ps5_fsr_env_f("PS5_FSR_MIN", 50.f);
  f.prewarm = ps5_fsr_env_f("PS5_FSR_PREWARM", 1.f) != 0.f;
  f.log = ps5_fsr_env_f("PS5_FSR_LOG", 1.f) != 0.f;
  const int all[4] = {100, 83, 67, 50};
  f.ladder_n = 0;
  for (int p : all)
    if (p >= f.min_pct || p == 100)
      f.ladder[f.ladder_n++] = p;
  f.lad = 0;
  f.pct = f.mode == 1 ? f.fixed_pct : 100;
  if (f.mode)
    lg::info("fsr: mode {} fixed {}% fsr {} sharp {} target {:.1f} ms refresh {:.0f} min {}%", f.mode, f.fixed_pct,
             f.fsr_on, f.sharp, f.target_ms, f.refresh_hz, f.min_pct);
}

// Change the AUTO ladder position. Resets the measurement window.
void OpenGLRenderer::fsr_set_ladder_pos(int pos, const char* why) {
  auto& f = m_fsr;
  if (f.log)
    lg::info("fsr: {}% -> {}% ({}) frame {}", f.ladder[f.lad], f.ladder[pos], why, f.frame);
  f.lad = pos;
  f.n = 0;
  f.settle = 6;  // frames after a change are not measured (target resize, copier reallocation)
  f.bad_windows = f.good_windows = 0;
  f.up_wait_frames = 0;
}

// Called first thing in render(): measures the previous frame and picks this frame's percent.
void OpenGLRenderer::fsr_frame_begin(const RenderOptions& s) {
  auto& f = m_fsr;
  if (!f.inited)
    fsr_init();
  f.active = false;
  if (f.mode == 0) {
    f.pct = 100;
    return;
  }
  f.frame++;
  if (s.save_screenshot || s.msaa_samples != 1 || s.game_res_w < 320 || s.game_res_h < 200) {
    f.pct = 100;
    f.t_begin = 0;  // do not measure across this frame
    return;
  }
  if (f.mode == 1) {
    f.pct = f.fixed_pct;
    return;
  }
  // ---- AUTO controller
  const long long now = ps5_fsr_now_us();
  if (f.t_begin && f.t_end >= f.t_begin) {
    const float P = (now - f.t_begin) / 1000.f;   // frame period
    const float R = (f.t_end - f.t_begin) / 1000.f;  // time inside render() (CPU recording + waits on the GPU)
    if (P < 100.f && f.settle > 0)
      f.settle--;
    else if (P < 100.f && f.n < 30) {
      f.sp[f.n] = P;
      f.sr[f.n] = R;
      f.n++;
    }  // shortcut: frames over 100 ms (loads, pauses) are dropped, not counted
  }
  f.t_begin = now;
  f.t_end = 0;

  if (f.n == 30) {
    float sp[30], sr[30];
    std::copy(f.sp, f.sp + 30, sp);
    std::copy(f.sr, f.sr + 30, sr);
    std::sort(sp, sp + 30);
    std::sort(sr, sr + 30);
    float aP = 0, aR = 0;
    for (int i = 0; i < 28; i++) {  // drop the 2 worst frames of the window (single hitches)
      aP += sp[i];
      aR += sr[i];
    }
    aP /= 28.f;
    aR /= 28.f;
    const float V = 1000.f / f.refresh_hz;
    const bool miss = aR > f.target_ms || aP > V * 1.08f;
    const bool good = aR < f.target_ms * 0.80f && aP < V * 1.04f;
    f.n = 0;
    if (f.log && f.frame % 300 < 30)
      lg::info("fsr: status {}% period {:.2f} ms render {:.2f} ms", f.ladder[f.lad], aP, aR);
    if (f.verify) {  // first window after a down step: did it help?
      f.verify = false;
      if (miss && aR > 0.93f * f.r_before && aP > V * 1.08f && f.lad > 0) {
        f.block_down_until = f.frame + f.block_len;  // the load is not resolution bound (CPU/driver): stop trying for a while
        f.block_len = std::min(21600L, f.block_len * 2);
        fsr_set_ladder_pos(f.lad - 1, "down step had no effect, blocking down");
        f.verify = false;
      }
    } else if (miss) {
      f.good_windows = 0;
      f.bad_windows++;
      if (f.lad < f.ladder_n - 1 && f.frame >= f.block_down_until && (f.bad_windows >= 2 || aP > V * 1.5f)) {
        if (f.probing && f.probe_windows < 4)  // the step up just failed: wait longer before the next probe
          f.backoff[f.lad] = std::min(96, f.backoff[f.lad] * 2);
        f.probing = false;
        f.r_before = aR;
        f.verify = true;
        fsr_set_ladder_pos(f.lad + 1, "frame time over target");
      }
    } else {
      f.bad_windows = 0;
      if (f.probing && ++f.probe_windows >= 4) {
        f.probing = false;
        f.backoff[f.lad] = 6;
      }
      if (good && f.lad > 0)
        f.good_windows++;
      else
        f.good_windows = 0;
    }
  }
  // up step: enough good windows, then wait for a safe point (fade / blackout hides the target switch) or 300 frames
  if (f.lad > 0 && f.good_windows >= f.backoff[f.lad - 1]) {
    if (s.pmode_alp_register < 1.f || ++f.up_wait_frames > 300) {
      f.probing = true;
      f.probe_windows = 0;
      fsr_set_ladder_pos(f.lad - 1, s.pmode_alp_register < 1.f ? "headroom, at fade" : "headroom");
    }
  }
  f.pct = f.ladder[f.lad];
}

void OpenGLRenderer::fsr_frame_end() {
  if (m_fsr.mode == 2 && m_fsr.t_begin)
    m_fsr.t_end = ps5_fsr_now_us();
}

// Render target for a scaled percent; reuses a pooled FBO of the right size.
Fbo* OpenGLRenderer::fsr_slot(int pct, int w, int h) {
  auto& f = m_fsr;
  int idx = -1;
  for (int i = 0; i < 4 && idx < 0; i++)
    if (f.slots[i].pct == pct)
      idx = i;
  for (int i = 0; i < 4 && idx < 0; i++)
    if (f.slots[i].pct == 0)
      idx = i;
  if (idx < 0)
    idx = 0;  // shortcut: evict slot 0; AUTO uses at most 3 slots, a fixed scale uses 1
  auto& sl = f.slots[idx];
  if (!sl.fbo.matches(w, h, 1)) {
    sl.fbo.clear();
    lg::info("fsr: render target {}% = {}x{}", pct, w, h);
    sl.fbo = make_fbo(w, h, 1, true);
  }
  sl.pct = pct;
  return &sl.fbo;
}

bool OpenGLRenderer::fsr_build() {
  auto& f = m_fsr;
  const std::string vs = kPs5FsrVert;
  std::string fs = kPs5FsrFrag;
  const size_t nl = fs.find('\n');  // splice the pass define behind the #version line
  const char* defs[2] = {"#define FSR_EASU 1\n", "#define FSR_RCAS 1\n"};
  GLuint v = ps5_fsr_compile(GL_VERTEX_SHADER, vs, "vertex shader");
  for (int i = 0; i < 2 && v; i++) {
    GLuint fr = ps5_fsr_compile(GL_FRAGMENT_SHADER, fs.substr(0, nl + 1) + defs[i] + fs.substr(nl + 1),
                                i ? "RCAS" : "EASU");
    if (!fr) {
      v = 0;
      break;
    }
    GLuint p = glCreateProgram();
    glAttachShader(p, v);
    glAttachShader(p, fr);
    glBindAttribLocation(p, 0, "position_in");
    glLinkProgram(p);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
      char err[1024];
      glGetProgramInfoLog(p, sizeof err, nullptr, err);
      lg::error("fsr: link failed: {}", err);
      v = 0;
      break;
    }
    f.prog[i] = p;
    const char* names[7] = {"src", "in_size", "out_size", "out_origin", "rcas_scale", "color_mult", "color_add"};
    for (int k = 0; k < 7; k++)
      f.loc[i][k] = glGetUniformLocation(p, names[k]);
  }
  if (!v) {
    f.prog[0] = f.prog[1] = 0;
    return false;
  }
  lg::info("fsr: shaders built");
  return true;
}

// Final upscale. Replaces the plain draw in do_pcrtc_effects (screen_vao/vbo, depth and blend state are set up by the caller).
// Returns false when the shaders are unusable; the caller then does the normal bilinear blit.
bool OpenGLRenderer::fsr_present(const Fbo* src, int bc, int ba) {
  auto& f = m_fsr;
  if (!f.fsr_on || f.gl_failed || !src || !src->tex_id)
    return false;
  if (!f.prog[0] && !fsr_build()) {
    f.gl_failed = true;
    return false;
  }
  const bool rcas = f.sharp > 0;
  if (rcas && (f.mid_w != f.win_w || f.mid_h != f.win_h || !f.mid_fbo)) {
    if (f.mid_fbo) {
      glDeleteFramebuffers(1, &f.mid_fbo);
      glDeleteTextures(1, &f.mid_tex);
    }
    glGenFramebuffers(1, &f.mid_fbo);
    glGenTextures(1, &f.mid_tex);
    glBindTexture(GL_TEXTURE_2D, f.mid_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, f.win_w, f.win_h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindFramebuffer(GL_FRAMEBUFFER, f.mid_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, f.mid_tex, 0);
    const bool ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    f.mid_w = f.win_w;
    f.mid_h = f.win_h;
    if (!ok) {
      lg::error("fsr: intermediate target incomplete, falling back to plain blit");
      f.gl_failed = true;
      return false;
    }
  }
  // same brightness/contrast math as post_processing.frag
  const float color = (float)bc / 128.0f, alpha = (float)ba / 128.0f;
  const float add = bc < 0 ? color * alpha : color;
  const float mult[4] = {1.f, 1.f, 1.f, alpha}, id_mult[4] = {1.f, 1.f, 1.f, 1.f};

  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, *src->tex_id);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  // EASU
  if (rcas) {
    glBindFramebuffer(GL_FRAMEBUFFER, f.mid_fbo);
    glViewport(0, 0, f.win_w, f.win_h);
  } else {
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(f.win_x, f.win_y, f.win_w, f.win_h);
  }
  const GLint* L = f.loc[0];
  glUseProgram(f.prog[0]);
  glUniform1i(L[0], 0);
  glUniform2f(L[1], (float)src->width, (float)src->height);
  glUniform2f(L[2], (float)f.win_w, (float)f.win_h);
  glUniform2f(L[3], rcas ? 0.f : (float)f.win_x, rcas ? 0.f : (float)f.win_y);
  const float* m = rcas ? id_mult : mult;
  glUniform4f(L[5], m[0], m[1], m[2], m[3]);
  glUniform4f(L[6], rcas ? 0.f : add, rcas ? 0.f : add, rcas ? 0.f : add, 0.f);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  if (rcas) {  // RCAS from the intermediate into the window
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(f.win_x, f.win_y, f.win_w, f.win_h);
    glBindTexture(GL_TEXTURE_2D, f.mid_tex);
    const GLint* R = f.loc[1];
    glUseProgram(f.prog[1]);
    glUniform1i(R[0], 0);
    glUniform2f(R[3], (float)f.win_x, (float)f.win_y);
    glUniform1f(R[4], std::exp2(-(2.0f - 0.18f * (float)f.sharp)));  // sharp 10 = 0.2 stops (FSR default), 1 = 1.82 stops
    glUniform4f(R[5], mult[0], mult[1], mult[2], mult[3]);
    glUniform4f(R[6], add, add, add, 0.f);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  }
  return true;
}
// ---------------------------------------------------------------- end ps5_fsr

'''.replace("@@VERT@@", vert).replace("@@FRAG@@", frag)

c = rep(c, "void OpenGLRenderer::blit_display(ScopedProfilerNode& prof) {", helpers + "void OpenGLRenderer::blit_display(ScopedProfilerNode& prof) {")
c = rep(c, '#include "game/kernel/common/kmachine.h"\n', '#include "game/kernel/common/kmachine.h"\n#include <algorithm>\n#include <chrono>\n#include <cmath>\n#include <cstdlib>\n#include <cstring>\n')

# ------------------------------------------------------------------ render(): frame hooks
c = rep(c, "void OpenGLRenderer::render(DmaFollower dma, const RenderOptions& settings) {\n",
        "void OpenGLRenderer::render(DmaFollower dma, const RenderOptions& settings) {\n  fsr_frame_begin(settings);  // ps5_fsr\n")
c = rep(c, '  g_current_renderer = "end";\n}', '  g_current_renderer = "end";\n  fsr_frame_end();  // ps5_fsr\n}')

# ------------------------------------------------------------------ setup_frame(): scaled render target
c = rep(c, """  window_fb.multisampled = false;

  // see if the render FBO is still applicable
  if (settings.save_screenshot || window_resized || !m_fbo_state.render_fbo ||
      !m_fbo_state.render_fbo->matches(settings.game_res_w, settings.game_res_h,
                                       settings.msaa_samples)) {
""", """  window_fb.multisampled = false;

  // ps5_fsr: size of the render target for this frame (fsr_frame_begin chose the percent)
  int rw = settings.game_res_w, rh = settings.game_res_h;
  const bool fsr_scaled = m_fsr.pct < 100 && !settings.save_screenshot && settings.msaa_samples == 1;
  m_fsr.active = fsr_scaled;
  if (fsr_scaled) {
    rw = std::max(64, (int)((long long)settings.game_res_w * m_fsr.pct / 100 + 1) & ~1);
    rh = std::max(64, (int)((long long)settings.game_res_h * m_fsr.pct / 100 + 1) & ~1);
  }

  // see if the render FBO is still applicable
  bool fsr_rebind = false;
  if (m_fsr.mode == 2 && m_fsr.prewarm && !m_fsr.prewarmed && settings.msaa_samples == 1 && !settings.save_screenshot) {
    m_fsr.prewarmed = true;  // allocate every ladder step once, at the first frame
    fsr_rebind = true;
    for (int i = 1; i < m_fsr.ladder_n; i++)
      fsr_slot(m_fsr.ladder[i], std::max(64, (int)((long long)settings.game_res_w * m_fsr.ladder[i] / 100 + 1) & ~1),
               std::max(64, (int)((long long)settings.game_res_h * m_fsr.ladder[i] / 100 + 1) & ~1));
  }
  if (fsr_scaled) {
    m_fbo_state.render_fbo = fsr_slot(m_fsr.pct, rw, rh);
  } else if (settings.save_screenshot || window_resized || !m_fbo_state.resources.render_buffer.valid ||
      !m_fbo_state.resources.render_buffer.matches(settings.game_res_w, settings.game_res_h,
                                       settings.msaa_samples)) {
""")
# the else branch for "still applicable": the closing brace of the original block is followed by the ASSERT_MSG
c = rep(c, """      lg::info("FBO Setup: not using second temporary buffer");
    }
  }
""", """      lg::info("FBO Setup: not using second temporary buffer");
    }
  } else {
    m_fbo_state.render_fbo = &m_fbo_state.resources.render_buffer;  // ps5_fsr: may have pointed at a pooled target
  }
  if (fsr_scaled || fsr_rebind)  // make_fbo leaves the last created FBO bound
    glBindFramebuffer(GL_FRAMEBUFFER, m_fbo_state.render_fbo->fbo_id);
""")
c = rep(c, """  m_render_state.render_fb_x = 0;
  m_render_state.render_fb_y = 0;
  m_render_state.render_fb_w = settings.game_res_w;
  m_render_state.render_fb_h = settings.game_res_h;
  glViewport(0, 0, settings.game_res_w, settings.game_res_h);
""", """  // ps5_fsr: the final pass needs the draw region in window pixels; everything inside the render FBO (DepthCue reads it
  // with draw_offset/draw_region) uses render target pixels.
  m_fsr.win_x = m_render_state.draw_offset_x;
  m_fsr.win_y = m_render_state.draw_offset_y;
  m_fsr.win_w = m_render_state.draw_region_w;
  m_fsr.win_h = m_render_state.draw_region_h;
  if (fsr_scaled) {
    const float sx = (float)rw / (float)settings.game_res_w, sy = (float)rh / (float)settings.game_res_h;
    m_render_state.draw_region_w = std::max(1, (int)std::lround(m_render_state.draw_region_w * sx));
    m_render_state.draw_region_h = std::max(1, (int)std::lround(m_render_state.draw_region_h * sy));
    m_render_state.draw_offset_x = (int)std::lround(m_render_state.draw_offset_x * sx);
    m_render_state.draw_offset_y = (int)std::lround(m_render_state.draw_offset_y * sy);
  }

  m_render_state.render_fb_x = 0;
  m_render_state.render_fb_y = 0;
  m_render_state.render_fb_w = rw;
  m_render_state.render_fb_h = rh;
  glViewport(0, 0, rw, rh);
""")

# ------------------------------------------------------------------ do_pcrtc_effects(): final pass
c = rep(c, "    window_blit_src = &m_fbo_state.resources.render_buffer;\n  }\n",
        "    window_blit_src = m_fbo_state.render_fbo;  // ps5_fsr: render_buffer or a pooled smaller target\n  }\n")
c = rep(c, """  glViewport(render_state->draw_offset_x, render_state->draw_offset_y, render_state->draw_region_w,
             render_state->draw_region_h);
  glBindTexture(GL_TEXTURE_2D, *window_blit_src->tex_id);""", """  glViewport(m_fsr.win_x, m_fsr.win_y, m_fsr.win_w, m_fsr.win_h);  // ps5_fsr: window pixels
  glBindTexture(GL_TEXTURE_2D, *window_blit_src->tex_id);""")
c = rep(c, "  glActiveTexture(GL_TEXTURE0);\n  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);\n\n  glBindBuffer(GL_ARRAY_BUFFER, 0);",
        "  glActiveTexture(GL_TEXTURE0);\n  if (!(m_fsr.active && fsr_present(window_blit_src, brightness_contrast_color, brightness_contrast_alpha)))\n    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);\n\n  glBindBuffer(GL_ARRAY_BUFFER, 0);")

open(HDR, "w", encoding="utf-8", newline="\n").write(h)
open(CPP, "w", encoding="utf-8", newline="\n").write(c)
print("ok")
