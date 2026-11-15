# Blender: makes a character's surface dense and smooth (Catmull-Clark), so its outline stays round up
# close. Bone weights, springs, shading normals and UVs are blended over the new points (UVs linearly, so
# no texture swatch bleeds into its neighbour). What smoothing would spoil keeps its exact shape: folds
# sharper than 60 degrees (teeth, claws, hair spikes, lips, ear rims), open edges where one part tucks
# into another (no gaps), and the painted details with the faces around them (the eyes, and whatever is
# painted black: brows, eye rims). Smoothing also shrinks a coarse model (thin arms get thinner), so each
# original point is put back where it was and the new points between get the same correction, blended.
# usage: blender -b <file.blend> -P tools/subdivide.py -- <out.blend> [levels, default 2]
import bpy, mathutils, sys, os
import numpy as np

args = sys.argv[sys.argv.index('--') + 1:]
out, levels = args[0], int(args[1]) if len(args) > 1 else 2
ob = bpy.data.objects['model']
me = ob.data
n = len(me.vertices)
uv = me.uv_layers.active.data
pixels = {}
EYES = ('eyeblink', 'gossamereye', 'eyeball', 'tweetyeye')  # eye textures: Taz and most others, Gossamer, zookeeper, Tweety

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
detail = [(any(k in me.materials[p.material_index].name for k in EYES) or painted_black(p)) for p in me.polygons]
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

def surface(P):  # the dense surface for cage points P
    for i in range(n): me.vertices[i].co = P[i]
    mod.subdivision_type = 'CATMULL_CLARK'
    dense = evaluate()  # the cage's own points come first, where the smooth surface puts them
    fix = [P[i] - dense.vertices[i].co for i in range(n)]
    for i in range(n): me.vertices[i].co = fix[i]
    mod.subdivision_type = 'SIMPLE'  # same vertex order, positions blended linearly
    lin = evaluate()
    for v, w in zip(dense.vertices, lin.vertices): v.co += w.co
    bpy.data.meshes.remove(lin)
    return dense, fix

P = [v.co.copy() for v in me.vertices]
dense, fix = surface(P)
print('subdivide: %d detail faces and %d edges kept sharp; smoothing moved points by %.2f on average, at most %.2f'
      % (sum(detail), sum(crease), sum(f.length for f in fix) / n, max(f.length for f in fix)))

# PERBONE=1 (rigidly skinned characters: everyone but Taz): the dense surface is a fixed blend of the
# original points, so it can follow the bones exactly as the original model does, as if the posed model
# were subdivided afresh every frame. For that each dense point gets, per bone, the place that bone's
# share of the blend puts it, and that share as its weight; the game's shader then moves each place with
# its own bone. One place blended between bones (what Blender's weights give) bunched skin up wherever
# a bone slides it a long way: Gossamer's brows over his eyes came out as wrinkled lumps with zigzag
# outlines. Up to 3 bones per point, the rest count with the strongest.
if os.environ.get('PERBONE'):
    G, N = len(ob.vertex_groups), len(dense.vertices)
    W = np.zeros((n, G))
    for v in me.vertices:
        for g in v.groups: W[v.index, g.group] = g.weight
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    Pn, Q, Wd = np.array(P), np.zeros((G, N, 3)), np.zeros((G, N))
    def blend(C):
        d, _ = surface([mathutils.Vector(c) for c in C])
        co = np.zeros(N * 3); d.vertices.foreach_get('co', co)
        bpy.data.meshes.remove(d)
        return co.reshape(N, 3)
    for g in range(G):
        if not W[:, g].any(): continue
        Q[g] = blend(Pn * W[:, g:g + 1])
        Wd[g] = blend(np.c_[W[:, g], np.zeros((n, 2))])[:, 0]
    whole = np.zeros(N * 3); dense.vertices.foreach_get('co', whole)
    print('subdivide: per-bone places add up to the surface within %.4f, weights to 1 within %.5f'
          % (abs(Q.sum(0) - whole.reshape(N, 3)).max(), abs(Wd.sum(0) - 1).max()))
    order = np.argsort(-Wd, axis=0)  # bones by share, strongest first
    cols = np.arange(N)
    keep = [order[k] for k in range(3)]
    kw = [Wd[keep[k], cols] for k in range(3)]
    kq = [Q[keep[k], cols] for k in range(3)]
    for k in (1, 2):  # too small to carry a place of its own
        small = kw[k] < 0.002
        kw[k] = np.where(small, 0, kw[k]); kq[k] = np.where(small[:, None], 0, kq[k])
    kw[0] = 1 - kw[1] - kw[2]
    kq[0] = whole.reshape(N, 3) - kq[1] - kq[2]
    for name, kind, data in [('bent_bone', 'FLOAT_VECTOR', np.stack([[int(ob.vertex_groups[g].name[4:]) for g in keep[k]] for k in range(3)], 1)),
                             ('bent_weight', 'FLOAT_VECTOR', np.stack(kw, 1))] + \
                            [('bent_place%d' % k, 'FLOAT_VECTOR', kq[k] / np.maximum(kw[k], 1e-9)[:, None]) for k in range(3)]:
        dense.attributes.new(name, kind, 'POINT').data.foreach_set('vector', np.asarray(data, dtype=np.float32).ravel())
    print('subdivide: %d of %d points move with more than one bone' % ((kw[1] > 0).sum(), N))
ob.modifiers.remove(mod)
dense.normals_split_custom_set([c.vector.normalized() for c in dense.attributes['nrm'].data])
dense.attributes.remove(dense.attributes['nrm'])
ob.data = dense
dense.name = 'model'
print('subdivide: %d -> %d vertices, %d faces' % (n, len(dense.vertices), len(dense.polygons)))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
