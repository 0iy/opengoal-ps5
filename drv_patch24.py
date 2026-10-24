#!/usr/bin/env python3
"""Driver patch 24: the GPU trace poller reads completion markers inside command memory, so a pending batch must not be
released before the poller has consumed its entries (patch 23 crashed on freed memory)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "pending->trace_head" in s:
    print("already patched")
    raise SystemExit

old = "    unsigned count, attempted;\n#ifdef PS5_DRAW_PROFILE\n    int profile;"
new = "    unsigned count, attempted;\n    uint64_t trace_head;\n#ifdef PS5_DRAW_PROFILE\n    int profile;"
assert s.count(old) == 1
s = s.replace(old, new)

old = "    pending->count = runtime_batch_count;\n    pending->attempted = attempted;\n"
new = "    pending->count = runtime_batch_count;\n    pending->attempted = attempted;\n    pending->trace_head = atomic_load_explicit(&gputrace_head, memory_order_acquire);\n"
assert s.count(old) == 1
s = s.replace(old, new)

old = "#if !defined(PS5_NATIVE_TITLE_RUNTIME) || defined(AGC_RUNTIME_DIAGNOSTICS)\n    printf(\"[ps5-multidraw-batch] draws=%u attempted=%u waits=%u result=0\\n\","
new = ("    if (gputrace_on())\n        while (atomic_load_explicit(&gputrace_tail, memory_order_acquire) < pending->trace_head)\n"
       "            __builtin_ia32_pause();\n" + old)
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
