# Blender: gives Taz rounder fingers. Replaces each hand's six-sided fingers and thumb in a .blend from
# tools/meshview.py with round, tapered ones with knuckles, on the same bones, blending weights across
# the joints so they bend smoothly. What is left of the old finger roots is tucked inside the new ones.
# usage: blender -b <taz.blend> -P tools/hands.py -- <out.blend>
import bpy, bmesh, sys, os, math
from collections import defaultdict, Counter
from mathutils import Vector

out = sys.argv[sys.argv.index('--') + 1]
SIDES = 10
ob = bpy.data.objects['model']
me = ob.data
gname = {g.index: g.name for g in ob.vertex_groups}
gindex = {g.name: g.index for g in ob.vertex_groups}

def top(v):
    return gname[max(v.groups, key=lambda g: g.weight).group]

def smoothstep(a, b, x):
    t = min(1, max(0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)

def hand_bones(side):
    # Bones owning vertices out past the wrist: palm, thumb (points forward, -y) and three fingers.
    pts = defaultdict(list)
    for v in me.vertices:
        if side * v.co.x > 150: pts[top(v)].append(v.co.copy())
    cen = {b: sum(p, Vector()) / len(p) for b, p in pts.items()}
    thumb = sorted((b for b in cen if cen[b].y < -8), key=lambda b: -cen[b].y)
    rest = [b for b in cen if b not in thumb]
    palm = min(rest, key=lambda b: side * cen[b].x)
    fingers = sorted((b for b in rest if b != palm), key=lambda b: cen[b].y)
    chains = [sorted(fingers[i:i + 2], key=lambda b: side * cen[b].x) for i in range(0, len(fingers), 2)]
    assert len(thumb) == 2 and len(chains) == 3 and all(len(c) == 2 for c in chains), (side, cen)
    return palm, [thumb] + chains

bm = bmesh.new()
bm.from_mesh(me)
deform = bm.verts.layers.deform.active
uvl = bm.loops.layers.uv.active
new_faces = []

def build(side):
    palm, chains = hand_bones(side)
    allb = {gindex[b] for c in chains for b in c}
    def owner(v):
        return max(v[deform].items(), key=lambda kv: kv[1])[0]
    centres, shapes = {}, []
    for prox, dist in chains:
        ps = [v.co for v in bm.verts if owner(v) in (gindex[prox], gindex[dist]) and side * v.co.x > 140]
        centres[prox] = sum(ps, Vector()) / len(ps)
    for prox, dist in chains:
        gap = min([(centres[prox] - centres[q]).yz.length for q in centres if q not in (prox, chains[0][0])] + [99])  # to the next finger (the thumb is apart)
        P = [v.co.copy() for v in bm.verts if owner(v) == gindex[prox] and side * v.co.x > 140]
        D = [v.co.copy() for v in bm.verts if owner(v) == gindex[dist] and side * v.co.x > 140]
        axis = sum(D, Vector()) / len(D) - sum(P, Vector()) / len(P)
        k = max(range(3), key=lambda i: abs(axis[i]))
        d = Vector([0, 0, 0]); d[k] = math.copysign(1, axis[k])
        up = Vector((0, 0, 1))
        across = d.cross(up)
        j1 = min(p.dot(d) for p in P); j2 = min(p.dot(d) for p in D); tip = max(p.dot(d) for p in D)
        c = sum(P + D, Vector()) / len(P + D)
        c -= d * c.dot(d)
        # Thickness: the old knuckle ring's radius (its corners sit on a circle; the median skips odd points).
        rs = sorted(((p - c) - d * (p - c).dot(d)).length for p in P)
        R = min(rs[len(rs) // 2], 6.0) * 1.08  # in game the old fingers look puffier than their corners: smoothing rounds them outwards
        wide = min(R, 0.5 * gap)  # side by side fingers keep a gap
        # Texture coordinates from the nearest point of the old finger, material from its faces.
        loops = [(l.vert.co.copy(), l[uvl].uv.copy()) for f in bm.faces for l in f.loops if owner(l.vert) in (gindex[prox], gindex[dist]) and side * l.vert.co.x > 140]
        mat = Counter(f.material_index for f in bm.faces if any(owner(v) == gindex[prox] for v in f.verts)).most_common(1)[0][0]
        def uv_at(p):
            return min(loops, key=lambda q: (q[0] - p).length_squared)[1]
        def radius(x, j1=j1, j2=j2, tip=tip, R=R):  # out of the palm, a knuckle, a gentle taper, a second knuckle, a rounded tip
            r = R * (0.72 + 0.28 * smoothstep(j1 - 5, j1 + 1, x))
            r *= 1 - 0.15 * smoothstep(j1, tip, x)
            r *= 1 + 0.06 * math.exp(-((x - (j1 + 1.5)) / 2.0) ** 2) + 0.05 * math.exp(-((x - j2) / 1.8) ** 2)
            dome = 1.3 * R
            u = (x - (tip - dome)) / dome
            if u > 0: r *= max(0, 1 - u ** 2.2) ** 0.55
            return r
        def weights(x, palm=palm, prox=prox, dist=dist, j1=j1, j2=j2):
            t1, t2 = smoothstep(j1 - 2, j1 + 2, x), smoothstep(j2 - 2, j2 + 2, x)
            return {gindex[palm]: 1 - t1, gindex[prox]: t1 * (1 - t2), gindex[dist]: t1 * t2}
        dome = 1.3 * R
        n = int((tip - dome - (j1 - 5)) / 2)
        xs = [j1 - 5 + i * (tip - dome - (j1 - 5)) / n for i in range(n + 1)] + [tip - dome + dome * (i / 6) ** 0.7 for i in range(1, 6)]
        rings = []
        for x in xs:
            r = radius(x)
            ring = []
            for s in range(SIDES):
                ang = 2 * math.pi * s / SIDES
                p = c + d * x + across * (r * wide / R * math.cos(ang)) + up * (r * math.sin(ang))
                v = bm.verts.new(p)
                for g, w in weights(x).items():
                    if w > 1e-3: v[deform][g] = w
                ring.append(v)
            rings.append(ring)
        tipv = bm.verts.new(c + d * tip)
        tipv[deform][gindex[dist]] = 1
        base = bm.verts.new(c + d * (j1 - 5))
        base[deform][gindex[palm]] = 1
        faces = []
        for r0, r1 in zip(rings, rings[1:]):
            for s in range(SIDES):
                faces.append(bm.faces.new((r0[s], r0[(s + 1) % SIDES], r1[(s + 1) % SIDES], r1[s])))
        for s in range(SIDES):
            faces.append(bm.faces.new((rings[-1][s], rings[-1][(s + 1) % SIDES], tipv)))
            faces.append(bm.faces.new((rings[0][(s + 1) % SIDES], rings[0][s], base)))
        for f in faces:
            f.material_index, f.smooth = mat, True
            for l in f.loops: l[uvl].uv = uv_at(l.vert.co)
        new_faces.extend(faces)
        shapes.append((gindex[prox], gindex[dist], c, d, across, up, radius, wide / R, weights))
    # Remove the old fingers, then close the palm where they were.
    old = [f for f in bm.faces if f not in set(new_faces) and all(owner(v) in allb for v in f.verts)]
    bmesh.ops.delete(bm, geom=old, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    # What is left of the old finger roots tucks inside the new fingers.
    fresh = {v for f in new_faces for v in f.verts}
    for gp, gd, c, d, across, up, radius, squash, weights in shapes:
        for v in bm.verts:
            if v in fresh or owner(v) not in (gp, gd): continue
            off = v.co - c
            x = off.dot(d)
            u, w = off.dot(across) / squash, off.dot(up)
            r = math.hypot(u, w)
            lim = radius(x) * 0.8
            if r > lim: v.co = c + d * x + (across * u * squash + up * w) * (lim / r)
            for g in list(v[deform].keys()): del v[deform][g]
            for g, wt in weights(x).items():
                if wt > 1e-3: v[deform][g] = wt
    edges = [e for e in bm.edges if e.is_boundary and all(side * v.co.x > 140 for v in e.verts)]
    filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)['faces']
    for f in filled: f.smooth = True
    new_faces.extend(filled)

for side in (1, -1):
    build(side)
bmesh.ops.recalc_face_normals(bm, faces=new_faces)
bm.to_mesh(me)
me.update()
print('hands: %d vertices, %d faces' % (len(me.vertices), len(me.polygons)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
