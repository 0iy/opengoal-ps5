// Minimal raw-deflate (RFC 1951) decoder, one shot: no zlib dependency (the console build links zstd, not zlib).
// Table driven (one lookup per symbol), about 150-300 MB/s on a modern core. Host-tested against Python zlib in tests_install_host.sh.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace ps5inst {

class Inflate {
 public:
  // Decodes the deflate stream src[0..n) into dst (capacity cap). Returns the number of bytes produced or -1 on any error
  // (bad stream, output larger than cap, truncated input).
  long run(const uint8_t* src, size_t n, uint8_t* dst, size_t cap) {
    p_ = src; end_ = src + n; bb_ = 0; nb_ = 0; err_ = false;
    uint8_t* o = dst;
    base_ = dst;
    uint8_t* const oend = dst + cap;
    bool last = false;
    while (!last && !err_) {
      need(3);
      last = bits(1) != 0;
      const unsigned type = bits(2);
      if (type == 0) {
        bb_ >>= (nb_ & 7); nb_ -= nb_ & 7;  // to the byte boundary
        need(32);
        if (err_) return -1;
        const unsigned len = bits(16), nlen = bits(16);
        if ((len ^ 0xFFFFu) != nlen || !copy_stored(o, oend, len)) return -1;
      } else if (type == 1) {
        fixed();
        if (!codes(o, oend)) return -1;
      } else if (type == 2) {
        if (!dynamic() || !codes(o, oend)) return -1;
      } else {
        return -1;
      }
    }
    return err_ ? -1 : long(o - dst);
  }

 private:
  struct Huff {
    uint16_t tab[1 << 15];  // (symbol << 4) | length, 0 = invalid
    int bits = 0;
  };
  const uint8_t *p_ = nullptr, *end_ = nullptr;
  uint64_t bb_ = 0;
  int nb_ = 0;
  bool err_ = false;
  Huff lit_, dist_;

  void need(int n) {
    while (nb_ < n) {
      if (p_ >= end_) { if (nb_ < n) { err_ = true; } return; }
      bb_ |= uint64_t(*p_++) << nb_;
      nb_ += 8;
    }
  }
  void refill() {
    while (nb_ <= 56 && p_ < end_) { bb_ |= uint64_t(*p_++) << nb_; nb_ += 8; }
  }
  unsigned bits(int n) {
    if (nb_ < n) { need(n); if (err_) return 0; }
    const unsigned v = unsigned(bb_ & ((1ull << n) - 1));
    bb_ >>= n; nb_ -= n;
    return v;
  }

  // stored block data: first the whole bytes still in the bit buffer, then the input
  bool copy_stored(uint8_t*& o, uint8_t* oend, unsigned len) {
    if (size_t(oend - o) < len) return false;
    while (len && nb_ >= 8) { *o++ = uint8_t(bb_); bb_ >>= 8; nb_ -= 8; --len; }
    if (size_t(end_ - p_) < len) return false;
    std::memcpy(o, p_, len); o += len; p_ += len;
    return true;
  }

  static bool build(Huff& h, const uint8_t* lens, int n) {
    int count[16] = {0};
    for (int i = 0; i < n; ++i) ++count[lens[i]];
    count[0] = 0;
    int maxb = 0, left = 1;
    for (int l = 1; l < 16; ++l) {
      left = (left << 1) - count[l];
      if (left < 0) return false;  // over-subscribed
      if (count[l]) maxb = l;
    }
    h.bits = maxb ? maxb : 1;
    std::memset(h.tab, 0, sizeof(uint16_t) << h.bits);
    unsigned next[16] = {0}, code = 0;
    for (int l = 1; l < 16; ++l) { code = (code + count[l - 1]) << 1; next[l] = code; }
    for (int s = 0; s < n; ++s) {
      const int l = lens[s];
      if (!l) continue;
      unsigned c = next[l]++, r = 0;
      for (int i = 0; i < l; ++i) { r = (r << 1) | (c & 1); c >>= 1; }
      for (unsigned i = r; i < (1u << h.bits); i += 1u << l) h.tab[i] = uint16_t((s << 4) | l);
    }
    return true;
  }

