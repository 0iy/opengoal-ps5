// Native index-format adaptation for the PS5 GPU path.
//
// The PS5 OpenGL driver cannot draw primitive-restart strips natively; for every such draw it reads the
// index buffer back from GPU-visible memory and rewrites it on the CPU. OpenGOAL draws almost all of its
// level geometry that way (triangle strips + restart index 0xFFFFFFFF), so that conversion dominates the
// frame time.
//
// This layer sits between the engine and the driver (the SDL shim hands these wrappers out as the GL
// function pointers). It keeps a CPU copy of every index buffer, converts strips / fans to plain triangle
// lists incrementally (each source index once), uploads the result into a driver-friendly buffer, and issues
// ordinary GL_TRIANGLES draws. Provoking-vertex order is preserved (the last vertex of every strip/fan
// triangle stays last), so flat-shaded geometry renders identically.

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <atomic>
#include <cstdio>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unordered_map>
#include <vector>

void ps5_log(const char* fmt, ...);
extern "C" const void* ps5_gl_lookup(const char* name);

namespace {

using GLenum = unsigned;
using GLuint = unsigned;
using GLint = int;
using GLsizei = int;
using GLintptr = ptrdiff_t;
using GLsizeiptr = ptrdiff_t;

constexpr GLenum kTriangles = 0x0004, kTriangleStrip = 0x0005, kTriangleFan = 0x0006;
constexpr GLenum kArrayBuffer = 0x8892, kElementArrayBuffer = 0x8893, kPrimitiveRestart = 0x8F9D, kUnsignedInt = 0x1405;
constexpr GLenum kStaticDraw = 0x88E4, kDynamicDraw = 0x88E8;
constexpr uint32_t kRestart = 0xFFFFFFFFu;

struct Real {
  void (*Enable)(GLenum) = nullptr;
  void (*Disable)(GLenum) = nullptr;
  void (*PrimitiveRestartIndex)(GLuint) = nullptr;
  void (*BindBuffer)(GLenum, GLuint) = nullptr;
  void (*BufferData)(GLenum, GLsizeiptr, const void*, GLenum) = nullptr;
  void (*BufferSubData)(GLenum, GLintptr, GLsizeiptr, const void*) = nullptr;
  void (*DeleteBuffers)(GLsizei, const GLuint*) = nullptr;
  void (*GenBuffers)(GLsizei, GLuint*) = nullptr;
  void (*BindVertexArray)(GLuint) = nullptr;
  void (*DeleteVertexArrays)(GLsizei, const GLuint*) = nullptr;
  void (*DrawElements)(GLenum, GLsizei, GLenum, const void*) = nullptr;
void (*DrawRangeElements)(GLenum, GLuint, GLuint, GLsizei, GLenum, const void*) = nullptr;
  void (*MultiDrawElements)(GLenum, const GLsizei*, GLenum, const void* const*, GLsizei) = nullptr;
  void (*DrawElementsBaseVertex)(GLenum, GLsizei, GLenum, const void*, GLint) = nullptr;
  void (*VertexAttribIPointer)(GLuint, GLint, GLenum, GLsizei, const void*) = nullptr;
  void (*DrawArrays)(GLenum, GLint, GLsizei) = nullptr;
  void (*BindFramebuffer)(GLenum, GLuint) = nullptr;
  void (*VertexAttribPointer)(GLuint, GLint, GLenum, unsigned char, GLsizei, const void*) = nullptr;
  bool ready = false;
} R;

void load_real() {
  if (R.ready) return;
#define LOAD(name) R.name = reinterpret_cast<decltype(R.name)>(const_cast<void*>(ps5_gl_lookup("gl" #name)))
  LOAD(Enable);
  LOAD(Disable);
  LOAD(PrimitiveRestartIndex);
  LOAD(BindBuffer);
  LOAD(BufferData);
  LOAD(BufferSubData);
  LOAD(DeleteBuffers);
  LOAD(GenBuffers);
  LOAD(BindVertexArray);
  LOAD(DeleteVertexArrays);
  LOAD(DrawElements);
LOAD(DrawRangeElements);
  LOAD(MultiDrawElements);
  LOAD(DrawElementsBaseVertex);
  LOAD(VertexAttribPointer);
  LOAD(BindFramebuffer);
  LOAD(DrawArrays);
  LOAD(VertexAttribIPointer);
#undef LOAD
  R.ready = true;
}

// CPU copy of one element-array buffer's contents.
struct Shadow {
  std::vector<uint32_t> data;  // indices (the engine only uses 32-bit indices)
};

// Incrementally converted triangle list for one (buffer, primitive mode).
uint64_t g_mm_gen = 1;  // bumped whenever a converted buffer is rebuilt (invalidates cached index bounds)
struct Converted {
  std::vector<uint32_t> out;  // triangle list
  std::vector<uint32_t> map;  // map[i] = out.size() before source index i was processed (i <= done)
  size_t done = 0;            // source indices processed
  uint32_t strip_pos = 0;     // position inside the current strip / fan
  uint32_t v0 = 0, a = 0, b = 0;  // fan hub, last two strip vertices
  GLuint gl_buffer = 0;
  size_t gl_capacity = 0;  // out indices the GL buffer can hold
  size_t uploaded = 0;     // out indices already uploaded
  void reset() {
    ++g_mm_gen;
    out.clear();
    map.clear();
    done = 0;
    strip_pos = 0;
    uploaded = 0;
  }
};

// Draw ranges that do not start right after a restart index: each is converted on its own (a draw always
// starts a new primitive) and cached until the element buffer changes.
struct RangeCache {
  Converted c;  // `out` is the concatenation of all converted ranges
  std::unordered_map<uint64_t, std::pair<uint32_t, uint32_t>> ranges;  // (first,count) -> (offset,length) in c.out
};

// Debug bisect: draw calls after `g_draw_limit` (when non-zero) are skipped in selected frames.
uint32_t g_draw_count = 0, g_draw_total = 0, g_draw_limit = 0, g_frame_no = 0;
unsigned g_skip = 0, g_skip_hi = 0;  // g_skip..g_skip_hi: skipped draw range (debug)
int g_dyn_limit = 0;       // set at runtime through the debug channel ("limit N"), 0 = off
bool g_dyn_note = false;
bool over_limit() {
  ++g_draw_count;
  if (g_draw_limit && g_draw_count == g_draw_limit && g_dyn_limit) g_dyn_note = true;
  if (g_skip && g_draw_count >= g_skip && g_draw_count <= (g_skip_hi ? g_skip_hi : g_skip)) { if (g_draw_count == g_skip) g_dyn_note = true; return true; }
  return g_draw_limit && g_draw_count > g_draw_limit;
}
// Describe the GL state of the last allowed draw (only while a dynamic limit is active).
struct TraceRec { char kind[10]; GLenum mode; GLint prog, tex0, tex1, fbo; long in_idx, out_idx, subs; };
long g_note_in = 0, g_note_out = 0, g_note_subs = 0;  // index counts of the draw being traced (debug)
bool g_tracing = false, g_trace_req = false;
std::vector<TraceRec> g_trace;
void note_last_draw(const char* kind, GLenum mode, GLsizei count) {
  if (g_tracing) {
    using GetFn = void (*)(GLenum, GLint*);
    using ActFn = void (*)(GLenum);
    auto get = reinterpret_cast<GetFn>(const_cast<void*>(ps5_gl_lookup("glGetIntegerv")));
    auto act = reinterpret_cast<ActFn>(const_cast<void*>(ps5_gl_lookup("glActiveTexture")));
    TraceRec r{};
    r.in_idx = g_note_in; r.out_idx = g_note_out; r.subs = g_note_subs;
    std::strncpy(r.kind, kind, 9);
    r.mode = mode;
    if (get && act) {
      get(0x8B8D, &r.prog);
      get(0x8CA6, &r.fbo);
      GLint unit = 0x84C0;
      get(0x84E0, &unit);
      act(0x84C0); get(0x8069, &r.tex0);
      act(0x84C1); get(0x8069, &r.tex1);
      act(GLenum(unit));
    }
    g_trace.push_back(r);
  }
  if (!g_dyn_note) return;
  g_dyn_note = false;
  using GetFn = void (*)(GLenum, GLint*);
  auto get = reinterpret_cast<GetFn>(const_cast<void*>(ps5_gl_lookup("glGetIntegerv")));
  GLint prog = -1, tex = -1, fbo = -1, unit = -1, vp[4] = {0, 0, 0, 0};
  if (get) {
    get(0x8B8D, &prog);   // CURRENT_PROGRAM
    get(0x84E0, &unit);   // ACTIVE_TEXTURE
    get(0x8069, &tex);    // TEXTURE_BINDING_2D
    get(0x8CA6, &fbo);    // DRAW_FRAMEBUFFER_BINDING
    get(0x0BA2, vp);      // VIEWPORT
  }
  {  // identify the program by its uniforms
    using LocFn = GLint (*)(GLuint, const char*);
    auto loc = reinterpret_cast<LocFn>(const_cast<void*>(ps5_gl_lookup("glGetUniformLocation")));
    if (loc && prog > 0) ps5_log("limit: prog uniforms tex_T20=%d tex_T0=%d alpha_min=%d color_mult=%d fog_color=%d perspective_matrix=%d", loc(GLuint(prog), "tex_T20"), loc(GLuint(prog), "tex_T0"), loc(GLuint(prog), "alpha_min"), loc(GLuint(prog), "color_mult"), loc(GLuint(prog), "fog_color"), loc(GLuint(prog), "perspective_matrix"));
  }
  ps5_log("limit: draw %u (%s mode=0x%x count=%d) program=%d unit=0x%x tex2d=%d fbo=%d viewport=%d,%d,%d,%d", g_draw_count, kind, mode,
          count, prog, unit, tex, fbo, vp[0], vp[1], vp[2], vp[3]);
}

struct State {
  GLuint array_bound = 0;  // buffer bound to GL_ARRAY_BUFFER (merc loader uploads indices through this target)
  bool restart_enabled = false;
  uint32_t restart_index = kRestart;
  GLuint vao = 0;
  std::unordered_map<GLuint, GLuint> ebo_of_vao;           // element buffer bound in each VAO
  std::unordered_map<GLuint, Shadow> shadows;              // element buffer id -> contents
  std::unordered_map<uint64_t, RangeCache> range_cache;   // (buffer, mode) -> separately converted ranges
  std::unordered_map<uint64_t, Converted> converted;       // (buffer, mode) -> list
  uint64_t why[8] = {0};
  uint64_t draws_converted = 0, draws_passthrough = 0, indices_converted = 0;
  uint64_t last_report_ns = 0;
} S;

uint64_t now_ns() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
}

