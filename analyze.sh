#!/usr/bin/env bash
cd "$HOME/jak_check" || exit 1
echo "== fatal errors (missing headers) =="
grep -h 'fatal error' *.log | sed -E 's/^[^ ]+ fatal error: //' | sort | uniq -c | sort -rn | head -12
echo "== other errors (normalized) =="
grep -h ' error: ' *.log | grep -v 'fatal error' | sed -E 's/^[^ ]+ error: //' | sed -E "s/'[^']*'/X/g" | sort | uniq -c | sort -rn | head -12
