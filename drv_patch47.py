#!/usr/bin/env python3
"""Driver patch 47: trace hook. ps5_driver_trace_hook(ev, t0_ns, dur_ns, arg) is set by the shim tracer (glfix.cpp).
Events: 100..103 waits per site (ps5_wsite_add, patch 43), 110 forced buffer drain (arg = caller), 111 batch submit,
112 backpressure wait. One pointer global, no other new static data (patch 45 added tables and the app crashed at start)."""
import os

base = os.path.expanduser("~/gl/src/ps5-opengl/src")
rt = os.path.join(base, "platform/ps5_agc_native_runtime.c")
sc = os.path.join(base, "gallium/ps5/ps5_screen.c")


def patch(path, edits, marker):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print(os.path.basename(path), "already patched")
        return
    for old, new in edits:
        assert s.count(old) == 1, (path, s.count(old), old[:70])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)
    print(os.path.basename(path), "ok")


patch(rt, [
    ("static inline void ps5_wsite_add(unsigned site, int64_t t0)\n{\n    int64_t d = os_time_get_nano() - t0;\n    if (d > 0) {",
     "void (*ps5_driver_trace_hook)(unsigned, unsigned long long, unsigned long long, unsigned long long);\n"
     "static inline void ps5_wsite_add(unsigned site, int64_t t0)\n{\n    int64_t d = os_time_get_nano() - t0;\n    if (d > 0) {\n"
     "        if (ps5_driver_trace_hook)\n            ps5_driver_trace_hook(100 + site, (unsigned long long)t0, (unsigned long long)d, 0);"),
], "ps5_driver_trace_hook")

patch(sc, [
    # declaration near the first batch declarations
    ("static void ps5_draw_batch_retire_locked(bool wait);",
     "static void ps5_draw_batch_retire_locked(bool wait);\nextern void (*ps5_driver_trace_hook)(unsigned, unsigned long long, unsigned long long, unsigned long long);"),
    # backpressure wait
    ("         ps5_bp_ns += (unsigned long long)(os_time_get_nano() - bp_t0);",
     "         ps5_bp_ns += (unsigned long long)(os_time_get_nano() - bp_t0);\n"
     "         if (ps5_driver_trace_hook)\n            ps5_driver_trace_hook(112, (unsigned long long)bp_t0, (unsigned long long)(os_time_get_nano() - bp_t0), 0);"),
    # batch submit
    ("         ps5_bp_submit_ns += (unsigned long long)(os_time_get_nano() - sub_t0);",
     "         ps5_bp_submit_ns += (unsigned long long)(os_time_get_nano() - sub_t0);\n"
     "         if (ps5_driver_trace_hook)\n            ps5_driver_trace_hook(111, (unsigned long long)sub_t0, (unsigned long long)(os_time_get_nano() - sub_t0), 0);"),
    # forced drain (current batch overlaps)
    ("      ps5_dbs_ns += (unsigned long long)(os_time_get_nano() - dbs_t0);\n   } else {",
     "      ps5_dbs_ns += (unsigned long long)(os_time_get_nano() - dbs_t0);\n"
     "      if (ps5_driver_trace_hook)\n         ps5_driver_trace_hook(110, (unsigned long long)dbs_t0, (unsigned long long)(os_time_get_nano() - dbs_t0), (unsigned long long)dbs_caller);\n   } else {"),
], "ps5_driver_trace_hook(112")
