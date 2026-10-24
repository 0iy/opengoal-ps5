#!/bin/bash
# compile the PS5 gallium driver (ps5_screen.c) from ~/gl/src with the SDK's flags -> ~/drv/out/ps5_screen.o
cd ~/drv
FLAGS=$(sed -n 2,3p rc.txt | tr '\n' ' ')
DEFS=$(sed -n 4,5p rc.txt | tr '\n' ' ')
env PS5_PAYLOAD_SDK="${PS5_PAYLOAD_SDK:-$HOME/ps5app/.deps/native/ps5-payload-sdk}" sh ~/ogapp/tooling/prospero-clang18 $FLAGS -Wno-error $DEFS \
  -I$HOME/gl/src/ps5-opengl/src/platform -I$HOME/drv/tp/mesa-26.2.0/src/mesa -DPS5_ENABLE_COMPRESSED_FALLBACK_CANDIDATE=1 -DPS5_ENABLE_CORE_CONTEXT_CANDIDATE=1 -Wno-unreachable-code-generic-assoc \
  ${EXTRA:-} -c -o out/ps5_screen.o $HOME/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c 2>&1 | grep -E "fatal error|error:" | head -10
ls -la out/ps5_screen.o 2>&1
