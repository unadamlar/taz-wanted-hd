"""Real geometry for what the game paints on flat cards or builds from very few faces. Runs inside Blender."""
import collections, math, struct
import bmesh, bpy
import numpy as np
from mathutils import Vector, geometry

CASES = {1: "LT", 2: "TR", 3: "LR", 4: "RB", 5: "LTRB", 6: "TB", 7: "LB", 8: "BL", 9: "BT", 10: "TRBL", 11: "BR", 12: "RL",
         13: "RT", 14: "TL"}


def capture(paths, wanted):
    """World draws of the captures using the wanted textures, or sharing a placed object's transform with one."""
    found = []
    for path in paths:
        b = open(path, "rb").read()
        _, nrs, ntss = struct.unpack_from("<3I", b)
        o, frame = 12 + 4 * nrs + 4 * ntss, []
        while o < len(b):
            if struct.unpack_from("<I", b, o)[0] == ord("F"):
                found += _keep(frame, wanted)
                frame, o = [], o + 12
                continue
            _, _, api, kind, count, shader, stride, nv, nidx = struct.unpack_from("<9I", b, o)
            q = o + 64 + 320 + 24 + 4 * nrs + 12 * ntss + (1536 if shader & 0x80000000 else 0)
            if not api and shader == 0x152 and stride == 36 and kind in (4, 5):
                frame.append((struct.unpack_from("<Q", b, o + 48)[0], struct.unpack_from("<16f", b, o + 64), kind, count, b[q:q + nv * 36]))
            o = q + nv * stride + 4 * nidx
        found += _keep(frame, wanted)
    return found


def _identity(w):
    return all(abs(w[i] - (i % 5 == 0)) < 1e-6 for i in range(16))


def _keep(frame, wanted):
    placed = {tuple(np.round(w, 3)) for h, w, *_ in frame if h in wanted and not _identity(w)}
    return [d for d in frame if d[0] and (d[0] in wanted or tuple(np.round(d[1], 3)) in placed)]


def key_of(verts):
    """FNV-1a 64 over each vertex's position and uv: look.c computes the same on the game's buffer."""
    h = 0xcbf29ce484222325
    for at in range(0, len(verts), 36):
        for c in verts[at:at + 12] + verts[at + 28:at + 36]:
            h = ((h ^ c) * 0x100000001b3) & 0xffffffffffffffff
    return h


def triangles(kind, count, verts):
    """(T, 3, 3) positions, (T, 3, 2) uvs and (T, 3, 3) colours, as world draws show them (2x), of a list or strip draw."""
    v = np.frombuffer(verts, np.float32).reshape(-1, 9)
    if kind == 4:
        i = np.arange(count * 3).reshape(-1, 3)
    else:
        i = np.stack([np.arange(count), np.arange(count) + 1, np.arange(count) + 2], 1)
        i[1::2, :2] = i[1::2, 1::-1]
    i = i[[len({tuple(v[k, :3]) for k in f}) == 3 for f in i]]
    rgb = np.frombuffer(verts, np.uint8).reshape(-1, 36)[:, [26, 25, 24]]
    return v[i][..., :3].astype(np.float64), v[i][..., 7:].astype(np.float64), np.minimum(rgb[i] / 255 * 2, 1)


def models(draws, card_textures):
    """Each distinct model once: {frozenset of draw keys: draws}. A placed object is everything at one transform."""
    groups = collections.defaultdict(dict)
    for d in draws:
        h, w = d[0], d[1]
        groups[(h if _identity(w) else 0, tuple(np.round(w, 3)))][key_of(d[4])] = d
    return {frozenset(g): list(g.values()) for g in groups.values() if any(d[0] in card_textures or not _identity(d[1]) for d in g.values())}


def _simplify(r, tol):
    c = np.vstack([r, r[:1]])
    far = int(np.argmax(((r - r[0]) ** 2).sum(1)))
    keep, stack = {0, far}, [(0, far), (far, len(r))]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        d = c[j] - c[i]
        e = np.abs(d[0] * (c[i + 1:j, 1] - c[i, 1]) - d[1] * (c[i + 1:j, 0] - c[i, 0])) / max(np.hypot(*d), 1e-9)
        k = int(e.argmax())
        if e[k] > tol:
            keep.add(i + 1 + k)
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return r[sorted(keep)]


