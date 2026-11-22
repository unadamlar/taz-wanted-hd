# Blender: exports a dressed level as look data, format version 3 (see FORMAT.md).
# usage: blender -b extracted/look/pass3/zoohub-dressed.blend --factory-startup --python-exit-code 1 \
#          -P tools/look/export.py -- --level zoohub|cityhub [--rebake]
# Writes extracted/look/runtime/scene<NN>/ atomically. Bakes are cached in extracted/look/runtime/.bake/.
# Game space is worldview.py's inverse: Blender (x, y, z) * 250 -> game (x, z, y).
import argparse, collections, ctypes, fnmatch, json, math, os, random, shutil, struct, sys, time
import bmesh, bpy
import numpy as np
from mathutils import Matrix, Vector, noise as mnoise

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import bake, dds, dress, kit

a = argparse.ArgumentParser()
a.add_argument("--level", default="zoohub")
a.add_argument("--runtime", default=None, help="output folder (default extracted/look/runtime)")
a.add_argument("--rebake", action="store_true")
args = a.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
LEVEL = dress.select(args.level)
args.scene = LEVEL["scene"]

K = 250.0
CHUNK = 1500.0  # game units (6 Blender units)
SPLIT = 4000  # one-off meshes above this many triangles are cut along the chunk grid
S = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
SC = dress.SCALE
root = next(p for p in [os.path.join(here, *([".."] * n)) for n in range(1, 7)] if os.path.isdir(os.path.join(p, "extracted", "textures")))
ext = os.path.join(root, "extracted")
base = args.runtime or os.path.join(ext, "look", "runtime")
cache = os.path.join(ext, "look", "runtime", ".bake" if args.level == "zoohub" else ".bake-" + args.level)
out = os.path.join(base, "scene%02d" % args.scene)
tmp = out + ".tmp%d" % os.getpid()
if args.rebake:
    shutil.rmtree(cache, ignore_errors=True)
os.makedirs(cache, exist_ok=True)
for stale in os.listdir(base):
    if stale.startswith(os.path.basename(out) + ".tmp"):
        shutil.rmtree(os.path.join(base, stale))
os.makedirs(os.path.join(tmp, "tex"))
kit.USE_ASSETS = True
sc = bpy.context.scene
for img in bpy.data.images:  # blends saved on another machine keep that machine's absolute paths
    if img.source == "FILE" and "/personal-games/" in img.filepath:
        img.filepath = os.path.join(os.path.dirname(kit.ASSET_LIB), img.filepath.split("/personal-games/", 1)[1])
        img.reload()
bake.use_gpu(sc)
LV = LEVEL["look"]

# ---------------------------------------------------------------- materials
# name: (bake graph, tile in Blender units, px, vertical bake plane)
TILES = {
    "dirt": (lambda: kit.mat_dirt(scale=SC), 2 * 2.4 * SC, 2048, False),
    "lawn": (lambda: kit.mat_grass_ground(scale=SC), 2 * 2.4 * SC, 1024, False),
    "brick": (lambda: kit.mat_brick(scale=SC), 4.6 * SC, 2048, True),
    "trim": (lambda: kit.mat_trim_stone(scale=SC), 2.6 * SC, 1024, True),
    "cliff": (lambda: kit.mat_sandstone(kit.srgb("#d98e62"), SC, 0.7, drips=False, base_dark=False), 2 * 3.0 * SC, 2048, True),
    "wood": (lambda: kit.mat_wood(scale=SC), 3.0, 1024, True),
    "bark": (lambda: kit.mat_bark(scale=SC), 1.2 * SC, 1024, True),
    "boulder": (lambda: kit.mat_boulder_dry(SC), 2 * 1.4 * SC, 1024, True),
}
TRIPLANAR, TWO_SIDED, WIND = 1, 2, 4
OPAQUE, CARD, GRASS, WATER = 0, 1, 2, 3
# foliage tints stand in for the kit's small emission term, which has no slot here
MATS = {  # name: albedo, has normal, kind, flags, tile (game units, 0 = mesh UVs), tint, rough, normal strength, alpha cut
    "dirt": ("dirt", True, OPAQUE, 0, TILES["dirt"][1] * K, (1, 1, 1), 0.88, 1.0, 0),
    "lawn": ("lawn", True, OPAQUE, 0, TILES["lawn"][1] * K, (1, 1, 1), 0.92, 1.0, 0),
    "brick": ("brick", True, OPAQUE, TRIPLANAR, TILES["brick"][1] * K, (1, 1, 1), 0.85, 1.0, 0),
    "trim": ("trim", True, OPAQUE, TRIPLANAR, TILES["trim"][1] * K, (1, 1, 1), 0.8, 1.0, 0),
    "cliff": ("cliff", True, OPAQUE, TRIPLANAR, TILES["cliff"][1] * K, (1, 1, 1), 0.9, 1.0, 0),
    "boulder": ("boulder", True, OPAQUE, TRIPLANAR, TILES["boulder"][1] * K, (1, 1, 1), 0.8, 1.0, 0),
    "bark": ("bark", True, OPAQUE, TRIPLANAR, TILES["bark"][1] * K, (1, 1, 1), 0.85, 1.0, 0),
    "wood": ("wood", True, OPAQUE, 0, 0.0, (1, 1, 1), 0.75, 1.0, 0),
    "water_bed": ("dirt", True, OPAQUE, TRIPLANAR, TILES["dirt"][1] * K, (0.42, 0.55, 0.56), 0.9, 0.6, 0),
    "water": ("", True, WATER, 0, 2.5 * SC * K, kit.srgb("#2aa6c8"), 0.03, 0.5, 0),
    "foam": ("foam", False, CARD, TWO_SIDED, 0.0, (1, 1, 1), 0.5, 0, 0.5),
    "leaves": ("leaves", False, CARD, TWO_SIDED | WIND, 0.0, (1.08, 1.08, 1.08), 0.75, 0, 0.5),
    "ivy": ("ivy", False, CARD, TWO_SIDED | WIND, 0.0, (1.08, 1.08, 1.08), 0.6, 0, 0.5),
    "leaf_core": ("", False, OPAQUE, 0, 0.0, (1.08, 1.08, 1.08), 0.75, 0, 0),
    "grass": ("", False, GRASS, TWO_SIDED | WIND, 0.0, (1.05, 1.05, 1.05), 0.7, 0, 0),
    "flat": ("", False, OPAQUE, TWO_SIDED, 0.0, (1, 1, 1), 0.7, 0, 0),
    "flat_wind": ("", False, OPAQUE, TWO_SIDED | WIND, 0.0, (1, 1, 1), 0.7, 0, 0),
}
for name, t in LEVEL.get("tiles", {}).items():
    TILES[name] = ((lambda n=name, t=t: kit.mat_texset(t.get("set", n), SC, t["period"], t.get("sat", 1.0), t.get("val", 1.0),
                                                       t.get("tint", (1.0, 1.0, 1.0)), t["rough"])), t["period"] * SC, t["px"], False)
    MATS[name] = (name, True, OPAQUE, TRIPLANAR if t.get("triplanar") else 0, TILES[name][1] * K, (2, 2, 2) if "detail" in t else (1, 1, 1),
                  t["rough"], t.get("normal", 1.0), 0)
