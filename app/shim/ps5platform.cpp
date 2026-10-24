#include <pthread.h>
#include <vector>
#include <utility>
#include <algorithm>
// PS5 platform layer for the OpenGOAL port: logging, audio (cubeb replacement), and stubs for the
// desktop-only libraries (curl, Discord RPC, tinyfiledialogs, zstd tracing).

#include <arpa/inet.h>
#include <dirent.h>
#include <signal.h>
#include <netinet/tcp.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#include "third-party/cubeb/cubeb/include/cubeb/cubeb.h"

extern "C" {
int sceKernelUsleep(unsigned int);
int sceUserServiceGetInitialUser(int*);
int sceAudioOutInit(void);
int sceAudioOutOpen(int user, int type, int index, uint32_t len, uint32_t freq, uint32_t param);
int sceAudioOutOutput(int handle, const void* ptr);
int sceAudioOutClose(int handle);
}

// ---------------------------------------------------------------------------------------------
// Logging: every line goes to a log file and out as broadcast UDP (port 9999) for the dev PC.
// ---------------------------------------------------------------------------------------------
void ps5_log(const char* fmt, ...);
namespace {
std::mutex g_log_mutex;
int g_log_sock = -1;
sockaddr_in g_log_dst{};
FILE* g_log_file = nullptr;

void log_open() {
  if (g_log_sock >= 0) return;
  g_log_sock = socket(AF_INET, SOCK_DGRAM, 0);
  int yes = 1;
  setsockopt(g_log_sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof yes);
  g_log_dst.sin_family = AF_INET;
  g_log_dst.sin_port = htons(9999);
  inet_pton(AF_INET, "255.255.255.255", &g_log_dst.sin_addr);
  g_log_file = std::fopen("/data/opengoal/log/ps5.log", "a");
}

// Reverse debug channel: the app dials out to the dev PC (TCP 9998, host from config/debughost.txt, default below), so it
// still works when the console's FTP/ELF-loader servers are dead. Line protocol; log lines go out as "L <text>".
// Commands: ping | ver | ls <dir> | get <path> | put <path> <size> (+bytes) | rm <path> | tail <path> <bytes> | exit
std::mutex g_dbg_mutex;
std::atomic<int> g_dbg_fd{-1};
std::atomic<bool> g_dbg_started{false};

std::mutex g_shot_mutex;
std::condition_variable g_shot_cv;
std::atomic<bool> g_shot_req{false};
std::atomic<int> g_shot_div{2};
std::atomic<bool> g_shot_screen{false};
bool g_shot_ready = false;
std::string g_shot;

extern "C" void ps5_glfix_set_limit(int);
extern "C" void ps5_glfix_trace();
extern "C" void ps5_pad_inject(unsigned buttons, unsigned ms);
extern "C" bool ps5_import_start(const char* game, const char* iso, const char* project);
extern "C" int ps5_import_state();
extern "C" int ps5_import_rc();
extern "C" void ps5_stick_inject(unsigned lx, unsigned ly, unsigned ms);
extern "C" void ps5_glfix_set_skip(int);
extern "C" void ps5_glfix_set_skip_range(int, int);
extern "C" int ps5_glfix_dump_prog(int);
extern "C" unsigned ps5_glfix_draw_total();
inline const char* chr_nl() { return "\n"; }
bool dbg_send_all(int fd, const void* p, size_t n) {
  const char* c = static_cast<const char*>(p);
  while (n) {
    ssize_t w = send(fd, c, n, 0);
    if (w <= 0) return false;
    c += w;
    n -= size_t(w);
  }
  return true;
}
bool dbg_reply(int fd, const std::string& s) { return dbg_send_all(fd, s.data(), s.size()); }
bool dbg_recv_all(int fd, void* p, size_t n) {
  char* c = static_cast<char*>(p);
  while (n) {
    ssize_t r = recv(fd, c, n, 0);
    if (r <= 0) return false;
    c += r;
    n -= size_t(r);
  }
  return true;
}

bool dbg_handle(int fd, const std::string& line) {
  std::lock_guard<std::mutex> lk(g_dbg_mutex);
  auto arg = [&](size_t skip) { return line.size() > skip ? line.substr(skip) : std::string(); };
  if (line.rfind("shot", 0) == 0) {
    g_shot_screen = line.find(" screen") != std::string::npos;
    g_shot_div = line.size() > 5 ? std::max(1, std::atoi(line.c_str() + 5)) : 2;  // grab the next rendered frame; the render thread fills g_shot via ps5_dbg_shot_deliver
    std::unique_lock<std::mutex> sl(g_shot_mutex);
    g_shot_ready = false;
    g_shot_req = true;
    if (!g_shot_cv.wait_for(sl, std::chrono::seconds(5), [] { return g_shot_ready; })) {
      g_shot_req = false;
      return dbg_reply(fd, "E no frame within 5 s (game not rendering?)\n");
    }
    if (!dbg_reply(fd, "B " + std::to_string(g_shot.size()) + "\n")) return false;
    return dbg_send_all(fd, g_shot.data(), g_shot.size());
  }
  if (line.rfind("mem ", 0) == 0) {  // mem <hexaddr> <len>: raw read of process memory (debug only)
    unsigned long long a = std::strtoull(line.c_str() + 4, nullptr, 16);
    const char* sp = std::strchr(line.c_str() + 4, ' ');
    size_t n = sp ? size_t(std::atol(sp + 1)) : 64;
    if (!dbg_reply(fd, "B " + std::to_string(n) + "\n")) return false;
    return dbg_send_all(fd, reinterpret_cast<const void*>(a), n);
  }
  if (line.rfind("limit ", 0) == 0) {
    ps5_glfix_set_limit(std::atoi(line.c_str() + 6));
    return dbg_reply(fd, "R draws/frame=" + std::to_string(ps5_glfix_draw_total()) + chr_nl());
  }
  if (line.rfind("dumpprog ", 0) == 0) { int n = ps5_glfix_dump_prog(std::atoi(line.c_str() + 9)); return dbg_reply(fd, "R dumpprog shaders=" + std::to_string(n) + std::string(chr_nl())); }
  if (line.rfind("skiprange ", 0) == 0) { int a = 0, b = 0; std::sscanf(line.c_str() + 10, "%d %d", &a, &b); ps5_glfix_set_skip_range(a, b); return dbg_reply(fd, "R skiprange " + std::to_string(a) + " " + std::to_string(b) + std::string(chr_nl())); }
  if (line.rfind("skip ", 0) == 0) { ps5_glfix_set_skip(std::atoi(line.c_str() + 5)); return dbg_reply(fd, "R draws/frame=" + std::to_string(ps5_glfix_draw_total()) + std::string(chr_nl())); }
  if (line.rfind("stick ", 0) == 0) { unsigned lx = 128, ly = 128, ms = 0; std::sscanf(line.c_str() + 6, "%u %u %u", &lx, &ly, &ms); ps5_stick_inject(lx, ly, ms); return dbg_reply(fd, "R stick" + std::string(chr_nl())); }
  if (line.rfind("import ", 0) == 0) { char game[16] = {0}, iso[512] = {0}; std::sscanf(line.c_str() + 7, "%15s %511s", game, iso); std::string proj = std::string("/data/opengoal/proj_") + game; bool ok = ps5_import_start(game, iso, proj.c_str()); return dbg_reply(fd, std::string(ok ? "R import started " : "R import busy ") + proj + std::string(chr_nl())); }
  if (line == "importstate") { return dbg_reply(fd, "R import state=" + std::to_string(ps5_import_state()) + " rc=" + std::to_string(ps5_import_rc()) + std::string(chr_nl())); }
  if (line.rfind("mark ", 0) == 0) { ps5_log("mark: %s", line.c_str() + 5); return dbg_reply(fd, "R mark" + std::string(chr_nl())); }
  if (line.rfind("press ", 0) == 0) { unsigned btn = 0, ms = 0; std::sscanf(line.c_str() + 6, "%x %u", &btn, &ms); ps5_pad_inject(btn, ms); return dbg_reply(fd, "R press" + std::string(chr_nl())); }
  if (line == "trace") { ps5_glfix_trace(); return dbg_reply(fd, "R tracing next frame" + std::string(chr_nl())); }
  if (line == "ping") return dbg_reply(fd, "R pong\n");
  if (line == "ver") return dbg_reply(fd, "R opengoal-ps5 dbg v1\n");
  if (line == "exit") {
    dbg_reply(fd, "R bye\n");
    _exit(0);
  }
  if (line.rfind("ls ", 0) == 0) {
    DIR* d = opendir(arg(3).c_str());
    if (!d) return dbg_reply(fd, "E opendir failed\n");
    std::string out;
    while (dirent* e = readdir(d)) {
      struct stat st{};
      std::string full = arg(3) + "/" + e->d_name;
      stat(full.c_str(), &st);
      out += std::string(e->d_name) + " " + std::to_string((long long)st.st_size) + (S_ISDIR(st.st_mode) ? " d\n" : "\n");
    }
    closedir(d);
    if (!dbg_reply(fd, "B " + std::to_string(out.size()) + "\n")) return false;
    return dbg_send_all(fd, out.data(), out.size());
  }
  if (line.rfind("get ", 0) == 0) {
    FILE* f = std::fopen(arg(4).c_str(), "rb");
    if (!f) return dbg_reply(fd, "E open failed\n");
    std::fseek(f, 0, SEEK_END);
    long sz = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (!dbg_reply(fd, "B " + std::to_string(sz) + "\n")) { std::fclose(f); return false; }
    std::vector<char> buf(1 << 16);
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), f)) > 0)
      if (!dbg_send_all(fd, buf.data(), n)) { std::fclose(f); return false; }
    std::fclose(f);
    return true;
  }
  if (line.rfind("tail ", 0) == 0) {
    std::string rest = arg(5);
    size_t sp = rest.rfind(' ');
    if (sp == std::string::npos) return dbg_reply(fd, "E usage: tail <path> <bytes>\n");
    long want = std::atol(rest.c_str() + sp + 1);
    FILE* f = std::fopen(rest.substr(0, sp).c_str(), "rb");
    if (!f) return dbg_reply(fd, "E open failed\n");
    std::fseek(f, 0, SEEK_END);
    long sz = std::ftell(f);
    long start = sz > want ? sz - want : 0;
    std::fseek(f, start, SEEK_SET);
    std::vector<char> buf(size_t(sz - start));
    size_t n = std::fread(buf.data(), 1, buf.size(), f);
    std::fclose(f);
    if (!dbg_reply(fd, "B " + std::to_string(n) + "\n")) return false;
    return dbg_send_all(fd, buf.data(), n);
  }
  if (line.rfind("rm ", 0) == 0) return dbg_reply(fd, std::remove(arg(3).c_str()) == 0 ? "R ok\n" : "E remove failed\n");
  if (line.rfind("put ", 0) == 0) {
    std::string rest = arg(4);
    size_t sp = rest.rfind(' ');
    if (sp == std::string::npos) return dbg_reply(fd, "E usage: put <path> <size>\n");
    size_t size = size_t(std::atoll(rest.c_str() + sp + 1));
    std::string path = rest.substr(0, sp);
    std::vector<char> buf(size);
    if (!dbg_recv_all(fd, buf.data(), size)) return false;
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return dbg_reply(fd, "E open failed\n");
    std::fwrite(buf.data(), 1, size, f);
    std::fclose(f);
    return dbg_reply(fd, "R ok\n");
  }
  return dbg_reply(fd, "E unknown command\n");
}

