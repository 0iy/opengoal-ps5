#!/usr/bin/env python3
"""Float32 numpy reference of EASU + RCAS, written in vectorised form (separate code path from the GLSL).
Run from Windows or WSL:  python3 fsr_ref.py   -> renders test images with fsr.frag on Mesa llvmpipe (EGL surfaceless,
via WSL), compares to the reference, prints max / mean error in 8 bit levels. Needs numpy, PIL, gcc, libEGL."""
import os
import subprocess
import sys

import numpy as np
from PIL import Image


def luma(c):
    return c[..., 2] * .5 + (c[..., 0] * .5 + c[..., 1])


def easu_ref(img, ow, oh):
    ih, iw = img.shape[:2]
    sx, sy = iw / ow, ih / oh
    X, Y = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
    ppx = X * np.float32(sx) + np.float32(.5 * sx - .5)
    ppy = Y * np.float32(sy) + np.float32(.5 * sy - .5)
    fx, fy = np.floor(ppx), np.floor(ppy)
    px, py = ppx - fx, ppy - fy
    fx = fx.astype(int)
    fy = fy.astype(int)

    def at(dx, dy):
        return img[np.clip(fy + dy, 0, ih - 1), np.clip(fx + dx, 0, iw - 1)]

    offs = dict(b=(0, -1), c=(1, -1), e=(-1, 0), f=(0, 0), g=(1, 0), h=(2, 0),
                i=(-1, 1), j=(0, 1), k=(1, 1), l=(2, 1), n=(0, 2), o=(1, 2))
    C = {k: at(*v) for k, v in offs.items()}
    L = {k: luma(v) for k, v in C.items()}
    st = dict(dx=np.zeros_like(px), dy=np.zeros_like(px), ln=np.zeros_like(px))

    def setq(w, a, b, c, d, e):
        lx = 1 / np.maximum(np.maximum(abs(d - c), abs(c - b)), 1 / 32768)
        dx = d - b
        st['dx'] = st['dx'] + dx * w
        lx = np.clip(abs(dx) * lx, 0, 1)
        st['ln'] = st['ln'] + lx * lx * w
        ly = 1 / np.maximum(np.maximum(abs(e - c), abs(c - a)), 1 / 32768)
        dy = e - a
        st['dy'] = st['dy'] + dy * w
        ly = np.clip(abs(dy) * ly, 0, 1)
        st['ln'] = st['ln'] + ly * ly * w

    setq((1 - px) * (1 - py), L['b'], L['e'], L['f'], L['g'], L['j'])
    setq(px * (1 - py), L['c'], L['f'], L['g'], L['h'], L['k'])
    setq((1 - px) * py, L['f'], L['i'], L['j'], L['k'], L['n'])
    setq(px * py, L['g'], L['j'], L['k'], L['l'], L['o'])
    dirx, diry, ln = st['dx'], st['dy'], st['ln']
    d2 = dirx * dirx + diry * diry
    zro = d2 < 1 / 32768
    r = np.where(zro, 1, 1 / np.sqrt(np.where(zro, 1, d2)))
    dirx = np.where(zro, 1, dirx) * r
    diry = diry * r
    ln = (ln * .5) ** 2
    stretch = (dirx * dirx + diry * diry) / np.maximum(abs(dirx), abs(diry))
    l2x = 1 + (stretch - 1) * ln
    l2y = 1 - .5 * ln
    lob = .5 + ((.25 - .04) - .5) * ln
    clp = 1 / lob
    acc = np.zeros(px.shape + (3,), np.float32)
    aw = np.zeros_like(px)
    for k, (ox, oy) in offs.items():
        vx = ox - px
        vy = oy - py
        rx = (vx * dirx + vy * diry) * l2x
        ry = (vx * -diry + vy * dirx) * l2y
        dd = np.minimum(rx * rx + ry * ry, clp)
        wb = (2 / 5 * dd - 1) ** 2
        wa = (lob * dd - 1) ** 2
        w = (25 / 16 * wb - (25 / 16 - 1)) * wa
        acc += C[k] * w[..., None]
        aw += w
    mn = np.minimum(np.minimum(C['f'], C['g']), np.minimum(C['j'], C['k']))
    mx = np.maximum(np.maximum(C['f'], C['g']), np.maximum(C['j'], C['k']))
    return np.minimum(mx, np.maximum(mn, acc / aw[..., None]))


