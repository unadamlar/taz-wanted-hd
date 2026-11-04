#!/usr/bin/env python3
"""List or unpack Taz: Wanted .pc pak files, or extract their textures as PNG.

Format (from MuxaJlbl4's patcher): offsets in the header and file table are in
units of the pak alignment; a hidden entry holds the names block.
Textures: header starting with width and height, then top-down A1R5G5B5 pixels
(see images() for the variants).
"""
import hashlib
import re
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


A8R8G8B8, A1R5G5B5, A4R4G4B4 = 21, 25, 26  # D3DFORMAT values, as the game uploads them
FONT_HEADER = 1872


def images(name, blob):
    """(suffix, width, height, format, pixels) for each image in a texture entry; empty if it isn't one.
    .bmp/.tga: one image. .gif: animation frames, after a frame count at byte 15 and one duration
    per frame. Splash screens are split into numbered tiles (name.bmp.0 ...), each a plain image.
    .ttf: Babel fonts, a glyph table then a 256-wide A4R4G4B4 letter sheet."""
    if name.lower().endswith(".ttf") and len(blob) > FONT_HEADER:
        h = (len(blob) - FONT_HEADER) // 512
        return [("", 256, h, A4R4G4B4, blob[FONT_HEADER:FONT_HEADER + 512 * h])]
    if len(blob) < 32:
        return []
    w, h = struct.unpack_from("<II", blob, 0)
    size = w * h * 2
    if not w or not h:
        return []
    if name.lower().endswith(".gif"):
        n, base = blob[15], 28 + blob[15] * 4
        if len(blob) < base + n * size:
            return []
        return [(f".frame{i}", w, h, A1R5G5B5, blob[base + i * size:base + (i + 1) * size]) for i in range(n)]
    if name.lower().endswith((".bmp", ".tga")) or SPLASH_TILE.search(name):
        if blob[8] == 1:  # 32-bit with a full alpha channel (soft sprites, mostly .tga)
            return [("", w, h, A8R8G8B8, blob[32:32 + 2 * size])] if len(blob) >= 32 + 2 * size else []
        return [("", w, h, A1R5G5B5, blob[32:32 + size])] if len(blob) >= 32 + size else []
    return []


SPLASH_TILE = re.compile(r"\.bmp\.(\d+)$", re.IGNORECASE)


def rgba_rows(w, h, data, fmt=A1R5G5B5):
    """Pixels as PNG scanlines (filter byte + RGBA)."""
    if fmt == A8R8G8B8:  # stored B, G, R, A
        return [b"\0" + bytes(c for i in range(y * w, (y + 1) * w) for c in (data[4 * i + 2], data[4 * i + 1], data[4 * i], data[4 * i + 3]))
                for y in range(h)]
    px = struct.unpack(f"<{w * h}H", data)
    x5 = lambda v: (v << 3) | (v >> 2)
    if fmt == A4R4G4B4:
        conv = lambda v: ((v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17, (v >> 12) * 17)
    else:
        conv = lambda v: (x5(v >> 10 & 31), x5(v >> 5 & 31), x5(v & 31), 255 if v >> 15 else 0)
    rows = []
    for y in range(h):
        row = bytearray(b"\0")
        for v in px[y * w:(y + 1) * w]:
            row += bytes(conv(v))
        rows.append(bytes(row))
    return rows


def fingerprint(w, h, data, fmt=A1R5G5B5):
    """Same FNV-1a 64 the d3d8 proxy computes when the game uploads the image (rows as stored)."""
    v = 0xcbf29ce484222325
    for b in struct.pack("<III", w, h, fmt) + data:
        v = ((v ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return v | 1


def write_png(path, w, h, rows):
    chunk = lambda tag, body: struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def stitch_splash(desc, tiles):
    """Splash tiles back into one image. The descriptor holds the screen size and tile size; the
    bottom row of tiles runs past the screen, so the image keeps the full tile height."""
    full_w, full_h, tw, th = struct.unpack_from("<IIII", desc, 0x20)
    cols, rows = -(-full_w // tw), -(-full_h // th)
    canvas = [bytearray(b"\0" + bytes(full_w * 4)) for _ in range(rows * th)]
    rects = {}
    for i, (w, h, data) in tiles.items():
        x, y = (i % cols) * tw, (i // cols) * th
        for r, line in enumerate(rgba_rows(w, h, data)):
            if y + r < len(canvas):
                canvas[y + r][1 + x * 4:1 + (x + w) * 4] = line[1:1 + min(w, full_w - x) * 4]
        rects[i] = (x, y, w, h)
    return full_w, rows * th, [bytes(r) for r in canvas], rects


def texture_key(w, h, fmt, data):
    return hashlib.sha1(struct.pack("<III", w, h, fmt) + data).digest()


def extract_textures(out, paks):
    """Each unique image is written once, under the first pak that has it; index.tsv lists every occurrence.
    fingerprints.tsv maps the proxy's fingerprint to that file (plus a tile rectangle for splash screens),
    so replacements can keep the original names."""
    written = {}
    with open(out / "index.tsv", "w") as index, open(out / "fingerprints.tsv", "w") as fps:
        index.write("pak\tname\twidth\theight\tfile\n")
        for pak in paks:
            stem = Path(pak).stem
            content = dict(entries(Path(pak).read_bytes()))
            # A .bmp and a .tga of the same name with different pixels (zoocloud) keep their extensions,
            # or the second would overwrite the first's PNG while both fingerprints point at it.
            stems = {}
            for name, blob in content.items():
                for suffix, w, h, fmt, data in [] if SPLASH_TILE.search(name) else images(name, blob):
                    stems.setdefault(str(Path(name).with_suffix("")) + suffix, set()).add(texture_key(w, h, fmt, data))
            splash = {}
            for name, blob in content.items():
                tile = SPLASH_TILE.search(name)
                for suffix, w, h, fmt, data in images(name, blob):
                    if tile:
                        splash.setdefault(name[:tile.start()] + ".bmp", {})[int(tile.group(1))] = (w, h, data)
                        continue
                    key = texture_key(w, h, fmt, data)
                    if key not in written:
                        base = str(Path(name).with_suffix("")) + suffix
                        dest = Path(stem) / ((name + suffix if len(stems[base]) > 1 else base) + ".png")
                        write_png(out / dest, w, h, rgba_rows(w, h, data, fmt))
                        written[key] = (w, h, dest)
                        fps.write(f"{fingerprint(w, h, data, fmt):016x}\t{dest}\n")
                    w, h, dest = written[key]
                    index.write(f"{stem}\t{name}{suffix}\t{w}\t{h}\t{dest}\n")
            for desc_name, tiles in splash.items():
                desc = content.get(desc_name)
                if desc is None or len(desc) < 0x30:
                    continue
                key = hashlib.sha1(b"".join(d for _, (_, _, d) in sorted(tiles.items()))).digest()
                if key not in written:
                    fw, fh, rows, rects = stitch_splash(desc, tiles)
                    dest = Path(stem) / (str(Path(desc_name).with_suffix("")) + ".png")
                    write_png(out / dest, fw, fh, rows)
                    written[key] = (fw, fh, dest)
                    for i, (w, h, data) in tiles.items():
                        x, y, tw, th = rects[i]
                        fps.write(f"{fingerprint(w, h, data):016x}\t{dest}\t{x} {y} {tw} {th} {fw} {fh}\n")
                fw, fh, dest = written[key]
                index.write(f"{stem}\t{desc_name}\t{fw}\t{fh}\t{dest}\n")
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
