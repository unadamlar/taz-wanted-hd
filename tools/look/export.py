# Blender: exports the look kit's additions in a dressed scene as a runtime file for src/d3d8/look.c.
# usage: blender -b <zoohub-dressed.blend> -P tools/look/export.py -- <out.bin>
# Prototype meshes (scatter variants, and each prop as a one-off) with their albedo baked into vertex
# colours, instances as 3x4 matrices in game space, grouped in grid chunks for culling and thinning,
# and the fingerprints of game textures the dressing hides or gives its ground material. The scene is not saved.
# Game space is worldview.py's inverse: Blender (x, y, z) * 250 -> game (x, z, y).
import bpy, bmesh, struct, sys, os, fnmatch, collections, random
import numpy as np
from mathutils import Matrix

out = sys.argv[sys.argv.index('--') + 1]
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import zoohub  # RULES: texture -> role
K = 250.0
CHUNK = 1500.0  # game units (6 Blender units)
S = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
ext = next(p for p in [os.path.join(here, *(['..'] * n), 'extracted') for n in range(1, 7)] if os.path.isdir(os.path.join(p, 'textures')))

sc = bpy.context.scene
scatter = [o for c in ('kit_grass', 'kit_clutter') for o in bpy.data.collections[c].objects]
scatter += [o for o in bpy.data.objects if o.name.startswith(('kit_vines', 'kit_ledge')) and o.type == 'MESH']
props = [o for o in bpy.data.collections['kit_props'].objects if o.type == 'MESH' and len(o.data.polygons)]

# Instances (depsgraph) -> prototype objects and matrices.
dg = bpy.context.evaluated_depsgraph_get()
names = {o.name for o in scatter}
inst = collections.defaultdict(list)
for i in dg.object_instances:
    if i.is_instance and i.parent and i.parent.original.name in names:
        inst[i.object.original.name].append(i.matrix_world.copy())
protos = [bpy.data.objects[n] for n in sorted(inst)] + props
print('export: %d prototypes, %d instances, %d props' % (len(inst), sum(map(len, inst.values())), len(props)))

# Albedo baked into a colour attribute per corner (Cycles, diffuse colour only).
sc.render.engine = 'CYCLES'
sc.cycles.samples = 4
sc.cycles.device = 'GPU'
bpy.ops.object.select_all(action='DESELECT')
todo = []
for o in protos:
    me = o.data
    if 'look_bake' not in me.color_attributes:
        me.color_attributes.new('look_bake', 'BYTE_COLOR', 'CORNER')
    me.color_attributes.active_color = me.color_attributes['look_bake']
    if o.name not in bpy.context.view_layer.objects: sc.collection.objects.link(o)  # scatter variants live in an excluded collection
    bpy.context.view_layer.update()
    o.hide_set(False); o.hide_render = False; o.select_set(True)
    todo.append(o)
bpy.context.view_layer.objects.active = todo[0]
bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, target='VERTEX_COLORS')
print('export: baked %d objects' % len(todo))
for o in protos:
    c = np.empty(len(o.data.loops) * 4, np.float32); o.data.color_attributes['look_bake'].data.foreach_get('color', c)
    print('export:   albedo %-26s %s' % (o.name, (c.reshape(-1, 4)[:, :3].mean(0) * 255).astype(int)))

def mesh_data(o, world):
    """Triangles in game space: unique (position, normal, colour) vertices and u16/u32 indices.
    Faces with foliage card materials are left out (they need their alpha texture)."""
    me = o.data
    me.calc_loop_triangles()
    col = me.color_attributes['look_bake'].data
    M = (S @ o.matrix_world) if world else S
    N = M.to_3x3().inverted().transposed()
    vi, verts, idx = {}, [], []
    for t in me.loop_triangles:
        mat = me.materials[t.material_index] if me.materials else None
        if mat and 'cards' in mat.name: continue
        for li in t.loops:
            l = me.loops[li]
            p = M @ me.vertices[l.vertex_index].co * K
            n = (N @ l.normal).normalized()
            c = col[li].color
            rgb = [min(255, int((x * 12.92 if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055) * 255 + 0.5)) for x in c[:3]]  # the game works in sRGB
            key = (round(p.x, 2), round(p.y, 2), round(p.z, 2), round(n.x, 2), round(n.y, 2), round(n.z, 2), *rgb)
            if key not in vi:
                vi[key] = len(verts)
                verts.append((p.x, p.y, p.z, n.x, n.y, n.z, 0xff000000 | rgb[0] << 16 | rgb[1] << 8 | rgb[2]))
            idx.append(vi[key])
    return verts, idx

