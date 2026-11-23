"""Tiling surfaces made here instead of taken from an asset set: (sRGB colour, tangent normal), both 0..1."""
import numpy as np


def _noise(n, power, seed):
    f = np.fft.fftfreq(n)
    r = np.hypot(f[:, None], f[None, :])
    r[0, 0] = 1
    a = np.fft.ifft2(np.fft.fft2(np.random.default_rng(seed).normal(size=(n, n))) / r ** power).real
    return (a - a.min()) / (a.max() - a.min())


def _normal(h, strength):
    gx, gy = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) / 2, (np.roll(h, -1, 0) - np.roll(h, 1, 0)) / 2
    v = np.dstack([-gx * strength, -gy * strength, np.ones_like(h)])
    return ((v / np.linalg.norm(v, axis=2, keepdims=True) + 1) / 2).astype(np.float32)


def snow(px):
    """Soft drifts with fine grain; hollows go a little blue."""
    drift, grain = _noise(px, 2.3, 1), _noise(px, 0.8, 2)
    t = np.clip((drift - 0.3) / 0.4, 0, 1)[..., None]
    colour = np.array((0.80, 0.88, 0.97)) * (1 - t) + np.array((1.0, 1.0, 1.0)) * t
    return (colour * (0.97 + 0.03 * grain[..., None])).astype(np.float32), _normal(drift + 0.05 * grain, px / 14)


def tile(kind, px):
    return {"snow": snow}[kind](px)
