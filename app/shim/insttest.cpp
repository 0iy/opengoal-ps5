// Go/no-go probe for merc instancing: does the PS5 GL driver run glDrawElementsInstanced + instanced vertex attributes + a buffer
// texture (texelFetch in the vertex shader) correctly and fast? Runs once, ~15 s into a run, when
// /data/opengoal/config/insttest.txt exists. Draws into its own FBO, restores the touched GL state, logs "insttest: ..." lines.
#include <sys/stat.h>
#include <time.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

#include "third-party/glad/include/glad/glad.h"

void ps5_log(const char* fmt, ...);

namespace {

struct F {
  void (*GenBuffers)(GLsizei, GLuint*);
  void (*DeleteBuffers)(GLsizei, const GLuint*);
  void (*BindBuffer)(GLenum, GLuint);
  void (*BufferData)(GLenum, GLsizeiptr, const void*, GLenum);
  void (*BindBufferRange)(GLenum, GLuint, GLuint, GLintptr, GLsizeiptr);
  void (*GenVertexArrays)(GLsizei, GLuint*);
  void (*DeleteVertexArrays)(GLsizei, const GLuint*);
  void (*BindVertexArray)(GLuint);
  void (*EnableVertexAttribArray)(GLuint);
  void (*VertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
  void (*VertexAttribIPointer)(GLuint, GLint, GLenum, GLsizei, const void*);
  void (*VertexAttribDivisor)(GLuint, GLuint);
  GLuint (*CreateShader)(GLenum);
  void (*ShaderSource)(GLuint, GLsizei, const GLchar* const*, const GLint*);
  void (*CompileShader)(GLuint);
  void (*GetShaderiv)(GLuint, GLenum, GLint*);
  void (*GetShaderInfoLog)(GLuint, GLsizei, GLsizei*, GLchar*);
  GLuint (*CreateProgram)();
  void (*AttachShader)(GLuint, GLuint);
  void (*LinkProgram)(GLuint);
  void (*GetProgramiv)(GLuint, GLenum, GLint*);
  void (*GetProgramInfoLog)(GLuint, GLsizei, GLsizei*, GLchar*);
  void (*UseProgram)(GLuint);
  void (*DeleteProgram)(GLuint);
  void (*DeleteShader)(GLuint);
  GLint (*GetUniformLocation)(GLuint, const GLchar*);
  GLuint (*GetUniformBlockIndex)(GLuint, const GLchar*);
  void (*UniformBlockBinding)(GLuint, GLuint, GLuint);
  void (*Uniform1i)(GLint, GLint);
  void (*GenTextures)(GLsizei, GLuint*);
  void (*DeleteTextures)(GLsizei, const GLuint*);
  void (*BindTexture)(GLenum, GLuint);
  void (*TexBuffer)(GLenum, GLenum, GLuint);
  void (*TexImage2D)(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*);
  void (*TexParameteri)(GLenum, GLenum, GLint);
  void (*ActiveTexture)(GLenum);
  void (*GenFramebuffers)(GLsizei, GLuint*);
  void (*DeleteFramebuffers)(GLsizei, const GLuint*);
  void (*BindFramebuffer)(GLenum, GLuint);
  void (*FramebufferTexture2D)(GLenum, GLenum, GLenum, GLuint, GLint);
  GLenum (*CheckFramebufferStatus)(GLenum);
  void (*Viewport)(GLint, GLint, GLsizei, GLsizei);
  void (*ClearColor)(GLfloat, GLfloat, GLfloat, GLfloat);
  void (*ClearDepth)(GLdouble);
  void (*Clear)(GLbitfield);
  void (*Enable)(GLenum);
  void (*Disable)(GLenum);
  void (*DepthFunc)(GLenum);
  void (*DepthMask)(GLboolean);
  void (*ColorMask)(GLboolean, GLboolean, GLboolean, GLboolean);
  void (*DrawElements)(GLenum, GLsizei, GLenum, const void*);
  void (*DrawElementsInstanced)(GLenum, GLsizei, GLenum, const void*, GLsizei);
  void (*ReadPixels)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*);
  void (*Finish)();
  GLenum (*GetError)();
  void (*GetIntegerv)(GLenum, GLint*);
  void (*GetIntegeri_v)(GLenum, GLuint, GLint*);
  GLboolean (*IsEnabled)(GLenum);
};

constexpr int kInst = 200, kSide = 32, kBoneVec = 1024;  // instances, mesh grid vertices per side, bone vec4s per instance (16 KB window)
constexpr int kRes = 256;

const char* kVsCommon = R"(#version 410 core
layout (location = 0) in vec3 position_in;
layout (location = 2) in vec3 weights_in;
layout (location = 5) in uvec3 mats;
out vec4 vtx_color;
void shade(mat4 X0, mat4 X1, mat4 X2, float inst) {
  vec4 p = vec4(position_in, 1);
  vec4 q = X0 * p * weights_in[0] + X1 * p * weights_in[1] + X2 * p * weights_in[2];
  gl_Position = vec4(q.xy, q.z, 1.0);
  vtx_color = vec4(fract(position_in.x * 7.0), fract(position_in.y * 5.0), fract(inst * 0.37), 1.0);
}
)";
const char* kVsUbo = R"(
struct M { mat4 X; mat3 R; vec4 pad; };
layout (std140) uniform ub_bones { M bones[128]; };
uniform float inst_id;
void main() { shade(bones[mats[0]].X, bones[mats[1]].X, bones[mats[2]].X, inst_id); }
)";
const char* kVsTbo = R"(
uniform samplerBuffer bones_tbo;
layout (location = 6) in uint first_bone;
mat4 fetchX(uint m) {
  int b = int(first_bone) + int(m) * 8;
  return mat4(texelFetch(bones_tbo, b), texelFetch(bones_tbo, b + 1), texelFetch(bones_tbo, b + 2), texelFetch(bones_tbo, b + 3));
}
mat3 fetchR(uint m) {
  int b = int(first_bone) + int(m) * 8;
  return mat3(texelFetch(bones_tbo, b + 4).xyz, texelFetch(bones_tbo, b + 5).xyz, texelFetch(bones_tbo, b + 6).xyz);
}
void main() {
  mat3 r = fetchR(mats[0]) + fetchR(mats[1]) + fetchR(mats[2]);  // keep the normal matrices live like the real shader
  shade(fetchX(mats[0]), fetchX(mats[1]), fetchX(mats[2]), float(first_bone / 1024u) + r[0][0] * 0.0);
}
)";
const char* kFs = R"(#version 410 core
in vec4 vtx_color;
out vec4 color;
void main() { color = vtx_color; }
)";

