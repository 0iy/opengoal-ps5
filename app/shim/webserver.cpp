// Tiny HTTP server for the ISO import page.
//   GET  /                    the import web page (embedded, see webpage.cpp)
//   GET  /api/status          JSON v3: per-game state, percent, speed, eta (see docs/ONBOARDING_WEB.md)
//   GET  /api/events          the same JSON as a server-sent-events stream (4 updates per second)
//   POST /api/begin?game=&total=&fp=&chunk=   start or RESUME the upload of that game (answers the finished chunk offsets)
//   PUT  /api/chunk?game=&off=&total=         raw body written at offset `off` (parallel chunks welcome)
//   POST /api/start?game=     finish the upload, pre-check the ISO, queue the import (imports run one after another)
//   POST /api/cancel?game=    cancel upload / queue entry / running import, or dismiss a done/failed card
//   GET|POST /api/settings[?delete_iso=0|1]   console-side settings
//   GET  /api/info            capabilities (install_api version) so a PC client can check before it sends gigabytes
//   PUT  /api/install?game=&total=&mode=replace|add&serial=&region=   PC import stream (installer/pc_import.py, install_stream.h):
//        unpacked while it arrives into /data/opengoal/<game>/data.new, verified (CRC32), then renamed to data (replace) or
//        merged into data (add). One connection, no temp copy, no second pass.
// Upload bodies are streamed straight into the final file with pwrite() in large reads, one thread per connection.
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
extern "C" bool ps5_import_start(const char* game, const char* iso, const char* project);
extern "C" int ps5_import_state();
extern "C" int ps5_import_rc();
extern "C" const char* ps5_import_stage();
extern "C" int ps5_import_stage_id();
extern "C" int ps5_import_stage_percent();
extern "C" void ps5_import_cancel();
extern "C" const char* ps5_import_reason();
extern "C" const char* ps5_iso_probe(const char* path, char* serial12, char* game8, char* region8);
extern "C" int sceSystemServicePowerTick(void) __attribute__((weak));  // keeps the console awake while busy (null if not linked)
const char* ps5_web_page();

