// ISO import on the console: runs the OpenGOAL extractor (ISO -> extract -> decompile -> compile) in a worker thread.
// The extractor is built from the jak-project sources (see engine/gen_ps5_extractor.py) and linked into the app.
#include <pthread.h>

#include <mutex>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#include "third-party/zstd/lib/zstd.h"
#include "import_progress.h"

void ps5_log(const char* fmt, ...);
int extractor_main(int argc, char** argv);  // decompiler/extractor/main.cpp, built with -Dmain=extractor_main

extern "C" void ps5_import_stage_set(const char* stage);

namespace {

ps5imp::Tracker g_trk;
std::mutex g_trk_mu;
std::atomic<bool> g_cancel{false};
pthread_t g_import_thread;
std::atomic<bool> g_import_thread_set{false};
struct ImportCancel {};  // thrown on the import thread from the log/progress hooks; deliberately not a std::exception

void check_cancel() {
  if (g_cancel.load() && g_import_thread_set.load() && pthread_equal(pthread_self(), g_import_thread)) throw ImportCancel{};
}

struct ImportJob {
  std::string game;       // jak1 | jak2 | jak3
  std::string iso;        // path of the uploaded ISO
  std::string project;    // project dir with goal_src/, decompiler/config/ ... and the output
};

bool dir_exists(const std::string& p) {
  struct stat st;
  return stat(p.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

void mkdir_p(const std::string& path) {
  std::string cur;
  for (size_t i = 0; i < path.size(); ++i) {
    cur += path[i];
    if (path[i] == '/' && cur.size() > 1) mkdir(cur.c_str(), 0777);
  }
  mkdir(path.c_str(), 0777);
}

// The toolchain pack (open-source sources and configs, no game data) ships as one tar.zst inside the app folder.
// Unpack it into the game's project directory, leaving out the other games' subfolders.
bool unpack_skeleton(const std::string& game, const std::string& dest) {
  const char* kArchive = "/data/homebrew/LAPY77001/assets/skeleton.tar.zst";
  FILE* f = std::fopen(kArchive, "rb");
  if (!f) {
    ps5_log("import: %s missing", kArchive);
    return false;
  }
  std::vector<char> in(1 << 20), chunk(1 << 20);
  std::string tar;
  ZSTD_DStream* ds = ZSTD_createDStream();
  ZSTD_initDStream(ds);
  size_t n;
  bool ok = true;
  while (ok && (n = std::fread(in.data(), 1, in.size(), f)) > 0) {
    ZSTD_inBuffer ib{in.data(), n, 0};
    while (ib.pos < ib.size) {
      ZSTD_outBuffer ob{chunk.data(), chunk.size(), 0};
      const size_t r = ZSTD_decompressStream(ds, &ob, &ib);
      if (ZSTD_isError(r)) { ok = false; break; }
      tar.append(chunk.data(), ob.pos);
    }
  }
  ZSTD_freeDStream(ds);
  std::fclose(f);
  if (!ok) return false;
  static const char* kGames[] = {"jak1", "jak2", "jak3", "jakx"};
  size_t pos = 0;
  std::string long_name;
  int files = 0;
  while (pos + 512 <= tar.size()) {
    const char* h = tar.data() + pos;
    if (h[0] == 0) break;
    std::string name(h, strnlen(h, 100));
    const std::string prefix(h + 345, strnlen(h + 345, 155));
    if (!prefix.empty()) name = prefix + "/" + name;
    const size_t size = std::strtoull(std::string(h + 124, 12).c_str(), nullptr, 8);
    g_trk.stage_pct = int(pos * 100 / tar.size());
    const char type = h[156];
    pos += 512;
    if (type == 'L') {  // GNU long name: the data block holds the next entry's name
      long_name.assign(tar.data() + pos, strnlen(tar.data() + pos, size));
    } else if (type == '0' || type == 0) {
      if (!long_name.empty()) { name = long_name; long_name.clear(); }
      bool skip = false;
      size_t s = 0;
      while (s <= name.size()) {  // skip entries that live under another game's folder
        size_t e = name.find('/', s);
        if (e == std::string::npos) e = name.size();
        const std::string comp = name.substr(s, e - s);
        for (const char* g : kGames) if (comp == g && game != g) skip = true;
        s = e + 1;
      }
      if (!skip && !name.empty() && name.find("..") == std::string::npos) {
        const std::string full = dest + "/" + name;
        mkdir_p(full.substr(0, full.rfind('/')));
        if (FILE* o = std::fopen(full.c_str(), "wb")) {
          std::fwrite(tar.data() + pos, 1, size, o);
          std::fclose(o);
          ++files;
        }
      }
    }
    pos += (size + 511) / 512 * 512;
  }
  ps5_log("import: unpacked %d toolchain files into %s", files, dest.c_str());
  return files > 0;
}

// Known discs (serial from the ELF name, as in decompiler/extractor/extractor_util.cpp). Keep in sync with the table in webpage.cpp.
struct DiscId { const char* serial; const char* game; const char* region; };
const DiscId kDiscs[] = {
    {"SCUS-97124", "jak1", "NTSC-U"}, {"SCES-50361", "jak1", "PAL"}, {"SCPS-15021", "jak1", "NTSC-J"}, {"SCPS-56003", "jak1", "NTSC-K"},
    {"SCUS-97265", "jak2", "NTSC-U"}, {"SCES-51608", "jak2", "PAL"},  {"SCPS-15057", "jak2", "NTSC-J"}, {"SCKA-20010", "jak2", "NTSC-K"},
    {"SCUS-97330", "jak3", "NTSC-U"}, {"SCUS-97516", "jak3", "NTSC-U"}, {"SCES-52460", "jak3", "PAL"},  {"SCKA-20040", "jak3", "NTSC-K"},
};

unsigned le32(const unsigned char* b) { return b[0] | (b[1] << 8) | (b[2] << 16) | (unsigned(b[3]) << 24); }

// Fast structural check of a plain 2048-byte-sector ISO: a handful of preads, no hashing. Returns nullptr when fine, else a reason key.
const char* probe_fd(int fd, char* serial, char* game, char* region) {
  struct stat st;
  if (fstat(fd, &st) != 0) return "io";
  const unsigned long long size = (unsigned long long)st.st_size;
  if (size < (64ull << 20)) return "tiny";
  unsigned char p[2048];
  if (pread(fd, p, sizeof p, 16 * 2048) != ssize_t(sizeof p)) return "notiso";
  if (p[0] != 1 || std::memcmp(p + 1, "CD001", 5) != 0) {
    unsigned char h[12];
    bool raw = pread(fd, h, 12, 0) == 12 && h[0] == 0 && h[11] == 0;
    for (int i = 1; i < 11; ++i) raw = raw && h[i] == 0xFF;
    return raw ? "raw" : "notiso";  // raw: 2352-byte sector .bin
  }
  if (size < (unsigned long long)le32(p + 80) * 2048) return "truncated";  // PVD volume size is exact
  const unsigned lba = le32(p + 158), len = le32(p + 166);
  if (len == 0 || len > (1u << 20)) return "notiso";
  std::vector<unsigned char> d(len);
  if (pread(fd, d.data(), len, off_t(lba) * 2048) != ssize_t(len)) return "notiso";
  bool sys = false, found = false;
  for (size_t pos = 0; pos + 34 <= d.size();) {
    const unsigned rl = d[pos];
    if (rl == 0) { pos = (pos / 2048 + 1) * 2048; continue; }  // records never straddle a sector
    const size_t nl = d[pos + 32];
    if (pos + 33 + nl > d.size()) break;
    const std::string name((const char*)&d[pos + 33], nl);
    if (name == "SYSTEM.CNF;1") sys = true;
    if (!found && name.size() == 13 && name[4] == '_' && name[8] == '.' && name.compare(11, 2, ";1") == 0) {
      std::snprintf(serial, 12, "%.4s-%.3s%.2s", name.c_str(), name.c_str() + 5, name.c_str() + 9);
      found = true;
    }
    pos += rl;
  }
  if (!sys) return "nosys";
  for (const DiscId& k : kDiscs)
    if (found && std::strcmp(k.serial, serial) == 0) {
      std::snprintf(game, 8, "%s", k.game);
      std::snprintf(region, 8, "%s", k.region);
      return nullptr;
    }
  return "unknown";
}

std::atomic<int> g_state{0};  // 0 idle, 1 running, 2 done, 3 failed
std::atomic<int> g_rc{0};
char g_stage[16] = "idle";
char g_game[16] = "";
char g_reason[24] = "";  // failure key for the page: toolchain | unknown_disc | bad_contents | bad_iso | decompile | compile | extract | cancelled

void* run_import(void* arg) {
  auto* job = static_cast<ImportJob*>(arg);
  std::vector<std::string> args = {"extractor", job->iso,        "--proj-path", job->project,
                                   "--game",    job->game,       "--extract",   "--decompile",
                                   "--compile", "--validate"};
  std::vector<char*> argv;
  for (auto& a : args) argv.push_back(a.data());
  argv.push_back(nullptr);
  mkdir_p(job->project);
  {
    struct stat ist;
    std::lock_guard<std::mutex> l(g_trk_mu);
    g_trk.reset(job->game == "jak1" ? 0 : job->game == "jak3" ? 2 : 1, stat(job->iso.c_str(), &ist) == 0 ? (unsigned long long)ist.st_size : 0);
  }
  g_import_thread = pthread_self();
  g_import_thread_set = true;
  if (!dir_exists(job->project + "/goal_src/" + job->game)) {
    ps5_import_stage_set("prepare");
    if (!unpack_skeleton(job->game, job->project)) {
      ps5_log("import: toolchain pack could not be unpacked");
      g_rc = 2;
      std::snprintf(g_reason, sizeof g_reason, "toolchain");
      g_state = 3;
      delete job;
      return nullptr;
    }
  }
  ps5_log("import: start game=%s iso=%s project=%s", job->game.c_str(), job->iso.c_str(), job->project.c_str());
  int rc = 1;
  try {
    rc = extractor_main(int(args.size()), argv.data());
  } catch (const ImportCancel&) {
    ps5_log("import: cancelled");
    rc = 4999;
  } catch (const std::exception& e) {
    ps5_log("import: exception: %s", e.what());
  } catch (...) {
    ps5_log("import: unknown exception");
  }
  g_import_thread_set = false;
  ps5_log("import: finished rc=%d", rc);
  if (rc == 0) g_trk.stage_pct = 100;
  if (rc != 0) {
    const char* r = rc == 4999 ? "cancelled"
                    : rc == 4000 || rc == 4001 || rc == 4002 ? "unknown_disc"
                    : rc == 4010 || rc == 4011 || rc == 4012 || rc == 4020 ? "bad_contents"
                    : rc == 4040 || rc == 4041 ? "bad_iso"
                    : rc == 4030 ? "decompile" : rc == 4050 ? "compile"
                    : !std::strcmp(g_stage, "decompile") ? "decompile" : !std::strcmp(g_stage, "compile") ? "compile" : "extract";
    std::snprintf(g_reason, sizeof g_reason, "%s", r);
  }
  g_rc = rc;
  g_state = rc == 0 ? 2 : 3;
  delete job;
  return nullptr;
}

}  // namespace

// Start an import; returns false if one is already running.
extern "C" bool ps5_import_start(const char* game, const char* iso, const char* project) {
  int expected = 0;
  if (!g_state.compare_exchange_strong(expected, 1)) {
    int s = g_state.load();
    if (s == 1) return false;
    g_state = 1;
  }
  std::snprintf(g_game, sizeof g_game, "%s", game);
  g_reason[0] = 0;
  g_rc = 0;
  g_cancel = false;
  auto* job = new ImportJob{game, iso, project};
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, 256u << 20);  // the decompiler recurses deeply
  pthread_t th;
  if (pthread_create(&th, &attr, run_import, job) != 0) {
    delete job;
    g_state = 3;
    return false;
  }
  pthread_detach(th);
  return true;
}

extern "C" int ps5_import_state() { return g_state.load(); }
extern "C" int ps5_import_rc() { return g_rc.load(); }

// Called from the patched extractor main.cpp at the start of each step.
extern "C" void ps5_import_stage_set(const char* stage) {
  std::snprintf(g_stage, sizeof g_stage, "%s", stage);
  const int id = !std::strcmp(stage, "prepare") ? ps5imp::PREPARE : !std::strcmp(stage, "extract") ? ps5imp::EXTRACT
               : !std::strcmp(stage, "decompile") ? ps5imp::DECOMPILE : !std::strcmp(stage, "compile") ? ps5imp::COMPILE : ps5imp::NONE;
  {
    std::lock_guard<std::mutex> l(g_trk_mu);
    g_trk.set_stage(id);
  }
  ps5_log("import: stage %s", stage);
  check_cancel();
}
extern "C" const char* ps5_import_stage() { return g_stage; }
extern "C" int ps5_import_stage_id() { return g_trk.stage; }
extern "C" int ps5_import_stage_percent() { return g_trk.stage_pct; }
extern "C" int ps5_import_percent() { return g_trk.stage_pct; }
extern "C" const char* ps5_import_game() { return g_game; }
extern "C" void ps5_import_cancel() { g_cancel = true; }

// Hooks called from the patched jak-project (engine/patch_import_progress.py; weak symbols there). Return 1 = keep this line off stdout.
extern "C" int ps5_import_log(int level, const char* msg) {
  if (g_state.load() != 1) return 0;
  {
    std::lock_guard<std::mutex> l(g_trk_mu);
    g_trk.feed(msg);
  }
  check_cancel();
  if (level >= 3) { ps5_log("import: %s", msg); return 0; }  // warn / error / die
  if (level < 0 && (std::strstr(msg, "rror") || std::strstr(msg, "ailed"))) ps5_log("import: %s", msg);
  return 1;
}
extern "C" void ps5_import_progress(int stage, long long done, long long total) {
  if (g_state.load() == 1) {
    std::lock_guard<std::mutex> l(g_trk_mu);
    g_trk.progress(stage, done, total);
  }
  check_cancel();
}
extern "C" const char* ps5_import_reason() { return g_reason; }

// Pre-check an uploaded ISO. Returns nullptr when it is a structurally sound, known disc (serial/game/region filled), else a reason key:
// io | tiny | notiso | raw | truncated | nosys | unknown.
extern "C" const char* ps5_iso_probe(const char* path, char* serial12, char* game8, char* region8) {
  serial12[0] = game8[0] = region8[0] = 0;
  const int fd = open(path, O_RDONLY);
  if (fd < 0) return "io";
  const char* r = probe_fd(fd, serial12, game8, region8);
  close(fd);
  return r;
}
