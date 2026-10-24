// Minimal QR code encoder: byte mode, error correction level L, versions 1-6 (up to 134 bytes). Used for the
// import-page link in the launcher. Follows ISO/IEC 18004; picks the mask with the lowest simple penalty.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

namespace {

struct VerInfo { int data_cw, ec_cw, blocks; };
// level L: total data codewords, EC codewords per block, number of blocks
const VerInfo kVer[7] = {{0, 0, 0}, {19, 7, 1}, {34, 10, 1}, {55, 15, 1}, {80, 20, 1}, {108, 26, 1}, {136, 18, 2}};

uint8_t g_exp[512], g_log[256];
void init_gf() {
  static bool done = false;
  if (done) return;
  int x = 1;
  for (int i = 0; i < 255; ++i) {
    g_exp[i] = uint8_t(x);
    g_log[x] = uint8_t(i);
    x <<= 1;
    if (x & 0x100) x ^= 0x11D;
  }
  for (int i = 255; i < 512; ++i) g_exp[i] = g_exp[i - 255];
  done = true;
}
uint8_t gmul(uint8_t a, uint8_t b) { return (a && b) ? g_exp[g_log[a] + g_log[b]] : 0; }

std::vector<uint8_t> rs_remainder(const std::vector<uint8_t>& data, int degree) {
  std::vector<uint8_t> gen(size_t(degree), 0);
  gen[size_t(degree) - 1] = 1;
  uint8_t root = 1;
  for (int i = 0; i < degree; ++i) {
    for (int j = 0; j < degree; ++j) {
      gen[size_t(j)] = gmul(gen[size_t(j)], root);
      if (j + 1 < degree) gen[size_t(j)] ^= gen[size_t(j) + 1];
    }
    root = gmul(root, 2);
  }
  std::vector<uint8_t> rem(size_t(degree), 0);
  for (uint8_t b : data) {
    uint8_t factor = b ^ rem[0];
    rem.erase(rem.begin());
    rem.push_back(0);
    for (int i = 0; i < degree; ++i) rem[size_t(i)] ^= gmul(gen[size_t(i)], factor);
  }
  return rem;
}

struct Matrix {
  int n;
  std::vector<uint8_t> m, fn;  // module value, is-function-module
  explicit Matrix(int size) : n(size), m(size_t(size) * size, 0), fn(size_t(size) * size, 0) {}
  void set(int x, int y, bool v, bool func = true) {
    m[size_t(y) * n + x] = v;
    if (func) fn[size_t(y) * n + x] = 1;
  }
  bool get(int x, int y) const { return m[size_t(y) * n + x]; }
  bool is_fn(int x, int y) const { return fn[size_t(y) * n + x]; }
};

void finder(Matrix& q, int cx, int cy) {
  for (int dy = -4; dy <= 4; ++dy)
    for (int dx = -4; dx <= 4; ++dx) {
      int x = cx + dx, y = cy + dy;
      if (x < 0 || y < 0 || x >= q.n || y >= q.n) continue;
      int d = std::max(dx < 0 ? -dx : dx, dy < 0 ? -dy : dy);
      q.set(x, y, d != 2 && d != 4);
    }
}

void alignment(Matrix& q, int cx, int cy) {
  for (int dy = -2; dy <= 2; ++dy)
    for (int dx = -2; dx <= 2; ++dx) {
      int d = std::max(dx < 0 ? -dx : dx, dy < 0 ? -dy : dy);
      q.set(cx + dx, cy + dy, d != 1);
    }
}

void format_bits(Matrix& q, int mask) {
  int data = (1 << 3) | mask;  // ECC level L = 01
  int rem = data;
  for (int i = 0; i < 10; ++i) rem = (rem << 1) ^ ((rem >> 9) * 0x537);
  int bits = ((data << 10) | rem) ^ 0x5412;
  auto bit = [&](int i) { return ((bits >> i) & 1) != 0; };
  for (int i = 0; i <= 5; ++i) q.set(8, i, bit(i));
  q.set(8, 7, bit(6));
  q.set(8, 8, bit(7));
  q.set(7, 8, bit(8));
  for (int i = 9; i < 15; ++i) q.set(14 - i, 8, bit(i));
  for (int i = 0; i < 8; ++i) q.set(q.n - 1 - i, 8, bit(i));
  for (int i = 8; i < 15; ++i) q.set(8, q.n - 15 + i, bit(i));
  q.set(8, q.n - 8, true);  // dark module
}

bool mask_bit(int mask, int x, int y) {
  switch (mask) {
    case 0: return (x + y) % 2 == 0;
    case 1: return y % 2 == 0;
    case 2: return x % 3 == 0;
    case 3: return (x + y) % 3 == 0;
    case 4: return (x / 3 + y / 2) % 2 == 0;
    case 5: return x * y % 2 + x * y % 3 == 0;
    case 6: return (x * y % 2 + x * y % 3) % 2 == 0;
    default: return ((x + y) % 2 + x * y % 3) % 2 == 0;
  }
}

int penalty(const Matrix& q) {
  int p = 0;
  for (int pass = 0; pass < 2; ++pass)
    for (int a = 0; a < q.n; ++a) {
      int run = 1;
      for (int b = 1; b < q.n; ++b) {
        bool cur = pass ? q.get(a, b) : q.get(b, a), prev = pass ? q.get(a, b - 1) : q.get(b - 1, a);
        if (cur == prev) {
          if (++run == 5) p += 3;
          else if (run > 5) p += 1;
        } else {
          run = 1;
        }
      }
    }
  int dark = 0;
  for (uint8_t v : q.m) dark += v;
  int pct = dark * 100 / int(q.m.size());
  p += (pct > 50 ? pct - 50 : 50 - pct) / 5 * 10;
  return p;
}

}  // namespace

