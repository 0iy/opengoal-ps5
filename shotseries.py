#!/usr/bin/env python3
"""shotseries.py: request screenshots from the running app and fetch them over FTP. Defines functions and a CLI only; it connects
to the console only when you call a command (the main session does that, one at a time).

Mechanism (same as ps5.py shot()): /data/opengoal/config/shot.txt holds space-separated seconds-after-start; the app writes
/data/opengoal/log/shot0.ppm, shot1.ppm ... one per listed time and logs 'captured'. shot.txt is read at app start, so write it BEFORE launch.

  python shotseries.py request 30 40 50            # write shot.txt (also removes stale shot*.ppm)
  python shotseries.py fetch OUTDIR TAG [--n 3]    # OUTDIR/TAG_0.png ... (full resolution, lossless)
CLI host: env PS5_IP (default from ps5cfg.py, port 2121) like ps5.py.
Typical: request, then launch the game with ps5.py (see docs/agent_syncdbg.md), wait, then fetch.
"""
from ps5cfg import PS5_IP
import argparse
import ftplib
import io
import os

IP = PS5_IP
PORT = 2121
CFG = "/data/opengoal/config"
LOG = "/data/opengoal/log"


def ftp(ip=IP, port=PORT):
    f = ftplib.FTP()
    f.connect(ip, port, timeout=30)
    f.login()
    f.voidcmd("TYPE I")
    return f


def request_shots(f, times):
    """Write shot.txt for the next app start and delete old shot*.ppm so a later fetch cannot return a stale frame."""
    for i in range(32):
        try:
            f.delete(f"{LOG}/shot{i}.ppm")
        except ftplib.error_reply:
            pass  # this FTP server answers a successful DELE with 226
        except ftplib.error_perm:
            break
    f.storbinary(f"STOR {CFG}/shot.txt", io.BytesIO(" ".join(str(t) for t in times).encode()))


def fetch_shots(f, n=None):
    """Return a list of PIL RGB images for shot0.ppm .. (n or until missing)."""
    from PIL import Image
    imgs = []
    for i in range(n if n is not None else 32):
        b = io.BytesIO()
        try:
            f.retrbinary(f"RETR {LOG}/shot{i}.ppm", b.write)
        except ftplib.error_perm:
            break
        b.seek(0)
        imgs.append(Image.open(b).convert("RGB"))
    return imgs


def save_series(imgs, outdir, tag):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i, im in enumerate(imgs):
        p = os.path.join(outdir, f"{tag}_{i}.png")
        im.save(p)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("request")
    r.add_argument("times", type=int, nargs="+")
    g = sub.add_parser("fetch")
    g.add_argument("outdir")
    g.add_argument("tag")
    g.add_argument("--n", type=int)
    ar = ap.parse_args()
    f = ftp()
    try:
        if ar.cmd == "request":
            request_shots(f, ar.times)
            print("shot.txt:", ar.times)
        else:
            for p in save_series(fetch_shots(f, ar.n), ar.outdir, ar.tag):
                print("saved", p)
    finally:
        f.quit()


if __name__ == "__main__":
    main()
