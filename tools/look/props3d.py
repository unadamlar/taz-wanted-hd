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


def _sheet(grid, colours, wrap=False):
    """Triangles of a (rows, cols, 3) point grid with per-point colours; normals from the faces, smoothed per point.
    wrap: the grid closes round (last column = first) and a row shrunk to a point is a pole, both smooth."""
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
    if wrap:
        vn[:, 0] = vn[:, -1] = vn[:, 0] + vn[:, -1]
        pole = np.ptp(grid, axis=1).max(1) < 1e-9
        vn[pole] = vn[pole].sum(1, keepdims=True)
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


def plank(path, half_w, half_d, normal=(0, 0, 1.0)):
    """A sawn board along a path: flat faces, half_w across in the plane normal to `normal`, half_d deep, ends capped.
    Both windings, so it shows from either side under any material."""
    z = np.asarray(normal, float)
    t = np.gradient(path, axis=0)
    s = np.cross(z, t); s /= np.linalg.norm(s, axis=1, keepdims=True)
    ring = np.stack([path + a * half_w * s + d * half_d * z for a, d in ((1, 1), (-1, 1), (-1, -1), (1, -1))], 1)
    face = np.stack([np.broadcast_to(z, s.shape), -s, -np.broadcast_to(z, s.shape), s], 1)
    P, N = [], []
    for i in range(len(path) - 1):
        for j in range(4):
            k = (j + 1) % 4
            P += [ring[[i, i + 1, i + 1], [j, j, k]], ring[[i, i + 1, i], [j, k, k]]]
            N += [face[[i, i + 1, i + 1], [j, j, j]]] * 2
    for i, sg in ((0, -1), (-1, 1)):
        cap = np.tile(sg * t[i] / np.linalg.norm(t[i]), (3, 1))
        P += [ring[i, [0, 1, 2]], ring[i, [0, 2, 3]]]; N += [cap, cap]
    P, N = np.concatenate(P), np.concatenate(N)
    return np.r_[P, P.reshape(-1, 3, 3)[:, ::-1].reshape(-1, 3)], np.r_[N, N]


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


def _stem(path, radius, pal, ribs, side, phase, depth=0.14):
    """A saguaro stem along a path in one plane (side: that plane's normal, so the ribs don't twist round bends).
    Each rib is a rounded ridge with a narrow light crest between soft grooves.
    pal: (rings, 3, 3) groove, body and stripe colours per ring."""
    t = np.gradient(path, axis=0); t /= np.linalg.norm(t, axis=1, keepdims=True)
    s = np.cross(side, t); s /= np.linalg.norm(s, axis=1, keepdims=True)
    u = np.cross(t, s)
    f = np.r_[np.tile([0, 0.12, 0.36, 0.5, 0.64, 0.88], ribs), 0]  # place across a rib: groove at 0, crest at 0.5
    a = 2 * np.pi * (np.r_[np.repeat(np.arange(ribs), 6), ribs] + f) / ribs + phase
    rib = 1 - depth * (1 - np.sin(np.pi * f)) ** 2
    grid = path[:, None] + (radius[:, None] * rib)[..., None] * (np.cos(a)[None, :, None] * s[:, None] + np.sin(a)[None, :, None] * u[:, None])
    w = np.array([[1, 0, 0], [0.3, 0.7, 0], [0, 1, 0], [0, 0.4, 0.6], [0, 1, 0], [0.3, 0.7, 0]])[np.r_[np.tile(np.arange(6), ribs), 0]]
    col = np.einsum("jc,icx->ijx", w, pal)
    return _sheet(grid[:, ::-1], col[:, ::-1], wrap=True)


def _dome(end, tangent, radius, n=6):
    """Centreline points and radii of a round cap over a stem's end."""
    th = np.linspace(0, np.pi / 2, n + 1)[1:]
    return end + np.outer(radius * np.sin(th), tangent), radius * np.cos(th)


