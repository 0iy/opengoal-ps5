#!/usr/bin/env bash
# usage: build.sh source.c out.elf [extra libs]   (PS5_SDK defaults to $HOME/ps5app/.deps/native/ps5-payload-sdk)
set -e
SDK="${PS5_SDK:-$HOME/ps5app/.deps/native/ps5-payload-sdk}"
export PATH="$SDK/bin:$PATH:/c/Program Files/LLVM/bin"
export SCE_PROSPERO_SDK_DIR="$SDK"
SRC=$1; OUT=$2; shift 2
KERN=-lkernel_web; case " $* " in *" -lkernel_sys "*) KERN= ;; esac  # a payload that needs getfsstat/statfs passes -lkernel_sys instead
# Linux/WSL: the SDK's own ld.lld is too old for --default-script, so its prospero-clang wrapper (same target, libs and crt) does the build
if ! ld.lld --help 2>&1 | grep -q -- --default-script && [ -x "$SDK/bin/prospero-clang" ]; then
  "$SDK/bin/prospero-clang" -Wall -O2 -o "$OUT" "$SRC" "$@"
  ls -la "$OUT"; exit 0
fi
clang -target x86_64-sie-ps5 -fvisibility-nodllstorageclass=default -isysroot "$SDK" -isystem "$SDK/target/include" -fno-stack-protector -fno-plt -femulated-tls -Wall -c -o "${OUT%.elf}.o" "$SRC"
ld.lld -m elf_x86_64_fbsd --sysroot="$SDK" -pie --eh-frame-hdr --hash-style=sysv --build-id=uuid --unresolved-symbols=report-all -z now -z start-stop-visibility=hidden -z rodynamic -z common-page-size=0x4000 -z max-page-size=0x4000 --default-script "$SDK/target/lib/main.script" -o "$OUT" -L"$SDK/target/lib" "$SDK/target/lib/crt1.o" "$SDK/target/lib/crti.o" "$SDK/target/lib/crtbegin.o" "${OUT%.elf}.o" -lSceLibcInternal -lSceNet $KERN "$@" "$SDK/target/lib/crtend.o" "$SDK/target/lib/crtn.o"
ls -la "$OUT"
