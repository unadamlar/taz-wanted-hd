# Blender: makes a character's surface dense and smooth (Catmull-Clark), so its outline stays round up
# close. Bone weights, springs, shading normals and UVs are blended over the new points (UVs linearly, so
# no texture swatch bleeds into its neighbour). What smoothing would spoil keeps its exact shape: folds
# sharper than 60 degrees (teeth, claws, hair spikes, lips, ear rims), open edges where one part tucks
# into another (no gaps), and the painted details with the faces around them (the eyes, and whatever is
# painted black: brows, eye rims). Smoothing also shrinks a coarse model (thin arms get thinner), so each
# original point is put back where it was and the new points between get the same correction, blended.
# usage: blender -b <file.blend> -P tools/subdivide.py -- <out.blend> [levels, default 2]
import bpy, sys, os

args = sys.argv[sys.argv.index('--') + 1:]
out, levels = args[0], int(args[1]) if len(args) > 1 else 2
ob = bpy.data.objects['model']
me = ob.data
n = len(me.vertices)
uv = me.uv_layers.active.data
pixels = {}

def painted_black(p):  # a black line painted on a lighter texture, under the face's middle
    img = next((nd.image for nd in me.materials[p.material_index].node_tree.nodes if nd.type == 'TEX_IMAGE' and nd.image), None)
    if not img or not img.size[0]: return False
    if img.name not in pixels:
        px = img.pixels[:]
        dark = [max(px[k:k + 3]) < 0.15 for k in range(0, len(px), 4)]
        pixels[img.name] = (img.size[0], img.size[1], dark, sum(dark) < 0.3 * len(dark))
    w, h, dark, lines = pixels[img.name]
    u = sum(uv[li].uv.x for li in p.loop_indices) / p.loop_total % 1
    v = sum(uv[li].uv.y for li in p.loop_indices) / p.loop_total % 1
    return lines and dark[min(h - 1, int(v * h)) * w + min(w - 1, int(u * w))]

faces = [[] for _ in me.edges]
for p in me.polygons:
    for li in p.loop_indices: faces[me.loops[li].edge_index].append(p.index)
detail = [('eyeblink' in me.materials[p.material_index].name or painted_black(p)) for p in me.polygons]
dv = {v for p, d in zip(me.polygons, detail) if d for v in p.vertices}
detail = [any(v in dv for v in p.vertices) for p in me.polygons]
crease = [1.0 if any(detail[i] for i in f) or len(f) == 2 and me.polygons[f[0]].normal.dot(me.polygons[f[1]].normal) < 0.5 else 0.0
          for f in faces]
corner = [0.0] * n
for e, f in zip(me.edges, faces):
    if len(f) == 1: corner[e.vertices[0]] = corner[e.vertices[1]] = 1.0
for name, domain, values in (('crease_edge', 'EDGE', crease), ('crease_vert', 'POINT', corner)):
    if name not in me.attributes: me.attributes.new(name, 'FLOAT', domain)
    me.attributes[name].data.foreach_set('value', values)

mod = ob.modifiers.new('subdivide', 'SUBSURF')
mod.levels = mod.render_levels = levels
mod.uv_smooth = 'NONE'
mod.use_limit_surface = True
nrm = me.attributes.new('nrm', 'FLOAT_VECTOR', 'CORNER')  # shading normals, blended like the UVs
nrm.data.foreach_set('vector', [x for c in me.corner_normals for x in c.vector])

def evaluate():
    dg = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)

P = [v.co.copy() for v in me.vertices]
dense = evaluate()  # the cage's own points come first, where the smooth surface puts them
fix = [P[i] - dense.vertices[i].co for i in range(n)]
print('subdivide: %d detail faces and %d edges kept sharp; smoothing moved points by %.2f on average, at most %.2f'
      % (sum(detail), sum(crease), sum(f.length for f in fix) / n, max(f.length for f in fix)))
for i in range(n): me.vertices[i].co = fix[i]
mod.subdivision_type = 'SIMPLE'  # same vertex order, positions blended linearly
lin = evaluate()
for v, w in zip(dense.vertices, lin.vertices): v.co += w.co
ob.modifiers.remove(mod)
dense.normals_split_custom_set([c.vector.normalized() for c in dense.attributes['nrm'].data])
dense.attributes.remove(dense.attributes['nrm'])
ob.data = dense
dense.name = 'model'
print('subdivide: %d -> %d vertices, %d faces' % (n, len(dense.vertices), len(dense.polygons)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