def saguaro(base, height, radius, colour, rng, arms=None):
    """A cartoon saguaro: a ribbed trunk with a round domed top, darker at its foot, and arms with a round elbow and
    domed ends: one to three at random, or one per (angle, height fraction, reach) in arms. Muted olive with soft
    grooves and a faint light crest per rib (sRGB): the painted cactus's dark grooves and bright stripes read as a watermelon."""
    up = np.array([0, 1.0, 0])
    c = np.asarray(colour, float)
    g = c @ (0.3, 0.59, 0.11); c = 0.85 * (c + 0.6 * (g * np.array((0.82, 1.0, 0.62)) - c))  # a saguaro's muted olive, not paint green
    pal = np.stack([c * 0.62, c * 0.9, np.clip(c * 1.05 + (0.05, 0.05, 0.02), 0, 1)])
    k = np.array([0, 0.04, 0.1, 0.18, 0.3, 0.48, 0.66, 0.84, 1.0])
    trunk_h = height - radius
    dp, dr = _dome(base + up * trunk_h, up, radius * 0.96)
    path = np.r_[base + np.outer(k * trunk_h, up), dp]
    prof = np.r_[radius * (1.04 - 0.08 * k), dr]
    foot = np.r_[np.clip(k / 0.2, 0, 1), np.ones(len(dr))] ** 0.7  # the foot is darker and a little olive
    tp = pal[None] * (0.6 + 0.4 * foot)[:, None, None]
    tp = tp + (1 - foot)[:, None, None] * 0.12 * (np.array([0.3, 0.27, 0.12]) - tp)
    parts = [_stem(path, prof, tp, 10, np.array([1.0, 0, 0]), rng.uniform(0, 2 * np.pi))]
    for j in range(rng.integers(1, 4) if arms is None else len(arms)):
        if arms is None:
            a = rng.uniform(0, 2 * np.pi) if j == 0 else a + np.pi * rng.uniform(0.7, 1.3)
            y0, reach = height * rng.uniform(0.35, 0.6), radius * rng.uniform(1.8, 2.6)
        else:
            a, y0, reach = arms[j][0], height * arms[j][1], arms[j][2]
        out = np.array([np.cos(a), 0, np.sin(a)])
        ar = radius * 0.68
        rise = max(height * rng.uniform(0.25, 0.38), 2.5 * ar)
        e = min(0.5 * reach, 0.45 * rise, 1.6 * ar)  # elbow radius
        root = base + up * y0
        h = np.outer(np.linspace(0, 1, 4)[:-1], out * (reach - e) + up * 0.2 * ar)  # out from the trunk's axis, rising a little
        corner = root + out * (reach - e) + up * 0.2 * ar
        ph = np.linspace(0, np.pi / 2, 7)
        elbow = corner + up * e + e * (np.outer(np.sin(ph), out) - np.outer(np.cos(ph), up))
        top = corner + out * e + up * (rise - ar)
        stem = np.r_[root + h, elbow, elbow[-1] + np.outer(np.linspace(0, 1, 4)[1:], top - elbow[-1])]
        cp, cr = _dome(top, up, ar * 0.96, 5)
        pr = np.r_[np.full(len(stem), ar), cr]
        parts.append(_stem(np.r_[stem, cp], pr, np.broadcast_to(pal, (len(pr), 3, 3)), 8, np.cross(out, up), rng.uniform(0, 2 * np.pi)))
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