GLuint current_ebo() {
  auto it = S.ebo_of_vao.find(S.vao);
  return it == S.ebo_of_vao.end() ? 0 : it->second;
}

uint64_t key_of(GLuint buf, GLenum mode) { return (uint64_t(buf) << 3) | (mode == kTriangleFan ? 2u : 1u); }

void invalidate(GLuint buf, size_t first_changed_index) {
  for (GLenum mode : {kTriangleStrip, kTriangleFan}) {
    auto it = S.converted.find(key_of(buf, mode));
    if (it != S.converted.end() && first_changed_index < it->second.done) it->second.reset();
    auto rc = S.range_cache.find(key_of(buf, mode));
    if (rc != S.range_cache.end()) {
      rc->second.c.reset();
      rc->second.ranges.clear();
    }
  }
}

// Convert source indices [c.done, end) of `src`.
void convert_until(Converted& c, const std::vector<uint32_t>& src, size_t end, bool fan) {
  if (c.map.size() < end + 1) c.map.resize(end + 1);
  for (size_t i = c.done; i < end; ++i) {
    c.map[i] = static_cast<uint32_t>(c.out.size());
    const uint32_t v = src[i];
    if (v == S.restart_index) {
      c.strip_pos = 0;
      continue;
    }
    if (!fan) {
      if (c.strip_pos >= 2) {
        // keep the last vertex last: triangle (a, b, v) for even positions, (b, a, v) for odd
        if (c.strip_pos & 1) {
          c.out.push_back(c.b);
          c.out.push_back(c.a);
        } else {
          c.out.push_back(c.a);
          c.out.push_back(c.b);
        }
        c.out.push_back(v);
      }
      c.a = c.b;
      c.b = v;
    } else {
      if (c.strip_pos == 0) {
        c.v0 = v;
      } else if (c.strip_pos >= 2) {
        c.out.push_back(c.v0);
        c.out.push_back(c.b);
        c.out.push_back(v);
      }
      c.b = v;
    }
    ++c.strip_pos;
  }
  c.map[end] = static_cast<uint32_t>(c.out.size());
  S.indices_converted += end - c.done;
  c.done = end;
}

int g_hw_restart = -1;  // restart state actually set in the driver (lazy: only touched when a draw needs a different one)
void hw_restart(bool on) {
  if (g_hw_restart == int(on)) return;
  g_hw_restart = on;
  if (on) R.Enable(kPrimitiveRestart); else R.Disable(kPrimitiveRestart);
}

GLuint g_hw_ebo = 0;
bool g_ebo_dirty = false;  // true while a converted buffer (not the VAO's own EBO) is bound
void bind_hw_ebo(GLuint buf) {
  if (g_ebo_dirty && g_hw_ebo == buf) return;
  R.BindBuffer(kElementArrayBuffer, buf);
  g_hw_ebo = buf;
  g_ebo_dirty = true;
}
void restore_ebo() {
  if (!g_ebo_dirty) return;
  R.BindBuffer(kElementArrayBuffer, current_ebo());
  g_ebo_dirty = false;
}

void upload(Converted& c) {
  if (c.uploaded >= c.out.size()) return;
  if (!c.gl_buffer) R.GenBuffers(1, &c.gl_buffer);
  bind_hw_ebo(c.gl_buffer);
  if (c.out.size() > c.gl_capacity) {
    c.gl_capacity = c.out.size() * 2 + 1024;
    R.BufferData(kElementArrayBuffer, GLsizeiptr(c.gl_capacity * 4), nullptr, kDynamicDraw);
    c.uploaded = 0;  // fresh storage: send everything
  }
  R.BufferSubData(kElementArrayBuffer, GLintptr(c.uploaded * 4), GLsizeiptr((c.out.size() - c.uploaded) * 4),
                  c.out.data() + c.uploaded);
  c.uploaded = c.out.size();
}

// Resolve a source draw range to a range of the converted list; false -> use the driver's own path.
bool glfix_disabled() {
  static int v = -1;
  if (v < 0) {
    struct stat st;
    v = stat("/data/opengoal/config/noglfix.txt", &st) == 0;
  }
  return v == 1;
}

const std::vector<uint32_t>* g_res_out = nullptr;  // converted index list of the range resolve() just returned
bool resolve(GLenum mode, GLsizei count, const void* offset_ptr, GLuint* out_buf, GLsizei* out_first, GLsizei* out_count) {
  if (glfix_disabled() || !S.restart_enabled || S.restart_index != kRestart) return false;
  if (mode != kTriangleStrip && mode != kTriangleFan) return false;
  const GLuint ebo = current_ebo();
  if (!ebo) return ++S.why[0], false;
  auto sh = S.shadows.find(ebo);
  if (sh == S.shadows.end()) return ++S.why[1], false;
  const size_t byte_offset = reinterpret_cast<uintptr_t>(offset_ptr);
  if (byte_offset & 3) return ++S.why[2], false;
  const size_t first = byte_offset / 4;
  if (count < 0 || first + size_t(count) > sh->second.data.size()) return ++S.why[3], false;
  // the range must start a strip, otherwise the mapped triangles would include earlier vertices
  if (first > 0 && sh->second.data[first - 1] != S.restart_index) {
    ++S.why[4];
    RangeCache& rc = S.range_cache[key_of(ebo, mode)];
    const uint64_t rk = (uint64_t(first) << 32) | uint32_t(count);
    auto it = rc.ranges.find(rk);
    if (it == rc.ranges.end()) {
      const uint32_t off = static_cast<uint32_t>(rc.c.out.size());
      Converted tmp;
      std::vector<uint32_t> slice(sh->second.data.begin() + first, sh->second.data.begin() + first + count);
      convert_until(tmp, slice, slice.size(), mode == kTriangleFan);
      rc.c.out.insert(rc.c.out.end(), tmp.out.begin(), tmp.out.end());
      it = rc.ranges.emplace(rk, std::make_pair(off, static_cast<uint32_t>(tmp.out.size()))).first;
    }
    upload(rc.c);
    *out_buf = rc.c.gl_buffer;
    *out_first = static_cast<GLsizei>(it->second.first);
    *out_count = static_cast<GLsizei>(it->second.second);
    g_res_out = &rc.c.out;
    return true;
  }
  Converted& c = S.converted[key_of(ebo, mode)];
  if (first + size_t(count) > c.done || c.map.empty()) convert_until(c, sh->second.data, first + size_t(count), mode == kTriangleFan);
  upload(c);
  *out_buf = c.gl_buffer;
  *out_first = static_cast<GLsizei>(c.map[first]);
  *out_count = static_cast<GLsizei>(c.map[first + size_t(count)] - c.map[first]);
  g_res_out = &c.out;
  return true;
}

