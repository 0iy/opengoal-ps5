#!/bin/bash
# compile the EGL layer (egl/ps5_egl.c) with the driver flags -> ~/drv/out/ps5_egl.o; link it before libPS5OpenGL.a (app/setup_ogapp.sh does)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RC="${DRV_RC:-$HERE/rc.txt}"   # compiler flags (lines 2-3) and defines (lines 4-5) of the SDK build; $HOME is expanded here
cd ~/drv
FLAGS=$(sed -n 2,3p "$RC" | tr '\n' ' ' | sed "s#\$HOME#$HOME#g")
DEFS=$(sed -n 4,5p "$RC" | tr '\n' ' ' | sed "s#\$HOME#$HOME#g")
env PS5_PAYLOAD_SDK="${PS5_PAYLOAD_SDK:-$HOME/ps5app/.deps/native/ps5-payload-sdk}" sh ~/ogapp/tooling/prospero-clang18 $FLAGS -Wno-error $DEFS \
  -I$HOME/gl/src/ps5-opengl/src/platform -I$HOME/gl/src/ps5-opengl/src/egl -I$HOME/drv/tp/mesa-26.2.0/src/mesa -DHAVE_PTHREAD=1 -DHAVE_STRUCT_TIMESPEC=1 -DPS5_ENABLE_COMPRESSED_FALLBACK_CANDIDATE=1 -DPS5_ENABLE_CORE_CONTEXT_CANDIDATE=1 -Wno-unreachable-code-generic-assoc \
  ${EXTRA:-} -c -o out/ps5_egl.o $HOME/gl/src/ps5-opengl/src/egl/ps5_egl.c 2>&1 | grep -E "fatal error|error:" | head -10
ls -la out/ps5_egl.o 2>&1
