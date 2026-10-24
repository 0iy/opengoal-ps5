#!/usr/bin/env bash
# Rebuild the engine archive and the app; print compile errors and undefined link symbols.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$HERE/apply_ps5_patches.py" || exit 1
python3 "$HERE/art/make_art.py" >/dev/null || exit 1
python3 "$HERE/gen_launcher_assets.py" "$HERE/ps5shim/launcher_assets.cpp" || exit 1
python3 "$HERE/gen_ps5_ninja.py" || exit 1
cd "$HOME/ps5build" || exit 1
ninja -k 0 -j 12 2>&1 | grep -E 'FAILED|error:' | head -30
test -s libgk.a || { echo "libgk.a missing"; exit 1; }
cp libgk.a "$HOME/ogapp/vendor/libgk.a"
cp "$HERE/ogapp_src/"* "$HOME/ogapp/src/"
cd "$HOME/ogapp"
make 2>&1 | tee "$HOME/ogapp_make.log" | grep -E 'undefined symbol|error:|Build complete' | sed -E 's/^ld.lld: error: //' | sort | uniq -c | sort -rn | head -60
# launcher font (Noto Sans JP, OFL, shipped with jak-project): lets the launcher render text before any game data exists
mkdir -p "$HOME/ogapp/dist/LAPY77001/assets" && cp "$HOME/jak/game/assets/fonts/NotoSansJP-Medium.ttf" "$HOME/ogapp/dist/LAPY77001/assets/" 2>/dev/null || true
# toolchain pack for the on-console import (open-source goal_src/configs/assets of the patched jak-project, no game data)
python3 "$HERE/make_skeleton.py" "$HOME/jak" "$HOME/ogapp/dist/LAPY77001/assets/skeleton.tar.zst" || echo "skeleton pack failed (pip install zstandard)"

# XMB art (own generated icon and backgrounds)
cp "$HERE/art/out/sce_sys/"* "$HOME/ogapp/dist/LAPY77001/sce_sys/"