inline uint64_t tsc() {
  uint32_t lo, hi;
  __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
  return (uint64_t(hi) << 32) | lo;
}
uint64_t g_bd_calls = 0, g_bd_bytes = 0, g_bsd_calls = 0, g_bsd_bytes = 0;
uint64_t g_bd_cycles = 0;
std::unordered_map<uint64_t, uint64_t> g_hist;
bool g_diag = false;  // diag.txt: per-draw diagnostics (histogram, slow-draw timeline); off in normal runs, they cost about 1 us per draw
inline void hist(unsigned kind, GLenum mode, GLenum type, bool restart) {
  if (!g_diag) return;
  ++g_hist[(uint64_t(kind) << 48) | (uint64_t(mode) << 24) | (uint64_t(type & 0xffff) << 8) | (restart ? 1u : 0u)];
}
uint64_t g_md_in = 0, g_md_out = 0;
uint64_t g_draw_cycles = 0, g_draw_calls = 0, g_rep_tsc = 0, g_rep_ns = 0;
// ---- per-frame draw timeline (diagnostic) ----
extern "C" void ps5_driver_wait_sites(unsigned long long* ns, unsigned long long* n);  // driver patch 43
struct SlowEv { double at_us, dur_us, gap_us; uint32_t idx; float wait_ms[4]; };
SlowEv g_slow[12];
double g_tsc_per_us = 0;
uint64_t g_cal_tsc = 0, g_cal_ns = 0, g_frame_tsc0 = 0, g_last_end_tsc = 0;
uint32_t g_ev_idx = 0;
void note_event(uint64_t t0, uint64_t t1, const unsigned long long* w0) {
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
  if (big > mnv) {
    unsigned long long w1[4], n1[4];
    ps5_driver_wait_sites(w1, n1);
    g_slow[mn] = {double(t0 - g_frame_tsc0) / g_tsc_per_us, dur, gap, g_ev_idx, {float((w1[0] - w0[0]) / 1e6), float((w1[1] - w0[1]) / 1e6), float((w1[2] - w0[2]) / 1e6), float((w1[3] - w0[3]) / 1e6)}};
  }
  ++g_ev_idx;
}
// TRACE_CORE: event tracer (diagnostic)
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
// TRACE_REAL: time of the real GL draw call
template <class F, class... A>
inline void rt_real(F f, A... a) {
  const uint64_t t = tsc();
  f(a...);
  trace_emit(11, t, tsc() - t, 0);
}
struct DrawTimer {
  unsigned long long w0[4], n0[4];
  uint64_t t0;
  bool on;
  DrawTimer() : on(g_diag || g_tr_on.load(std::memory_order_relaxed)) { if (on) { ps5_driver_wait_sites(w0, n0); t0 = tsc(); } }
  ~DrawTimer() { if (!on) return; const uint64_t t1 = tsc(); g_draw_cycles += t1 - t0; ++g_draw_calls; note_event(t0, t1, w0); trace_emit(10, t0, t1 - t0, g_ev_idx); }
};

void report() {
  const uint64_t t = now_ns();
  if (t - S.last_report_ns < 10000000000ull) return;
  S.last_report_ns = t;
  ps5_log("glfix: strip draws not converted: no-ebo=%llu no-shadow=%llu misaligned=%llu out-of-range=%llu mid-strip=%llu",
          (unsigned long long)S.why[0], (unsigned long long)S.why[1], (unsigned long long)S.why[2],
          (unsigned long long)S.why[3], (unsigned long long)S.why[4]);
  {
    const uint64_t nt = tsc(), nn = now_ns();
    if (g_rep_tsc) {
      const double ghz = double(nt - g_rep_tsc) / double(nn - g_rep_ns);
      ps5_log("glfix: BufferData inside %.1f ms/s", g_bd_cycles / ghz / 1e6 / (double(nn - g_rep_ns) / 1e9));
      ps5_log("glfix: BufferData %llu calls %llu KB, BufferSubData %llu calls %llu KB", (unsigned long long)g_bd_calls, (unsigned long long)(g_bd_bytes >> 10), (unsigned long long)g_bsd_calls, (unsigned long long)(g_bsd_bytes >> 10));
      for (auto& kv : g_hist)
        ps5_log("glfix: hist kind=%llu mode=0x%llx type=0x%llx restart=%llu n=%llu", (unsigned long long)(kv.first >> 48),
                (unsigned long long)((kv.first >> 24) & 0xffffff), (unsigned long long)((kv.first >> 8) & 0xffff),
                (unsigned long long)(kv.first & 1), (unsigned long long)kv.second);
      g_hist.clear();
      ps5_log("glfix: multidraw ranges in=%llu out=%llu", (unsigned long long)g_md_in, (unsigned long long)g_md_out);
      g_md_in = g_md_out = 0;
      ps5_log("glfix: draw calls=%llu, %.1f ms/s inside draw calls (%.2f us each)", (unsigned long long)g_draw_calls,
              g_draw_cycles / ghz / 1e6 / (double(nn - g_rep_ns) / 1e9), g_draw_cycles / ghz / 1e3 / double(g_draw_calls ? g_draw_calls : 1));
    }
    g_rep_tsc = nt; g_rep_ns = nn; g_bd_cycles = 0; g_bd_calls = g_bd_bytes = g_bsd_calls = g_bsd_bytes = 0; g_draw_cycles = 0; g_draw_calls = 0;
  }
  ps5_log("glfix: draws converted=%llu passthrough=%llu, indices converted=%llu, buffers=%zu",
          (unsigned long long)S.draws_converted, (unsigned long long)S.draws_passthrough,
          (unsigned long long)S.indices_converted, S.converted.size());
}

