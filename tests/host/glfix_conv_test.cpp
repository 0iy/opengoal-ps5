#include <cstdint>
#include <cstdio>
#include <vector>
#include <cstdlib>
typedef uint32_t GLuint; typedef unsigned GLenum;
constexpr GLenum kTriangleStrip = 0x0005, kTriangleFan = 0x0006;
constexpr uint32_t kRestart = 0xFFFFFFFFu;
struct Shadow { std::vector<uint32_t> data; };
struct State { uint32_t restart_index = kRestart; size_t indices_converted = 0; } S;
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
    out.clear();
    map.clear();
    done = 0;
    strip_pos = 0;
    uploaded = 0;
  }
};

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
std::vector<uint32_t> ref_tris(const std::vector<uint32_t>& src) {
  std::vector<uint32_t> out; std::vector<uint32_t> strip;
  auto flush = [&]() { for (size_t i = 0; i + 2 < strip.size(); ++i) { uint32_t a = strip[i], b = strip[i+1], c = strip[i+2]; if (i & 1) { out.push_back(b); out.push_back(a); } else { out.push_back(a); out.push_back(b); } out.push_back(c); } strip.clear(); };
  for (uint32_t v : src) { if (v == kRestart) flush(); else strip.push_back(v); }
  flush(); return out;
}
int main() {
  int bad = 0, tot = 0;
  for (int t = 0; t < 300; ++t) {
    std::vector<uint32_t> src; int n = 40 + rand() % 300;
    for (int i = 0; i < n; ++i) { if (rand() % 13 == 0) src.push_back(kRestart); else src.push_back(rand() % 60); }
    Converted c; convert_until(c, src, src.size(), false);
    for (int k = 0; k < 20; ++k) {
      size_t first = rand() % src.size(); if (first > 0 && src[first - 1] != kRestart) continue;
      size_t count = 1 + rand() % (src.size() - first);
      std::vector<uint32_t> slice(src.begin() + first, src.begin() + first + count);
      auto r = ref_tris(slice);
      std::vector<uint32_t> got(c.out.begin() + c.map[first], c.out.begin() + c.map[first + count]);
      ++tot;
      if (got != r) { ++bad; if (bad <= 3) printf("range mismatch t=%d first=%zu count=%zu got=%zu ref=%zu\n", t, first, count, got.size(), r.size()); }
    }
  }
  printf("range mismatches: %d / %d\n", bad, tot);
  return bad ? 1 : 0;
}
int main_unused() {
  int bad = 0;
  for (int t = 0; t < 200; ++t) {
    std::vector<uint32_t> src; int n = 20 + rand() % 200;
    for (int i = 0; i < n; ++i) { if (rand() % 17 == 0) src.push_back(kRestart); else src.push_back(rand() % 50); }
    Converted c; convert_until(c, src, src.size(), false);
    auto r = ref_tris(src);
    if (c.out != r) { ++bad; if (bad <= 2) printf("mismatch t=%d out=%zu ref=%zu\n", t, c.out.size(), r.size()); }
  }
  printf("strip mismatches: %d / 200\n", bad);
  return 0;
}