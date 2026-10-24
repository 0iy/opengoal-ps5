#!/usr/bin/env python3
"""Nearest-symbol lookup for runtime addresses from a CRASH log.

usage: symlookup.py <runtime ps5_log address hex> <runtime addr hex>...
The slide is computed from the runtime address of ps5_log (printed on the CRASH line).
"""
import bisect
import os
import subprocess
import sys

ELF = os.path.expanduser("~/ogapp/build/llvm-pie.elf")
out = subprocess.run(["llvm-nm-18", "-n", "--defined-only", "--demangle", ELF], capture_output=True, text=True).stdout
syms = []
static_log = None
for line in out.splitlines():
    parts = line.split(None, 2)
    if len(parts) == 3 and parts[1] in "tTwW":
        syms.append((int(parts[0], 16), parts[2]))
        if parts[2].startswith("ps5_log(char const*"):
            static_log = int(parts[0], 16)
slide = int(sys.argv[1], 16) - static_log
print(f"slide=0x{slide:x}")
addrs = [a for a, _ in syms]
for a in sys.argv[2:]:
    static = int(a, 16) - slide
    i = bisect.bisect_right(addrs, static) - 1
    if i >= 0:
        base, name = syms[i]
        print(f"{a} -> {name} +0x{static - base:x}")
    else:
        print(f"{a} -> ?")