for name, (tint, rough) in LEVEL.get("flats", {}).items():
    MATS[name] = ("", False, OPAQUE, 0, 1000.0, tint, rough, 0, 0)
if "skin" in LEVEL:  # wrinkled hide for untextured characters, mapped on their bind pose
    MATS["skin"] = ("skin", False, OPAQUE, 0, LEVEL["skin"]["tile"], (1, 1, 1), 0.6, 0, LEVEL["skin"]["grain"])
for name, tint in LEVEL.get("tints", {}).items():
    MATS[name] = (*MATS[name][:5], tint, *MATS[name][6:])
if "materials" in LEVEL:  # a level loads only what it uses
    MATS["paint"] = ("", False, OPAQUE, 0, 1000.0, (0.86, 0.88, 0.92), 0.6, 0, 0)  # road markings, kept white
    MATS = {n: m for n, m in MATS.items() if n in LEVEL["materials"]}
    TILES = {n: t for n, t in TILES.items() if n in MATS}
MAT_ID = {n: i for i, n in enumerate(MATS)}
BLENDER_MAT = {
    "kit_grass_blades": "grass", "kit_foliage": "leaf_core", "kit_foliage_cards": "leaves", "kit_ivy": "ivy",
    "kit_wood": "wood", "kit_bark": "bark", "kit_boulder_dry": "boulder", "kit_sandstone_mass": "cliff",
    "kit_water_bed": "water_bed", "kit_foam": "foam", "kit_pebble": "flat", "kit_stem": "flat_wind",
    "kit_petal_pink": "flat_wind", "kit_petal_white": "flat_wind", "kit_petal_blue": "flat_wind",
    "kit_flower_center": "flat_wind", "kit_weed_leaf": "flat_wind",
}


def format_mat(name):
    if name in BLENDER_MAT:
        return BLENDER_MAT[name]
    if name.startswith("kit_leaf_"):
        return "flat"
    if name.startswith("kit_water_clear"):
        return "water"
    raise KeyError("no look material for " + name)


# ---------------------------------------------------------------- textures
tex_bytes = {}


def put_tex(name, chain, fourcc):
    tex_bytes[name] = dds.write_dxt(os.path.join(tmp, "tex", name + ".dds"), chain, fourcc)


def put_normal(name, nor):
    h, w = nor.shape[:2]
    # DXT5nm: x in alpha, y in green
    xy = np.dstack([np.zeros((h, w)), nor[..., 1], np.zeros((h, w)), nor[..., 0]])
    put_tex(name, dds.mips_data(xy.astype(np.float32)), b"DXT5")


def periodic_noise(n, power, seed):
    """Tileable noise in 0..1 with a 1/f^power spectrum."""
    f = np.fft.fftfreq(n)
    r = np.sqrt(f[:, None] ** 2 + f[None, :] ** 2)
    r[0, 0] = 1
    spec = np.fft.fft2(np.random.default_rng(seed).normal(size=(n, n))) / r ** power
    spec[0, 0] = 0
    a = np.fft.ifft2(spec).real
    return (a - a.min()) / (a.max() - a.min())


