#!/usr/bin/env python3
"""Screen state summary without viewing the image (saves tokens).

usage: python analyze.py [png] [--snap]
  --snap   take a fresh screenshot via ps5.py snap first (default if no png given)
Prints: mean luma, black fraction, blank/black verdict, 4x3 grid of mean RGB and luma,
and a rough content class per cell (black / flat / textured).
"""
import os
import subprocess
import sys

import warnings

from PIL import Image

warnings.filterwarnings("ignore", category=DeprecationWarning)
HERE = os.path.dirname(os.path.abspath(__file__))
BLACK_LUMA = 8
FLAT_STD = 6


def take_snap(name):
    subprocess.run([sys.executable, os.path.join(HERE, "ps5.py"), "snap", name],
                   capture_output=True, text=True, timeout=60)
    return os.path.join(HERE, name)


def classify(cell):
    px = list(cell.getdata())
    n = len(px)
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean = sum(lum) / n
    var = sum((v - mean) ** 2 for v in lum) / n
    std = var ** 0.5
    rgb = tuple(int(sum(p[i] for p in px) / n) for i in range(3))
    if mean < BLACK_LUMA:
        kind = "black"
    elif std < FLAT_STD:
        kind = "flat"
    else:
        kind = "textured"
    return mean, rgb, kind


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or "--snap" in sys.argv:
        path = take_snap(args[0] if args else "analyze_now.png")
    else:
        path = args[0]
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = list(im.getdata())
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean = sum(lum) / len(lum)
    black = sum(1 for v in lum if v < BLACK_LUMA) / len(lum)
    verdict = "BLACK SCREEN" if black > 0.95 else ("MOSTLY BLACK" if black > 0.5 else "content")
    print(f"file={os.path.basename(path)} size={w}x{h} mean_luma={mean:.1f} black_frac={black:.3f} verdict={verdict}")
    cols, rows = 4, 3
    for r in range(rows):
        cells = []
        for c in range(cols):
            box = (c * w // cols, r * h // rows, (c + 1) * w // cols, (r + 1) * h // rows)
            m, rgb, kind = classify(im.crop(box))
            cells.append(f"{kind[0]}{int(m):3d}#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
        print(" | ".join(cells))
    print("cells: k=black f=flat t=textured, luma, mean rgb")


if __name__ == "__main__":
    sys.exit(main())
