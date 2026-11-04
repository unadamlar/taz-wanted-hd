#!/bin/sh
# Builds two zips in dist/:
#   taz-wanted-hd-<version>.zip        DLL, README, license: our own work only, for GitHub.
#   taz-wanted-hd-<version>-assets.zip upscaled textures, videos and character models (made from the
#                                      game's files by tools/pak.py, upscale.py, videos.py, meshpack.py).
#                                      Never upload it to GitHub; it only goes into the pre-modded build.
# Both unzip into the game folder.
# usage: tools/package.sh <version>
set -e
cd "$(dirname "$0")/.."
v=${1:?usage: package.sh <version>}
out=dist/taz-wanted-hd-$v
assets=$out-assets
make
rm -rf "$out" "$out.zip" "$assets" "$assets.zip"
mkdir -p "$out" "$assets/taz-hd/videos" "$assets/taz-hd/meshes"
cp build/d3d8.dll "$out/"
sed "s/VERSION/$v/" package/README.txt > "$out/README.txt"
cp LICENSE "$out/LICENSE.txt"
cp extracted/textures/fingerprints.tsv "$assets/taz-hd/"
cp -r extracted/upscaled "$assets/taz-hd/textures"
for d in extracted/videos/*/; do cp -r "$d" "$assets/taz-hd/videos/"; done
cp extracted/meshes/out/*.bin "$assets/taz-hd/meshes/"
(cd "$out" && zip -qr "../taz-wanted-hd-$v.zip" .)
(cd "$assets" && zip -qr -0 "../taz-wanted-hd-$v-assets.zip" .) # PNG and JPEG don't compress further
ls -la "$out.zip" "$assets.zip"
