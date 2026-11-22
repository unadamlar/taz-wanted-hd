"""Planet X's painted space panels rebuilt at high resolution, procedurally, on the game's own layout: its swirls, stars and
planets stay where they are painted, the planets become lit spheres with soft atmospheres. numpy only.
Colours are linear until the end; panels are viewed from the middle of a cube, so a planet is a sphere seen along its ray."""
import numpy as np

import dds


def blur(a, sigma):
    f = [np.fft.fftfreq(n) for n in a.shape[:2]]
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (f[0][:, None] ** 2 + f[1][None, :] ** 2)).astype(np.float32)
    return np.fft.ifft2(np.fft.fft2(a) * g).real.astype(np.float32)


def cloud(n, power, seed):
    """Smooth 1/f noise in 0..1."""
    fx, fy = np.fft.fftfreq(n), np.fft.fftfreq(n)
    r = np.sqrt(fx[:, None] ** 2 + fy[None, :] ** 2)
    r[0, 0] = 1
    a = np.fft.ifft2(np.fft.fft2(np.random.default_rng(seed).normal(size=(n, n))) / r ** power).real
    return ((a - a.min()) / (a.max() - a.min())).astype(np.float32)


def fbm(p, freq, octaves, seed):
    """Value noise over a 3D point array, about 0..1."""
    perm = np.random.default_rng(seed).permutation(1024)
    table = np.random.default_rng(seed + 1).random(1024).astype(np.float32)
    total, amp, norm = 0, 1.0, 0.0
    for o in range(octaves):
        q = p * freq * 2 ** o + o * 17.3
        i = np.floor(q).astype(np.int64)
        f = q - i
        f = f * f * (3 - 2 * f)
        def at(dx, dy, dz):
            return table[perm[(perm[(perm[(i[..., 0] + dx) & 1023] + i[..., 1] + dy) & 1023] + i[..., 2] + dz) & 1023]]
        x0 = at(0, 0, 0) * (1 - f[..., 0]) + at(1, 0, 0) * f[..., 0]
        x1 = at(0, 1, 0) * (1 - f[..., 0]) + at(1, 1, 0) * f[..., 0]
        x2 = at(0, 0, 1) * (1 - f[..., 0]) + at(1, 0, 1) * f[..., 0]
        x3 = at(0, 1, 1) * (1 - f[..., 0]) + at(1, 1, 1) * f[..., 0]
        y0 = x0 * (1 - f[..., 1]) + x1 * f[..., 1]
        y1 = x2 * (1 - f[..., 1]) + x3 * f[..., 1]
        total = total + amp * (y0 * (1 - f[..., 2]) + y1 * f[..., 2])
        norm += amp
        amp *= 0.5
    return total / norm


def bilinear(a, x, y):
    h, w = a.shape[:2]
    x, y = np.clip(x, 0, w - 1.001), np.clip(y, 0, h - 1.001)
    i, j = x.astype(np.int32), y.astype(np.int32)
    f, g = (x - i)[..., None], (y - j)[..., None]
    return a[j, i] * (1 - f) * (1 - g) + a[j, i + 1] * f * (1 - g) + a[j + 1, i] * (1 - f) * g + a[j + 1, i + 1] * f * g


def stamp(img, x, y, radius, colour, sharp=1):
    """Adds a soft round light."""
    h, w = img.shape[:2]
    reach = int(radius * 3.2) + 2
    x0, x1, y0, y1 = max(int(x) - reach, 0), min(int(x) + reach + 1, w), max(int(y) - reach, 0), min(int(y) + reach + 1, h)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    img[y0:y1, x0:x1] += np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * radius * radius)) ** sharp)[..., None].astype(np.float32) * colour


def painted_stars(rgb, keep_out):
    """Connected bright dots of the painting: (x, y, radius) in its pixels."""
    todo = (rgb.max(2) > 0.55) & ~keep_out
    h, w = todo.shape
    found = []
    for y0, x0 in zip(*np.nonzero(todo)):
        if not todo[y0, x0]:
            continue
        stack, xs, ys = [(y0, x0)], [], []
        todo[y0, x0] = False
        while stack:
            y, x = stack.pop()
            xs.append(x), ys.append(y)
            for b, a in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= b < h and 0 <= a < w and todo[b, a]:
                    todo[b, a] = False
                    stack.append((b, a))
        if len(xs) >= 6:
            found.append((float(np.mean(xs)), float(np.mean(ys)), float(np.sqrt(len(xs) / np.pi))))
    return found