void dbg_thread() {
  signal(SIGPIPE, SIG_IGN);
  for (;;) {
    std::string host;  // dev channel is opt-in: only when config/debughost.txt names the PC
    if (FILE* hf = std::fopen("/data/opengoal/config/debughost.txt", "r")) {
      char b[64] = {};
      if (std::fgets(b, sizeof b, hf)) {
        std::string s(b);
        while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ')) s.pop_back();
        if (!s.empty()) host = s;
      }
      std::fclose(hf);
    }
    int fd = host.empty() ? -1 : socket(AF_INET, SOCK_STREAM, 0);
    if (fd >= 0) {
      sockaddr_in a{};
      a.sin_family = AF_INET;
      a.sin_port = htons(9998);
      inet_pton(AF_INET, host.c_str(), &a.sin_addr);
      timeval tv{15, 0};
      setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
      if (connect(fd, reinterpret_cast<sockaddr*>(&a), sizeof a) == 0) {
        int one = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        { std::lock_guard<std::mutex> lk(g_dbg_mutex); dbg_reply(fd, "R hello ps5 opengoal\n"); }
        g_dbg_fd = fd;
        std::string line;
        char c;
        bool ok = true;
        while (ok && recv(fd, &c, 1, 0) == 1) {
          if (c == '\n') { ok = dbg_handle(fd, line); line.clear(); }
          else if (c != '\r') line += c;
        }
        g_dbg_fd = -1;
      }
      close(fd);
    }
    sceKernelUsleep(3000000);
  }
}

