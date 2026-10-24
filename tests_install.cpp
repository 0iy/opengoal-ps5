// Host test of ps5shim/install_stream.h (+ inflate_lite.h). usage: tests_install STREAM CHUNK
// Feeds the stream in pieces of CHUNK bytes (0 = random sizes), prints "OK files bytes MB/s" and one "name size crc32" line per file,
// or "FAIL <error>". tests_install_host.sh compares the lines with what pc_import.py put into the stream.
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <set>

#include "install_stream.h"

struct MemSink : ps5inst::Sink {
  std::map<std::string, std::pair<uint64_t, uint32_t>> files;
  std::set<std::string> dirs;
  std::string cur;
  uint64_t n = 0;
  uint32_t crc = 0;
  bool make_dir(const std::string& r) override { dirs.insert(r); return true; }
  bool open_file(const std::string& r, uint64_t) override { cur = r; n = 0; crc = 0; return true; }
  bool write(const char* p, size_t k) override {
    crc = ps5inst::crc32_update(crc, reinterpret_cast<const uint8_t*>(p), k);
    n += k;
    return true;
  }
  bool close_file() override { files[cur] = {n, crc}; return true; }
};

int main(int argc, char** argv) {
  if (argc < 3) return 2;
  FILE* f = std::fopen(argv[1], "rb");
  if (!f) return 2;
  std::vector<char> d;
  char b[1 << 16];
  size_t k;
  while ((k = std::fread(b, 1, sizeof b, f)) > 0) d.insert(d.end(), b, b + k);
  std::fclose(f);
  const size_t chunk = std::strtoul(argv[2], nullptr, 10);
  MemSink s;
  ps5inst::Receiver r(&s, 0);
  srand(1);
  const auto t0 = std::chrono::steady_clock::now();
  bool ok = true;
  for (size_t pos = 0; pos < d.size() && ok;) {
    size_t n = chunk ? chunk : size_t(1 + rand() % 70000);
    if (n > d.size() - pos) n = d.size() - pos;
    ok = r.feed(d.data() + pos, n);
    pos += n;
  }
  const double dt = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  if (!ok || !r.finished()) {
    std::printf("FAIL %s\n", ok ? "unfinished" : r.error());
    return 1;
  }
  std::printf("OK %llu %llu %.0f\n", (unsigned long long)r.files(), (unsigned long long)r.raw_done(), double(r.raw_done()) / dt / 1048576.0);
  for (const auto& e : s.files) std::printf("%s %llu %08x\n", e.first.c_str(), (unsigned long long)e.second.first, e.second.second);
  for (const auto& e : s.dirs) std::printf("dir %s\n", e.c_str());
  return 0;
}