def backdrop(rgb, planets, n, seed):
    """The swirls: the painting's three flat tones without its planets and stars, redrawn with depth."""
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    hide = rgb.max(2) > 0.3
    for p in planets:
        hide |= (xx - p["c"][0]) ** 2 + (yy - p["c"][1]) ** 2 < (p["r"] * p.get("paint", 1.45)) ** 2
    for _ in range(5):  # a star's dim halo
        hide = hide | np.roll(hide, 1, 0) | np.roll(hide, -1, 0) | np.roll(hide, 1, 1) | np.roll(hide, -1, 1)
    tone = np.where(rgb[..., 2] < 0.06, 0, np.where(rgb[..., 2] < 0.19, 1, 2)).astype(np.int8)
    tone[hide] = -1
    while (tone < 0).any():  # each hidden pixel takes its nearest visible tone
        for ax, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
            m = np.roll(tone, step, ax)
            k = (tone < 0) & (m >= 0)
            tone[k] = m[k]
    scale = n // w
    masks = [blur((tone == k).repeat(scale, 0).repeat(scale, 1).astype(np.float32), scale * 0.9) for k in range(3)]
    big, fine, hue = cloud(n, 1.5, seed), cloud(n, 1.05, seed + 1), cloud(n, 1.7, seed + 2)
    grain = 0.72 * big + 0.28 * fine
    out = np.zeros((n, n, 3), np.float32)
    deep = np.stack([0.0003 + 0.002 * grain ** 2, 0.0003 + 0.003 * grain ** 2, 0.001 + 0.009 * grain ** 2], 2)
    base = np.stack([0.0004 + 0.003 * hue * grain, 0.0006 + 0.004 * grain, 0.007 + 0.017 * grain], 2)
    swirl_a, swirl_b = np.array([0.004, 0.02, 0.095], np.float32), np.array([0.02, 0.016, 0.115], np.float32)
    swirl = (swirl_a * (1 - hue[..., None]) + swirl_b * hue[..., None]) * (0.55 + 1.0 * grain[..., None])
    for m, c in zip(masks, (deep, base, swirl)):
        out += m[..., None] * c
    glow = np.clip(blur(masks[2], scale * 16) - masks[2], 0, 1)[..., None]  # the swirls' edges bleed a little light
    out += glow * (swirl_a * (1 - hue[..., None]) + swirl_b * hue[..., None]) * 0.3
    fade = np.minimum.reduce([np.arange(n), np.arange(n)[::-1]]).astype(np.float32) / (n * 0.04)
    edge = np.clip(np.minimum(fade[:, None], fade[None, :]), 0, 1)[..., None]  # panel borders stay the painting's plain tones
    flat = sum(m[..., None] * np.array(c, np.float32) for m, c in zip(masks, ((0.0004, 0.0005, 0.003), (0.001, 0.002, 0.014), (0.006, 0.016, 0.08))))
    return out * edge + flat * (1 - edge)


def star_field(img, painted, n, scale, seed):
    rng = np.random.default_rng(seed)
    for _ in range(5200):  # dust of faint stars, a few warm or blue
        t = rng.random()
        tint = np.array((1.0, 0.82, 0.62) if t < 0.14 else (0.66, 0.8, 1.0) if t < 0.5 else (0.95, 0.95, 1.0), np.float32)
        stamp(img, rng.uniform(6, n - 6), rng.uniform(6, n - 6), rng.uniform(0.55, 1.0), tint * float(0.025 + 0.32 * rng.random() ** 5))
    for _ in range(240):
        tint = np.array(((1.0, 0.86, 0.7), (0.7, 0.84, 1.0), (1.0, 1.0, 1.0))[rng.integers(3)], np.float32)
        x, y, r = rng.uniform(10, n - 10), rng.uniform(10, n - 10), rng.uniform(1.0, 1.9)
        stamp(img, x, y, r, tint * float(rng.uniform(0.25, 0.8)))
        stamp(img, x, y, r * 3.6, tint * 0.018)
    for x, y, r in painted:  # the game's own stars, where it put them
        r *= scale
        x, y = (x + 0.5) * scale, (y + 0.5) * scale
        stamp(img, x, y, r * 1.5, np.array((0.004, 0.013, 0.06), np.float32))
        stamp(img, x, y, r * 0.82, np.array((0.05, 0.11, 0.4), np.float32), 2)
        stamp(img, x, y, r * 0.46, np.array((1.3, 1.4, 1.6), np.float32), 3)
        for k in range(-int(r * 5), int(r * 5) + 1):  # a thin sparkle
            a = 0.16 * np.exp(-abs(k) / (r * 0.9))
            for px, py in ((int(x) + k, int(y)), (int(x), int(y) + k)):
                if 0 <= px < n and 0 <= py < n:
                    img[py, px] += np.array((0.6, 0.72, 1.0), np.float32) * float(a)