def pine(base, height, radius, needle, snow, rng):
    """A stylized fir: stacked tiers with scalloped, drooping skirts and a real underside, thick snow caps poured over
    each tier, a short trunk. Each tree keeps its paint's colour (user's pick over snow-white tiers, 2026-11-25)."""
    needle, snow = np.asarray(needle, float), np.asarray(snow, float)
    tiers = int(np.clip(round(height / radius * 1.2), 3, 5))
    lobes = 9
    cols = lobes * 4
    a = np.linspace(0, 2 * np.pi, cols + 1)[None]
    ph = rng.uniform(0, 2 * np.pi)
    trunk_h = 0.14 * height
    parts = []
    p, n = _tube(np.array([base, base + [0, trunk_h + 0.1 * height, 0]]), np.array([0.13, 0.1]) * radius, 8)
    parts.append((p, n, np.tile([0.32, 0.2, 0.12], (len(p), 1))))
    span = height - trunk_h
    for i in range(tiers):
        f = i / (tiers - 1)  # 0 top tier, 1 bottom
        R = radius * (0.38 + 0.62 * f)
        top = base[1] + height - span * (0.0 if i == 0 else 0.22 + 0.74 * (i - 0.4) / tiers)
        h = span * (0.42 if i == 0 else 0.36 + 0.06 * f)
        t = np.linspace(0, 1, 8)[:, None]
        wave = np.cos(lobes * a + ph + i)
        r = R * t ** 0.85 * (1 + 0.1 * wave * t ** 3)
        y = top - h * t - 0.1 * h * (0.5 + 0.5 * wave) * t ** 4
        shade = (0.72 + 0.4 * (1 - t) - 0.12 * f)[..., None]
        col = np.clip(needle * shade, 0, 1) * np.ones(r.shape + (3,))
        g = np.stack([base[0] + r * np.cos(a), y, base[2] + r * np.sin(a)], -1)
        parts.append(_sheet(g, col, wrap=True))
        # underside: from the rim back in and up to the trunk, darker
        u = np.linspace(0, 1, 4)[:, None]
        ru = r[-1:] * (1 - 0.85 * u)
        yu = y[-1:] + 0.28 * h * u ** 0.7
        gu = np.stack([base[0] + ru * np.cos(a), yu, base[2] + ru * np.sin(a)], -1)
        parts.append(_sheet(gu[:, ::-1], np.clip(needle * 0.45, 0, 1) * np.ones(gu.shape)))
        # a snow cap with drips down the scallops, sitting just proud of the tier
        ts = np.linspace(0, 1, 6)[:, None]
        reach = 0.42 + 0.2 * (0.5 + 0.5 * np.cos(lobes * a + ph + i)) ** 3 + 0.06 * np.sin(3 * lobes * a)
        tt = ts * reach
        rs = R * tt ** 0.85 * (1 + 0.1 * np.cos(lobes * a + ph + i) * tt ** 3) * 1.035 + 0.012 * R
        ys = top - h * tt + 0.03 * h * (1 - ts) + 0.015 * h
        gs = np.stack([base[0] + rs * np.cos(a), ys, base[2] + rs * np.sin(a)], -1)
        cs = np.clip(snow * (0.92 + 0.1 * (1 - ts))[..., None], 0, 1) * np.ones(gs.shape)
        parts.append(_sheet(gs, cs, wrap=True))
        parts.append(_sheet(np.stack([gs[-1], gs[-1] + [0, -0.035 * h, 0] - 0.02 * R * np.stack([np.cos(a[0]), 0 * a[0], np.sin(a[0])], -1)], 0)[:, ::-1], np.clip(snow * 0.82, 0, 1) * np.ones((2,) + gs.shape[1:])))
    return _faces(*zip(*parts))


def icicles(width, tops, lengths, radius, ice, snow):
    """A snow lip along a ledge with icicles hanging from it, in a card's own metric frame: x along the ledge (0..width),
    y down from the ledge, z out of the card. tops[i], lengths[i]: where icicle i hangs from and how long it is."""
    ice, snow = np.asarray(ice, float), np.asarray(snow, float)
    parts = []
    x = np.linspace(-0.5 * radius, width + 0.5 * radius, 16)
    lip = np.c_[x, 0.1 * radius + 0.25 * radius * np.sin(x / max(radius, 1e-6) * 0.7), np.zeros(len(x))]  # a lumpy roll of snow
    p, n = _tube(lip, 1.1 * radius * (1 + 0.2 * np.sin(x / max(radius, 1e-6) * 1.3)), 8)
    parts.append((p, n, np.tile(snow, (len(p), 1))))
    for x, L in zip(tops, lengths):
        if L < 1.5 * radius:
            continue
        k = np.linspace(0, 1, 6)
        path = np.c_[np.full(6, x), 0.5 * radius + k * L, 0.15 * radius * np.sin(k * 3)]
        r = radius * (1 - k) ** 1.1 * (1 + 0.18 * np.sin(k * 11)) + 0.03 * radius
        p, n = _tube(path, r, 7)
        parts.append((p, n, np.clip(ice[None] * (1.05 - 0.3 * (p[:, 1:2] / (L + radius))), 0, 1)))  # deeper blue towards the tip
    return _faces(*zip(*parts))


