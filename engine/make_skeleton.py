#!/usr/bin/env python3
"""Pack the toolchain pack: the open-source parts of jak-project the on-console importer needs
(goal_src, decompiler configs, engine assets). No game data. Output: skeleton.tar.zst (GNU tar + zstd).
usage: make_skeleton.py <jak-project dir> <out file>"""
import io
import os
import sys
import tarfile

import zstandard

SRC = sys.argv[1]
OUT = sys.argv[2]
INCLUDE = ["goal_src", "decompiler/config", "decompiler/data", "game/assets", "custom_assets", "common/goos"]
SKIP_NAMES = {".git", "__pycache__"}


def main():
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        count = 0
        for inc in INCLUDE:
            top = os.path.join(SRC, inc)
            if not os.path.isdir(top):
                continue
            for dirpath, dirs, files in os.walk(top):
                dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
                for name in sorted(files):
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, SRC).replace("\\", "/")
                    ti = tar.gettarinfo(full, arcname=rel)
                    ti.uid = ti.gid = 0
                    ti.uname = ti.gname = ""
                    with open(full, "rb") as fh:
                        tar.addfile(ti, fh)
                    count += 1
    data = raw.getvalue()
    comp = zstandard.ZstdCompressor(level=19, threads=-1).compress(data)
    with open(OUT, "wb") as f:
        f.write(comp)
    print(f"{count} files, {len(data) >> 20} MiB tar -> {len(comp) >> 20} MiB zst: {OUT}")


main()
