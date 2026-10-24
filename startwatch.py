#!/usr/bin/env python3
"""Press Play in the launcher and sample the screen every few seconds: darkness ratio and spinner pixels
(the loading overlay's amber dots), to see how long each phase of the game start lasts.
usage: startwatch.py [seconds=60]"""
import os
import subprocess
import sys
import time

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
total = int(sys.argv[1]) if len(sys.argv) > 1 else 60


def run(*a):
    return subprocess.run([sys.executable, os.path.join(HERE, *a[:1]), *a[1:]], capture_output=True, text=True, cwd=HERE)


run("dbg.py", "press", "4000", "150")
t0 = time.time()
while time.time() - t0 < total:
    run("ps5.py", "snap", "sw.png")
    im = Image.open(os.path.join(HERE, "sw.png")).convert("RGB")
    px = list(im.getdata())
    n = len(px)
    dark = sum(1 for r, g, b in px if r + g + b < 30) / n
    spin = sum(1 for r, g, b in px if r > 230 and 150 < g < 200 and b < 40)
    print(f"t={time.time() - t0:5.1f}s dark={dark:.2f} spinner_px={spin}", flush=True)