namespace {

constexpr const char* kImportDir = "/data/opengoal/import";
constexpr const char* kSettingsFile = "/data/opengoal/config/delete_iso.txt";  // "0" = keep the ISO after the import
constexpr unsigned long long kDefaultChunk = 32ull << 20;
std::string g_ip = "0.0.0.0";

using namespace ps5imp;  // Phase enum: IDLE..FAILED (same numbers as Ps5GameStatus::phase)
const char* const kPhase[] = {"idle", "uploading", "verifying", "queued", "importing", "done", "failed"};
const char* const kStageName[] = {"", "prepare", "extract", "decompile", "compile"};
const char* const kIds[3] = {"jak1", "jak2", "jak3"};
const char* const kTitles[3] = {"Jak and Daxter", "Jak II", "Jak 3"};

struct GameSt {
  std::atomic<int> phase{IDLE};
  std::atomic<unsigned long long> bytes{0}, total{0}, chunk{kDefaultChunk};
  std::atomic<unsigned> speed{0};         // smoothed upload bytes/s (sampler thread)
  std::atomic<long> t0{0}, t_end{0};      // import start / end, time(0)
  std::atomic<long> up0{0}, last_io{0};   // upload start, last chunk activity
  std::atomic<bool> cancelling{false};
  std::atomic<bool> installing{false};    // PC import stream in progress (phase is IMPORTING, stage "install")
  char err[24] = "";                      // reason key while phase == failed (guarded by g_mu)
  char serial[16] = "";
  char region[8] = "";
  std::string fp;                         // client fingerprint of the file (guarded by g_mu)
  std::set<unsigned long long> done;      // finished chunk offsets (guarded by g_mu)
  unsigned long long sample_bytes = 0;    // sampler state
  double sample_t = 0;
};
GameSt g_g[3];
std::mutex g_mu;
std::deque<int> g_queue;  // games waiting for the importer
int g_cur = -1;           // game the importer is working on (guarded by g_mu)
std::atomic<int> g_last_up{0};
std::atomic<bool> g_installing{false};  // one PC install stream at a time

int gidx(const std::string& g) { return g == "jak1" ? 0 : g == "jak2" ? 1 : g == "jak3" ? 2 : -1; }
std::string path_of(const std::string& game, const char* ext) { return std::string(kImportDir) + "/" + game + ext; }
void set_err(int i, const char* e) {
  std::lock_guard<std::mutex> l(g_mu);
  std::snprintf(g_g[i].err, sizeof g_g[i].err, "%s", e);
  g_g[i].phase = FAILED;
}
bool delete_iso_setting() {
  FILE* f = std::fopen(kSettingsFile, "r");
  if (!f) return true;  // default on
  const int c = std::fgetc(f);
  std::fclose(f);
  return c != '0';
}
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
  o->installed = installed(kIds[i]) ? 1 : 0;
  o->phase = ph;
  o->bytes = g.bytes.load();
  o->total = g.total.load();
  const bool inst = ph == IMPORTING && g.installing.load();
  o->speed_bps = (ph == UPLOADING || inst) ? g.speed.load() : 0;
  o->stage = 0;
  o->stage_percent = -1;
  if (inst) {
    o->elapsed_s = int(now - g.t0.load());  // stage 0 = "Installing" in the launcher
  } else if (ph == IMPORTING && g_cur == i) {
    o->stage = ps5_import_stage_id();
    o->stage_percent = ps5_import_stage_percent();
    o->elapsed_s = int(now - g.t0.load());
  } else if (ph == IMPORTING) {
    o->stage = PREPARE;
  } else if (ph == UPLOADING) {
    o->elapsed_s = g.up0.load() ? int(now - g.up0.load()) : 0;
  } else if ((ph == DONE || ph == FAILED) && g.t_end.load() && g.t0.load()) {
    o->elapsed_s = int(g.t_end.load() - g.t0.load());
  }
  const double up_frac = o->total ? double(o->bytes) / double(o->total) : 0;
  o->percent = overall(i, ph, o->stage, o->stage_percent, up_frac);
  if (ph == IMPORTING && o->stage == EXTRACT && o->stage_percent >= 0) o->stage_percent = std::min(o->stage_percent, 100);
  o->eta_s = eta(ph, o->bytes, o->total, o->speed_bps, o->percent, o->elapsed_s);
  if (inst) {
    o->percent = o->stage_percent = std::min(99, int(100.0 * up_frac));
    o->eta_s = (o->speed_bps > 0 && o->total > o->bytes) ? int((o->total - o->bytes) / o->speed_bps) : -1;
  }
  std::snprintf(o->serial, sizeof o->serial, "%s", g.serial);
  std::snprintf(o->region, sizeof o->region, "%s", g.region);
  if (ph == FAILED) std::snprintf(o->reason, sizeof o->reason, "%s", g.err);
  else if (ph == IMPORTING && g.cancelling.load()) std::snprintf(o->reason, sizeof o->reason, "cancelling");
}

