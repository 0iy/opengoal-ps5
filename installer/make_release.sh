#!/usr/bin/env bash
# Linux/WSL variant of make_release.ps1: bundle the installer, wrappers, README, app and SHA256SUMS into a zip.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)   # installer/
root=$(dirname "$here")                 # repository root
out=$root/release/OpenGOAL-PS5
rm -rf "$out"; mkdir -p "$out/app" "$out/tools"
cp -r ~/ogapp/dist/LAPY77001 "$out/app/LAPY77001"
rm -f "$out/app/LAPY77001/sce_sys/snd0.at9"  # hover music is derived from a copyrighted track: never ship it
cp "$root/payloads/scan.elf" "$out/tools/"
cp -r "$here"/release_template/* "$out/"
chmod +x "$out/install.sh"
# one-liner GUI: gui/, pc_import.py and the bootstrap scripts travel inside the bundle too
cp -r "$here/gui" "$out/gui"; rm -rf "$out/gui/__pycache__"; cp "$here/bootstrap.ps1" "$here/bootstrap.sh" "$out/"
cp "$here/pc_import.py" "$out/"
(cd "$out" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | xargs sha256sum > SHA256SUMS)
rm -f "$root/release/OpenGOAL-PS5.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'OpenGOAL-PS5')" "$root/release/OpenGOAL-PS5" "$root/release"
# release assets for the one-liners: OpenGOAL-PS5-gui.zip, bootstrap.ps1/.sh and the release-level SHA256SUMS
python3 "$here/gui/make_gui_zip.py" "$root/release"
ls -la "$root/release/OpenGOAL-PS5.zip"