def star_tier(centre, radius, drop, bands, points=10, depth=0.38, thick=0.08, phase=0.0, tip_lift=0.15):
    """One thick star leaf in crisp planar facets, two per point, creased along each point's ridge and valley: straight
    sharp edges, the paint's colour bands (body, pale inner line, dark outline) as hard stripes of even width along the
    edges, a dark wall round the rim and a dark underside. drop: how far the valleys sit below the middle (negative cups
    it); the tips sit tip_lift of that higher. bands: (colour, inner edge as a share of the radius) from the middle out."""
    cen = np.asarray(centre, float)
    up, e1, e2 = np.array([0, 1.0, 0]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0])
    a = phase + np.pi * np.arange(2 * points + 1) / points
    r = np.where(np.arange(2 * points + 1) % 2 == 0, radius, radius * (1 - depth))
    h = np.where(np.arange(2 * points + 1) % 2 == 0, -drop * (1 - tip_lift), -drop)
    rim = cen + (r * np.cos(a))[:, None] * e1 + (r * np.sin(a))[:, None] * e2 + h[:, None] * up
    dark = np.asarray(bands[-1][0], float)
    under = np.clip(np.asarray(bands[0][0], float) * 0.4, 0, 1)
    T, C, F = [], [], []  # corners, colours, the side each triangle faces
    for k in range(2 * points):  # facet from the middle to rim[k], rim[k + 1]
        A, B = rim[k] - cen, rim[k + 1] - cen
        edges = [b[1] for b in bands[1:]] + [1.0]
        for (col, s0), s1 in zip(bands, edges):
            q = [cen + s0 * A, cen + s1 * A, cen + s1 * B, cen + s0 * B]
            T += [q[0], q[1], q[2], q[0], q[2], q[3]] if s0 > 0 else [cen, q[1], q[2]]
            C += [col] * (6 if s0 > 0 else 3)
            F += [up] * (2 if s0 > 0 else 1)
        lo = -thick * radius * up
        a2, b2 = cen + lo + 0.97 * A, cen + lo + 0.97 * B
        T += [rim[k], rim[k] + lo, rim[k + 1] + lo, rim[k], rim[k + 1] + lo, rim[k + 1]]  # the rim's wall
        C += [dark * 0.8] * 6
        F += [A + B] * 2
        T += [cen + lo * 2.5, b2, a2]  # underside, a shallow cone down to the stem
        C += [under] * 3
        F += [-up]
    P = np.array(T)
    t = P.reshape(-1, 3, 3)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n *= np.where((n * np.array(F)).sum(1) < 0, -1, 1)[:, None]
    return P, np.repeat(n, 3, 0), np.array(C)


def starbush(base, height, radius, bands, rng, points=10):
    """A reimagined spiky plant: stacked crisp star tiers that narrow upward over a dark stem, the top one a star spike."""
    base = np.asarray(base, float)
    up = np.array([0, 1.0, 0])
    tiers = int(np.clip(round(height / radius * 2) + 2, 3, 5))
    parts = []
    p, n = _tube(np.array([base, base + up * 0.6 * height]), np.array([0.12, 0.08]) * radius, 8)
    parts.append((p, n, np.tile(np.clip(np.asarray(bands[0][0], float) * 0.3, 0, 1), (len(p), 1))))
    for i in range(tiers):
        f = i / max(tiers - 1, 1)  # 0 bottom, 1 top
        R = radius * (1 - 0.6 * f)  # each tier shows a broad band of itself past the one above
        y = height * (0.4 + 0.58 * f)
        drop = height * (0.2 - 0.04 * f) if i < tiers - 1 else height * 0.28  # the top tier is a peaked spike
        parts.append(star_tier(base + up * y, R, drop, bands, points, phase=rng.uniform(0, 2 * np.pi), thick=0.07))
    return _faces(*zip(*parts))


