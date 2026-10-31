#!/usr/bin/env python3
"""Refresh the game code inside the console's CGO/DGO files without an ISO or a full re-import.

  ps5cgo.py sync [jak1 jak2 jak3] [--dry-run]
  ps5cgo.py restore [jak1 jak2 jak3]

Compile the code first in WSL, with the disc region of the installed game (the objects depend on it; check against
an original object, e.g. pad.o, before uploading): GAME_TERRITORY_SCEA 0, SCEE 1 (PAL), SCEI 2, SCEK 3.
  goalc -g <game> --user-auto --proj-path ~/jak -c '(begin (seval (set! *default-territory* 1)) (make-group "all-code"))'
This console: jak1 and jak2 PAL (1), jak3 NTSC (0). For every CGO/DGO in
/data/opengoal/<game>/data/out/<game>/iso, each entry that has a freshly compiled ~/jak/out/<game>/obj/<entry>.o is
replaced by that object; art entries (no "GOAL" header, even when named like code) stay. Only changed containers are uploaded; the originals are kept in
out/cgo_backup/<game>/ for `restore`."""
import io, os, struct, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps5live as L

BACKUP = os.path.join(ROOT, "out", "cgo_backup")


def wsl_obj_dir(game):
    p = subprocess.run(["wsl", "bash", "-lc", f"wslpath -w {os.environ.get('PS5CGO_TREE', '~/jak')}/out/{game}/obj"], capture_output=True, text=True)
    return p.stdout.strip()


def parse(data):
    """[(name, payload)] of a DGO/CGO plus its header name."""
    count, = struct.unpack_from("<I", data, 0)
    name = data[4:64].split(b"\0")[0]
    off, out = 64, []
    for _ in range(count):
        size, = struct.unpack_from("<I", data, off)
        ename = data[off + 4:off + 64].split(b"\0")[0].decode()
        out.append((ename, data[off + 64:off + 64 + size]))
        off = (off + 64 + size + 15) & ~15
    return name, out


def build(name, entries):
    w = io.BytesIO()
    w.write(struct.pack("<I", len(entries)) + name.ljust(60, b"\0"))
    for ename, payload in entries:
        w.write(struct.pack("<I", len(payload)) + ename.encode().ljust(60, b"\0") + payload)
        w.write(b"\0" * (-w.tell() & 15))
    return w.getvalue()


def chmod(f, path):
    """the import wrote the files 0644 as another user; not every FTP payload knows SITE CHMOD (ftpsrv runs as root)"""
    try:
        f.sendcmd(f"SITE CHMOD 666 {path}")
    except Exception:
        pass


def iso_dir(game):
    return f"/data/opengoal/{game}/data/out/{game}/iso"


def sync(game, dry):
    objs = wsl_obj_dir(game)
    f = L.ftp()
    lines = []
    f.retrlines(f"LIST {iso_dir(game)}", lines.append)  # ftpsrv.elf has no NLST
    names = [l.split()[-1] for l in lines if l.upper().endswith((".CGO", ".DGO"))]
    changed = 0
    for n in sorted(os.path.basename(x) for x in names):
        buf = io.BytesIO()
        f.retrbinary(f"RETR {iso_dir(game)}/{n}", buf.write)
        data = buf.getvalue()
        hname, entries = parse(data)
        assert build(hname, entries) == data, f"{n}: round trip differs, format not understood"
        new, swapped = [], []
        for ename, payload in entries:
            p = os.path.join(objs, ename + ".o")
            # art entries often share the name of a code object ("sig", "grunt"): only code objects start with "GOAL"
            if payload[:4] == b"GOAL" and os.path.exists(p):
                fresh = open(p, "rb").read()
                if fresh != payload:
                    swapped.append(ename)
                    payload = fresh
            new.append((ename, payload))
        if not swapped:
            continue
        changed += 1
        print(f"{game} {n}: {len(swapped)} code object(s): {' '.join(swapped[:8])}{' ...' if len(swapped) > 8 else ''}")
        if dry:
            continue
        bdir = os.path.join(BACKUP, game)
        os.makedirs(bdir, exist_ok=True)
        if not os.path.exists(os.path.join(bdir, n)):  # keep the first original
            open(os.path.join(bdir, n), "wb").write(data)
        chmod(f, f"{iso_dir(game)}/{n}")
        f.storbinary(f"STOR {iso_dir(game)}/{n}", io.BytesIO(build(hname, new)))
    f.close()
    print(f"{game}: {changed} container(s) {'would change' if dry else 'updated'}")


def restore(game):
    bdir = os.path.join(BACKUP, game)
    f = L.ftp()
    for n in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
        chmod(f, f"{iso_dir(game)}/{n}")
        f.storbinary(f"STOR {iso_dir(game)}/{n}", open(os.path.join(bdir, n), "rb"))
        print("restored", game, n)
    f.close()


def main(a):
    if not a or a[0] not in ("sync", "restore"):
        print(__doc__)
        return
    games = [g for g in a[1:] if g.startswith("jak")] or ["jak1", "jak2", "jak3"]
    for g in games:
        sync(g, "--dry-run" in a) if a[0] == "sync" else restore(g)


if __name__ == "__main__":
    main(sys.argv[1:])
