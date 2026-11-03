# Blender: builds a character from a DLL mesh capture (taz-hd\capture-NNN.bin) in its bind pose,
# textured from extracted/textures, with one vertex group per bone, and saves it as a .blend.
# usage: blender -b -P tools/meshview.py -- <capture.bin> <buffer index, biggest first> <out.blend>
import bpy, struct, sys, os
from collections import defaultdict

cap, which, out = sys.argv[sys.argv.index('--') + 1:][:3]
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'extracted', 'textures')
names = {}
for line in open(os.path.join(root, 'fingerprints.tsv')):
    h, n = line.rstrip('\n').split('\t')[:2]
    names.setdefault(int(h, 16), n)

b = open(cap, 'rb').read()
o, vbs, draws = 0, {}, []
while o < len(b):
    if struct.unpack_from('<I', b, o)[0] == ord('V'):
        _, i, n = struct.unpack_from('<3I', b, o)
        vbs[i] = [struct.unpack_from('<3f3f4B3fI2f', b, o + 12 + k * 52) for k in range(n // 52)]
        o += 12 + n
    else:
        _, i, ty, st, ct = struct.unpack_from('<5I', b, o)
        tex, = struct.unpack_from('<Q', b, o + 20)
        draws.append((i, ty, st, ct, tex, struct.unpack_from('<384f', b, o + 28)))
        o += 28 + 1536
vb = sorted(vbs, key=lambda k: -len(vbs[k]))[int(which)]
V = vbs[vb]

# Bones: the same skinning matrix in different batches is the same bone.
bones = {}
def bone(c, reg):
    m = tuple(round(x, 4) for x in c[reg * 4:reg * 4 + 12])
    return bones.setdefault(m, len(bones))

verts, vindex, faces, uvs, mats, groups = [], {}, [], [], [], defaultdict(dict)
texs = []
for i, ty, st, ct, tex, c in draws:
    if i != vb or not tex: continue  # untextured draws are the outline pass
    if tex not in texs: texs.append(tex)
    tri = [(st + t, st + t + 1, st + t + 2)[::(-1 if t & 1 else 1)] if ty == 5 else (st + 3 * t, st + 3 * t + 1, st + 3 * t + 2) for t in range(ct)]
    for a, bb, cc in tri:
        if len({V[a][:3], V[bb][:3], V[cc][:3]}) < 3: continue
        f, fuv = [], []
        for k in (a, bb, cc):
            p = V[k][:3]
            if p not in vindex:
                vindex[p] = len(verts)
                verts.append((p[0], p[2], p[1]))
            vi = vindex[p]
            for s in range(3):
                if V[k][3 + s] > 0: groups[bone(c, V[k][6 + s])][vi] = V[k][3 + s]
            f.append(vi)
            fuv.append((V[k][14], 1 - V[k][15]))
        faces.append(f[::-1])  # swapping y and z flips the winding
        uvs += fuv[::-1]
        mats.append(texs.index(tex))

bpy.ops.wm.read_factory_settings(use_empty=True)
me = bpy.data.meshes.new('taz')
me.from_pydata(verts, [], faces)
uv = me.uv_layers.new()
for k, l in enumerate(me.loops): uv.data[k].uv = uvs[k]
for k, p in enumerate(me.polygons): p.material_index, p.use_smooth = mats[k], True
for tex in texs:
    m = bpy.data.materials.new(names.get(tex, '%016x' % tex))
    m.use_nodes = True
    img = m.node_tree.nodes.new('ShaderNodeTexImage')
    path = os.path.join(root, names.get(tex, ''))
    if os.path.isfile(path): img.image = bpy.data.images.load(path)
    bsdf = m.node_tree.nodes['Principled BSDF']
    m.node_tree.links.new(img.outputs['Color'], bsdf.inputs['Base Color'])
    m.node_tree.links.new(img.outputs['Alpha'], bsdf.inputs['Alpha'])
    me.materials.append(m)
ob = bpy.data.objects.new('taz', me)
bpy.context.scene.collection.objects.link(ob)
for g, ws in sorted(groups.items()):
    vg = ob.vertex_groups.new(name='bone%02d' % g)
    for vi, w in ws.items(): vg.add([vi], w, 'REPLACE')
print('mesh: %d vertices, %d triangles, %d bones, textures %s' % (len(verts), len(faces), len(bones), [names.get(t, t) for t in texs]))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
