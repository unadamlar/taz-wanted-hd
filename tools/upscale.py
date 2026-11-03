#!/usr/bin/env python3
"""Upscale extracted textures 4x with Real-ESRGAN, keeping repeating textures seamless.

usage: upscale.py <extracted_dir> <out_dir> [name_filter]

Each texture is padded with its own opposite edges (as it repeats in game), upscaled, then the
padding is cropped, so tiled surfaces don't get seams. Along an axis whose opposite edges don't
continue each other (sky panels, grass-to-path joiners) it is mirrored instead: wrapping put the
other edge's colour and a drawn outline into the edge rows, which polygons that stretch an edge
show as a wrong colour or a line. Afterwards each upscale's broad colours are pulled back to the
original's (the upscaler drifts colour and contrast); fine detail is kept. The transparency mask goes through the
upscaler as its own image; on/off masks (cut-outs) are cut back to hard edges, soft ones (fonts) stay soft.
Mostly see-through sprites (glows, smoke) are just enlarged smoothly, since there is no detail to recover.
Invisible pixels are first filled with neighbouring colours so dark fringes don't bleed into edges.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ESRGAN = os.environ.get("REALESRGAN", "realesrgan-ncnn-vulkan")
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


def repeats(px, axis):
    """Whether the texture's opposite edges along axis continue each other like neighbouring rows do."""
    a = np.moveaxis(px[..., :3].astype(np.float32), axis, 0)
    if a.shape[0] < 4:
        return True
    steps = np.abs(np.diff(a, axis=0)).mean((1, 2))
    return np.abs(a[0] - a[-1]).mean() <= 2 * np.percentile(steps, 90) + 4


def pad(px, n, modes):
    for axis, mode in enumerate(modes):
        px = np.pad(px, [(n, n) if a == axis else (0, 0) for a in range(px.ndim)], mode=mode)
    return px


def blur(e, modes):
    k = np.array([1, 4, 6, 4, 1], np.float32) / 16
    p = pad(e, 2, modes)
    e = sum(k[i] * p[i:i + e.shape[0]] for i in range(5))
    return sum(k[i] * e[:, i:i + p.shape[1] - 4] for i in range(5))


def up4(e, modes):
    """Bilinear 4x enlargement."""
    e = pad(e, 1, modes)
    for axis in (0, 1):
        x = (np.arange((e.shape[axis] - 2) * 4) + 0.5) / 4 + 0.5
        i = np.floor(x).astype(int)
        f = (x - i).reshape([-1 if a == axis else 1 for a in range(3)]).astype(np.float32)
        e = np.take(e, i, axis) * (1 - f) + np.take(e, i + 1, axis) * f
    return e


def fit(rgb, target, modes):
    """Nudges rgb until its 4x4 averages match target's colours, blurred so only broad colour changes."""
    hd, target = rgb.astype(np.float32), target.astype(np.float32)
    h, w = target.shape[:2]
    for _ in range(2):
        hd += up4(blur(target - hd.reshape(h, 4, w, 4, 3).mean((1, 3)), modes), modes)
    return np.clip(hd + 0.5, 0, 255).astype(np.uint8)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    wanted = sys.argv[3] if len(sys.argv) > 3 else ""
    # ramps.png is a shading lookup strip, not a picture: upscaling smears the cartoon shading.
    files = sorted(p for p in src.rglob("*.png") if wanted in str(p.relative_to(src)) and p.stem != "ramps")
    with tempfile.TemporaryDirectory() as tmp:
        stage, done = Path(tmp, "in"), Path(tmp, "out")
        stage.mkdir()
        done.mkdir()
        alpha = {}  # index -> mask is on/off only
        modes = {}  # index -> padding per axis
        soft = set()  # mostly see-through gradients (glows, smoke): the upscaler hardens them
        for i, p in enumerate(files):
            px = np.asarray(Image.open(p).convert("RGBA"))
            modes[i] = ["wrap" if repeats(px, axis) else "symmetric" for axis in (0, 1)]
            padded = pad(px, min(PAD, *px.shape[:2]), modes[i])
            Image.fromarray(bleed(padded)).save(stage / f"{i}.png")
            if (px[..., 3] < 255).any():
                alpha[i] = bool(np.isin(px[..., 3], (0, 255)).all())
                a = px[..., 3][px[..., 3] > 8]
                if a.size and ((a < 247).mean() > 0.35):
                    soft.add(i)
                Image.fromarray(padded[..., 3]).convert("RGB").save(stage / f"{i}a.png")
        subprocess.run([str(ESRGAN), "-i", str(stage), "-o", str(done), "-n", MODEL, "-s", "4", "-f", "png"],
                       check=True, stdout=subprocess.DEVNULL)
        for i, p in enumerate(files):
            rgb = np.asarray(Image.open(done / f"{i}.png").convert("RGB"))
            px = np.asarray(Image.open(p).convert("RGBA"))
            h, w = px.shape[:2]
            n = min(PAD, h, w) * 4
            rgb = fit(rgb[n:n + h * 4, n:n + w * 4], bleed(px), modes[i])
            if i in soft:
                img = Image.fromarray(np.dstack([bleed(px), px[..., 3]]), "RGBA").resize((w * 4, h * 4), Image.BICUBIC)
            elif i in alpha:
                a = np.asarray(Image.open(done / f"{i}a.png").convert("L"))[n:n + h * 4, n:n + w * 4]
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
