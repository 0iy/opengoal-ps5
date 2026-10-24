#!/usr/bin/env bash
# Linux/WSL variant of make_release.ps1: bundle the installer, wrappers, README, app and SHA256SUMS into a zip.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)   # installer/
root=$(dirname "$here")                 # repository root
out=$root/release/OpenGOAL-PS5
# the setup script cannot work without the agent payload: stop here instead of shipping a bundle that fails on the user's machine
[ -f "$root/payloads/ogagent.elf" ] || { echo "missing payloads/ogagent.elf: build it first (bash payloads/build.sh payloads/ogagent.c payloads/ogagent.elf)" >&2; exit 1; }
rm -rf "$out"; mkdir -p "$out/app" "$out/tools" "$out/payloads"
cp -r ~/ogapp/dist/LAPY77001 "$out/app/LAPY77001"
rm -f "$out/app/LAPY77001/sce_sys/snd0.at9"  # hover music is derived from a copyrighted track: never ship it
cp "$root/payloads/scan.elf" "$out/tools/"
cp -r "$here"/release_template/* "$out/"
chmod +x "$out/install.sh"
# one-liner GUI: gui/, pc_import.py and the bootstrap scripts travel inside the bundle too
cp -r "$here/gui" "$out/gui"; rm -rf "$out/gui/__pycache__"; cp "$here/bootstrap.ps1" "$here/bootstrap.sh" "$out/"
cp "$here/pc_import.py" "$here/ps5_setup.py" "$out/"
cp "$root/payloads/ogagent.elf" "$root/payloads/scan.elf" "$out/payloads/"
# toolchain pack (see docs/PC_IMPORT.md, `pc_import.py --make-pack`): travels in the bundle and as its own release asset
[ -f "$here/opengoal-ps5-pack.tgz" ] && cp "$here/opengoal-ps5-pack.tgz" "$out/" || { echo "missing installer/opengoal-ps5-pack.tgz"; exit 1; }
# licences travel with the binaries (GPL, OFL font notice, third-party notices)
cp "$root/LICENSE" "$root/THIRD_PARTY_NOTICES.md" "$out/"; cp -r "$root/LICENSES" "$out/LICENSES"
(cd "$out" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | sort | xargs sha256sum > SHA256SUMS)
rm -f "$root/release/OpenGOAL-PS5.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'OpenGOAL-PS5')" "$root/release/OpenGOAL-PS5" "$root/release"
# release assets for the one-liners: OpenGOAL-PS5-gui.zip, bootstrap.ps1/.sh and the release-level SHA256SUMS
python3 "$here/gui/make_gui_zip.py" "$root/release"
ls -la "$root/release/OpenGOAL-PS5.zip"

cp "$out/opengoal-ps5-pack.tgz" "$root/release/"
(cd "$root/release" && sha256sum OpenGOAL-PS5.zip OpenGOAL-PS5-gui.zip opengoal-ps5-pack.tgz bootstrap.ps1 bootstrap.sh > SHA256SUMS 2>/dev/null; ls -la)
