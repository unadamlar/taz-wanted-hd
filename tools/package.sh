#!/bin/sh
# Builds the release zip: dist/taz-wanted-hd-<version>.zip with the DLL, upscaled textures, videos
# and character models (from extracted/, made by tools/pak.py, upscale.py, videos.py and meshpack.py),
# install.sh, README and license, and dist/taz-wanted-hd-<version>-setup.exe, the one-file Windows
# installer carrying the same DLL and taz-hd folder.
# usage: tools/package.sh <version>
set -e
cd "$(dirname "$0")/.."
v=${1:?usage: package.sh <version>}
out=dist/taz-wanted-hd-$v
make build/d3d8.dll installer
rm -rf "$out" "$out.zip"
mkdir -p "$out/taz-hd"
cp build/d3d8.dll package/install.sh "$out/"
cp extracted/textures/fingerprints.tsv "$out/taz-hd/"
cp -r extracted/upscaled "$out/taz-hd/textures"
mkdir -p "$out/taz-hd/videos"
for d in extracted/videos/*/; do cp -r "$d" "$out/taz-hd/videos/"; done
mkdir -p "$out/taz-hd/meshes"
cp extracted/meshes/out/*.bin "$out/taz-hd/meshes/"
sed "s/VERSION/$v/" package/README.txt > "$out/README.txt"
cp LICENSE "$out/LICENSE.txt"
mkdir -p "$out/taz-hd/licenses" # d3d8to9 is compiled into the DLL; its BSD-2 notice ships with it
cp third_party/d3d8to9/LICENSE.md "$out/taz-hd/licenses/d3d8to9-LICENSE.txt"
(cd "$out" && zip -qr -0 "../taz-wanted-hd-$v.zip" .) # PNG and JPEG don't compress further
tools/pack-installer.py build/installer.exe "$out" "$out-setup.exe"
ls -la "$out.zip"
