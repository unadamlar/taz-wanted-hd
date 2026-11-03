# Blender: renders a character .blend from four sides, textured and as a wireframe.
# usage: blender -b <file.blend> -P tools/meshshot.py -- <out prefix>
import bpy, sys, math, mathutils
pre = sys.argv[sys.argv.index('--') + 1]
sc = bpy.context.scene
ob = [o for o in sc.objects if o.type == 'MESH'][0]
pts = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
lo = mathutils.Vector([min(p[i] for p in pts) for i in range(3)]); hi = mathutils.Vector([max(p[i] for p in pts) for i in range(3)])
mid, size = (lo + hi) / 2, max(hi - lo) * 1.05
sc.render.engine = 'BLENDER_WORKBENCH'
sc.render.resolution_x = sc.render.resolution_y = 1800
sh = sc.display.shading
sh.light, sh.show_backface_culling = 'STUDIO', True
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam); sc.camera = cam
cam.data.type, cam.data.ortho_scale, cam.data.clip_end = 'ORTHO', size, size * 10
wire = ob.copy(); wire.data = ob.data.copy(); sc.collection.objects.link(wire)
mod = wire.modifiers.new('w', 'WIREFRAME'); mod.thickness = size / 1500; mod.use_even_offset = False
black = bpy.data.materials.new('black'); black.diffuse_color = (0, 0, 0, 1)
wire.data.materials.clear(); wire.data.materials.append(black)
for name, a in (('front', 0), ('left', 90), ('back', 180), ('right', 270)):
    d = mathutils.Vector((math.sin(math.radians(a)), -math.cos(math.radians(a)), 0))
    cam.location = mid + d * size * 3
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    for kind in ('tex', 'wire'):
        wire.hide_render = kind == 'tex'
        sh.color_type = 'TEXTURE' if kind == 'tex' else 'SINGLE'
        sh.single_color = (0.85, 0.85, 0.85)
        sc.render.filepath = '%s-%s-%s.png' % (pre, name, kind)
        bpy.ops.render.render(write_still=True)