def _inset(E, w):
    """The polyline E (x along, y down) moved up by w, mitred at its corners so the band between stays w wide."""
    d = np.diff(E, axis=0)
    n = np.c_[d[:, 1], -d[:, 0]] / np.linalg.norm(d, axis=1, keepdims=True)  # each segment's side towards the top
    na, nb = np.r_[n[:1], n], np.r_[n, n[-1:]]
    m = (na + nb) / np.maximum(1 + (na * nb).sum(1, keepdims=True), 0.25)
    q = E + w * m
    q[:, 1] = np.maximum(q[:, 1], 0.02 * E[:, 1].max())
    return q


def fringe(edge, bands, widths, thick, curl, tip):
    """A zigzag fringe in a card's metric frame (x along, y down from its top edge, z out of the card): a thick sheet with
    a rounded roll along the top, crisp teeth creased down their middles, their points curling out by curl, and on both
    faces the paint's hard colour bands following the zigzag (body, pale line, dark outline), the back face darker.
    edge: the zigzag's corners (x, y), left to right; tip: 1 at a point, 0 at a notch, per corner; widths: pale, dark."""
    E = np.asarray(edge, float)
    H = E[:, 1].max()
    body, pale, dark = (np.asarray(b, float) for b in bands)
    rows = [np.c_[E[:, 0], np.zeros(len(E))], _inset(E, widths[0] + widths[1]), _inset(E, widths[1]), E]
    cols = [body, pale, dark]
    out = lambda q: curl * H * (q[:, 1] / H) ** 2 * (0.4 + 0.6 * np.asarray(tip)) + 0.18 * thick * np.asarray(tip) * q[:, 1] / H
    T, C, F = [], [], []
    for face in (1, -1):
        for k in range(3):
            a, b = rows[k], rows[k + 1]
            A = np.c_[a, out(a) + face * thick / 2]
            B = np.c_[b, out(b) + face * thick / 2]
            for i in range(len(E) - 1):
                T += [A[i], B[i], B[i + 1], A[i], B[i + 1], A[i + 1]]
                C += [cols[k]] * 6
                F += [(0, 0, face)] * 2
    lo, hi = np.c_[E, out(E) - thick / 2], np.c_[E, out(E) + thick / 2]
    for i in range(len(E) - 1):  # the edge's wall
        T += [lo[i], hi[i], hi[i + 1], lo[i], hi[i + 1], lo[i + 1]]
        C += [dark * 0.8] * 6
        F += [(E[i, 1] - E[i + 1, 1], E[i + 1, 0] - E[i, 0], 0)] * 2  # away from the top
    P = np.array(T)
    t = P.reshape(-1, 3, 3)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n *= np.where((n * np.array(F)).sum(1) < 0, -1, 1)[:, None]
    r = 0.75 * thick
    p, nn = _tube(np.array([[E[0, 0], r, 0], [E[-1, 0], r, 0]]), np.full(2, r), 10)
    return np.r_[P, p], np.r_[np.repeat(n, 3, 0), nn], np.r_[np.array(C), np.tile(body, (len(p), 1))]


