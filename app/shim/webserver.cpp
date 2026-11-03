// Tiny HTTP server of the app: status page and the PC import. Games are built on the PC (installer/pc_import.py) and streamed here.
//   GET  /                    the status web page (embedded, see webpage.cpp)
//   GET  /api/status          JSON v3: per-game state, percent, speed, eta (see docs/ONBOARDING_WEB.md)
//   GET  /api/events          the same JSON as a server-sent-events stream (4 updates per second)
//   POST /api/cancel?game=    cancel a running install, or dismiss a done/failed card
//   GET  /api/info            capabilities (install_api version) so a PC client can check before it sends gigabytes
//   GET  /api/log[?kb=N]      tail of the app log
//   PUT  /api/install?game=&total=&mode=replace|add&serial=&region=   PC import stream (installer/pc_import.py, install_stream.h):
//        unpacked while it arrives into /data/opengoal/<game>/data.new, verified (CRC32), then renamed to data (replace) or
//        merged into data (add). One connection, no temp copy, no second pass. One thread per connection.
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/time.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <vector>

#include "import_progress.h"
#include "include/ps5import.h"
#include "install_stream.h"

void ps5_log(const char* fmt, ...);
extern "C" int sceSystemServicePowerTick(void) __attribute__((weak));  // keeps the console awake while busy (null if not linked)
const char* ps5_web_page();

namespace {

std::string g_ip = "0.0.0.0";

using namespace ps5imp;  // Phase enum: IDLE..FAILED (same numbers as Ps5GameStatus::phase)
const char* const kPhase[] = {"idle", "uploading", "verifying", "queued", "importing", "done", "failed"};
extern "C" bool ps5sdl_game_active();
extern "C" unsigned ps5sdl_slow_frames();
std::atomic<int> g_inst_kbps{5120};  // current write cap in KiB/s while a game runs
std::atomic<int> g_inst_game{-1};    // game index of the running install stream
std::atomic<unsigned long long> g_inst_base{0}, g_inst_all{0};  // bytes of the import before this stream, whole import (0 = unknown)
static long long mono_ms_ws() { timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000; }

const char* const kIds[3] = {"jak1", "jak2", "jak3"};
const char* const kTitles[3] = {"Jak and Daxter", "Jak II", "Jak 3"};

struct GameSt {
  std::atomic<int> phase{IDLE};
  std::atomic<unsigned long long> bytes{0}, total{0};
  std::atomic<unsigned> speed{0};         // smoothed install bytes/s (sampler thread)
  std::atomic<long> t0{0}, t_end{0};      // install start / end, time(0)
  std::atomic<long> last_io{0};           // last received data
  std::atomic<bool> cancelling{false};
  std::atomic<bool> installing{false};    // PC import stream in progress (phase is IMPORTING, stage "install")
  char err[24] = "";                      // reason key while phase == failed (guarded by g_mu)
  char serial[16] = "";
  char region[8] = "";
  unsigned long long sample_bytes = 0;    // sampler state
  double sample_t = 0;
};
GameSt g_g[3];
std::mutex g_mu;
std::atomic<bool> g_installing{false};  // one PC install stream at a time

int gidx(const std::string& g) { return g == "jak1" ? 0 : g == "jak2" ? 1 : g == "jak3" ? 2 : -1; }
double mono() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return double(ts.tv_sec) + double(ts.tv_nsec) * 1e-9;
}

std::string query_value(const std::string& q, const char* key) {
  std::string k = std::string(key) + "=";
  size_t p = 0;
  while (p < q.size()) {
    size_t e = q.find('&', p);
    if (e == std::string::npos) e = q.size();
    if (q.compare(p, k.size(), k) == 0) return q.substr(p + k.size(), e - p - k.size());
    p = e + 1;
  }
  return "";
}