def game_matrix(m):  # Blender matrix_world -> game rows (x, y, z) of [linear | translation]
    g = S @ m @ S
    return [x for r in range(3) for x in (g[r][0], g[r][1], g[r][2], g[r][3] * K)]

blob = []
proto_bbox = []
for o in protos:
    v, ix = mesh_data(o, world=o in props)
    a = np.array([p[:3] for p in v]) if v else np.zeros((1, 3))
    proto_bbox.append((a.min(0), a.max(0)))
    blob.append((v, ix))

# Chunks: instance centre -> grid cell; each cell lists (prototype, matrices), shuffled for thinning.
cells = collections.defaultdict(lambda: collections.defaultdict(list))
boxes = {}
def add(cell, pi, rows, lo, hi):
    cells[cell][pi].append(rows)
    b = boxes.get(cell)
    boxes[cell] = (np.minimum(b[0], lo), np.maximum(b[1], hi)) if b else (lo, hi)
rng = random.Random(1)
for pi, o in enumerate(protos):
    lo, hi = proto_bbox[pi]
    mats = [Matrix.Identity(4)] if o in props else inst[o.name]
    for m in mats:
        rows = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] if o in props else game_matrix(m)
        R = np.array(rows).reshape(3, 4)
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ R[:, :3].T + R[:, 3]
        c = corners.mean(0)
        add((int(c[0] // CHUNK), int(c[2] // CHUNK)), pi, rows, corners.min(0), corners.max(0))
for cell in cells.values():
    for runs in cell.values(): rng.shuffle(runs)

# Game textures the dressing hides (role -> fingerprints); 'shadow' ones only once real shadows are on.
fp = {}
for line in open(os.path.join(ext, 'textures', 'fingerprints.tsv')):
    h, f = line.rstrip('\n').split('\t')[:2]
    fp.setdefault(f, int(h, 16))
hide, shadow, ground = set(), set(), set()
for line in list(open(os.path.join(ext, 'textures', 'index.tsv')))[1:]:
    pak, name, w, h, f = line.rstrip('\n').split('\t')
    label = pak + '/' + os.path.splitext(name)[0]
    role = zoohub.role_of(label) if pak.startswith('zoohub') or pak == 'resTex' else None
    if f in fp and role in ('hide', 'fence_rail', 'fence_post', 'fence_cap', 'tree'):
        (shadow if 'shadowsub' in label else hide).add(fp[f])
    if f in fp and role == 'ground':
        ground.add(fp[f])

with open(out, 'wb') as f:
    f.write(struct.pack('<4sI', b'TZLK', 2))
    for s_ in (hide, shadow, ground):
        f.write(struct.pack('<I', len(s_)) + b''.join(struct.pack('<Q', h) for h in sorted(s_)))
    f.write(struct.pack('<I', len(protos)))
    for (v, ix), o in zip(blob, protos):
        f.write(struct.pack('<II', len(v), len(ix)))
        f.write(b''.join(struct.pack('<6fI', *p) for p in v))
        f.write(struct.pack('<%dI' % len(ix), *ix))
    f.write(struct.pack('<I', len(cells)))
    for cell, runs in sorted(cells.items()):
        lo, hi = boxes[cell]
        f.write(struct.pack('<6fI', *lo, *hi, len(runs)))
        for pi, rows in sorted(runs.items()):
            f.write(struct.pack('<II', pi, len(rows)))
            f.write(b''.join(struct.pack('<12f', *r) for r in rows))
tris = sum(len(ix) // 3 * (1 if o in props else len(inst[o.name])) for (v, ix), o in zip(blob, protos))
print('export: %s, %d chunks, %d triangles in all, %d hidden + %d shadow fingerprints, %.1f MB'
      % (out, len(cells), tris, len(hide), len(shadow), os.path.getsize(out) / 1e6))
for (v, ix), o in zip(blob, protos):
    print('export:  %-28s %6d verts %6d tris x %d' % (o.name, len(v), len(ix) // 3, 1 if o in props else len(inst[o.name])))