void dbg_forward_log(const char* text, size_t len) {
  int fd = g_dbg_fd.load();
  if (fd < 0 || !len) return;
  if (!g_dbg_mutex.try_lock()) return;  // a command reply is in flight: drop this line
  std::string m = "L ";
  m.append(text, len);
  m += '\n';
  if (!dbg_send_all(fd, m.data(), m.size())) { g_dbg_fd = -1; shutdown(fd, 2); }
  g_dbg_mutex.unlock();
}

void log_line(const char* text, size_t len) {
  std::lock_guard<std::mutex> lock(g_log_mutex);
  log_open();
  if (!g_dbg_started.exchange(true)) std::thread(dbg_thread).detach();
  dbg_forward_log(text, len);
  if (g_log_sock >= 0 && len) sendto(g_log_sock, text, len, 0, reinterpret_cast<sockaddr*>(&g_log_dst), sizeof g_log_dst);
  if (g_log_file) {
    std::fwrite(text, 1, len, g_log_file);
    std::fputc('\n', g_log_file);
    std::fflush(g_log_file);
  }
}
}  // namespace

extern "C" bool ps5_dbg_shot_screen() { return g_shot_screen.load(); }
extern "C" bool ps5_dbg_shot_pending() { return g_shot_req.load(); }
extern "C" void ps5_dbg_shot_deliver(int w, int h, const unsigned char* rgb) {
  std::lock_guard<std::mutex> lk(g_shot_mutex);
  const int d = g_shot_div.load(), ow = w / d, oh = h / d;
  g_shot = "P6\n" + std::to_string(ow) + " " + std::to_string(oh) + "\n255\n";
  const size_t hdr = g_shot.size();
  g_shot.resize(hdr + size_t(ow) * oh * 3);
  for (int y = 0; y < oh; ++y)
    for (int x = 0; x < ow; ++x)
      std::memcpy(&g_shot[hdr + (size_t(y) * ow + x) * 3], rgb + (size_t(y) * d * w + size_t(x) * d) * 3, 3);
  g_shot_req = false;
  g_shot_ready = true;
  g_shot_cv.notify_all();
}

