# Taz: Wanted HD

HD remaster mod for the 2002 PC release of Taz: Wanted (Blitz Games, Babel engine, Direct3D 8, MSVC 6).
Shape: a loader DLL and asset packs applied to the user's own copy; later an optional modern render mode by hooking Babel's PC render layer (`C:\Babel\PC\Src\bDisplay`, `bActor`).

## Local setup
- Pristine install: a retail install kept outside the repo (never modify). `taz.exe` linked 2002-07-22.
- Dev install: `~/Games/taz-wanted` (btrfs reflink copy). `d3d8.dll` there is a symlink to `build/d3d8.dll`; it writes `taz-hd.log` in the game folder.
- Wine prefix: `~/.local/share/wineprefixes/tazwanted`, now Proton-format (system `wine` can't open it; edit `*.reg` directly with nothing running). The game needs `Software\Infogrames\TazWanted\Release` `Location` = install dir; a preinstalled copy has no installer to write it.
- The game checks for its CD (volume label). Disc image: `~/Games/taz-wanted-cd/taz-wanted.iso` (label TAZWANTED; its exes are byte-identical to the install). `tools/mount-cd.sh` mounts it and points the prefix's `D:` at it.
- Lutris entry: dev install, that prefix, override `d3d8=n,b`, pre-launch `tools/mount-cd.sh`.
- Texture pipeline (in the proxy): fingerprint = FNV-1a 64 over (w, h, D3DFORMAT as 3 u32) + level-0 rows, `|1`. Pak textures are uploaded unchanged as format 25, so `tools/pak.py textures` writes the same fingerprints to `fingerprints.tsv`; copy it to `<game>/taz-hd/fingerprints.tsv`. Replacement lookup: `<game>/taz-hd/textures/<pak>/<path>.png` by name, then `<fingerprint>.png`. Any size; mipmaps generated. If `<game>/taz-hd/dump/` exists, every uploaded texture is saved as `<fingerprint>.png` (about 85% of a level's textures come from paks).
- Ghidra project lives in `re/` (ignored). `make` builds the proxy with mingw-w64.
- `tools/pak.py list|unpack|textures` reads `.pc` paks; `textures` writes each unique texture once as PNG plus `index.tsv` (all occurrences). Output goes in `extracted/` (ignored). Textures are 16-bit, mostly 64-128 px, max 512; 6,512 unique.

## Rules
- The game exe is a downloaded copy: agents analyse it statically; the user launches it.
- Never commit game binaries, pak files, or anything extracted from them. Public releases ship only our code and our assets.
