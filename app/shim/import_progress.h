// Pure progress logic for the ISO import (no I/O, no globals): stage weights, log-line parsing, overall percent, ETA.
// Used by importer.cpp / webserver.cpp and by tests/host/import_progress_test.cpp on the host.
//
// WEIGHTS ARE ESTIMATES. No import timing logs exist on this machine; the split below is a plausible default
// (the goalc "(mi)" build of all game code is single threaded and dominates, level extraction second).
// Re-measure from the "import: stage ..." lines in the console log and edit kStageW.
#pragma once
#include <cstdlib>
#include <cstring>

namespace ps5imp {

enum Phase { IDLE, UPLOADING, VERIFYING, QUEUED, IMPORTING, DONE, FAILED };
enum Stage { NONE, PREPARE, EXTRACT, DECOMPILE, COMPILE };

// Overall percent bands (sum 100): upload, verify, then the import stages, per game {prepare, extract, decompile, compile}.
constexpr int kUpW = 10, kVerW = 2;
constexpr int kStageW[3][4] = {{1, 10, 24, 53},   // jak1  (smallest game code base)
                               {1, 11, 25, 51},   // jak2
                               {1, 11, 25, 51}};  // jak3
// Expected number of "stats for <level>" lines in the level extraction (progress inside the decompile stage). Estimates.
constexpr int kLevels[3] = {22, 30, 30};

// Overall 0..100 for one game. stage_pct < 0 counts as 0 inside the stage. up_frac in 0..1.
inline int overall(int gi, int phase, int stage, int stage_pct, double up_frac) {
  if (gi < 0 || gi > 2) return -1;
  const int* w = kStageW[gi];
  double p = 0;
  switch (phase) {
    case IDLE: return -1;
    case UPLOADING: p = kUpW * (up_frac < 0 ? 0 : up_frac > 1 ? 1 : up_frac); break;
    case VERIFYING: p = kUpW + kVerW * 0.5; break;
    case QUEUED: p = kUpW + kVerW; break;
    case IMPORTING: {
      p = kUpW + kVerW;
      const double f = stage_pct < 0 ? 0 : stage_pct > 100 ? 1 : stage_pct / 100.0;
      for (int s = PREPARE; s <= COMPILE; ++s) {
        if (s < stage) p += w[s - 1];
        else if (s == stage) p += w[s - 1] * f;
      }
      break;
    }
    case DONE: return 100;
    default: return -1;
  }
  const int r = int(p + 0.5);
  return r > 99 ? 99 : r;
}

// ETA in seconds, -1 unknown. Upload: bytes left / speed. Import: linear extrapolation from the import's own progress.
inline int eta(int phase, unsigned long long bytes, unsigned long long total, unsigned speed_bps, int overall_pct, int elapsed_s) {
  if (phase == UPLOADING) return (speed_bps > 0 && total > bytes) ? int((total - bytes) / speed_bps) : -1;
  if (phase == IMPORTING) {
    const int start = kUpW + kVerW;
    const int done = overall_pct - start;
    if (done < 3 || elapsed_s < 5) return -1;  // too early to extrapolate
    return int(double(elapsed_s) * (100 - overall_pct) / done);
  }
  return -1;
}

// Parses log lines of the (patched) extractor/decompiler/compiler and tracks per-stage progress. Single writer thread assumed
// per call site; the outputs are plain ints that the reader copies (races only give a slightly stale number).
struct Tracker {
  int game = 0;
  volatile int stage = NONE;
  volatile int stage_pct = -1;
  unsigned long long iso_size = 0;
  unsigned long long ext_done = 0, ext_cur = 0;
  int levels_done = 0;
  int dmark = 0;  // decompile milestone percent

  void reset(int g, unsigned long long iso_bytes) {
    game = g; stage = NONE; stage_pct = -1; iso_size = iso_bytes; ext_done = ext_cur = 0; levels_done = 0; dmark = 0;
  }
  void set_stage(int s) {
    stage = s;
    stage_pct = (s == EXTRACT || s == DECOMPILE) ? 0 : -1;
    if (s == DECOMPILE) { dmark = 0; levels_done = 0; }
  }
  // generic progress call (compile loop hook): done of total
  void progress(int s, long long done, long long total) {
    if (s != stage || total <= 0) return;
    int p = int(100 * done / total);
    stage_pct = p > 100 ? 100 : p < 0 ? 0 : p;
  }
  void feed(const char* m) {
    if (stage == EXTRACT) {
      if (!std::strncmp(m, "Extracting ", 11)) {
        ext_done += ext_cur;  // the previous file is finished now
        const char* sz = std::strstr(m, "size 0x");
        ext_cur = sz ? std::strtoull(sz + 7, nullptr, 16) : 0;
        if (iso_size) {
          unsigned long long p = ext_done * 100 / iso_size;
          stage_pct = int(p > 99 ? 99 : p);
        }
      }
    } else if (stage == DECOMPILE) {
      static const struct { const char* key; int pct; } kMarks[] = {
          {"[Mem] After init:", 2},     {"[Mem] After config read:", 4}, {"[Mem] After DB setup:", 8},
          {"[Mem] After link data:", 18}, {"[Mem] After code:", 22},     {"[Mem] After decomp:", 26},
          {"[Mem] After text:", 30},    {"[Mem] After spool handling:", 32}, {"[Mem] After textures:", 52},
          {"[Mem] After extraction:", 96}};
      for (const auto& k : kMarks)
        if (!std::strncmp(m, k.key, std::strlen(k.key))) { if (k.pct > dmark) dmark = k.pct; stage_pct = dmark; return; }
      if (!std::strncmp(m, "stats for ", 10)) {  // one per finished level (and the common data), between "textures" (52) and "extraction" (96)
        ++levels_done;
        const int n = kLevels[game < 0 || game > 2 ? 1 : game];
        const int span = 96 - 52;
        int p = 52 + span * (levels_done > n ? n : levels_done) / (n + 1);
        if (p > dmark) dmark = p;
        stage_pct = dmark;
      }
      if (!std::strncmp(m, "Decompiler has finished", 23)) { dmark = 100; stage_pct = 100; }
    }
  }
};

}  // namespace ps5imp
