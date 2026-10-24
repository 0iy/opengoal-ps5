#include <cstdio>
#include <vector>
#include <cstdint>
int ps5_qr_encode(const char*, std::vector<uint8_t>*);
int main(int argc, char** argv) {
  std::vector<uint8_t> m;
  int n = ps5_qr_encode(argv[1], &m);
  std::printf("%d\n", n);
  for (int y = 0; y < n; ++y) { for (int x = 0; x < n; ++x) std::putchar(m[size_t(y) * n + x] ? '1' : '0'); std::putchar('\n'); }
}