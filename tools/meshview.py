# Blender: builds a character from DLL mesh captures (taz-hd\capture-NNN.bin) in its bind pose,
# textured from extracted/textures, with one vertex group per bone, and saves it as a .blend that
# tools/meshpack.py turns back into a replacement for the game.
# usage: blender -b -P tools/meshview.py -- <out.blend> <buffer index, biggest first, or fingerprint> <capture.bin>...
# Bones are told apart by their matrices in all the given captures (same scene, different frames).
import bpy, struct, sys, os, json
from collections import defaultdict

args = sys.argv[sys.argv.index('--') + 1:]
out, which, caps = args[0], args[1], args[2:]
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'extracted', 'textures')
names = {}
for line in open(os.path.join(root, 'fingerprints.tsv')):
    h, n = line.rstrip('\n').split('\t')[:2]
    names.setdefault(int(h, 16), n)

def load(path):
    b = open(path, 'rb').read()
    o, vbs, draws = 0, {}, []
    while o < len(b):
        if struct.unpack_from('<I', b, o)[0] == ord('V'):
            _, i, n = struct.unpack_from('<3I', b, o)
            vbs[i] = b[o + 12:o + 12 + n]
            o += 12 + n
        else:
            _, i, ty, st, ct = struct.unpack_from('<5I', b, o)
            tex, = struct.unpack_from('<Q', b, o + 20)
            draws.append((i, ty, st, ct, tex, struct.unpack_from('<384f', b, o + 28)))
            o += 28 + 1536
    return vbs, draws

def fnv(raw):
    h = 0xcbf29ce484222325
    for x in raw: h = ((h ^ x) * 0x100000001b3) & 0xffffffffffffffff
    return h

frames = [load(c) for c in caps]
vbs, draws = frames[0]
vb = next(k for k in vbs if fnv(vbs[k]) == int(which, 16)) if len(which) == 16 else sorted(vbs, key=lambda k: -len(vbs[k]))[int(which)]
raw = vbs[vb]
h = fnv(raw)
V = [struct.unpack_from('<3f3f4B3fI2f', raw, k * 52) for k in range(len(raw) // 52)]
passes = [[d for d in f[1] if d[0] == vb] for f in frames]  # same buffer address in every frame of one run
# The lit pass comes first; the outline pass, or a second copy of the character (two players, crowds), repeats
# its batches: keep the first run. Batches can be untextured: most cutscene Taz copies colour by vertex.
passes = [next((p[:k] for k in range(1, len(p)) if p[k][1:4] == p[0][1:4]), p) for p in passes]
batches = [(d[2], d[3], d[1]) for d in passes[0]]
assert all([(d[2], d[3], d[1]) for d in p] == batches for p in passes), 'captures draw different batches'

bones, sources, palette, merged = {}, [], defaultdict(dict), set()
def bone(bi, reg):
    key = tuple(round(x, 3) for p in passes for x in p[bi][5][reg * 4:reg * 4 + 12])
    if key not in bones:
        bones[key] = len(bones)
        sources.append((bi, reg))
    palette[bi][reg] = bones[key]
    if list(palette[bi].values()).count(bones[key]) > 1: merged.add(bones[key])  # two bones moved alike in every frame given
    return bones[key]

verts, vindex, faces, uvs, nors, cols, mats, groups, texs = [], {}, [], [], [], [], [], defaultdict(dict), []
for bi, (i, ty, st, ct, tex, c) in enumerate(passes[0]):
    if tex not in [t for t, _ in texs]: texs.append((tex, bi))
    tri = [(st + t, st + t + 1, st + t + 2)[::(-1 if t & 1 else 1)] if ty == 5 else (st + 3 * t, st + 3 * t + 1, st + 3 * t + 2) for t in range(ct)]
    for a, b, cc in tri:
        if len({V[a][:3], V[b][:3], V[cc][:3]}) < 3: continue
        f = []
        for k in (cc, b, a):  # swapping y and z flips the winding
            p = V[k][:3]
            if p not in vindex:
                vindex[p] = len(verts)
                verts.append((p[0], p[2], p[1]))
            vi = vindex[p]
            for s in range(3):
                if V[k][3 + s] > 0: groups[bone(bi, V[k][6 + s])][vi] = V[k][3 + s]
            f.append(vi)
            uvs.append((V[k][14], 1 - V[k][15]))
            nors.append((V[k][10], V[k][12], V[k][11]))
            cols.append([(V[k][13] >> s & 255) / 255 for s in (16, 8, 0, 24)])  # D3DCOLOR ARGB
        faces.append(f)
        mats.append([t for t, _ in texs].index(tex))

bpy.ops.wm.read_factory_settings(use_empty=True)
me = bpy.data.meshes.new('model')
me.from_pydata(verts, [], faces)
uv = me.uv_layers.new()
for k in range(len(me.loops)): uv.data[k].uv = uvs[k]
for k, p in enumerate(me.polygons): p.material_index, p.use_smooth = mats[k], True
me.normals_split_custom_set(nors)
me.color_attributes.new('col', 'FLOAT_COLOR', 'CORNER').data.foreach_set('color', [x for c in cols for x in c])
for tex, bi in texs:
    m = bpy.data.materials.new(names.get(tex, '%016x' % tex))
    m['batch'] = bi  # the game binds this texture for batch bi; the replacement borrows it from there
    m.use_nodes = True
    img = m.node_tree.nodes.new('ShaderNodeTexImage')
    path = os.path.join(root, names.get(tex, ''))
    if os.path.isfile(path): img.image = bpy.data.images.load(path)
    bsdf = m.node_tree.nodes['Principled BSDF']
    m.node_tree.links.new(img.outputs['Color'], bsdf.inputs['Base Color'])
    m.node_tree.links.new(img.outputs['Alpha'], bsdf.inputs['Alpha'])
    me.materials.append(m)
ob = bpy.data.objects.new('model', me)
bpy.context.scene.collection.objects.link(ob)
for g in range(len(sources)):
    vg = ob.vertex_groups.new(name='bone%02d' % g)
    for vi, w in groups[g].items(): vg.add([vi], w, 'REPLACE')
ob['hash'] = '%016x' % h
ob['batches'] = json.dumps(batches)
ob['sources'] = json.dumps(sources)
ob['poses'] = json.dumps([[[round(x, 4) for x in p[bi][5][reg * 4:reg * 4 + 12]] for bi, reg in sources] for p in passes])  # each frame's bone matrices, for tools/subdivide.py
print('mesh: %d vertices, %d triangles, %d bones, %d batches, buffer %016x' % (len(verts), len(faces), len(sources), len(batches), h))
if merged: print('mesh: WARNING %d bones stand for several; capture frames with more varied poses' % len(merged))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
