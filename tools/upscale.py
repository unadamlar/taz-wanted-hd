#!/usr/bin/env python3
"""Upscale extracted textures 4x with Real-ESRGAN, keeping repeating textures seamless.

usage: upscale.py <extracted_dir> <out_dir> [name_filter]

Each texture is padded with its own opposite edges (as it repeats in game), upscaled, then the
padding is cropped, so tiled surfaces don't get seams. Along an axis whose opposite edges don't
continue each other (sky panels, grass-to-path joiners) it is mirrored instead: wrapping put the
other edge's colour and a drawn outline into the edge rows, which polygons that stretch an edge
show as a wrong colour or a line. Afterwards each upscale's broad colours are pulled back to the
original's (the upscaler drifts colour and contrast); fine detail is kept. Finally each pixel is
kept within the colours of the original's nearby pixels, which removes the dark outlines and light
rims the upscaler draws along colour borders. The transparency mask goes through the
upscaler as its own image; on/off masks (cut-outs) are cut back to hard edges, antialiased ones (letters)
keep their soft edge, within the original's nearby alpha so a letter never spreads into the next one on a font sheet.
Mostly see-through sprites (glows, smoke) and opaque gradients without hard edges (shadows) are just
enlarged smoothly, since there is no detail to recover,
and so is any texture whose upscale strays far from the original (fine fences, thin stripes).
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
# Opaque textures enlarged by flat_up, with how far it rounds (in original pixels). Single-pixel dots
# need under ~0.47 or they vanish.
FLAT = {"citybloom01": 0.5, "citybloom02": 0.5, "cowboystubble01": 0.3,
        "zoohubgrass5": 0.5, "zoohubgrass6": 0.5, "zoohubgrass7": 0.5}
# FLAT textures whose edges are antialiased: treated as separate colours, those edges come out as blocky rims.
BLENDED = {"zoohubgrass5", "zoohubgrass6", "zoohubgrass7"}


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


def no_edges(px):
    """Smooth gradients and blobs (Taz's shadow, light streaks, soft clouds): no step between neighbouring
    pixels covers a quarter of the brightness range. The upscaler turns their fades into rings and bands."""
    g = px[..., :3].astype(np.float32).mean(2)
    rng = np.ptp(g)
    if rng < 64 or min(g.shape) < 8:
        return False
    return max(np.abs(np.diff(g, axis=0)).max(), np.abs(np.diff(g, axis=1)).max()) < rng / 4


def line_art(px):
    """Letters, notes and outlines: one colour shaped by an antialiased alpha whose partly see-through
    pixels sit on a steep step between clear and solid (median step to a neighbour ~180 in the font
    sheets; glows and smoke stay under 70, blurry snowflakes and stars ~105). The upscaler sharpens them."""
    al = px[..., 3]
    h, w = al.shape
    f = np.pad(al.astype(np.int16), 1, mode="edge")
    step = np.max([np.abs(f[1:-1, 1:-1] - f[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]) for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))], 0)
    part = (al > 8) & (al < 247)
    return part.any() and np.median(step[part]) >= 112 and px[..., :3][al > 8].std(0).max() < 8


def blocky(px):
    """Colour swatches and stripes (Sam's and Tweety's colour sheets, the cowboy hat's band): solid
    rectangles in strongly different colours, which models pick by UV. The upscaler softened and wobbled
    their borders, so they are just enlarged pixel for pixel. Counted as rectangles: areas that fill their
    bounding box and are 2 pixels thick or span the texture; staircase outlines break into thin pieces."""
    p = px.astype(np.int16)
    steps = np.concatenate([np.abs(p[1:] - p[:-1]).max(2).ravel(), np.abs(p[:, 1:] - p[:, :-1]).max(2).ravel()])
    steps = steps[steps > 0]
    if not steps.size or steps.min() < 64:  # banded gradients look better smoothed
        return False
    cols, lab = np.unique(px.reshape(-1, 4), axis=0, return_inverse=True)
    if len(cols) > 16:
        return False
    h, w = px.shape[:2]
    lab = lab.reshape(h, w)
    a, b, c, d = lab[:-1, :-1], lab[:-1, 1:], lab[1:, :-1], lab[1:, 1:]
    corners = (~(((a == b) & (c == d)) | ((a == c) & (b == d)))).sum()
    seen = np.zeros((h, w), bool)
    rects = 0
    for y, x in np.ndindex(h, w):
        if seen[y, x]:
            continue
        seen[y, x] = True
        todo, ys, xs = [(y, x)], [], []
        while todo:
            i, j = todo.pop()
            ys.append(i)
            xs.append(j)
            for k, l in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= k < h and 0 <= l < w and not seen[k, l] and lab[k, l] == lab[y, x]:
                    seen[k, l] = True
                    todo.append((k, l))
        bh, bw = max(ys) - min(ys) + 1, max(xs) - min(xs) + 1
        rects += bh * bw == len(ys) and (min(bh, bw) >= 2 or bh == h or bw == w)
    return corners <= 4 * rects


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


def coverage(px, tol):
    """Each main colour's share of each pixel. A colour within tol of the line between two more common
    ones is an antialiased edge, split between them."""
    cols, lab, n = np.unique(px.reshape(-1, 3), axis=0, return_inverse=True, return_counts=True)
    lab = lab.reshape(px.shape[:2])
    main, parts = [], {}
    for c in sorted(range(len(cols)), key=lambda c: (-n[c], c)) if tol else range(len(cols)):
        x, best = cols[c].astype(float), None
        for i, a in enumerate(main):
            for j in range(i + 1, len(main)):
                p, q = cols[a].astype(float), cols[main[j]].astype(float)
                t = np.clip((x - p) @ (q - p) / ((q - p) @ (q - p)), 0, 1)
                d = np.linalg.norm(p + t * (q - p) - x)
                if d < tol and (best is None or d < best[0]):
                    best = d, i, j, t
        if best is None:
            best = 0, len(main), len(main), 0.0
            main.append(c)
        parts[c] = best[1:]
    cover = np.zeros((len(main), *lab.shape), np.float32)
    for c, (i, j, t) in parts.items():
        cover[i][lab == c] += 1 - t
        cover[j][lab == c] += t
    return cols[main], cover


def flat_up(px, modes, sg, tol=0):
    """4x for flat-colour pixel art too small for the upscaler (the city's grass flowers, each petal a few
    pixels, came out as blurry squares; the cowboy costume's one-pixel stubble as squiggles): each colour's
    area is rounded off on its own (blur of sg pixels) and every pixel takes the colour that covers it most,
    worked out at 8x and averaged down so edges are antialiased."""
    h, w = px.shape[:2]
    cols, cover = coverage(px, tol)
    s, sg = 8, sg * 8
    r = int(3 * sg) + 1
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sg * sg)).astype(np.float32)
    k /= k.sum()
    best = np.full((h * s, w * s), -1, np.float32)
    out = np.zeros((h * s, w * s), np.intp)
    for i in range(len(cols)):
        m = pad(np.repeat(np.repeat(cover[i], s, 0), s, 1)[..., None], r, modes)[..., 0]
        m = sum(k[j] * m[j:j + h * s] for j in range(2 * r + 1))
        m = sum(k[j] * m[:, j:j + w * s] for j in range(2 * r + 1))
        more = m > best
        best[more], out[more] = m[more], i
    return cols[out].reshape(h * 4, 2, w * 4, 2, 3).mean((1, 3)).round().astype(np.uint8)


def fit(rgb, target, modes):
    """Nudges rgb until its 4x4 averages match target's colours, blurred so only broad colour changes."""
    hd, target = rgb.astype(np.float32), target.astype(np.float32)
    h, w = target.shape[:2]
    for _ in range(2):
        hd += up4(blur(target - hd.reshape(h, 4, w, 4, 3).mean((1, 3)), modes), modes)
    return np.clip(hd + 0.5, 0, 255).astype(np.uint8)


def clamp(rgb, target):
    """Limits each pixel to the range of the original's 3x3 pixels around it. The window never wraps:
    many polygons stretch an edge row, so it must keep its own colour even on repeating textures."""
    p = pad(target, 1, ["symmetric", "symmetric"])
    h, w = target.shape[:2]
    win = np.stack([p[y:y + h, x:x + w] for y in range(3) for x in range(3)])
    lo, hi = (np.repeat(np.repeat(v, 4, 0), 4, 1) for v in (win.min(0), win.max(0)))
    return np.clip(rgb, lo, hi)


def lost(rgb, a, px, target):
    """Whether the upscale lost the original's look: fine patterns it smears or redraws (chain-link
    fences, thin stripes). Those are enlarged smoothly instead."""
    h, w = target.shape[:2]
    vis = px[..., 3] >= 128
    drift = np.abs(rgb.reshape(h, 4, w, 4, 3).mean((1, 3)) - target).mean(2)
    if vis.any() and drift[vis].mean() > 15:
        return True
    return a is not None and np.abs(a.reshape(h, 4, w, 4).mean((1, 3)) - px[..., 3]).mean() > 30


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
                if a.size and ((a < 247).mean() > 0.35) and not line_art(px):
                    soft.add(i)
                Image.fromarray(padded[..., 3]).convert("RGB").save(stage / f"{i}a.png")
            elif no_edges(px):
                soft.add(i)
        subprocess.run([str(ESRGAN), "-i", str(stage), "-o", str(done), "-n", MODEL, "-s", "4", "-f", "png"],
                       check=True, stdout=subprocess.DEVNULL)
        for i, p in enumerate(files):
            rgb = np.asarray(Image.open(done / f"{i}.png").convert("RGB"))
            px = np.asarray(Image.open(p).convert("RGBA"))
            h, w = px.shape[:2]
            n = min(PAD, h, w) * 4
            target = bleed(px)
            rgb = clamp(fit(rgb[n:n + h * 4, n:n + w * 4], target, modes[i]), target)
            a = None
            if i in alpha:
                a = np.asarray(Image.open(done / f"{i}a.png").convert("L"))[n:n + h * 4, n:n + w * 4]
                a = np.where(a >= 128, 255, 0).astype(np.uint8) if alpha[i] else clamp(a[..., None], px[..., 3:])[..., 0]
            if p.stem in FLAT:
                tol = 32 if p.stem in BLENDED else 0
                img = Image.fromarray(flat_up(px[..., :3], modes[i], FLAT[p.stem], tol), "RGB")
            elif blocky(px):
                img = Image.fromarray(px if i in alpha else px[..., :3]).resize((w * 4, h * 4), Image.NEAREST)
            elif i in soft or lost(rgb, a, px, target):
                img = Image.fromarray(np.dstack([target, px[..., 3]]), "RGBA").resize((w * 4, h * 4), Image.BICUBIC)
                if alpha.get(i) and i not in soft:
                    img.putalpha(img.getchannel("A").point(lambda v: 255 if v >= 128 else 0))
                if i not in alpha:
                    img = img.convert("RGB")
            elif a is not None:
                img = Image.fromarray(np.dstack([rgb, a]), "RGBA")
            else:
                img = Image.fromarray(rgb, "RGB")
            dest = out / p.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            img.save(dest)
    # Rows 5-6 of Taz's strip are the zoo boss level's shading: its near-black brown shadow made half the
    # elephant look burnt, so it is lifted 35% toward the lit tone. The strip stays 1x.
    ramps = src / "taz/textures/ramps.png"
    if ramps.exists() and wanted in "taz/textures/ramps.png":
        px = np.asarray(Image.open(ramps).convert("RGBA")).copy()
        rows = px[5:7]
        rows[(rows[..., :3] == (140, 57, 0)).all(2), :3] = (180, 121, 69)
        (out / "taz/textures").mkdir(parents=True, exist_ok=True)
        Image.fromarray(px, "RGBA").save(out / "taz/textures/ramps.png")
    print(f"{len(files)} textures upscaled into {out}")


if __name__ == "__main__":
    main()
