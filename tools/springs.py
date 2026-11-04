# Blender: gives Taz spring bones (src/d3d8/mesh.c) so his ears, the fur on top of his head and his
# tail lag behind his moves and bounce back. Each spring takes over part of its parent bone's weight,
# more towards the tip.
# usage: blender -b <taz.blend> -P tools/springs.py -- <out.blend> [<springs.json>]
# With a springs file (other characters), each entry is one spring in the .blend's coordinates:
# {"pivot": [x,y,z], "tip": [x,y,z], "radius": r, "start": a, "end": b, "stiffness": .., "damping": ..,
#  "amount": .., "limit": degrees}; it hangs off the bone owning the point nearest the pivot, and
# takes points from a along the pivot-tip line (none) to b (all), within radius of that line.
import bpy, sys, os, json, math
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
out = args[0]
ob = bpy.data.objects['model']
me = ob.data
gname = {g.index: g.name for g in ob.vertex_groups}
first = len(json.loads(ob['sources']))
springs = []

def smoothstep(a, b, x):
    t = min(1, max(0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)

def owner(v):
    return gname[max(v.groups, key=lambda g: g.weight).group]

def game(p):
    return [p.x, p.z, p.y]

def add(parent, pivot, tip, weight, stiffness, damping, amount, limit):
    vg = ob.vertex_groups.new(name='bone%02d' % (first + len(springs)))
    gname[vg.index] = vg.name
    pg = ob.vertex_groups[parent]
    moved = 0
    for v in me.vertices:
        pw = next((g.weight for g in v.groups if g.group == pg.index), 0)
        w = weight(v.co) if pw > 0 else 0
        if w <= 0.01: continue
        vg.add([v.index], pw * w, 'REPLACE')
        pg.add([v.index], pw * (1 - w), 'REPLACE')
        moved += 1
    springs.append(dict(parent=int(parent[4:]), pivot=game(pivot), tip=game(tip), stiffness=stiffness, damping=damping, amount=amount, limit=math.radians(limit)))
    print('spring %s: %d points' % (vg.name, moved))

if len(args) > 1:
    for s in json.load(open(args[1])):
        pivot, tip = Vector(s['pivot']), Vector(s['tip'])
        d = (tip - pivot).normalized()
        parent = owner(min(me.vertices, key=lambda v: (v.co - pivot).length))
        def part(p, pivot=pivot, d=d, s=s):
            o = p - pivot
            along = o.dot(d)
            return smoothstep(s['start'], s['end'], along) * (1 - smoothstep(0.7 * s['radius'], s['radius'], (o - d * along).length))
        add(parent, pivot, tip, part, s['stiffness'], s['damping'], s['amount'], s['limit'])
    ob['springs'] = json.dumps(springs)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
    sys.exit()

ears = [p for p in me.polygons if 'ears' in me.materials[p.material_index].name]
head = owner(me.vertices[ears[0].vertices[0]])
hv = [v.co for v in me.vertices if owner(v) == head]
H = sum(hv, Vector()) / len(hv)
for side in (1, -1):
    pts = [me.vertices[i].co for p in ears if side * p.center.x > 0 for i in p.vertices]
    C = sum(pts, Vector()) / len(pts)
    d = (C - H).normalized()
    pivot, tip = C - d * 6, C + d * 10
    def ear(p, pivot=pivot, d=d):
        o = p - pivot
        along = o.dot(d)
        return smoothstep(4, 10, along) * (1 - smoothstep(9, 14, (o - d * along).length))
    add(head, pivot, tip, ear, 400, 10, 0.8, 22)

top = max(p.z for p in hv)
hair = [p for p in hv if p.z > top - 14]
c = sum(hair, Vector()) / len(hair)
add(head, Vector((c.x, c.y, top - 18)), Vector((c.x, c.y, top)), lambda p: smoothstep(top - 15, top - 4, p.z), 500, 14, 0.6, 14)

tail = max({owner(v) for v in me.vertices}, key=lambda b: sum(v.co.y for v in me.vertices if owner(v) == b) / max(1, sum(1 for v in me.vertices if owner(v) == b)))
tv = [v.co for v in me.vertices if owner(v) == tail]
y0, y1 = min(p.y for p in tv), max(p.y for p in tv)
base = sum((p for p in tv if p.y < y0 + 6), Vector()) / len([p for p in tv if p.y < y0 + 6])
end = sum((p for p in tv if p.y > y1 - 6), Vector()) / len([p for p in tv if p.y > y1 - 6])
add(tail, base, end, lambda p: smoothstep(y0 + 3, y1, p.y), 200, 7, 1.0, 30)

ob['springs'] = json.dumps(springs)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
