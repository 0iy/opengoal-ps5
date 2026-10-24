#!/usr/bin/env bash
# Build a C++ app variant (exceptions, RTTI, static libc++) from ~/ps5app.
# usage: build_cxx.sh <source dir relative to ~/ps5app> [extra archives relative to ~/ps5app]
set -uo pipefail
cd "$HOME/ps5app"
src=${1:-cxxtest/src}; shift || true
SDKLIB=.deps/native/ps5-payload-sdk/target/lib
mkdir -p libs
cp -n "$SDKLIB/libc++.a" libs/libcxx.a
cp -n "$SDKLIB/libc++abi.a" libs/libcxxabi.a
cp -n "$SDKLIB/libunwind.a" libs/libunwind.a
cp -n "$SDKLIB/libpthread.a" libs/libpthr.a
if ! grep -q 'no-dependent-libraries' tools/build-cxx.sh; then
  sed -i 's#ps5-pie.ld" --eh-frame-hdr#ps5-pie.ld" --no-dependent-libraries --eh-frame-hdr#' tools/build-cxx.sh
fi
grep -c 'no-dependent-libraries' tools/build-cxx.sh
export APP_SOURCE_DIR=$src
export APP_STATIC_ARCHIVES="libs/libcxx.a libs/libcxxabi.a libs/libunwind.a libs/libpthr.a $*"
bash tools/build-cxx.sh Folder 2>&1 | grep -E 'error|undefined|Build complete|wrote' | sort | uniq -c | sort -rn | head -40