// ---- wrappers ------------------------------------------------------------------------------------------
void w_Enable(GLenum cap) {
  load_real();
  if (cap == kPrimitiveRestart) { S.restart_enabled = true; return; }
  R.Enable(cap);
}
void w_Disable(GLenum cap) {
  load_real();
  if (cap == kPrimitiveRestart) { S.restart_enabled = false; return; }
  R.Disable(cap);
}
void w_PrimitiveRestartIndex(GLuint index) {
  load_real();
  S.restart_index = index;
  R.PrimitiveRestartIndex(index);
}
void w_BindVertexArray(GLuint vao) {
  load_real();
  restore_ebo();
  S.vao = vao;
  R.BindVertexArray(vao);
}
void w_DeleteVertexArrays(GLsizei n, const GLuint* vaos) {
  load_real();
  for (GLsizei i = 0; i < n; ++i) S.ebo_of_vao.erase(vaos[i]);
  R.DeleteVertexArrays(n, vaos);
}
void w_BindBuffer(GLenum target, GLuint buf) {
  load_real();
  if (target == kArrayBuffer) S.array_bound = buf;
  if (target == kElementArrayBuffer) restore_ebo();
  if (target == kElementArrayBuffer) {
    S.ebo_of_vao[S.vao] = buf;
    if (buf && S.shadows.find(buf) == S.shadows.end()) S.shadows.emplace(buf, Shadow{});
  }
  R.BindBuffer(target, buf);
}
void w_BufferData(GLenum target, GLsizeiptr size, const void* data, GLenum usage) {
  load_real();
  ++g_bd_calls; g_bd_bytes += size_t(size);
  struct T { uint64_t t0 = tsc(); ~T() { g_bd_cycles += tsc() - t0; } } bd_timer;
  if (target == kElementArrayBuffer) restore_ebo();
  if (target == kElementArrayBuffer) {
    const GLuint ebo = current_ebo();
    if (ebo) {
      Shadow& sh = S.shadows[ebo];
      sh.data.assign(size_t(size) / 4, 0u);
      if (data) std::memcpy(sh.data.data(), data, size_t(size) / 4 * 4);
      invalidate(ebo, 0);
    }
  }
  R.BufferData(target, size, data, usage);
}
void w_BufferSubData(GLenum target, GLintptr offset, GLsizeiptr size, const void* data) {
  load_real();
  ++g_bsd_calls; g_bsd_bytes += size_t(size);
  if (target == kArrayBuffer && S.array_bound && S.shadows.count(S.array_bound)) {  // index data uploaded via ARRAY target
    Shadow& sh = S.shadows[S.array_bound];
    if (data && offset >= 0 && (offset & 3) == 0 && size_t(offset) + size_t(size) <= sh.data.size() * 4) std::memcpy(sh.data.data() + offset / 4, data, size_t(size) / 4 * 4);
    invalidate(S.array_bound, size_t(offset) / 4);
  }
  if (target == kElementArrayBuffer) restore_ebo();
  if (target == kElementArrayBuffer) {
    const GLuint ebo = current_ebo();
    if (ebo) {
      Shadow& sh = S.shadows[ebo];
      const size_t end = size_t(offset + size) / 4;
      if (sh.data.size() < end) sh.data.resize(end, 0u);
      std::memcpy(reinterpret_cast<uint8_t*>(sh.data.data()) + offset, data, size_t(size));
      invalidate(ebo, size_t(offset) / 4);
    }
  }
  R.BufferSubData(target, offset, size, data);
}
void w_DeleteBuffers(GLsizei n, const GLuint* bufs) {
  load_real();
  restore_ebo();
  for (GLsizei i = 0; i < n; ++i) {
    S.shadows.erase(bufs[i]);
    for (GLenum mode : {kTriangleStrip, kTriangleFan}) {
      auto rc = S.range_cache.find(key_of(bufs[i], mode));
      if (rc != S.range_cache.end()) {
        if (rc->second.c.gl_buffer) R.DeleteBuffers(1, &rc->second.c.gl_buffer);
        S.range_cache.erase(rc);
      }
      auto it = S.converted.find(key_of(bufs[i], mode));
      if (it != S.converted.end()) {
        if (it->second.gl_buffer) R.DeleteBuffers(1, &it->second.gl_buffer);
        S.converted.erase(it);
      }
    }
  }
  R.DeleteBuffers(n, bufs);
}

// MERGE_DRAWS: gather the sub-draws of a multi-draw call into one draw (PS5_MERGE_DRAWS=1), statistics (PS5_MERGE_STATS=1)
struct MergeStats {
  uint64_t t0_ns = 0, frame0 = 0;
  uint64_t multi = 0, single = 0, other = 0;        // draw calls seen (converted multi, converted single, anything else)
  uint64_t subs = 0, nonempty = 0;                  // sub-draws in, calls with at least one non-empty range
  uint64_t sub_hist[8] = {0};                       // sub-draws per multi call: 1, 2, 3-4, 5-8, 9-16, 17-32, 33-64, 65+
  uint64_t pairs = 0, src_contig = 0;               // neighbouring sub-draw pairs; contiguous in the source index buffer
  uint64_t gap_hist[6] = {0};                       // gap in converted indices: <0, 0, 1-12, 13-48, 49-192, >192
  uint64_t idx_drawn = 0, idx_gap192 = 0;           // converted indices drawn; indices lying in gaps of 1..192 (cost of bridging)
  uint64_t cc_pairs = 0, cc_prog = 0, cc_state = 0, cc_contig = 0;  // consecutive draw calls: any, same program, same GL state, same state and contiguous
  uint64_t gathered = 0, gathered_idx = 0, gather_fail = 0;
  int sig[8] = {0};
  bool have_sig = false;
  GLuint last_buf = 0;
  long last_end = -1;
};
struct MergeState {
  bool gather = false, stats = false;
  GLuint ebo = 0;
  size_t cap = 0, off = 0;   // gather buffer capacity / fill, in indices
  bool orphan = true;        // start of a frame: respecify the storage before the first write
  std::vector<uint32_t> stage;
  MergeStats ms;
};
MergeState* make_merge_state() {
  const char* d = std::getenv("PS5_MERGE_DRAWS");
  const char* t = std::getenv("PS5_MERGE_STATS");
  const bool g = d && *d && *d != '0', st = t && *t && *t != '0';
  if (!g && !st) return nullptr;
  MergeState* m = new MergeState();
  m->gather = g;
  m->stats = st;
  ps5_log("glfix: merge draws: gather=%d stats=%d", int(g), int(st));
  return m;
}
inline MergeState* mg() {
  static MergeState* p = make_merge_state();
  return p;
}

void ms_sig(int* sig) {
  using GetFn = void (*)(GLenum, GLint*);
  static const GLenum kQ[8] = {0x8B8D /*program*/, 0x8069 /*tex2d*/, 0x8CA6 /*draw fbo*/, 0x85B5 /*vao*/,
                               0x0BE2 /*blend*/, 0x0B72 /*depth mask*/, 0x0B74 /*depth func*/, 0x80C9 /*blend src rgb*/};
  auto get = reinterpret_cast<GetFn>(const_cast<void*>(ps5_gl_lookup("glGetIntegerv")));
  for (int i = 0; i < 8; ++i) { sig[i] = 0; if (get) get(kQ[i], &sig[i]); }
}
// One draw call finished its decision: chain statistics against the previous call. buf == 0: a call that can never be contiguous.
void ms_chain(MergeStats& s, GLuint buf, long first, long end) {
  int sig[8];
  ms_sig(sig);
  if (s.have_sig) {
    ++s.cc_pairs;
    if (sig[0] == s.sig[0]) ++s.cc_prog;
    if (std::memcmp(sig, s.sig, sizeof sig) == 0) {
      ++s.cc_state;
      if (buf && buf == s.last_buf && first == s.last_end) ++s.cc_contig;
    }
  }
  std::memcpy(s.sig, sig, sizeof sig);
  s.have_sig = true;
  s.last_buf = buf;
  s.last_end = end;
}
void ms_report(MergeStats& s) {
  const uint64_t t = now_ns();
  if (!s.t0_ns) { s.t0_ns = t; s.frame0 = g_frame_no; return; }
  if (t - s.t0_ns < 3000000000ull) return;
  const double fr = double(g_frame_no - s.frame0 ? g_frame_no - s.frame0 : 1);
  ps5_log("merge: %.1fs %.0f frames; per frame: multi=%.0f single=%.0f other=%.0f subs=%.0f nonempty-calls=%.0f", double(t - s.t0_ns) / 1e9, fr,
          s.multi / fr, s.single / fr, s.other / fr, s.subs / fr, s.nonempty / fr);
  ps5_log("merge: subs/call 1:%llu 2:%llu 3-4:%llu 5-8:%llu 9-16:%llu 17-32:%llu 33-64:%llu 65+:%llu", (unsigned long long)s.sub_hist[0],
          (unsigned long long)s.sub_hist[1], (unsigned long long)s.sub_hist[2], (unsigned long long)s.sub_hist[3], (unsigned long long)s.sub_hist[4],
          (unsigned long long)s.sub_hist[5], (unsigned long long)s.sub_hist[6], (unsigned long long)s.sub_hist[7]);
  ps5_log("merge: neighbour sub-draws=%llu src-contiguous=%llu; gap(conv idx) <0:%llu 0:%llu 1-12:%llu 13-48:%llu 49-192:%llu >192:%llu",
          (unsigned long long)s.pairs, (unsigned long long)s.src_contig, (unsigned long long)s.gap_hist[0], (unsigned long long)s.gap_hist[1],
          (unsigned long long)s.gap_hist[2], (unsigned long long)s.gap_hist[3], (unsigned long long)s.gap_hist[4], (unsigned long long)s.gap_hist[5]);
  ps5_log("merge: indices drawn=%llu, lying in 1..192 gaps=%llu; consecutive calls=%llu same-program=%llu same-state=%llu same-state+contiguous=%llu",
          (unsigned long long)s.idx_drawn, (unsigned long long)s.idx_gap192, (unsigned long long)s.cc_pairs, (unsigned long long)s.cc_prog,
          (unsigned long long)s.cc_state, (unsigned long long)s.cc_contig);
  ps5_log("merge: gather calls=%llu indices=%llu fallback=%llu", (unsigned long long)s.gathered, (unsigned long long)s.gathered_idx,
          (unsigned long long)s.gather_fail);
  const bool have = s.have_sig;
  int sig[8];
  std::memcpy(sig, s.sig, sizeof sig);
  const GLuint lb = s.last_buf;
  const long le = s.last_end;
  s = MergeStats();
  s.t0_ns = t;
  s.frame0 = g_frame_no;
  s.have_sig = have;
  std::memcpy(s.sig, sig, sizeof sig);
  s.last_buf = lb;
  s.last_end = le;
}
// Statistics for a converted multi-draw call, before the adjacent-range merge. src_off/src_cnt are the engine's own arrays.
void ms_multi(MergeState* m, GLuint buf, const std::vector<GLsizei>& cnt, const std::vector<const void*>& off, const GLsizei* src_cnt,
              const void* const* src_off, GLsizei drawcount) {
  MergeStats& s = m->ms;
  ++s.multi;
  s.subs += size_t(drawcount);
  if (!cnt.empty()) ++s.nonempty;
  const size_t k = size_t(drawcount);
  ++s.sub_hist[k <= 1 ? 0 : k == 2 ? 1 : k <= 4 ? 2 : k <= 8 ? 3 : k <= 16 ? 4 : k <= 32 ? 5 : k <= 64 ? 6 : 7];
  for (GLsizei d = 0; d + 1 < drawcount; ++d)
    if (reinterpret_cast<uintptr_t>(src_off[d]) + uintptr_t(src_cnt[d]) * 4 == reinterpret_cast<uintptr_t>(src_off[d + 1])) ++s.src_contig;
  long first = -1, end = -1;
  for (size_t i = 0; i < cnt.size(); ++i) {
    s.idx_drawn += size_t(cnt[i]);
    const long o = long(reinterpret_cast<uintptr_t>(off[i]) / 4);
    if (i == 0) first = o;
    end = o + cnt[i];
    if (i + 1 < cnt.size()) {
      const long gap = long(reinterpret_cast<uintptr_t>(off[i + 1]) / 4) - end;
      ++s.pairs;
      ++s.gap_hist[gap < 0 ? 0 : gap == 0 ? 1 : gap <= 12 ? 2 : gap <= 48 ? 3 : gap <= 192 ? 4 : 5];
      if (gap > 0 && gap <= 192) s.idx_gap192 += size_t(gap);
    }
  }
  ms_chain(s, cnt.empty() ? 0 : buf, first, end);
  ms_report(s);
}
void ms_single(MergeState* m, GLuint buf, long first, long n) {
  ++m->ms.single;
  ms_chain(m->ms, buf, first, first + n);
  ms_report(m->ms);
}
void ms_other(MergeState* m) {
  ++m->ms.other;
  ms_chain(m->ms, 0, 0, -1);
  ms_report(m->ms);
}

