#!/usr/bin/env bash
# Prepare the driver build in WSL: unpack the ps5-opengl sources of the SDK release, apply driver/ps5-opengl.patch and
# create ~/drv (the directory the drv_cc*.sh scripts compile in). Needs the SDK release archive (see driver/README.md).
# usage: setup.sh [path/to/sdk.tgz]       default: ~/gl/sdk.tgz
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GL=${GL:-$HOME/gl}
TGZ=${1:-$GL/sdk.tgz}
WANT=f93643c04c843d56143b00951df1f8042ea7706ae9f19e4e9abf158e1ead77c5
[ -s "$TGZ" ] || { echo "SDK archive not found: $TGZ" >&2; exit 1; }
echo "$WANT  $TGZ" | sha256sum --check --status || { echo "unexpected SDK archive (sha256 differs from $WANT)" >&2; exit 1; }
mkdir -p "$GL/src"
[ -d "$GL/ps5-opengl-sdk-1.0.0" ] || tar xzf "$TGZ" -C "$GL"
if [ ! -d "$GL/src/ps5-opengl" ]; then
  tar xf "$GL/ps5-opengl-sdk-1.0.0/sources/ps5-opengl.tar" -C "$GL/src"
  (cd "$GL/src/ps5-opengl" && patch -p1 < "$HERE/../ps5-opengl.patch")
else
  (cd "$GL/src/ps5-opengl" && patch -p1 --dry-run -R < "$HERE/../ps5-opengl.patch" >/dev/null) \
    || { echo "$GL/src/ps5-opengl exists but does not carry the patch; move it away and run again" >&2; exit 1; }
  echo "sources already patched"
fi
# compile directory: objects go to ~/drv/out; headers and Mesa come from the prepared SDK source tree
mkdir -p "$HOME/drv/out" "$HOME/drv/tp"
ln -sfn "$GL/src/ps5-opengl/build/mesa-ps5-probe" "$HOME/drv/mbuild"
ln -sfn "$GL/src/ps5-opengl/third_party/mesa-26.2.0" "$HOME/drv/tp/mesa-26.2.0"
ln -sfn "$GL/src/ps5-opengl/third_party/opengnm-psbc" "$HOME/drv/tp/opengnm-psbc"
for d in mbuild tp/mesa-26.2.0 tp/opengnm-psbc; do
  [ -e "$HOME/drv/$d" ] || echo "note: ~/drv/$d is not available yet: prepare the SDK source tree first (driver/README.md, step 2)" >&2
done
echo "driver build directory ready: ~/drv (next: bash $HERE/drv_cc_cache.sh && bash $HERE/drv_cc_backend.sh && bash $HERE/drv_cc_egl.sh)"
