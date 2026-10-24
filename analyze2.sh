#!/usr/bin/env bash
cd "$HOME/jak_check2" || exit 1
echo "failed files: $(ls *.log 2>/dev/null | wc -l)"
echo "== failed files by subdir =="
ls *.log 2>/dev/null | sed -E 's/\.cpp\.log$//' | awk -F_ '{print $1"_"$2"_"$3}' | sort | uniq -c | sort -rn | head -15
echo "== missing headers =="
grep -h 'fatal error' *.log | sed -E 's/^[^ ]+ fatal error: //' | sort | uniq -c | sort -rn | head -12
echo "== other errors (normalized) =="
grep -h ' error: ' *.log | grep -v 'fatal error' | sed -E 's/^[^ ]+ error: //' | sed -E "s/'[^']*'/X/g" | sort | uniq -c | sort -rn | head -12
