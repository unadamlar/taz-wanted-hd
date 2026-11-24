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

def _faces(P, N, C):
    return np.concatenate(P), np.concatenate(N), np.concatenate(C)


def _sheet(grid, colours):
    """Triangles of a (rows, cols, 3) point grid with per-point colours; normals from the faces, smoothed per point."""
    r, c = grid.shape[:2]
    colours = np.broadcast_to(colours, grid.shape)
    I, J = np.mgrid[:r - 1, :c - 1]
    tri = [((I, J), (I + 1, J), (I + 1, J + 1)), ((I, J), (I + 1, J + 1), (I, J + 1))]
    vn = np.zeros_like(grid)
    for t in tri:
        a, b, d = (grid[i, j] for i, j in t)
        f = np.cross(b - a, d - a)
        for i, j in t:
            np.add.at(vn, (i, j), f)
    vn /= np.maximum(np.linalg.norm(vn, axis=2, keepdims=True), 1e-12)
    P = np.concatenate([np.stack([grid[i, j] for i, j in t], 2).reshape(-1, 3) for t in tri])
    N = np.concatenate([np.stack([vn[i, j] for i, j in t], 2).reshape(-1, 3) for t in tri])
    C = np.concatenate([np.stack([colours[i, j] for i, j in t], 2).reshape(-1, 3) for t in tri])
    return P, N, C


def leaf(root, axis, side, length, width, colour, droop=0.25, cup=0.18, steps=9):
    """A modelled leaf: an oval blade with a raised midrib and a real thickness, cupped and drooping to its tip.
    axis points from stalk to tip, side across; both in the leaf's plane."""
    up = np.cross(side, axis); up = up / np.linalg.norm(up) * (1 if np.cross(side, axis)[1] >= 0 else -1)
    t = np.linspace(0, 1, steps)[:, None]
    across = np.linspace(-1, 1, 7)[None, :]
    half = width / 2 * np.sin(np.pi * np.clip(t * 0.96 + 0.04, 0, 1)) ** 0.75
    spine = root + t * length * axis - (droop * length * t ** 2) * up
    lift = cup * half * across ** 2 + 0.04 * width * (1 - np.abs(across)) ** 6  # cupped, with a ridge along the midrib
    top = spine[:, None] + (half * across)[..., None] * side + lift[..., None] * up
    thick = 0.035 * width * (1 - 0.7 * t) * (1 - across ** 2)
    bot = top - thick[..., None] * up
    base = np.asarray(colour, float)
    shade = 0.82 + 0.18 * np.abs(across) ** 0.5  # the midrib a little lighter
    ctop = np.clip(base[None, None] * shade[..., None] + (1 - np.abs(across)[..., None]) ** 8 * 0.18, 0, 1)
    cbot = np.clip(base * 1.12 + 0.04, 0, 1) * np.ones_like(bot)
    P1, N1, C1 = _sheet(top, ctop)
    P2, N2, C2 = _sheet(bot[:, ::-1], cbot)
    edge = np.stack([top[:, 0], bot[:, 0]], 1), np.stack([bot[:, -1], top[:, -1]], 1)
    parts = [(P1, N1, C1), (P2, N2, C2)] + [_sheet(e, np.tile(base * 0.8, e.shape[:2] + (1,))) for e in edge]
    return _faces(*zip(*parts))