std::string status_json() {
  std::lock_guard<std::mutex> l(g_mu);
  const long now = (long)time(nullptr);
  const int ist = ps5_import_state();
  char b[768];
  std::string j = std::string("{\"version\":3,\"ip\":\"") + g_ip + "\",\"busy\":" + (ist == 1 ? "true" : "false") + ",\"current\":\"" + (g_cur >= 0 ? kIds[g_cur] : "") + "\",\"queue\":[";
  for (size_t k = 0; k < g_queue.size(); ++k) j += std::string(k ? "," : "") + "\"" + kIds[g_queue[k]] + "\"";
  j += "],\"games\":{";
  int sum = 0, n = 0, eta_sum = 0, eta_known = 0, eta_unknown = 0;
  int cur_total_est = -1;
  for (int i = 0; i < 3; ++i) {
    Ps5GameStatus s;
    fill_locked(i, &s);
    const GameSt& g = g_g[i];
    const long idle = g.last_io.load() ? now - g.last_io.load() : -1;
    std::snprintf(b, sizeof b,
                  "%s\"%s\":{\"installed\":%s,\"phase\":\"%s\",\"stage\":\"%s\",\"percent\":%d,\"stage_percent\":%d,\"bytes\":%llu,\"total\":%llu,"
                  "\"speed\":%u,\"eta\":%d,\"elapsed\":%d,\"idle\":%ld,\"serial\":\"%s\",\"region\":\"%s\",\"reason\":\"%s\"}",
                  i ? "," : "", kIds[i], s.installed ? "true" : "false", kPhase[s.phase], g.installing.load() ? "install" : kStageName[s.stage], s.percent, s.stage_percent,
                  s.bytes, s.total, s.speed_bps, s.eta_s, s.elapsed_s, idle, s.serial, s.region, s.reason);
    j += b;
    if (s.phase >= UPLOADING && s.phase <= DONE) {  // games of this session
      ++n;
      sum += s.percent < 0 ? 0 : s.percent;
      if (s.phase != DONE) {
        if (s.eta_s >= 0) { eta_sum += s.eta_s; ++eta_known; }
        else ++eta_unknown;
      }
      if (s.phase == IMPORTING && s.eta_s >= 0) cur_total_est = s.elapsed_s + s.eta_s;
    }
  }
  // games that wait for the importer: assume they need as long as the running one
  if (eta_unknown && cur_total_est > 0) { eta_sum += eta_unknown * cur_total_est; eta_unknown = 0; }
  const GameSt& u = g_g[g_last_up.load()];
  std::snprintf(b, sizeof b,
                "},\"overall\":{\"games\":%d,\"percent\":%d,\"eta\":%d},\"settings\":{\"delete_iso\":%s},"
                "\"upload\":{\"game\":\"%s\",\"bytes\":%llu,\"total\":%llu},\"import\":{\"state\":%d,\"rc\":%d,\"stage\":\"%s\",\"percent\":%d}}",
                n, n ? sum / n : -1, (n && !eta_unknown && eta_known) ? eta_sum : -1, delete_iso_setting() ? "true" : "false", kIds[g_last_up.load()],
                (unsigned long long)u.bytes.load(), (unsigned long long)u.total.load(), ist, ps5_import_rc(), ps5_import_stage(), ps5_import_stage_percent());
  return j + b;
}

void mkdir_p(const char* path) {
  std::string p;
  for (const char* c = path; *c; ++c) {
    p += *c;
    if (*c == '/' && p.size() > 1) mkdir(p.c_str(), 0777);
  }
  mkdir(path, 0777);
}

void remove_upload_files(const std::string& game) {
  unlink(path_of(game, ".part").c_str());
  unlink(path_of(game, ".meta").c_str());
  unlink(path_of(game, ".done").c_str());
}

void remove_iso(const std::string& game) { unlink(path_of(game, ".iso").c_str()); }

// ---- upload state on disk (resume) ----------------------------------------------------------------------------------
// <game>.meta: "total chunk fp"; <game>.done: one finished chunk offset per line. Survives page reloads and app restarts.

void write_meta(const std::string& game, unsigned long long total, unsigned long long chunk, const std::string& fp) {
  if (FILE* f = std::fopen(path_of(game, ".meta").c_str(), "w")) {
    std::fprintf(f, "%llu %llu %s\n", total, chunk, fp.c_str());
    std::fclose(f);
  }
}

bool read_meta(const std::string& game, unsigned long long* total, unsigned long long* chunk, std::string* fp) {
  FILE* f = std::fopen(path_of(game, ".meta").c_str(), "r");
  if (!f) return false;
  char fpb[256] = "";
  const int n = std::fscanf(f, "%llu %llu %255s", total, chunk, fpb);
  std::fclose(f);
  if (n < 2 || *chunk == 0) return false;
  *fp = fpb;
  return true;
}

void load_done(const std::string& game, std::set<unsigned long long>* out) {
  out->clear();
  if (FILE* f = std::fopen(path_of(game, ".done").c_str(), "r")) {
    unsigned long long v;
    while (std::fscanf(f, "%llu", &v) == 1) out->insert(v);
    std::fclose(f);
  }
}

