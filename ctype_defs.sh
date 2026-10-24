#!/usr/bin/env bash
cd "$HOME/ogapp/.deps/native/ps5-payload-sdk/target/include" || exit 1
grep -rn 'define[[:space:]]*_CTYPE_' . | head -30
echo ---
sed -n 100,140p xlocale/_ctype.h
echo ---
grep -n '___runetype_l\|___tolower_l\|___toupper_l\|___mb_cur_max_l\|__runes_for_locale' -r . | head -12