def flower(centre, radius, petal, middle, rng, petals=9, rings=2, cheap=False):
    """A modelled flower: a cup of shaped petals (narrow at the base, round at the tip, curving up), a domed centre
    and short stamens. cheap: fewer petals and points and no stamens, for beds of many flowers (a quarter of the
    triangles)."""
    if cheap:
        petals = min(petals, 7)
    up = np.array([0, 1.0, 0])
    petal, middle = np.asarray(petal, float), np.asarray(middle, float)
    parts = []
    for ring, (n_, lift, length) in enumerate(((petals, 0.12, 1.0), (petals - 3, 0.45, 0.7))[:rings]):
        for k in range(n_):
            a = 2 * np.pi * (k + 0.5 * ring) / n_ + rng.uniform(-0.12, 0.12)
            d = np.array([np.cos(a), lift, np.sin(a)]); d /= np.linalg.norm(d)
            side = np.cross(d, up); side /= np.linalg.norm(side)
            t = np.linspace(0, 1, 4 if cheap else 6)[:, None]; across = np.linspace(-1, 1, 3 if cheap else 4)[None, :]
            half = radius * 0.4 * np.sqrt(np.clip(np.sin(np.pi * (0.12 + 0.88 * t)), 0, 1)) * (0.3 + 0.7 * t) ** 0.6  # narrow foot, broad round tip
            normal = np.cross(side, d); normal *= np.sign(normal[1] or 1)
            spine = centre + t * radius * length * d + (0.12 * radius * t ** 2) * up
            g = spine[:, None] + (half * across)[..., None] * side + (0.12 * half * across ** 2)[..., None] * normal
            col = np.clip(petal * (0.82 + 0.25 * t[..., None]) * (1.0 if ring == 0 else 0.9), 0, 1) * np.ones(g.shape)
            for sheet in (g, g[:, ::-1] - normal * radius * 0.01):
                parts.append(_sheet(sheet, col))
    th = np.linspace(0, np.pi / 2, 3 if cheap else 5)[:, None]; ph = np.linspace(0, 2 * np.pi, 9 if cheap else 13)[None, :]
    dome = centre + radius * 0.34 * np.stack([np.cos(th) * np.cos(ph), 0.8 * np.sin(th) * np.ones_like(ph) + 0.15, np.cos(th) * np.sin(ph)], -1)
    dcol = np.clip(middle * (0.75 + 0.35 * np.sin(th))[..., None] * np.ones(dome.shape), 0, 1)
    parts.append(_sheet(dome, dcol))
    for k in range(0 if cheap else 6):  # stamens
        a = 2 * np.pi * k / 6
        d = np.array([np.cos(a) * 0.5, 1.0, np.sin(a) * 0.5]); d /= np.linalg.norm(d)
        p, n = _tube(np.array([centre + up * radius * 0.1, centre + up * radius * 0.1 + d * radius * 0.3]), np.array([radius * 0.025, radius * 0.02]), 4)
        parts.append((p, n, np.tile(np.clip(middle * 1.1, 0, 1), (len(p), 1))))
    return _faces(*zip(*parts))


def disc(centre, radius, normal, thick, colour=(0.62, 0.64, 0.68), sides=32):
    """A metal disc: front and back faces and a rim."""
    n = normal / np.linalg.norm(normal)
    h = np.cross(n, [0, 1.0, 0]); h = h / np.linalg.norm(h) if np.linalg.norm(h) > 1e-6 else np.array([1.0, 0, 0])
    v = np.cross(n, h)
    a = np.linspace(0, 2 * np.pi, sides + 1)
    ring = centre + radius * (np.cos(a)[:, None] * h + np.sin(a)[:, None] * v)
    P, N = [], []
    for s in (1, -1):
        f, c = ring + s * thick * n, centre + s * thick * n
        for i in range(sides):
            tri = np.array([c, f[i], f[i + 1]]) if s > 0 else np.array([c, f[i + 1], f[i]])
            P.append(tri); N.append(np.tile(s * n, (3, 1)))
    for i in range(sides):
        q = np.array([ring[i] + thick * n, ring[i] - thick * n, ring[i + 1] - thick * n, ring[i + 1] + thick * n])
        out = (ring[i] + ring[i + 1]) / 2 - centre; out /= np.linalg.norm(out)
        P += [q[[0, 1, 2]], q[[0, 2, 3]]]; N += [np.tile(out, (3, 1))] * 2
    P, N = np.concatenate(P), np.concatenate(N)
    return P, N, np.tile(np.asarray(colour, float), (len(P), 1))


