#!/usr/bin/env python3
"""Driver patch 30 (diagnostic): count forced buffer drains per caller address (ps5_driver_drainbuf_sites)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_dbs_site_addr" in s:
    print("already patched")
    raise SystemExit

old = "static unsigned long long ps5_dbs_calls, ps5_dbs_current, ps5_dbs_inflight, ps5_dbs_ns;\n"
new = (old +
       "static uintptr_t ps5_dbs_site_addr[16];\n"
       "static unsigned long long ps5_dbs_site_n[16], ps5_dbs_site_bytes[16];\n"
       "unsigned\nps5_driver_drainbuf_sites(uintptr_t *addr, unsigned long long *n, unsigned long long *bytes)\n{\n"
       "   unsigned c = 0;\n"
       "   for (unsigned i = 0; i < 16 && ps5_dbs_site_addr[i]; ++i, ++c) {\n"
       "      addr[i] = ps5_dbs_site_addr[i]; n[i] = ps5_dbs_site_n[i]; bytes[i] = ps5_dbs_site_bytes[i];\n"
       "   }\n   return c;\n}\n")
assert s.count(old) == 1
s = s.replace(old, new)

old = "ps5_draw_batch_drain_buffer(struct pipe_resource *base)\n{"
new = "__attribute__((noinline)) ps5_draw_batch_drain_buffer(struct pipe_resource *base)\n{\n   const uintptr_t dbs_caller = (uintptr_t)__builtin_return_address(0);"
assert s.count(old) == 1
s = s.replace(old, new)

old = "      ++ps5_dbs_current;\n"
new = ("      ++ps5_dbs_current;\n"
       "      for (unsigned si = 0; si < 16; ++si) {\n"
       "         if (ps5_dbs_site_addr[si] == dbs_caller || !ps5_dbs_site_addr[si]) {\n"
       "            ps5_dbs_site_addr[si] = dbs_caller;\n"
       "            ++ps5_dbs_site_n[si];\n"
       "            ps5_dbs_site_bytes[si] += base ? base->width0 : 0;\n"
       "            break;\n"
       "         }\n"
       "      }\n")
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