// Gather the converted ranges of one multi-draw call into one range of a private element buffer and draw it once.
// Returns true when the draw was issued. Conservative: any doubt -> false and the caller draws the ranges as before.
bool merge_gather(MergeState* m, const std::vector<GLsizei>& cnt, const std::vector<const void*>& off) {
  if (!m || !m->gather || cnt.size() < 2 || !g_res_out) return false;
  const std::vector<uint32_t>& src = *g_res_out;
  size_t total = 0;
  for (size_t i = 0; i < cnt.size(); ++i) {
    const uintptr_t o = reinterpret_cast<uintptr_t>(off[i]);
    if ((o & 3) || cnt[i] <= 0 || o / 4 + size_t(cnt[i]) > src.size()) return ++m->ms.gather_fail, false;
    total += size_t(cnt[i]);
  }
  if (total > (size_t(1) << 22) || total % 3) return ++m->ms.gather_fail, false;
  if (m->stage.size() < total) m->stage.resize(total);
  uint32_t* p = m->stage.data();
  uint32_t lo = 0xFFFFFFFFu, hi = 0;
  for (size_t i = 0; i < cnt.size(); ++i) {
    const uint32_t* q = src.data() + reinterpret_cast<uintptr_t>(off[i]) / 4;
    for (GLsizei k = 0; k < cnt[i]; ++k) { const uint32_t v = q[k]; p[k] = v; lo = v < lo ? v : lo; hi = v > hi ? v : hi; }
    p += cnt[i];
  }
  if (!m->ebo) R.GenBuffers(1, &m->ebo);
  bind_hw_ebo(m->ebo);
  R.BufferData(kElementArrayBuffer, GLsizeiptr(total * 4), m->stage.data(), kDynamicDraw);  // fresh storage per gather: no sync with queued draws
  m->off = 0;
  hw_restart(false);
  const void* first = reinterpret_cast<const void*>(uintptr_t(m->off) * 4);
  m->off += total;
  ++m->ms.gathered;
  m->ms.gathered_idx += total;
  if (R.DrawRangeElements) rt_real(R.DrawRangeElements, kTriangles, lo, hi, GLsizei(total), kUnsignedInt, first);
  else rt_real(R.DrawElements, kTriangles, GLsizei(total), kUnsignedInt, first);
  return true;
}

void w_DrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
  DrawTimer draw_timer;
  load_real();
  if (over_limit()) return;
  g_note_in = count; g_note_out = 0; g_note_subs = 1;
  note_last_draw("elements", mode, 0);
  GLuint buf = 0;
  GLsizei first = 0, n = 0;
  if (type == kUnsignedInt && resolve(mode, count, indices, &buf, &first, &n)) {
    ++S.draws_converted;
    hist(3, mode, type, S.restart_enabled);
    if (MergeState* ms_ = mg()) { if (ms_->stats) ms_single(ms_, n > 0 ? buf : 0, first, n); }
    if (n > 0) {
      bind_hw_ebo(buf);
      // converted lists hold no restart index: switching restart off keeps the driver from scanning them
      hw_restart(false);
      // The driver scans every indexed draw for its min/max index on the CPU; the converted lists are static,
      // so compute the bounds once per (buffer, range) and hand them over with DrawRangeElements.
      struct MM { uint64_t gen; uint32_t lo, hi; };
      static std::unordered_map<uint64_t, MM> mm_cache;
      const uint64_t key = (uint64_t(buf) << 40) ^ (uint64_t(uint32_t(first)) << 20) ^ uint64_t(uint32_t(n));
      auto mit = mm_cache.find(key);
      if (mit == mm_cache.end() || mit->second.gen != g_mm_gen) {
        uint32_t lo = 0xFFFFFFFFu, hi = 0;
        if (g_res_out && size_t(first) + size_t(n) <= g_res_out->size()) {
          for (GLsizei i = 0; i < n; ++i) { const uint32_t v = (*g_res_out)[size_t(first) + size_t(i)]; if (v < lo) lo = v; if (v > hi) hi = v; }
        }
        mit = mm_cache.insert_or_assign(key, MM{g_mm_gen, lo, hi}).first;
      }
      if (mit->second.lo <= mit->second.hi && R.DrawRangeElements) rt_real(R.DrawRangeElements, kTriangles, mit->second.lo, mit->second.hi, n, kUnsignedInt, reinterpret_cast<const void*>(uintptr_t(first) * 4));
      else rt_real(R.DrawElements, kTriangles, n, kUnsignedInt, reinterpret_cast<const void*>(uintptr_t(first) * 4));
    }
  } else {
    ++S.draws_passthrough;
    hist(2, mode, type, S.restart_enabled);
    if (MergeState* ms_ = mg()) { if (ms_->stats) ms_other(ms_); }
    // plain triangle lists never use primitive restart; the driver otherwise lowers them on the CPU
    restore_ebo();
    hw_restart(S.restart_enabled && mode != kTriangles);
    rt_real(R.DrawElements, mode, count, type, indices);
  }
  report();
}

