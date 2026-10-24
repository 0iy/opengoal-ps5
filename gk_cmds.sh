#!/usr/bin/env bash
set -u
cd "$HOME/jak_cfg" || exit 1
ninja -t commands gk > "$HOME/gk_cmds.txt" 2>"$HOME/gk_cmds.err"
echo "total commands: $(wc -l < "$HOME/gk_cmds.txt")"
echo "compile (c/c++): $(grep -cE ' -c ' "$HOME/gk_cmds.txt")"
echo "asm: $(grep -cE 'nasm' "$HOME/gk_cmds.txt")"
echo "== by directory (object output dirs) =="
grep -E ' -c ' "$HOME/gk_cmds.txt" | grep -oE ' -o [^ ]+' | sed -E 's# -o ##; s#/CMakeFiles/.*##' | sort | uniq -c | sort -rn | head -40
echo "== link command =="
tail -1 "$HOME/gk_cmds.txt" | cut -c1-600