def outlines(alpha, tol, min_area):
    """Closed outlines of alpha > 0.5 by marching squares, in texels; the inside is to the right of travel on screen."""
    a = np.pad(alpha, 1).astype(np.float64)
    on = a > 0.5
    code = on[:-1, :-1] * 1 | on[:-1, 1:] * 2 | on[1:, 1:] * 4 | on[1:, :-1] * 8

    def at(y, x, e):
        y0, x0, y1, x1 = {"T": (y, x, y, x + 1), "R": (y, x + 1, y + 1, x + 1), "B": (y + 1, x, y + 1, x + 1), "L": (y, x, y + 1, x)}[e]
        t = (0.5 - a[y0, x0]) / (a[y1, x1] - a[y0, x0])
        return (x0 + t * (x1 - x0) - 1, y0 + t * (y1 - y0) - 1)

    step = {}
    for y, x in zip(*np.nonzero((code > 0) & (code < 15))):
        c = CASES[int(code[y, x])]
        for k in range(0, len(c), 2):
            step[at(y, x, c[k])] = at(y, x, c[k + 1])
    rings = []
    while step:
        p = next(iter(step))
        ring = []
        while p in step:
            ring.append(p)
            p = step.pop(p)
        r = np.array(ring)
        if len(r) > 3 and abs(np.sum(r[:, 0] * np.roll(r[:, 1], -1) - np.roll(r[:, 0], -1) * r[:, 1])) / 2 >= min_area:
            r = _simplify(r, tol)
            if len(r) > 2:
                rings.append(r)
    return rings


def plate(alpha, size, depth, tol=1.0, min_area=8.0):
    """The opaque shape of a cut-out as a solid: corners (u, v, side offset) and normals in (size x, size y, 1) units.
    Face normals lean towards the outline, so a thin bar shades round without extra triangles."""
    h, w = alpha.shape
    rings = outlines(alpha, tol, min_area)
    xy = np.concatenate(rings)
    scale = np.array([size[0] / w, size[1] / h])
    out, edges, at = [], [], 0
    for r in rings:
        d = (np.roll(r, -1, 0) - r) * scale
        e = np.stack([-d[:, 1], d[:, 0]], 1) / np.maximum(np.hypot(*d.T)[:, None], 1e-9)
        o = e + np.roll(e, 1, 0)
        out.append(o / np.maximum(np.hypot(*o.T)[:, None], 1e-9))
        edges += [(at + i, at + (i + 1) % len(r)) for i in range(len(r))]
        at += len(r)
    out = np.concatenate(out)
    v, _, faces, orig, *_ = geometry.delaunay_2d_cdt([Vector(q) for q in xy.tolist()], edges, [], 0, 1e-4)
    v = np.array([tuple(q) for q in v])
    t = np.array([f for f in faces if len(f) == 3])
    c = np.rint(v[t].mean(1)).astype(int)
    t = t[alpha[c[:, 1].clip(0, h - 1), c[:, 0].clip(0, w - 1)] > 0.5]
    vo = np.array([out[o[0]] if len(o) else (0.0, 0.0) for o in orig])
    uv = (v + 0.5) / [w, h]
    lean = 0.8
    parts = []
    for z, flip in ((depth, False), (-depth, True)):
        f = t[:, ::-1] if flip else t
        n = np.column_stack([vo[f.ravel()] * lean, np.full(f.size, math.copysign(0.6, z))])
        parts.append((np.column_stack([uv[f.ravel()], np.full(f.size, z)]), n))
    at = 0
    for r in rings:
        i = at + np.arange(len(r))
        j = at + (np.arange(len(r)) + 1) % len(r)
        at += len(r)
        order = ((i, depth), (j, depth), (j, -depth), (i, depth), (j, -depth), (i, -depth))
        wall = np.stack([np.column_stack([(xy[k] + 0.5) / [w, h], np.full(len(k), z)]) for k, z in order], 1)
        nor = np.stack([np.column_stack([out[k], np.zeros(len(k))]) for k, _ in order], 1)
        parts.append((wall.reshape(-1, 3), nor.reshape(-1, 3)))
    return np.concatenate([x for x, _ in parts]), np.concatenate([x for _, x in parts])


