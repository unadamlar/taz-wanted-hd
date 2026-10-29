#!/usr/bin/env python3
"""List or unpack Taz: Wanted .pc pak files, or extract their textures as PNG.

Format (from MuxaJlbl4's patcher): offsets in the header and file table are in
units of the pak alignment; a hidden entry holds the names block.
Textures (.bmp entries): 32-byte header starting with width and height, then
top-down A1R5G5B5 pixels.
"""
import hashlib
import struct
import sys
import zlib
from pathlib import Path


def entries(data):
    align, = struct.unpack_from("<I", data, 0x04)
    count, info = struct.unpack_from("<II", data, 0x0C)
    names_off, names_size = struct.unpack_from("<II", data, 0x28)
    names = data[names_off * align:names_off * align + names_size]
    for i in range(count):
        off, _, size, name_off, is_file = struct.unpack_from("<5I", data, info * align + i * 32)
        if is_file == 0 and size == names_size:
            continue
        name = names[name_off:names.index(b"\0", name_off)].decode("ascii")
        yield name.replace("\\", "/"), data[off * align:off * align + size]


def texture_rgba(blob):
    w, h = struct.unpack_from("<II", blob, 0)
    if not w or not h or len(blob) < 32 + w * h * 2:
        return None
    px = struct.unpack_from(f"<{w * h}H", blob, 32)
    x5 = lambda v: (v << 3) | (v >> 2)
    rows = []
    for y in range(h):
        row = bytearray(b"\0")  # PNG filter type: none
        for v in px[y * w:(y + 1) * w]:
            row += bytes((x5(v >> 10 & 31), x5(v >> 5 & 31), x5(v & 31), 255 if v >> 15 else 0))
        rows.append(bytes(row))
    return w, h, b"".join(rows)


def fingerprint(blob):
    """Same FNV-1a 64 the d3d8 proxy computes when the game uploads the texture (format 25, rows as stored)."""
    w, h = struct.unpack_from("<II", blob, 0)
    v = 0xcbf29ce484222325
    for b in struct.pack("<III", w, h, 25) + blob[32:32 + w * h * 2]:
        v = ((v ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return v | 1


def write_png(path, w, h, raw):
    chunk = lambda tag, body: struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def extract_textures(out, paks):
    """Each unique texture is written once, under the first pak that has it; index.tsv lists every occurrence.
    fingerprints.tsv maps the proxy's fingerprint to that file, so replacements can keep the original names."""
    written = {}
    with open(out / "index.tsv", "w") as index, open(out / "fingerprints.tsv", "w") as fps:
        index.write("pak\tname\twidth\theight\tfile\n")
        for pak in paks:
            for name, blob in entries(Path(pak).read_bytes()):
                if not name.lower().endswith(".bmp"):
                    continue
                key = hashlib.sha1(blob).digest()
                if key not in written:
                    tex = texture_rgba(blob)
                    if tex is None:
                        continue
                    dest = Path(Path(pak).stem) / Path(name).with_suffix(".png")
                    (out / dest).parent.mkdir(parents=True, exist_ok=True)
                    write_png(out / dest, *tex)
                    written[key] = (tex[0], tex[1], dest)
                    fps.write(f"{fingerprint(blob):016x}\t{dest}\n")
                w, h, dest = written[key]
                index.write(f"{Path(pak).stem}\t{name}\t{w}\t{h}\t{dest}\n")
    return len(written)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 2 else None
    if cmd not in ("list", "unpack", "textures"):
        sys.exit("usage: pak.py list <pak>... | pak.py unpack|textures <out_dir> <pak>...")
    if cmd == "list":
        for pak in sys.argv[2:]:
            for name, blob in entries(Path(pak).read_bytes()):
                print(f"{Path(pak).name}\t{name}\t{len(blob)}")
        return
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    if cmd == "textures":
        print(f"{extract_textures(out, sys.argv[3:])} unique textures")
        return
    for pak in sys.argv[3:]:
        for name, blob in entries(Path(pak).read_bytes()):
            dest = out / Path(pak).stem / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)


if __name__ == "__main__":
    main()
