#!/usr/bin/env python3
"""Compose the README banner (docs/img/banner.png) from the launcher artwork in art/launcher. Needs Pillow."""
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W, H = 1600, 400
FONT = os.path.join(HERE, "fonts", "NotoSansJP-Medium.ttf")


def main():
    bgs = [Image.open(os.path.join(HERE, "launcher", "bg%d.jpg" % i)).convert("RGB") for i in (1, 2, 3)]
    img = Image.new("RGB", (W, H))
    third = W // 3 + 2
    for i, bg in enumerate(bgs):  # three game backdrops side by side, cropped to the band
        crop = bg.resize((third * 2, int(third * 2 * 9 / 16))).crop((third // 2, 150, third // 2 + third, 150 + H))
        img.paste(crop, (i * (W // 3), 0))
    img = ImageEnhance.Brightness(img).enhance(0.55).filter(ImageFilter.GaussianBlur(1.2))
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    for y in range(H):
        d.line((0, y, W, y), fill=int(150 * (y / H) ** 1.5))
    img = Image.composite(Image.new("RGB", (W, H), (6, 8, 16)), img, shade)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT, 120)
    sub = ImageFont.truetype(FONT, 40)
    text = "OpenGOAL-PS5"
    tw = d.textlength(text, font=title)
    d.text(((W - tw) / 2 + 4, 66), text, font=title, fill=(0, 0, 0))
    d.text(((W - tw) / 2, 62), text, font=title, fill=(255, 255, 255))
    line = "Jak and Daxter 1, 2 and 3 on a jailbroken PlayStation 5. Native. No emulation."
    d.text(((W - d.textlength(line, font=sub)) / 2, 224), line, font=sub, fill=(255, 205, 140))
    logos = [Image.open(os.path.join(HERE, "launcher", "logo%d.png" % i)).convert("RGBA") for i in (1, 2, 3)]
    h = 70
    ims = [lg.resize((int(lg.width * h / lg.height), h)) for lg in logos]
    total = sum(i.width for i in ims) + 80 * 2
    x = (W - total) // 2
    for lg in ims:
        img.paste(lg, (x, 308), lg)
        x += lg.width + 80
    out = os.path.join(ROOT, "docs", "img", "banner.png")
    img.save(out, optimize=True)
    print(out, os.path.getsize(out) >> 10, "KB")


if __name__ == "__main__":
    main()


def social():
    """1280x640 social preview (GitHub repository settings, Social preview): banner art scaled up with the title larger."""
    w, h = 1280, 640
    src = Image.open(os.path.join(ROOT, "docs", "img", "banner.png")).convert("RGB")
    bg = src.resize((int(src.width * h / src.height), h)).crop(((int(src.width * h / src.height) - w) // 2, 0, (int(src.width * h / src.height) + w) // 2, h))
    bg = ImageEnhance.Brightness(bg).enhance(0.6)
    d = ImageDraw.Draw(bg)
    big = ImageFont.truetype(FONT, 150)
    mid = ImageFont.truetype(FONT, 48)
    for dx, dy, col in ((5, 6, (0, 0, 0)), (0, 0, (255, 255, 255))):
        d.text(((w - d.textlength("OpenGOAL-PS5", font=big)) / 2 + dx, 150 + dy), "OpenGOAL-PS5", font=big, fill=col)
    line = "Jak and Daxter 1, 2, 3 on PlayStation 5"
    d.text(((w - d.textlength(line, font=mid)) / 2, 340), line, font=mid, fill=(255, 205, 140))
    sm = ImageFont.truetype(FONT, 36)
    line2 = "Native. 60 fps. Playable in a minute."
    d.text(((w - d.textlength(line2, font=sm)) / 2, 420), line2, font=sm, fill=(235, 235, 245))
    out = os.path.join(ROOT, "docs", "img", "social-preview.png")
    bg.save(out, optimize=True)
    print(out, os.path.getsize(out) >> 10, "KB")


if __name__ == "__main__":
    social()