def link(alpha, size, sides=7, steps=22):
    """One round chain link with the painted link's outline: corners (u, v, side offset) and normals, as plate()."""
    h, w = alpha.shape
    row, col = alpha[h // 2] > 0.5, alpha[:, w // 2] > 0.5
    xs, ys = np.nonzero(row)[0], np.nonzero(col)[0]
    bar = np.argmin(row[xs[0]:]) * size[0] / w
    r = bar / 2
    ax = (xs[-1] - xs[0] + 1) * size[0] / w / 2 - r
    ay = (ys[-1] - ys[0] + 1) * size[1] / h / 2 - r
    ctr = np.array([(xs[0] + xs[-1] + 1) / 2 * size[0] / w, (ys[0] + ys[-1] + 1) / 2 * size[1] / h])
    straight = max(ay - ax, 0)
    t = (np.arange(steps) + 0.5) / steps * 2 * np.pi
    rad = np.stack([np.cos(t), np.sin(t)], 1)
    path = ctr + rad * ax + np.stack([np.zeros(steps), np.sign(rad[:, 1]) * straight], 1)
    spin = np.arange(sides) * 2 * np.pi / sides
    spoke = np.concatenate([rad[:, None] * np.cos(spin)[None, :, None], np.sin(spin)[None, :, None] * np.ones((steps, sides, 1))], 2)
    ring = np.concatenate([np.broadcast_to(path[:, None], (steps, sides, 2)), np.zeros((steps, sides, 1))], 2) + r * spoke
    I, J = np.arange(steps)[:, None], np.arange(sides)[None]
    tri = [(I, J), ((I + 1) % steps, J), ((I + 1) % steps, (J + 1) % sides), (I, J), ((I + 1) % steps, (J + 1) % sides), (I, (J + 1) % sides)]
    p = np.stack([ring[a, b] for a, b in tri], 2).reshape(-1, 3)
    n = np.stack([spoke[a, b] for a, b in tri], 2).reshape(-1, 3)
    return p / [size[0], size[1], 1], n


def on_card(P, N, pos, uv, col, size):
    """Moves plate() corners onto a game card given as triangles; the texture repeats where the card's uvs do."""
    parts = []
    for k in range(int(math.floor(uv[..., 0].min() + 1e-6)), int(math.ceil(uv[..., 0].max() - 1e-6))):
        q = P[:, :2] + [k, 0]
        a, e1, e2 = uv[:, 0], uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
        det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        rel = q[:, None] - a[None]
        l1 = (rel[..., 0] * e2[:, 1] - rel[..., 1] * e2[:, 0]) / det
        l2 = (e1[:, 0] * rel[..., 1] - e1[:, 1] * rel[..., 0]) / det
        t = np.minimum(np.minimum(l1, l2), 1 - l1 - l2).argmax(1)
        ix = np.arange(len(q))
        A, B, C = pos[t, 0], pos[t, 1], pos[t, 2]
        du = ((B - A) * e2[t, 1, None] - (C - A) * e1[t, 1, None]) / det[t, None]
        dv = ((C - A) * e1[t, 0, None] - (B - A) * e2[t, 0, None]) / det[t, None]
        side = np.cross(du, dv)
        side /= np.linalg.norm(side, axis=1, keepdims=True)
        p = A + (B - A) * l1[ix, t, None] + (C - A) * l2[ix, t, None] + side * P[:, 2:]
        F = np.stack([du / size[0], dv / size[1], side], 2)
        n = (np.linalg.inv(F).transpose(0, 2, 1) @ N[..., None])[..., 0]
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        c = col[t, 0] + (col[t, 1] - col[t, 0]) * l1[ix, t, None] + (col[t, 2] - col[t, 0]) * l2[ix, t, None]
        parts.append((p, n, q, np.clip(c, 0, 1)))
    return [np.concatenate(x) for x in zip(*parts)]


def rounded(pos, uv, tex, levels=2):
    """A low-poly model subdivided smooth, resized to its old bounds: corner positions, normals, uvs, texture index."""
    vs, inv = np.unique(np.round(pos.reshape(-1, 3), 2), axis=0, return_inverse=True)
    me = bpy.data.meshes.new("solid_soft")
    me.from_pydata(vs.tolist(), [], inv.reshape(-1, 3).tolist())
    layer = me.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", uv.reshape(-1).astype(np.float32))
    me.polygons.foreach_set("material_index", tex.astype(np.int32))
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.join_triangles(bm, faces=bm.faces, cmp_uvs=True, cmp_materials=True, angle_face_threshold=math.radians(35),
                             angle_shape_threshold=math.radians(70))
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()
    ob = bpy.data.objects.new("solid_soft", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("s", "SUBSURF").levels = levels
    dg = bpy.context.evaluated_depsgraph_get()
    e = ob.evaluated_get(dg).to_mesh()
    e.calc_loop_triangles()
    n = len(e.loop_triangles)
    lt = np.empty(n * 3, np.int32); e.loop_triangles.foreach_get("loops", lt)
    mi = np.empty(n, np.int32); e.loop_triangles.foreach_get("material_index", mi)
    vi = np.empty(len(e.loops), np.int32); e.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(e.vertices) * 3, np.float32); e.vertices.foreach_get("co", co)
    cn = np.empty(len(e.loops) * 3, np.float32); e.corner_normals.foreach_get("vector", cn)
    cu = np.empty(len(e.loops) * 2, np.float32); e.uv_layers[0].data.foreach_get("uv", cu)
    p = co.reshape(-1, 3)[vi[lt]].astype(np.float64)
    lo, hi, plo, phi = vs.min(0), vs.max(0), p.min(0), p.max(0)
    p = (p - (plo + phi) / 2) * (hi - lo) / np.maximum(phi - plo, 1e-6) + (lo + hi) / 2
    out = p, cn.reshape(-1, 3)[lt], cu.reshape(-1, 2)[lt], mi.repeat(3)
    ob.evaluated_get(dg).to_mesh_clear()
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    return out
