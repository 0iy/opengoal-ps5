#!/usr/bin/env python3
"""Driver patch 28 (diagnostic): count CPU-access drains of buffers that are still referenced by queued draws
(ps5_draw_batch_drain_buffer): how often they force a submit + full GPU wait, how often they wait for one in-flight batch,
how many ns they block. Reported by ps5_driver_drainbuf_stats()."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_drainbuf_stats" in s:
    print("already patched")
    raise SystemExit

anchor = "static void\nps5_draw_batch_drain_buffer_impl_marker;"
# helper block placed right before the function definition
fn_head = "ps5_draw_batch_drain_buffer(struct pipe_resource *base)\n{"
assert s.count(fn_head) == 1
i = s.index(fn_head)
# find the start of the preceding "static void\n" line
j = s.rfind("static void\n", 0, i)
stats = """static unsigned long long ps5_dbs_calls, ps5_dbs_current, ps5_dbs_inflight, ps5_dbs_ns;
void
ps5_driver_drainbuf_stats(unsigned long long *calls, unsigned long long *current,
                          unsigned long long *inflight, unsigned long long *ns)
{
   *calls = ps5_dbs_calls; *current = ps5_dbs_current; *inflight = ps5_dbs_inflight; *ns = ps5_dbs_ns;
}

"""
s = s[:j] + stats + s[j:]

old = """   if (ps5_deferred_batch_overlaps(&ps5_deferred, buffer)) {
      ps5_draw_batch_flush_locked();
      ps5_draw_batch_retire_locked(true);
   } else {"""
new = """   ++ps5_dbs_calls;
   if (ps5_deferred_batch_overlaps(&ps5_deferred, buffer)) {
      const int64_t dbs_t0 = os_time_get_nano();
      ps5_draw_batch_flush_locked();
      ps5_draw_batch_retire_locked(true);
      ++ps5_dbs_current;
      ps5_dbs_ns += (unsigned long long)(os_time_get_nano() - dbs_t0);
   } else {"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """            const uint64_t sequence =
               ps5_inflight[(ps5_inflight_head + i) % PS5_INFLIGHT_BATCH_CAPACITY].sequence;
            while (ps5_completed_sequence < sequence &&
                   ps5_draw_batch_retire_one_locked(true)) {}
            break;"""
new = """            const uint64_t sequence =
               ps5_inflight[(ps5_inflight_head + i) % PS5_INFLIGHT_BATCH_CAPACITY].sequence;
            const int64_t dbs_t0 = os_time_get_nano();
            const bool dbs_wait = ps5_completed_sequence < sequence;
            while (ps5_completed_sequence < sequence &&
                   ps5_draw_batch_retire_one_locked(true)) {}
            if (dbs_wait) {
               ++ps5_dbs_inflight;
               ps5_dbs_ns += (unsigned long long)(os_time_get_nano() - dbs_t0);
            }
            break;"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
