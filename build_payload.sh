#!/usr/bin/env bash
# Build a small C payload ELF with the PS5 payload SDK (Linux clang driver wrapper).
# usage: build_payload.sh <file.c> <out.elf> [extra clang args...]
set -euo pipefail
SRC=$1; OUT=$2; shift 2
export PS5_PAYLOAD_SDK=$HOME/ogapp/.deps/native/ps5-payload-sdk
"$PS5_PAYLOAD_SDK/bin/prospero-clang" -std=gnu11 -O2 -Wall "$SRC" -o "$OUT" -lSceNet "$@"
ls -la "$OUT"
