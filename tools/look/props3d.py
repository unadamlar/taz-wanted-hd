"""Real 3D stand-ins for the game's flat painted cards, built where a card stands. Game space: y up, game units.
Each builder returns triangle corners: positions (n, 3), normals (n, 3), linear colours (n, 3)."""
import numpy as np


def footprint(W):
    """Base point, height and radius of a card's painted silhouette (points in game space)."""
    lo, hi = W[:, 1].min(), W[:, 1].max()
    low = W[W[:, 1] < lo + 0.2 * max(hi - lo, 1e-6)]
    base = np.array([low[:, 0].mean(), lo, low[:, 2].mean()])
    r = np.hypot(W[:, 0] - base[0], W[:, 2] - base[2]).max()
    return base, hi - lo, r


def _tube(path, radius, sides=6):
    """Round tube along a path: corners and normals."""
    t = np.gradient(path, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    ref = np.where(np.abs(t[:, 1:2]) > 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
    s = np.cross(t, ref); s /= np.linalg.norm(s, axis=1, keepdims=True)
    u = np.cross(s, t)
    a = np.linspace(0, 2 * np.pi, sides + 1)[:-1]
    spoke = np.cos(a)[None, :, None] * s[:, None] + np.sin(a)[None, :, None] * u[:, None]
    ring = path[:, None] + radius[:, None, None] * spoke
    I, J = np.mgrid[:len(path) - 1, :sides]
    K = (J + 1) % sides
    corner = ((I, J), (I + 1, J), (I + 1, K), (I, J), (I + 1, K), (I, K))
    return np.stack([ring[i, j] for i, j in corner], 2).reshape(-1, 3), np.stack([spoke[i, j] for i, j in corner], 2).reshape(-1, 3)


def _blade(root, d, side, length, width, droop, curl, steps=7, round_tip=0.7):
    """A curved leaf or petal: a strip from root along d, bending down, folded along its midrib. Both sides.
    round_tip under 0.5 gives a broad rounded petal, 0.7 a pointed leaf."""
    up = np.array([0, 1.0, 0])
    t = np.linspace(0, 1, steps)
    spine = root + np.outer(t * length, d) - np.outer(droop * length * t ** 2, up)
    if round_tip < 0.5:  # an ellipse is round at its tip
        w = width * np.sqrt(np.clip(4 * t * (1 - t), 0, 1)) ** 0.6 * (0.55 + 0.45 * t)
    else:
        w = width * np.sin(np.pi * np.minimum(t * 1.08, 1)) ** round_tip
    n = np.cross(d, side); n = n / np.linalg.norm(n) * np.sign(n @ up or 1)
    left, right = spine + w[:, None] * side + curl * w[:, None] * n, spine - w[:, None] * side + curl * w[:, None] * n
    P, N = [], []
    for i in range(steps - 1):
        for tri in ((spine[i], left[i], left[i + 1]), (spine[i], left[i + 1], spine[i + 1]),
                    (spine[i], spine[i + 1], right[i + 1]), (spine[i], right[i + 1], right[i])):
            q = np.array(tri)
            f = np.cross(q[1] - q[0], q[2] - q[0]); f /= max(np.linalg.norm(f), 1e-9)
            f = f if f @ up >= 0 else -f
            P += [q, q[::-1]]; N += [np.tile(f, (3, 1)), np.tile(-f, (3, 1))]
    return np.concatenate(P), np.concatenate(N)


def plant(base, height, radius, petal, leaf, rng, petals=7):
    """A flowering plant: a curved stem, a ring of leaves at its foot and a flower of curved petals."""
    up = np.array([0, 1.0, 0])
    parts, cols = [], []
    leaf = np.asarray(leaf, float); petal = np.asarray(petal, float)
    lean = rng.normal(0, 0.12, 3) * [1, 0, 1]
    top = base + up * height * 0.82 + lean * height
    path = np.array([base + (top - base) * s + lean * height * 0.15 * np.sin(np.pi * s) for s in np.linspace(0, 1, 6)])
    parts.append(_tube(path, np.linspace(0.05, 0.03, 6) * radius, 6)); cols.append(leaf * 0.7)
    for k in range(6):  # leaves around the foot
        a = 2 * np.pi * k / 6 + rng.uniform(0, 0.5)
        d = np.array([np.cos(a), 0.45, np.sin(a)]); d /= np.linalg.norm(d)
        side = np.cross(d, up); side /= np.linalg.norm(side)
        parts.append(_blade(base + up * height * 0.06, d, side, radius * rng.uniform(0.75, 1.0), radius * 0.22, 0.45, 0.35))
        cols.append(leaf * rng.uniform(0.85, 1.1))
    for k in range(petals):  # the flower faces up and a little out
        a = 2 * np.pi * k / petals
        d = np.array([np.cos(a), 0.25, np.sin(a)]); d /= np.linalg.norm(d)
        side = np.cross(d, up); side /= np.linalg.norm(side)
        parts.append(_blade(top, d, side, radius * 0.42, radius * 0.16, -0.15, 0.3, 5)); cols.append(petal)
    c, n = _tube(np.array([top - up * radius * 0.04, top + up * radius * 0.05]), np.array([radius * 0.1, radius * 0.08]), 8)
    parts.append((c, n)); cols.append(np.minimum(petal * 0.4 + np.array([0.6, 0.5, 0.05]), 1))
    P = np.concatenate([p for p, _ in parts]); N = np.concatenate([n for _, n in parts])
    C = np.concatenate([np.tile(c, (len(p), 1)) for (p, _), c in zip(parts, cols)])
    return P, N, C


def board(art_p, axes, depth, colour=(0.33, 0.2, 0.11)):
    """A wooden board through a sign's art plane, a little larger than the art, thinner than the art slab so the
    painted faces stay on top on both sides."""
    c = art_p.mean(0)
    h, v = axes  # the texture's own u and v on the card
    n = np.cross(h, v); n /= np.linalg.norm(n)
    v = np.cross(n, h)
    x, y = (art_p - c) @ h, (art_p - c) @ v
    hw, hh = (x.max() - x.min()) / 2 * 1.07, (y.max() - y.min()) / 2 * 1.09
    c = c + h * (x.max() + x.min()) / 2 + v * (y.max() + y.min()) / 2
    P, N = [], []
    corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    for axis in range(3):
        for sgn in (-1, 1):
            q = corners[corners[:, axis] == sgn][[0, 1, 3, 2]]
            w = c + np.outer(q[:, 0] * hw, h) + np.outer(q[:, 1] * hh, v) + np.outer(q[:, 2] * depth, n)
            f = [h, v, n][axis] * sgn
            for tri in ((0, 1, 2), (0, 2, 3)):
                P.append(w[list(tri)]); N.append(np.tile(f, (3, 1)))
    P, N = np.concatenate(P), np.concatenate(N)
    return P, N, np.tile(np.asarray(colour, float), (len(P), 1))

def ribs(p, n, axis_pts, count=12, depth=0.06):
    """Cactus ribs: pushes a smooth surface in and out around the nearest vertical axis through axis_pts."""
    d = p[:, None, [0, 2]] - axis_pts[None, :, [0, 2]]
    k = np.linalg.norm(d, axis=2).argmin(1)
    v = d[np.arange(len(p)), k]
    ang = np.arctan2(v[:, 1], v[:, 0])
    r = np.linalg.norm(v, axis=1)
    tang = np.stack([-np.sin(ang), np.zeros_like(ang), np.cos(ang)], 1)
    n2 = n - tang * (depth * count * np.sin(ang * count))[:, None]
    return p + n * (depth * r * np.cos(ang * count))[:, None], n2 / np.linalg.norm(n2, axis=1, keepdims=True)


def curl(P, N, alpha, size, fold=0.18, droop=0.12):
    """Bends plate() corners (texture u, v and side offset) into a leaf: folded up along the long axis of the painted
    shape and drooping towards its far end. Offsets in the card's own units; normals follow the fold."""
    ys, xs = np.nonzero(alpha > 0.5)
    h, w = alpha.shape
    u0, u1, v0, v1 = xs.min() / w, (xs.max() + 1) / w, ys.min() / h, (ys.max() + 1) / h
    su, sv = (u1 - u0) * size[0], (v1 - v0) * size[1]
    long_u = su >= sv
    a = (P[:, 0] - (u0 + u1) / 2) * size[0] if not long_u else (P[:, 1] - (v0 + v1) / 2) * size[1]  # across the midrib
    t = (P[:, 1] - v0) / max(v1 - v0, 1e-6) if not long_u else (P[:, 0] - u0) / max(u1 - u0, 1e-6)  # along it
    half = (su if not long_u else sv) / 2
    span = sv if not long_u else su
    P = P.copy()
    P[:, 2] += fold * half * (a / max(half, 1e-6)) ** 2 - droop * span * t ** 2
    N = N.copy()
    k = 0 if not long_u else 1
    N[:, k] -= np.sign(N[:, 2]) * 2 * fold * a / max(half, 1e-6) / max(size[k], 1e-6) * size[k]
    return P, N


def flower(centre, radius, petal, rng, petals=8):
    """A flower head in the round: two rings of curved petals around a domed centre, facing up."""
    up = np.array([0, 1.0, 0])
    petal = np.asarray(petal, float)
    parts, cols = [], []
    for ring, (n_, lift, length) in enumerate(((petals, 0.35, 1.0), (petals - 2, 0.7, 0.7))):
        for k in range(n_):
            a = 2 * np.pi * (k + 0.5 * ring) / n_ + rng.uniform(-0.1, 0.1)
            d = np.array([np.cos(a), lift, np.sin(a)]); d /= np.linalg.norm(d)
            side = np.cross(d, up); side /= np.linalg.norm(side)
            parts.append(_blade(centre, d, side, radius * length, radius * 0.38, -0.05, 0.25, 8, round_tip=0.35))
            cols.append(petal * (1.0 if ring == 0 else 0.85))
    c, n = _tube(np.array([centre - up * radius * 0.08, centre + up * radius * 0.12]), np.array([radius * 0.26, radius * 0.18]), 10)
    parts.append((c, n)); cols.append(np.minimum(petal * 0.3 + np.array([0.65, 0.55, 0.08]), 1))
    P = np.concatenate([p for p, _ in parts]); N = np.concatenate([n for _, n in parts])
    return P, N, np.concatenate([np.tile(c, (len(p), 1)) for (p, _), c in zip(parts, cols)])
