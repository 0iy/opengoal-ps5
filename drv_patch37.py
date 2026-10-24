#!/usr/bin/env python3
"""Driver patch 37 (diagnostic): back-pressure waits. How often and how long ps5_draw_batch_flush_locked blocks because
all PS5_INFLIGHT_BATCH_CAPACITY batches are in flight (the GPU is behind the CPU)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_backpressure_stats" in s:
    print("already patched")
    raise SystemExit

old = """      ps5_draw_batch_retire_locked(false);
      if (ps5_inflight_count == PS5_INFLIGHT_BATCH_CAPACITY)
         ps5_draw_batch_retire_one_locked(true);
      if (ps5_agc_gate2_batch_submit() != 0) {"""
new = """      ps5_draw_batch_retire_locked(false);
      ++ps5_bp_flushes;
      if (ps5_inflight_count == PS5_INFLIGHT_BATCH_CAPACITY) {
         const int64_t bp_t0 = os_time_get_nano();
         ps5_draw_batch_retire_one_locked(true);
         ++ps5_bp_waits;
         ps5_bp_ns += (unsigned long long)(os_time_get_nano() - bp_t0);
      }
      {
         const int64_t sub_t0 = os_time_get_nano();
         const int sub_rc = ps5_agc_gate2_batch_submit();
         ps5_bp_submit_ns += (unsigned long long)(os_time_get_nano() - sub_t0);
         if (sub_rc != 0) {
            fputs("[ps5-gallium] deferred batch submission failed; terminating before resource release\\n", stderr);
            fflush(stderr);
            _Exit(EXIT_FAILURE);
         }
      }
      if (0) {"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

a = s.index("static void\nps5_draw_batch_flush_locked(void)")
helper = """static unsigned long long ps5_bp_flushes, ps5_bp_waits, ps5_bp_ns, ps5_bp_submit_ns;
void
ps5_driver_backpressure_stats(unsigned long long *flushes, unsigned long long *waits, unsigned long long *wait_ns,
                              unsigned long long *submit_ns)
{
   *flushes = ps5_bp_flushes; *waits = ps5_bp_waits; *wait_ns = ps5_bp_ns; *submit_ns = ps5_bp_submit_ns;
}

"""
s = s[:a] + helper + s[a:]
open(P, "w", encoding="utf-8").write(s)
print("ok")
