"""Stand-in zoo hub built like the game (flat sheets, angular polygons, boxes),
rendered flat ("before") and with the look kit applied ("after").

  blender -b --factory-startup --python-exit-code 1 -P tools/look/standin.py -- [--scale 1.0] [--only before|after] [--samples 64]
Writes extracted/look/kit-before.jpg, kit-after.jpg, kit-side-by-side.jpg and the .blend files.
"""
import bpy, sys, math, time, argparse
import numpy as np
from pathlib import Path
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit  # noqa: E402

GAME = {  # flat game colours (sRGB), from the zoo hub screenshots
    "dirt": "#efa040", "lawn": "#1f9a1c", "lawn_border": "#137a14", "fence": "#d6d0f2", "fence_cap": "#f0d23a",
    "cliff": "#f2c8b4", "cliff_top": "#2e9e26", "brick": "#d0581e", "trim": "#f4e6c4", "water": "#2266e8",
    "stone": "#b8b4cc", "bark": "#8a4e2a", "foliage": "#2f9a24", "rock": "#a8a8b4", "hero": "#7a4630", "hill": "#3fae3a",
}


def gmat(key, role=None):
    name = f"game_{key}"
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    c = kit.srgb(GAME[key])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*c, 1)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs[0])
    m["game_color"] = c
    if role:
        m["look"] = role
    return m


def mk(name, verts, faces, mats, face_mats=None, role=None, smooth=False):
    me = kit._mesh(name, verts, faces, None, mats, face_mats, smooth=smooth)
    ob = kit._obj(name, me)
    if role:
        ob["look"] = role
    return ob


def prism(name, poly, z0, z1, mat, role, top_mat=None):
    n = len(poly)
    V = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    F = [tuple(range(n))[::-1], tuple(range(n, 2 * n))] + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    mats = [mat] + ([top_mat] if top_mat else [])
    fm = [0, 1 if top_mat else 0] + [0] * n
    return mk(name, V, F, mats, fm, role)


def box(name, c, s, mat, role, rot=0.0):
    hx, hy = s[0] / 2, s[1] / 2
    pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    cr, sr = math.cos(rot), math.sin(rot)
    poly = [(c[0] + x * cr - y * sr, c[1] + x * sr + y * cr) for x, y in pts]
    return prism(name, poly, c[2], c[2] + s[2], mat, role)


def lawn(name, poly, u, z=0.03, zig=0.35, seed=0):
    """Game-style lawn: bright flat polygon ringed by a darker zigzag strip (one mesh)."""
    rng = np.random.default_rng(seed)
    pts = []
    P = [Vector((x, y)) for x, y in poly]
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        k = max(2, int((b - a).length / (0.9 * u)))
        for j in range(k):
            pts.append(a.lerp(b, j / k))
    n = len(pts)
    cen = sum(pts, Vector((0, 0))) / n
    outer = []
    for i, p in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % n]
        t = (nxt - prev).normalized()
        nrm = Vector((t.y, -t.x))
        if nrm.dot(p - cen) < 0:
            nrm = -nrm
        outer.append(p + nrm * (zig * u * (1.6 if i % 2 else 0.5) * rng.uniform(0.7, 1.3)))
    V = [(p.x, p.y, z) for p in pts] + [(p.x, p.y, z) for p in outer]
    F = [tuple(range(n))] + [(i, n + i, n + (i + 1) % n, (i + 1) % n) for i in range(n)]
    ob = mk(name, V, F, [gmat("lawn", "lawn"), gmat("lawn_border", "lawn")], [0] + [1] * n)
    # normals up
    if ob.data.polygons[0].normal.z < 0:
        ob.data.flip_normals()
    return ob


def blob_tree(name, base, h, r, u, seed=0):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.22 * u, radius2=0.14 * u, depth=h * 0.6)
    for v in bm.verts:
        v.co.z += h * 0.3
    ico = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)["verts"]
    rng = np.random.default_rng(seed)
    for v in ico:
        v.co = Vector((v.co.x * rng.uniform(0.9, 1.1), v.co.y * rng.uniform(0.9, 1.1), v.co.z * 0.85 + h - r * 0.85))
    for f in {f for v in ico for f in v.link_faces}:
        f.material_index = 1
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(gmat("bark"))
    me.materials.append(gmat("foliage"))
    ob = kit._obj(name, me)
    ob.location = base
    ob["look"] = "tree"
    return ob


