#!/usr/bin/env python3
"""Driver patch 16: export the async prep worker thread handles so the sampling profiler can target a worker."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_agc_async_thread" in s:
    print("already patched"); raise SystemExit
anchor = "static _Atomic uint64_t runtime_async_produced, runtime_async_consumed;"
add = """unsigned long ps5_agc_async_thread(unsigned i)
{
    return i < PS5_NATIVE_PREP_WORKERS && runtime_async_started ? (unsigned long)runtime_async_threads[i] : 0;
}
"""
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + "\n" + add)
open(P, "w", encoding="utf-8").write(s)
print("ok")
