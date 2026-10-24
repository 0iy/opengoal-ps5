#!/usr/bin/env python3
"""Shim patch (diagnostic): timed pass-through wrappers for the non-draw GL calls that can block (texture uploads, clears,
blits, mipmaps, readbacks, FBO changes, finish/flush, map/unmap). Slow frames log the biggest per-function totals."""
import os

here = os.path.dirname(os.path.abspath(__file__))
g = os.path.join(here, "ps5shim", "glfix.cpp")
s = open(g, encoding="utf-8").read()
if "GLCALL_WRAPPERS" in s:
    print("already patched")
    raise SystemExit

# name, return type, parameter types, argument names
calls = [
    ("TexImage2D", "void", ["GLenum", "GLint", "GLint", "GLsizei", "GLsizei", "GLint", "GLenum", "GLenum", "const void*"]),
    ("TexSubImage2D", "void", ["GLenum", "GLint", "GLint", "GLint", "GLsizei", "GLsizei", "GLenum", "GLenum", "const void*"]),
    ("TexImage1D", "void", ["GLenum", "GLint", "GLint", "GLsizei", "GLint", "GLenum", "GLenum", "const void*"]),
    ("TexSubImage1D", "void", ["GLenum", "GLint", "GLint", "GLsizei", "GLenum", "GLenum", "const void*"]),
    ("Clear", "void", ["GLbitfield"]),
    ("BlitFramebuffer", "void", ["GLint", "GLint", "GLint", "GLint", "GLint", "GLint", "GLint", "GLint", "GLbitfield", "GLenum"]),
    ("GenerateMipmap", "void", ["GLenum"]),
    ("ReadPixels", "void", ["GLint", "GLint", "GLsizei", "GLsizei", "GLenum", "GLenum", "void*"]),
    ("Finish", "void", []),
    ("Flush", "void", []),
    ("FramebufferTexture2D", "void", ["GLenum", "GLenum", "GLenum", "GLuint", "GLint"]),
    ("MapBufferRange", "void*", ["GLenum", "GLintptr", "GLsizeiptr", "GLbitfield"]),
    ("UnmapBuffer", "GLboolean", ["GLenum"]),
    ("CopyTexSubImage2D", "void", ["GLenum", "GLint", "GLint", "GLint", "GLint", "GLint", "GLsizei", "GLsizei"]),
]
N = len(calls)

code = [
    "// GLCALL_WRAPPERS: timed pass-through wrappers (diagnostic)",
    "struct GlCallStat { const char* name; uint64_t n, ns, max_ns; };",
    "GlCallStat g_glcalls[%d];" % N,
    "struct GlCallTimer {",
    "  int slot; uint64_t t0;",
    "  explicit GlCallTimer(int s) : slot(s), t0(now_ns()) {}",
    "  ~GlCallTimer() { const uint64_t d = now_ns() - t0; GlCallStat& e = g_glcalls[slot]; ++e.n; e.ns += d; if (d > e.max_ns) e.max_ns = d; }",
    "};",
]
for i, (name, ret, types) in enumerate(calls):
    names = [chr(ord("a") + k) for k in range(len(types))]
    params = ", ".join("%s %s" % (t, n) for t, n in zip(types, names))
    ftype = "%s (*)(%s)" % (ret, ", ".join(types) if types else "void")
    code.append("%s w_gl%s(%s) {" % (ret, name, params))
    code.append("  using Fn = %s;" % ftype)
    code.append('  static Fn real = reinterpret_cast<Fn>(const_cast<void*>(ps5_gl_lookup("gl%s")));' % name)
    code.append("  g_glcalls[%d].name = \"gl%s\";" % (i, name))
    code.append("  GlCallTimer timer(%d);" % i)
    code.append("  %sreal(%s);" % ("" if ret == "void" else "return ", ", ".join(names)))
    code.append("}")
code.append("""void report_glcalls(double interval_ms) {
  GlCallStat e[%d];
  std::memcpy(e, g_glcalls, sizeof e);
  std::sort(e, e + %d, [](const GlCallStat& a, const GlCallStat& b) { return a.ns > b.ns; });
  char buf[600];
  int n = std::snprintf(buf, sizeof buf, "glcalls (frame %%.1f ms):", interval_ms);
  for (int i = 0; i < 6 && e[i].ns > 200000 && n < 520; ++i)
    n += std::snprintf(buf + n, sizeof buf - size_t(n), " %%s n=%%llu total=%%.2fms max=%%.2fms;", e[i].name, (unsigned long long)e[i].n, e[i].ns / 1e6, e[i].max_ns / 1e6);
  ps5_log("%%s", buf);
}
void reset_glcalls() { for (auto& x : g_glcalls) { x.n = 0; x.ns = 0; x.max_ns = 0; } }
""" % (N, N))
block = "\n".join(code) + "\n"

marker = "struct Entry {"
assert s.count(marker) == 1
s = s.replace(marker, block + "\n" + marker)

old = '    ps5_log("slowdraws: frame %.1f ms, %u draws; events (at ms, draw# before/in, gap ms, draw ms):", interval_ms, g_ev_idx);'
assert s.count(old) == 1
s = s.replace(old, "    report_glcalls(interval_ms);\n" + old)
old = "  std::memset(g_slow, 0, sizeof g_slow);\n  g_ev_idx = 0;"
assert s.count(old) == 1
s = s.replace(old, "  reset_glcalls();\n" + old)

anchor = '    {"glMultiDrawElements", reinterpret_cast<void*>(&w_MultiDrawElements)},'
assert s.count(anchor) == 1
reg = "\n".join('    {"gl%s", reinterpret_cast<void*>(&w_gl%s)},' % (c[0], c[0]) for c in calls)
s = s.replace(anchor, anchor + "\n" + reg)
open(g, "w", encoding="utf-8").write(s)
print("ok")