def game_fence(name, p0, p1, u, h=1.0, spacing=2.4):
    import bmesh
    p0, p1 = Vector(p0), Vector(p1)
    L = (p1 - p0).length
    n = max(1, round(L / (spacing * u)))
    d = (p1 - p0).normalized()
    bm = bmesh.new()

    def add_box(c, s, mi):
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co = Vector((v.co.x * s[0], v.co.y * s[1], v.co.z * s[2])) + Vector(c)
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = mi
    for i in range(n + 1):
        x = L * i / n
        add_box((x, 0, h * u / 2), (0.07 * u, 0.07 * u, h * u), 0)
        add_box((x, 0, h * u + 0.06 * u), (0.16 * u, 0.16 * u, 0.12 * u), 1)
    for rz in (0.45, 0.85):
        add_box((L / 2, 0.05 * u, rz * h * u), (L, 0.04 * u, 0.1 * u), 0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(gmat("fence"))
    me.materials.append(gmat("fence_cap"))
    ob = kit._obj(name, me)
    ob.location = p0
    ob.rotation_euler = (0, 0, math.atan2(d.y, d.x))
    ob["look"] = "fence"
    return ob


def build(u=1.0):
    """u = hero height / 1.2 m. Returns (camera, hero)."""
    S = lambda *a: tuple(x * u for x in a)  # noqa: E731
    sc = bpy.context.scene
    # ground sheet
    G = 30 * u
    mk("ground", [(-G, -G, 0), (G, -G, 0), (G, G, 0), (-G, G, 0)], [(0, 1, 2, 3)], [gmat("dirt", "dirt")])
    F = 600 * u
    mk("ground_far", [(-F, -F, -0.05 * u), (F, -F, -0.05 * u), (F, F, -0.05 * u), (-F, F, -0.05 * u)], [(0, 1, 2, 3)],
       [gmat("hill", "lawn_far")])
    # distant green hills as a backdrop (the game has them too)
    import bmesh
    rng = np.random.default_rng(9)
    for i, a in enumerate(np.linspace(0.15, np.pi - 0.15, 9)):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        me = bpy.data.meshes.new(f"hill_{i}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(gmat("hill", "lawn_far"))
        ob = kit._obj(f"hill_{i}", me)
        d = rng.uniform(90, 130) * u
        ob.location = (math.cos(a) * d, math.sin(a) * d + 10 * u, -6 * u)
        ob.scale = (rng.uniform(25, 40) * u, rng.uniform(15, 25) * u, rng.uniform(14, 24) * u)
    # lawns (angular, like the game)
    lawn("lawn_left", [S(-16, -3), S(-3.2, -3.5), S(-2.0, 1.5), S(-2.6, 5.0), S(-5, 6.3), S(-16, 6.6)], u, seed=1)
    lawn("lawn_right_front", [S(2.4, -4.5), S(12, -5), S(12, 3.8), S(5.5, 3.2), S(3.0, 1.0)], u, seed=2)
    lawn("lawn_right_back", [S(3.4, 6.2), S(12, 5.8), S(12, 9.6), S(3.2, 9.2)], u, seed=3)
    lawn("lawn_back_left", [S(-18, 8.2), S(-2.8, 8.0), S(-2.4, 10.4), S(-18, 10.4)], u, seed=4)
    # pond, front right: flat water with a faceted rim of stone blocks
    pc, pr, n = Vector(S(4.6, -2.4, 0)), 1.9 * u, 10
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    mk("pond_water", [(pc.x + math.cos(a) * pr, pc.y + math.sin(a) * pr, 0.12 * u) for a in ang], [tuple(range(n))],
       [gmat("water", "water")])
    for i, a in enumerate(ang):
        a2 = a + np.pi / n
        box(f"pond_rim_{i}", (pc.x + math.cos(a2) * (pr + 0.18 * u), pc.y + math.sin(a2) * (pr + 0.18 * u), 0),
            S(0.42, 1.28, 0.32), gmat("stone", "stone"), None, rot=a2)
    # fences, mid-ground, gap for the path
    game_fence("fence_left", S(-15, 7.2, 0), S(-2.2, 7.2, 0), u)
    game_fence("fence_right", S(3.0, 5.6, 0), S(11.5, 5.6, 0), u)
    # low brick wall with cream cap behind the left fence
    box("wall_left", S(-9.5, 11.6, 0), S(14, 0.5, 1.3), gmat("brick", "brick"), None)
    box("wall_left_cap", S(-9.5, 11.6, 1.3), S(14.2, 0.7, 0.18), gmat("trim", "trim"), None)
    # brick building + pillars, right
    box("building", S(11.5, 11.5, 0), S(5, 5, 4.2), gmat("brick", "brick"), None)
    box("building_cap", S(11.5, 11.5, 4.2), S(5.5, 5.5, 0.35), gmat("trim", "trim"), None)
    for cx, cy in ((9.0, 9.0), (9.0, 14.0), (14.0, 9.0)):
        box(f"building_corner_{cx}_{cy}", S(cx, cy, 0), S(0.7, 0.7, 4.2), gmat("trim", "trim"), None)
    box("pillar", S(7.6, 7.6, 0), S(1.3, 1.3, 2.6), gmat("brick", "brick"), None)
    box("pillar_cap", S(7.6, 7.6, 2.6), S(1.6, 1.6, 0.25), gmat("trim", "trim"), None)
    # sandstone cliffs, centre back: blocky slabs with green caps
    cliffs = [
        ([S(-4.5, 15), S(-1.2, 14.2), S(-0.4, 17.5), S(-4.0, 18.5)], 6.6),
        ([S(-1.0, 14.6), S(2.6, 14.0), S(3.4, 17.0), S(-0.2, 17.8)], 5.4),
        ([S(2.8, 14.8), S(6.0, 15.4), S(5.4, 18.4), S(3.0, 18.0)], 7.4),
        ([S(-8.5, 15.8), S(-4.3, 15.2), S(-3.8, 18.8), S(-8.0, 19.0)], 4.8),
    ]
    for i, (poly, h) in enumerate(cliffs):
        prism(f"cliff_{i}", poly, 0, h * u, gmat("cliff", "cliff"), None)
        c = sum((Vector(p) for p in poly), Vector((0, 0))) / len(poly)
        big = [tuple(c + (Vector(p) - c) * 1.06) for p in poly]
        prism(f"cliff_top_{i}", big, h * u - 0.05 * u, h * u + 0.2 * u, gmat("cliff_top", "cliff_top"), None)
    # trees: background, on the cliff, and one off-frame left for a foreground shadow
    for i, (x, y, z, h, r) in enumerate([(-7.8, -3.0, 0, 5.4, 2.0), (-11, 13.5, 0, 5.5, 2.2), (-0.8, 16.0, 6.8, 4.2, 1.7),
                                         (7.0, 17.5, 0, 6.0, 2.3), (15, 6.5, 0, 5.0, 2.0), (-15, 4.0, 0, 5.5, 2.1)]):
        blob_tree(f"tree_{i}", S(x, y, z), h * u, r * u, u, seed=i)
    # boulders
    for i, (x, y, z, r) in enumerate([(-2.6, 3.0, 0, 0.45), (2.7, 4.3, 0, 0.6), (7.6, 7.6, 2.85, 0.55), (-12, 7.6, 0, 0.7)]):
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r * u)
        for v in bm.verts:
            v.co.z = max(v.co.z, -0.2 * r * u) + 0.2 * r * u
        me = bpy.data.meshes.new(f"boulder_{i}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(gmat("rock"))
        ob = kit._obj(f"boulder_{i}", me)
        ob.location = S(x, y, z)
        ob["look"] = "boulder"
    # hero reference: 1.2 m tall Taz-ish blob (body + head + feet)
    import bmesh
    bm = bmesh.new()
    for c, rad, sz in (((0, 0, 0.42), 0.36, 1.15), ((0, 0.02, 0.98), 0.26, 0.85)):
        r = bmesh.ops.create_icosphere(bm, subdivisions=3, radius=rad * u)
        for v in r["verts"]:
            v.co.z *= sz
            v.co += Vector(c) * u
    for fx in (-0.13, 0.13):
        r = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.11 * u)
        for v in r["verts"]:
            v.co = Vector((v.co.x, v.co.y * 1.6 - 0.06 * u, v.co.z * 0.5)) + Vector((fx * u, 0, 0.05 * u))
    me = bpy.data.meshes.new("hero")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(gmat("hero"))
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    hero = kit._obj("hero", me)
    hero.location = S(0.2, 0.2, 0)
    hero["look"] = "hero"
    # camera: low, wide, behind the hero
    cd = bpy.data.cameras.new("cam")
    cd.lens = 18
    cd.clip_end = 400 * u
    cam = kit._obj("cam", cd)
    cam.location = S(0.4, -6.2, 1.75)
    cam.rotation_euler = (Vector(S(0.2, 10, 1.6)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    return cam, hero


def setup_before(sc):
    """Game-like: flat unlit colours, saturated gradient sky, no post."""
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 93
    sc.eevee.taa_render_samples = 16
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("game_sky")
    sc.world = w
    w.use_nodes = True
    t = w.node_tree
    t.nodes.clear()
    b = kit._B(t)
    d = b.vmath("NORMALIZE", kit.o(b("ShaderNodeTexCoord"), "Generated"))
    z = b.sep(d)[2]
    col = b.ramp(b.math("MAXIMUM", z, 0), [(0.0, kit.srgb("#a8d8ff")), (0.25, kit.srgb("#3a60ff")), (0.6, kit.srgb("#0a1cf0"))])
    b("ShaderNodeOutputWorld", {"Surface": b("ShaderNodeBackground", {"Color": col})})


def hero_material(scale):
    m, b = kit._new_mat("kit_hero")
    kit._finish(b, kit.srgb("#7a4630"), 0.6)
    return m


def render(path):
    t = time.time()
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return time.time() - t


def side_by_side(a, b, out):
    ia, ib = bpy.data.images.load(str(a)), bpy.data.images.load(str(b))
    w, h = ia.size
    pa = np.array(ia.pixels[:], np.float32).reshape(h, w, 4)
    pb = np.array(ib.pixels[:], np.float32).reshape(h, w, 4)
    gap = np.ones((h, 16, 4), np.float32) * np.array([0.05, 0.05, 0.05, 1])
    c = np.concatenate([pa, gap, pb], 1)
    img = bpy.data.images.new("sbs", c.shape[1], h)
    img.pixels.foreach_set(c.astype(np.float32).ravel())
    img.filepath_raw = str(out)
    img.file_format = "JPEG"
    img.save()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", choices=["before", "after"])
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--res", type=int, default=100, help="resolution percentage (quick iterations)")
    a = ap.parse_args(argv)
    out = kit.out_dir()
    out.mkdir(parents=True, exist_ok=True)
    u = a.scale
    if a.only != "after":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        build(u)
        setup_before(bpy.context.scene)
        bpy.context.scene.render.resolution_percentage = a.res
        bpy.ops.wm.save_as_mainfile(filepath=str(out / "kit-before.blend"))
        print("BEFORE render s", round(render(out / "kit-before.jpg"), 1))
    if a.only != "before":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cam, hero = build(u)
        sc = bpy.context.scene
        kit.setup_render(sc, cam, scale=u, samples=a.samples, dof_target=hero)
        sc.render.resolution_percentage = a.res
        hero.data.materials[0] = hero_material(u)
        stats = kit.apply(scale=u, region=(-20 * u, -8 * u, 20 * u, 22 * u), lod_origin=(cam.location.x, cam.location.y))
        print("STATS", stats)
        bpy.ops.wm.save_as_mainfile(filepath=str(out / "kit-after.blend"))
        t = render(out / "kit-after.jpg")
        print("AFTER render s", round(t, 1))
    if a.only is None:
        side_by_side(out / "kit-before.jpg", out / "kit-after.jpg", out / "kit-side-by-side.jpg")


main()
