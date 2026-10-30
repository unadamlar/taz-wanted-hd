#!/bin/sh
# Builds the release zip: dist/taz-wanted-hd-<version>.zip with the DLL, upscaled textures and
# videos (from extracted/, made by tools/pak.py, upscale.py and videos.py), README and license.
# usage: tools/package.sh <version>
set -e
cd "$(dirname "$0")/.."
v=${1:?usage: package.sh <version>}
out=dist/taz-wanted-hd-$v
make
rm -rf "$out" "$out.zip"
mkdir -p "$out/taz-hd"
cp build/d3d8.dll "$out/"
cp extracted/textures/fingerprints.tsv "$out/taz-hd/"
cp -r extracted/upscaled "$out/taz-hd/textures"
mkdir -p "$out/taz-hd/videos"
for d in extracted/videos/*/; do cp -r "$d" "$out/taz-hd/videos/"; done
sed "s/VERSION/$v/" package/README.txt > "$out/README.txt"
cp LICENSE "$out/LICENSE.txt"
(cd "$out" && zip -qr -0 "../taz-wanted-hd-$v.zip" .) # PNG and JPEG don't compress further
ls -la "$out.zip"