void w_MultiDrawElements(GLenum mode, const GLsizei* counts, GLenum type, const void* const* indices, GLsizei drawcount) {
  DrawTimer draw_timer;
  load_real();
  if (over_limit()) return;
  g_note_in = 0; g_note_out = 0; g_note_subs = drawcount;
  for (GLsizei d = 0; d < drawcount; ++d) g_note_in += counts[d];
  note_last_draw("multi", mode, 0);
  static std::vector<GLsizei> out_counts;
  static std::vector<const void*> out_offsets;
  out_counts.clear();
  out_offsets.clear();
  GLuint buf = 0;
  bool ok = type == kUnsignedInt;
  for (GLsizei d = 0; ok && d < drawcount; ++d) {
    GLuint b = 0;
    GLsizei first = 0, n = 0;
    if (!resolve(mode, counts[d], indices[d], &b, &first, &n) || (buf && b != buf)) {
      ok = false;
      break;
    }
    buf = b;
    if (n > 0) {
      out_counts.push_back(n);
      out_offsets.push_back(reinterpret_cast<const void*>(uintptr_t(first) * 4));
    }
  }
  if (ok) {
    S.draws_converted += drawcount;
    g_md_in += out_counts.size();
    MergeState* mst_ = mg();
    if (mst_ && mst_->stats) ms_multi(mst_, buf, out_counts, out_offsets, counts, indices, drawcount);
    // adjacent ranges of the converted list draw as one (every range becomes its own driver draw otherwise)
    size_t w = 0;
    for (size_t r = 1; r < out_counts.size(); ++r) {
      const uintptr_t end = reinterpret_cast<uintptr_t>(out_offsets[w]) + uintptr_t(out_counts[w]) * 4;
      if (end == reinterpret_cast<uintptr_t>(out_offsets[r])) {
        out_counts[w] += out_counts[r];
      } else {
        ++w;
        out_counts[w] = out_counts[r];
        out_offsets[w] = out_offsets[r];
      }
    }
    if (!out_counts.empty()) {
      out_counts.resize(w + 1);
      out_offsets.resize(w + 1);
    }
    g_md_out += out_counts.size();
    if (g_tracing && !g_trace.empty()) { long t = 0; for (auto c : out_counts) t += c; g_trace.back().out_idx = t; g_trace.back().subs = long(out_counts.size()); }
    if (merge_gather(mst_, out_counts, out_offsets)) {
      // one driver draw issued
    } else if (!out_counts.empty()) {
      bind_hw_ebo(buf);
      hw_restart(false);
      rt_real(R.MultiDrawElements, kTriangles, out_counts.data(), kUnsignedInt, out_offsets.data(),
                          static_cast<GLsizei>(out_counts.size()));
    }
  } else {
    S.draws_passthrough += drawcount;
    restore_ebo();  // an earlier range may have bound a converted buffer
    hw_restart(S.restart_enabled && mode != kTriangles);
    rt_real(R.MultiDrawElements, mode, counts, type, indices, drawcount);
  }
  report();
}

// Remembers the first off-screen framebuffer bound after each swap: that is the game's main render target
// (used by the optional frame capture).
GLuint g_frame_fbo = 0, g_main_fbo = 0;
GLuint g_bound_draw_fbo = 0;
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
}

// Log each distinct vertex attribute layout once (which of them the driver can take natively).
void w_VertexAttribPointer(GLuint index, GLint size, GLenum type, unsigned char normalized, GLsizei stride, const void* ptr) {
  load_real();
  static uint64_t seen[64];
  static int nseen = 0;
  const uint64_t key = (uint64_t(size) << 40) | (uint64_t(type) << 8) | normalized;
  bool known = false;
  for (int i = 0; i < nseen; ++i) known |= seen[i] == key;
  if (!known && nseen < 64) {
    seen[nseen++] = key;
    ps5_log("glfix: attrib size=%d type=0x%x normalized=%d", size, type, normalized);
  }
  // 3 x normalized ubyte is not a native fetch format on the PS5 driver (CPU translation per draw); fetch 4 bytes and
  // let the vec3 input drop the fourth (shrub vertex colours).
  if (type == 0x1401 && size == 3 && normalized) size = 4;
  R.VertexAttribPointer(index, size, type, normalized, stride, ptr);
}

struct ArrIB {
  GLuint buf = 0;
  size_t tris = 0;
};
ArrIB g_strip_ib, g_fan_ib;
void ensure_arr_ib(ArrIB& ib, size_t tris, bool fan) {
  if (ib.buf && tris <= ib.tris) return;
  const size_t cap = tris < 4096 ? 4096 : tris * 2;
  std::vector<uint32_t> idx(cap * 3);
  for (size_t i = 0; i < cap; ++i) {
    uint32_t a, b, c;
    if (fan) {
      a = 0; b = uint32_t(i + 1); c = uint32_t(i + 2);
    } else {
      a = uint32_t(i); b = uint32_t(i + 1); c = uint32_t(i + 2);
      if (i & 1) std::swap(a, b);
    }
    idx[i * 3] = a; idx[i * 3 + 1] = b; idx[i * 3 + 2] = c;
  }
  if (!ib.buf) R.GenBuffers(1, &ib.buf);
  bind_hw_ebo(ib.buf);
  R.BufferData(kElementArrayBuffer, GLsizeiptr(idx.size() * 4), idx.data(), kStaticDraw);
  ib.tris = cap;
}

void w_DrawArrays(GLenum mode, GLint first, GLsizei count) {
  DrawTimer draw_timer;
  load_real();
  if (over_limit()) return;
  note_last_draw("arrays", mode, 0);
  hist(1, mode, 0, S.restart_enabled);
  if (MergeState* ms_ = mg()) { if (ms_->stats) ms_other(ms_); }
  if ((mode == kTriangleStrip || mode == kTriangleFan) && count >= 3 && !glfix_disabled()) {
    // The driver batches only plain triangle lists; strips/fans take its slow immediate path. Draw them as an
    // indexed triangle list from a shared pattern buffer (the pattern is a prefix of itself, so one buffer serves
    // every count), with `first` as the base vertex.
    ArrIB& ib = mode == kTriangleFan ? g_fan_ib : g_strip_ib;
    ensure_arr_ib(ib, size_t(count - 2), mode == kTriangleFan);
    bind_hw_ebo(ib.buf);
    hw_restart(false);
    rt_real(R.DrawElementsBaseVertex, kTriangles, 3 * (count - 2), kUnsignedInt, nullptr, first);
    return;
  }
  rt_real(R.DrawArrays, mode, first, count);
}

// 16-bit integer attributes are not a native vertex format on the PS5 driver (it converts them on the CPU for
// every draw). They are fetched as 32-bit integers instead; the vertex shaders (patched in Shader.cpp) unpack
// the two halves. The attribute must start on a 4-byte boundary, which holds for every vertex layout the engine
// uses with these attributes.
void w_VertexAttribIPointer(GLuint index, GLint size, GLenum type, GLsizei stride, const void* ptr) {
  load_real();
  constexpr GLenum kUnsignedShort = 0x1403;
  if (type == kUnsignedShort && (size == 1 || size == 2 || size == 4)) {
    if ((reinterpret_cast<uintptr_t>(ptr) | uintptr_t(stride)) & 3) ps5_log("glfix: unaligned u16 attribute %u", index);
    R.VertexAttribIPointer(index, size == 4 ? 2 : 1, kUnsignedInt, stride, ptr);
    return;
  }
  R.VertexAttribIPointer(index, size, type, stride, ptr);
}

// Indexed triangle lists never use primitive restart; with it enabled the driver scans them on the CPU.
void w_DrawElementsBaseVertex(GLenum mode, GLsizei count, GLenum type, const void* indices, GLint base) {
  DrawTimer draw_timer;
  load_real();
  if (over_limit()) return;
  note_last_draw("basevertex", mode, 0);
  restore_ebo();
  hw_restart(S.restart_enabled && mode != kTriangles);
  rt_real(R.DrawElementsBaseVertex, mode, count, type, indices, base);
}