bool dir_exists(const std::string& p) {
  struct stat st;
  return stat(p.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

bool installed(const char* id) {
  std::string base = std::string("/data/opengoal/") + id + "/data";
  return dir_exists(base + "/out/" + id + "/fr3") && dir_exists(base + "/out/" + id + "/iso") && dir_exists(base + "/game/assets");
}

// installed() of every game, refreshed every 2 s on a thread of its own: the launcher asks for the status of each game in
// every frame (under g_mu), and stat() blocks for seconds while an install writes gigabytes
std::atomic<int> g_inst_mask{-1};
bool installed_cached(int i) {
  static std::atomic<bool> started{false};
  if (!started.exchange(true))
    std::thread([] {
      for (;;) {
        int m = 0;
        for (int k = 0; k < 3; ++k) m |= installed(kIds[k]) ? 1 << k : 0;
        g_inst_mask = m;
        sleep(2);
      }
    }).detach();
  const int m = g_inst_mask.load();
  return m >= 0 && ((m >> i) & 1);
}

bool send_all(int fd, const char* p, size_t n) {
  while (n) {
    ssize_t w = send(fd, p, n, MSG_NOSIGNAL);
    if (w <= 0) return false;
    p += w;
    n -= size_t(w);
  }
  return true;
}

void respond(int fd, int code, const char* type, const std::string& body, bool keep) {
  const char* text = code == 200 ? "OK" : code == 204 ? "No Content" : code == 400 ? "Bad Request" : code == 404 ? "Not Found" : code == 409 ? "Conflict" : code == 422 ? "Unprocessable Entity" : "Error";
  char head[256];
  int n = std::snprintf(head, sizeof head, "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\nCache-Control: no-store\r\nConnection: %s\r\n\r\n", code, text, type,
                        body.size(), keep ? "keep-alive" : "close");
  send_all(fd, head, size_t(n));
  if (!body.empty()) send_all(fd, body.data(), body.size());
}

// ---- status ---------------------------------------------------------------------------------------------------------

// Fills one game's status. Caller holds g_mu.
void fill_locked(int i, Ps5GameStatus* o) {
  const GameSt& g = g_g[i];
  std::memset(o, 0, sizeof *o);
  const int ph = g.phase.load();
  const long now = (long)time(nullptr);
  o->installed = installed_cached(i) ? 1 : 0;
  o->phase = ph;
  o->bytes = g.bytes.load();
  o->total = g.total.load();
  const bool inst = ph == IMPORTING && g.installing.load();  // stage 0 = "Installing" in the launcher
  o->speed_bps = inst ? g.speed.load() : 0;
  o->stage = 0;
  o->stage_percent = -1;
  o->percent = ph == DONE ? 100 : -1;
  o->eta_s = -1;
  if (inst) {
    o->elapsed_s = int(now - g.t0.load());
    o->percent = o->stage_percent = std::min(99, int(o->total ? 100.0 * double(o->bytes) / double(o->total) : 0));
    o->eta_s = (o->speed_bps > 0 && o->total > o->bytes) ? int((o->total - o->bytes) / o->speed_bps) : -1;
  } else if ((ph == DONE || ph == FAILED) && g.t_end.load() && g.t0.load()) {
    o->elapsed_s = int(g.t_end.load() - g.t0.load());
  }
  std::snprintf(o->serial, sizeof o->serial, "%s", g.serial);
  std::snprintf(o->region, sizeof o->region, "%s", g.region);
  if (ph == FAILED) std::snprintf(o->reason, sizeof o->reason, "%s", g.err);
  else if (ph == IMPORTING && g.cancelling.load()) std::snprintf(o->reason, sizeof o->reason, "cancelling");
}

std::string status_json() {
  std::lock_guard<std::mutex> l(g_mu);
  const long now = (long)time(nullptr);
  char b[768];
  std::string j = std::string("{\"version\":3,\"ip\":\"") + g_ip + "\",\"busy\":" + (g_installing.load() ? "true" : "false") + ",\"games\":{";
  int sum = 0, n = 0, eta_sum = 0, eta_known = 0, eta_unknown = 0;
  for (int i = 0; i < 3; ++i) {
    Ps5GameStatus s;
    fill_locked(i, &s);
    const GameSt& g = g_g[i];
    const long idle = g.last_io.load() ? now - g.last_io.load() : -1;
    std::snprintf(b, sizeof b,
                  "%s\"%s\":{\"installed\":%s,\"phase\":\"%s\",\"stage\":\"%s\",\"percent\":%d,\"stage_percent\":%d,\"bytes\":%llu,\"total\":%llu,"
                  "\"speed\":%u,\"eta\":%d,\"elapsed\":%d,\"idle\":%ld,\"serial\":\"%s\",\"region\":\"%s\",\"reason\":\"%s\"}",
                  i ? "," : "", kIds[i], s.installed ? "true" : "false", kPhase[s.phase], g.installing.load() ? "install" : "", s.percent, s.stage_percent,
                  s.bytes, s.total, s.speed_bps, s.eta_s, s.elapsed_s, idle, s.serial, s.region, s.reason);
    j += b;
    if (s.phase == IMPORTING || s.phase == DONE) {  // games of this session
      ++n;
      sum += s.percent < 0 ? 0 : s.percent;
      if (s.phase != DONE) {
        if (s.eta_s >= 0) { eta_sum += s.eta_s; ++eta_known; }
        else ++eta_unknown;
      }
    }
  }
  std::snprintf(b, sizeof b, "},\"overall\":{\"games\":%d,\"percent\":%d,\"eta\":%d}}", n, n ? sum / n : -1,
                (n && !eta_unknown && eta_known) ? eta_sum : -1);
  return j + b;
}

void mkdir_p(const char* path) {
  std::string p;
  for (const char* c = path; *c; ++c) {
    p += *c;
    if (*c == '/' && p.size() > 1) mkdir(p.c_str(), 0777);
  }
  mkdir(path, 0777);
  chmod(path, 0777);  // umask or another owner must not leave the folder unwritable for the game process
}

// ---- PC install stream ----------------------------------------------------------------------------------------------

void rm_rf(const std::string& p) {
  if (DIR* d = opendir(p.c_str())) {
    while (dirent* e = readdir(d)) {
      if (!std::strcmp(e->d_name, ".") || !std::strcmp(e->d_name, "..")) continue;
      const std::string c = p + "/" + e->d_name;
      struct stat st;
      if (stat(c.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) rm_rf(c);
      else unlink(c.c_str());
    }
    closedir(d);
    rmdir(p.c_str());
  } else {
    unlink(p.c_str());
  }
}

void* rm_thread(void* a) {
  std::unique_ptr<std::string> p(static_cast<std::string*>(a));
  rm_rf(*p);
  return nullptr;
}

// Writes the unpacked files below `root`. Replace mode writes straight to the final name (the whole directory is renamed at the
// end); add mode writes <name>.part and renames per file, so a game that is already playable never sees a half file.
// Connection to the ogwriter payload (payloads/ogwriter.c, 127.0.0.1:9098): the console throttles the disk writes of this process
// to ~2 MB/s after ~1.3 GB, the writer process keeps ~250 MB/s. Not running: the app sends its copy of the payload to the ELF loader
// (127.0.0.1:9021) and connects again; without a loader the app writes itself.
std::atomic<long long> g_writer_tried{-100000};  // last start attempt (ms): one try per 30 s, a missing loader costs nothing per chunk
struct Writer {
  int s = -1;
  bool try_connect() {
    s = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in a{};
    a.sin_family = AF_INET; a.sin_port = htons(9098); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (s >= 0 && connect(s, (sockaddr*)&a, sizeof a) == 0) return true;
    if (s >= 0) close(s);
    s = -1;
    return false;
  }
  static void launch() {
    FILE* f = std::fopen("/data/homebrew/LAPY77001/ogwriter.elf", "rb");
    if (!f) { ps5_log("install: writer: ogwriter.elf missing in the app folder"); return; }
    std::vector<char> elf(1 << 20);
    elf.resize(std::fread(elf.data(), 1, elf.size(), f));
    std::fclose(f);
    const int l = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in a{};
    a.sin_family = AF_INET; a.sin_port = htons(9021); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bool sent = l >= 0 && connect(l, (sockaddr*)&a, sizeof a) == 0;
    for (size_t off = 0; sent && off < elf.size();) {
      const ssize_t w = send(l, elf.data() + off, elf.size() - off, 0);
      if (w <= 0) sent = false; else off += size_t(w);
    }
    if (l >= 0) close(l);
    ps5_log("install: writer: %s", sent ? "sent ogwriter.elf to the ELF loader" : "no ELF loader on 127.0.0.1:9021");
  }
  bool connect_local() {
    bool ok = try_connect();
    const long long now = mono_ms_ws();
    if (!ok && now - g_writer_tried.load() > 30000) {
      g_writer_tried = now;
      launch();
      for (int i = 0; i < 20 && !ok; ++i) { usleep(100000); ok = try_connect(); }
    }
    if (ok) {
      int one = 1;
      setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
      timeval tv{30, 0};
      setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    }
    return ok;
  }
  ~Writer() { if (s >= 0) close(s); }
  bool put(const void* p, size_t n) {
    for (const char* c = (const char*)p; n;) {
      const ssize_t w = send(s, c, n, 0);
      if (w <= 0) return false;
      c += w; n -= size_t(w);
    }
    return true;
  }
  int answer() {  // errno from the writer, EPIPE when the connection broke
    int32_t v = 0;
    for (size_t got = 0; got < 4;) {
      const ssize_t r = recv(s, (char*)&v + got, 4 - got, 0);
      if (r <= 0) return EPIPE;
      got += size_t(r);
    }
    return v;
  }
  int op(char o, const void* p, uint32_t n) {  // 'O' waits for the answer, 'W' does not
    if (!put(&o, 1) || !put(&n, 4) || !put(p, n)) return EPIPE;
    return o == 'O' ? answer() : 0;
  }
  int close_file() {
    const char c = 'C';
    return put(&c, 1) ? answer() : EPIPE;
  }
};

struct FsSink : ps5inst::Sink {
  std::string root, cur, tmp;
  bool per_file_rename;
  int fd = -1, err = 0;
  const char* step = "";  // what failed (mkdir | open | write | close | rename) and on which path: reported to the PC and logged
  std::string fail_path;
  std::set<std::string> dirs;
  Writer wr;
  bool remote = false;
  FsSink(const std::string& r, bool prf) : root(r), per_file_rename(prf) {
    remote = wr.connect_local();
    ps5_log("install: writer %s", remote ? "payload (127.0.0.1:9098)" : "not running, the app writes itself");
  }
  ~FsSink() override { if (fd > 0 && !remote) close(fd); }
  bool bad(const char* s, const std::string& p) { err = errno; step = s; fail_path = p; return false; }
  bool ensure(const std::string& full) {
    if (dirs.count(full)) return true;
    mkdir_p(full.c_str());
    const int e = errno;
    dirs.insert(full);
    if (!dir_exists(full)) { errno = e; return bad("mkdir", full); }
    return true;
  }
  bool make_dir(const std::string& rel) override { return ensure(root + "/" + rel); }
  bool open_file(const std::string& rel, uint64_t) override {
    const size_t sl = rel.rfind('/');
    if (sl != std::string::npos && !ensure(root + "/" + rel.substr(0, sl))) return false;
    struct Add { long long& a; long long t; ~Add() { a += mono_ms_ws() - t; } } add{open_ms, mono_ms_ws()};
    cur = root + "/" + rel;
    tmp = per_file_rename ? cur + ".part" : cur;
    f_t0 = mono_ms_ws(); f_bytes = 0;
    if (remote) {
      const int e = wr.op('O', tmp.data(), uint32_t(tmp.size()));
      if (e) { errno = e; return bad("open", tmp); }
      fd = 0;
      return true;
    }
    fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return bad("open", tmp);
    return true;
  }
  long long write_ms = 0, open_ms = 0;  // measurement: disk time inside the install loop
  long long f_t0 = 0;
  unsigned long long f_bytes = 0;
  unsigned long long writes = 0;
  bool write(const char* p, size_t n) override {
    const long long t0 = mono_ms_ws();
    ++writes;
    f_bytes += n;
    struct Add { long long& a; long long t; ~Add() { a += mono_ms_ws() - t; } } add{write_ms, t0};
    if (remote) {
      if (wr.op('W', p, uint32_t(n))) { errno = EPIPE; return bad("write", tmp); }
      return true;
    }
    while (n) {
      const ssize_t w = ::write(fd, p, n);
      if (w <= 0) return bad("write", tmp);
      p += w; n -= size_t(w);
    }
    return true;
  }
  bool close_file() override {
    const long long tc = mono_ms_ws();
    int r = 0;
    if (remote) {
      const int e = wr.close_file();
      if (e) { errno = e; r = -1; }
    } else {
      r = close(fd);
    }
    if (f_bytes >= (16ull << 20))
      ps5_log("install: file %s %llu MB, open to close %lld ms, close %lld ms", cur.c_str() + root.size(), f_bytes >> 20, mono_ms_ws() - f_t0,
              mono_ms_ws() - tc);
    fd = -1;
    if (r != 0) return bad("close", tmp);
    if (per_file_rename && rename(tmp.c_str(), cur.c_str()) != 0) return bad("rename", tmp);
    return true;
  }
};

std::string clean_token(const std::string& s) {
  std::string o;
  for (char c : s) if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '-') o += c;
  return o.substr(0, 15);
}

// First line of a small text file with every character outside [0-9A-Za-z._-] dropped (it ends up inside JSON); "" when unreadable.
std::string read_token(const std::string& path) {
  std::string o;
  if (FILE* f = std::fopen(path.c_str(), "r")) {
    char b[64];
    if (std::fgets(b, sizeof b, f))
      for (const char* c = b; *c && o.size() < 24; ++c)
        if ((*c >= '0' && *c <= '9') || (*c >= 'A' && *c <= 'Z') || (*c >= 'a' && *c <= 'z') || *c == '.' || *c == '-' || *c == '_') o += *c;
    std::fclose(f);
  }
  return o;
}

// Capabilities, the app version (the VERSION file of the release, uploaded with the app) and the data format of every installed game
// (.format next to the game's data; a game installed before the file existed is format 1). The PC setup decides on updates from these.
// access() is not reliable on the console (it failed for folders the app writes fine), so test with a real create and unlink
static bool can_write(const char* dir) {
  const std::string f = std::string(dir) + "/.og_write_test";
  const int fd = open(f.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0666);
  if (fd < 0) return false;
  close(fd);
  unlink(f.c_str());
  return true;
}

std::string info_json() {
  std::string fm;
  for (int i = 0; i < 3; ++i) {
    if (!installed(kIds[i])) continue;
    const std::string f = read_token(std::string("/data/opengoal/") + kIds[i] + "/data/.format");
    fm += std::string(fm.empty() ? "" : ",") + "\"" + kIds[i] + "\":" + (f.empty() ? "1" : f);
  }
  // folders the app must be able to write, checked as the app's own user: the setup repairs them when one is listed (#5)
  std::string bad;
  for (const char* d : {"/data/opengoal", "/data/opengoal/log", "/data/opengoal/config", "/data/opengoal/config/OpenGOAL", "/data/opengoal/jak1",
                        "/data/opengoal/jak2", "/data/opengoal/jak3", "/data/opengoal/config/OpenGOAL/jak1", "/data/opengoal/config/OpenGOAL/jak2",
                        "/data/opengoal/config/OpenGOAL/jak3"})
    if (!can_write(d)) bad += std::string(bad.empty() ? "" : ",") + "\"" + d + "\"";
  return "{\"install_api\":1,\"max_frame\":16777216,\"codecs\":[\"raw\",\"deflate\"],\"busy\":" + std::string(g_installing.load() ? "true" : "false") +
         ",\"app\":\"" + read_token("/data/homebrew/LAPY77001/VERSION") + "\",\"formats\":{" + fm + "},\"unwritable\":[" + bad + "]}";
}

// Answers, then swallows what the client is still sending (up to 64 MB / 1 s of silence) so the close does not turn into a TCP
// reset that destroys the answer before the client reads it.
void reply(int fd, int code, const char* type, const std::string& body, bool keep) {
  respond(fd, code, type, body, keep);
  shutdown(fd, SHUT_WR);
  timeval tv{1, 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  std::vector<char> junk(1 << 16);
  unsigned long long left = 64ull << 20;
  while (left) {
    const ssize_t r = recv(fd, junk.data(), junk.size(), 0);
    if (r <= 0) break;
    left -= std::min<unsigned long long>(left, (unsigned long long)r);
  }
}

// PUT /api/install: the body is the self-delimiting stream (no Content-Length). Always answers and closes the connection.
void handle_install(int fd, int gi, const std::string& query, std::string& pending, std::vector<char>& buf) {
  GameSt& g = g_g[gi];
  const std::string game = kIds[gi];
  const unsigned long long total = strtoull(query_value(query, "total").c_str(), nullptr, 10);
  const bool add = query_value(query, "mode") == "add";
  const std::string serial = clean_token(query_value(query, "serial")), region = clean_token(query_value(query, "region"));
  const char* J = "application/json";
  if (total < 1024 || total > (64ull << 30)) { reply(fd, 400, J, "{\"error\":\"total\"}", false); return; }
  const std::string base = std::string("/data/opengoal/") + game, data = base + "/data", stage_dir = add ? data : base + "/data.new";
  if (add && !dir_exists(data)) { reply(fd, 409, J, "{\"error\":\"nogame\"}", false); return; }
  bool expect = false;
  if (!g_installing.compare_exchange_strong(expect, true)) { reply(fd, 409, J, "{\"error\":\"busy\"}", false); return; }
  bool busy = false;
  {
    std::lock_guard<std::mutex> l(g_mu);
    const int ph = g.phase.load();
    busy = ph == IMPORTING;
    if (!busy) {
      g.err[0] = 0;
      std::snprintf(g.serial, sizeof g.serial, "%s", serial.c_str());
      std::snprintf(g.region, sizeof g.region, "%s", region.c_str());
      g.bytes = 0; g.total = total; g.speed = 0; g.sample_bytes = 0; g.sample_t = 0;
      g.t0 = (long)time(nullptr); g.t_end = 0; g.last_io = g.t0.load();
      g.cancelling = false; g.installing = true;
      g.phase = IMPORTING;
    }
  }
  if (busy) {
    g_installing = false;
    reply(fd, 409, J, "{\"error\":\"busy\"}", false);  // outside the lock: reply() drains the client for a moment
    return;
  }
  timeval tv{30, 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  std::string key;
  int eno = 0;
  std::string where;  // "<step> <path>" of the failing filesystem call
  uint64_t files = 0;
  bool used_writer = false;
  {
    mkdir_p(base.c_str());
    if (!add) rm_rf(stage_dir);
    mkdir_p(stage_dir.c_str());
    if (!dir_exists(stage_dir)) {  // /data/opengoal/<game> cannot be created or written: say so now, not after the upload
      key = "io"; eno = errno; where = "mkdir " + stage_dir;
      ps5_log("install: %s cannot create %s: errno %d (%s)", game.c_str(), stage_dir.c_str(), eno, strerror(eno));
    }
    FsSink sink(stage_dir, add);
    used_writer = sink.remote;
    std::unique_ptr<ps5inst::Receiver> rx(new ps5inst::Receiver(&sink, total));  // ~130 KB of tables: heap, the thread stack is small
    unsigned long long throttled = 0;
    long long tq0 = 0, tadj = 0;
    unsigned slow0 = 0;
    long long st_t = mono_ms_ws(), st_net = 0, st_feed = 0, st_sleep = 0;
    unsigned long long st_wire = 0;
    g_inst_kbps = 5120;
    g_inst_base = strtoull(query_value(query, "base").c_str(), nullptr, 10);  // whole import: game, then voice languages
    g_inst_all = strtoull(query_value(query, "all").c_str(), nullptr, 10);
    g_inst_game = gi;
    bool ok = key.empty() && (pending.empty() || rx->feed(pending.data(), pending.size()));
    pending.clear();
    while (ok && !rx->finished()) {
      if (g.cancelling.load()) { key = "cancelled"; break; }
      g.bytes = rx->raw_done();
      const long long m0 = mono_ms_ws();
      const ssize_t r = recv(fd, buf.data(), buf.size(), 0);
      if (r <= 0) { key = "net"; ps5_log("install: recv rc=%d errno=%d", int(r), errno); break; }
      g.last_io = (long)time(nullptr);
      const long long m1 = mono_ms_ws();
      ok = rx->feed(buf.data(), size_t(r));
      const long long m2 = mono_ms_ws();
      st_net += m1 - m0; st_feed += m2 - m1; st_wire += size_t(r);
      if (m2 - st_t >= 5000) {  // where the time goes: waiting for the PC, inflating + writing, throttle sleep
        ps5_log("install: %s %llu MB raw, last %.1f s: wire %.1f MB/s, recv %lld ms, inflate+write %lld ms, throttle %lld ms, cap %d KB/s; disk write %lld ms (%llu writes), open %lld ms",
                game.c_str(), (unsigned long long)(rx->raw_done() >> 20), (m2 - st_t) / 1000.0, st_wire / 1048.576 / double(m2 - st_t),
                st_net, st_feed, st_sleep, ps5sdl_game_active() ? g_inst_kbps.load() : 0, sink.write_ms, sink.writes, sink.open_ms);
        sink.write_ms = sink.open_ms = 0; sink.writes = 0;
        st_t = m2; st_net = st_feed = st_sleep = 0; st_wire = 0;
      }
      // while a game runs, cap the disk writes: unthrottled, the game's level loading waited 5 to 20 s and 20 MB/s dropped
      // Jak 1 to 25 fps. The cap adapts once a second: halved when the game had slow frames (over 20 ms), else raised by 1 MB/s.
      if (ps5sdl_game_active()) {
        throttled += size_t(r);
        const long long t = mono_ms_ws();
        if (!tq0) { tq0 = tadj = t; slow0 = ps5sdl_slow_frames(); }
        if (t - tadj >= 1000) {
          const unsigned slow = ps5sdl_slow_frames();
          const int kbps = g_inst_kbps.load();
          g_inst_kbps = slow - slow0 >= 2 ? std::max(2048, kbps / 2) : std::min(20480, kbps + 1024);
          slow0 = slow;
          tadj = t;
        }
        const long long due = tq0 + (long long)(throttled / (unsigned long long)g_inst_kbps.load());  // ms for `throttled` bytes at the cap
        if (due > t) { usleep(useconds_t((due - t) * 1000)); st_sleep += due - t; }
        if (t - tq0 > 2000) { tq0 = mono_ms_ws(); throttled = 0; }
      } else {
        tq0 = 0;
        throttled = 0;
      }
    }
    if (key.empty() && !ok) {
      const std::string e = rx->error();
      key = e == "io" ? ((sink.err == ENOSPC || sink.err == EDQUOT) ? "no_space" : "io") : "bad_contents";
      eno = sink.err;
      if (e == "io") where = std::string(sink.step) + " " + sink.fail_path;
      ps5_log("install: %s failed: %s (errno %d %s) at %s, %llu of %llu bytes received", game.c_str(), e.c_str(), sink.err, strerror(sink.err),
              where.c_str(), (unsigned long long)rx->raw_done(), (unsigned long long)total);
    }
    if (key.empty() && !(rx->finished() && rx->raw_done() == total)) key = "bad_contents";
    files = rx->files();
  }
  if (key.empty()) {
    if (add) {
      // files are already in place
    } else {
      if (FILE* f = std::fopen((stage_dir + "/.format").c_str(), "w")) {  // data format of this install, see info_json()
        const unsigned long long fmt = strtoull(query_value(query, "format").c_str(), nullptr, 10);  // a client that sends none is format 1
        std::fprintf(f, "%llu\n", fmt < 1 ? 1ull : std::min(999ull, fmt));
        std::fclose(f);
      }
      if (FILE* f = std::fopen((stage_dir + "/.ps5ready").c_str(), "w")) {
        std::fprintf(f, "{\"game\":\"%s\",\"serial\":\"%s\",\"region\":\"%s\",\"time\":%ld,\"source\":\"pc_import\"}\n", game.c_str(), serial.c_str(), region.c_str(), (long)time(nullptr));
        std::fclose(f);
      }
      const std::string old = base + "/data.old";
      if (dir_exists(old)) rm_rf(old);  // leftover of an interrupted earlier swap
      const bool had = dir_exists(data);
      if (had && rename(data.c_str(), old.c_str()) != 0) { key = "io"; eno = errno; where = "rename " + data + " -> " + old; }
      else if (rename(stage_dir.c_str(), data.c_str()) != 0) { key = "io"; eno = errno; where = "rename " + stage_dir + " -> " + data; if (had) rename(old.c_str(), data.c_str()); }
      if (!key.empty()) ps5_log("install: %s swap failed: errno %d (%s) at %s", game.c_str(), eno, strerror(eno), where.c_str());
      else if (had) {
        pthread_t th;
        if (pthread_create(&th, nullptr, rm_thread, new std::string(old)) == 0) pthread_detach(th);
      }
    }
  }
  if (!key.empty() && !add) rm_rf(stage_dir);
  {
    std::lock_guard<std::mutex> l(g_mu);
    g.t_end = (long)time(nullptr);
    g.installing = false;
    g.cancelling = false;
    if (key.empty()) { g.bytes = total; g.phase = DONE; }
    else { std::snprintf(g.err, sizeof g.err, "%s", key.c_str()); g.phase = FAILED; }
  }
  g_inst_game = -1;
  g_installing = false;
  ps5_log("install: %s %s (%llu files, %llu bytes, %ld s)", game.c_str(), key.empty() ? "ok" : key.c_str(), (unsigned long long)files, total,
          (long)time(nullptr) - g.t0.load());
  char b[640];
  if (key.empty()) {
    std::snprintf(b, sizeof b, "{\"ok\":true,\"files\":%llu,\"bytes\":%llu,\"mode\":\"%s\",\"writer\":\"%s\"}", (unsigned long long)files, total,
                  add ? "add" : "replace", used_writer ? "payload" : "app");
    reply(fd, 200, J, b, false);
  } else {
    for (char& c : where) if (c == '"' || c == '\\' || (unsigned char)c < 32) c = '\'';
    std::snprintf(b, sizeof b, "{\"error\":\"%s\",\"errno\":%d,\"why\":\"%s\",\"where\":\"%.300s\"}", key.c_str(), eno, eno ? strerror(eno) : "", where.c_str());
    reply(fd, key == "bad_contents" || key == "cancelled" ? 422 : 500, J, b, false);
  }
}

// ---- HTTP -----------------------------------------------------------------------------------------------------------

struct Conn {
  int fd;
};

void serve_events(int fd) {
  const char* head = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: close\r\nX-Accel-Buffering: no\r\n\r\nretry: 1000\n\n";
  if (!send_all(fd, head, std::strlen(head))) return;
  for (;;) {
    const std::string j = "data: " + status_json() + "\n\n";
    if (!send_all(fd, j.data(), j.size())) return;
    usleep(250 * 1000);
  }
}

void* serve(void* arg) {
  int fd = static_cast<Conn*>(arg)->fd;
  delete static_cast<Conn*>(arg);
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  int rcvbuf = 4 << 20;
  setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof rcvbuf);
  std::vector<char> buf(2 << 20);  // big reads keep the per-byte cost low
  std::string pending;
  for (;;) {
    // read one request head
    size_t head_end;
    while ((head_end = pending.find("\r\n\r\n")) == std::string::npos) {
      ssize_t r = recv(fd, buf.data(), buf.size(), 0);
      if (r <= 0 || pending.size() > (64 << 10)) goto done;
      pending.append(buf.data(), size_t(r));
    }
    {
      std::string head = pending.substr(0, head_end);
      pending.erase(0, head_end + 4);
      size_t sp1 = head.find(' '), sp2 = head.find(' ', sp1 + 1);
      if (sp1 == std::string::npos || sp2 == std::string::npos) goto done;
      std::string method = head.substr(0, sp1), target = head.substr(sp1 + 1, sp2 - sp1 - 1);
      std::string path = target, query;
      if (size_t q = target.find('?'); q != std::string::npos) { path = target.substr(0, q); query = target.substr(q + 1); }
      unsigned long long clen = 0;
      bool keep = true;
      for (size_t p = head.find("\r\n"); p != std::string::npos; p = head.find("\r\n", p + 2)) {
        const char* line = head.c_str() + p + 2;
        if (strncasecmp(line, "Content-Length:", 15) == 0) clen = strtoull(line + 15, nullptr, 10);
        if (strncasecmp(line, "Connection: close", 17) == 0) keep = false;
      }
      std::string game = query_value(query, "game");
      const int gi = gidx(game);
      if (method == "GET" && (path == "/" || path == "/index.html")) {
        respond(fd, 200, "text/html; charset=utf-8", ps5_web_page(), keep);
      } else if (method == "GET" && path == "/api/status") {
        respond(fd, 200, "application/json", status_json(), keep);
      } else if (method == "GET" && path == "/api/events") {
        serve_events(fd);
        goto done;
      } else if (method == "GET" && path == "/api/info") {
        respond(fd, 200, "application/json", info_json(), keep);
      } else if (method == "GET" && path == "/api/log") {  // tail of ps5.log (the file is huge): ?kb=N, default 128, max 1024
        unsigned long long kb = strtoull(query_value(query, "kb").c_str(), nullptr, 10);
        kb = kb < 1 ? 128 : kb > 1024 ? 1024 : kb;
        std::string txt;
        if (FILE* f = std::fopen("/data/opengoal/log/ps5.log", "rb")) {
          std::fseek(f, 0, SEEK_END);
          const long end = std::ftell(f), from = end > long(kb << 10) ? end - long(kb << 10) : 0;
          std::fseek(f, from, SEEK_SET);
          txt.resize(size_t(end - from));
          txt.resize(std::fread(&txt[0], 1, txt.size(), f));
          std::fclose(f);
        } else {
          txt = "cannot open /data/opengoal/log/ps5.log: " + std::string(strerror(errno)) + "\nThe app cannot write /data/opengoal. Check owner and permissions of /data/opengoal (FTP) and run the setup again.\n";
        }
        respond(fd, 200, "text/plain; charset=utf-8", txt, keep);
      } else if (method == "PUT" && path == "/api/install" && gi >= 0) {
        handle_install(fd, gi, query, pending, buf);
        goto done;
      } else if (method == "POST" && path == "/api/cancel" && gi >= 0) {
        GameSt& g = g_g[gi];
        std::lock_guard<std::mutex> l(g_mu);
        const int ph = g.phase.load();
        if (ph == IMPORTING) {
          g.cancelling = true;  // the install loop stops at the next read
        } else if (ph == DONE || ph == FAILED) {
          g.phase = IDLE;
        }
        respond(fd, 200, "application/json", "{\"ok\":true}", keep);
      } else {
        respond(fd, 404, "text/plain", "not found", keep);
      }
      if (!keep) goto done;
    }
  }
done:
  close(fd);
  return nullptr;
}

// Samples the install speed and keeps the console awake while a game installs.
void* speed_loop(void*) {
  int tick = 0;
  for (;;) {
    usleep(200 * 1000);
    const double now_m = mono();
    std::lock_guard<std::mutex> l(g_mu);
    for (int i = 0; i < 3; ++i) {  // exponential average over ~1 s
      GameSt& g = g_g[i];
      if (!g.installing.load()) { g.speed = 0; g.sample_t = 0; continue; }
      const unsigned long long b = g.bytes.load();
      if (g.sample_t > 0 && now_m > g.sample_t) {
        const double v = (b >= g.sample_bytes ? double(b - g.sample_bytes) : 0.0) / (now_m - g.sample_t);
        g.speed = unsigned(g.speed.load() * 0.7 + v * 0.3);
      }
      g.sample_bytes = b;
      g.sample_t = now_m;
    }
    if (++tick % 50 == 0 && sceSystemServicePowerTick && g_installing.load()) sceSystemServicePowerTick();  // every 10 s while busy
  }
  return nullptr;
}

void* accept_loop(void* arg) {
  int port = int(reinterpret_cast<intptr_t>(arg));
  int ls = socket(AF_INET, SOCK_STREAM, 0);
  int one = 1;
  setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(uint16_t(port));
  if (bind(ls, reinterpret_cast<sockaddr*>(&addr), sizeof addr) != 0 || listen(ls, 16) != 0) {
    ps5_log("web: bind/listen on port %d failed", port);
    return nullptr;
  }
  ps5_log("web: status page on port %d", port);
  for (;;) {
    int fd = accept(ls, nullptr, nullptr);
    if (fd < 0) continue;
    pthread_t th;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 256 << 10);
    if (pthread_create(&th, &attr, serve, new Conn{fd}) == 0) pthread_detach(th);
    else close(fd);
  }
  return nullptr;
}

}  // namespace

// Start the server (idempotent). `ip` is shown on the page and in the launcher QR code.
extern "C" void ps5_web_start(int port, const char* ip) {
  static std::atomic<bool> started{false};
  if (started.exchange(true)) return;
  if (ip && ip[0]) g_ip = ip;
  else {  // first non-loopback IPv4 address
    ifaddrs* ifa = nullptr;
    if (getifaddrs(&ifa) == 0) {
      for (ifaddrs* a = ifa; a; a = a->ifa_next) {
        if (!a->ifa_addr || a->ifa_addr->sa_family != AF_INET) continue;
        char s[32];
        inet_ntop(AF_INET, &reinterpret_cast<sockaddr_in*>(a->ifa_addr)->sin_addr, s, sizeof s);
        if (std::strncmp(s, "127.", 4) != 0) { g_ip = s; break; }
      }
      freeifaddrs(ifa);
    }
  }
  pthread_t th;
  pthread_create(&th, nullptr, accept_loop, reinterpret_cast<void*>(intptr_t(port)));
  pthread_detach(th);
  if (pthread_create(&th, nullptr, speed_loop, nullptr) == 0) pthread_detach(th);
}

extern "C" const char* ps5_web_ip() { return g_ip.c_str(); }
// ---- stable C API for the launcher (include/ps5import.h) ------------------------------------------------------------
extern "C" bool ps5_web_installing() { return g_installing.load(); }  // a PC import stream is writing a game right now

extern "C" int ps5_game_status(const char* game, Ps5GameStatus* out) {
  const int i = game ? gidx(game) : -1;
  if (i < 0 || !out) return -1;
  std::lock_guard<std::mutex> l(g_mu);
  fill_locked(i, out);
  return 0;
}

extern "C" const char* ps5_import_queue_text() {
  static std::string t;  // no thread_local: the PS5 SDK has no __cxa_thread_atexit_impl; guarded by g_mu
  std::lock_guard<std::mutex> l(g_mu);
  t.clear();
  for (int i = 0; i < 3; ++i)
    if (g_g[i].phase.load() == IMPORTING && g_g[i].installing.load()) {
      Ps5GameStatus s;
      fill_locked(i, &s);
      t = std::string(kTitles[i]) + ": installing " + std::to_string(s.percent < 0 ? 0 : s.percent) + "%";
    }
  return t.c_str();
}

// install notice in the running game (launcher.cpp): game index, percent of the running stream, current write cap
extern "C" bool ps5_install_notice_state(int* game, int* pct, int* kbps) {
  const int gi = g_inst_game.load();
  if (gi < 0) return false;
  const unsigned long long all = g_inst_all.load();
  const unsigned long long b = g_g[gi].bytes.load() + (all ? g_inst_base.load() : 0), t = all ? all : g_g[gi].total.load();
  *game = gi;
  *pct = t ? int(b * 100 / t) : 0;
  *kbps = g_inst_kbps.load();
  return true;
}
