# Blender: writes a character .blend made by tools/meshview.py (edited or not) as a replacement the
# DLL loads from taz-hd\meshes\<buffer fingerprint>.bin.
# usage: blender -b <file.blend> -P tools/meshpack.py -- <out dir>
import bpy, struct, sys, os, json

outdir = sys.argv[sys.argv.index('--') + 1]
ob = bpy.data.objects['model']
batches, sources = json.loads(ob['batches']), json.loads(ob['sources'])
springs = json.loads(ob.get('springs', '[]'))
me = ob.data
me.calc_loop_triangles()  # keeps each corner's own normal, unlike triangulating the faces
groupname = {g.index: g.name for g in ob.vertex_groups}

def weights(v):
    ws = sorted(((g.weight, int(groupname[g.group][4:])) for g in v.groups if g.weight > 0 and groupname[g.group].startswith('bone')), reverse=True)[:3]
    total = sum(w for w, _ in ws) or 1
    return [(b, w / total) for w, b in ws]

bent = [me.attributes[k].data for k in ('bent_bone0', 'bent_bone1', 'bent_weight0', 'bent_weight1', *('bent_place%d' % k for k in range(6)))] if 'bent_bone0' in me.attributes else None
def places(v):  # per bone (tools/subdivide.py): where it alone puts the point, game axes
    b, w = (*bent[0][v.index].vector, *bent[1][v.index].vector), (*bent[2][v.index].vector, *bent[3][v.index].vector)
    ws = [(int(round(x)), y) for x, y in zip(b, w) if y > 0]
    ps = [(q.x, q.z, q.y) for q in (bent[4 + k][v.index].vector for k in range(6))][:len(ws)]
    return ws, ps + [(v.co.x, v.co.z, v.co.y)] * (6 - len(ps))

uv = me.uv_layers.active.data
col = me.attributes['col'].data if 'col' in me.attributes else None
def d3dcolor(li):
    if not col: return 0x7f7f7f7f
    r, g, b, a = (min(255, max(0, round(x * 255))) for x in col[li].color)
    return a << 24 | r << 16 | g << 8 | b
normal = me.corner_normals
tris = []  # (texbatch, bones, corners)
for t in me.loop_triangles:
    corners = []
    for li in reversed(t.loops):  # back to the game's winding
        v = me.vertices[me.loops[li].vertex_index]
        n = normal[li].vector
        ws, extra = places(v) if bent else (weights(v), ())
        corners.append(((v.co.x, v.co.z, v.co.y), ws, (n.x, n.z, n.y), (uv[li].uv.x, 1 - uv[li].uv.y), extra, d3dcolor(li)))
    bones = frozenset(b for c in corners for b, _ in c[1])
    tris.append((me.materials[t.material_index]['batch'], bones, corners))

# Groups: one texture and at most 16 bones each, filled with triangles sharing bones.
groups = []
for tb in sorted(set(t[0] for t in tris)):
    left = sorted((t for t in tris if t[0] == tb), key=lambda t: sorted(t[1]))
    while left:
        have, take, rest = set(), [], []
        for t in left:
            if len(have | t[1]) <= 16: have |= t[1]; take.append(t)
            else: rest.append(t)
        groups.append((tb, sorted(have), take))
        left = rest

# Each group's corners are shared where they match exactly; indices count from the group's first vertex.
verts, more, idx, gdata = bytearray(), bytearray(), [], bytearray()
nverts = 0
for tb, have, take in groups:
    reg = {b: i * 3 for i, b in enumerate(have)}
    local, first = {}, len(idx)
    for _, _, corners in take:
        for p, ws, n, t, extra, rgba in corners:
            w = [x for _, x in ws[:3]] + [0] * (3 - len(ws[:3]))
            bi = [reg[b] for b, _ in ws[:3]] + [0] * (4 - len(ws[:3]))
            v = struct.pack('<3f3f4B3fI2f', *p, *w, *bi, *n, rgba, *t)
            more_w = [x for _, x in ws[3:]] + [0] * (3 - len(ws[3:]))
            more_b = [reg[b] for b, _ in ws[3:]] + [0] * (3 - len(ws[3:]))
            x = b''.join(struct.pack('<3f', *q) for q in extra) + struct.pack('<6f', *more_w, *more_b) if extra else b''
            if v + x not in local:
                local[v + x] = len(local)
                verts += v
                more += x
            idx.append(local[v + x])
    assert len(local) < 65536, 'group too big for 16-bit indices'
    gdata += struct.pack('<6I16H', first, len(take), tb, len(have), nverts, len(local), *(have + [0] * (16 - len(have))))
    nverts += len(local)
head = struct.pack('<7IQ', 0x354d5a54 if bent else 0x334d5a54, len(batches), len(sources), len(springs), len(groups), nverts, len(idx), int(ob['hash'], 16))
body = b''.join(struct.pack('<3I', *b) for b in batches) + b''.join(struct.pack('<2H', *s) for s in sources)
body += b''.join(struct.pack('<I10f', s['parent'], *s['pivot'], *s['tip'], s['stiffness'], s['damping'], s['amount'], s['limit']) for s in springs)
os.makedirs(outdir, exist_ok=True)
path = os.path.join(outdir, ob['hash'] + '.bin')
open(path, 'wb').write(head + body + gdata + verts + more + struct.pack('<%dH' % len(idx), *idx))
print('packed %s: %d triangles, %d vertices in %d groups, %d springs' % (path, len(tris), nverts, len(groups), len(springs)))
