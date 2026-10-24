#!/usr/bin/env bash
# OpenGOAL-PS5 one-liner bootstrap (macOS/Linux). User runs:   curl -fsSL <BASE>/bootstrap.sh | bash
# What it does, nothing else: downloads SHA256SUMS and OpenGOAL-PS5-gui.zip from the same release, checks the zip's SHA-256,
# unpacks it to ~/.opengoal-ps5/app and starts the import window. No sudo, no system settings changed, no installs.
# Test/override: OGPS5_BASE (other base URL), OGPS5_NORUN=1 (stop after unpacking).
set -euo pipefail
# PLACEHOLDER: replace <owner>/<repo> when the release exists (make_release does not know it).
BASE=${OGPS5_BASE:-https://github.com/<owner>/<repo>/releases/latest/download}
case $BASE in *'<owner>'*) echo "bootstrap.sh: the download address is still the placeholder <owner>/<repo>. Use the one-liner from the release page." >&2; exit 1;; esac
DIR=$HOME/.opengoal-ps5; ZIP=OpenGOAL-PS5-gui.zip
echo "OpenGOAL-PS5 will now:"
echo "  1. download $BASE/SHA256SUMS and $BASE/$ZIP"
echo "  2. verify the zip against SHA256SUMS (stops if it does not match)"
echo "  3. unpack it to $DIR/app and open the import window (gui/macos/OpenGOAL-PS5.command)"
mkdir -p "$DIR"; TMP=$DIR/download; rm -rf "$TMP"; mkdir "$TMP"
curl -fsSL "$BASE/SHA256SUMS" -o "$TMP/SHA256SUMS"
curl -fsSL "$BASE/$ZIP" -o "$TMP/$ZIP"
want=$(awk -v f="$ZIP" '{n=$2; sub(/^\*/,"",n)} n==f {print $1; exit}' "$TMP/SHA256SUMS")
if command -v sha256sum >/dev/null; then got=$(sha256sum "$TMP/$ZIP" | cut -d' ' -f1); else got=$(shasum -a 256 "$TMP/$ZIP" | cut -d' ' -f1); fi
got=${got//\\/}  # git-bash sha256sum prefixes a backslash for Windows paths
[ -n "$want" ] || { echo "SHA256SUMS has no entry for $ZIP. Nothing was run." >&2; exit 1; }
[ "$want" = "$got" ] || { echo "SHA-256 mismatch for $ZIP (expected $want, got $got). Nothing was run." >&2; exit 1; }
echo "SHA-256 OK: $got"
rm -rf "$DIR/app"; mkdir -p "$DIR/app"
if command -v unzip >/dev/null; then unzip -q "$TMP/$ZIP" -d "$DIR/app"; else python3 -c 'import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$TMP/$ZIP" "$DIR/app"; fi
rm -rf "$TMP"
[ -z "${OGPS5_NORUN:-}" ] || { echo "Unpacked to $DIR/app (OGPS5_NORUN set)."; exit 0; }
# stdin of a piped script is the script itself: give the GUI the terminal (needed only for the text fallback)
exec bash "$DIR/app/gui/macos/OpenGOAL-PS5.command" </dev/tty