void ps5_log(const char* fmt, ...) {
  char buf[1024];
  va_list ap;
  va_start(ap, fmt);
  int n = std::vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if (static_cast<size_t>(n) >= sizeof buf) n = sizeof buf - 1;
  log_line(buf, static_cast<size_t>(n));
}

// ---------------------------------------------------------------------------------------------
// Crash handler: log the signal, fault address, registers and a frame-pointer backtrace.
// ---------------------------------------------------------------------------------------------
#include <signal.h>
#include <ucontext.h>

extern "C" void ps5_crash_handler(int sig, siginfo_t* si, void* uc_) {
  // The PS5 kernel's ucontext layout differs from the SDK header; offsets verified on hardware:
  // words[11]=rbp, [28]=rip, [31]=rsp (words[0..1] hold the signal mask).
  const uint64_t* words = static_cast<const uint64_t*>(uc_);
  uint64_t rip = words[28], rsp = words[31], rbp = words[11];
  ps5_log("CRASH sig=%d code=%d addr=%p rip=%llx rsp=%llx rbp=%llx (ps5_log@%p)", sig, si ? si->si_code : -1,
          si ? si->si_addr : nullptr, (unsigned long long)rip, (unsigned long long)rsp,
          (unsigned long long)rbp, (void*)&ps5_log);
  {
    const uint64_t* raw = reinterpret_cast<const uint64_t*>(uc_);
    char line[512];
    int off = 0;
    for (int i = 0; i < 44 && off < 480; ++i) off += std::snprintf(line + off, sizeof line - off, "%llx ", (unsigned long long)raw[i]);
    ps5_log("ucontext raw: %s", line);
  }
  // Poor man's backtrace: scan the stack for words that look like return addresses into the image.
  const uint64_t base = reinterpret_cast<uint64_t>(&ps5_log) & ~0xfffffull;
  const uint64_t lo = base > 0x4000000 ? base - 0x4000000 : 0x400000, hi = base + 0x4000000;
  const uint64_t* sp = reinterpret_cast<const uint64_t*>(rsp);
  int found = 0;
  for (int i = 0; i < 512 && found < 30 && rsp > 0x10000; ++i) {
    uint64_t v = sp[i];
    if (v >= lo && v < hi && v > 0x400000 && v < 0x3000000) {
      ps5_log("  stack[%d] %llx", i, (unsigned long long)v);
      ++found;
    }
  }
  sceKernelUsleep(400000);  // let the stdio forwarder drain the engine's last lines
  _exit(128 + sig);
}

// ---- optional sampling profiler (only when /data/opengoal/config/profile.txt exists) -------------------
static volatile uint64_t g_prof_samples[8192][3];
static volatile unsigned g_prof_n = 0;
static pthread_t g_prof_target;
static volatile bool g_prof_have_target = false;
static pthread_t g_main_thread;
static volatile bool g_prof_worker = false;

static void ps5_prof_handler(int, siginfo_t*, void* ctx) {
  const uint64_t* w = static_cast<const uint64_t*>(ctx);
  const unsigned i = g_prof_n;
  if (i < 8192) {
    const uint64_t rip = w[28], rsp = w[31], rbp = w[11];
    uint64_t r1 = 0, r2 = 0;
    // no frame pointers in the driver: take the first two stack words that look like return addresses into the image
    const uint64_t* sp = reinterpret_cast<const uint64_t*>(rsp);
    const int limit = g_prof_worker ? int((4096 - (rsp & 4095)) / 8) : 384;  // worker stacks are shallow: stay inside the current page
    for (int k = 0; k < limit && !(r1 && r2); ++k) {
      const uint64_t v = sp[k];
      if (v > 0x400000 && v < 0x2800000) (r1 ? r2 : r1) = v;
    }
    (void)rbp;
    g_prof_samples[i][0] = rip;
    g_prof_samples[i][1] = r1;
    g_prof_samples[i][2] = r2;
    g_prof_n = i + 1;
  }
}

