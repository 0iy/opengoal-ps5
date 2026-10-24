#!/usr/bin/env bash
# usage: build.sh source.c out.elf [extra libs]
set -e
export PATH="/c/Program Files/LLVM/bin:$PATH"
SDK="${PS5_SDK:?set PS5_SDK to your ps5-payload-sdk install}"
export SCE_PROSPERO_SDK_DIR="$SDK"
SRC=$1; OUT=$2; shift 2
clang -target x86_64-sie-ps5 -fvisibility-nodllstorageclass=default -isysroot "$SDK" -isystem "$SDK/target/include" -fno-stack-protector -fno-plt -femulated-tls -Wall -c -o "${OUT%.elf}.o" "$SRC"
ld.lld -m elf_x86_64_fbsd --sysroot="$SDK" -pie --eh-frame-hdr --hash-style=sysv --build-id=uuid --unresolved-symbols=report-all -z now -z start-stop-visibility=hidden -z rodynamic -z common-page-size=0x4000 -z max-page-size=0x4000 --default-script "$SDK/target/lib/main.script" -o "$OUT" -L"$SDK/target/lib" "$SDK/target/lib/crt1.o" "$SDK/target/lib/crti.o" "$SDK/target/lib/crtbegin.o" "${OUT%.elf}.o" -lSceLibcInternal -lSceNet -lkernel_web "$@" "$SDK/target/lib/crtend.o" "$SDK/target/lib/crtn.o"
ls -la "$OUT"
