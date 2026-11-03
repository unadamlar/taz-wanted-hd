# Blender: evens out a character's shading normals so its cel-shading bands have clean, rounded edges
# instead of ragged ones (the game's bands follow the normals, which in the original models vary
# unevenly from point to point). Each point's normal is averaged with its neighbours' a few times;
# hard edges (corners whose normals differ by more than ~30 degrees, like the teeth) keep their own.
# usage: blender -b <file.blend> -P tools/normals.py -- <out.blend>
import bpy, sys, os
from mathutils import Vector

out = sys.argv[sys.argv.index('--') + 1]
ROUNDS = 3
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
me.normals_split_custom_set([tuple(smooth[l.vertex_index] if corner[li].dot(point[l.vertex_index]) > 0.87 else corner[li])
                             for li, l in enumerate(me.loops)])
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
