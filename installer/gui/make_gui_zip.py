#!/usr/bin/env python3
"""make_gui_zip.py RELEASE_DIR: build OpenGOAL-PS5-gui.zip (gui scripts, pc_import.py, ps5_setup.py, payloads/ogagent.elf), copy bootstrap.ps1/.sh next to it and write
RELEASE_DIR/SHA256SUMS over every release asset (gui zip, bootstrap scripts, OpenGOAL-PS5.zip if present). Used by make_release.*"""
import hashlib, os, shutil, sys, zipfile

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
out = os.path.abspath(sys.argv[1])
os.makedirs(out, exist_ok=True)
files = {n: os.path.join(root, n) for n in ("gui/windows/OpenGOAL-PS5.ps1", "gui/macos/OpenGOAL-PS5.command", "gui/OpenGOAL-PS5-gui.py", "ps5_setup.py")}
if os.path.exists(os.path.join(root, "pc_import.py")):
    files["pc_import.py"] = os.path.join(root, "pc_import.py")
else:
    print("WARNING: pc_import.py not found, the GUI zip has no import engine", file=sys.stderr)
# the one-liner runs ps5_setup.py first, which needs the agent payload (and uses scan.elf when present)
for n in ("ogagent.elf", "scan.elf"):
    src = os.path.join(root, "..", "payloads", n)
    if not os.path.exists(src):
        if n == "ogagent.elf":
            sys.exit("missing payloads/ogagent.elf: build it first (bash payloads/build.sh payloads/ogagent.c payloads/ogagent.elf)")
        continue
    files["payloads/" + n] = src
zp = os.path.join(out, "OpenGOAL-PS5-gui.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for name, src in files.items():
        zi = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))  # fixed timestamps: same input gives the same zip and hash
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (0o755 if name.endswith(".command") else 0o644) << 16
        with open(src, "rb") as f:
            z.writestr(zi, f.read())
for b in ("bootstrap.ps1", "bootstrap.sh"):
    shutil.copy(os.path.join(root, b), os.path.join(out, b))
names = [n for n in ("OpenGOAL-PS5-gui.zip", "bootstrap.ps1", "bootstrap.sh", "OpenGOAL-PS5.zip") if os.path.exists(os.path.join(out, n))]
with open(os.path.join(out, "SHA256SUMS"), "w", newline="\n") as f:
    for n in names:
        f.write("%s  %s\n" % (hashlib.sha256(open(os.path.join(out, n), "rb").read()).hexdigest(), n))
print("wrote", zp, "and SHA256SUMS for:", ", ".join(names))