// GLCALL_WRAPPERS: timed pass-through wrappers (diagnostic)
struct GlCallStat { const char* name; uint64_t n, ns, max_ns; };
GlCallStat g_glcalls[14];
struct GlCallTimer {
  int slot; uint64_t t0;
  explicit GlCallTimer(int s) : slot(s), t0(now_ns()) {}
  ~GlCallTimer() { const uint64_t d = now_ns() - t0; GlCallStat& e = g_glcalls[slot]; ++e.n; e.ns += d; if (d > e.max_ns) e.max_ns = d; trace_emit(200 + slot, t0, d, 0); }
};
void w_glTexImage2D(GLenum a, GLint b, GLint c, GLsizei d, GLsizei e, GLint f, GLenum g, GLenum h, const void* i) {
  using Fn = void (*)(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glTexImage2D")));
  g_glcalls[0].name = "glTexImage2D";
  GlCallTimer timer(0);
  // glow probe depth copy: a plain GL_DEPTH_COMPONENT texture differs from the D24S8 render buffer and the driver rejects that depth blit
  // (probe sees an empty depth buffer, glows show through solid objects). Allocate it as D24S8 like the render buffer.
  if (!i && c == 0x1902 && g == 0x1902 && !std::getenv("PS5_NO_DEPTH_FMT_FIX")) { c = 0x88F0; g = 0x84F9; h = 0x84FA; }
  real(a, b, c, d, e, f, g, h, i);
}
void w_glTexSubImage2D(GLenum a, GLint b, GLint c, GLint d, GLsizei e, GLsizei f, GLenum g, GLenum h, const void* i) {
  using Fn = void (*)(GLenum, GLint, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, const void*);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glTexSubImage2D")));
  g_glcalls[1].name = "glTexSubImage2D";
  GlCallTimer timer(1);
  real(a, b, c, d, e, f, g, h, i);
}
void w_glTexImage1D(GLenum a, GLint b, GLint c, GLsizei d, GLint e, GLenum f, GLenum g, const void* h) {
  using Fn = void (*)(GLenum, GLint, GLint, GLsizei, GLint, GLenum, GLenum, const void*);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glTexImage1D")));
  g_glcalls[2].name = "glTexImage1D";
  GlCallTimer timer(2);
  real(a, b, c, d, e, f, g, h);
}
void w_glTexSubImage1D(GLenum a, GLint b, GLint c, GLsizei d, GLenum e, GLenum f, const void* g) {
  using Fn = void (*)(GLenum, GLint, GLint, GLsizei, GLenum, GLenum, const void*);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glTexSubImage1D")));
  g_glcalls[3].name = "glTexSubImage1D";
  GlCallTimer timer(3);
  real(a, b, c, d, e, f, g);
}
void w_glClear(unsigned a) {
  using Fn = void (*)(unsigned);
  if (g_bound_draw_fbo == 0 && g_frames_seen > 8 && !keep_window_clear()) { ++g_window_clears_skipped; return; }
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glClear")));
  g_glcalls[4].name = "glClear";
  GlCallTimer timer(4);
  real(a);
}
void w_glBlitFramebuffer(GLint a, GLint b, GLint c, GLint d, GLint e, GLint f, GLint g, GLint h, unsigned i, GLenum j) {
  using Fn = void (*)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, unsigned, GLenum);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glBlitFramebuffer")));
  g_glcalls[5].name = "glBlitFramebuffer";
  GlCallTimer timer(5);
  real(a, b, c, d, e, f, g, h, i, j);
  if (i & 0x100) {  // GL_DEPTH_BUFFER_BIT: log the first few depth blits (glow probe depth copy)
    static int n = 0;
    static unsigned (*get_err)() = reinterpret_cast<unsigned (*)()>(const_cast<void*>(ps5_gl_lookup("glGetError")));
    if (n++ < 6) ps5_log("glfix: depth blit src %d,%d-%d,%d dst %d,%d-%d,%d mask 0x%x filter 0x%x err 0x%x", a, b, c, d, e, f, g, h, i, unsigned(j), get_err ? get_err() : 0u);
  }
}
void w_glGenerateMipmap(GLenum a) {
  using Fn = void (*)(GLenum);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glGenerateMipmap")));
  g_glcalls[6].name = "glGenerateMipmap";
  GlCallTimer timer(6);
  real(a);
}
void w_glReadPixels(GLint a, GLint b, GLsizei c, GLsizei d, GLenum e, GLenum f, void* g) {
  using Fn = void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glReadPixels")));
  g_glcalls[7].name = "glReadPixels";
  GlCallTimer timer(7);
  real(a, b, c, d, e, f, g);
}
void w_glFinish() {
  using Fn = void (*)(void);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glFinish")));
  g_glcalls[8].name = "glFinish";
  GlCallTimer timer(8);
  real();
}
void w_glFlush() {
  using Fn = void (*)(void);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glFlush")));
  g_glcalls[9].name = "glFlush";
  GlCallTimer timer(9);
  real();
}
void w_glFramebufferTexture2D(GLenum a, GLenum b, GLenum c, GLuint d, GLint e) {
  using Fn = void (*)(GLenum, GLenum, GLenum, GLuint, GLint);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glFramebufferTexture2D")));
  g_glcalls[10].name = "glFramebufferTexture2D";
  GlCallTimer timer(10);
  real(a, b, c, d, e);
}
void* w_glMapBufferRange(GLenum a, GLintptr b, GLsizeiptr c, unsigned d) {
  using Fn = void* (*)(GLenum, GLintptr, GLsizeiptr, unsigned);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glMapBufferRange")));
  g_glcalls[11].name = "glMapBufferRange";
  GlCallTimer timer(11);
  return real(a, b, c, d);
}
unsigned char w_glUnmapBuffer(GLenum a) {
  using Fn = unsigned char (*)(GLenum);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glUnmapBuffer")));
  g_glcalls[12].name = "glUnmapBuffer";
  GlCallTimer timer(12);
  return real(a);
}
void w_glCopyTexSubImage2D(GLenum a, GLint b, GLint c, GLint d, GLint e, GLint f, GLsizei g, GLsizei h) {
  using Fn = void (*)(GLenum, GLint, GLint, GLint, GLint, GLint, GLsizei, GLsizei);
  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("glCopyTexSubImage2D")));
  g_glcalls[13].name = "glCopyTexSubImage2D";
  GlCallTimer timer(13);
  real(a, b, c, d, e, f, g, h);
}
void report_glcalls(double interval_ms) {
  GlCallStat e[14];
  std::memcpy(e, g_glcalls, sizeof e);
  std::sort(e, e + 14, [](const GlCallStat& a, const GlCallStat& b) { return a.ns > b.ns; });
  char buf[600];
  int n = std::snprintf(buf, sizeof buf, "glcalls (frame %.1f ms):", interval_ms);
  for (int i = 0; i < 6 && e[i].ns > 200000 && n < 520; ++i)
    n += std::snprintf(buf + n, sizeof buf - size_t(n), " %s n=%llu total=%.2fms max=%.2fms;", e[i].name, (unsigned long long)e[i].n, e[i].ns / 1e6, e[i].max_ns / 1e6);
  ps5_log("%s", buf);
}
void reset_glcalls() { for (auto& x : g_glcalls) { x.n = 0; x.ns = 0; x.max_ns = 0; } }