def sphere(img, paint, p, n, seed):
    """One planet: the painted surface wrapped on a lit ball, with its atmosphere."""
    h = paint.shape[0]
    cx, cy, r = p["c"][0] + 0.5, p["c"][1] + 0.5, float(p["r"])
    C = np.array((2 * cx / h - 1, 2 * cy / h - 1, 1.0))
    D = C / np.linalg.norm(C)
    sin_a = np.sin(np.arctan(2 * r / h * D[2]))
    ex = np.cross((0, 1, 0), D); ex /= np.linalg.norm(ex)
    ey = np.cross(D, ex)
    reach = p.get("reach", 1.0)
    half = int((r * reach * 1.45 + 6) * n / h)
    mx, my = int(cx * n / h), int(cy * n / h)
    x0, x1, y0, y1 = max(mx - half, 0), min(mx + half, n), max(my - half, 0), min(my + half, n)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    X, Y = 2 * (xx + 0.5) / n - 1, 2 * (yy + 0.5) / n - 1
    L = np.sqrt(X * X + Y * Y + 1)
    d = np.stack([X / L, Y / L, 1 / L], 2)
    s, t = (d @ ex) / sin_a, (d @ ey) / sin_a
    rho = np.sqrt(s * s + t * t).astype(np.float32)
    z = np.sqrt(np.clip(1 - rho * rho, 0, 1)).astype(np.float32)
    px = r * n / h  # its radius in output pixels
    cover = np.clip((1 - rho) * px, 0, 1)[..., None].astype(np.float32)
    alb = dds.to_linear(bilinear(paint, cx - 0.5 + r * s * 0.985, cy - 0.5 + r * t * 0.985)).astype(np.float32)
    ball = np.stack([s, t, z], 2).astype(np.float32)
    detail = fbm(ball, p.get("freq", 3.2), 6, seed)
    alb = alb * (0.86 + 0.28 * detail[..., None])
    lum = alb.mean(2) ** 0.5
    hgt = 0.5 * blur(lum, px * 0.02) + p.get("bump", 0.1) * detail
    gy, gx = np.gradient(hgt)
    k = px * 0.3
    nor = np.stack([s - gx * k, t - gy * k, z + 0.001], 2).astype(np.float32)
    nor /= np.maximum(np.linalg.norm(nor, axis=2, keepdims=True), 1e-5)
    sun = np.array((-0.58, -0.56, 0.59), np.float32)
    lit = np.clip(nor @ sun, 0, 1)[..., None]
    soft = np.clip((ball @ sun + 0.22) / 0.62, 0, 1)[..., None]  # the terminator, softer than the bumps
    col = alb * (0.34 + 1.02 * lit * soft + 0.12 * soft)
    col += np.clip(nor @ ((sun + (0, 0, 1)) / np.linalg.norm(sun + (0, 0, 1))), 0, 1)[..., None] ** 40 * p.get("gloss", 0.05) * soft
    atm = p.get("atm")
    if atm is not None:
        atm = np.array(atm, np.float32)
        col += atm * ((1 - z[..., None]) ** 2.6) * (0.28 + 0.9 * soft)
        out = np.clip(rho - 1, 0, None)[..., None]
        gate = np.clip((reach - rho) / max(reach - 1, 0.01), 0, 1)[..., None] ** 1.5
        img[y0:y1, x0:x1] += atm * (0.5 * np.exp(-out / 0.016) + 0.2 * np.exp(-out / 0.07) + 0.1 * np.exp(-out / 0.22)) * gate * (rho >= 1)[..., None]
    img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - cover) + col * cover


def panel(rgb, planets, n=4096, seed=1):
    """rgb: the HD painting as sRGB floats, top row first. Returns the new panel, sRGB floats, top row first."""
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    keep = np.zeros((h, w), bool)
    for p in planets:
        keep |= (xx - p["c"][0]) ** 2 + (yy - p["c"][1]) ** 2 < (p["r"] * p.get("paint", 1.45)) ** 2
    img = backdrop(rgb, planets, n, seed)
    star_field(img, painted_stars(rgb, keep), n, n / w, seed + 5)
    for i, p in enumerate(planets):
        sphere(img, rgb, p, n, seed + 10 + i)
    noise = np.random.default_rng(seed + 9).random((n, n, 1), np.float32) - 0.5
    return np.clip(dds.to_srgb(np.clip(img, 0, 1)) + noise * 1.5 / 255, 0, 1).astype(np.float32)
