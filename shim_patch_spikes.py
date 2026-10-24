#!/usr/bin/env python3
"""Shim patch (agent spikes): per-thread CPU mask and scheduling class from /data/opengoal/config/threadpol.txt.
Without that file nothing changes. File format, one line per thread, '#' lines ignored:
    <name> <cpu mask hex, 0 = leave> <class, 0 = leave> <prio>
  name  = the engine thread name given to ps5_thread_register (IOP, DMP, EE-Worker, EE, ...; see the 'threads:' log line)
          or RENDER for the thread that calls SDL_GL_SwapWindow (applied at its first swap, before renderpin.txt)
  class = rtprio_thread class: 2 realtime round robin, 10 realtime FIFO, 3 timeshare, 4 idle; prio 0 (best) to 31
Every line logs 'threadpol: <name> mask=.. rc=.. class=.. prio=.. rc=..'.
usage: python3 shim_patch_spikes.py        (root: env PS5_SHIM_DIR, default <this dir>/ps5shim; edits ps5sdl.cpp)"""
import os

d = os.environ.get("PS5_SHIM_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps5shim"))
P = os.path.join(d, "ps5sdl.cpp")
s = open(P, encoding="utf-8").read()
if "ps5_apply_thread_policy" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


rep("#include <sys/cpuset.h>\n", "#include <sys/cpuset.h>\n#include <sys/rtprio.h>\n")
rep('extern "C" void ps5_thread_register(const char* name) {\n', r'''static void ps5_apply_thread_policy(const char* name) {
  FILE* f = std::fopen("/data/opengoal/config/threadpol.txt", "r");
  if (!f) return;
  char line[160], nm[32];
  while (std::fgets(line, sizeof line, f)) {
    unsigned long long mask = 0;
    int cls = 0, prio = 0;
    if (line[0] == '#' || std::sscanf(line, "%31s %llx %d %d", nm, &mask, &cls, &prio) != 4 || std::strcmp(nm, name) != 0) continue;
    int rc_a = 0, rc_p = 0;
    if (mask) {
      cpuset_t set;
      CPU_ZERO(&set);
      for (int c = 0; c < 64; ++c)
        if ((mask >> c) & 1) CPU_SET(c, &set);
      rc_a = cpuset_setaffinity(CPU_LEVEL_WHICH, CPU_WHICH_TID, -1, 8, &set);
    }
    if (cls) {
      struct rtprio rp;
      rp.type = (u_short)cls;
      rp.prio = (u_short)prio;
      rc_p = rtprio_thread(RTP_SET, 0, &rp);
    }
    ps5_log("threadpol: %s mask=%llx rc=%d class=%d prio=%d rc=%d", name, mask, rc_a, cls, prio, rc_p);
  }
  std::fclose(f);
}
extern "C" void ps5_thread_register(const char* name) {
''')
rep("  g_threads[i].last_cpu = 0;\n  static std::atomic<bool> installed{false};",
    "  g_threads[i].last_cpu = 0;\n  ps5_apply_thread_policy(name);\n  static std::atomic<bool> installed{false};")
rep("""      pin_done = true;
      if (FILE* pf = std::fopen("/data/opengoal/config/renderpin.txt", "r")) {""",
    """      pin_done = true;
      ps5_apply_thread_policy("RENDER");
      if (FILE* pf = std::fopen("/data/opengoal/config/renderpin.txt", "r")) {""")
open(P, "w", encoding="utf-8").write(s)
print("ok")
