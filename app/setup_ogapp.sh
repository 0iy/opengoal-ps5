#!/usr/bin/env bash
# Assemble ~/ogapp: the boilerplate packaging pipeline + PS5 OpenGL native-app link recipe + libgk.a.
set -euo pipefail
APP=$HOME/ogapp
SRC=$HOME/ps5app
GL=$HOME/gl/src/ps5-opengl
GLSDK=${GLSDK:-$HOME/gl/ps5-opengl-sdk-1.0.0}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # repository root

mkdir -p "$APP"
for d in assets runtime sce_sys tooling tools; do
  rm -rf "$APP/$d"
  cp -a "$SRC/$d" "$APP/"
done
cp "$SRC/Makefile" "$APP/"
[ -d "$APP/.deps" ] || cp -a "$SRC/.deps" "$APP/.deps"
SDK=$APP/.deps/native/ps5-payload-sdk

# 256 MiB module heap (as in the PS5 OpenGL native test app)
python3 - "$APP/tooling/native/sce_module_writer.cpp" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = "write_u64(result.data, result.heap_size, std::numeric_limits<std::uint64_t>::max());"
new = "write_u64(result.data, result.heap_size, 0x10000000ULL);"
assert old in s or new in s
open(p, "w").write(s.replace(old, new))
PY

# link recipe: malloc wraps (app_heap.c), exceptions + RTTI for the engine's own sources
sed -i 's/--eh-frame-hdr \\/--eh-frame-hdr --wrap=malloc --wrap=calloc --wrap=realloc --wrap=free --wrap=posix_memalign --wrap=malloc_usable_size --wrap=printf --wrap=clock_gettime \\/' "$APP/tools/build.sh"
sed -i 's/args+=(-fno-exceptions -fno-rtti)/args+=(-fexceptions -frtti)/' "$APP/tools/build.sh"
cp "$SRC/tooling/native/ps5-pie.ld" "$APP/tooling/native/ps5-pie-base.ld"
cp "$GL/native-app/ps5-pie.ld" "$APP/tooling/native/ps5-pie.ld"
cp "$GL/native-app/app-symbols.map" "$APP/tooling/native/app-symbols.map"

# Agc link stubs
mkdir -p "$APP/build/native-imports"
for pair in "agc_link_stub:libSceAgc" "agc_driver_link_stub:libSceAgcDriver"; do
  obj=${pair%%:*}; lib=${pair##*:}
  PS5_PAYLOAD_SDK="$SDK" sh "$APP/tooling/prospero-clang18" -std=c11 -O2 -fPIC -ffunction-sections -fdata-sections \
    -c "$GL/native-app/$obj.c" -o "$APP/build/native-imports/$obj.o"
  "$SDK/bin/prospero-lld" --shared -soname "$lib.prx" -o "$SDK/target/lib/$lib.so" "$APP/build/native-imports/$obj.o"
done

# sources
rm -rf "$APP/src" "$APP/include" "$APP/vendor"
mkdir -p "$APP/src" "$APP/include" "$APP/vendor"
cp "$GL/native-app/runtime_shims.c" "$GL/native-app/app_heap.c" "$APP/src/"
cp "$HERE/app/glue/"* "$APP/src/"
for h in EGL GL KHR; do cp -a "$GLSDK/sdk/include/$h" "$APP/include/"; done
cp "$GLSDK/sdk/include/"ps5_opengl_display*.h "$APP/include/"

# group archive (linker script) with the engine and the GL runtime
RT=$(clang-18 --print-resource-dir)/lib/linux/libclang_rt.builtins-x86_64.a
test -s "$RT"
cp "$HOME/ps5build/libgk.a" "$APP/vendor/libgk.a"
{
  printf 'SEARCH_DIR("%s")\n' "$SDK/target/lib"
  printf 'EXTERN(main)\n'
  printf 'EXTERN(ps5_agc_gate2_run)\n'
  printf 'GROUP (\n'
  printf '  "%s"\n' "$HOME/drv/out/ps5_screen.o" "$HOME/drv/out/ps5_agc_runtime_backend.o" "$HOME/drv/out/ps5_egl.o" "$APP/vendor/libgk.a" "$GLSDK/sdk/lib/libPS5OpenGL.a" "$HOME/ps5build_ext/libextractor.a" \
    "$SDK/target/lib/libunwind.a" "$SDK/target/lib/libc++abi.a" "$SDK/target/lib/libc++.a" "$RT"
  printf ')\n'
} > "$APP/vendor/libog_group.a"
printf 'APP_INCLUDE_PATHS = include\nAPP_STATIC_ARCHIVES = vendor/libog_group.a\n' > "$APP/.env"

# identity + display metadata
(cd "$APP" && make init TITLE_ID=PPSA77001 APP_NAME="OpenGOAL" >/dev/null)
cp "$HERE/art/sce_sys/param.json" "$APP/sce_sys/param.json"  # title id LAPY77001 (make init only accepts PPSA ids)
python3 "$GL/tools/native-display-metadata.py" "$APP/sce_sys/param.json" --fps 60 --sdk-prefix "$GLSDK/sdk" || true
echo "ogapp ready: $APP"