double now_ms() {
  timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

GLuint build(const F& f, const char* vs_body, bool& ok) {
  auto compile = [&](GLenum type, std::vector<const char*> src) {
    GLuint s = f.CreateShader(type);
    f.ShaderSource(s, GLsizei(src.size()), src.data(), nullptr);
    f.CompileShader(s);
    GLint st = 0;
    f.GetShaderiv(s, GL_COMPILE_STATUS, &st);
    if (!st) {
      char log[512] = {};
      f.GetShaderInfoLog(s, sizeof log - 1, nullptr, log);
      ps5_log("insttest: shader error: %s", log);
      ok = false;
    }
    return s;
  };
  GLuint v = compile(GL_VERTEX_SHADER, {kVsCommon, vs_body}), fs = compile(GL_FRAGMENT_SHADER, {kFs});
  GLuint p = f.CreateProgram();
  f.AttachShader(p, v);
  f.AttachShader(p, fs);
  f.LinkProgram(p);
  GLint st = 0;
  f.GetProgramiv(p, GL_LINK_STATUS, &st);
  if (!st) {
    char log[512] = {};
    f.GetProgramInfoLog(p, sizeof log - 1, nullptr, log);
    ps5_log("insttest: link error: %s", log);
    ok = false;
  }
  f.DeleteShader(v);
  f.DeleteShader(fs);
  return p;
}

uint64_t hash_image(const F& f) {
  std::vector<uint8_t> px(size_t(kRes) * kRes * 4);
  f.ReadPixels(0, 0, kRes, kRes, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
  uint64_t h = 1469598103934665603ull;
  for (uint8_t b : px) h = (h ^ b) * 1099511628211ull;
  size_t lit = 0;
  for (size_t i = 0; i < px.size(); i += 4) lit += (px[i] | px[i + 1] | px[i + 2]) != 0;
  ps5_log("insttest: image has %zu lit pixels of %d", lit, kRes * kRes);
  return h;
}

void run(void* (*getproc)(const char*)) {
  F f{};
  bool ok = true;
#define L(n) f.n = reinterpret_cast<decltype(f.n)>(getproc("gl" #n)); if (!f.n) { ps5_log("insttest: missing gl" #n); ok = false; }
  L(GenBuffers) L(DeleteBuffers) L(BindBuffer) L(BufferData) L(BindBufferRange) L(GenVertexArrays) L(DeleteVertexArrays) L(BindVertexArray)
  L(EnableVertexAttribArray) L(VertexAttribPointer) L(VertexAttribIPointer) L(VertexAttribDivisor) L(CreateShader) L(ShaderSource)
  L(CompileShader) L(GetShaderiv) L(GetShaderInfoLog) L(CreateProgram) L(AttachShader) L(LinkProgram) L(GetProgramiv) L(GetProgramInfoLog)
  L(UseProgram) L(DeleteProgram) L(DeleteShader) L(GetUniformLocation) L(GetUniformBlockIndex) L(UniformBlockBinding) L(Uniform1i)
  L(GenTextures) L(DeleteTextures) L(BindTexture) L(TexBuffer) L(TexImage2D) L(TexParameteri) L(ActiveTexture) L(GenFramebuffers)
  L(DeleteFramebuffers) L(BindFramebuffer) L(FramebufferTexture2D) L(CheckFramebufferStatus) L(Viewport) L(ClearColor) L(ClearDepth)
  L(Clear) L(Enable) L(Disable) L(DepthFunc) L(DepthMask) L(ColorMask) L(DrawElements) L(DrawElementsInstanced) L(ReadPixels) L(Finish)
  L(GetError) L(GetIntegerv) L(GetIntegeri_v) L(IsEnabled)
#undef L
  if (!ok) { ps5_log("insttest: ABORT, entry points missing"); return; }
  ps5_log("insttest: start (%d instances, mesh %dx%d vertices, %d triangles each)", kInst, kSide, kSide, (kSide - 1) * (kSide - 1) * 2);
  while (f.GetError()) {}

  // save the state we touch
  GLint s_prog, s_vao, s_arr, s_fbo, s_tex0, s_texbuf, s_active, s_ubo, s_vp[4], s_depth_func;
  GLint s_uboi_buf, s_uboi_off, s_uboi_size;
  GLboolean s_depth_mask;
  f.GetIntegerv(GL_CURRENT_PROGRAM, &s_prog);
  f.GetIntegerv(GL_VERTEX_ARRAY_BINDING, &s_vao);
  f.GetIntegerv(GL_ARRAY_BUFFER_BINDING, &s_arr);
  f.GetIntegerv(GL_FRAMEBUFFER_BINDING, &s_fbo);
  f.GetIntegerv(GL_ACTIVE_TEXTURE, &s_active);
  f.GetIntegerv(GL_TEXTURE_BINDING_2D, &s_tex0);
  f.GetIntegerv(GL_TEXTURE_BINDING_BUFFER, &s_texbuf);
  f.GetIntegerv(GL_UNIFORM_BUFFER_BINDING, &s_ubo);
  f.GetIntegeri_v(GL_UNIFORM_BUFFER_BINDING, 1, &s_uboi_buf);
  f.GetIntegeri_v(GL_UNIFORM_BUFFER_START, 1, &s_uboi_off);
  f.GetIntegeri_v(GL_UNIFORM_BUFFER_SIZE, 1, &s_uboi_size);
  f.GetIntegerv(GL_VIEWPORT, s_vp);
  f.GetIntegerv(GL_DEPTH_FUNC, &s_depth_func);
  { GLint dm = 1; f.GetIntegerv(GL_DEPTH_WRITEMASK, &dm); s_depth_mask = GLboolean(dm); }
  const GLboolean s_depth_test = f.IsEnabled(GL_DEPTH_TEST), s_blend = f.IsEnabled(GL_BLEND), s_cull = f.IsEnabled(GL_CULL_FACE),
                  s_scissor = f.IsEnabled(GL_SCISSOR_TEST), s_prim = f.IsEnabled(GL_PRIMITIVE_RESTART);

  // mesh: grid, interleaved pos3 / weights3 / mats uvec3 = 36 bytes
  struct V { float p[3], w[3]; uint32_t m[3]; };
  std::vector<V> verts;
  for (int y = 0; y < kSide; ++y)
    for (int x = 0; x < kSide; ++x) {
      V v{};
      v.p[0] = float(x) / (kSide - 1) * 2.f - 1.f;
      v.p[1] = float(y) / (kSide - 1) * 2.f - 1.f;
      v.p[2] = 0.f;
      v.w[0] = 0.5f; v.w[1] = 0.3f; v.w[2] = 0.2f;
      v.m[0] = uint32_t((x + y) % 8); v.m[1] = uint32_t((x + y + 1) % 8); v.m[2] = uint32_t((x + y + 2) % 8);
      verts.push_back(v);
    }
  std::vector<uint32_t> idx;
  for (int y = 0; y + 1 < kSide; ++y)
    for (int x = 0; x + 1 < kSide; ++x) {
      uint32_t a = uint32_t(y * kSide + x), b = a + 1, c = a + kSide, d = c + 1;
      idx.insert(idx.end(), {a, b, c, b, d, c});
    }
  // bones: 8 per instance, every bone = scale + translation of the instance, rows laid out as 4 vec4 (columns) + 3 vec4 + pad
  std::vector<float> bones(size_t(kInst) * kBoneVec * 4, 0.f);
  for (int i = 0; i < kInst; ++i) {
    const float sc = 0.06f, tx = (float(i % 20) - 9.5f) * 0.1f, ty = (float(i / 20) - 4.5f) * 0.2f, tz = -0.9f + 1.8f * float(i) / kInst;
    for (int b = 0; b < 8; ++b) {
      float* m = &bones[(size_t(i) * kBoneVec + size_t(b) * 8) * 4];
      m[0] = sc; m[5] = sc; m[10] = 0.001f; m[12] = tx; m[13] = ty; m[14] = tz; m[15] = 1.f;  // mat4, column major
      m[16] = 1.f; m[21] = 1.f; m[26] = 1.f;                                                   // mat3 columns in vec4s 4..6
    }
  }
  std::vector<uint32_t> firstb(kInst);
  for (int i = 0; i < kInst; ++i) firstb[size_t(i)] = uint32_t(i * kBoneVec);

  GLuint vbo, ebo, bonebuf, instbuf, tbo, vao, fbo, col, dep;
  f.GenBuffers(1, &vbo); f.GenBuffers(1, &ebo); f.GenBuffers(1, &bonebuf); f.GenBuffers(1, &instbuf);
  f.GenVertexArrays(1, &vao);
  f.BindVertexArray(vao);
  f.BindBuffer(GL_ARRAY_BUFFER, vbo);
  f.BufferData(GL_ARRAY_BUFFER, GLsizeiptr(verts.size() * sizeof(V)), verts.data(), GL_STATIC_DRAW);
  f.BindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
  f.BufferData(GL_ELEMENT_ARRAY_BUFFER, GLsizeiptr(idx.size() * 4), idx.data(), GL_STATIC_DRAW);
  f.EnableVertexAttribArray(0); f.VertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(V), (void*)0);
  f.EnableVertexAttribArray(2); f.VertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, sizeof(V), (void*)12);
  f.EnableVertexAttribArray(5); f.VertexAttribIPointer(5, 3, GL_UNSIGNED_INT, sizeof(V), (void*)24);
  f.BindBuffer(GL_UNIFORM_BUFFER, bonebuf);
  f.BufferData(GL_UNIFORM_BUFFER, GLsizeiptr(bones.size() * 4), bones.data(), GL_DYNAMIC_DRAW);
  f.BindBuffer(GL_ARRAY_BUFFER, instbuf);
  f.BufferData(GL_ARRAY_BUFFER, GLsizeiptr(firstb.size() * 4), firstb.data(), GL_DYNAMIC_DRAW);
  f.GenTextures(1, &tbo);
  f.ActiveTexture(GL_TEXTURE0 + 5);
  f.BindTexture(GL_TEXTURE_BUFFER, tbo);
  f.TexBuffer(GL_TEXTURE_BUFFER, GL_RGBA32F, bonebuf);
  const GLenum e_tbo = f.GetError();
  GLint maxtb = 0; f.GetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE, &maxtb);
  ps5_log("insttest: texbuffer error=0x%x, max texture buffer size=%d", e_tbo, maxtb);

  f.GenFramebuffers(1, &fbo); f.GenTextures(1, &col); f.GenTextures(1, &dep);
  f.ActiveTexture(GL_TEXTURE0);
  f.BindTexture(GL_TEXTURE_2D, col);
  f.TexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, kRes, kRes, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
  f.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  f.BindTexture(GL_TEXTURE_2D, dep);
  f.TexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, kRes, kRes, 0, GL_DEPTH_COMPONENT, GL_UNSIGNED_INT, nullptr);
  f.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  f.BindFramebuffer(GL_FRAMEBUFFER, fbo);
  f.FramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, col, 0);
  f.FramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, dep, 0);
  const GLenum fbs = f.CheckFramebufferStatus(GL_FRAMEBUFFER);
  ps5_log("insttest: framebuffer status=0x%x", fbs);

  GLuint pu = build(f, kVsUbo, ok), pt = build(f, kVsTbo, ok);
  if (ok && fbs == GL_FRAMEBUFFER_COMPLETE) {
    f.Viewport(0, 0, kRes, kRes);
    f.Disable(GL_BLEND); f.Disable(GL_CULL_FACE); f.Disable(GL_SCISSOR_TEST); f.Disable(GL_PRIMITIVE_RESTART);
    f.Enable(GL_DEPTH_TEST); f.DepthFunc(GL_LESS); f.DepthMask(GL_TRUE); f.ColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    f.ClearColor(0, 0, 0, 1); f.ClearDepth(1.0);
    const GLsizei n_idx = GLsizei(idx.size());

    auto vattr_inst = [&](bool on) {
      f.BindBuffer(GL_ARRAY_BUFFER, instbuf);
      if (on) { f.EnableVertexAttribArray(6); f.VertexAttribIPointer(6, 1, GL_UNSIGNED_INT, 4, (void*)0); f.VertexAttribDivisor(6, 1); }
    };
    const GLint tbo_loc = f.GetUniformLocation(pt, "bones_tbo"), id_loc = f.GetUniformLocation(pu, "inst_id");
    const GLuint blk = f.GetUniformBlockIndex(pu, "ub_bones");
    f.UniformBlockBinding(pu, blk, 1);

    auto u1f = reinterpret_cast<void (*)(GLint, GLfloat)>(getproc("glUniform1f"));
    auto run_ubo = [&] {
      f.UseProgram(pu);
      f.BindVertexArray(vao);
      f.BindBuffer(GL_ARRAY_BUFFER, vbo);
      for (int i = 0; i < kInst; ++i) {
        u1f(id_loc, float(i));
        f.BindBufferRange(GL_UNIFORM_BUFFER, 1, bonebuf, GLintptr(i) * kBoneVec * 16, 128 * 128);
        f.DrawElements(GL_TRIANGLES, n_idx, GL_UNSIGNED_INT, nullptr);
      }
    };
    auto run_tbo_single = [&] {  // same shader as the instanced path, one draw per instance (isolates the texelFetch cost)
      f.UseProgram(pt);
      f.Uniform1i(tbo_loc, 5);
      f.BindVertexArray(vao);
      for (int i = 0; i < kInst; ++i) {
        f.BindBuffer(GL_ARRAY_BUFFER, instbuf);
        f.VertexAttribIPointer(6, 1, GL_UNSIGNED_INT, 4, (void*)(uintptr_t(i) * 4));
        f.DrawElementsInstanced(GL_TRIANGLES, n_idx, GL_UNSIGNED_INT, nullptr, 1);
      }
    };
    auto run_tbo_inst = [&] {
      f.UseProgram(pt);
      f.Uniform1i(tbo_loc, 5);
      f.BindVertexArray(vao);
      f.BindBuffer(GL_ARRAY_BUFFER, instbuf);
      f.VertexAttribIPointer(6, 1, GL_UNSIGNED_INT, 4, (void*)0);
      f.DrawElementsInstanced(GL_TRIANGLES, n_idx, GL_UNSIGNED_INT, nullptr, kInst);
    };
    f.BindVertexArray(vao);
    vattr_inst(true);

    double med[3] = {0, 0, 0}, cpu[3] = {0, 0, 0};
    uint64_t hsh[3] = {0, 0, 0};
    for (int v = 0; v < 3; ++v) {
      std::vector<double> t, c;
      for (int rep = 0; rep < 18; ++rep) {
        f.Clear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        f.Finish();
        const double t0 = now_ms();
        if (v == 0) run_ubo(); else if (v == 1) run_tbo_single(); else run_tbo_inst();
        const double t1 = now_ms();
        f.Finish();
        const double t2 = now_ms();
        if (rep >= 3) { t.push_back(t2 - t0); c.push_back(t1 - t0); }
        if (rep == 17) hsh[v] = hash_image(f);
      }
      std::sort(t.begin(), t.end()); std::sort(c.begin(), c.end());
      med[v] = t[t.size() / 2]; cpu[v] = c[c.size() / 2];
    }
    const char* names[3] = {"ubo, draw per instance (old engine path)", "tbo shader, draw per instance", "tbo shader, ONE instanced draw"};
    for (int v = 0; v < 3; ++v)
      ps5_log("insttest: %-42s total %.2f ms  cpu-submit %.2f ms  image hash %016llx", names[v], med[v], cpu[v], (unsigned long long)hsh[v]);
    ps5_log("insttest: images %s; gl error 0x%x", (hsh[0] == hsh[1] && hsh[1] == hsh[2]) ? "IDENTICAL" : "DIFFER", f.GetError());
    if (med[2] > 0) ps5_log("insttest: speedup of the instanced draw vs old path: x%.2f total, x%.2f cpu", med[0] / med[2], cpu[0] / std::max(cpu[2], 0.001));
    ps5_log("insttest: VERDICT %s", (hsh[0] == hsh[1] && hsh[1] == hsh[2] && med[2] < med[0]) ? "GO" : "NO-GO (see lines above)");
  }

  // clean up and restore
  f.UseProgram(0);
  f.DeleteProgram(pu); f.DeleteProgram(pt);
  f.BindFramebuffer(GL_FRAMEBUFFER, GLuint(s_fbo));
  f.DeleteFramebuffers(1, &fbo);
  f.ActiveTexture(GL_TEXTURE0);
  f.DeleteTextures(1, &col); f.DeleteTextures(1, &dep);
  f.ActiveTexture(GL_TEXTURE0 + 5); f.BindTexture(GL_TEXTURE_BUFFER, GLuint(s_texbuf)); f.DeleteTextures(1, &tbo);
  f.ActiveTexture(GL_TEXTURE0); f.BindTexture(GL_TEXTURE_2D, GLuint(s_tex0));
  f.ActiveTexture(GLenum(s_active));
  f.BindVertexArray(GLuint(s_vao));
  f.DeleteVertexArrays(1, &vao);
  f.DeleteBuffers(1, &vbo); f.DeleteBuffers(1, &ebo); f.DeleteBuffers(1, &instbuf);
  f.BindBuffer(GL_ARRAY_BUFFER, GLuint(s_arr));
  f.BindBuffer(GL_UNIFORM_BUFFER, GLuint(s_ubo));
  if (s_uboi_buf) f.BindBufferRange(GL_UNIFORM_BUFFER, 1, GLuint(s_uboi_buf), s_uboi_off, s_uboi_size);
  f.DeleteBuffers(1, &bonebuf);
  f.UseProgram(GLuint(s_prog));
  f.Viewport(s_vp[0], s_vp[1], s_vp[2], s_vp[3]);
  f.DepthFunc(GLenum(s_depth_func)); f.DepthMask(s_depth_mask);
  f.ColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
  (s_depth_test ? f.Enable : f.Disable)(GL_DEPTH_TEST);
  (s_blend ? f.Enable : f.Disable)(GL_BLEND);
  (s_cull ? f.Enable : f.Disable)(GL_CULL_FACE);
  (s_scissor ? f.Enable : f.Disable)(GL_SCISSOR_TEST);
  (s_prim ? f.Enable : f.Disable)(GL_PRIMITIVE_RESTART);
  while (f.GetError()) {}
  ps5_log("insttest: done");
}

}  // namespace

// Called once per swap on the GL thread.
extern "C" void ps5_insttest_tick(void* (*getproc)(const char*)) {
  static int frame = 0, state = 0;  // 0 waiting, 1 done, 2 disabled
  if (state) return;
  if (++frame == 1) {
    struct stat st;
    if (stat("/data/opengoal/config/insttest.txt", &st) != 0) { state = 2; return; }
  }
  if (frame < 900) return;
  state = 1;
  run(getproc);
}
