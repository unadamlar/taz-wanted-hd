#!/bin/sh
# Builds a replacement model from captured frames: the biggest captured character, with new hands,
# evened normals and springs, packed into extracted/meshes/out. Work files go in extracted/meshes/<name>.
# usage: tools/models.sh <name> <capture-001.bin> <capture-020.bin> ... (frames of one scene)
# NOHANDS=1 keeps the model's own hands (costumes with claws or gloves, other characters).
# BUFFER=n builds the n-th biggest captured character instead of the biggest (Taz).
# SPRINGS=<file.json> gives the springs listed there (see tools/springs.py) instead of Taz's.
set -e
cd "$(dirname "$0")/.."
name=$1; shift
B=${BLENDER:-$HOME/.local/share/devtools/blender/blender}
d=extracted/meshes/$name
mkdir -p "$d" extracted/meshes/out
run() { "$B" -b "$@" 2>&1 | grep -E '^(mesh|hands|spring|packed)|Error|Traceback' || true; }
run -P tools/meshview.py -- "$d/model.blend" "${BUFFER:-0}" "$@"
if [ -n "$NOHANDS" ]; then cp "$d/model.blend" "$d/hands.blend"; else run "$d/model.blend" -P tools/hands.py -- "$d/hands.blend"; fi
run "$d/hands.blend" -P tools/normals.py -- "$d/final.blend"
run "$d/final.blend" -P tools/springs.py -- "$d/springs.blend" $SPRINGS
run "$d/springs.blend" -P tools/meshpack.py -- extracted/meshes/out