def rcas_ref(img, stops):
    P = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode='edge')
    b, d, e, f, hh = P[:-2, 1:-1], P[1:-1, :-2], img, P[1:-1, 2:], P[2:, 1:-1]
    Lb, Ld, Le, Lf, Lh = map(luma, (b, d, e, f, hh))
    nz = .25 * (Lb + Ld + Lf + Lh) - Le
    rng = np.maximum.reduce([Lb, Ld, Le, Lf, Lh]) - np.minimum.reduce([Lb, Ld, Le, Lf, Lh])
    nz = -.5 * np.clip(abs(nz) / np.maximum(rng, 1 / 65536), 0, 1) + 1
    mn = np.minimum(np.minimum(b, d), np.minimum(f, hh))
    mx = np.maximum(np.maximum(b, d), np.maximum(f, hh))
    hmin = mn / (4 * np.maximum(mx, 1 / 65536))
    hmax = (1 - mx) / np.minimum(4 * mn - 4, -1 / 65536)
    lobe_rgb = np.maximum(-hmin, hmax)
    lobe = np.maximum(-(.25 - 1 / 16), np.minimum(lobe_rgb.max(-1), 0)) * np.float32(2 ** -stops) * nz
    return (lobe[..., None] * (b + d + hh + f) + e) / (4 * lobe[..., None] + 1)


def make_image(w, h):
    rng = np.random.default_rng(1)
    X, Y = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    img = np.stack([X, Y, .5 + .5 * np.sin(12 * X + 5 * Y)], -1)
    img[h // 3:h // 2, w // 4:w // 2] = [.9, .2, .1]  # hard axis aligned edges
    yy, xx = np.mgrid[0:h, 0:w]
    img[((xx - w * .7) ** 2 + (yy - h * .6) ** 2) < (h * .15) ** 2] = [.05, .8, .9]  # circle: diagonal edges
    img[yy % 6 < 1] *= .5  # thin lines
    img += rng.normal(0, .02, img.shape)  # noise
    return np.clip(img, 0, 1).astype(np.float32)


def q8(a):
    return np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)


def run_gl(here, iw, ih, ow, oh, stops):
    d = here.replace('\\', '/')
    if len(d) > 1 and d[1] == ':':
        d = '/mnt/' + d[0].lower() + d[2:]
    cmd = (f'cd "{d}" && gcc gl_harness.c -o /tmp/gl_harness_fsr -lEGL -lGL -lm && '
           f'LIBGL_ALWAYS_SOFTWARE=1 /tmp/gl_harness_fsr _in.raw {iw} {ih} {ow} {oh} {stops} _easu.raw _rcas.raw')
    argv = ['bash', '-c', cmd] if sys.platform != 'win32' else ['wsl', '-d', 'Ubuntu', '-e', 'bash', '-c', cmd]
    return subprocess.run(argv, capture_output=True, text=True)


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    worst = 0
    for (iw, ih, ow, oh, stops) in [(160, 90, 192, 108, .2), (128, 72, 256, 144, 1.0), (333, 187, 640, 360, .5)]:
        img = make_image(iw, ih)
        u8 = q8(img)
        np.concatenate([u8, np.full((ih, iw, 1), 255, np.uint8)], -1).tofile(f'{here}/_in.raw')
        out = run_gl(here, iw, ih, ow, oh, stops)
        print(out.stdout.strip(), out.stderr.strip()[:300])
        ge = np.fromfile(f'{here}/_easu.raw', np.uint8).reshape(oh, ow, 4)[..., :3].astype(int)
        gr = np.fromfile(f'{here}/_rcas.raw', np.uint8).reshape(oh, ow, 4)[..., :3].astype(int)
        e_q = q8(easu_ref(u8.astype(np.float32) / 255, ow, oh))
        r_q = q8(rcas_ref(ge.astype(np.float32) / 255, stops))  # RCAS reference fed with the GL EASU output (isolates RCAS error)
        de = abs(ge - e_q.astype(int))
        dr = abs(gr - r_q.astype(int))
        worst = max(worst, de.max(), dr.max())
        print(f'{iw}x{ih}->{ow}x{oh} stops={stops}: EASU max {de.max()} mean {de.mean():.4f} | '
              f'RCAS max {dr.max()} mean {dr.mean():.4f} | pixels >2 levels: {(de > 2).mean() * 100:.3f}% / {(dr > 2).mean() * 100:.3f}%')
        k = ow // iw + 1
        left = np.kron(u8, np.ones((k, k, 1), np.uint8))[:oh, :ow]
        Image.fromarray(np.concatenate([left, gr.astype(np.uint8)], 1)).save(f'{here}/_cmp_{ow}.png')
    print('PASS' if worst <= 3 else 'FAIL', 'worst error', worst)
