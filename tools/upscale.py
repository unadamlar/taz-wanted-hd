#!/usr/bin/env python3
"""Upscale extracted textures 4x with Real-ESRGAN, keeping repeating textures seamless.

usage: upscale.py <extracted_dir> <out_dir> [name_filter]

Each texture is padded with its own opposite edges (as it repeats in game), upscaled, then the
padding is cropped, so tiled surfaces don't get seams. The transparency mask goes through the
upscaler as its own image; on/off masks (cut-outs) are cut back to hard edges, soft ones (fonts) stay soft.
Invisible pixels are first filled with neighbouring colours so dark fringes don't bleed into edges.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ESRGAN = Path.home() / ".local/share/devtools/realesrgan/realesrgan-ncnn-vulkan"
MODEL = "realesrgan-x4plus-anime"
PAD = 8


def bleed(px):
    """Spread opaque colours into transparent pixels, a few pixels at a time."""
    rgb = px[..., :3].astype(np.float32)
    known = px[..., 3] >= 128
    if known.all() or not known.any():
        return px[..., :3]
    for _ in range(16):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        grow = ~known & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow, None]
        known = known | grow
        if known.all():
            break
    rgb[~known] = rgb[known].mean(0)
    return rgb.astype(np.uint8)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    wanted = sys.argv[3] if len(sys.argv) > 3 else ""
    files = sorted(p for p in src.rglob("*.png") if wanted in str(p.relative_to(src)))
    with tempfile.TemporaryDirectory() as tmp:
        stage, done = Path(tmp, "in"), Path(tmp, "out")
        stage.mkdir()
        done.mkdir()
        alpha = {}  # index -> mask is on/off only
        for i, p in enumerate(files):
            px = np.asarray(Image.open(p).convert("RGBA"))
            pad = min(PAD, *px.shape[:2])
            padded = np.pad(px, ((pad, pad), (pad, pad), (0, 0)), mode="wrap")
            Image.fromarray(bleed(padded)).save(stage / f"{i}.png")
            if (px[..., 3] < 255).any():
                alpha[i] = bool(np.isin(px[..., 3], (0, 255)).all())
                Image.fromarray(padded[..., 3]).convert("RGB").save(stage / f"{i}a.png")
        subprocess.run([str(ESRGAN), "-i", str(stage), "-o", str(done), "-n", MODEL, "-s", "4", "-f", "png"],
                       check=True, stdout=subprocess.DEVNULL)
        for i, p in enumerate(files):
            rgb = np.asarray(Image.open(done / f"{i}.png").convert("RGB"))
            h, w = Image.open(p).size[::-1]
            pad = min(PAD, h, w) * 4
            rgb = rgb[pad:pad + h * 4, pad:pad + w * 4]
            if i in alpha:
                a = np.asarray(Image.open(done / f"{i}a.png").convert("L"))[pad:pad + h * 4, pad:pad + w * 4]
                a = np.where(a >= 128, 255, 0).astype(np.uint8) if alpha[i] else a
                img = Image.fromarray(np.dstack([rgb, a]), "RGBA")
            else:
                img = Image.fromarray(rgb, "RGB")
            dest = out / p.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest)
    print(f"{len(files)} textures upscaled into {out}")


if __name__ == "__main__":
    main()
