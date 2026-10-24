#!/usr/bin/env bash
# OpenGOAL-PS5 import window for macOS and Linux (double-click on macOS, or run from a terminal). Needs Python 3.
# Files passed as arguments are added to the list.
here=$(cd "$(dirname "$0")" && pwd)
py=$(command -v python3 || command -v python)
if [ -z "$py" ] || ! "$py" -c 'import sys; sys.exit(sys.version_info[0] != 3)' 2>/dev/null; then
  msg="Python 3 is needed. macOS: run xcode-select --install in Terminal (free), or install it from https://www.python.org/downloads/ . Linux: install python3 (and python3-tk for the window)."
  if [ "$(uname)" = Darwin ] && command -v osascript >/dev/null; then osascript -e "display dialog \"$msg\" buttons {\"OK\"}" >/dev/null; fi
  echo "$msg" >&2; exit 1
fi
exec "$py" "$here/../OpenGOAL-PS5-gui.py" "$@"
