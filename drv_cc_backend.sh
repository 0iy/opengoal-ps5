#!/bin/bash
# compile ps5_agc_runtime_backend.c (includes ps5_agc_native_runtime.c) with async native prep -> ~/drv/out/ps5_agc_runtime_backend.o
cd ~/drv
FLAGS=$(sed -n 2,3p rc.txt | tr '\n' ' ')
DEFS=$(sed -n 4,5p rc.txt | tr '\n' ' ')
env PS5_PAYLOAD_SDK="${PS5_PAYLOAD_SDK:-$HOME/ps5app/.deps/native/ps5-payload-sdk}" sh ~/ogapp/tooling/prospero-clang18 $FLAGS -Wno-error ${TLSFLAG--femulated-tls} $DEFS \
  -I$HOME/gl/src/ps5-opengl/src/platform -Wno-error=unused-function -DPS5_ASYNC_NATIVE_PREP=1 -DPS5_NATIVE_PREP_WORKERS=${WORKERS:-2} \
  -Dmain=ps5_agc_gate2_run_sync -DAGC_TRIANGLE_SUBMIT=1 -DAGC_RUNTIME_PACKAGES=1 ${EXTRA:-} \
  -c -o out/ps5_agc_runtime_backend.o $HOME/gl/src/ps5-opengl/src/platform/ps5_agc_runtime_backend.c 2>&1 | grep -E "fatal error|error:" | head
ls -la out/ps5_agc_runtime_backend.o
