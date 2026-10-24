#!/usr/bin/env python3
"""Driver patch 40 (diagnostic): why does ps5_agc_writes_scanout() say yes (target pool unknown vs target inside the pool)?"""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_runtime_backend.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_scanout_reasons" in s:
    print("already patched")
    raise SystemExit

old = """   const uintptr_t first = (uintptr_t)ps5_agc_scanout_target;
   if (!first)
      return true;
   for (unsigned i = 0; i < ps5_agc_mrt_count; ++i) {
      if (!(ps5_agc_mrt_mask & (UINT32_C(0xf) << (4 * i))))
         continue;
      const uintptr_t target = (uintptr_t)ps5_agc_mrt_targets[i];
      if (!target || (target >= first && target - first < PS5_AGC_FRAMEBUFFER_POOL_BYTES))
         return true;
   }
   return false;"""
new = """   const uintptr_t first = (uintptr_t)ps5_agc_scanout_target;
   ++ps5_wr_calls;
   if (!first) {
      ++ps5_wr_nopool;
      return true;
   }
   for (unsigned i = 0; i < ps5_agc_mrt_count; ++i) {
      if (!(ps5_agc_mrt_mask & (UINT32_C(0xf) << (4 * i))))
         continue;
      const uintptr_t target = (uintptr_t)ps5_agc_mrt_targets[i];
      if (!target) {
         ++ps5_wr_notarget;
         return true;
      }
      if (target >= first && target - first < PS5_AGC_FRAMEBUFFER_POOL_BYTES) {
         ++ps5_wr_inpool;
         return true;
      }
   }
   return false;"""
assert s.count(old) == 1
s = s.replace(old, new)

a = s.index("static bool\nps5_agc_writes_scanout(void)")
helper = """static unsigned long long ps5_wr_calls, ps5_wr_nopool, ps5_wr_notarget, ps5_wr_inpool;
void
ps5_driver_scanout_reasons(unsigned long long *calls, unsigned long long *nopool, unsigned long long *notarget,
                           unsigned long long *inpool)
{
   *calls = ps5_wr_calls; *nopool = ps5_wr_nopool; *notarget = ps5_wr_notarget; *inpool = ps5_wr_inpool;
}
"""
s = s[:a] + helper + s[a:]
open(P, "w", encoding="utf-8").write(s)
print("ok")
