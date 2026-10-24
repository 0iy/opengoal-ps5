#!/usr/bin/env bash
# One-time bring-up of the WSL build tree on a new machine (after SETUP_NEW_MACHINE steps 1-3 sources are in place).
# Output: ~/ps5build/libgk.a and ~/ogapp/dist/LAPY77001/eboot.bin. Log: ~/first_build.log
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HOME"
echo "[1] cxx variant"; bash "$HERE/setup_cxx.sh" || exit 1
echo "[2] host cmake config"
rm -rf jak_cfg; cmake -S jak -B jak_cfg -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python3 -DPython_EXECUTABLE=/usr/bin/python3 > cmake_cfg.log 2>&1 || { tail -20 cmake_cfg.log; exit 1; }
bash "$HERE/gk_cmds.sh" | head -3
echo "[3] patches + ninja"
python3 "$HERE/apply_ps5_patches.py" || exit 1
python3 "$HERE/gen_launcher_assets.py" "$HERE/ps5shim/launcher_assets.cpp" || exit 1
python3 "$HERE/gen_ps5_ninja.py" || exit 1
cd "$HOME/ps5build" && ninja -k 0 -j 3 2>&1 | grep -E 'FAILED|error:' | head -30
test -s libgk.a || { echo "libgk.a missing"; exit 1; }
echo "[4] ogapp"
mkdir -p "$HOME/ogapp"
bash "$HERE/setup_ogapp.sh" || exit 1
bash "$HERE/retitle.sh" || exit 1
cp "$HERE/ogapp_src/"* "$HOME/ogapp/src/"
cd "$HOME/ogapp" && make 2>&1 | tee "$HOME/ogapp_make.log" | grep -E 'undefined symbol|error:|Build complete' | sort | uniq -c | head -30
ls -la "$HOME/ogapp/dist/LAPY77001/" 2>&1
echo "FIRST_BUILD_DONE"
