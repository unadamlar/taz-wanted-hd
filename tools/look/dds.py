"""DDS writer for the look data: mip chains, DXT1/DXT5 (vectorised range fit), cube maps. numpy only."""
import struct
import numpy as np


def to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def to_linear(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _down(a):
    return (a + np.roll(a, -1, 0) + np.roll(a, -1, 1) + np.roll(np.roll(a, -1, 0), -1, 1))[::2, ::2] / 4


def bleed(rgb, alpha, cut=0.5):
    """Spread opaque colours into the see-through texels so mips and DXT blocks don't pull in fringes."""
    pyr = [(rgb * (alpha > cut)[..., None], (alpha > cut).astype(np.float32))]
    while min(pyr[-1][1].shape) > 1:
        c, w = pyr[-1]
        pyr.append((_down(c), _down(w)))
    out = pyr[-1][0] / np.maximum(pyr[-1][1][..., None], 1e-6)
    for c, w in pyr[-2::-1]:
        up = out.repeat(2, 0).repeat(2, 1)[:c.shape[0], :c.shape[1]]
        k = w[..., None] > 0
        out = np.where(k, c / np.maximum(w[..., None], 1e-6), up)
    return out


def mips(rgba, cut=None):
    """Full chain from an sRGB float image, box filtered in linear light. With cut, each level's alpha is
    rescaled to keep the top level's coverage at that threshold, so cards don't thin out with distance."""
    h, w = rgba.shape[:2]
    if w & (w - 1) or h & (h - 1):
        raise ValueError(f"not a power of two: {w}x{h}")
    lin = np.dstack([to_linear(rgba[..., :3]), rgba[..., 3:]]) if rgba.shape[2] > 3 else to_linear(rgba)
    cover = (rgba[..., 3] > cut).mean() if cut is not None else None
    out = [rgba]
    while lin.shape[0] > 1 or lin.shape[1] > 1:
        s0, s1 = 2 if lin.shape[0] > 1 else 1, 2 if lin.shape[1] > 1 else 1
        a = lin
        if s0 == 2: a = (a + np.roll(a, -1, 0))[::2] / 2
        if s1 == 2: a = (a + np.roll(a, -1, 1))[:, ::2] / 2
        lin = a
        m = np.dstack([to_srgb(a[..., :3]), a[..., 3:]]) if a.shape[2] > 3 else to_srgb(a)
        if cover is not None and cover > 0:
            t = np.quantile(m[..., 3], np.clip(1 - cover, 0, 1))
            m[..., 3] = np.clip(m[..., 3] * cut / max(t, 1e-3), 0, 1)
        out.append(m)
    return out


def mips_data(xyza):
    """Full chain for non-colour data (normal maps, already unit-mapped to 0..1)."""
    out = [xyza]
    while out[-1].shape[0] > 1 or out[-1].shape[1] > 1:
        a = out[-1]
        if a.shape[0] > 1: a = (a + np.roll(a, -1, 0))[::2] / 2
        if a.shape[1] > 1: a = (a + np.roll(a, -1, 1))[:, ::2] / 2
        out.append(a)
    return out


def _blocks(a):
    """HxWxC float image -> Nx16xC blocks; odd small mips are padded by repeating edge texels."""
    h, w = a.shape[:2]
    ph, pw = -h % 4, -w % 4
    if ph or pw:
        a = np.pad(a, ((0, ph), (0, pw), (0, 0)), mode="edge")
        h, w = a.shape[:2]
    return a.reshape(h // 4, 4, w // 4, 4, -1).transpose(0, 2, 1, 3, 4).reshape(-1, 16, a.shape[2])


def _bc1_colour(b):
    """Nx16x3 in 0..1 -> u32 endpoints and indices (four-colour mode)."""
    m = b.mean(1, keepdims=True)
    d = b - m
    cov = np.einsum("nij,nik->njk", d, d)
    v = np.ones((len(b), 3)) / 3 ** 0.5
    for _ in range(6):
        v = (cov @ v[..., None])[..., 0]
        v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    t = (d * v[:, None]).sum(2)
    c0 = np.clip(m[:, 0] + v * t.max(1, keepdims=True), 0, 1)
    c1 = np.clip(m[:, 0] + v * t.min(1, keepdims=True), 0, 1)
    q = np.array([31, 63, 31])
    e0, e1 = np.rint(c0 * q).astype(np.int32), np.rint(c1 * q).astype(np.int32)
    u0 = e0[:, 0] << 11 | e0[:, 1] << 5 | e0[:, 2]
    u1 = e1[:, 0] << 11 | e1[:, 1] << 5 | e1[:, 2]
    swap = u0 < u1
    u0[swap], u1[swap] = u1[swap], u0[swap].copy()
    e0[swap], e1[swap] = e1[swap], e0[swap].copy()
    f0, f1 = (e0 / q)[:, None], (e1 / q)[:, None]
    pal = np.stack([f0, f1, (2 * f0 + f1) / 3, (f0 + 2 * f1) / 3], 1)
    idx = ((b[:, None] - pal) ** 2).sum(3).argmin(1)
    same = u0 == u1
    idx[same] = 0
    bits = (idx.astype(np.uint64) << (2 * np.arange(16, dtype=np.uint64))).sum(1)
    return u0.astype(np.uint32) | u1.astype(np.uint32) << 16, bits.astype(np.uint32)


def _bc4(a):
    """Nx16 in 0..1 -> u64 alpha block (eight-value mode)."""
    lo, hi = np.rint(a.min(1) * 255).astype(np.int32), np.rint(a.max(1) * 255).astype(np.int32)
    flat = hi == lo
    hi = np.where(flat & (hi < 255), hi + 1, hi)
    lo = np.where(flat & (hi == 255) & (lo == 255), 254, lo)
    w = np.arange(8)[None] / 7
    pal = (hi[:, None] * (1 - w) + lo[:, None] * w) / 255
    near = np.abs(a[:, None] - pal[..., None]).argmin(1)
    code = np.array([0, 2, 3, 4, 5, 6, 7, 1])[near].astype(np.uint64)
    bits = (code << (3 * np.arange(16, dtype=np.uint64))).sum(1)
    return hi.astype(np.uint64) | lo.astype(np.uint64) << 8 | bits << 16


def _encode(level, fourcc, chunk=1 << 16):
    b = _blocks(level)
    out = []
    for i in range(0, len(b), chunk):
        c = b[i:i + chunk]
        col, bits = _bc1_colour(c[..., :3])
        if fourcc == b"DXT1":
            out.append(np.stack([col, bits], 1).astype("<u4").tobytes())
        else:
            al = _bc4(c[..., 3]).astype("<u8")
            rec = np.zeros(len(c), dtype=[("a", "<u8"), ("c", "<u4"), ("b", "<u4")])
            rec["a"], rec["c"], rec["b"] = al, col, bits
            out.append(rec.tobytes())
    return b"".join(out)


def _header(w, h, nmips, fourcc=None, cube=False):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | (0x80000 if fourcc else 0x8)
    bpp_block = {b"DXT1": 8, b"DXT5": 16}.get(fourcc)
    pitch = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bpp_block if fourcc else w * 4
    pf = (struct.pack("<II4sIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0) if fourcc else
          struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0xff0000, 0xff00, 0xff, 0xff000000))
    caps = 0x1000 | 0x400000 | 0x8 | (0x8 if cube else 0)
    caps2 = 0xfe00 if cube else 0
    return b"DDS " + struct.pack("<7I", 124, flags, h, w, pitch, 0, nmips) + b"\0" * 44 + pf + \
        struct.pack("<5I", caps, caps2, 0, 0, 0)


def write_dxt(path, chain, fourcc):
    """chain: mip levels, HxWx4 floats in 0..1 (rgb stored as given). Returns the byte size."""
    data = _header(chain[0].shape[1], chain[0].shape[0], len(chain), fourcc) + b"".join(_encode(m, fourcc) for m in chain)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def write_cube(path, faces, rng=None):
    """faces: six HxHx3 sRGB float images in D3D order (+x -x +y -y +z -z); A8R8G8B8, full mips.
    Dithered by one quantisation step to hide banding in the sky gradient."""
    rng = rng or np.random.default_rng(0)
    out = [_header(faces[0].shape[1], faces[0].shape[0], len(mips(faces[0])), cube=True)]
    for f in faces:
        for m in mips(f):
            v = np.clip(m + (rng.random(m.shape) - 0.5) / 255, 0, 1)
            px = np.rint(v * 255).astype(np.uint8)
            out.append(np.dstack([px[..., 2], px[..., 1], px[..., 0], np.full(px.shape[:2], 255, np.uint8)]).tobytes())
    data = b"".join(out)
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)
