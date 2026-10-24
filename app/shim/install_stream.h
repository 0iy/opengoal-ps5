// Receiver of the PC import stream (PUT /api/install, see docs/PC_IMPORT.md and installer/pc_import.py). Pure logic, no sockets:
// feed() takes the bytes as they arrive, decodes frames (raw / deflate), checks the CRC32 of the whole tar stream and unpacks the
// tar through a Sink while receiving. Host-tested by tests/host/install_host.sh with streams written by installer/pc_import.py.
//
// Wire format: "PS5IMP01", then frames {u32 codec, u32 clen, u32 rlen, payload[clen]} (little endian), codec 0 raw, 1 raw-deflate,
// 255 END (payload: u32 crc32 of all raw bytes, u64 raw byte count). The raw bytes are one ustar archive (files + dirs only).
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "inflate_lite.h"

namespace ps5inst {

struct Sink {
  virtual ~Sink() {}
  virtual bool make_dir(const std::string& rel) = 0;
  virtual bool open_file(const std::string& rel, uint64_t size) = 0;
  virtual bool write(const char* p, size_t n) = 0;
  virtual bool close_file() = 0;
};

inline uint32_t crc32_update(uint32_t crc, const uint8_t* p, size_t n) {
  static uint32_t t[4][256];
  static bool init = false;  // benign race: every thread computes the same values
  if (!init) {
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
      t[0][i] = c;
    }
    for (uint32_t i = 0; i < 256; ++i)
      for (int k = 1; k < 4; ++k) t[k][i] = (t[k - 1][i] >> 8) ^ t[0][t[k - 1][i] & 0xFF];
    init = true;
  }
  crc = ~crc;
  for (; n >= 4; n -= 4, p += 4) {
    crc ^= uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
    crc = t[3][crc & 0xFF] ^ t[2][(crc >> 8) & 0xFF] ^ t[1][(crc >> 16) & 0xFF] ^ t[0][crc >> 24];
  }
  while (n--) crc = (crc >> 8) ^ t[0][(crc ^ *p++) & 0xFF];
  return ~crc;
}

class Receiver {
 public:
  static constexpr uint32_t kMaxFrame = 16u << 20;
  Receiver(Sink* s, uint64_t max_raw) : sink_(s), max_raw_(max_raw) {}

  // false = failed, error() says why: "format" | "crc" | "io" | "size"
  bool feed(const char* d, size_t n) {
    const uint8_t* p = reinterpret_cast<const uint8_t*>(d);
    while (n && !failed()) {
      if (st_ == DONE) return fail("format");  // bytes after the END frame
      size_t take = need_ - acc_.size();
      if (take > n) take = n;
      if (acc_.empty() && take == need_) {  // whole unit in the input: no copy for headers
        if (!unit(p, take)) return false;
      } else {
        acc_.insert(acc_.end(), p, p + take);
        if (acc_.size() == need_) {
          std::vector<uint8_t> u;
          u.swap(acc_);
          if (!unit(u.data(), u.size())) return false;
        }
      }
      p += take; n -= take;
    }
    return !failed();
  }
  bool finished() const { return st_ == DONE && !failed(); }
  const char* error() const { return err_; }
  uint64_t raw_done() const { return raw_; }
  uint64_t files() const { return files_; }

 private:
  enum St { MAGIC, FHDR, PAYLOAD, DONE } st_ = MAGIC;
  Sink* sink_;
  uint64_t max_raw_, raw_ = 0, files_ = 0;
  uint32_t crc_ = 0, codec_ = 0, clen_ = 0, rlen_ = 0;
  size_t need_ = 8;
  std::vector<uint8_t> acc_, out_;
  const char* err_ = "";
  Inflate inf_;

  // tar state
  enum Tar { T_HDR, T_DATA, T_PAD, T_END } tar_ = T_HDR;
  uint8_t th_[512];
  size_t thn_ = 0;
  uint64_t left_ = 0, pad_ = 0;
  bool in_file_ = false;

  bool failed() const { return err_[0] != 0; }
  bool fail(const char* e) { if (!err_[0]) err_ = e; return false; }

  bool unit(const uint8_t* p, size_t n) {
    if (st_ == MAGIC) {
      if (std::memcmp(p, "PS5IMP01", 8) != 0) return fail("format");
      st_ = FHDR; need_ = 12;
    } else if (st_ == FHDR) {
      std::memcpy(&codec_, p, 4); std::memcpy(&clen_, p + 4, 4); std::memcpy(&rlen_, p + 8, 4);  // little endian host (x86-64)
      if (clen_ > kMaxFrame || rlen_ > kMaxFrame) return fail("format");
      if (codec_ == 255 ? clen_ != 12 : (codec_ > 1 || (codec_ == 0 && clen_ != rlen_))) return fail("format");
      if (clen_ == 0) return payload(p, 0);
      st_ = PAYLOAD; need_ = clen_;
    } else {
      return payload(p, n);
    }
    return true;
  }

