#!/usr/bin/env python3
"""Driver patch 26 (experiment): PS5_FLIP_MODE=<n> forces the flip mode of every frame (1 vsync, 2 hsync/immediate)."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "PS5_FLIP_MODE" in s:
    print("already patched")
    raise SystemExit
old = "static uint32_t runtime_adaptive_flip_mode(void)\n{\n"
new = ("static uint32_t runtime_adaptive_flip_mode(void)\n{\n"
       "    static int forced = -2;\n"
       "    if (forced == -2) {\n"
       "        const char *e = getenv(\"PS5_FLIP_MODE\");\n"
       "        forced = e ? atoi(e) : -1;\n"
       "    }\n"
       "    if (forced > 0)\n"
       "        return (uint32_t)forced;\n")
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