def turf(xs, cover, bulge, grass, soil, rng, blade_gap):
    """A grassy sod edge in a card's metric frame (x along, y down from its top edge, z out of the card): a rounded lip
    reaching cover(x) down, bulging out by bulge, its underside darkening into soil, and grass blades along its top
    leaning out and drooping over it. xs: sample points along the edge; cover: the lip's depth at each."""
    xs, cover = np.asarray(xs, float), np.asarray(cover, float)
    grass, soil = np.asarray(grass, float), np.asarray(soil, float)
    s = np.linspace(0, 1, 9)
    y = cover[None, :] * s[:, None]
    z = np.broadcast_to(bulge * (np.sin(np.pi * np.minimum(s * 0.85, 1)) ** 0.7 * (1 - 0.55 * s))[:, None], y.shape)
    grid = np.stack([np.broadcast_to(xs, y.shape), y, z], 2)
    shade = np.clip((s - 0.45) / 0.55, 0, 1)[:, None, None]
    cols = grass * (1 - 0.45 * np.clip(s / 0.8, 0, 1))[:, None, None] * (1 - shade) + soil * shade
    P, N, C = _sheet(grid, np.broadcast_to(cols, grid.shape).copy())
    parts = [(P, N, C)]
    for x in np.arange(xs[0], xs[-1], blade_gap) + rng.random(int(np.ceil((xs[-1] - xs[0]) / blade_gap))) * blade_gap:
        k = min(np.searchsorted(xs, x), len(xs) - 1)
        root = np.array([x, cover[k] * rng.uniform(0.02, 0.3), bulge * rng.uniform(0.4, 0.9)])
        d = np.array([rng.uniform(-0.35, 0.35), rng.uniform(-0.9, -0.2), rng.uniform(0.6, 1.0)])
        d /= np.linalg.norm(d)
        length, width = cover[k] * rng.uniform(0.45, 1.0), blade_gap * rng.uniform(0.7, 1.2)
        t = np.linspace(0, 1, 5)
        spine = root + np.outer(t * length, d) + np.outer(rng.uniform(0.3, 0.7) * length * t ** 2, (0, 1.0, 0))  # droops down (y)
        side = np.cross(d, (0, 0, 1.0)); side = side / max(np.linalg.norm(side), 1e-9)
        w = width * (1 - t) ** 0.8
        L, R = spine + w[:, None] * side, spine - w[:, None] * side
        g = grass * rng.uniform(0.75, 1.15)
        for i in range(4):
            for q in ((L[i], R[i], R[i + 1]), (L[i], R[i + 1], L[i + 1])):
                q = np.array(q)
                f = np.cross(q[1] - q[0], q[2] - q[0]); f /= max(np.linalg.norm(f), 1e-9)
                f = f if f[2] >= 0 else -f
                c = np.tile(g * (0.7 + 0.3 * t[i]), (3, 1))
                parts += [(q, np.tile(f, (3, 1)), c), (q[::-1], np.tile(-f, (3, 1)), c * 0.8)]
    return tuple(np.concatenate(x) for x in zip(*parts))


