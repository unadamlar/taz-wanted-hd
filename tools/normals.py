# Blender: evens out a character's shading normals so its cel-shading bands have clean, rounded edges
# instead of ragged ones (the game's bands follow the normals, which in the original models vary
# unevenly from point to point). Each point's normal is averaged with its neighbours' a few times;
# hard edges (corners whose normals differ by more than ~30 degrees, like the teeth) keep their own,
# except around the ears' insides, whose rims then smooth into a rounded lip in game.
# usage: blender -b <file.blend> -P tools/normals.py -- <out.blend>
import bpy, sys, os
from mathutils import Vector

out = sys.argv[sys.argv.index('--') + 1]
ROUNDS = 3
SOFT = ('ears',)  # materials whose edges smooth over even where they fold
PLATES = ('elephanttoes',)  # materials with free-standing thin flaps (the elephant's ears); Taz's thin decals keep theirs
me = bpy.data.objects['model'].data
corner = [Vector(n.vector) for n in me.corner_normals]
point = [Vector() for _ in me.vertices]
for li, l in enumerate(me.loops): point[l.vertex_index] += corner[li]
point = [n.normalized() if n.length > 1e-6 else n for n in point]
near = [[] for _ in me.vertices]
for e in me.edges:
    a, b = e.vertices
    near[a].append(b)
    near[b].append(a)
smooth = point
for _ in range(ROUNDS):
    nxt = []
    for i, n in enumerate(smooth):
        s = Vector(n)
        for j in near[i]:
            if smooth[j].dot(n) > 0.5: s += smooth[j] * 0.5  # across a fold (lips, teeth) neighbours don't count
        nxt.append(s.normalized() if s.length > 1e-6 else n)
    smooth = nxt
soft = {me.loops[li].vertex_index for p in me.polygons if any(k in me.materials[p.material_index].name for k in SOFT) for li in p.loop_indices}
new = [smooth[l.vertex_index] if corner[li].dot(point[l.vertex_index]) > 0.87 or l.vertex_index in soft else corner[li] for li, l in enumerate(me.loops)]
# Thin plates (the elephant's ears) share their rim points between front and back, so one normal can't
# suit both sides and a side came out lit from behind (dark patches) with its outline poking through.
# A corner there more than 60 degrees off its face gets the average of the faces on its own side instead.
around = [[] for _ in me.vertices]
for p in me.polygons:
    for v in p.vertices: around[v].append(p)
plate = {v for v, ps in enumerate(around) if any(a.normal.dot(b.normal) < -0.7 for a in ps for b in ps)  # front meets back
         and any(k in me.materials[q.material_index].name for q in ps for k in PLATES)}
flipped = 0
for p in me.polygons:
    for li in p.loop_indices:
        if me.loops[li].vertex_index in plate and new[li].dot(p.normal) < 0.5:
            new[li] = sum((q.normal * q.area for q in around[me.loops[li].vertex_index] if q.normal.dot(p.normal) > 0.5), Vector()).normalized()
            flipped += 1
print('normals: %d corners turned to their own side' % flipped)
me.normals_split_custom_set([tuple(n) for n in new])
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