def pole(top, bottom, radius, colour=(0.55, 0.57, 0.6)):
    p, n = _tube(np.array([top, bottom]), np.array([radius, radius]), 8)
    return p, n, np.tile(np.asarray(colour, float), (len(p), 1))


def spindle(top, bottom, radius, colour, sides=12):
    """A turned baluster from top to bottom, radius at its bulb: collars and beads at both ends, a bulb low down."""
    s = np.r_[0, 0.06, 0.07, 0.11, 0.12, 0.17, np.linspace(0.21, 0.87, 12), 0.91, 0.93, 0.94, 1]
    bulb = 0.34 + 0.66 * np.clip(np.sin(np.pi * (s[6:18] - 0.21) / 0.66), 0, 1) ** 0.7
    f = np.r_[0.5, 0.5, 0.62, 0.62, 0.5, 0.3, bulb, 0.3, 0.55, 0.5, 0.5]
    p, n = _tube(top + np.outer(s, bottom - top), radius * f, sides)
    return p, n, np.tile(np.asarray(colour, float), (len(p), 1))


def _ribbed(path, radius, colour, ribs=14, depth=0.05, sides=42, cap=True):
    """A ribbed succulent trunk along a path with a rounded top: corners, normals, colours."""
    t = np.gradient(path, axis=0); t /= np.linalg.norm(t, axis=1, keepdims=True)
    ref = np.where(np.abs(t[:, 1:2]) > 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
    s = np.cross(t, ref); s /= np.linalg.norm(s, axis=1, keepdims=True)
    u = np.cross(s, t)
    a = np.linspace(0, 2 * np.pi, sides + 1)
    rib = 1 + depth * (np.abs(np.cos(ribs * a / 2)) * 2 - 1)  # rounded ribs with narrow grooves
    r = radius[:, None] * rib[None]
    grid = path[:, None] + r[..., None] * (np.cos(a)[None, :, None] * s[:, None] + np.sin(a)[None, :, None] * u[:, None])
    col = np.asarray(colour, float) * (0.72 + 0.28 * (rib[None, :, None] - 1 + depth) / (2 * depth)) * np.ones(grid.shape)
    return _sheet(grid[:, ::-1], col)


def saguaro(base, height, radius, colour, rng, arms=None):
    """A saguaro: a ribbed trunk with a domed top and arms that bend upward: one to three at random, or one per
    (angle, height fraction, reach) in arms."""
    up = np.array([0, 1.0, 0])
    k = np.r_[np.linspace(0, 0.85, 12), 0.85 + 0.15 * np.sin(np.linspace(0, np.pi / 2, 9)[1:])]  # rings bunched into the domed top
    top = (k - 0.85) / 0.15
    prof = radius * np.where(k > 0.85, np.sqrt(np.clip(1 - top ** 2, 0.0, 1)), 1.0) * (1.04 - 0.08 * k)
    parts = [_ribbed(base + np.outer(k * height, up), prof, colour)]
    for j in range(rng.integers(1, 4) if arms is None else len(arms)):
        if arms is None:
            a = rng.uniform(0, 2 * np.pi) if j == 0 else a + np.pi * rng.uniform(0.7, 1.3)
            y0, reach = height * rng.uniform(0.35, 0.6), radius * rng.uniform(1.8, 2.6)
        else:
            a, y0, reach = arms[j][0], height * arms[j][1], arms[j][2]
        out = np.array([np.cos(a), 0, np.sin(a)])
        rise = height * rng.uniform(0.25, 0.38)
        q = np.r_[np.linspace(0, 0.85, 12), 0.85 + 0.15 * np.sin(np.linspace(0, np.pi / 2, 7)[1:])]
        path = base + up * y0 + np.outer(np.minimum(q * 2, 1) * reach, out) + np.outer(np.clip(q * 1.6 - 0.45, 0, 1) ** 1.2 * rise + q * radius * 0.6, up)
        pr = radius * 0.62 * np.where(q > 0.85, np.sqrt(np.clip(1 - ((q - 0.85) / 0.15) ** 2, 0.0, 1)), 1.0)
        parts.append(_ribbed(path, pr, colour))
    return _faces(*zip(*parts))


def barrel(base, height, radius, colour, flower_colour, rng):
    """A barrel cactus: a squat ribbed dome with a ring of small flowers on top."""
    k = np.linspace(0, 1, 12)
    prof = radius * np.sqrt(np.clip(1 - (k * 1.05 - 0.05) ** 2 * 0.8, 0.02, 1)) * (0.75 + 0.25 * np.sin(np.pi * np.minimum(k * 1.6, 1)))
    prof[-1] = radius * 0.05
    parts = [_ribbed(base + np.outer(k * height, [0, 1.0, 0]), prof, colour, ribs=16, depth=0.07)]
    for j in range(5):
        a = 2 * np.pi * j / 5
        c = base + np.array([np.cos(a) * radius * 0.35, height * 0.97, np.sin(a) * radius * 0.35])
        parts.append(flower(c, radius * 0.22, flower_colour, (0.95, 0.8, 0.2), rng, petals=5, rings=1))
    return _faces(*zip(*parts))


def cloth(u, v, size, along_u, top, folds, amp, steps=(24, 12)):
    """A hanging banner over a card's texture rectangle u=(u0, u1), v=(v0, v1): corners (u, v, offset) and normals as
    solid.plate gives them, waved into folds across it (along u if along_u) that deepen away from its top edge
    (texture coordinate top on the hanging axis)."""
    a_r, d_r = (u, v) if along_u else (v, u)
    A, D = np.meshgrid(np.linspace(*a_r, steps[0]), np.linspace(*d_r, steps[1]), indexing="ij")
    fa = (A - a_r[0]) / (a_r[1] - a_r[0])
    fd = np.abs(D - top) / (d_r[1] - d_r[0])
    k = 2 * np.pi * folds
    w = amp * (0.25 + 0.75 * fd)
    Z = w * np.sin(k * fa)
    slope = w * np.cos(k * fa) * k / ((a_r[1] - a_r[0]) * size[0 if along_u else 1])
    grid = np.stack([A, D, Z], -1) if along_u else np.stack([D, A, Z], -1)
    nrm = np.stack([-slope, np.zeros_like(slope), np.ones_like(slope)], -1) if along_u else np.stack([np.zeros_like(slope), -slope, np.ones_like(slope)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    I, J = np.mgrid[:steps[0] - 1, :steps[1] - 1]
    corner = ((I, J), (I + 1, J), (I + 1, J + 1), (I, J), (I + 1, J + 1), (I, J + 1))
    return np.stack([grid[i, j] for i, j in corner], 2).reshape(-1, 3), np.stack([nrm[i, j] for i, j in corner], 2).reshape(-1, 3)


def bulb(centre, radius, colour, down=(0, -1.0, 0)):
    """A round light bulb hanging from a wire: a glassy sphere with a dark socket on its wire side."""
    d = np.asarray(down, float); d /= np.linalg.norm(d)
    h = np.cross(d, [1.0, 0, 0]); h = h / np.linalg.norm(h) if np.linalg.norm(h) > 1e-6 else np.array([0, 0, 1.0])
    v = np.cross(d, h)
    th = np.linspace(0, np.pi, 7)[:, None]; ph = np.linspace(0, 2 * np.pi, 11)[None, :]
    g = centre + radius * (np.cos(th)[..., None] * -d + (np.sin(th) * np.cos(ph))[..., None] * h + (np.sin(th) * np.sin(ph))[..., None] * v)
    c = np.clip(np.asarray(colour, float) * (0.75 + 0.35 * np.cos(th / 2))[..., None], 0, 1) * np.ones(g.shape)
    p, n = _tube(np.array([centre - d * radius * 0.7, centre - d * radius * 1.3]), np.array([radius * 0.45, radius * 0.4]), 6)
    parts = [_sheet(g, c), (p, n, np.tile([0.12, 0.12, 0.13], (len(p), 1)))]
    return _faces(*zip(*parts))