unsigned long long done_bytes(const std::set<unsigned long long>& d, unsigned long long total, unsigned long long chunk) {
  unsigned long long b = 0;
  for (unsigned long long off : d) b += std::min(chunk, total > off ? total - off : 0ull);
  return b;
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
struct FsSink : ps5inst::Sink {
  std::string root, cur, tmp;
  bool per_file_rename;
  int fd = -1, err = 0;
  std::set<std::string> dirs;
  FsSink(const std::string& r, bool prf) : root(r), per_file_rename(prf) {}
  ~FsSink() override { if (fd >= 0) close(fd); }
  bool ensure(const std::string& full) {
    if (dirs.count(full)) return true;
    mkdir_p(full.c_str());
    dirs.insert(full);
    if (!dir_exists(full)) { err = errno; return false; }
    return true;
  }
  bool make_dir(const std::string& rel) override { return ensure(root + "/" + rel); }
  bool open_file(const std::string& rel, uint64_t) override {
    const size_t sl = rel.rfind('/');
    if (sl != std::string::npos && !ensure(root + "/" + rel.substr(0, sl))) return false;
    cur = root + "/" + rel;
    tmp = per_file_rename ? cur + ".part" : cur;
    fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { err = errno; return false; }
    return true;
  }
  bool write(const char* p, size_t n) override {
    while (n) {
      const ssize_t w = ::write(fd, p, n);
      if (w <= 0) { err = errno; return false; }
      p += w; n -= size_t(w);
    }
    return true;
  }
  bool close_file() override {
    const int r = close(fd);
    fd = -1;
    if (r != 0) { err = errno; return false; }
    if (per_file_rename && rename(tmp.c_str(), cur.c_str()) != 0) { err = errno; return false; }
    return true;
  }
};

std::string clean_token(const std::string& s) {
  std::string o;
  for (char c : s) if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '-') o += c;
  return o.substr(0, 15);
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
    busy = (ph == UPLOADING && g.last_io.load() && (long)time(nullptr) - g.last_io.load() < 10) || ph == VERIFYING || ph == QUEUED || ph == IMPORTING;
    if (!busy) {
      g.err[0] = 0;
      std::snprintf(g.serial, sizeof g.serial, "%s", serial.c_str());
      std::snprintf(g.region, sizeof g.region, "%s", region.c_str());
      g.bytes = 0; g.total = total; g.speed = 0; g.sample_bytes = 0; g.sample_t = 0;
      g.t0 = (long)time(nullptr); g.t_end = 0; g.last_io = g.t0.load();
      g.cancelling = false; g.installing = true;
      g.phase = IMPORTING;
      g_last_up = gi;
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
  uint64_t files = 0;
  {
    mkdir_p(base.c_str());
    if (!add) rm_rf(stage_dir);
    mkdir_p(stage_dir.c_str());
    FsSink sink(stage_dir, add);
    std::unique_ptr<ps5inst::Receiver> rx(new ps5inst::Receiver(&sink, total));  // ~130 KB of tables: heap, the thread stack is small
    bool ok = pending.empty() || rx->feed(pending.data(), pending.size());
    pending.clear();
    while (ok && !rx->finished()) {
      if (g.cancelling.load()) { key = "cancelled"; break; }
      g.bytes = rx->raw_done();
      const ssize_t r = recv(fd, buf.data(), buf.size(), 0);
      if (r <= 0) { key = "net"; break; }
      g.last_io = (long)time(nullptr);
      ok = rx->feed(buf.data(), size_t(r));
    }
    if (key.empty() && !ok) {
      const std::string e = rx->error();
      key = e == "io" ? ((sink.err == ENOSPC || sink.err == EDQUOT) ? "no_space" : "io") : "bad_contents";
      ps5_log("install: %s failed: %s (errno %d)", game.c_str(), e.c_str(), sink.err);
    }
    if (key.empty() && !(rx->finished() && rx->raw_done() == total)) key = "bad_contents";
    files = rx->files();
  }
  if (key.empty()) {
    if (add) {
      // files are already in place
    } else {
      if (FILE* f = std::fopen((stage_dir + "/.ps5ready").c_str(), "w")) {
        std::fprintf(f, "{\"game\":\"%s\",\"serial\":\"%s\",\"region\":\"%s\",\"time\":%ld,\"source\":\"pc_import\"}\n", game.c_str(), serial.c_str(), region.c_str(), (long)time(nullptr));
        std::fclose(f);
      }
      const std::string old = base + "/data.old";
      if (dir_exists(old)) rm_rf(old);  // leftover of an interrupted earlier swap
      const bool had = dir_exists(data);
      if (had && rename(data.c_str(), old.c_str()) != 0) key = "io";
      else if (rename(stage_dir.c_str(), data.c_str()) != 0) { key = "io"; if (had) rename(old.c_str(), data.c_str()); }
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
  g_installing = false;
  ps5_log("install: %s %s (%llu files, %llu bytes, %ld s)", game.c_str(), key.empty() ? "ok" : key.c_str(), (unsigned long long)files, total,
          (long)time(nullptr) - g.t0.load());
  char b[160];
  if (key.empty()) {
    std::snprintf(b, sizeof b, "{\"ok\":true,\"files\":%llu,\"bytes\":%llu,\"mode\":\"%s\"}", (unsigned long long)files, total, add ? "add" : "replace");
    reply(fd, 200, J, b, false);
  } else {
    std::snprintf(b, sizeof b, "{\"error\":\"%s\"}", key.c_str());
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
        respond(fd, 200, "application/json", "{\"install_api\":1,\"max_frame\":16777216,\"codecs\":[\"raw\",\"deflate\"],\"busy\":" + std::string(g_installing.load() ? "true" : "false") + "}", keep);
      } else if (method == "PUT" && path == "/api/install" && gi >= 0) {
        handle_install(fd, gi, query, pending, buf);
        goto done;
      } else if (path == "/api/settings") {
        const std::string v = query_value(query, "delete_iso");
        if (method == "POST" && (v == "0" || v == "1")) {
          mkdir_p("/data/opengoal/config");
          if (FILE* f = std::fopen(kSettingsFile, "w")) { std::fputs(v.c_str(), f); std::fclose(f); }
        }
        respond(fd, 200, "application/json", status_json(), keep);
      } else if (method == "POST" && path == "/api/begin" && gi >= 0) {
        GameSt& g = g_g[gi];
        const unsigned long long total = strtoull(query_value(query, "total").c_str(), nullptr, 10);
        unsigned long long chunk = strtoull(query_value(query, "chunk").c_str(), nullptr, 10);
        if (chunk < (1ull << 20) || chunk > (256ull << 20)) chunk = kDefaultChunk;
        const std::string fp = query_value(query, "fp").substr(0, 200);
        const int ph = g.phase.load();
        mkdir_p(kImportDir);
        if (total == 0) {
          respond(fd, 400, "application/json", "{\"error\":\"total\"}", keep);
        } else if (ph == VERIFYING || ph == QUEUED || ph == IMPORTING) {
          respond(fd, 409, "application/json", "{\"error\":\"busy\"}", keep);
        } else {
          // resume when the same file (fingerprint, size, chunk size) was partly uploaded before
          unsigned long long mt = 0, mc = 0;
          std::string mfp;
          struct stat pst;
          const bool resume = !fp.empty() && read_meta(game, &mt, &mc, &mfp) && mt == total && mc == chunk && mfp == fp &&
                              stat(path_of(game, ".part").c_str(), &pst) == 0 && (unsigned long long)pst.st_size == total;
          std::string offs;
          if (resume) {
            std::lock_guard<std::mutex> l(g_mu);
            if (g.phase.load() != UPLOADING || g.fp != fp) load_done(game, &g.done);
            g.bytes = done_bytes(g.done, total, chunk);
            for (unsigned long long o : g.done) offs += (offs.empty() ? "" : ",") + std::to_string(o);
          } else {
            // no free-space probe: statvfs crashes on the PS5 SDK (stub); a full disk shows up as a write error (409 io / failed)
            const bool low = false;
            if (low) { respond(fd, 409, "application/json", "{\"error\":\"no_space\"}", keep); goto next; }
            remove_upload_files(game);
            int out = open(path_of(game, ".part").c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0666);
            if (out < 0) { respond(fd, 409, "application/json", "{\"error\":\"io\"}", keep); goto next; }
            if (ftruncate(out, off_t(total)) != 0) {}  // sparse preallocation: chunks arrive out of order
            close(out);
            write_meta(game, total, chunk, fp.empty() ? "-" : fp);
            std::lock_guard<std::mutex> l(g_mu);
            g.done.clear();
            g.bytes = 0;
          }
          g.total = total;
          g.chunk = chunk;
          g_last_up = gi;
          {
            std::lock_guard<std::mutex> l(g_mu);
            g.err[0] = 0; g.serial[0] = 0; g.region[0] = 0;
            g.fp = fp;
          }
          g.speed = 0;
          g.sample_bytes = g.bytes.load();
          g.up0 = (long)time(nullptr);
          g.last_io = (long)time(nullptr);
          g.cancelling = false;
          g.phase = UPLOADING;
          respond(fd, 200, "application/json", std::string("{\"resume\":[") + offs + "],\"chunk\":" + std::to_string(chunk) + ",\"status\":" + status_json() + "}", keep);
        }
      } else if (method == "PUT" && path == "/api/chunk" && gi >= 0) {
        GameSt& g = g_g[gi];
        unsigned long long off = strtoull(query_value(query, "off").c_str(), nullptr, 10);
        if (g.phase.load() != UPLOADING) { respond(fd, 409, "text/plain", "no upload in progress", false); goto done; }
        int out = open(path_of(game, ".part").c_str(), O_WRONLY, 0666);  // created by /api/begin
        if (out < 0) { respond(fd, 400, "text/plain", "cannot open file", false); goto done; }
        const unsigned long long total = g.total.load(), chunk = g.chunk.load();
        const unsigned long long want_len = off < total ? std::min(chunk, total - off) : 0;
        unsigned long long left = clen, pos = off, written = 0;
        bool ok = off < total && off + clen <= total;
        if (ok && !pending.empty()) {  // body bytes that arrived with the head
          size_t n = pending.size() < left ? pending.size() : size_t(left);
          if (pwrite(out, pending.data(), n, off_t(pos)) != ssize_t(n)) ok = false;
          pos += n; left -= n; written += n; g.bytes += n;
          pending.erase(0, n);
        }
        while (ok && left) {
          if (g.phase.load() != UPLOADING) { ok = false; break; }  // cancelled meanwhile
          size_t want = left < buf.size() ? size_t(left) : buf.size();
          ssize_t r = recv(fd, buf.data(), want, 0);
          if (r <= 0) { ok = false; break; }
          if (pwrite(out, buf.data(), size_t(r), off_t(pos)) != r) { ok = false; break; }
          pos += size_t(r); left -= size_t(r); written += size_t(r); g.bytes += size_t(r);
          g.last_io = (long)time(nullptr);
        }
        close(out);
        if (!ok) {
          g.bytes -= std::min<unsigned long long>(written, g.bytes.load());  // the half chunk is sent again
          goto done;
        }
        {
          std::lock_guard<std::mutex> l(g_mu);
          if (clen == want_len && off % chunk == 0) {
            if (!g.done.insert(off).second) {
              g.bytes -= std::min<unsigned long long>(written, g.bytes.load());  // duplicate of a finished chunk
            } else if (FILE* f = std::fopen(path_of(game, ".done").c_str(), "a")) {
              std::fprintf(f, "%llu\n", off);
              std::fclose(f);
            }
          } else {
            g.bytes -= std::min<unsigned long long>(written, g.bytes.load());  // odd-sized piece: not resumable, not counted
          }
        }
        respond(fd, 204, "text/plain", "", keep);
      } else if (method == "POST" && path == "/api/start" && gi >= 0) {
        GameSt& g = g_g[gi];
        bool complete;
        {
          std::lock_guard<std::mutex> l(g_mu);
          const unsigned long long total = g.total.load(), chunk = g.chunk.load();
          complete = g.phase.load() == UPLOADING && g.done.size() == (total + chunk - 1) / chunk;
        }
        int expect = UPLOADING;
        if (!complete) {
          respond(fd, 409, "application/json", status_json(), keep);
        } else if (!g.phase.compare_exchange_strong(expect, VERIFYING)) {
          respond(fd, 409, "application/json", status_json(), keep);
        } else {
          std::string part = path_of(game, ".part"), iso = path_of(game, ".iso");
          char serial[16], gm[8], region[8];
          rename(part.c_str(), iso.c_str());
          unlink(path_of(game, ".meta").c_str());
          unlink(path_of(game, ".done").c_str());
          const char* bad = ps5_iso_probe(iso.c_str(), serial, gm, region);
          if (!bad && game != gm) bad = "wrong_game";
          if (bad) {
            unlink(iso.c_str());
            set_err(gi, bad);
            respond(fd, 422, "application/json", status_json(), keep);
          } else {
            {
              std::lock_guard<std::mutex> l(g_mu);
              std::snprintf(g.serial, sizeof g.serial, "%s", serial);
              std::snprintf(g.region, sizeof g.region, "%s", region);
              g_queue.push_back(gi);
              g.phase = QUEUED;
            }
            respond(fd, 200, "application/json", status_json(), keep);
          }
        }
      } else if (method == "POST" && path == "/api/cancel" && gi >= 0) {
        GameSt& g = g_g[gi];
        std::lock_guard<std::mutex> l(g_mu);
        const int ph = g.phase.load();
        if (ph == UPLOADING) {
          g.phase = IDLE;  // in-flight chunk requests notice this and stop
          g.bytes = 0;
          g.done.clear();
          remove_upload_files(game);
        } else if (ph == QUEUED) {
          g_queue.erase(std::remove(g_queue.begin(), g_queue.end(), gi), g_queue.end());
          remove_iso(game);
          g.phase = IDLE;
        } else if (ph == IMPORTING) {
          g.cancelling = true;
          if (g_cur == gi) ps5_import_cancel();
        } else if (ph == DONE || ph == FAILED) {
          g.phase = IDLE;
        }
        respond(fd, 200, "application/json", "{\"ok\":true}", keep);
      } else {
        respond(fd, 404, "text/plain", "not found", keep);
      }
    next:
      if (!keep) goto done;
    }
  }
done:
  close(fd);
  return nullptr;
}

// Runs the queued imports one after another, records each result, samples the upload speed.
void* queue_loop(void*) {
  int tick = 0;
  for (;;) {
    usleep(200 * 1000);
    const int ist = ps5_import_state();
    const double now_m = mono();
    std::lock_guard<std::mutex> l(g_mu);
    for (int i = 0; i < 3; ++i) {  // upload speed: exponential average over ~1 s
      GameSt& g = g_g[i];
      if (g.phase.load() != UPLOADING && !g.installing.load()) { g.speed = 0; g.sample_t = 0; continue; }
      const unsigned long long b = g.bytes.load();
      if (g.sample_t > 0 && now_m > g.sample_t) {
        const double v = (b >= g.sample_bytes ? double(b - g.sample_bytes) : 0.0) / (now_m - g.sample_t);
        g.speed = unsigned(g.speed.load() * 0.7 + v * 0.3);
      }
      g.sample_bytes = b;
      g.sample_t = now_m;
    }
    if (++tick % 50 == 0 && sceSystemServicePowerTick && (ist == 1 || g_cur >= 0)) sceSystemServicePowerTick();  // every 10 s while busy
    if (g_cur >= 0 && (ist == 2 || ist == 3)) {
      GameSt& g = g_g[g_cur];
      g.t_end = (long)time(nullptr);
      if (ist == 2) {
        g.phase = DONE;
      } else {
        std::snprintf(g.err, sizeof g.err, "%s", ps5_import_reason()[0] ? ps5_import_reason() : "extract");
        g.phase = FAILED;
      }
      g.cancelling = false;
      if (delete_iso_setting()) remove_iso(kIds[g_cur]);  // free the space whatever the outcome
      g_cur = -1;
    }
    if (g_cur < 0 && ist != 1 && !g_queue.empty()) {
      const int i = g_queue.front();
      const std::string iso = path_of(kIds[i], ".iso"), proj = std::string("/data/opengoal/proj_") + kIds[i];
      g_g[i].t0 = (long)time(nullptr);
      g_g[i].t_end = 0;
      if (ps5_import_start(kIds[i], iso.c_str(), proj.c_str())) {
        g_queue.pop_front();
        g_cur = i;
        g_g[i].phase = IMPORTING;
      }
    }
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
  ps5_log("web: import page on port %d", port);
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

// After an app restart: pick up half-finished uploads so the page shows them and the same file can resume.
void restore_uploads() {
  for (int i = 0; i < 3; ++i) {
    unsigned long long total = 0, chunk = 0;
    std::string fp;
    struct stat st;
    if (!read_meta(kIds[i], &total, &chunk, &fp) || stat(path_of(kIds[i], ".part").c_str(), &st) != 0 || (unsigned long long)st.st_size != total) continue;
    GameSt& g = g_g[i];
    std::lock_guard<std::mutex> l(g_mu);
    load_done(kIds[i], &g.done);
    g.total = total;
    g.chunk = chunk;
    g.fp = fp;
    g.bytes = done_bytes(g.done, total, chunk);
    g.phase = UPLOADING;  // stalled until the page re-sends the file (status "idle" seconds grow)
    g_last_up = i;
  }
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
  restore_uploads();
  pthread_t th;
  pthread_create(&th, nullptr, accept_loop, reinterpret_cast<void*>(intptr_t(port)));
  pthread_detach(th);
  if (pthread_create(&th, nullptr, queue_loop, nullptr) == 0) pthread_detach(th);
}

extern "C" const char* ps5_web_ip() { return g_ip.c_str(); }
extern "C" void ps5_web_progress(unsigned long long* bytes, unsigned long long* total, char* game16) {
  const GameSt& g = g_g[g_last_up.load()];
  *bytes = g.bytes.load();
  *total = g.total.load();
  std::snprintf(game16, 16, "%s", kIds[g_last_up.load()]);
}

// ---- stable C API for the launcher (include/ps5import.h) ------------------------------------------------------------
extern "C" int ps5_game_status(const char* game, Ps5GameStatus* out) {
  const int i = game ? gidx(game) : -1;
  if (i < 0 || !out) return -1;
  std::lock_guard<std::mutex> l(g_mu);
  fill_locked(i, out);
  return 0;
}

extern "C" const char* ps5_import_queue_text() {
  static std::string t;  // no thread_local: the PS5 SDK has no __cxa_thread_atexit_impl; guarded by g_mu
  static const char* const kVerb[] = {"", "preparing", "unpacking", "decompiling", "compiling"};
  std::lock_guard<std::mutex> l(g_mu);
  t.clear();
  int pick = -1;
  for (int i = 0; i < 3; ++i)
    if (g_g[i].phase.load() == IMPORTING) pick = i;
  if (pick < 0)
    for (int i = 0; i < 3; ++i)
      if (g_g[i].phase.load() == UPLOADING || g_g[i].phase.load() == VERIFYING) pick = i;
  if (pick >= 0) {
    Ps5GameStatus s;
    fill_locked(pick, &s);
    char b[96];
    if (s.phase == IMPORTING && g_g[pick].installing.load()) {
      std::snprintf(b, sizeof b, "%s: installing %d%%", kTitles[pick], s.percent < 0 ? 0 : s.percent);
    } else if (s.phase == IMPORTING) {
      const char* v = kVerb[s.stage];
      if (s.stage_percent >= 0) std::snprintf(b, sizeof b, "%s: %s %d%%", kTitles[pick], v, s.stage_percent);
      else std::snprintf(b, sizeof b, "%s: %s", kTitles[pick], v[0] ? v : "starting");
    } else if (s.phase == UPLOADING) {
      std::snprintf(b, sizeof b, "%s: uploading %d%%", kTitles[pick], s.percent < 0 ? 0 : int(s.total ? 100 * s.bytes / s.total : 0));
    } else {
      std::snprintf(b, sizeof b, "%s: checking disc", kTitles[pick]);
    }
    t = b;
    if (!g_queue.empty()) t += " (+" + std::to_string(g_queue.size()) + " waiting)";
  } else if (!g_queue.empty()) {
    t = std::string(kTitles[g_queue.front()]) + ": waiting";
  }
  return t.c_str();
}
