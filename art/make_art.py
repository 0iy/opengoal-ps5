#!/usr/bin/env python3
"""Build the app art (icon0.png, pic0.dds, pic1.dds) from the OpenGOAL logo files.
Inputs (next to this script's parent): og_icon.png (OpenGOAL mask), og_logo_text.png (wordmark).
Outputs go to ./out/. The DDS files reuse the header of an existing 1920x1080 RGBA8 DDS."""
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

BG_TOP = (28, 24, 40)
BG_BOTTOM = (10, 10, 18)
FONT = r"C:\Windows\Fonts\segoeuib.ttf"


def gradient(size, glow=True):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        c = tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    if glow:
        halo = Image.new("L", size, 0)
        d = ImageDraw.Draw(halo)
        d.ellipse((w * 0.2, h * 0.15, w * 0.8, h * 0.85), fill=70)
        halo = halo.filter(ImageFilter.GaussianBlur(h * 0.12))
        warm = Image.new("RGB", size, (255, 170, 20))
        img = Image.composite(warm, img, halo.point(lambda v: int(v * 0.35)))
    return img


def paste_center(base, layer, cy_frac, width):
    ratio = width / layer.width
    layer = layer.resize((width, int(layer.height * ratio)), Image.LANCZOS)
    x = (base.width - layer.width) // 2
    y = int(base.height * cy_frac - layer.height / 2)
    base.paste(layer, (x, y), layer)
    return base


def make_icon():
    icon = gradient((512, 512), glow=False)
    mask = Image.open(os.path.join(ROOT, "og_icon.png")).convert("RGBA")
    mask = mask.resize((420, 420), Image.LANCZOS)
    icon.paste(mask, ((512 - 420) // 2, 40), mask)
    d = ImageDraw.Draw(icon)
    f = ImageFont.truetype(FONT, 46)
    text = "PS5"
    tw = d.textlength(text, font=f)
    d.text(((512 - tw) / 2, 440), text, font=f, fill=(255, 255, 255))
    icon.save(os.path.join(OUT, "icon0.png"))


def make_background():
    bg = gradient((3840, 2160))
    logo = Image.open(os.path.join(ROOT, "og_logo_text.png")).convert("RGBA")
    paste_center(bg, logo, 0.46, 2600)
    d = ImageDraw.Draw(bg)
    f = ImageFont.truetype(FONT, 128)
    text = "for PlayStation 5"
    tw = d.textlength(text, font=f)
    d.text(((3840 - tw) / 2, 1280), text, font=f, fill=(235, 235, 245))
    return bg


def main():
    make_icon()
    bg = make_background()
    bg.save(os.path.join(OUT, "background.png"))
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