def card_tile(name, mat, opacity, px=1024):
    """Atlas for alpha cards: the kit graph baked over the UV square, cut by the set's opacity map."""
    alb, _ = bake.bake_tile(cache, name, mat, 1.0, px, overlap=0, seamless=False)
    img = bpy.data.images.load(str(kit.ASSET_LIB / opacity), check_existing=True)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    a_ = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a_)
    a_ = a_.reshape(h, w, 4)[::-1, :, 0]
    a_ = a_[(np.arange(px) * h // px)][:, (np.arange(px) * w // px)]
    rgb = dds.bleed(np.asarray(alb, np.float32), a_)
    return np.dstack([rgb, a_]).astype(np.float32)


t0 = time.time()
tile_mean = {}
for name, (graph, tile, px, vertical) in TILES.items():
    # the cliff graph's strata depend on height: bake it where the rock actually stands
    z0 = kit.world_bbox(bpy.data.objects["kit_cliff_mass"])[0].z if name == "cliff" else 0.0
    alb, nor = bake.bake_tile(cache, name, graph(), tile, px, vertical, z0=z0)
    alb, nor = np.asarray(alb, np.float32), np.asarray(nor, np.float32)
    tile_mean[name] = dds.to_linear(alb).reshape(-1, 3).mean(0)
    grain = LEVEL.get("tiles", {}).get(name, {}).get("detail")
    if grain:  # grey around 0.5, so the material's tint of 2 leaves the game's colour on average
        lin = dds.to_linear(alb).mean(2)
        alb = np.repeat(dds.to_srgb(np.clip(0.5 * (1 + grain * (lin / lin.mean() - 1)), 0, 1))[..., None], 3, 2).astype(np.float32)
    put_tex(name, dds.mips(np.dstack([alb, np.ones(alb.shape[:2])])), b"DXT1")
    put_normal(name + "_n", nor)
for name, mat, folder in (("leaves", kit._cards_mat, "leaves024"), ("ivy", kit._ivy_mat, "ivy017")):
    if name in MATS:
        set_ = kit.TEXSETS[folder]
        put_tex(name, dds.mips(card_tile(name, mat(SC) if name == "leaves" else mat(), f"{set_[0]}/{set_[2]}"), cut=0.5), b"DXT5")
if "water" in MATS:
    n = periodic_noise(512, 1.6, 5)
    gx, gy = (np.roll(n, -1, 1) - np.roll(n, 1, 1)) / 2, (np.roll(n, -1, 0) - np.roll(n, 1, 0)) / 2
    put_normal("water_n", np.dstack([gx * 12 + 1, gy * 12 + 1, np.ones((512, 512))]).clip(0, 2) / 2)
    foam_u = periodic_noise(256, 1.2, 6)
    fade = np.linspace(0, 1, 256)[:, None]  # shore at v = 1
    foam_a = np.clip(fade * 1.6 * (0.35 + foam_u), 0, 1)
    put_tex("foam", dds.mips(np.dstack([np.full((256, 256, 3), 0.97), foam_a]).astype(np.float32), cut=0.5), b"DXT5")
if "skin" in MATS:
    def creases(count, seed):
        """Tileable cracks between wobbly cells, wider along u (around the body): 0 on a crack, about 1 mid-cell."""
        pts = np.random.default_rng(seed).random((count, 2))
        v, u = np.mgrid[0:512, 0:512] / 512
        u = u + 0.09 * (periodic_noise(512, 2.2, seed + 1) - 0.5)
        v = v + 0.09 * (periodic_noise(512, 2.2, seed + 2) - 0.5)
        out = np.empty((512, 512), np.float32)
        for row in range(512):
            du, dv = np.abs(u[row, :, None] - pts[:, 0]) % 1, np.abs(v[row, :, None] - pts[:, 1]) % 1
            d = np.sqrt(np.partition(np.minimum(du, 1 - du) ** 2 / 2.2 + np.minimum(dv, 1 - dv) ** 2, 1, axis=1)[:, :2])
            out[row] = (d[:, 1] - d[:, 0]) * np.sqrt(count)
        return out
    h = 1 - 0.42 * np.exp(-creases(46, 21) / 0.05) - 0.2 * np.exp(-creases(420, 31) / 0.07) + 0.22 * (periodic_noise(512, 1.6, 10) - 0.5)
    shade = np.clip(0.5 * (1 + 0.9 * (h / h.mean() - 1)), 0, 1)  # read raw by the character shader
    put_tex("skin", dds.mips_data(np.dstack([shade, shade, shade, np.ones((512, 512))]).astype(np.float32)), b"DXT1")
print("export: textures %.1fs, %.1f MB" % (time.time() - t0, sum(tex_bytes.values()) / 1e6))

# ---------------------------------------------------------------- instances and prototypes
dg = bpy.context.evaluated_depsgraph_get()
scatter_names = {o.name for c in ("kit_grass", "kit_clutter") if c in bpy.data.collections for o in bpy.data.collections[c].objects}
scatter_names |= {o.name for o in bpy.data.objects if o.name.startswith(("kit_vines", "kit_ledge")) and o.type == "MESH"}
inst = collections.defaultdict(list)
for i in dg.object_instances:
    if i.is_instance and i.parent and i.parent.original.name in scatter_names:
        inst[i.object.original.name].append(np.array(i.matrix_world, np.float32))
props = [o for o in (bpy.data.collections["kit_props"].objects if "kit_props" in bpy.data.collections else []) if o.type == "MESH" and len(o.data.polygons)]


def game_rows(m):
    g = np.array(S) @ m @ np.array(S)
    r = g[:3].copy()
    r[:, 3] *= K
    return r.ravel()


MOSS = dds.to_linear(np.array([84, 112, 31]) / 255)  # the rock graph's moss, measured on the mass's top faces
TIP_RAMP = [(0.2, kit.srgb("#3f8f22")), (0.45, kit.srgb("#62b02e")), (0.75, kit.srgb("#86c63a")), (0.97, kit.srgb("#b2c94c"))]


def ramp(t):
    xs = [p for p, _ in TIP_RAMP]
    return np.array([np.interp(t, xs, [c[k] for _, c in TIP_RAMP]) for k in range(3)], np.float32)


# grass variants ordered by tip colour; instances pick by the kit's patch noise so the lawn keeps its colour patches
grass_names = sorted(n for n in inst if n.startswith("kit_v_grass"))
if grass_names:
    mats = [m for n in grass_names for m in inst[n]]
    rng = np.random.default_rng(11)
    v = np.array([(mnoise.noise(Vector(m[:3, 3]) * 0.3 / SC) + 1) / 2 * 0.8 for m in mats]) + rng.random(len(mats)) * 0.35
    order = np.argsort(v)
    for n in grass_names:
        inst[n] = []
    for rank, idx in enumerate(order):
        inst[grass_names[rank * len(grass_names) // len(order)]].append(mats[idx])


def smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


def srgb8(c):
    return np.rint(dds.to_srgb(np.clip(c, 0, 1)) * 255).astype(np.uint32)


def packed(c):
    q = srgb8(c)
    return 0xff000000 | q[..., 0] << 16 | q[..., 1] << 8 | q[..., 2]


# blades lose their middle ring: 5 triangles -> 3, same silhouette at game distances
for n in grass_names:
    me = bpy.data.objects[n].data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.dissolve_verts(bm, verts=[bm.verts[7 * b + k] for b in range(len(bm.verts) // 7) for k in (2, 3)])
    bm.to_mesh(me)
    bm.free()



# flat-coloured variants: albedo through Cycles into a corner colour attribute
flat = [bpy.data.objects[n] for n in sorted(inst) if not n.startswith(("kit_v_grass", "kit_v_bush", "kit_v_vine"))]
sc.cycles.samples = 4
bpy.ops.object.select_all(action="DESELECT")
for o in flat:
    if "look_bake" not in o.data.color_attributes:
        o.data.color_attributes.new("look_bake", "FLOAT_COLOR", "CORNER")
    o.data.color_attributes.active_color = o.data.color_attributes["look_bake"]
    if o.name not in bpy.context.view_layer.objects:
        sc.collection.objects.link(o)
    o.hide_set(False); o.hide_render = False; o.select_set(True)
bpy.context.view_layer.update()
bpy.context.view_layer.objects.active = flat[0]
bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, target="VERTEX_COLORS")


def corner_colors(o, co, grass_rank):
    """Linear RGB per corner: multiplies the albedo, or is the colour for materials without one."""
    me = o.data
    nl = len(me.loops)
    if o.name.startswith("kit_v_grass"):
        tip = np.empty(len(me.vertices), np.float32)
        me.attributes["kit_tip"].data.foreach_get("value", tip)
        vi = np.empty(nl, np.int32); me.loops.foreach_get("vertex_index", vi)
        t = (tip[vi] ** 0.8)[:, None]
        return np.array(kit.srgb("#1e4410"))[None] * (1 - t) + ramp(0.2 + 0.77 * (grass_rank + 0.5) / 8)[None] * t
    if "look_bake" in me.color_attributes:
        c = np.empty(nl * 4, np.float32)
        me.color_attributes["look_bake"].data.foreach_get("color", c)
        return c.reshape(-1, 4)[:, :3]
    if "kit_ao" in me.attributes:
        ao = np.empty(len(me.vertices), np.float32)
        me.attributes["kit_ao"].data.foreach_get("value", ao)
        vi = np.empty(nl, np.int32); me.loops.foreach_get("vertex_index", vi)
        ao = ao[vi][:, None]
        inner = np.array(kit.srgb("#1f4a14")) / np.array(kit.srgb("#58a52e"))  # cards' albedo already holds the leaf green
        wob = np.array([1 + 0.25 * mnoise.noise(Vector(p) * 0.6 / SC) for p in co[vi][::4]], np.float32).repeat(4)[:nl][:, None]
        return np.clip((ao + inner[None] * (1 - ao)) * wob, 0, 1)
    return np.ones((nl, 3), np.float32)


_ico = bmesh.new()
bmesh.ops.create_icosphere(_ico, subdivisions=2, radius=1)
ICO_V = np.array([v.co for v in _ico.verts], np.float32)[:, [0, 2, 1]]  # Blender -> game axes, like every mesh here
ICO_T = np.array([[l.vert.index for l in f.loops] for f in _ico.faces])
_ico.free()


def thin_cores(p, n, c, uv, m):
    """Canopy clumps are icospheres (320 triangles each) under the leaf cards: rebuild them with 80."""
    core = m == MAT_ID.get("leaf_core", -1)
    if not core.any():
        return p, n, c, uv, m
    cp = p[core].reshape(-1, 960, 3)  # one clump per 320 corners-triples, as _canopy_mesh emits them
    cen = cp.mean(1)
    rad = np.linalg.norm(cp - cen[:, None], axis=2).mean(1)
    cc = cen.mean(0)
    R = np.linalg.norm(cp - cc, axis=2).max()
    d = ICO_V[ICO_T.ravel()]
    q = cen[:, None] + rad[:, None, None] * d
    away = (q - cc) / np.maximum(np.linalg.norm(q - cc, axis=2, keepdims=True), 1e-6)
    nn = 0.6 * d + 0.4 * away
    nn /= np.linalg.norm(nn, axis=2, keepdims=True)
    ao = np.clip(0.35 + 0.65 * (away[..., 1] * 0.5 + 0.5) * np.minimum(1, np.linalg.norm(q - cc, axis=2) / R), 0, 1)[..., None]
    wob = np.array([1 + 0.25 * mnoise.noise(Vector(x) * 0.6 / (SC * K)) for x in cen], np.float32)[:, None, None]
    col = (np.array(kit.srgb("#58a52e"))[None, None] * ao + np.array(kit.srgb("#1f4a14"))[None, None] * (1 - ao)) * wob
    rest = ~core
    return (np.concatenate([q.reshape(-1, 3), p[rest]]), np.concatenate([nn.reshape(-1, 3), n[rest]]),
            np.concatenate([col.reshape(-1, 3), c[rest]]), np.concatenate([np.full((q.size // 3, 2), 0.5, np.float32), uv[rest]]),
            np.concatenate([np.full(q.size // 3, MAT_ID["leaf_core"]), m[rest]]))


def tris_of(o, world):
    """Corner arrays of an object in game space: (pos, normal, colour, uv, material id), three per triangle."""
    me = o.data
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    lt = np.empty(n * 3, np.int32); me.loop_triangles.foreach_get("loops", lt)
    mi = np.empty(n, np.int32); me.loop_triangles.foreach_get("material_index", mi)
    vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    cn = np.empty(len(me.loops) * 3, np.float32); me.corner_normals.foreach_get("vector", cn); cn = cn.reshape(-1, 3)
    uv = np.zeros((len(me.loops), 2), np.float32)
    if me.uv_layers:
        me.uv_layers[0].data.foreach_get("uv", uv.ravel())
        uv[:, 1] = 1 - uv[:, 1]  # Direct3D's v runs down from the image's top row
    rank = grass_names.index(o.name) if o.name in grass_names else 0
    col = corner_colors(o, co, rank)
    if o.name.startswith("kit_cliff_mass"):  # the graphs' moss on upward faces, as a tint over the tile
        key, amount = ("boulder", 0.5) if "rubble" in o.name else ("cliff", 1.0)
        t = (smooth(cn[:, 2], 0.55, 0.8) * amount)[:, None]
        col = col * (1 - t) + np.clip(MOSS / tile_mean[key], 0, 1)[None] * t
    M = np.array(S @ o.matrix_world if world else S, np.float32)
    pos = (co[vi] @ M[:3, :3].T + M[:3, 3]) * K
    N = np.linalg.inv(M[:3, :3]).T
    nor = cn @ N.T
    if o.name.startswith("kit_v_grass"):  # the kit's mostly-up shading normal: a lawn lights as one soft surface
        nor = nor / np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-9) * 0.35 + [0, 1, 0]
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-9)
    ids = np.array([MAT_ID[format_mat(m.name)] for m in me.materials], np.int32)[mi] if me.materials else np.zeros(n, np.int32)
    if "kit_gdir" in me.attributes:  # fences: planks' UVs run along the grain, one repeat per wood tile
        gd = np.empty(len(me.vertices) * 3, np.float32); me.attributes["kit_gdir"].data.foreach_get("vector", gd)
        gd = gd.reshape(-1, 3)[vi] @ M[:3, :3].T
        gd /= np.maximum(np.linalg.norm(gd, axis=1, keepdims=True), 1e-9)
        side = np.cross(gd, nor)
        tile = TILES["wood"][1] * K
        uv = np.stack([(pos * gd).sum(1), (pos * side).sum(1)], 1) / tile
    return thin_cores(pos[lt], nor[lt], col[lt], uv[lt], ids.repeat(3))


def weld(p, n, c, uv, m):
    """Corners -> unique vertices + triangles sorted by material."""
    order = np.argsort(m[::3], kind="stable")
    idx = np.stack([order * 3, order * 3 + 1, order * 3 + 2], 1).ravel()
    p, n, c, uv, m = p[idx], n[idx], c[idx], uv[idx], m[idx]
    key = np.hstack([np.round(p, 2), np.round(n, 3), np.round(c, 3), np.round(uv, 4), m[:, None]])
    uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    subs, start = [], 0
    for mid in np.unique(m):
        k = int((m == mid).sum())
        subs.append((int(mid), start, k))
        start += k
    return p[first], n[first], c[first], uv[first], inv.ravel().astype(np.uint32), subs


protos = []  # dict(v, i, subs, lo, hi, name)
place = []  # (proto index, rows or None for identity)


def add_proto(name, p, n, c, uv, m):
    v, vn, vc, vuv, ix, subs = weld(p, n, c, uv, m)
    protos.append(dict(name=name, p=v, n=vn, c=packed(vc), uv=vuv, ix=ix, subs=subs))
    return len(protos) - 1


for name in sorted(inst):
    o = bpy.data.objects[name]
    pi = add_proto(name, *tris_of(o, False))
    place.append((pi, [game_rows(m) for m in inst[name]]))

for o in props:
    p, n, c, uv, m = tris_of(o, True)
    ntri = len(p) // 3
    if ntri > SPLIT:
        cen = p.reshape(-1, 3, 3).mean(1)
        cell = (np.floor(cen[:, 0] / CHUNK).astype(np.int64) << 32) + np.floor(cen[:, 2] / CHUNK).astype(np.int64)
        for cid in np.unique(cell):
            t = np.where(cell == cid)[0]
            k = np.stack([t * 3, t * 3 + 1, t * 3 + 2], 1).ravel()
            place.append((add_proto("%s.%d" % (o.name, cid & 0xffff), p[k], n[k], c[k], uv[k], m[k]), None))
    else:
        place.append((add_proto(o.name, p, n, c, uv, m), None))

# game water faces (their texture is hidden below): same positions, drawn with the water material
water = []
for o in bpy.data.objects:
    if o.type != "MESH" or not any(s.material and s.material.name.startswith("kit_water_clear") for s in o.material_slots):
        continue
    me = o.data
    me.calc_loop_triangles()
    mi = np.empty(len(me.loop_triangles), np.int32); me.loop_triangles.foreach_get("material_index", mi)
    slot_water = np.array([bool(s.material and s.material.name.startswith("kit_water_clear")) for s in o.material_slots])
    tv = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", tv)
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    M = np.array(S @ o.matrix_world, np.float32)
    w = (co.reshape(-1, 3)[tv.reshape(-1, 3)[slot_water[mi]].ravel()] @ M[:3, :3].T + M[:3, 3]) * K
    if "@placed" in o.name and np.ptp(w[:, 1]) > 10:  # a floating log's wet underside, not a water surface
        continue
    water.append(w)
if water:
    wp = np.concatenate(water)
    # the capture repeats draws (hero + sweep): keep one copy of each triangle
    t = wp.reshape(-1, 3, 3)
    _, u = np.unique(np.round(np.sort(t.reshape(-1, 3, 3), axis=1), 1).reshape(-1, 9), axis=0, return_index=True)
    wp = t[np.sort(u)].reshape(-1, 3)
    wn = np.tile([0, 1, 0], (len(wp), 1)).astype(np.float32)
    place.append((add_proto("water_surface", wp, wn, np.ones((len(wp), 3), np.float32),
                            wp[:, [0, 2]] / MATS["water"][4], np.full(len(wp), MAT_ID["water"])), None))
    water_y = float(np.median(wp[:, 1]))
else:
    water_y = 0.0

# The dressing hides a fence texture only near kit fences, but the game can only hide a whole texture:
# faces that stayed visible are redrawn from the look data with the same HD texture.
HIDDEN_ROLES = ("hide", "fence_rail", "fence_post", "fence_cap", "tree", "water", "sky")
kept = collections.defaultdict(list)
for coll in dress.GAME_COLLS:
    for o in (bpy.data.collections[coll].objects if coll in bpy.data.collections else []):
        if o.type != "MESH" or o.hide_render:
            continue
        for si, slot in enumerate(o.material_slots):
            m = slot.material
            if m and m.name.startswith(("lit:", "lit+:")) and dress.role_of(m.name.split(":", 1)[1]) in HIDDEN_ROLES:
                kept[dress.base_name(m.name.split(":", 1)[1])].append((o, si, m))
for label, users in sorted(kept.items()):
    corners = []
    for o, si, _ in users:
        me = o.data
        me.calc_loop_triangles()
        mi = np.empty(len(me.loop_triangles), np.int32); me.loop_triangles.foreach_get("material_index", mi)
        lt = np.empty(len(mi) * 3, np.int32); me.loop_triangles.foreach_get("loops", lt)
        lt = lt.reshape(-1, 3)[mi == si].ravel()
        vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
        cn = np.empty(len(me.loops) * 3, np.float32); me.corner_normals.foreach_get("vector", cn)
        uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers["UVMap"].data.foreach_get("uv", uv)
        vc = np.empty(len(me.loops) * 4, np.float32); me.color_attributes["kit_vcol"].data.foreach_get("color", vc)
        M = np.array(S @ o.matrix_world, np.float32)
        P = (co.reshape(-1, 3)[vi[lt]] @ M[:3, :3].T + M[:3, 3]) * K
        N = cn.reshape(-1, 3)[lt] @ np.linalg.inv(M[:3, :3])
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        U = uv.reshape(-1, 2)[lt] * [1, -1] + [0, 1]
        corners.append((P, N, np.minimum(vc.reshape(-1, 4)[lt, :3] * 2, 1), U))  # world draws are modulate 2x
    P, N, C, U = (np.concatenate(x) for x in zip(*corners))
    if not len(P):
        continue
    img = next(n.image for n in users[0][2].node_tree.nodes if n.type == "TEX_IMAGE" and n.image)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    rgba = px.reshape(h, w, 4)[::-1].copy()
    card = bool((rgba[..., 3] < 0.5).any())
    if card:
        rgba[..., :3] = dds.bleed(rgba[..., :3], rgba[..., 3])
    name = "game_" + label.rsplit("/", 1)[1][:26]
    put_tex(name, dds.mips(rgba, cut=0.5 if card else None), b"DXT5" if card else b"DXT1")
    MATS[name] = (name, False, CARD if card else OPAQUE, TWO_SIDED, 0.0, (1, 1, 1), 0.7, 0, 0.5 if card else 0)
    MAT_ID[name] = len(MAT_ID)
    _, u = np.unique(np.round(P.reshape(-1, 9), 1), axis=0, return_index=True)  # hero and sweep captures repeat draws
    k = (np.sort(u)[:, None] * 3 + [0, 1, 2]).ravel()
    place.append((add_proto(name, P[k], N[k], C[k], U[k], np.full(len(k), MAT_ID[name])), None))
    print("export: kept %s, %d triangles" % (name, len(k) // 3))


def wire_tube(path, side, up, r):
    """Three-sided tube along a path: triangles of positions and normals."""
    a = np.arange(3) * 2 * np.pi / 3
    spoke = np.cos(a)[:, None] * side + np.sin(a)[:, None] * up
    ring = path[:, None] + r * spoke
    I, J = np.arange(len(path) - 1)[:, None], np.arange(3)[None]
    corners = [(I + di, (J + dj) % 3) for di, dj in ((0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1))]
    p = np.stack([ring[i, j] for i, j in corners], 2).reshape(-1, 3, 3)
    n = np.stack([np.broadcast_to(spoke[j], (len(I), 3, 3)) for _, j in corners], 2).reshape(-1, 3, 3)
    return p, n


def wire_barb(c, axis, side, up, turn):
    """A wrap around the wire and four spikes."""
    parts = [wire_tube(np.array([c - axis * 3, c + axis * 3]), side, up, 2.8)]
    for k in range(4):
        t = turn + k * np.pi / 2
        d = np.cos(t) * side + np.sin(t) * up + (0.35 if k % 2 else -0.35) * axis
        d /= np.linalg.norm(d)
        e1 = np.cross(d, axis); e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        a = np.arange(3) * 2 * np.pi / 3
        base = c + 1.3 * (np.cos(a)[:, None] * e1 + np.sin(a)[:, None] * e2)
        p = np.stack([base, np.roll(base, -1, 0), np.tile(c + d * 13, (3, 1))], 1)
        f = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        f *= np.sign((f * (p.mean(1) - c)).sum(1, keepdims=True)) / np.linalg.norm(f, axis=1, keepdims=True)
        parts.append((p, np.repeat(f[:, None], 3, 1)))
    return parts


def barbed_wire(o):
    """Real twisted wire along the rows the game paints on its flat strips, which the look hides."""
    me = o.data
    M = np.array(S @ o.matrix_world, np.float64)
    uv = me.uv_layers[0].data
    tris = {}
    for f in me.polygons:
        c = [((np.array(me.vertices[me.loops[l].vertex_index].co) @ M[:3, :3].T + M[:3, 3]) * K, tuple(uv[l].uv)) for l in f.loop_indices]
        tris[tuple(sorted(tuple(np.round(q, 1)) for q, _ in c))] = c
    tris, quads, used = list(tris.items()), [], set()
    for i, (ka, a) in enumerate(tris):
        for j, (kb, b) in enumerate(tris[i + 1:], i + 1):
            if i not in used and j not in used and len(set(ka) & set(kb)) == 2:
                used |= {i, j}
                quads.append({(u[0] > 0.5, u[1] > 0.28): q for q, u in a + b})
    parts = []
    for q in quads:
        for row in (0.3, 0.8):
            a, b = (q[(s, False)] * (1 - row) + q[(s, True)] * row for s in (False, True))
            L = np.linalg.norm(b - a)
            axis = (b - a) / L
            side = np.cross(axis, (0, 1, 0)); side /= np.linalg.norm(side)
            up = np.cross(side, axis)
            t = np.linspace(0, 1, max(8, int(L / 6)) + 1)
            mid = a + (b - a) * t[:, None] - [0, 1, 0] * (5 * 4 * t * (1 - t))[:, None]  # a little slack
            for phase in (0, np.pi):
                w = 2 * np.pi * L * t / 36 + phase
                parts.append(wire_tube(mid + 1.6 * (np.cos(w)[:, None] * side + np.sin(w)[:, None] * up), side, up, 1.6))
            for s in np.arange(36, L - 12, 72):
                parts += wire_barb(mid[int(s / L * (len(t) - 1))], axis, side, up, s)
    p, n = (np.concatenate(x).astype(np.float32) for x in zip(*parts))
    flip = (np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]) * n.mean(1)).sum(1) > 0  # game space winding
    p[flip], n[flip] = p[flip][:, [0, 2, 1]], n[flip][:, [0, 2, 1]]
    print("export: barbed wire, %d strips, %d triangles" % (len(quads), len(p)))
    p, n = p.reshape(-1, 3), n.reshape(-1, 3)
    return add_proto("barbed_wire", p, n, np.ones_like(p), np.zeros((len(p), 2), np.float32), np.full(len(p), MAT_ID["steel"]))


if "wire" in LEVEL:
    place.append((barbed_wire(bpy.data.objects[LEVEL["wire"]]), None))

# chunks: instance centre -> grid cell; each cell lists (proto, matrices), shuffled for thinning
cells = collections.defaultdict(lambda: collections.defaultdict(list))
boxes = {}
IDENT = np.array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0], np.float32)
for pi, rows in place:
    P = protos[pi]["p"]
    lo, hi = P.min(0), P.max(0)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    for r in (rows if rows is not None else [IDENT]):
        R = np.asarray(r).reshape(3, 4)
        w = corners @ R[:3, :3].T + R[:3, 3]
        cen = w.mean(0)
        cell = (int(cen[0] // CHUNK), int(cen[2] // CHUNK))
        cells[cell][pi].append(np.asarray(r, np.float32))
        b = boxes.get(cell)
        boxes[cell] = (np.minimum(b[0], w.min(0)), np.maximum(b[1], w.max(0))) if b else (w.min(0), w.max(0))
rng = random.Random(1)
for cell in cells.values():
    for runs in cell.values():
        rng.shuffle(runs)

# ---------------------------------------------------------------- game textures -> materials, from RULES
fp = {}
for line in open(os.path.join(ext, "textures", "fingerprints.tsv")):
    h, f = line.rstrip("\n").split("\t")[:2]
    fp.setdefault(f, int(h, 16))
hide, shade, binds, glows, hash_of = set(), set(), {}, {}, {}


def tex_pixels(file):
    img = bpy.data.images.load(os.path.join(ext, "textures", file), check_existing=True)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[..., :3]


def kit_trim_mask(srgb):
    """kit.light_mask_node on the texture as Blender sees it (linear)."""
    lin = dds.to_linear(srgb)
    lum = lin @ np.array([0.3, 0.59, 0.11])
    sat = lin.max(2) - lin.min(2)
    return smooth(lum, 0.55, 0.7) * (1 - smooth(sat, 0.25, 0.45))


mask_report = []


def brick_binds(fprint, file):
    """Brick where the game paints brick, trim where the kit's pale-and-unsaturated test says so,
    fitted to a threshold on the raw texture's lowest channel (pale colours have no low channel)."""
    px = tex_pixels(file)
    want = kit_trim_mask(px)
    low = px.min(2)
    if want.mean() < 0.01:
        return [(fprint, MAT_ID["brick"], 0, 0.0, 1.0)]
    best = min(np.arange(0.3, 0.98, 0.02), key=lambda t: np.abs(smooth(low, t - 0.05, t + 0.05) - want).mean())
    err = float(np.abs(smooth(low, best - 0.05, best + 0.05) - want).mean())
    mask_report.append((file, float(want.mean()), float(best), err))
    return [(fprint, MAT_ID["brick"], 3, float(best + 0.05), float(best - 0.05)),
            (fprint, MAT_ID["trim"], 3, float(best - 0.05), float(best + 0.05))]


REDDER = (-0.14, -0.05)  # r - g on the raw texture; the kit's "green dominates" edge lands here
for line in list(open(os.path.join(ext, "textures", "index.tsv")))[1:]:
    pak, name, w_, h_, f = line.rstrip("\n").split("\t")
    if f not in fp or not (pak.startswith(LEVEL["pak"]) or pak == "resTex"):
        continue
    label = pak + "/" + os.path.splitext(name)[0]
    role = dress.role_of(label)
    h = hash_of[label] = fp[f]
    for pat, power, span in LEVEL.get("glow", ()):
        if fnmatch.fnmatch(label, pat):
            glows[h] = (power, *(span or (0.0, 1.0)), 2 if span else 0)
            break
    if "shadowsub" in label:
        shade.add(h)
    elif role in HIDDEN_ROLES or label == LEVEL.get("wire"):
        hide.add(h)
    elif h in binds:
        continue
    elif role == "lit" and any(fnmatch.fnmatch(label, pat) for pat, _ in LEVEL.get("detail", ())):
        binds[h] = [(h, MAT_ID[next(m for pat, m in LEVEL["detail"] if fnmatch.fnmatch(label, pat))], 4, -1.0, 0.0)]
    elif role in LEVEL.get("binds", ()):
        binds[h] = [(h, MAT_ID[m], mask, lo, hi) for m, mask, lo, hi in LEVEL["binds"][role]]
    elif role == "ground":
        binds[h] = [(h, MAT_ID["dirt"], 1, *REDDER)]
    elif role == "lawn":
        binds[h] = [(h, MAT_ID["lawn"], 0, 0.0, 1.0)]
    elif role == "cliff":
        binds[h] = [(h, MAT_ID["cliff"], 0, 0.0, 1.0)]
    elif role == "brick":
        binds[h] = brick_binds(h, f)
bind_list = [b for h in sorted(binds) for b in binds[h]]
swaps = sorted({(hash_of[n], *(np.array((S @ o.matrix_world).translation) * K))
                for o in bpy.data.objects if o.get("kit_replaced") for s in o.material_slots if s.material
                for n in [dress.base_name(s.material.name.split(":", 1)[-1])]
                if any(fnmatch.fnmatch(n, p) for p in LEVEL["trees"])})



def level_lights(cfg):
    """Lamps from the objects carrying a lamp-role texture, plus the pools of warm light baked into the game's
    vertices that no lamp explains (shop fronts, doors). Game space, as the file stores them."""
    colour = np.array(kit.srgb(cfg["color"]))
    tops, warm, wts = {}, [], []
    for coll in dress.GAME_COLLS:
        for o in (bpy.data.collections[coll].objects if coll in bpy.data.collections else []):
            if o.type != "MESH" or not len(o.data.polygons):
                continue
            if any(s.material and dress.role_of(s.material.name.split(":", 1)[-1]) == "lamp" for s in o.material_slots):
                lo, hi = kit.world_bbox(o)
                tops[(round((lo.x + hi.x) / 2), round((lo.y + hi.y) / 2))] = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z - cfg["drop"])
            if "game_color" not in o.data.color_attributes or o.data.color_attributes["game_color"].domain != "CORNER":
                continue
            me = o.data
            c = np.empty(len(me.loops) * 4, np.float32); me.color_attributes["game_color"].data.foreach_get("color", c)
            c = c.reshape(-1, 4)[:, :3]
            vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
            co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
            n = np.empty(len(me.loops) * 3, np.float32); me.corner_normals.foreach_get("vector", n)
            M = np.array(o.matrix_world, np.float32)
            n = n.reshape(-1, 3) @ M[:3, :3].T
            k = (c[:, 0] > c[:, 2] * 1.5) & (c[:, 0] > 0.3) & (n[:, 2] > 0.5 * np.linalg.norm(n, axis=1))
            if k.any():
                warm.append(co.reshape(-1, 3)[vi[k]] @ M[:3, :3].T + M[:3, 3])
                wts.append(c[k, 0] - c[k, 2])
    lamps = list(tops.values())
    out = [((x, z, y), cfg["radius"], colour * cfg["power"], cfg["cone"]) for x, y, z in lamps]
    if warm:
        p, w = np.concatenate(warm), np.concatenate(wts)
        if lamps:
            far = np.hypot(p[:, 0, None] - np.array(lamps)[:, 0], p[:, 1, None] - np.array(lamps)[:, 1]).min(1) > 7
            p, w = p[far], w[far]
        cells = collections.defaultdict(list)
        for i, q in enumerate(np.floor(p[:, :2] / 5).astype(int)):
            cells[tuple(q)].append(i)
        for ix in cells.values():
            if w[ix].sum() < 2.0:   # a stray warm vertex is not a light
                continue
            q = np.average(p[ix], 0, weights=w[ix])
            out.append(((q[0], q[2] + cfg["pool_height"], q[1]), cfg["pool_radius"], colour * cfg["pool_power"], cfg["pool_cone"]))
    print("export: %d lamps, %d baked pools" % (len(lamps), len(out) - len(lamps)))
    return [(*(np.array(p) * K), r * K, *c, cone) for p, r, c, cone in out[:64]]


lights = level_lights(LEVEL["lamps"]) if "lamps" in LEVEL else []

# ---------------------------------------------------------------- sky
eye = bpy.data.objects["hero camera"].matrix_world.translation.copy() if "hero camera" in bpy.data.objects else Vector()
sky = np.asarray(bake.bake_sky(cache, sc, eye, panels=LEVEL.get("sky_panels", False)), np.float32)
sky_scale = max(1.0, float(np.quantile(sky, 0.9999)))
faces = [np.asarray(dds.to_srgb(f / sky_scale), np.float32) for f in bake.cube_faces(sky, 1024)]
sky_bytes = dds.write_cube(os.path.join(tmp, "sky.dds"), faces)

# ---------------------------------------------------------------- scene.bin


def name32(s):
    b = s.encode()
    if len(b) > 31:
        raise ValueError("name too long: " + s)
    return b.ljust(32, b"\0")


with open(os.path.join(tmp, "scene.bin"), "wb") as f:
    f.write(struct.pack("<4sI", b"TZLK", 3))
    for s_ in (hide, shade):
        f.write(struct.pack("<I", len(s_)) + b"".join(struct.pack("<Q", h) for h in sorted(s_)))
    f.write(struct.pack("<I", len(MATS)))
    for n, (alb, has_n, kind, flags, tile, tint, rough, ns, cut) in MATS.items():
        nrm = "water_n" if n == "water" else (alb + "_n" if has_n else "")
        f.write(name32(n) + name32(alb) + name32(nrm))
        f.write(struct.pack("<HHf3ffff", kind, flags, tile, *tint, rough, ns, cut))
    f.write(struct.pack("<I", len(bind_list)))
    for fprint, mid, mask, lo, hi in bind_list:
        f.write(struct.pack("<QIIff", fprint, mid, mask, lo, hi))
    f.write(struct.pack("<I", len(protos)))
    vt = np.dtype([("p", "<f4", 3), ("n", "<f4", 3), ("c", "<u4"), ("uv", "<f4", 2)])
    for P in protos:
        f.write(struct.pack("<III", len(P["p"]), len(P["ix"]), len(P["subs"])))
        v = np.zeros(len(P["p"]), vt)
        v["p"], v["n"], v["c"], v["uv"] = P["p"], P["n"], P["c"], P["uv"]
        f.write(v.tobytes())
        f.write(P["ix"].astype("<u4").tobytes())
        for sub in P["subs"]:
            f.write(struct.pack("<III", *sub))
    f.write(struct.pack("<I", len(cells)))
    for cell, runs in sorted(cells.items()):
        lo, hi = boxes[cell]
        f.write(struct.pack("<6fI", *lo, *hi, len(runs)))
        for pi, rows in sorted(runs.items()):
            f.write(struct.pack("<II", pi, len(rows)))
            f.write(np.stack(rows).astype("<f4").tobytes())
    if lights or glows or swaps:  # optional sections, absent for a level without local lights
        f.write(struct.pack("<I", len(lights)) + b"".join(struct.pack("<8f", *l) for l in lights))
        f.write(struct.pack("<I", len(glows)) + b"".join(struct.pack("<Q3fI", h, *glows[h]) for h in sorted(glows)))
        f.write(struct.pack("<I", len(swaps)) + b"".join(struct.pack("<Q4f", *s_, 2.0) for s_ in swaps))

# ---------------------------------------------------------------- level.ini
sun, grade, sk = LV["sun"], LV["grade"], LV["sky"]
az, el = math.radians(sun["sun_azimuth"]), math.radians(sun["sun_elevation"])
amb = np.array(kit.srgb(sk["ambient"])) * grade["ambient_strength"]
fog_start = grade["fog_start"] * SC * K
vals = [
    ("sun_dir", (math.cos(az) * math.cos(el), math.sin(el), math.sin(az) * math.cos(el))),
    ("sun_color", np.array(kit.srgb(sun["sun_color"])) * sun["sun_strength"] / math.pi),
    ("sky_ambient", amb), ("ground_ambient", amb * np.array((0.55, 0.47, 0.38))),
    ("shadow_softness", math.tan(math.radians(1.0))), ("ao_radius", 2.5 * SC * K), ("ao_strength", 1.0),
    ("fog_color", kit.srgb("#b8d6f2")), ("fog_start", fog_start),
    ("fog_end", fog_start + grade["fog_depth"] * SC * K / grade["fog"]),  # Blender's fog tops out at this 7%
    ("exposure", 2 ** grade["exposure"]), ("bloom_threshold", 0.9), ("bloom_strength", grade["bloom"]),
    ("saturation", grade["saturation"]), ("contrast", 1.15),
    ("water_height", water_y), ("water_color", kit.srgb("#2aa6c8")), ("water_clarity", 0.72),
    ("grass_fade_start", 5000.0), ("grass_fade_end", 10000.0), ("sky_scale", sky_scale * LEVEL.get("sky_gain", 1.0)),
] + [(k, LEVEL[k]) for k in ("unbake", "char_fill") if k in LEVEL]
with open(os.path.join(tmp, "level.ini"), "w") as f:
    f.write("[level]\n")
    for k, x in vals:
        f.write("%s = %s\n" % (k, " ".join("%.5f" % c for c in x) if hasattr(x, "__len__") else "%.5f" % x))

# ---------------------------------------------------------------- atomic swap


def swap(new, old):
    if not os.path.exists(old):
        return os.rename(new, old)
    if ctypes.CDLL(None, use_errno=True).renameat2(-100, new.encode(), -100, old.encode(), 2):  # RENAME_EXCHANGE
        raise OSError(ctypes.get_errno(), "renameat2")
    shutil.rmtree(new)


tris = sum(len(protos[pi]["ix"]) // 3 * len(r if r is not None else [0]) for pi, r in place)
ninst = sum(len(r) for _, r in place if r is not None)
report = dict(triangles=int(tris), instances=int(ninst), protos=len(protos), chunks=len(cells), materials=len(MATS),
              binds=len(bind_list), lights=len(lights), glows=len(glows), hidden=len(hide), shade=len(shade), texture_mb=round(sum(tex_bytes.values()) / 1e6, 1),
              sky_mb=round(sky_bytes / 1e6, 1), scene_mb=round(os.path.getsize(os.path.join(tmp, "scene.bin")) / 1e6, 1),
              water_y=water_y, sky_scale=sky_scale, brick_masks=mask_report)
json.dump(report, open(os.path.join(cache, "report.json"), "w"), indent=1)
swap(tmp, out)
print("export:", json.dumps({k: v for k, v in report.items() if k != "brick_masks"}))
