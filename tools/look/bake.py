"""Blender side of the look export: bakes the kit's node materials into tiling albedo + normal
tiles, and the world (with the far hill panels) into a sky panorama. Results are cached as .npz."""
import bpy, math
import numpy as np
from pathlib import Path
from mathutils import Vector
import kit, dds


def use_gpu(sc):
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "NONE"):
        try:
            prefs.compute_device_type = kind
            break
        except TypeError:
            pass
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type != "CPU"
    sc.cycles.device = "GPU" if any(d.use for d in prefs.devices) else "CPU"
    print("bake: device", sc.cycles.device, [d.name for d in prefs.devices if d.use])


def _plane(size, vertical):
    """Quad over [0, size]^2 in world space, with the attributes the kit's graphs read."""
    co = [(0, 0, 0), (size, 0, 0), (size, 0, size), (0, 0, size)] if vertical else \
         [(0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0)]
    me = bpy.data.meshes.new("bake_plane")
    me.from_pydata(co, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    uv.data.foreach_set("uv", [0, 0, 1, 0, 1, 1, 0, 1])
    for name, typ, val in (("kit_h", "FLOAT", 1.0), ("kit_ao", "FLOAT", 1.0), ("kit_tip", "FLOAT", 1.0)):
        me.attributes.new(name, typ, "POINT").data.foreach_set("value", [val] * 4)
    me.attributes.new("kit_gdir", "FLOAT_VECTOR", "POINT").data.foreach_set("vector", [1, 0, 0] * 4)
    ob = bpy.data.objects.new("bake_plane", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _bake(ob, mat, n, kind):
    img = bpy.data.images.new("bake_" + kind, n, n, float_buffer=True, alpha=False)
    img.colorspace_settings.name = "Non-Color"
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    mat.node_tree.nodes.active = node
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    if kind == "albedo":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=0, use_clear=True)
    else:
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=0, use_clear=True)
    px = np.empty(n * n * 4, np.float32)
    img.pixels.foreach_get(px)
    mat.node_tree.nodes.remove(node)
    bpy.data.images.remove(img)
    return px.reshape(n, n, 4)[::-1, :, :3].copy()  # top row first


def _seamless(a, n):
    """Crossfade the strip past the tile back over its start, on both axes."""
    ov = a.shape[0] - n
    if ov <= 0:
        return a
    w = (np.arange(ov) + 0.5) / ov
    a = a.copy()
    a[:ov] = a[:ov] * w[:, None, None] + a[n:n + ov] * (1 - w)[:, None, None]
    a[:, :ov] = a[:, :ov] * w[None, :, None] + a[:, n:n + ov] * (1 - w)[None, :, None]
    return a[:n, :n]


def bake_tile(cache, name, mat, tile, px, vertical=True, overlap=0.125, samples=8, seamless=True):
    """Albedo (sRGB) and tangent normal (0..1) of a material over a `tile`-sized square."""
    f = Path(cache) / (name + ".npz")
    if f.exists():
        d = np.load(f)
        return d["albedo"], d["normal"]
    sc = bpy.context.scene
    sc.cycles.samples = samples
    ov = int(round(px * overlap)) if seamless else 0
    n = px + ov
    ob = _plane(tile * n / px, vertical)
    alb, nor = _bake(ob, mat, n, "albedo"), _bake(ob, mat, n, "normal")
    bpy.data.objects.remove(ob)
    alb, nor = _seamless(alb, px), _seamless(nor, px)
    alb = dds.to_srgb(alb).astype(np.float32)
    v = nor * 2 - 1
    v /= np.maximum(np.linalg.norm(v, axis=2, keepdims=True), 1e-6)
    nor = ((v + 1) / 2).astype(np.float32)
    np.savez_compressed(f, albedo=alb.astype(np.float16), normal=nor.astype(np.float16))
    print("bake: %s %dpx, tile %.2f, mean albedo %s" % (name, px, tile, (alb.reshape(-1, 3).mean(0) * 255).astype(int)))
    return alb, nor


def bake_sky(cache, sc, eye, n=8192):
    """Equirect render of what a camera sees beyond the level: world + far hill panels, scene-linear."""
    f = Path(cache) / "sky.npz"
    if f.exists():
        return np.load(f)["sky"]
    for o in bpy.data.objects:
        if o.type == "MESH":
            keep = any(s.material and s.material.name.startswith("backdrop:") for s in o.material_slots)
            o.hide_render = not keep
    cd = bpy.data.cameras.new("sky_cam")
    cd.type = "PANO"
    cd.panorama_type = "EQUIRECTANGULAR"
    cam = bpy.data.objects.new("sky_cam", cd)
    sc.collection.objects.link(cam)
    cam.location = eye
    cam.rotation_euler = (math.pi / 2, 0, 0)
    sc.camera = cam
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage, r.pixel_aspect_x = n, n // 2, 100, 1.0
    r.use_compositing, r.film_transparent = False, False
    sc.cycles.samples = 16
    r.image_settings.file_format = "OPEN_EXR"
    r.image_settings.color_depth = "32"
    r.filepath = str(Path(cache) / "sky_render.exr")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(r.filepath)
    px = np.empty(n * (n // 2) * 4, np.float32)
    img.pixels.foreach_get(px)
    sky = px.reshape(n // 2, n, 4)[::-1, :, :3].copy()
    bpy.data.images.remove(img)
    Path(r.filepath).unlink()
    np.savez_compressed(f, sky=sky.astype(np.float16))
    return sky


def cube_faces(sky, size=1024):
    """Six faces in D3D order, sampled by game-space direction (game (x, y, z) = Blender (x, z, y))."""
    t = (np.arange(size) + 0.5) / size * 2 - 1
    u, v = np.meshgrid(t, t)
    one = np.ones_like(u)
    dirs = [(one, -v, -u), (-one, -v, u), (u, one, v), (u, -one, -v), (u, -v, one), (-u, -v, -one)]
    h, w = sky.shape[:2]
    out = []
    for gx, gy, gz in dirs:
        bx, by, bz = gx, gz, gy  # game -> Blender
        r = np.sqrt(bx * bx + by * by + bz * bz)
        # Cycles equirect: longitude 0 at -Y is image centre, x to the right
        lon = np.arctan2(bx, by)
        lat = np.arcsin(np.clip(bz / r, -1, 1))
        px = ((lon / (2 * np.pi) + 0.5) * w - 0.5) % w
        py = np.clip((0.5 - lat / np.pi) * h - 0.5, 0, h - 1)
        x0, y0 = np.floor(px).astype(np.int32), np.floor(py).astype(np.int32)
        fx, fy = (px - x0)[..., None], (py - y0)[..., None]
        x1, y1 = (x0 + 1) % w, np.minimum(y0 + 1, h - 1)
        out.append((sky[y0, x0] * (1 - fx) + sky[y0, x1] * fx) * (1 - fy) + (sky[y1, x0] * (1 - fx) + sky[y1, x1] * fx) * fy)
    return out