// Called from the render thread every frame; the first call elects it as the thread to sample.
void ps5_log_import_addrs();
extern "C" unsigned long ps5_agc_async_thread(unsigned);
extern "C" void ps5_profile_tick() {
  static int ticks = 0;
  if (++ticks == 400) ps5_log_import_addrs();
  static bool started = false, follow = true;
  static int worker = -1;  // profile.txt "w0"/"w1": sample an async prep worker instead of the swapping thread
  if (started) {
    if (worker >= 0) { if (unsigned long t = ps5_agc_async_thread(unsigned(worker))) g_prof_target = reinterpret_cast<pthread_t>(t); }
    else if (follow) g_prof_target = pthread_self();  // the swapping thread changes at the launcher -> game handoff
    return;
  }
  if ((ticks & 31) != 0) return;  // look for the flag file twice a second, not every frame
  struct stat st;
  if (stat("/data/opengoal/config/profile.txt", &st) != 0) return;
  started = true;
  g_prof_target = pthread_self();
  if (FILE* pf = std::fopen("/data/opengoal/config/profile.txt", "r")) {  // "main" -> sample the thread that installed the crash handler
    char b[16] = {};
    if (std::fgets(b, sizeof b, pf) && b[0] == 'm') { g_prof_target = g_main_thread; follow = false; }
    else if (b[0] == 'w') { worker = b[1] - '0'; g_prof_worker = true; }
    std::fclose(pf);
  }
  g_prof_have_target = true;
  struct sigaction sa;
  std::memset(&sa, 0, sizeof sa);
  sa.sa_sigaction = ps5_prof_handler;
  sa.sa_flags = SA_SIGINFO | SA_RESTART;
  sigaction(SIGUSR1, &sa, nullptr);
  std::thread([] {
    for (;;) {
      for (int k = 0; k < 2000; ++k) {  // ~8 s at 250 Hz
        usleep(4000);
        pthread_kill(g_prof_target, SIGUSR1);
      }
      const unsigned n = g_prof_n < 8192 ? g_prof_n : 8192;
      // histogram by (rip block, caller, grand-caller)
      struct Key { uint64_t a, b, c; unsigned n; };
      std::vector<Key> h;
      for (unsigned i = 0; i < n; ++i) {
        const uint64_t a = g_prof_samples[i][0] >> 4, b = g_prof_samples[i][1], c = g_prof_samples[i][2];
        bool f = false;
        for (auto& e : h)
          if (e.a == a && e.b == b && e.c == c) { ++e.n; f = true; break; }
        if (!f) h.push_back({a, b, c, 1u});
      }
      std::sort(h.begin(), h.end(), [](const Key& x, const Key& y) { return x.n > y.n; });
      ps5_log("prof: %u samples", n);
      for (size_t i = 0; i < h.size() && i < 60; ++i)
        ps5_log("prof: %5u  %llx <- %llx <- %llx", h[i].n, (unsigned long long)(h[i].a << 4), (unsigned long long)h[i].b,
                (unsigned long long)h[i].c);
      g_prof_n = 0;
    }
  }).detach();
}

// Remote input script: /data/opengoal/config/inject.txt is read (and removed) twice a second. One command per line:
//   p <hexmask> <ms> <wait_ms>      press buttons        s <lx> <ly> <ms> <wait_ms>      move the left stick
//   w <ms>                          wait                 m <text>                        write a "mark:" log line
// Lets a remote PC drive the game over FTP when the debug channel cannot reach it.
static void ps5_inject_file_loop() {
  for (;;) {
    usleep(500000);
    FILE* f = std::fopen("/data/opengoal/config/inject.txt", "r");
    if (!f) continue;
    std::vector<std::string> lines;
    char buf[160];
    while (std::fgets(buf, sizeof buf, f)) lines.emplace_back(buf);
    std::fclose(f);
    std::remove("/data/opengoal/config/inject.txt");
    for (const std::string& l : lines) {
      unsigned a = 0, b = 0, c = 0, d = 0;
      if (l[0] == 'p' && std::sscanf(l.c_str() + 1, "%x %u %u", &a, &b, &c) >= 2) { ps5_pad_inject(a, b); usleep((b + c) * 1000u); }
      else if (l[0] == 's' && std::sscanf(l.c_str() + 1, "%u %u %u %u", &a, &b, &c, &d) >= 3) { ps5_stick_inject(a, b, c); usleep((c + d) * 1000u); }
      else if (l[0] == 'w' && std::sscanf(l.c_str() + 1, "%u", &a) == 1) usleep(a * 1000u);
      else if (l[0] == 'm') ps5_log("mark: %s", l.c_str() + 2);
    }
  }
}
void ps5_inject_file_start() { std::thread(ps5_inject_file_loop).detach(); }