def grille(rect, cell, frame, pitch, bar, x0, frame_col, wire_col, edge_col):
    """A welded mesh panel in a card's metric frame (x along u, y along v, z out): a bevelled frame with bolt heads on both
    faces and a diagonal lattice of straps (wide bars) or wires inside, one direction over the other. cell: the world size
    of one texture repeat; rect (x0, x1, y0, y1): the part of it this card shows, framed only along the repeat's own edges.
    pitch: spacing of the lattice along x; x0: where a bar crosses the repeat's middle row. Wires face out in wire_col
    and turn to edge_col round their sides, as the paint's wires have an outline and a glow round them."""
    fc, wc, ec = (np.asarray(c_, float) for c_ in (frame_col, wire_col, edge_col))
    xa, xb, ya, yb = rect
    W, H = cell
    parts = []
    r = frame / 2
    on = lambda a, b: abs(a - b) < 0.02 * max(W, H)
    beams = [((xa, ya + r), (xb, ya + r), on(ya, 0)), ((xa, yb - r), (xb, yb - r), on(yb, H)),
             ((xa + r, ya), (xa + r, yb), on(xa, 0)), ((xb - r, ya), (xb - r, yb), on(xb, W))]
    for a, b, keep in beams:
        if not keep:
            continue
        p, n = plank(np.c_[np.array([a, b], float), np.zeros(2)], r, 0.55 * r)
        parts.append((p, n, np.tile(fc, (len(p), 1))))
        for t in (0.1, 0.5, 0.9):
            for z in (1, -1):
                c = np.array([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, z * 0.55 * r])
                parts.append(disc(c, 0.3 * r, np.array([0, 0, z * 1.0]), 0.14 * r, np.clip(fc * 1.25 + 0.1, 0, 1), 5))
    lo = np.array([xa + (frame * 0.8 if on(xa, 0) else 0), ya + (frame * 0.8 if on(ya, 0) else 0)])
    hi = np.array([xb - (frame * 0.8 if on(xb, W) else 0), yb - (frame * 0.8 if on(yb, H) else 0)])
    flat = bar > 0.04 * min(W, H)
    for sgn, z in ((1, 0.25), (-1, -0.25)):
        for k in range(-int(2 * W / pitch) - 2, int(2 * W / pitch) + 3):
            c = x0 + k * pitch  # bar through (c, H / 2), slope sgn
            t = np.array([lo[0] - c, hi[0] - c, (lo[1] - H / 2) * sgn, (hi[1] - H / 2) * sgn])
            s0, s1 = max(min(t[0], t[1]), min(t[2], t[3])), min(max(t[0], t[1]), max(t[2], t[3]))
            if s1 - s0 < bar:
                continue
            path = np.array([[c + s, H / 2 + sgn * s, z * bar * (0.7 if flat else 1.2)] for s in (s0, s1)])
            if flat:
                p, n = plank(path, bar / 2, 0.22 * bar)
            else:
                p, n = _tube(path, np.full(2, bar / 2), 6)
            parts.append((p, n, ec + (wc - ec) * n[:, 2:] ** 2))
    return _faces(*zip(*parts)) if parts else None


def lip(length, height, repeat, top_col, body_col, neon):
    """A raised walkway edge in a card's metric frame (x 0..length, y 0..height downward, z out both ways): a rounded
    rail on top, a deep panel below with one recessed lit channel per texture repeat, a thin rail at the foot."""
    tc, bc, nc = (np.asarray(c, float) for c in (top_col, body_col, neon))
    d = 0.16 * height
    parts = []
    tube = lambda y, r, c: (lambda pn: parts.append((pn[0], pn[1], np.tile(c, (len(pn[0]), 1)))))(_tube(np.array([[0, y, 0], [length, y, 0]], float), np.full(2, r), 10))
    tube(0.13 * height, 0.15 * height, tc)
    tube(0.96 * height, 0.05 * height, np.clip(bc * 1.3, 0, 1))
    box = lambda x0, x1, y0, y1, dz, c: (lambda pn: parts.append((pn[0], pn[1], np.tile(c, (len(pn[0]), 1)))))(
        plank(np.array([[x0, (y0 + y1) / 2, 0], [x1, (y0 + y1) / 2, 0]], float), (y1 - y0) / 2, dz))
    box(0, length, 0.24 * height, 0.5 * height, d, bc)
    box(0, length, 0.72 * height, 0.95 * height, d, bc)
    n = max(1, int(round(length / repeat)))
    for i in range(n + 1):
        x = i * length / n
        box(max(x - 0.05 * repeat, 0), min(x + 0.05 * repeat, length), 0.5 * height, 0.72 * height, d, bc)
    box(0, length, 0.5 * height, 0.72 * height, 0.25 * d, np.clip(bc * 0.35, 0, 1))  # the channel's back
    for i in range(n):
        x0, x1 = (i + 0.05) * length / n + 0.02 * repeat, (i + 0.95) * length / n - 0.02 * repeat
        for z in (1, -1):
            p, nn = _tube(np.array([[x0, 0.61 * height, z * 0.55 * d], [x1, 0.61 * height, z * 0.55 * d]]), np.full(2, 0.06 * height), 8)
            parts.append((p, nn, np.tile(nc, (len(p), 1))))
    return _faces(*zip(*parts))


