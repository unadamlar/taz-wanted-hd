#!/usr/bin/env python3
# Makes the one-file Windows installer: appends the mod's files to build/installer.exe, which reads
# them back from its own end (src/installer/install.c, open_pack).
# usage: tools/pack-installer.py <installer.exe> <mod folder with d3d8.dll and taz-hd> <out.exe>
import shutil, struct, sys
from pathlib import Path

exe, mod, out = map(Path, sys.argv[1:4])
# taz-hd in path order (the installer clears each subfolder when it first meets it), d3d8.dll last.
files = sorted((p for p in (mod / "taz-hd").rglob("*") if p.is_file()), key=lambda p: p.parts) + [mod / "d3d8.dll"]
with open(out, "wb") as o:
    o.write(exe.read_bytes())
    o.write(b"TAZHDPK1" + struct.pack("<IQ", len(files), sum(p.stat().st_size for p in files)))
    for p in files:
        name = str(p.relative_to(mod)).replace("/", "\\").encode()
        o.write(struct.pack("<H", len(name)) + name + struct.pack("<I", p.stat().st_size))
        with open(p, "rb") as f:
            shutil.copyfileobj(f, o, 1 << 20)
print(out, len(files), "files", out.stat().st_size >> 20, "MB")
