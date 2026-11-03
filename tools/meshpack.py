# Blender: writes a character .blend made by tools/meshview.py (edited or not) as a replacement the
# DLL loads from taz-hd\meshes\<buffer fingerprint>.bin.
# usage: blender -b <file.blend> -P tools/meshpack.py -- <out dir>
import bpy, bmesh, struct, sys, os, json

outdir = sys.argv[sys.argv.index('--') + 1]
ob = bpy.data.objects['model']
batches, sources = json.loads(ob['batches']), json.loads(ob['sources'])
springs = json.loads(ob.get('springs', '[]'))
bm = bmesh.new()
bm.from_mesh(ob.data)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
me = bpy.data.meshes.new('packed')
bm.to_mesh(me)
groupname = {g.index: g.name for g in ob.vertex_groups}

def weights(v):
    ws = sorted(((g.weight, int(groupname[g.group][4:])) for g in v.groups if g.weight > 0 and groupname[g.group].startswith('bone')), reverse=True)[:3]
    total = sum(w for w, _ in ws) or 1
    return [(b, w / total) for w, b in ws]

uv = me.uv_layers.active.data
tris = []  # (texbatch, bones, corners)
for p in me.polygons:
    corners = []
    for li in reversed(p.loop_indices):  # back to the game's winding
        l = me.loops[li]
        v = me.vertices[l.vertex_index]
        n = me.corner_normals[li].vector
        corners.append(((v.co.x, v.co.z, v.co.y), weights(v), (n.x, n.z, n.y), (uv[li].uv.x, 1 - uv[li].uv.y)))
    bones = frozenset(b for c in corners for b, _ in c[1])
    tris.append((ob.data.materials[p.material_index]['batch'], bones, corners))

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

verts, gdata = bytearray(), bytearray()
first = 0
for tb, have, take in groups:
    reg = {b: i * 3 for i, b in enumerate(have)}
    for _, _, corners in take:
        for p, ws, n, t in corners:
            w = [x for _, x in ws] + [0] * (3 - len(ws))
            idx = [reg[b] for b, _ in ws] + [0] * (4 - len(ws))
            verts += struct.pack('<3f3f4B3fI2f', *p, *w, *idx, *n, 0x7f7f7f7f, *t)
    gdata += struct.pack('<4I16H', first, len(take), tb, len(have), *(have + [0] * (16 - len(have))))
    first += len(take) * 3
head = struct.pack('<6IQ', 0x324d5a54, len(batches), len(sources), len(springs), len(groups), first, int(ob['hash'], 16))
body = b''.join(struct.pack('<3I', *b) for b in batches) + b''.join(struct.pack('<2H', *s) for s in sources)
body += b''.join(struct.pack('<I10f', s['parent'], *s['pivot'], *s['tip'], s['stiffness'], s['damping'], s['amount'], s['limit']) for s in springs)
os.makedirs(outdir, exist_ok=True)
path = os.path.join(outdir, ob['hash'] + '.bin')
open(path, 'wb').write(head + body + gdata + verts)
print('packed %s: %d triangles in %d groups, %d springs' % (path, len(tris), len(groups), len(springs)))
