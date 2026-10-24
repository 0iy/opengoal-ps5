#!/usr/bin/env bash
# usage: disasm.sh <static address hex> [bytes before] [bytes after]
ELF=$HOME/ogapp/build/llvm-pie.elf
A=$((0x$1))
B=${2:-40}
C=${3:-40}
llvm-objdump-18 -d --no-show-raw-insn --demangle --start-address=$((A-B)) --stop-address=$((A+C)) "$ELF" | tail -n +5
