# Taz: Wanted HD

An unofficial fan remaster mod for the 2002 PC release of Taz: Wanted. It runs the game at your
desktop resolution and screen shape, replaces its textures and intro videos with 4x upscaled
versions, rounds off the characters' low-poly models, gives Taz rounder hands and cleaner shading, adds WASD and mouse-look controls, speeds up the
menu text and adds quicksave/quickload (F5/F9).

It is a mod, not a copy of the game: you need your own retail install and its disc (or disc image).

## Install

Download the zip from [Releases](../../releases), unzip it into the game folder next to `taz.exe`,
and follow the `README.txt` inside (Windows, Steam/Proton and Lutris steps, settings, uninstall).
The same text is in [package/README.txt](package/README.txt).

## Build from source

Needs Linux, `i686-w64-mingw32-gcc`, Python 3 with numpy and Pillow, ffmpeg, zip, and
[realesrgan-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) on `PATH` (or set
`REALESRGAN` to its path). The textures and videos are made from your own copy of the game:

```sh
GAME=/path/to/taz-wanted
make                                                         # build/d3d8.dll
tools/pak.py textures extracted/textures "$GAME"/Paks/*.pc   # originals + fingerprints.tsv
tools/upscale.py extracted/textures extracted/upscaled       # slow: GPU upscale of every texture
tools/videos.py "$GAME" extracted/videos
# Taz's model: in a level, a taz-hd\capture file holding 60 records 60 frames as taz-hd\capture-NNN.bin
blender -b -P tools/meshview.py -- extracted/meshes/taz.blend 0 capture-001.bin capture-020.bin capture-040.bin capture-060.bin
blender -b extracted/meshes/taz.blend -P tools/hands.py -- extracted/meshes/taz-hands.blend
blender -b extracted/meshes/taz-hands.blend -P tools/normals.py -- extracted/meshes/taz-final.blend
blender -b extracted/meshes/taz-final.blend -P tools/meshpack.py -- extracted/meshes/out
tools/package.sh 0.2                                         # dist/taz-wanted-hd-0.2.zip
```

`extracted/`, `build/` and `dist/` are git-ignored. Never commit game files or anything made
from them.

## Development

`tools/run-dev.sh` starts a dev install with `umu-run` after mounting the disc image with
`tools/mount-cd.sh` (needs udisks2). Both read local paths from `dev.env` in the repo root, which
is git-ignored:

```sh
TAZ_GAME=${TAZ_GAME:-$HOME/Games/taz-wanted}                 # game folder, d3d8.dll linked to build/
WINEPREFIX=${WINEPREFIX:-$HOME/.local/share/wineprefixes/taz}
ISO=${ISO:-$HOME/Games/taz-wanted.iso}                        # disc image
# PROTONPATH=...                                              # optional, umu picks one otherwise
```

Engine notes, addresses and the testing setup are in [AGENTS.md](AGENTS.md).

## License

The mod's code is MIT ([LICENSE](LICENSE)). Taz: Wanted is (c) Warner Bros. Entertainment,
developed by Blitz Games and published by Infogrames. This project is not affiliated with or
endorsed by them.