void ps5_install_crash_handler() {
  g_main_thread = pthread_self();
  struct sigaction sa;
  std::memset(&sa, 0, sizeof sa);
  sa.sa_sigaction = ps5_crash_handler;
  sa.sa_flags = SA_SIGINFO;
  for (int sig : {SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT, SIGTRAP}) sigaction(sig, &sa, nullptr);
}

// Forward everything the engine prints to stdout/stderr (lg:: logging) to the same sinks.
static bool g_verbose_stdio = false;

// The prebuilt PS5 OpenGL library prints a diagnostic line (including index lists) for many draws. The link
// wraps printf so that, outside debug mode, those driver lines cost nothing.
extern "C" int __wrap_printf(const char* fmt, ...) {
  if (!g_verbose_stdio && fmt) {
    if (std::strncmp(fmt, "[ps5-", 5) == 0) {  // tagged driver lines: keep only the rare profile summaries
      static const char* const keep[] = {"[ps5-driver", "[ps5-map-caller", "[ps5-cpu-flush", "[ps5-batch",
                                         "[ps5-submit-perf", "[ps5-prepare-perf", "[ps5-present-perf",
                                         "[ps5-draw-gpu-time", "[ps5-deferred-batch", "[ps5-multidraw"};
      for (const char* k : keep)
        if (std::strncmp(fmt, k, std::strlen(k)) == 0) goto passthrough;
      return 0;
    }
    if (std::strcmp(fmt, "%s%u") == 0 || std::strcmp(fmt, "%s\n") == 0) return 0;       // index-list pieces
  }
passthrough:
  va_list ap;
  va_start(ap, fmt);
  const int n = std::vprintf(fmt, ap);
  va_end(ap);
  return n;
}

void ps5_capture_stdio() {
  // Normal play: only forward stdout/stderr when /data/opengoal/config/debug.txt exists.
  struct stat dbg;
  if (stat("/data/opengoal/config/debug.txt", &dbg) != 0) return;
  g_verbose_stdio = true;
  // The PS5 runtime shim (runtime_shims.c) already redirects stdout/stderr to /download0/ps5-opengl.log
  // (unbuffered). Tail that file and forward new lines to the log sinks.
  std::thread([] {
    char chunk[1024];
    std::string line;
    FILE* f = nullptr;
    for (;;) {
      if (!f) {
        f = std::fopen("/download0/ps5-opengl.log", "r");
        if (!f) {
          sceKernelUsleep(50000);
          continue;
        }
      }
      ssize_t n = static_cast<ssize_t>(std::fread(chunk, 1, sizeof chunk, f));
      if (n <= 0) {
        std::clearerr(f);
        sceKernelUsleep(20000);
        continue;
      }
      for (ssize_t i = 0; i < n; ++i) {
        if (chunk[i] == '\n') {
          log_line(line.data(), line.size());
          line.clear();
        } else if (line.size() < 900) {
          line.push_back(chunk[i]);
        }
      }
    }
  }).detach();
}

// ---------------------------------------------------------------------------------------------
// cubeb replacement on top of sceAudioOut (48 kHz stereo S16 is all OpenGOAL asks for).
// ---------------------------------------------------------------------------------------------
struct cubeb {
  int dummy;
};

struct cubeb_stream {
  cubeb_data_callback data_cb = nullptr;
  cubeb_state_callback state_cb = nullptr;
  void* user = nullptr;
  uint32_t rate = 48000;
  std::atomic<bool> running{false};
  std::atomic<bool> quit{false};
  std::thread worker;
  int handle = -1;
};

constexpr uint32_t kGrain = 256;  // frames per sceAudioOutOutput call

