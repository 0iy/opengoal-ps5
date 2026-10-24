#!/usr/bin/env bash
# usage: addr2sym.sh <runtime ps5_log address hex> <runtime addr hex>...
# Resolves runtime addresses from the CRASH log lines to function names using build/llvm-pie.elf.
ELF=$HOME/ogapp/build/llvm-pie.elf
NM=llvm-nm-18
A2L=llvm-symbolizer-18
command -v $A2L >/dev/null || A2L=llvm-addr2line-18
static=$($NM "$ELF" | awk '$3=="_Z7ps5_logPKcz"||$3=="ps5_log"{print $1; exit}')
echo "static ps5_log = 0x$static"
slide=$(( 0x$1 - 0x$static ))
printf 'slide = 0x%x\n' "$slide"
shift
for a in "$@"; do
  s=$(( 0x$a - slide ))
  printf '%s -> static 0x%x : ' "$a" "$s"
  $A2L --obj="$ELF" --functions=short --demangle "$(printf '0x%x' $s)" 2>/dev/null | head -2 | tr '\n' ' '
  echo
done