struct Entry {
  const char* name;
  void* fn;
};
const Entry kWrappers[] = {
    {"glEnable", reinterpret_cast<void*>(&w_Enable)},
    {"glDisable", reinterpret_cast<void*>(&w_Disable)},
    {"glPrimitiveRestartIndex", reinterpret_cast<void*>(&w_PrimitiveRestartIndex)},
    {"glBindVertexArray", reinterpret_cast<void*>(&w_BindVertexArray)},
    {"glDeleteVertexArrays", reinterpret_cast<void*>(&w_DeleteVertexArrays)},
    {"glBindBuffer", reinterpret_cast<void*>(&w_BindBuffer)},
    {"glBufferData", reinterpret_cast<void*>(&w_BufferData)},
    {"glBufferSubData", reinterpret_cast<void*>(&w_BufferSubData)},
    {"glDeleteBuffers", reinterpret_cast<void*>(&w_DeleteBuffers)},
    {"glDrawElements", reinterpret_cast<void*>(&w_DrawElements)},
    {"glDrawElementsBaseVertex", reinterpret_cast<void*>(&w_DrawElementsBaseVertex)},
    {"glDrawArrays", reinterpret_cast<void*>(&w_DrawArrays)},
    {"glBindFramebuffer", reinterpret_cast<void*>(&w_BindFramebuffer)},
    {"glVertexAttribIPointer", reinterpret_cast<void*>(&w_VertexAttribIPointer)},
    {"glVertexAttribPointer", reinterpret_cast<void*>(&w_VertexAttribPointer)},
    {"glMultiDrawElements", reinterpret_cast<void*>(&w_MultiDrawElements)},
    {"glTexImage2D", reinterpret_cast<void*>(&w_glTexImage2D)},
    {"glTexSubImage2D", reinterpret_cast<void*>(&w_glTexSubImage2D)},
    {"glTexImage1D", reinterpret_cast<void*>(&w_glTexImage1D)},
    {"glTexSubImage1D", reinterpret_cast<void*>(&w_glTexSubImage1D)},
    {"glClear", reinterpret_cast<void*>(&w_glClear)},
    {"glBlitFramebuffer", reinterpret_cast<void*>(&w_glBlitFramebuffer)},
    {"glGenerateMipmap", reinterpret_cast<void*>(&w_glGenerateMipmap)},
    {"glReadPixels", reinterpret_cast<void*>(&w_glReadPixels)},
    {"glFinish", reinterpret_cast<void*>(&w_glFinish)},
    {"glFlush", reinterpret_cast<void*>(&w_glFlush)},
    {"glFramebufferTexture2D", reinterpret_cast<void*>(&w_glFramebufferTexture2D)},
    {"glMapBufferRange", reinterpret_cast<void*>(&w_glMapBufferRange)},
    {"glUnmapBuffer", reinterpret_cast<void*>(&w_glUnmapBuffer)},
    {"glCopyTexSubImage2D", reinterpret_cast<void*>(&w_glCopyTexSubImage2D)},
};

}  // namespace

// Returns the wrapper for an interposed GL entry point, or null.
extern "C" void* ps5_glfix_lookup(const char* name) {
  for (const Entry& e : kWrappers)
    if (std::strcmp(e.name, name) == 0) return e.fn;
  return nullptr;
}

// Called once per swap: returns the render FBO of the frame that just finished (0 if none) and starts a new frame.
extern "C" unsigned ps5_glfix_end_frame() {
  if (MergeState* m_ = mg()) m_->orphan = true;
  g_draw_total = g_draw_count;
  g_draw_count = 0;
  ++g_frame_no;
  // bisect mode (/data/opengoal/config/bisect.txt): in every 900th frame only the first k/4 of the draws run
  static int bisect = -1;
  if (bisect < 0) {
    struct stat st;
    bisect = stat("/data/opengoal/config/bisect.txt", &st) == 0;
  }
  g_draw_limit = 0;
  if (bisect && (g_frame_no + 1) % 900 == 0) {
    static const int frac[] = {8, 8, 8, 2, 1, 4, 6, 7};  // eighths of the frame's draws, by capture number
    const unsigned idx = (g_frame_no + 1) / 900;
    g_draw_limit = idx < 8 ? g_draw_total * frac[idx] / 8 : 0;
  }
  if (g_tracing) {
    g_tracing = false;
    const size_t from = 0;
    ps5_log("trace: %zu draws, last %zu:", g_trace.size(), g_trace.size() - from);
    for (size_t i = from; i < g_trace.size(); ++i)
      ps5_log("trace[%zu] %s mode=0x%x prog=%d tex0=%d tex1=%d fbo=%d in=%ld out=%ld subs=%ld", i + 1, g_trace[i].kind, g_trace[i].mode, g_trace[i].prog,
              g_trace[i].tex0, g_trace[i].tex1, g_trace[i].fbo, g_trace[i].in_idx, g_trace[i].out_idx, g_trace[i].subs);
    g_trace.clear();
  }
  if (g_trace_req) {
    g_trace_req = false;
    g_tracing = true;
    g_trace.clear();
  }
  if (g_dyn_limit) g_draw_limit = unsigned(g_dyn_limit);
  const unsigned fbo = g_frame_fbo;
  g_frame_fbo = 0;
  if (fbo) g_main_fbo = fbo;
  return g_main_fbo;
}

extern "C" void ps5_glfix_set_limit(int n) { g_dyn_limit = n; }
extern "C" unsigned ps5_glfix_draw_total() { return g_draw_total; }
// Running counters for the slow-frame log: buffer uploads (calls, bytes), texture uploads and draw cycles.
extern "C" void ps5_glfix_counters(unsigned long long* bd_calls, unsigned long long* bd_bytes, unsigned long long* bsd_calls,
                                   unsigned long long* bsd_bytes, unsigned long long* draw_cycles) {
  *bd_calls = g_bd_calls; *bd_bytes = g_bd_bytes; *bsd_calls = g_bsd_calls; *bsd_bytes = g_bsd_bytes; *draw_cycles = g_draw_cycles;
}

extern "C" void ps5_glfix_trace() { g_trace_req = true; }

extern "C" void ps5_glfix_set_skip(int n) { g_skip = unsigned(n); g_skip_hi = 0; }
extern "C" void ps5_glfix_set_skip_range(int a, int b) { g_skip = unsigned(a); g_skip_hi = unsigned(b); }

// Debug: write the attached shader sources of GL program `prog` to /data/opengoal/log/prog<N>_<k>.glsl
extern "C" int ps5_glfix_dump_prog(int prog) {
  using GetAtt = void (*)(GLuint, GLsizei, GLsizei*, GLuint*);
  using GetSrc = void (*)(GLuint, GLsizei, GLsizei*, char*);
  auto att = reinterpret_cast<GetAtt>(const_cast<void*>(ps5_gl_lookup("glGetAttachedShaders")));
  auto src = reinterpret_cast<GetSrc>(const_cast<void*>(ps5_gl_lookup("glGetShaderSource")));
  if (!att || !src) return -1;
  GLuint sh[8];
  GLsizei n = 0;
  att(GLuint(prog), 8, &n, sh);
  for (GLsizei i = 0; i < n; ++i) {
    static char buf[1 << 18];
    GLsizei len = 0;
    src(sh[i], sizeof buf - 1, &len, buf);
    buf[len] = 0;
    char path[96];
    std::snprintf(path, sizeof path, "/data/opengoal/log/prog%d_%d.glsl", prog, int(i));
    if (FILE* f = std::fopen(path, "w")) { std::fwrite(buf, 1, size_t(len), f); std::fclose(f); }
  }
  return int(n);
}

// Called once per frame from SDL_GL_SwapWindow with the frame interval in ms; dumps the biggest gaps/draws of slow frames.
extern "C" void ps5_glfix_frame_end(double interval_ms) {
  ++g_frames_seen;
  static uint64_t last_dump = 0;
  const uint64_t n = now_ns();
  if (interval_ms > 25.0 && n - last_dump > 2000000000ull && g_tsc_per_us > 0) {
    last_dump = n;
    SlowEv e[12];
    std::memcpy(e, g_slow, sizeof e);
    std::sort(e, e + 12, [](const SlowEv& a, const SlowEv& b) { return a.at_us < b.at_us; });
    report_glcalls(interval_ms);
    ps5_log("slowdraws: frame %.1f ms, %u draws; events (at ms, draw# before/in, gap ms, draw ms):", interval_ms, g_ev_idx);
    for (const SlowEv& x : e)
      if (x.dur_us > 0 || x.gap_us > 0) ps5_log("  slowdraws: at %7.2f  #%-4u gap %6.2f  draw %6.2f  waits retire %.2f frame %.2f flip %.2f collect %.2f", x.at_us / 1000.0, x.idx, x.gap_us / 1000.0, x.dur_us / 1000.0, x.wait_ms[0], x.wait_ms[1], x.wait_ms[2], x.wait_ms[3]);
  }
  reset_glcalls();
  std::memset(g_slow, 0, sizeof g_slow);
  g_ev_idx = 0;
  g_frame_tsc0 = 0;
  g_last_end_tsc = 0;
}

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
    if (FILE* d = std::fopen("/data/opengoal/config/diag.txt", "r")) { g_diag = true; std::fclose(d); }
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
      std::snprintf(path, sizeof path, "/data/opengoal/log/trace_%llu_%u.bin", (unsigned long long)(first_ns / 1000000000ull), dump_no++);
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
