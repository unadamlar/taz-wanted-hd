#!/bin/sh
# Builds a replacement model from captured frames: the biggest captured character, with new hands,
# evened normals, springs and a dense smooth surface, packed into extracted/meshes/out. Work files go in
# extracted/meshes/<name>.
# usage: tools/models.sh <name> <capture-001.bin> <capture-020.bin> ... (frames of one scene)
# Without captures it rebuilds from the springs.blend made earlier.
# NOHANDS=1 keeps the model's own hands (costumes with claws or gloves, other characters).
# BUFFER=n builds the n-th biggest captured character instead of the biggest (Taz).
# SPRINGS=<file.json> gives the springs listed there (see tools/springs.py) instead of Taz's.
# LEVELS=n subdivides n times (default 2; 0 skips it).
set -e
cd "$(dirname "$0")/.."
name=$1; shift
B=${BLENDER:-$HOME/.local/share/devtools/blender/blender}
d=extracted/meshes/$name
mkdir -p "$d" extracted/meshes/out
run() { "$B" -b "$@" 2>&1 | grep -E '^(mesh|hands|spring|subdivide|packed)|Error|Traceback' || true; }
if [ $# -gt 0 ]; then
    run -P tools/meshview.py -- "$d/model.blend" "${BUFFER:-0}" "$@"
    if [ -n "$NOHANDS" ]; then cp "$d/model.blend" "$d/hands.blend"; else run "$d/model.blend" -P tools/hands.py -- "$d/hands.blend"; fi
    run "$d/hands.blend" -P tools/normals.py -- "$d/final.blend"
    run "$d/final.blend" -P tools/springs.py -- "$d/springs.blend" $SPRINGS
fi
if [ "${LEVELS:-2}" -gt 0 ]; then run "$d/springs.blend" -P tools/subdivide.py -- "$d/dense.blend" "${LEVELS:-2}"; else cp "$d/springs.blend" "$d/dense.blend"; fi
run "$d/dense.blend" -P tools/meshpack.py -- extracted/meshes/out
