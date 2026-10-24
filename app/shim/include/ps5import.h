// Stable C API between the ISO import/onboarding code (importer.cpp, webserver.cpp) and the launcher UI.
#pragma once

struct Ps5GameStatus {
  int installed;
  int phase;          // 0 idle, 1 uploading, 2 verifying, 3 queued, 4 importing, 5 done, 6 failed
  int stage;          // 0 none, 1 prepare, 2 extract, 3 decompile, 4 compile
  int percent;        // overall 0..100 or -1 unknown
  int stage_percent;  // 0..100 or -1
  unsigned long long bytes, total;
  unsigned speed_bps;
  int eta_s;          // -1 unknown
  int elapsed_s;
  char serial[16];
  char region[8];
  char reason[24];
};

#ifdef __cplusplus
extern "C" {
#endif
// game = "jak1" | "jak2" | "jak3". Returns 0 on success, -1 for an unknown game.
int ps5_game_status(const char* game, struct Ps5GameStatus* out);
// One short human line, e.g. "Jak II: decompiling 50%". Empty string when nothing is going on. Pointer valid until the next call.
const char* ps5_import_queue_text();
#ifdef __cplusplus
}
#endif
