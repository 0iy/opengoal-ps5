#!/usr/bin/env bash
# First build on a new machine (WSL Ubuntu). Prerequisite: the checkouts and packages of docs/DEVELOPMENT.md, sections 1 to 3.
# Result: ~/ps5build/libgk.a, ~/drv/out/*.o and ~/ogapp/dist/LAPY77001/eboot.bin. Log: ~/first_build.log
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repository root
cd "$HOME"
step() { echo "[$1] $2"; }
{
step 1 "host configuration of jak-project (the compile commands are the input of the PS5 build files)"
rm -rf jak_cfg
cmake -S jak -B jak_cfg -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_BUILD_TYPE=Release \
  -DPYTHON_EXECUTABLE=/usr/bin/python3 -DPython_EXECUTABLE=/usr/bin/python3 > cmake_cfg.log 2>&1 || { tail -20 cmake_cfg.log; exit 1; }
rm -f gk_cmds.txt ext_cmds.txt

step 2 "engine patches, launcher artwork, PS5 build files, engine archive"
python3 "$HERE/engine/apply_ps5_patches.py" || exit 1
python3 "$HERE/app/gen_launcher_assets.py" "$HERE/app/shim/launcher_assets.cpp" || exit 1
python3 "$HERE/engine/gen_ps5_ninja.py" || exit 1
( cd "$HOME/ps5build" && ninja -k 0 -j "$(nproc)" 2>&1 | grep -E 'FAILED|error:' | head -30 )
test -s ps5build/libgk.a || { echo "libgk.a missing"; exit 1; }

step 3 "game extractor archive (ISO import on the console)"
python3 "$HERE/engine/gen_ps5_extractor.py" || exit 1
( cd "$HOME/ps5build_ext" && ninja -k 0 -j "$(nproc)" 2>&1 | grep -E 'FAILED|error:' | head -30 )

step 4 "graphics driver objects"
bash "$HERE/driver/build/setup.sh" || exit 1
bash "$HERE/driver/build/drv_cc_cache.sh" && bash "$HERE/driver/build/drv_cc_backend.sh" && bash "$HERE/driver/build/drv_cc_egl.sh" || exit 1

step 5 "app packaging tree and eboot.bin"
bash "$HERE/app/setup_ogapp.sh" || exit 1
bash "$HERE/app/rebuild_all.sh" || exit 1
ls -la "$HOME/ogapp/dist/LAPY77001/"
echo "FIRST_BUILD_DONE"
} 2>&1 | tee "$HOME/first_build.log"
