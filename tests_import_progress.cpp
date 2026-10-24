// Host-side test of ps5shim/import_progress.h:  g++ -std=c++17 -I ps5shim tests_import_progress.cpp -o /tmp/tip && /tmp/tip
#include <cassert>
#include <cstdio>
#include "import_progress.h"
using namespace ps5imp;
int main() {
  for (int g = 0; g < 3; ++g) {
    int sum = kUpW + kVerW;
    for (int s = 0; s < 4; ++s) sum += kStageW[g][s];
    assert(sum == 100);
  }
  assert(overall(1, IDLE, 0, -1, 0) == -1);
  assert(overall(1, UPLOADING, 0, -1, 0) == 0);
  assert(overall(1, UPLOADING, 0, -1, 1.0) == kUpW);
  assert(overall(1, QUEUED, 0, -1, 1) == kUpW + kVerW);
  assert(overall(1, DONE, 0, -1, 1) == 100);
  int last = -1;  // monotonic through the whole import
  for (int st = PREPARE; st <= COMPILE; ++st)
    for (int p = 0; p <= 100; p += 5) {
      int v = overall(0, IMPORTING, st, p, 1);
      assert(v >= last && v <= 99);
      last = v;
    }
  assert(overall(0, IMPORTING, COMPILE, 100, 1) == 99);
  assert(overall(0, IMPORTING, EXTRACT, -1, 1) == kUpW + kVerW + kStageW[0][0]);
  assert(overall(5, IMPORTING, 1, 0, 0) == -1);
  // eta
  assert(eta(UPLOADING, 100, 1100, 100, 5, 3) == 10);
  assert(eta(UPLOADING, 100, 1100, 0, 5, 3) == -1);
  assert(eta(IMPORTING, 0, 0, 0, 12, 100) == -1);                 // nothing done yet
  assert(eta(IMPORTING, 0, 0, 0, 12 + 44, 100) == 100 * 44 / 44);  // half of the 88 import points in 100 s -> 100 s left
  // tracker: extract
  Tracker t;
  t.reset(1, 1000);
  t.set_stage(EXTRACT);
  t.feed("Extracting A.DGO, size 0x64 offset 0x0...");
  assert(t.stage_pct == 0);
  t.feed("Extracting B.DGO, size 0x64 offset 0x64...");
  assert(t.stage_pct == 10);
  t.feed("Extracting C, size 0x3e8 offset 0x64...");
  assert(t.stage_pct == 20);
  t.set_stage(DECOMPILE);
  assert(t.stage_pct == 0);
  t.feed("[Mem] After link data: 5 MB");
  assert(t.stage_pct == 18);
  t.feed("[Mem] After init: 1");  // never goes backwards
  assert(t.stage_pct == 18);
  t.feed("[Mem] After textures: 9");
  assert(t.stage_pct == 52);
  for (int i = 0; i < 100; ++i) t.feed("stats for x");
  assert(t.stage_pct >= 52 && t.stage_pct < 96);
  t.feed("[Mem] After extraction: 9");
  assert(t.stage_pct == 96);
  t.feed("Decompiler has finished successfully in 3 seconds.");
  assert(t.stage_pct == 100);
  t.set_stage(COMPILE);
  assert(t.stage_pct == -1);
  t.progress(COMPILE, 50, 200);
  assert(t.stage_pct == 25);
  t.progress(DECOMPILE, 1, 2);  // wrong stage ignored
  assert(t.stage_pct == 25);
  std::puts("import_progress: all tests passed");
}