  void fixed() {
    uint8_t l[288 + 30];
    for (int i = 0; i < 144; ++i) l[i] = 8;
    for (int i = 144; i < 256; ++i) l[i] = 9;
    for (int i = 256; i < 280; ++i) l[i] = 7;
    for (int i = 280; i < 288; ++i) l[i] = 8;
    build(lit_, l, 288);
    for (int i = 0; i < 30; ++i) l[i] = 5;
    build(dist_, l, 30);
  }

  bool dynamic() {
    need(14);
    const int hlit = int(bits(5)) + 257, hdist = int(bits(5)) + 1, hclen = int(bits(4)) + 4;
    if (err_ || hlit > 286 || hdist > 30) return false;
    static const uint8_t order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    uint8_t cl[19] = {0};
    for (int i = 0; i < hclen; ++i) { need(3); cl[order[i]] = uint8_t(bits(3)); }
    if (err_) return false;
    Huff& c = dist_;  // scratch: the code-length code lives in dist_ until the real tables are built
    if (!build(c, cl, 19)) return false;
    uint8_t lens[286 + 30] = {0};
    int i = 0;
    while (i < hlit + hdist) {
      refill();
      const unsigned e = c.tab[bb_ & ((1u << c.bits) - 1)];
      const int l = e & 15;
      if (!l || l > nb_) return false;
      bb_ >>= l; nb_ -= l;
      const int sym = e >> 4;
      if (sym < 16) { lens[i++] = uint8_t(sym); continue; }
      int rep, val = 0;
      if (sym == 16) { if (!i) return false; val = lens[i - 1]; need(2); rep = 3 + int(bits(2)); }
      else if (sym == 17) { need(3); rep = 3 + int(bits(3)); }
      else { need(7); rep = 11 + int(bits(7)); }
      if (err_ || i + rep > hlit + hdist) return false;
      while (rep--) lens[i++] = uint8_t(val);
    }
    if (!lens[256]) return false;  // no end-of-block code
    return build(lit_, lens, hlit) && build(dist_, lens + hlit, hdist);
  }

  bool codes(uint8_t*& o, uint8_t* oend) {
    static const uint16_t lbase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
    static const uint8_t lext[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
    static const uint16_t dbase[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
    static const uint8_t dext[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};
    const unsigned lmask = (1u << lit_.bits) - 1, dmask = (1u << dist_.bits) - 1;
    for (;;) {
      refill();
      unsigned e = lit_.tab[bb_ & lmask];
      int l = e & 15;
      if (!l || l > nb_) return false;
      bb_ >>= l; nb_ -= l;
      const int sym = int(e >> 4);
      if (sym < 256) {
        if (o >= oend) return false;
        *o++ = uint8_t(sym);
        continue;
      }
      if (sym == 256) return true;
      const int li = sym - 257;
      if (li >= 29) return false;
      refill();
      int len = lbase[li];
      if (lext[li]) { if (nb_ < lext[li]) return false; len += int(bb_ & ((1u << lext[li]) - 1)); bb_ >>= lext[li]; nb_ -= lext[li]; }
      e = dist_.tab[bb_ & dmask];
      l = e & 15;
      if (!l || l > nb_) return false;
      bb_ >>= l; nb_ -= l;
      const int ds = int(e >> 4);
      if (ds >= 30) return false;
      refill();
      unsigned dist = dbase[ds];
      if (dext[ds]) { if (nb_ < dext[ds]) return false; dist += unsigned(bb_ & ((1u << dext[ds]) - 1)); bb_ >>= dext[ds]; nb_ -= dext[ds]; }
      if (dist > size_t(o - base_) || size_t(oend - o) < size_t(len)) return false;
      const uint8_t* s = o - dist;
      for (int k = 0; k < len; ++k) o[k] = s[k];  // may overlap
      o += len;
    }
  }
  const uint8_t* base_ = nullptr;
};

}  // namespace ps5inst