  bool payload(const uint8_t* p, size_t n) {
    st_ = FHDR; need_ = 12;
    if (codec_ == 255) {
      uint32_t crc; uint64_t tot;
      std::memcpy(&crc, p, 4); std::memcpy(&tot, p + 4, 8);
      if (crc != crc_ || tot != raw_) return fail("crc");
      if (tar_ != T_HDR && tar_ != T_END) return fail("format");  // archive cut in the middle of an entry
      st_ = DONE; need_ = 1;
      return true;
    }
    const uint8_t* r = p;
    if (codec_ == 1) {
      out_.resize(rlen_);
      if (inf_.run(p, n, out_.data(), rlen_) != long(rlen_)) return fail("format");
      r = out_.data();
    }
    crc_ = crc32_update(crc_, r, rlen_);
    raw_ += rlen_;
    if (max_raw_ && raw_ > max_raw_) return fail("size");
    return tar(r, rlen_);
  }

  static uint64_t octal(const uint8_t* p, int n, bool* ok) {
    uint64_t v = 0;
    int i = 0;
    while (i < n && p[i] == ' ') ++i;
    for (; i < n && p[i] >= '0' && p[i] <= '7'; ++i) v = (v << 3) | uint64_t(p[i] - '0');
    for (; i < n; ++i) if (p[i] != 0 && p[i] != ' ') *ok = false;
    return v;
  }

  static bool safe(const std::string& s) {
    if (s.empty() || s.size() > 200 || s[0] == '/') return false;
    size_t b = 0;
    while (b <= s.size()) {
      size_t e = s.find('/', b);
      if (e == std::string::npos) e = s.size();
      const std::string c = s.substr(b, e - b);
      if (c == ".." || c == "." || (c.empty() && e != s.size())) return false;
      if (c.size() > 100) return false;
      b = e + 1;
    }
    for (unsigned char ch : s) if (ch < 32 || ch == '\\' || ch == ':') return false;
    return true;
  }

  bool header() {
    bool zero = true;
    for (int i = 0; i < 512; ++i) if (th_[i]) { zero = false; break; }
    if (zero) { tar_ = T_END; return true; }
    uint32_t sum = 0;
    for (int i = 0; i < 512; ++i) sum += (i >= 148 && i < 156) ? ' ' : th_[i];
    bool ok = true;
    if (octal(th_ + 148, 8, &ok) != sum || !ok) return fail("format");
    std::string name(reinterpret_cast<const char*>(th_), strnlen(reinterpret_cast<const char*>(th_), 100));
    const uint64_t size = octal(th_ + 124, 12, &ok);
    if (!ok) return fail("format");
    while (!name.empty() && name.back() == '/') name.pop_back();
    if (!safe(name)) return fail("format");
    const char type = char(th_[156]);
    if (type == '5') {
      if (!sink_->make_dir(name)) return fail("io");
      tar_ = T_HDR;
    } else if (type == '0' || type == 0) {
      if (!sink_->open_file(name, size)) return fail("io");
      in_file_ = true; ++files_;
      left_ = size; pad_ = (512 - size % 512) % 512;
      tar_ = size ? T_DATA : (pad_ ? T_PAD : T_HDR);
      if (!size) { in_file_ = false; if (!sink_->close_file()) return fail("io"); }
    } else {
      return fail("format");  // links, devices, pax headers ...
    }
    return true;
  }

  bool tar(const uint8_t* p, size_t n) {
    while (n) {
      if (tar_ == T_END) {  // only zero blocks may follow the end marker
        for (size_t i = 0; i < n; ++i) if (p[i]) return fail("format");
        return true;
      }
      if (tar_ == T_HDR) {
        const size_t t = std::min<size_t>(512 - thn_, n);
        std::memcpy(th_ + thn_, p, t);
        thn_ += t; p += t; n -= t;
        if (thn_ == 512) { thn_ = 0; if (!header()) return false; }
      } else if (tar_ == T_DATA) {
        const size_t t = size_t(std::min<uint64_t>(left_, n));
        if (!sink_->write(reinterpret_cast<const char*>(p), t)) return fail("io");
        p += t; n -= t; left_ -= t;
        if (!left_) {
          in_file_ = false;
          if (!sink_->close_file()) return fail("io");
          tar_ = pad_ ? T_PAD : T_HDR;
        }
      } else {  // T_PAD
        const size_t t = size_t(std::min<uint64_t>(pad_, n));
        p += t; n -= t; pad_ -= t;
        if (!pad_) tar_ = T_HDR;
      }
    }
    return true;
  }
};

}  // namespace ps5inst