def profiled(path, half_w, half_d, bands, chamfer=0.25, edge=0.45, normal=(0, 0, 1.0)):
    """A board with chamfered long edges along a path in a card's plane (z out of it), coloured across its width by the
    paint's own bands as hard stripes on both faces: the paint's pale edge lines land near the chamfers, its dark outline
    on the edge walls. half_w: a number or one per point (0 at a picket's point).
    bands: (colour, t0, t1) across the width, t from -1 to 1 along the path's left side (z x tangent).
    normal: z, one for all or one per point (a beam that follows a run of cards round its corners)."""
    path = np.asarray(path, float)
    hw = np.broadcast_to(np.asarray(half_w, float), len(path))
    z = np.broadcast_to(np.asarray(normal, float), path.shape)
    t_ = np.gradient(path, axis=0)
    t_ /= np.linalg.norm(t_, axis=1, keepdims=True)
    s = np.cross(z, t_)
    s /= np.linalg.norm(s, axis=1, keepdims=True)
    cols = [np.asarray(c, float) for c, _, _ in bands]
    cut = sorted({round(float(x), 4) for _, a, b in bands for x in (a, b)} | {-1.0, 1.0})
    ts = np.array(sorted(set(cut) | {round(-1 + chamfer, 4), round(1 - chamfer, 4)}))
    prof = [(t, half_d * (edge + (1 - edge) * min(1.0, (1 - abs(t)) / chamfer))) for t in ts]
    band = lambda t: cols[next((i for i, (_, a, b) in enumerate(bands) if a <= t <= b), int(np.argmin([min(abs(t - a), abs(t - b)) for _, a, b in bands])))]
    ring = []  # cross-section corners (t, z) round the board: front left to right, back right to left
    ring += [(t, zz, band(0.5 * (t + prof[min(i + 1, len(prof) - 1)][0]))) for i, (t, zz) in enumerate(prof)]
    ring += [(t, -zz, band(0.5 * (t + prof[max(i - 1, 0)][0]))) for i, (t, zz) in reversed(list(enumerate(prof)))]
    wall = [np.clip(band(1.0) * 0.75, 0, 1), np.clip(band(-1.0) * 0.75, 0, 1)]
    P, C, F = [], [], []
    at = lambda i, t, zz: path[i] + t * hw[i] * s[i] + zz * z[i]
    m = len(ring)
    for j in range(m):
        (t0, z0, c0), (t1, z1, _) = ring[j], ring[(j + 1) % m]
        side_wall = abs(t0 - t1) < 1e-6
        col = wall[0 if t0 > 0 else 1] if side_wall else c0
        out = np.array([t0 + t1, 0, z0 + z1]) if not side_wall else np.array([np.sign(t0), 0, 0])
        for i in range(len(path) - 1):
            a, b, c, d = at(i, t0, z0), at(i + 1, t0, z0), at(i + 1, t1, z1), at(i, t1, z1)
            P += [a, b, c, a, c, d]
            C += [col] * 6
            o = out[0] * s[i] + out[2] * z[i]
            F += [o, o]
    end = np.clip(min(cols, key=lambda c: c.sum()) * 0.7, 0, 1)
    for i, sg in ((0, -1), (len(path) - 1, 1)):
        q = [at(i, t, zz) for t, zz, _ in ring]
        for j in range(1, m - 1):
            P += [q[0], q[j], q[j + 1]]
            C += [end] * 3
            F += [sg * t_[i]]
    P = np.array(P)
    tri = P.reshape(-1, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ok = np.linalg.norm(n, axis=1) > 1e-9
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n *= np.where((n * np.array(F)).sum(1) < 0, -1, 1)[:, None]
    k = np.repeat(ok, 3)
    return P[k], np.repeat(n, 3, 0)[k], np.array(C)[k]
