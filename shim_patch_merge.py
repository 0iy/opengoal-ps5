#!/usr/bin/env python3
"""Shim patch: merge the sub-draws of one glMultiDrawElements call into ONE driver draw (gather), plus statistics.

Target: ps5shim/glfix.cpp, or the file named by env GLFIX_SRC (use a private copy for tests). Idempotent; every anchor is asserted.

Env switches (map /data/opengoal/config/mergedraws.txt and mergestats.txt to them in appmain.cpp, see docs/agent_merge.md):
  PS5_MERGE_DRAWS=1  gather: the converted index ranges of one multi-draw call are copied into one contiguous index range of a
                     private dynamic element buffer and drawn with a single glDrawRangeElements. Exactly the same triangles in the
                     same order as the sub-draws, so the image is identical. Default off = current behaviour.
  PS5_MERGE_STATS=1  every 3 s log histograms (sub-draws per call, gaps between sub-draws, consecutive calls with identical state).
                     Works with or without PS5_MERGE_DRAWS.
Static data added: ONE function-local `static MergeState*` (heap object, allocated only when one of the two switches is set).
No namespace-scope variables, no arrays.
"""
import os

P = os.environ.get("GLFIX_SRC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps5shim", "glfix.cpp")
s = open(P, encoding="utf-8").read()
if "MERGE_DRAWS" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


HELPERS = r'''// MERGE_DRAWS: gather the sub-draws of a multi-draw call into one draw (PS5_MERGE_DRAWS=1), statistics (PS5_MERGE_STATS=1)
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
  if (m->orphan || m->off + total > m->cap) {
    if (m->off + total > m->cap) m->cap = std::max(m->cap * 2, total * 2 + 65536);
    if (m->cap < (size_t(1) << 20)) m->cap = size_t(1) << 20;
    R.BufferData(kElementArrayBuffer, GLsizeiptr(m->cap * 4), nullptr, kDynamicDraw);  // new storage; draws already queued keep the old one
    m->off = 0;
    m->orphan = false;
  }
  R.BufferSubData(kElementArrayBuffer, GLintptr(m->off * 4), GLsizeiptr(total * 4), m->stage.data());
  hw_restart(false);
  const void* first = reinterpret_cast<const void*>(uintptr_t(m->off) * 4);
  m->off += total;
  ++m->ms.gathered;
  m->ms.gathered_idx += total;
  if (R.DrawRangeElements) rt_real(R.DrawRangeElements, kTriangles, lo, hi, GLsizei(total), kUnsignedInt, first);
  else rt_real(R.DrawElements, kTriangles, GLsizei(total), kUnsignedInt, first);
  return true;
}

'''

rep("#include <cstring>" + chr(10), "#include <cstring>" + chr(10) + "#include <cstdlib>" + chr(10))
rep("void w_DrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {",
    HELPERS + "void w_DrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {")

# single draws: statistics only
rep("    hist(3, mode, type, S.restart_enabled);\n",
    "    hist(3, mode, type, S.restart_enabled);\n"
    "    if (MergeState* ms_ = mg()) { if (ms_->stats) ms_single(ms_, n > 0 ? buf : 0, first, n); }\n")
rep("    hist(2, mode, type, S.restart_enabled);\n",
    "    hist(2, mode, type, S.restart_enabled);\n"
    "    if (MergeState* ms_ = mg()) { if (ms_->stats) ms_other(ms_); }\n")
rep("  hist(1, mode, 0, S.restart_enabled);\n",
    "  hist(1, mode, 0, S.restart_enabled);\n"
    "  if (MergeState* ms_ = mg()) { if (ms_->stats) ms_other(ms_); }\n")

# multi draw: statistics before the existing adjacent-range merge, gather instead of the multi-draw call
rep("    g_md_in += out_counts.size();\n",
    "    g_md_in += out_counts.size();\n"
    "    MergeState* mst_ = mg();\n"
    "    if (mst_ && mst_->stats) ms_multi(mst_, buf, out_counts, out_offsets, counts, indices, drawcount);\n")
rep("    if (!out_counts.empty()) {\n      bind_hw_ebo(buf);\n      hw_restart(false);\n      rt_real(R.MultiDrawElements, kTriangles,",
    "    if (merge_gather(mst_, out_counts, out_offsets)) {\n"
    "      // one driver draw issued\n"
    "    } else if (!out_counts.empty()) {\n      bind_hw_ebo(buf);\n      hw_restart(false);\n      rt_real(R.MultiDrawElements, kTriangles,")

# new frame: the gather buffer is respecified before its first use
rep("extern \"C\" unsigned ps5_glfix_end_frame() {\n  g_draw_total = g_draw_count;\n",
    "extern \"C\" unsigned ps5_glfix_end_frame() {\n  if (MergeState* m_ = mg()) m_->orphan = true;\n  g_draw_total = g_draw_count;\n")

open(P, "w", encoding="utf-8").write(s)
print("patched", P)
