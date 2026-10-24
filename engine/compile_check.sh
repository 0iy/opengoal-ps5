#!/usr/bin/env bash
# Syntax-check jak-project sources against the PS5 SDK (libc++ headers) to estimate port effort.
# usage: compile_check.sh <dir under ~/jak> ...   -> writes ~/jak_check/<name>.log and summary
set -u
SDK=$HOME/ps5app/.deps/native/ps5-payload-sdk
J=$HOME/jak
OUT=$HOME/jak_check2
mkdir -p "$OUT"
export PS5_PAYLOAD_SDK=$SDK
INC=(-I"$J" -I"$J/third-party" -I"$J/third-party/fmt/include" -I"$J/third-party/glad/include"
     -I"$J/third-party/SDL/include" -I"$J/third-party/imgui" -I"$J/third-party/zstd/lib"
     -I"$J/third-party/inja" -I"$J/third-party/curl/include" -I"$J/third-party/stb_image"
     -I"$J/third-party/libco" -I"$J/third-party/cubeb/cubeb/include" -I"$J/third-party/mman"
     -I"$J/third-party/sqlite3" -I"$J/third-party/zydis" -I"$J/third-party/xdelta3"
     -I"$J/third-party/lzokay" -I"$J/third-party/tiny_gltf" -I"$J/third-party/draco/src"
     -I"$J/third-party/discord-rpc/include")
DEFS=(-DOS_POSIX -D__ps5__ -D__forceinline=inline -DMAP_POPULATE=0)
ok=0; bad=0
for d in "$@"; do
  while IFS= read -r f; do
    name=$(echo "$f" | tr '/' '_')
    if sh "$HOME/ps5app/tooling/prospero-clang18" -std=c++20 -fexceptions -frtti -fsyntax-only -w "${DEFS[@]}" "${INC[@]}" \
         "$J/$f" >"$OUT/$name.log" 2>&1; then ok=$((ok+1)); rm -f "$OUT/$name.log"; else bad=$((bad+1)); fi
  done < <(cd "$J" && find "$d" -name '*.cpp' | sort)
done
echo "ok=$ok bad=$bad"