// Encodes `text`; on success fills `modules` (size*size, 1 = dark) and returns the side length, else 0.
int ps5_qr_encode(const char* text, std::vector<uint8_t>* modules) {
  init_gf();
  const int len = int(std::strlen(text));
  int ver = 0;
  for (int v = 1; v <= 6; ++v)
    if (len + 2 <= kVer[v].data_cw) { ver = v; break; }
  if (!ver) return 0;
  const VerInfo vi = kVer[ver];

  std::vector<uint8_t> bits;
  auto put = [&](unsigned val, int count) { for (int i = count - 1; i >= 0; --i) bits.push_back(uint8_t((val >> i) & 1)); };
  put(4, 4);
  put(unsigned(len), 8);
  for (int i = 0; i < len; ++i) put(uint8_t(text[i]), 8);
  const int cap = vi.data_cw * 8;
  for (int i = 0; i < 4 && int(bits.size()) < cap; ++i) bits.push_back(0);
  while (bits.size() % 8) bits.push_back(0);
  std::vector<uint8_t> data;
  for (size_t i = 0; i < bits.size(); i += 8) {
    uint8_t b = 0;
    for (int j = 0; j < 8; ++j) b = uint8_t((b << 1) | bits[i + size_t(j)]);
    data.push_back(b);
  }
  for (uint8_t pad = 0xEC; int(data.size()) < vi.data_cw; pad ^= 0xEC ^ 0x11) data.push_back(pad);

  // split into blocks, add EC, interleave
  const int per = vi.data_cw / vi.blocks;
  std::vector<std::vector<uint8_t>> blk, ecc;
  for (int b = 0; b < vi.blocks; ++b) {
    blk.emplace_back(data.begin() + b * per, data.begin() + (b + 1) * per);
    ecc.push_back(rs_remainder(blk.back(), vi.ec_cw));
  }
  std::vector<uint8_t> all;
  for (int i = 0; i < per; ++i) for (int b = 0; b < vi.blocks; ++b) all.push_back(blk[size_t(b)][size_t(i)]);
  for (int i = 0; i < vi.ec_cw; ++i) for (int b = 0; b < vi.blocks; ++b) all.push_back(ecc[size_t(b)][size_t(i)]);

  const int n = 17 + 4 * ver;
  Matrix base(n);
  finder(base, 3, 3);
  finder(base, n - 4, 3);
  finder(base, 3, n - 4);
  for (int i = 8; i < n - 8; ++i) {
    base.set(i, 6, i % 2 == 0);
    base.set(6, i, i % 2 == 0);
  }
  if (ver >= 2) alignment(base, n - 7, n - 7);
  format_bits(base, 0);  // reserve the format areas

  Matrix best = base;
  int best_pen = 1 << 30;
  for (int mask = 0; mask < 8; ++mask) {
    Matrix q = base;
    size_t bit = 0;
    for (int right = n - 1; right >= 1; right -= 2) {
      if (right == 6) right = 5;
      for (int vert = 0; vert < n; ++vert)
        for (int j = 0; j < 2; ++j) {
          int x = right - j;
          bool upward = ((right + 1) & 2) == 0;
          int y = upward ? n - 1 - vert : vert;
          if (q.is_fn(x, y)) continue;
          bool v = bit < all.size() * 8 && ((all[bit >> 3] >> (7 - (bit & 7))) & 1);
          ++bit;
          q.set(x, y, v ^ mask_bit(mask, x, y), false);
        }
    }
    format_bits(q, mask);
    int pen = penalty(q);
    if (pen < best_pen) { best_pen = pen; best = q; }
  }
  *modules = best.m;
  return n;
}