extern "C" {

int cubeb_init(cubeb** context, const char*, const char*) {
  *context = new cubeb{0};
  return CUBEB_OK;
}
void cubeb_destroy(cubeb* context) { delete context; }

int cubeb_get_min_latency(cubeb*, cubeb_stream_params*, uint32_t* latency_frames) {
  *latency_frames = kGrain;
  return CUBEB_OK;
}

int cubeb_stream_init(cubeb*, cubeb_stream** stream, const char*, cubeb_devid, cubeb_stream_params*,
                      cubeb_devid, cubeb_stream_params* output, unsigned int, cubeb_data_callback data_cb,
                      cubeb_state_callback state_cb, void* user) {
  auto* s = new cubeb_stream();
  s->data_cb = data_cb;
  s->state_cb = state_cb;
  s->user = user;
  s->rate = output ? output->rate : 48000;
  sceAudioOutInit();
  int uid = 0;
  sceUserServiceGetInitialUser(&uid);
  // type 0 = main port, param 1 = signed 16 bit stereo. The main port belongs to the system user (0xFF).
  s->handle = sceAudioOutOpen(0xFF, 0, 0, kGrain, s->rate, 1);
  ps5_log("audio: sceAudioOutOpen(system user) -> 0x%x", s->handle);
  if (s->handle < 0) {
    s->handle = sceAudioOutOpen(uid, 0, 0, kGrain, s->rate, 1);
    ps5_log("audio: sceAudioOutOpen(user 0x%x) -> 0x%x", uid, s->handle);
  }
  if (s->handle < 0) {
    s->handle = sceAudioOutOpen(0xFF, 1, 0, kGrain, s->rate, 1);  // background-music port
    ps5_log("audio: sceAudioOutOpen(bgm port) -> 0x%x", s->handle);
  }
  if (s->handle < 0) {
    delete s;
    return CUBEB_ERROR;
  }
  *stream = s;
  return CUBEB_OK;
}

int cubeb_stream_start(cubeb_stream* s) {
  if (s->running.exchange(true)) return CUBEB_OK;
  s->worker = std::thread([s] {
    int16_t buffer[kGrain * 2];
    int peak = 0, last_rc = 0;
    uint32_t calls = 0;
    while (!s->quit.load()) {
      std::memset(buffer, 0, sizeof buffer);
      if (s->running.load() && s->data_cb) s->data_cb(s, s->user, nullptr, buffer, kGrain);
      {  // diag: loudest sample per second, to tell silence from missing output
        for (uint32_t i = 0; i < kGrain * 2; ++i) { int v = buffer[i] < 0 ? -buffer[i] : buffer[i]; if (v > peak) peak = v; }
        if (++calls % 188 == 0) { ps5_log("audio: peak=%d over %u grains rc=%d", peak, calls, last_rc); peak = 0; }
      }
      last_rc = sceAudioOutOutput(s->handle, buffer);  // blocks for one grain of playback
    }
  });
  if (s->state_cb) s->state_cb(s, s->user, CUBEB_STATE_STARTED);
  return CUBEB_OK;
}

int cubeb_stream_stop(cubeb_stream* s) {
  s->running = false;
  if (s->state_cb) s->state_cb(s, s->user, CUBEB_STATE_STOPPED);
  return CUBEB_OK;
}

void cubeb_stream_destroy(cubeb_stream* s) {
  if (!s) return;
  s->running = false;
  s->quit = true;
  if (s->worker.joinable()) s->worker.join();
  if (s->handle >= 0) sceAudioOutClose(s->handle);
  delete s;
}

}  // extern "C"

// ---------------------------------------------------------------------------------------------
// Stubs for desktop-only dependencies.
// ---------------------------------------------------------------------------------------------
extern "C" {

// libcurl (update checks, downloads): always report "no network".
typedef void CURL;
int curl_global_init(long) { return 0; }
void curl_global_cleanup(void) {}
CURL* curl_easy_init(void) { return nullptr; }
void curl_easy_cleanup(CURL*) {}
int curl_easy_setopt(CURL*, int, ...) { return 0; }
int curl_easy_perform(CURL*) { return 7; }  // CURLE_COULDNT_CONNECT
const char* curl_easy_strerror(int) { return "network access is not available in the PS5 build"; }

// Discord rich presence.
void Discord_Initialize(const char*, void*, int, const char*) {}
void Discord_Shutdown(void) {}
void Discord_UpdatePresence(const void*) {}
void Discord_ClearPresence(void) {}

// tinyfiledialogs.
int tinyfd_messageBox(const char* title, const char* message, const char*, const char*, int) {
  ps5_log("messagebox: %s: %s", title ? title : "", message ? message : "");
  return 1;
}

// zstd tracing hooks (weak in zstd, referenced when tracing is compiled in).
unsigned long long ZSTD_trace_compress_begin(const void*) { return 0; }
void ZSTD_trace_compress_end(unsigned long long, const void*) {}
unsigned long long ZSTD_trace_decompress_begin(const void*) { return 0; }
void ZSTD_trace_decompress_end(unsigned long long, const void*) {}

}  // extern "C"

