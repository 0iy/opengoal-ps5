#!/usr/bin/env python3
"""shotdiff.py: compare two screenshots (PNG or PPM). Prints percentage of pixels whose max channel difference exceeds a threshold
and the bounding boxes of the largest differing regions; optionally writes a heatmap PNG.

  python shotdiff.py a.png b.ppm [--thresh 16] [--heat heat.png] [--block 16] [--top 5] [--resize]
Exit status: 0 always when the compare ran (read the numbers); 2 on size mismatch without --resize.
"""
import argparse
import sys

import numpy as np
from PIL import Image


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def diff_image(a, b):
    """Per-pixel max absolute channel difference, uint8 HxW."""
    return np.abs(a - b).max(axis=2).astype(np.uint8)


def regions(mask, block=16, top=5):
    """Bounding boxes (x0, y0, x1, y1 exclusive, pixel count) of 8-connected groups of differing blocks, largest first.
    The mask is reduced to block x block cells first, so near pixels merge into one region."""
    h, w = mask.shape
    gh, gw = -(-h // block), -(-w // block)
    pad = np.zeros((gh * block, gw * block), bool)
    pad[:h, :w] = mask
    cnt = pad.reshape(gh, block, gw, block).sum(axis=(1, 3))
    grid = cnt > 0
    seen = np.zeros_like(grid)
    out = []
    for sy, sx in zip(*np.nonzero(grid)):
        if seen[sy, sx]:
            continue
        stack, cells = [(sy, sx)], []
        seen[sy, sx] = True
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and grid[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        ys = [c[0] for c in cells]
        xs = [c[1] for c in cells]
        # tighten to the real pixels inside the cell box
        sub = mask[min(ys) * block:(max(ys) + 1) * block, min(xs) * block:(max(xs) + 1) * block]
        py, px = np.nonzero(sub)
        out.append((min(xs) * block + int(px.min()), min(ys) * block + int(py.min()),
                    min(xs) * block + int(px.max()) + 1, min(ys) * block + int(py.max()) + 1,
                    int(sum(cnt[y, x] for y, x in cells))))
    out.sort(key=lambda r: -r[4])
    return out[:top]


def heatmap(d, thresh):
    """Black = identical, dark red .. yellow = growing difference, pixels over the threshold at least mid red."""
    v = d.astype(np.float32) / 255.0
    v = np.where(d > thresh, np.maximum(v, 0.5), v * 0.5)
    rgb = np.zeros(d.shape + (3,), np.uint8)
    rgb[..., 0] = np.clip(v * 2 * 255, 0, 255)
    rgb[..., 1] = np.clip((v - 0.5) * 2 * 255, 0, 255)
    return Image.fromarray(rgb)


def compare(pa, pb, thresh=16, block=16, top=5, resize=False, heat=None):
    a, b = load(pa), load(pb)
    if a.shape != b.shape:
        if not resize:
            raise ValueError(f"size mismatch {a.shape[1]}x{a.shape[0]} vs {b.shape[1]}x{b.shape[0]} (use --resize)")
        b = np.asarray(Image.fromarray(b.astype(np.uint8)).resize((a.shape[1], a.shape[0]), Image.BILINEAR), dtype=np.int16)
    d = diff_image(a, b)
    mask = d > thresh
    res = {"pct": 100.0 * mask.mean(), "mean_abs": float(d.mean()), "max": int(d.max()),
           "regions": regions(mask, block, top)}
    if heat:
        heatmap(d, thresh).save(heat)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--thresh", type=int, default=16, help="max channel difference (0..255) above which a pixel counts")
    ap.add_argument("--heat", help="write heatmap PNG here")
    ap.add_argument("--block", type=int, default=16, help="regions merge when closer than this many pixels")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--resize", action="store_true", help="resize b to a's size instead of failing")
    ar = ap.parse_args()
    try:
        r = compare(ar.a, ar.b, ar.thresh, ar.block, ar.top, ar.resize, ar.heat)
    except ValueError as e:
        print("ERROR:", e)
        return 2
    print(f"differing pixels (>{ar.thresh}): {r['pct']:.3f}%   mean abs diff {r['mean_abs']:.3f}   max {r['max']}")
    for x0, y0, x1, y1, n in r["regions"]:
        print(f"  region x={x0}..{x1} y={y0}..{y1} ({x1 - x0}x{y1 - y0}) pixels={n}")
    if not r["regions"]:
        print("  no differing region")
    return 0


if __name__ == "__main__":
    sys.exit(main())
