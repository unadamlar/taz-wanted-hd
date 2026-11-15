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

bent = [me.attributes[k].data for k in ('bent_bone', 'bent_weight', 'bent_place0', 'bent_place1', 'bent_place2')] if 'bent_bone' in me.attributes else None
def places(v):  # per bone (tools/subdivide.py, PERBONE): where it alone puts the point, game axes
    b, w = bent[0][v.index].vector, bent[1][v.index].vector
    ws = [(int(round(b[k])), w[k]) for k in range(3) if w[k] > 0]
    ps = [(q.x, q.z, q.y) for q in (bent[2 + k][v.index].vector for k in range(3)) ][:len(ws)]
    return ws, ps + [(v.co.x, v.co.z, v.co.y)] * (3 - len(ps))

uv = me.uv_layers.active.data
normal = me.corner_normals
tris = []  # (texbatch, bones, corners)
for t in me.loop_triangles:
    corners = []
    for li in reversed(t.loops):  # back to the game's winding
        v = me.vertices[me.loops[li].vertex_index]
        n = normal[li].vector
        ws, extra = places(v) if bent else (weights(v), ())
        corners.append(((v.co.x, v.co.z, v.co.y), ws, (n.x, n.z, n.y), (uv[li].uv.x, 1 - uv[li].uv.y), extra))
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
        for p, ws, n, t, extra in corners:
            w = [x for _, x in ws] + [0] * (3 - len(ws))
            bi = [reg[b] for b, _ in ws] + [0] * (4 - len(ws))
            v = struct.pack('<3f3f4B3fI2f', *p, *w, *bi, *n, 0x7f7f7f7f, *t)
            x = b''.join(struct.pack('<3f', *q) for q in extra)
            if v + x not in local:
                local[v + x] = len(local)
                verts += v
                more += x
            idx.append(local[v + x])
    assert len(local) < 65536, 'group too big for 16-bit indices'
    gdata += struct.pack('<6I16H', first, len(take), tb, len(have), nverts, len(local), *(have + [0] * (16 - len(have))))
    nverts += len(local)
head = struct.pack('<7IQ', 0x344d5a54 if bent else 0x334d5a54, len(batches), len(sources), len(springs), len(groups), nverts, len(idx), int(ob['hash'], 16))
body = b''.join(struct.pack('<3I', *b) for b in batches) + b''.join(struct.pack('<2H', *s) for s in sources)
body += b''.join(struct.pack('<I10f', s['parent'], *s['pivot'], *s['tip'], s['stiffness'], s['damping'], s['amount'], s['limit']) for s in springs)
os.makedirs(outdir, exist_ok=True)
path = os.path.join(outdir, ob['hash'] + '.bin')
open(path, 'wb').write(head + body + gdata + verts + more + struct.pack('<%dH' % len(idx), *idx))
print('packed %s: %d triangles, %d vertices in %d groups, %d springs' % (path, len(tris), nverts, len(groups), len(springs)))