// ---------------------------------------------------------------------------------------------
// Fast monotonic clock. clock_gettime is a real syscall on the PS5 (about 30 % of a Jak 2 frame went into it: engine
// profiler nodes, frame limiter, driver profiling). The link wraps it; monotonic reads are served from the TSC,
// re-anchored to the kernel clock every 200 ms so rate drift stays bounded and time never goes backwards.
// ---------------------------------------------------------------------------------------------
#include <time.h>
extern "C" int __real_clock_gettime(clockid_t, struct timespec*);
namespace {
struct ClockAnchor {
  uint64_t tsc, ns;
  double ns_per_tick;
};
ClockAnchor g_clock[2];
std::atomic<unsigned> g_clock_idx{0};
std::atomic<uint64_t> g_clock_last{0};
std::atomic<bool> g_clock_busy{false};
int64_t g_clock_rt_offset = 0;
inline uint64_t rdtsc_now() {
  uint32_t lo, hi;
  __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
  return (uint64_t(hi) << 32) | lo;
}
uint64_t real_ns() {
  timespec ts;
  __real_clock_gettime(CLOCK_MONOTONIC, &ts);
  return uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
}
void clock_reanchor() {
  const ClockAnchor& old = g_clock[g_clock_idx.load()];
  ClockAnchor n;
  n.tsc = rdtsc_now();
  n.ns = real_ns();
  const double dt = double(n.tsc - old.tsc);
  n.ns_per_tick = (dt > 1e6 && n.ns > old.ns) ? double(n.ns - old.ns) / dt : old.ns_per_tick;
  const unsigned other = g_clock_idx.load() ^ 1u;
  g_clock[other] = n;
  g_clock_idx.store(other);
}
}  // namespace

extern "C" int __wrap_clock_gettime(clockid_t id, struct timespec* ts) {
  const bool realtime = id == CLOCK_REALTIME || id == 9 || id == 10;  // REALTIME, _PRECISE, _FAST
  if (!realtime && id != CLOCK_MONOTONIC && id != 11 /*MONOTONIC_PRECISE*/ && id != 12 /*MONOTONIC_FAST*/) return __real_clock_gettime(id, ts);
  static std::once_flag once;
  std::call_once(once, [] {
    g_clock[0].tsc = rdtsc_now();
    g_clock[0].ns = real_ns();
    sceKernelUsleep(20000);
    const uint64_t t1 = rdtsc_now(), n1 = real_ns();
    g_clock[0].ns_per_tick = double(n1 - g_clock[0].ns) / double(t1 - g_clock[0].tsc);
    g_clock[0].tsc = t1;
    g_clock[0].ns = n1;
    timespec rt;
    __real_clock_gettime(CLOCK_REALTIME, &rt);
    g_clock_rt_offset = int64_t(uint64_t(rt.tv_sec) * 1000000000ull + uint64_t(rt.tv_nsec)) - int64_t(real_ns());
  });
  const ClockAnchor a = g_clock[g_clock_idx.load()];
  const uint64_t tsc = rdtsc_now();
  uint64_t ns = a.ns + uint64_t(double(tsc - a.tsc) * a.ns_per_tick);
  if (tsc - a.tsc > 400000000ull && !g_clock_busy.exchange(true)) {  // roughly 150-200 ms of ticks
    clock_reanchor();
    g_clock_busy = false;
  }
  uint64_t last = g_clock_last.load(std::memory_order_relaxed);
  while (ns > last && !g_clock_last.compare_exchange_weak(last, ns)) {}
  if (ns < last) ns = last;
  if (realtime) ns = uint64_t(int64_t(ns) + g_clock_rt_offset);
  ts->tv_sec = time_t(ns / 1000000000ull);
  ts->tv_nsec = long(ns % 1000000000ull);
  return 0;
}

// Debug: print where imported libc/libkernel entry points live, to decode profiler addresses.
#include <sched.h>
#include <sys/cpuset.h>
void ps5_log_import_addrs() {
  cpuset_t mask;
  CPU_ZERO(&mask);
  int rc = cpuset_getaffinity(CPU_LEVEL_WHICH, CPU_WHICH_PID, -1, 8, &mask);
  uint64_t bits = 0;
  std::memcpy(&bits, &mask, sizeof bits);
  ps5_log("affinity: rc=%d mask=0x%llx", rc, (unsigned long long)bits);
  CPU_ZERO(&mask);
  rc = cpuset_getaffinity(CPU_LEVEL_WHICH, CPU_WHICH_TID, -1, 8, &mask);
  std::memcpy(&bits, &mask, sizeof bits);
  ps5_log("affinity(thread): rc=%d mask=0x%llx", rc, (unsigned long long)bits);
  ps5_log("imports: usleep=%p __real_clock_gettime=%p memcpy_prx=%p mutex_lock=%p cond_wait=%p cond_timedwait=%p sched_yield=%p sem_wait=%p nanosleep=%p getpid=%p",
          (void*)&sceKernelUsleep, (void*)&__real_clock_gettime, (void*)&strlen, (void*)&pthread_mutex_lock,
          (void*)&pthread_cond_wait, (void*)&pthread_cond_timedwait, (void*)&sched_yield, (void*)&usleep, (void*)&nanosleep, (void*)&getpid);
}
