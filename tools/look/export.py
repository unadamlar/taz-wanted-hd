# Blender: exports a dressed level as look data, format version 3 (see FORMAT.md).
# usage: blender -b extracted/look/pass3/zoohub-dressed.blend --factory-startup --python-exit-code 1 \
#          -P tools/look/export.py -- --level zoohub|cityhub [--rebake]
# Writes extracted/look/runtime/scene<NN>/ atomically. Bakes are cached in extracted/look/runtime/.bake/.
# Game space is worldview.py's inverse: Blender (x, y, z) * 250 -> game (x, z, y).
import argparse, collections, ctypes, fnmatch, hashlib, json, math, os, random, shutil, struct, sys, time
import bmesh, bpy
import numpy as np
from mathutils import Matrix, Vector, noise as mnoise

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import bake, dds, dress, kit, made, props3d, space, solid

a = argparse.ArgumentParser()
a.add_argument("--level", default="zoohub")
a.add_argument("--runtime", default=None, help="output folder (default extracted/look/runtime)")
a.add_argument("--rebake", action="store_true")
a.add_argument("--cpu", action="store_true", help="bake on the CPU, for when the GPU is busy")
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
cache = os.path.join(base, ".bake" if args.level == "zoohub" else ".bake-" + args.level)
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
if args.cpu:
    sc.render.engine, sc.cycles.device = "CYCLES", "CPU"  # listing devices would open the GPU
else:
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
OPAQUE, CARD, GRASS, WATER, GLASS, CASTER = 0, 1, 2, 3, 4, 5
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
    "prop": ("", False, OPAQUE, TWO_SIDED, 0.0, (1, 1, 1), 0.7, 0, 0),  # the real 3D stand-ins: flat colour a level's tint of "flat" (its pebbles) leaves alone
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
for name in LEVEL.get("triplanar", ()):  # ground that also covers steep banks
    MATS[name] = (*MATS[name][:3], MATS[name][3] | TRIPLANAR, *MATS[name][4:])
if "dome" in LEVEL:
    MATS["glass"] = ("", False, GLASS, TWO_SIDED, 0.0, (1, 1, 1), 0.05, 0, 0)
    MATS["caster"] = ("", False, CASTER, TWO_SIDED, 0.0, (1, 1, 1), 1.0, 0, 0)
    MATS["dome_steel"] = ("", False, GLASS, TWO_SIDED, 0.0, (0.34, 0.37, 0.42), 0.28, 1, 0)
    LEVEL["materials"] += ("glass", "dome_steel", "caster", "hull")
MATS["leaves_tint"] = ("leaves_tint", False, CARD, TWO_SIDED | WIND, 0.0, (1, 1, 1), 0.75, 0, 0.5)  # grey leaves: a bush's colour is its vertex colour
if "materials" in LEVEL and LEVEL.get("card_models"):  # real 3D stand-ins for painted cards: flowers and boards are flat colour
    LEVEL["materials"] = tuple(LEVEL["materials"]) + ("prop",) + (("leaves", "leaf_core", "leaves_tint") if any(k == "bush" for _, k in LEVEL["card_models"]) else ())
if "materials" in LEVEL and (LEVEL.get("cacti") or LEVEL.get("clusters")):
    LEVEL["materials"] = tuple(LEVEL["materials"]) + ("prop",)
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
    "kit_palm_leaf": "flat_wind",
    "kit_snow_lump": "flat",
}


def format_mat(name):
    name = name if name in BLENDER_MAT else name.split(".")[0]  # kit meshes made again here carry Blender's .001 copies
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
    spec = LEVEL.get("tiles", {}).get(name, {})
    alb, nor = made.tile(spec["made"], px) if "made" in spec else bake.bake_tile(cache, name, graph(), tile, px, vertical, z0=z0)
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
if "leaves_tint" in MATS:
    t_ = card_tile("leaves", kit._cards_mat(SC), "%s/%s" % (kit.TEXSETS["leaves024"][0], kit.TEXSETS["leaves024"][2]))
    lum = dds.to_linear(t_[..., :3]) @ np.array([0.3, 0.59, 0.11])
    g = dds.to_srgb(np.clip(lum / max(lum[t_[..., 3] > 0.5].mean(), 1e-6) * 0.55, 0, 1))
    put_tex("leaves_tint", dds.mips(np.dstack([g, g, g, t_[..., 3]]).astype(np.float32), cut=0.5), b"DXT5")
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
if flat:
    bpy.context.view_layer.objects.active = flat[0]
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, target="VERTEX_COLORS")
for o in flat:
    baked = np.empty(len(o.data.loops) * 4, np.float32)
    o.data.color_attributes["look_bake"].data.foreach_get("color", baked)
    if not baked.reshape(-1, 4)[:, :3].any():
        raise RuntimeError("bake came out black (GPU out of memory? try --cpu): " + o.name)


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
    if not len(w) or "@placed" in o.name and np.ptp(w[:, 1]) > 10:  # a floating log's wet underside, not a water surface
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
HIDDEN_ROLES = ("hide", "fence_rail", "fence_post", "fence_cap", "tree", "palm", "drip", "vine", "water", "sky")
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


def wire_tube(path, side, up, r, sides=3):
    """Tube along a path: triangles of positions and normals."""
    a = np.arange(sides) * 2 * np.pi / sides
    spoke = np.cos(a)[:, None] * side + np.sin(a)[:, None] * up
    ring = path[:, None] + r * spoke
    I, J = np.arange(len(path) - 1)[:, None], np.arange(sides)[None]
    corners = [(I + di, (J + dj) % sides) for di, dj in ((0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1))]
    p = np.stack([ring[i, j] for i, j in corners], 2).reshape(-1, 3, 3)
    n = np.stack([np.broadcast_to(spoke[j], (len(I), sides, 3)) for _, j in corners], 2).reshape(-1, 3, 3)
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
    print("export: barbed wire, %d strips" % len(quads))
    return solid_proto("barbed_wire", parts, "steel")


def solid_proto(name, parts, mat, colour=None):
    """A proto from (triangle positions, normals) parts, wound the way game space culls."""
    p, n = (np.concatenate(x).astype(np.float32) for x in zip(*parts))
    flip = (np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]) * n.mean(1)).sum(1) > 0
    p[flip], n[flip] = p[flip][:, [0, 2, 1]], n[flip][:, [0, 2, 1]]
    c = np.ones_like(p) if colour is None else np.array(colour, np.float32)
    if colour is not None:
        c[flip] = c[flip][:, [0, 2, 1]]
    p, n = p.reshape(-1, 3), n.reshape(-1, 3)
    return add_proto(name, p, n, c.reshape(-1, 3), np.zeros((len(p), 2), np.float32), np.full(len(p), MAT_ID[mat]))


def game_faces(wanted):
    """Unique faces in game space, with their UVs, of the capture's surfaces whose role or texture passes `wanted`."""
    faces = {}
    for coll in dress.GAME_COLLS:
        for o in (bpy.data.collections[coll].objects if coll in bpy.data.collections else []):
            if o.type != "MESH":
                continue
            M = np.array(S @ o.matrix_world, np.float64)
            uv = o.data.uv_layers[0].data
            for f in o.data.polygons:
                m = o.data.materials[f.material_index]
                if m and wanted(dress.base_name(m.name.split(":", 1)[-1])):
                    c = [(np.array(o.data.vertices[o.data.loops[l].vertex_index].co) @ M[:3, :3].T + M[:3, 3]) * K for l in f.loop_indices]
                    faces[tuple(sorted(tuple(np.round(q, 1)) for q in c))] = (np.array(c), [tuple(np.round(uv[l].uv, 2)) for l in f.loop_indices])
    return list(faces.values())


def revolve(c, ax, e1, e2, r, h, nr, nh, segments, colour=None):
    """A smooth surface of revolution from a profile: triangle corners (positions, normals, colours)."""
    th = np.linspace(0, 2 * np.pi, segments + 1)
    d = np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2
    P = c + r[:, None, None] * d + h[:, None, None] * ax
    N = nr[:, None, None] * d + nh[:, None, None] * ax
    C = np.ones((len(r), segments + 1, 3)) if colour is None else np.broadcast_to(colour[:, None], (len(r), segments + 1, 3))
    I, J = np.mgrid[:len(r) - 1, :segments]
    corners = ((I, J), (I + 1, J), (I + 1, J + 1), (I, J), (I + 1, J + 1), (I, J + 1))
    return [np.stack([A[i, j] for i, j in corners], 2).reshape(-1, 3, 3) for A in (P, N, C)]


def bent_tube(path, up, radius, sides=8):
    """Round bar along a curve; `up` is the surface normal at each point."""
    t = np.gradient(path, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    side = np.cross(t, up)
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    top = np.cross(side, t)
    a = np.linspace(0, 2 * np.pi, sides + 1)[:-1]
    spoke = np.cos(a)[None, :, None] * side[:, None] + np.sin(a)[None, :, None] * top[:, None]
    ring = path[:, None] + radius * spoke
    I, J = np.mgrid[:len(path) - 1, :sides]
    K_ = (J + 1) % sides
    corners = ((I, J), (I + 1, J), (I + 1, K_), (I, J), (I + 1, K_), (I, K_))
    return [np.stack([A[i, j] for i, j in corners], 2).reshape(-1, 3, 3) for A in (ring, spoke)]


def dome_protos():
    """A round glass dome on the game's rim, curved steel ribs and rings where its panel edges ran, and a smooth hull ring
    laid just over the game's faceted one, which stays there underneath (its collision is untouched)."""
    V = np.unique(np.round(np.concatenate([c for c, _ in game_faces(lambda label: dress.role_of(label) == LEVEL["dome"] and label.endswith("spacestation"))]), 1), axis=0)
    rim = V[V[:, 1] < V[:, 1].min() + 150]
    c = rim.mean(0)
    ax = np.linalg.svd(rim - c)[2][2]
    ax = ax * np.sign(ax[1])
    e1 = np.cross(ax, (0, 0, 1.0)); e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    H = (V - c) @ ax
    R = np.linalg.norm(V - c - H[:, None] * ax, axis=1)
    # a superellipse on the rim plane: walls that rise straight from the hull into a round top, containing every game vertex
    power, b = 2.6, H.max() + 5
    wide = (R > 500) & (H > 0)
    a = (R[wide] / (1 - (H[wide] / b) ** power) ** (1 / power)).max() + 2
    q = np.linspace(0, np.arccos((R[H > 900].min() * 0.92 / a) ** (power / 2)), 44) ** 1.0
    r_, h_ = np.r_[a, a * np.cos(q) ** (2 / power)], np.r_[-5.0, b * np.sin(q) ** (2 / power)]
    nr, nh = (r_ / a) ** (power - 1) / a, (np.maximum(h_, 0) / b) ** (power - 1) / b
    l = np.hypot(nr, nh)
    nr, nh = nr / l, nh / l
    P, N, _ = revolve(c, ax, e1, e2, r_, h_, nr, nh, 160)
    glass = solid_proto("dome_glass", [(P, N)], "glass")

    az = np.unique(np.round(np.arctan2((rim - c) @ e2, (rim - c) @ e1), 2))
    frame = []
    for th in az:  # ribs
        d = np.cos(th) * e1 + np.sin(th) * e2
        frame.append(bent_tube(c + r_[:, None] * d + h_[:, None] * ax, nr[:, None] * d + nh[:, None] * ax, 7.0))
    levels_ = sorted({int(round(x / 40)) * 40 for x in H[(H > 100) & (H < 930)]})
    th = np.linspace(0, 2 * np.pi, 161)
    d = np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2
    for lv_h, rad in [(x, 6.5) for x in levels_] + [(4.0, 11.0), (h_[-1], 10.0)]:  # rings
        k = np.argmin(np.abs(h_[1:] - lv_h)) + 1
        frame.append(bent_tube(c + r_[k] * d + h_[k] * ax, nr[k] * d + nh[k] * ax, rad))
    bars = solid_proto("dome_frame", frame, "dome_steel")

    ri, ro = R[H < 40].mean() * np.cos(np.pi / 14) - 3.5, 1304.0  # inside the 14-sided wall's flats, outside its corners
    top, wall = np.array((226, 227, 247)) / 255, np.array((168, 166, 241)) / 255
    band, outer = np.array((190, 188, 244)) / 255, np.array((212, 211, 248)) / 255
    arc = lambda r0, h1, q0, q1, rad, m: (r0 + rad * np.cos(np.linspace(q0, q1, m)), h1 + rad * np.sin(np.linspace(q0, q1, m)))
    pr, ph, pc = [np.array([ri, ri])], [np.array([-250.0, -6.0])], [np.array([wall, wall])]
    x, y = arc(ri + 11, -2.0, np.pi, np.pi / 2, 11.0, 7)
    pr.append(x), ph.append(y), pc.append(np.linspace(wall, band, 7))
    pr.append(np.array([ri + 30, ro - 30])), ph.append(np.array([9.0, 9.0])), pc.append(np.array([top, top]))
    x, y = arc(ro - 21, -12.0, np.pi / 2, -0.46, 21.0, 9)
    pr.append(x), ph.append(y), pc.append(np.linspace(top, outer, 9))
    pr.append(np.array([ro - 104, 1148.0])), ph.append(np.array([-210.0, -292.0])), pc.append(np.array([band, wall]))
    pr, ph, pc = np.concatenate(pr), np.concatenate(ph), dds.to_linear(np.concatenate(pc))
    tr, th_ = np.gradient(pr), np.gradient(ph)
    l = np.maximum(np.hypot(tr, th_), 1e-6)
    P, N, C = revolve(c, ax, e1, e2, pr, ph, -th_ / l, tr / l, 160, pc)  # outward: from the inner wall up, over, and down the outside
    hull = solid_proto("hull_ring", [(P, N)], "hull", C)

    LEVEL["shadow_floor"] = float(c[1] - 252)
    print("export: dome radius %.0f height %.0f, %d ribs, %d rings, glass %d, frame %d, hull %d triangles" % (
        a, b, len(az), len(levels_) + 2, len(protos[glass]["ix"]) // 3, len(protos[bars]["ix"]) // 3, len(protos[hull]["ix"]) // 3))
    return glass, bars, hull


def caster_proto():
    """Depth-only copies of the doors and the flag, for the sun map: the game draws them after it is built."""
    x0, y0, x1, y1 = (v * K for v in LEVEL["hub"])
    faces = [c for c, _ in game_faces(lambda label: dress.role_of(label) == "gameplay") if x0 < c[:, 0].mean() < x1 and y0 < c[:, 2].mean() < y1]
    parts = [(c[[0, 1, 2]][None], np.tile(np.cross(c[1] - c[0], c[2] - c[0]), (1, 3, 1))) for c in faces]
    parts += [(c[[0, 2, 3]][None], np.tile(np.cross(c[1] - c[0], c[2] - c[0]), (1, 3, 1))) for c in faces if len(c) == 4]
    return solid_proto("shadow_casters", parts, "caster")


if "wire" in LEVEL:
    place.append((barbed_wire(bpy.data.objects[LEVEL["wire"]]), None))
if "dome" in LEVEL:
    place += [(pi, None) for pi in (*dome_protos(), caster_proto())]

fp = {}
for line in open(os.path.join(ext, "textures", "fingerprints.tsv")):
    h, f = line.rstrip("\n").split("\t")[:2]
    fp.setdefault(f, int(h, 16))
for stem, planets in LEVEL.get("space", {}).items():  # the game's painted backdrop panels, redrawn (bound by look.c in their place)
    file = "cityhub/textures/%s.png" % stem
    name = "paint_%016x" % fp[file]
    key = hashlib.sha1((repr(planets) + open(os.path.join(here, "space.py")).read()).encode()).hexdigest()[:12]
    cached = os.path.join(cache, "%s-%s.dds" % (name, key))
    if not os.path.exists(cached):
        img = bpy.data.images.load(os.path.join(ext, "upscaled", file), check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        rgb = px.reshape(img.size[1], img.size[0], 4)[::-1, :, :3].copy()
        out_rgb = space.panel(rgb, planets, 4096, seed=sorted(LEVEL["space"]).index(stem) * 40 + 3)
        dds.write_dxt(cached, dds.mips(np.dstack([out_rgb, np.ones(out_rgb.shape[:2], np.float32)])), b"DXT1")
    shutil.copy(cached, os.path.join(tmp, "tex", name + ".dds"))
    tex_bytes[name] = os.path.getsize(cached)
tex_hash = {}
for line in list(open(os.path.join(ext, "textures", "index.tsv")))[1:]:
    pak, name, _, _, f = line.rstrip("\n").split("\t")
    if pak == LEVEL["pak"] and f in fp:
        tex_hash[pak + "/" + os.path.splitext(name)[0]] = fp[f]


def game_rgba(label):
    """The HD image of a game texture, top row first."""
    m = next(m for m in bpy.data.materials if m.name.startswith(("lit:", "lit+:")) and dress.base_name(m.name.split(":", 1)[1]) == label)
    img = next(n.image for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[::-1].copy()


def card_mat(label):
    """A game texture drawn as the game draws it, cut-out kept: for a hidden texture's draws that stay."""
    name = "card_" + label.rsplit("/", 1)[1][:26]
    if name not in MAT_ID:
        rgba = game_rgba(label)
        card = bool((rgba[..., 3] < 0.5).any())
        if card:
            rgba[..., :3] = dds.bleed(rgba[..., :3], rgba[..., 3])
        put_tex(name, dds.mips(rgba, cut=0.5 if card else None), b"DXT5" if card else b"DXT1")
        MATS[name] = (name, False, CARD if card else OPAQUE, TWO_SIDED, 0.0, (1, 1, 1), 0.7, 0, 0.5 if card else 0)
        MAT_ID[name] = len(MAT_ID)
    return MAT_ID[name]


def solid_mat(label, tint=(1, 1, 1), rough=0.6, flags=TWO_SIDED):
    """A game texture as an opaque material for real geometry: colour bled past the cut-out's edge."""
    name = "game_" + label.rsplit("/", 1)[1][:26] + ("" if flags == TWO_SIDED else "_%d" % flags)
    if name not in MAT_ID:
        rgba = game_rgba(label)
        rgba[..., :3] = dds.bleed(rgba[..., :3], rgba[..., 3])
        rgba[..., 3] = 1
        put_tex(name, dds.mips(rgba), b"DXT1")
        MATS[name] = (name, False, OPAQUE, flags, 0.0, tint, rough, 0, 0)
        MAT_ID[name] = len(MAT_ID)
    return MAT_ID[name]


def place_static(name, p, n, uv, c, mat):
    """Hides nothing itself. Split along the chunk grid so the parts cull separately."""
    p, n, uv, c = p.astype(np.float32), n.astype(np.float32), uv.astype(np.float32), dds.to_linear(c).astype(np.float32)
    tri = p.reshape(-1, 3, 3)
    flip = (np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) * n.reshape(-1, 3, 3).mean(1)).sum(1) > 0  # game space winding
    order = np.tile([0, 1, 2], (len(tri), 1))
    order[flip] = [0, 2, 1]
    k = (np.arange(len(tri))[:, None] * 3 + order).ravel()
    p, n, uv, c = p[k], n[k], uv[k], c[k]
    cen = p.reshape(-1, 3, 3).mean(1)
    cell = (np.floor(cen[:, 0] / CHUNK).astype(np.int64) << 32) + np.floor(cen[:, 2] / CHUNK).astype(np.int64)
    for cid in np.unique(cell):
        t = np.where(cell == cid)[0]
        j = (t[:, None] * 3 + [0, 1, 2]).ravel()
        place.append((add_proto("%s.%d" % (name, cid & 0xffff), p[j], n[j], c[j], uv[j], np.full(len(j), mat)), None))
    print("export: %s, %d triangles" % (name, len(p) // 3))


def relief(cfg):
    """The biggest flat painted walls raised in their own paint: blocks that follow the strata, always in front of the game's
    face, flat at the foot (where Taz walks) and at the wall's open edges. Sizes in Blender units."""
    from mathutils.bvhtree import BVHTree
    x0, z0, x1, z1 = (v * K for v in LEVEL["hub"])
    faces, edge_n = [], collections.Counter()
    found = {}
    for coll in dress.GAME_COLLS:  # game_faces, plus each corner's paint colour (baked shade dropped), as world draws show it (2x)
        for o in (bpy.data.collections[coll].objects if coll in bpy.data.collections else []):
            if o.type != "MESH" or "kit_vcol" not in o.data.color_attributes:
                continue
            M, uvl, col = np.array(S @ o.matrix_world, np.float64), o.data.uv_layers[0].data, o.data.color_attributes["kit_vcol"].data
            for f in o.data.polygons:
                m = o.data.materials[f.material_index]
                if m and any(fnmatch.fnmatch(dress.base_name(m.name.split(":", 1)[-1]), p) for p in cfg["textures"]) and len(f.loop_indices) >= 3:
                    c = np.array([(np.array(o.data.vertices[o.data.loops[l].vertex_index].co) @ M[:3, :3].T + M[:3, 3]) * K for l in f.loop_indices])
                    found[tuple(sorted(tuple(np.round(q, 1)) for q in c))] = (c, [tuple(uvl[l].uv) for l in f.loop_indices],
                                                                              np.minimum(np.array([tuple(col[l].color)[:3] for l in f.loop_indices]) * 2, 1))
    for a_, uv_, vc_ in found.values():
        n = -np.cross(a_[1] - a_[0], a_[2] - a_[0]) * (-1 if cfg.get("flip") else 1)  # game space is left-handed
        area = sum(np.linalg.norm(np.cross(a_[k] - a_[0], a_[k + 1] - a_[0])) for k in range(1, len(a_) - 1)) / 2
        n /= max(np.linalg.norm(n), 1e-9)
        cen = a_.mean(0)
        if area < cfg["min_area"] * K * K or abs(n[1]) > 0.45 or not (x0 < cen[0] < x1 and z0 < cen[2] < z1):
            continue
        keys = [tuple(np.round(q, 0)) for q in a_]
        for i in range(len(a_)):
            edge_n[frozenset((keys[i], keys[(i + 1) % len(a_)]))] += 1
        faces.append((a_, np.array(uv_) * (1, -1) + (0, 1), n, keys, vc_))  # Direct3D's v runs down
    def bvh(role):
        tris = [t for c, _ in game_faces(lambda l: dress.role_of(l) == role) for t in ([c[[0, 1, 2]]] + ([c[[0, 2, 3]]] if len(c) == 4 else []))]
        return BVHTree.FromPolygons(np.concatenate(tris).tolist(), np.arange(3 * len(tris)).reshape(-1, 3).tolist()) if tris else None
    ground, play = bvh("ground"), bvh("gameplay")  # flat where Taz walks and behind signs, buttons and pickups by the wall
    hash_ = lambda a, b: np.modf(np.sin(a * 12.9898 + b * 78.233) * 43758.5453)[0] % 1.0
    P, N, U, C = [], [], [], []
    for a_, uv_, n, keys, vc_ in faces:
        t = np.cross((0, 1, 0), n); t /= max(np.linalg.norm(t), 1e-9)
        bound = [(a_[i], a_[(i + 1) % len(a_)]) for i in range(len(a_)) if edge_n[frozenset((keys[i], keys[(i + 1) % len(a_)]))] == 1]
        for f3 in ([0, k, k + 1] for k in range(1, len(a_) - 1)):
            A, UV, VC = a_[f3], uv_[f3], vc_[f3]
            m = int(np.ceil(max(np.linalg.norm(A[1] - A[0]), np.linalg.norm(A[2] - A[0]), np.linalg.norm(A[2] - A[1])) / (cfg["cell"] * K)))
            I, J = [x.ravel() for x in np.mgrid[:m + 1, :m + 1]]
            k = I + J <= m
            I, J = I[k], J[k]
            p = A[0] + np.outer(I / m, A[1] - A[0]) + np.outer(J / m, A[2] - A[0])
            uv = UV[0] + np.outer(I / m, UV[1] - UV[0]) + np.outer(J / m, UV[2] - UV[0])
            vc = VC[0] + np.outer(I / m, VC[1] - VC[0]) + np.outer(J / m, VC[2] - VC[0])
            s = p[:, [0, 2]] @ t[[0, 2]]
            L = p[:, 1] / (cfg["band"] * K) + 0.35 * np.sin(s / (2.3 * K)) + 0.2 * np.sin(s / (0.9 * K) + 1.7)
            row = np.floor(L)
            blk = np.floor(s / (cfg["block"] * K) + hash_(row, 3.1))
            d = cfg["depth"] * K * (0.25 + 0.75 * hash_(row, blk))
            foot = np.ones(len(p))
            if ground:
                for q in range(len(p)):
                    hit = ground.ray_cast(p[q] + (0, 5, 0), (0, -1, 0), 20 * K)[0]
                    foot[q] = np.clip((p[q, 1] - hit[1]) / (cfg["foot"] * K), 0, 1) if hit is not None else 1
            if play:
                for q in range(len(p)):
                    hit = play.find_nearest(p[q], (0.1 + cfg["border"]) * K)[3]
                    foot[q] = min(foot[q], np.clip((hit / K - 0.1) / cfg["border"], 0, 1)) if hit is not None else foot[q]
            edge = np.ones(len(p))
            for e0, e1 in bound:
                v = e1 - e0
                w = np.clip(((p - e0) @ v) / max(v @ v, 1e-9), 0, 1)
                edge = np.minimum(edge, np.linalg.norm(p - e0 - np.outer(w, v), axis=1) / (cfg["border"] * K))
            p = p + np.outer(d * np.minimum(foot, np.clip(edge, 0, 1)) ** 1.5 + 2.0, n)
            ix = {(i, j): q for q, (i, j) in enumerate(zip(I, J))}
            tri = [(ix[i, j], ix[i + 1, j], ix[i, j + 1]) for i, j in zip(I, J) if i + j < m] + \
                  [(ix[i + 1, j], ix[i + 1, j + 1], ix[i, j + 1]) for i, j in zip(I, J) if i + j < m - 1]
            tri = np.array(tri)
            T = p[tri]
            fn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
            fn *= np.sign((fn @ n))[:, None]  # facing out, flat per facet: hard edges read as chiselled
            fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-9)
            P.append(T.reshape(-1, 3)); N.append(np.repeat(fn, 3, 0)); U.append(uv[tri].reshape(-1, 2))
            C.append(vc[tri].reshape(-1, 3))
    return P, N, U, C


captures = [os.path.join(ext, "look", f) for f in LEVEL.get("captures", ())]
if "relief" in LEVEL:
    by_label = collections.defaultdict(list)
    for pat in LEVEL["relief"]["textures"]:
        for label in sorted({dress.base_name(m.name.split(":", 1)[1]) for m in bpy.data.materials if m.name.startswith(("lit:", "lit+:"))}):
            if fnmatch.fnmatch(label, pat):
                by_label[label] = True
    for label in by_label:
        P, N, U, C = relief(dict(LEVEL["relief"], textures=(label,)))
        if P and "unbake" in LEVEL:  # as for solids: the baked night tint goes, the moon shades
            C = [c ** LEVEL["unbake"] for c in C]
        if P:
            place_static("relief_" + label.rsplit("/", 1)[1], *(np.concatenate(x) for x in (P, N, U, C)), solid_mat(label, LEVEL["relief"].get("tint", (1, 1, 1)), 0.88, 0))  # one-sided: a camera pressed into it sees the game's wall
if "chain" in LEVEL or "grill" in LEVEL:
    want = {tex_hash[LEVEL[k]]: k for k in ("chain", "grill") if k in LEVEL}
    cards = {h: {} for h in want}
    for d in solid.capture(captures, set(want)):
        if d[0] in want and all(abs(d[1][i] - (i % 5 == 0)) < 1e-6 for i in range(16)):
            cards[d[0]][solid.key_of(d[4])] = solid.triangles(d[2], d[3], d[4])
    for h, kind in want.items():
        rgba = game_rgba(LEVEL[kind])
        if kind == "chain":
            size, mat = (200.0, 300.0), MAT_ID["link"]
            P, N = solid.link(rgba[..., 3], size)
        else:
            size, mat = (90.0, 345.0), solid_mat(LEVEL[kind])
            P, N = solid.plate(rgba[..., 3], size, 4.5, tol=1.4, min_area=30.0, repeat=2)
        parts = [solid.on_card(P, N, pos, uv, np.ones_like(col) if kind == "chain" else col, size) for pos, uv, col in cards[h].values()]
        place_static(kind, *(np.concatenate(x) for x in zip(*parts)), mat)

# Things the game may move: models in their own space, drawn at the game's transform in place of its draws (hd_solid_draw).
def paint_families(px):
    """The main colours of a painted card (its outline left out): the biggest colour family, then a second one if it
    covers a good share. Greens give way to another big family, so a magenta bush with green leaves painted on stays magenta."""
    px = px[px.max(1) > 0.25] if (px.max(1) > 0.25).any() else px
    if not len(px):
        return [np.array((0.3, 0.5, 0.2))]
    hue = (np.round(np.arctan2(np.sqrt(3) * (px[:, 1] - px[:, 2]), 2 * px[:, 0] - px[:, 1] - px[:, 2]) / (np.pi / 6)) % 12).astype(int)
    cnt = np.bincount(hue, minlength=12)
    other = cnt.copy(); other[3:6] = 0
    first = other.argmax() if other.max() >= 0.3 * cnt.sum() else cnt.argmax()
    out = [np.median(px[hue == first], 0)]
    rest = cnt.copy(); rest[[first, (first + 1) % 12, (first - 1) % 12]] = 0
    if rest.max() >= 0.2 * cnt.sum():
        out.append(np.median(px[hue == rest.argmax()], 0))
    return out


def leaf_from(W, colour, hub):
    """A modelled leaf along the long axis of a painted leaf's outline, rooted at its lower end, or for a leaf lying
    flat, at the end nearer the middle of its plant (hub)."""
    c = W.mean(0)
    ax = np.linalg.svd(W - c, full_matrices=False)[2]
    x, y = (W - c) @ ax[0], (W - c) @ ax[1]
    a0, a1 = c + ax[0] * x.min(), c + ax[0] * x.max()
    if abs((a1 - a0)[1]) > 0.3 * np.linalg.norm(a1 - a0):
        root, tip = (a0, a1) if a0[1] <= a1[1] else (a1, a0)
    else:
        root, tip = (a0, a1) if np.linalg.norm(a0 - hub) <= np.linalg.norm(a1 - hub) else (a1, a0)
    axis = (tip - root) / max(np.linalg.norm(tip - root), 1e-6)
    side = np.cross(axis, ax[2]); side /= max(np.linalg.norm(side), 1e-6)
    natural = np.clip(0.6 * np.asarray(colour) + 0.4 * np.array((0.2, 0.48, 0.12)), 0, 1)
    p, n, col = props3d.leaf(root, axis, side, np.linalg.norm(tip - root), y.max() - y.min(), natural)
    return p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])


_ground = []


def ground_below(p_game):
    """Height (game units) of the level's surface under a game-space point, or None."""
    if not _ground:
        from mathutils.bvhtree import BVHTree
        V, F, off = [], [], 0
        for coll in dress.GAME_COLLS:
            for o in (bpy.data.collections[coll].objects if coll in bpy.data.collections else []):
                if o.type == "MESH" and len(o.data.polygons) and "placed" not in coll:
                    co, tv, _ = kit._world_tris(o)
                    V.append(co); F.append(tv + off); off += len(co)
        _ground.append(BVHTree.FromPolygons(np.concatenate(V).tolist(), np.concatenate(F).tolist()))
    hit = _ground[0].ray_cast(Vector((p_game[0] / K, p_game[2] / K, p_game[1] / K - 0.05)), Vector((0, 0, -1)), 40.0)
    return hit[0].z * K if hit[0] is not None else None


def sign_mount(art, axes, thin, alpha, world):
    """A sign as a real object: a wooden board (or a metal disc for a round sign) behind its art, on a post or pole down
    to the ground. art in the draw's own space; world is the game's matrix for a placed sign."""
    M = np.array(world, np.float64).reshape(4, 4)
    to_w = lambda q: q @ M[:3, :3] + M[3, :3]
    to_l = lambda q: (q - M[3, :3]) @ np.linalg.inv(M[:3, :3])
    on = alpha > 0.5
    fill = on.mean() / max(on.any(1).mean() * on.any(0).mean(), 1e-6)
    h, v = axes
    nrm = np.cross(h, v); nrm /= np.linalg.norm(nrm)
    c = art.mean(0)
    x, y = (art - c) @ h, (art - c) @ v
    out = []
    if 0.7 < fill < 0.84:  # round: a metal disc on a pole
        r = (np.ptp(x) + np.ptp(y)) / 4 * 1.04
        cc = c + h * (x.max() + x.min()) / 2 + v * (y.max() + y.min()) / 2
        p, n, col = props3d.disc(cc, r, nrm, thin * 0.8)
        bottom = cc - np.array([0, r, 0.0])
        pr = r * 0.06
    else:  # a board a little larger than the art
        p, n, col = props3d.board(art, axes, 0.8 * thin)
        bottom = c - np.array([0, (np.ptp(y)) / 2, 0.0])
        pr = max(np.ptp(x), np.ptp(y)) * 0.03
        r = np.ptp(y) / 2
    out.append((p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])))
    g = ground_below(to_w(bottom[None])[0])
    bw = to_w(bottom[None])[0]
    if g is not None and 0 < bw[1] - g < 6 * r:  # on the ground: a pole, or two posts for a wide board
        feet = [bottom] if fill < 0.84 or np.ptp(x) < 1.5 * np.ptp(y) else [bottom - h * np.ptp(x) * 0.3, bottom + h * np.ptp(x) * 0.3]
        for f in feet:
            top_w, foot_w = to_w(f[None])[0], to_w(f[None])[0] * [1, 0, 1] + [0, g - 10, 0]
            p, n, col = props3d.pole(to_l(top_w[None])[0] + v * r * 0.3, to_l(foot_w[None])[0], pr, (0.55, 0.57, 0.6) if fill < 0.84 else (0.3, 0.19, 0.1))
            out.append((p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])))
    return out


def cactus_geo(W, colour, rng, armed=False):
    """A modelled cactus over a cactus's footprint: a saguaro if it is tall or armed (its arms widen the footprint),
    a barrel if squat."""
    c = W.mean(0)
    ax = np.linalg.svd(W - c, full_matrices=False)[2]
    up = ax[0] * np.sign(ax[0][1] or 1)
    ext = np.ptp((W - c) @ ax.T, 0)
    if ext[0] < 1.6 * ext[1] or abs(up[1]) < 0.5:  # squat, or its long side lies down: it stands upright
        up = np.array([0, 1.0, 0])
    h = (W - c) @ up
    side = np.linalg.norm((W - c) - np.outer(h, up), axis=1)
    height, radius = np.ptp(h), np.percentile(side, 90)
    base = c + up * h.min()
    green = np.clip(0.55 * np.asarray(colour) + 0.45 * np.array((0.22, 0.45, 0.18)), 0, 1)
    if armed:
        trunk = max(np.percentile(side, 10), height * 0.06)  # most points are on the arms
        far = side > 2.5 * trunk  # the model's own arms: one each side of the trunk, where they reach out
        flat = (W - c) - np.outer(h, up)
        arms = []
        if far.sum() > 2:
            ax_ = np.linalg.svd(flat[far], full_matrices=False)[2][0]
            for sgn in (1, -1):
                f_ = far & (sgn * (flat @ ax_) > 0)
                if f_.any():
                    d_ = flat[f_].mean(0)
                    arms.append((np.arctan2(d_[2], d_[0]), np.clip((np.median(h[f_]) - h.min()) / height - 0.12, 0.3, 0.65), np.percentile(side[f_], 60) * 0.9))
        p, n, col = props3d.saguaro(np.zeros(3), height, trunk, green, rng, arms or None)
    elif height > 2.2 * radius:
        p, n, col = props3d.saguaro(np.zeros(3), height, max(radius * 0.45, height * 0.08), green, rng)
    else:
        p, n, col = props3d.barrel(np.zeros(3), height, radius, green, (0.95, 0.4, 0.6), rng)
    y = np.array([0, 1.0, 0]); k = np.cross(y, up); s_ = np.linalg.norm(k); c_ = y @ up
    R = np.eye(3) if s_ < 1e-6 else np.eye(3) + (K_ := np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])) + K_ @ K_ * ((1 - c_) / s_ ** 2)
    return p @ R.T + base, n @ R.T, col


def bush_geo(base, height, radius, colour, rng):
    """A leafy bush of the kit's clumps and leaf cards filling a painted bush's footprint, tinted to its paint (sRGB)."""
    R, H = radius / K, max(height, radius * 0.6) / K
    n = int(np.clip(round((R / 0.5) ** 2 * H / 0.8), 4, 12))
    centers = []
    for _ in range(n):  # overlapping clumps, so the bush reads as one mass
        a_, d_ = rng.uniform(0, 2 * np.pi), np.sqrt(rng.uniform(0, 1)) * R * 0.55
        r_ = rng.uniform(0.45, 0.6) * min(1.0, max(R, 0.5))
        z_ = rng.uniform(r_ * 0.9, max(H - r_ * 0.8, r_ * 0.95))
        centers.append((Vector((np.cos(a_) * d_, np.sin(a_) * d_, z_)), r_))
    o = bpy.data.objects.new("kit_bushprop", kit._canopy_mesh("kit_bushprop", centers, max(R, H / 2), rng, 16, SC))
    sc.collection.objects.link(o)
    bpy.context.view_layer.update()
    p, n_, c, uv, m = tris_of(o, True)
    bpy.data.objects.remove(o)
    lum = (c @ np.array([0.3, 0.59, 0.11]))[:, None]
    target = dds.to_linear(np.asarray(colour, float))
    cards = m == MAT_ID["leaves"]
    c = np.where(cards[:, None], lum * target / max(target.max(), 1e-3) * 1.4, lum * target / max(target @ np.array([0.3, 0.59, 0.11]), 1e-3))
    m = np.where(cards, MAT_ID["leaves_tint"], m)
    return p + base, n_, uv, dds.to_srgb(np.clip(c, 0, 1)), m  # in the order the card stand-ins use


def banister_geo(alpha, paint, pos, uv, col, size):
    """A painted banister (two rails along the texture's v, spindles across between them) as round rails and turned
    balusters where the paint has spindles. Triangle by triangle: one piece of card can join two panels painted alike."""
    on = alpha > 0.5
    H, Wd = on.shape
    rail = np.nonzero(on.mean(0) > 0.95)[0]
    gap = np.nonzero(np.diff(rail) > 1)[0]
    if len(gap) != 1:
        return []
    rails = (rail[:gap[0] + 1], rail[gap[0] + 1:])
    lo, hi = rails[0][-1] + 1, rails[1][0]
    rows = np.nonzero(on[:, lo:hi].any(1))[0]
    blobs = [b for b in np.split(rows, np.nonzero(np.diff(rows) > 1)[0] + 1) if len(b) > 1] if len(rows) else []
    lit = np.clip(col.mean((0, 1)), 0, 1)
    tone = lambda px: np.clip(np.median(px.reshape(-1, 3), 0) * lit * 1.15, 0, 1)
    out = []
    for i in range(len(pos)):
        tri = uv[i]

        def world(q):  # absolute uvs: the extra point past 1 keeps on_card from shifting or copying them
            P = np.r_[np.c_[q, np.zeros(len(q))], [[2.0, 2.0, 0]]]
            return solid.on_card(P, np.tile([0, 0, 1.0], (len(P), 1)), pos[i:i + 1], uv[i:i + 1], col[i:i + 1], size)[0][:-1]

        for r in rails:  # the rail's stretch across this triangle
            u_ = (r[0] + r[-1] + 1) / 2 / Wd
            vs = [a[1] + (u_ - a[0]) / (b[0] - a[0]) * (b[1] - a[1]) for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))
                  if a[0] != b[0] and (a[0] - u_) * (b[0] - u_) <= 0]
            if len(vs) > 1 and max(vs) - min(vs) > 1e-3:
                ends = world(np.array([[u_, min(vs)], [u_, max(vs)]]))
                out.append(props3d.pole(ends[0], ends[1], len(r) / Wd * size[0] * 0.55, tone(paint[:, r])))
        e1, e2 = tri[1] - tri[0], tri[2] - tri[0]
        det = e1[0] * e2[1] - e1[1] * e2[0]
        for b in blobs:
            radius = max(on[b, x].sum() for x in range(lo, hi)) / H * size[1] / 2
            for k in range(int(np.floor(tri[:, 1].min() + 1e-6)), int(np.ceil(tri[:, 1].max() - 1e-6))):
                q = np.array([(lo + hi) / 2 / Wd, k + (b.mean() + 0.5) / H]) - tri[0]
                l1, l2 = (q[0] * e2[1] - q[1] * e2[0]) / det, (e1[0] * q[1] - e1[1] * q[0]) / det
                if min(l1, l2, 1 - l1 - l2) > 0:  # its middle is on this triangle
                    ends = world(np.array([[lo / Wd, q[1] + tri[0][1]], [hi / Wd, q[1] + tri[0][1]]]))
                    out.append(props3d.spindle(ends[0], ends[1], radius, tone(paint[b, lo:hi][on[b, lo:hi]])))
    return [(p, n, np.zeros((len(p), 2)), c, np.full(len(p), MAT_ID["prop"])) for p, n, c in out]


def iron_geo(alpha, paint, pos, uv, col, size, wood=False):
    """Painted wrought iron as round bars along the paint's strokes, a spear head on each bar that ends upward in one.
    wood: sawn boards instead, flat-faced, each in its own paint, with plank grain; no plates or heads.
    Only what falls on this piece of card is kept: its texture repeats, and the card can start part way into one."""
    h, w = alpha.shape
    px = np.array(size, float) / [w, h]  # world size of a texel
    lines = solid.strokes(alpha)
    if not lines:
        return []
    lit = np.clip(col.mean((0, 1)), 0, 1)
    iron = np.median(paint[alpha > 0.5], 0) * lit
    iron = np.clip(iron * (1.6 if iron.max() < 0.15 else 1.15), 0, 1)  # black ink lifted a little, so it shades round
    rmed = np.median(np.concatenate([r for _, r, *_ in lines]))
    on = lambda q: 0 <= q[1] < h and alpha[int(q[1]), int(q[0]) % w] > 0.5

    def half_width(q, d):  # paint across the bar at q
        side = np.array([-d[1], d[0]])
        return min(next(k for k in range(1, 40) if not on(q + s_ * k * side)) for s_ in (1, -1)) - 0.5

    P, N, C = [], [], []
    nodes = []  # bolted plates where bars meet: the paint is wide every way round the joint
    for q in (p_ + 0.5 for xy, *_ in ([] if wood else lines) for p_ in (xy[0], xy[-1])):
        if all(np.abs(q - o).max() > 2 for o in nodes):
            nodes.append(q)
    for q in nodes:
        reach = min(next((k for k in range(1, 40) if not on(q + k * np.array(d_))), 40) for d_ in
                    ((1, 0), (-1, 0), (0, 1), (0, -1), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7))) - 0.5
        if reach < 2 * rmed or not 0 <= q[1] < h:
            continue
        c_, hw = q * px, reach * px.mean()
        t_ = 1.3 * rmed * 0.85 * px.mean()
        p, n, _ = props3d.board(np.array([[c_[0] - hw, c_[1] - hw, 0], [c_[0] + hw, c_[1] + hw, 0]]), (np.array([1.0, 0, 0]), np.array([0, 1.0, 0])), t_)
        P.append(p); N.append(n); C.append(np.tile(iron, (len(p), 1)))
        k_ = max(2, int(reach * 0.6))
        near = paint[max(int(q[1]) - k_, 0):int(q[1]) + k_ + 1, (int(q[0]) + np.arange(-k_, k_ + 1)) % w].reshape(-1, 3)
        bolt = np.clip(near[near.min(1).argmax()] * lit * 1.15, 0, 1)  # the bolt head's pale paint, not its slot
        if np.abs(bolt - iron).max() > 0.15:  # a painted bolt head on both faces
            for z_ in (1, -1):
                p, n, _ = props3d.disc(np.array([c_[0], c_[1], z_ * t_ * 1.2]), hw * 0.45, np.array([0, 0, z_ * 1.0]), t_ * 0.3, sides=10)
                P.append(p); N.append(n); C.append(np.tile(bolt, (len(p), 1)))
    for xy, r, *free in lines:
        xy = xy + 0.5
        heads = []
        for end, f in ((0, free[0]), (-1, free[1])):
            if not f or len(xy) < 6 or wood:
                continue
            seg = xy if end == -1 else xy[::-1]
            d = seg[-1] - seg[max(-10, -len(seg))]
            d /= max(np.linalg.norm(d), 1e-9)
            if d[1] > -0.7:  # up the texture only: the card's top is the world's top
                continue
            tip = seg[-1].copy()
            while on(tip + d):
                tip = tip + d
            k = len(seg) - 1  # the head: down the bar while the paint stays wide
            while k > 0 and half_width(seg[k], d) > 1.6 * rmed:
                k -= 1
            wide = min(max(half_width(q, d) for q in seg[k:]), 3 * rmed) if k < len(seg) - 1 else 2.2 * rmed
            if np.linalg.norm(tip - seg[k]) < 2 * rmed:
                k = max(0, len(seg) - 1 - int(3 * rmed))
            heads.append((end, k, seg[k], tip, wide))
        for end, k, base, tip, wide in heads:  # the bar stops at its head
            xy = xy[:k + 1] if end == -1 else xy[len(xy) - 1 - k:]
            r = r[:k + 1] if end == -1 else r[len(r) - 1 - k:]
            m0, m1 = base * px, tip * px
            p, n = props3d._tube(np.c_[np.array([m0, m0 + (m1 - m0) * 1e-3, m1]), np.zeros(3)], np.array([0.0, 0.9 * wide * px.mean(), 0.0]), 4)
            P.append(p); N.append(n); C.append(np.tile(iron, (len(p), 1)))
        if len(xy) > 4:  # pixel steps smoothed out, ends kept
            sm = np.c_[[np.convolve(np.pad(xy[:, c], 2, mode="edge"), np.ones(5) / 5, "valid") for c in (0, 1)]].T
            sm[[0, -1]] = xy[[0, -1]]
            xy = sm
        idx = np.unique(np.r_[np.arange(0, len(xy), 3), len(xy) - 1])
        m = xy[idx] * px
        if len(m) < 2 or np.linalg.norm(m[-1] - m[0]) < 1e-6:
            continue
        if wood:
            d_ = (xy[-1] - xy[0]) / np.linalg.norm(xy[-1] - xy[0])
            hw = (np.median(r) + 0.5) * np.linalg.norm(np.array([-d_[1], d_[0]]) * px)  # the paint's width across the board
            p, n = props3d.plank(np.c_[m, np.zeros(len(m))], hw, 0.15 * hw)  # a board 0.3 as deep as it is tall
            board = np.median(paint[np.clip(xy[:, 1].astype(int), 0, h - 1), xy[:, 0].astype(int) % w], 0)
            P.append(p); N.append(n); C.append(np.tile(np.clip(board * lit * 1.15, 0, 1), (len(p), 1)))
            continue
        p, n = props3d._tube(np.c_[m, np.zeros(len(m))], np.full(len(m), np.clip(np.median(r), 0.5, 1.3 * rmed) * 0.85 * px.mean()), 6)  # forged bars: even
        P.append(p); N.append(n); C.append(np.tile(iron, (len(p), 1)))
    if not P:
        return []
    p, n, cc = np.concatenate(P), np.concatenate(N), np.concatenate(C)
    pw, nw, q, c = solid.on_card(p / [size[0], size[1], 1], n, pos, uv, col, size, tiled=True)
    cc = np.tile(cc, (len(pw) // len(p), 1))  # one copy per texture repeat
    a_, e1, e2 = uv[:, 0], uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    rel = q[:, None] - a_[None]
    l1 = (rel[..., 0] * e2[:, 1] - rel[..., 1] * e2[:, 0]) / det
    l2 = (e1[:, 0] * rel[..., 1] - e1[:, 1] * rel[..., 0]) / det
    keep = (np.minimum(np.minimum(l1, l2), 1 - l1 - l2) > -0.01).any(1).reshape(-1, 3).all(1)
    k = (np.nonzero(keep)[0][:, None] * 3 + [0, 1, 2]).ravel()
    return [(pw[k], nw[k], np.zeros((len(k), 2)), cc[k], np.full(len(k), MAT_ID["d_plank" if wood and "d_plank" in MAT_ID else "prop"]))]


STRIPS = ("banister", "iron", "wood")  # painted along a run of cards that turns corners: any number of facings
solids, static_hide, static_parts, static_done = {}, set(), [], set()
cfg = dict(LEVEL.get("solids") or dict(cards={}, soft=()))
cfg["cards"] = dict(cfg["cards"])
for l in tex_hash:  # painted cards (bushes, flowers, leaves, signs), by rule: real 3D stand-ins where each card stands
    for pat, kind in LEVEL.get("card_models", ()):
        if l not in cfg["cards"] and fnmatch.fnmatch(l, pat):
            cfg["cards"][l] = dict(auto=True, kind=kind)
if cfg["cards"] or cfg["soft"]:
    card_h, labels = {tex_hash[l] for l in cfg["cards"]}, collections.defaultdict(list)
    for l, h in tex_hash.items():
        labels[h].append(l)
    known = {dress.base_name(m.name.split(":", 1)[1]) for m in bpy.data.materials if m.name.startswith(("lit:", "lit+:"))}
    soft_h = {tex_hash[l] for l in cfg["soft"] if l in tex_hash}  # a bonus level may lack its twin's props
    found = solid.models(solid.capture(captures, card_h | soft_h, soft_h), card_h)
    label_of = lambda h: next((l for l in labels[h] if l in known), None)  # None: a texture from another pak, left as the game's draw
    solid_tex = {h: label_of(h) is not None and game_rgba(label_of(h))[..., 3].mean() > 0.98 for h in {d[0] for ds in found.values() for d in ds}}
    for keys, ds in sorted(found.items(), key=lambda kv: -len(kv[0])):  # a sweep frame can hold part of a model
        ds = [d for d in ds if (d[0] in card_h and label_of(d[0])) or solid_tex[d[0]]]  # see-through parts, and another pak's copies, stay the game's own draws
        strip = lambda d: cfg["cards"].get(label_of(d[0]), {}).get("kind") in STRIPS
        auto = [d for d in ds if cfg["cards"].get(label_of(d[0]), {}).get("auto") and not strip(d)]
        if auto:  # faces of a modelled object (a box, a signal) drawn one by one: joined across draws they face 3+ ways
            tp = [solid.triangles(d[2], d[3], d[4])[0] for d in auto]
            owner = np.concatenate([np.full(len(t), i) for i, t in enumerate(tp)])
            allp = np.concatenate(tp)
            bad = {int(i) for t in solid.islands(allp) if solid.orientations([allp[t]]) > 2 for i in np.unique(owner[t])}
            ds = [d for d in ds if not any(d is auto[i] for i in bad)]
        ds = [d for d in ds if not cfg["cards"].get(label_of(d[0]), {}).get("auto") or strip(d) or solid.card_pieces(*solid.triangles(d[2], d[3], d[4])[:2])]
        if not ds:
            continue
        if {(solid.key_of(d[4]), d[0]) for d in ds} <= solids.keys():
            continue
        T = [solid.triangles(d[2], d[3], d[4]) for d in ds]
        if all(d[0] in card_h for d in ds):
            pos, uv, col = (np.concatenate(x) for x in zip(*T))
            spec = cfg["cards"][label_of(ds[0][0])]
            if spec.get("links"):
                p, n, u, c = solid.chain_on_cards(pos, uv, col)
            elif spec.get("auto"):
                parts, kept, traced = [], [], {}
                for d, (dp, du, dc) in zip(ds, T):
                    lab = label_of(d[0])
                    kind = cfg["cards"][lab]["kind"]  # a placed plant mixes kinds: its leaves and its flower
                    if lab not in traced:
                        rgba = game_rgba(lab)
                        step_ = max(1, rgba.shape[0] // 256, rgba.shape[1] // 256)
                        traced[lab] = rgba[::step_, ::step_, 3], rgba[::step_, ::step_, :3]  # traced at up to 256 px
                    small, paint = traced[lab]
                    got, sil, cols = [], [], []
                    # a fence's boards run across a twisted card's two triangles: one piece, or they break at the fold
                    for t in (solid.islands(dp) if kind == "wood" else solid.flat_pieces(dp, du) if kind in STRIPS else solid.card_pieces(dp, du)):
                        tu, size = du[t], solid.repeat_size(dp[t], du[t])
                        a_ = small
                        if np.ptp(tu[..., 0]) <= 1.001 and np.ptp(tu[..., 1]) <= 1.001:  # one repeat: only the part of the texture the card shows
                            a_ = small * solid.uv_mask(tu - np.floor(tu.reshape(-1, 2).min(0) + 1e-6), small.shape)
                        if not solid.outlines(a_, 1.0, (a_.shape[1] / 48) ** 2):
                            continue
                        if kind == "bulbs":  # a painted string of lights: real bulbs where the paint has them, on a wire
                            sat_ = paint.max(2) - paint.min(2)
                            on_ = (a_ > 0.5) & (sat_ > 0.3)  # the bulbs' coloured cores: their pale halos touch
                            lab_ = np.zeros(on_.shape, int); blobs = []
                            for y0, x0 in zip(*np.nonzero(on_)):
                                if lab_[y0, x0]:
                                    continue
                                lab_[y0, x0] = len(blobs) + 1; stack, px_ = [(y0, x0)], []
                                while stack:
                                    y, x = stack.pop(); px_.append((y, x))
                                    for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                                        if 0 <= yy < on_.shape[0] and 0 <= xx < on_.shape[1] and on_[yy, xx] and not lab_[yy, xx]:
                                            lab_[yy, xx] = len(blobs) + 1; stack.append((yy, xx))
                                blobs.append(np.array(px_))
                            blobs = [b for b in blobs if len(b) > on_.size * 2e-4]
                            if not blobs:
                                continue
                            lo_, hi_ = tu.reshape(-1, 2).min(0), tu.reshape(-1, 2).max(0)
                            pts, cols_ = [], []
                            for k_ in range(int(np.floor(lo_[0] + 1e-6)), int(np.ceil(hi_[0] - 1e-6))):  # every repeat along the string
                                for b in blobs:
                                    cy, cx = b.mean(0)
                                    u_, w_ = k_ + (cx + 0.5) / on_.shape[1], np.floor(lo_[1] + 1e-6) + (cy + 0.5) / on_.shape[0]
                                    if lo_[0] <= u_ <= hi_[0] and lo_[1] <= w_ <= hi_[1]:
                                        cols_.append(np.clip(np.median(paint[b[:, 0], b[:, 1]], 0) * 1.1, 0, 1))
                                        pts.append([u_, w_, 1.3 * np.sqrt(len(b) / np.pi) / on_.shape[1]])
                            if not pts:
                                continue
                            pts = np.array(pts)
                            P_ = np.c_[pts[:, 0], pts[:, 1] - np.floor(lo_[1] + 1e-6), np.zeros(len(pts))]
                            P_ = np.r_[P_, [[2.0, 0, 0]]]  # a u past 1 makes on_card take u as given, no copies per repeat
                            W_ = solid.on_card(P_, np.tile([0, 0, 1.0], (len(P_), 1)), dp[t], tu, dc[t], size)[0][:-1]
                            order = np.argsort(pts[:, 0])
                            for i in order:
                                p, n, col = props3d.bulb(W_[i], 0.8 * pts[i, 2] * size[0], cols_[i])
                                got.append((p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])))
                            for a, b in zip(order[:-1], order[1:]):  # the wire, sagging a little between bulbs
                                mid = (W_[a] + W_[b]) / 2 + np.array([0, 0.6 * pts[a, 2] * size[0], 0])
                                for q0, q1 in ((W_[a], mid), (mid, W_[b])):
                                    p, n, col = props3d.pole(q0, q1, 0.06 * pts[a, 2] * size[0], (0.1, 0.25, 0.1))
                                    got.append((p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])))
                            continue
                        if kind == "banister":
                            got += banister_geo(small, paint, dp[t], tu, dc[t], size)
                            continue
                        if kind in ("iron", "wood"):
                            got += iron_geo(small, paint, dp[t], tu, dc[t], size, kind == "wood")
                            continue
                        if kind == "banner":  # cloth in folds under a rod, the game's paint and cut-out kept
                            v_ = solid.uv_axes(dp[t], tu)[1]
                            fu = tu.reshape(-1, 2) - np.floor(tu.reshape(-1, 2).min(0) + 1e-6)
                            along_u = abs(h_[1]) < abs(v_[1])
                            r_ = (fu[:, 1].min(), fu[:, 1].max()) if along_u else (fu[:, 0].min(), fu[:, 0].max())
                            top = r_[1] if (v_ if along_u else h_)[1] > 0 else r_[0]
                            wide = np.ptp(fu[:, 0]) * size[0] if along_u else np.ptp(fu[:, 1]) * size[1]
                            P, N = props3d.cloth((fu[:, 0].min(), fu[:, 0].max()), (fu[:, 1].min(), fu[:, 1].max()), size, along_u, top, 2.5, 0.07 * wide)
                            q = solid.on_card(P, N, dp[t], tu, dc[t], size)
                            got.append((*q, np.full(len(q[0]), card_mat(lab))))
                            ends = np.array([[fu[:, 0].min(), top, 0], [fu[:, 0].max(), top, 0]] if along_u else [[top, fu[:, 1].min(), 0], [top, fu[:, 1].max(), 0]])
                            e_ = solid.on_card(ends, np.tile([0, 0, 1.0], (2, 1)), dp[t], tu, dc[t], size)[0]
                            ax_ = e_[1] - e_[0]
                            p, n, col = props3d.pole(e_[0] - 0.08 * ax_, e_[1] + 0.08 * ax_, 0.035 * wide, (0.72, 0.55, 0.22))
                            got.append((p, n, np.zeros((len(p), 2)), col, np.full(len(p), MAT_ID["prop"])))
                            continue
                        thin = 0.02 * min(size) if kind == "sign" else 1e-3
                        P, N = solid.plate(a_, size, thin, tol=1.0, min_area=(a_.shape[1] / 48) ** 2)
                        if kind == "sign":
                            keep = np.abs(N[:, 2]).reshape(-1, 3).min(1) > 0.3  # the art's two faces only: the edge is the board's
                            P, N = P.reshape(-1, 3, 3)[keep].reshape(-1, 3), N.reshape(-1, 3, 3)[keep].reshape(-1, 3)
                        q = solid.on_card(P, N, dp[t], tu, dc[t], size)
                        if not (len(q) and len(q[0]) and np.isfinite(q[0]).all()):
                            continue
                        fam = paint_families(paint[a_ > 0.5])
                        cols.append([f * np.clip(dc[t].mean((0, 1)), 0, 1) for f in fam])
                        sil.append(q[0])
                        if kind == "leaf":
                            got.append(leaf_from(q[0], fam[0], dp.reshape(-1, 3).mean(0)))
                        elif kind == "sign":
                            got.append((*q, np.full(len(q[0]), solid_mat(label_of(d[0])))))
                            got += sign_mount(q[0], solid.uv_axes(dp[t], tu), thin, a_, d[1])
                    groups = []  # a plant's crossed cards make one model; a bed's separate flower cards one each
                    for i, q_ in enumerate(sil if kind in ("flower", "cactus") else ()):
                        g_ = next((g for g in groups if np.linalg.norm(q_.mean(0) - sil[g[0]].mean(0)) < 0.3 * max(np.ptp(q_, 0).max(), np.ptp(sil[g[0]], 0).max())), None)
                        g_.append(i) if g_ else groups.append([i])
                    for g_ in groups:
                        W = np.concatenate([sil[i] for i in g_])
                        rng_ = np.random.default_rng((solid.key_of(d[4]) + len(got)) & 0xffff)
                        main = np.clip(np.mean([cols[i][0] for i in g_], 0), 0, 1)
                        if kind == "flower":
                            is_yel = lambda f: min(f[0], f[1]) > 2.5 * f[2] and f[1] > 0.55 * f[0]  # by hue: these colours carry the baked light
                            petal = [next((f for f in cols[i] if not is_yel(f)), cols[i][0]) for i in g_]  # a big yellow middle is not the petals' colour
                            main = np.mean(petal, 0)
                            main = np.clip(main * min(1.5, 1 / max(main.max(), 1e-3)), 0, 1)  # the family's median takes in its dark outline
                            yel = [f for i in g_ for f in cols[i] if is_yel(f) and not any(f is p_ for p_ in petal)]  # a painted yellow middle
                            mid = np.clip(np.mean(yel, 0), 0, 1) if yel else np.array((0.95, 0.8, 0.2))
                            bp, bn, bc = props3d.flower(W.mean(0), 0.5 * np.ptp(W, 0).max(), main, mid, rng_, cheap=len(groups) > 3)
                        else:
                            bp, bn, bc = cactus_geo(W, main, rng_, any(fnmatch.fnmatch(lab, pat) for pat in LEVEL.get("armed_cacti", ())))
                        got.append((bp, bn, np.zeros((len(bp), 2)), bc, np.full(len(bp), MAT_ID["prop"])))
                    if sil and kind == "bush":
                        W = np.concatenate(sil)
                        base, height, radius = props3d.footprint(W)
                        rng_ = np.random.default_rng(solid.key_of(d[4]) & 0xffff)
                        fams = cols[0]
                        if len(fams) > 1:  # a two-colour bush: two clumps side by side, each its own colour
                            side_ = np.cross([0, 1.0, 0], np.linalg.svd(W - W.mean(0), full_matrices=False)[2][2])  # along the card
                            side_ /= max(np.linalg.norm(side_), 1e-6)
                            for k_, f_ in enumerate(fams[:2]):
                                got.append(bush_geo(base + side_ * radius * (0.45 if k_ else -0.45), height * (1 if k_ == 0 else 0.85), radius * 0.6, f_, rng_))
                        else:
                            got.append(bush_geo(base, height, radius, fams[0], rng_))
                    if not got:  # a draw that gave nothing stays the game's own
                        continue
                    # each draw its own prototype: a placed plant's leaves are shared by its red and blue copies
                    if "unbake" in LEVEL:  # as the game's baked light: its brightness only, so the paint keeps its colour.
                        # A flat-colour stand-in gets one brightness per piece, so its modelled shading (a cactus's ribs) stays.
                        got = [(p_, n_, u_, c_ * np.maximum(np.percentile(c_.max(1), 90) if (m_ == MAT_ID["prop"]).all() else c_.max(1, keepdims=True), 1e-4) ** (LEVEL["unbake"] - 1), m_)
                               for p_, n_, u_, c_, m_ in got]
                    p, n, u, c, m = (np.concatenate(x) for x in zip(*got))
                    kept.append((d, (p.astype(np.float32), n.astype(np.float32), dds.to_linear(np.clip(c, 0, 1)).astype(np.float32), u.astype(np.float32), m)))
                if not kept:
                    continue
                if solid._identity(ds[0][1]):
                    # the static world's cards: fixed additions and the game's texture hidden. Its draws that gave no
                    # stand-in are redrawn from the capture with the same paint. Replacing draws as the game issues them
                    # means hashing every static draw of that texture each frame (1.6 ms in the safari for its signs).
                    kept = [(d, geo) for d, geo in kept if (solid.key_of(d[4]), d[0]) not in static_done]  # a sweep frame repeats the hero's
                    static_parts.extend(geo for _, geo in kept)
                    static_done.update((solid.key_of(d[4]), d[0]) for d, _ in kept)
                    for d, (dp, du, dc) in zip(ds, T):  # a draw that gave no stand-in, next to ones that did
                        if (solid.key_of(d[4]), d[0]) not in static_done:
                            static_done.add((solid.key_of(d[4]), d[0]))
                            nrm = np.cross(dp[:, 1] - dp[:, 0], dp[:, 2] - dp[:, 0])
                            nrm = np.repeat(nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9), 3, 0)
                            static_parts.append((dp.reshape(-1, 3).astype(np.float32), nrm.astype(np.float32), dds.to_linear(dc.reshape(-1, 3)).astype(np.float32),
                                                 du.reshape(-1, 2).astype(np.float32), np.full(len(dp) * 3, card_mat(label_of(d[0])))))
                    static_hide.update(d[0] for d in ds)
                else:
                    for d, geo in kept:
                        solids.setdefault((solid.key_of(d[4]), d[0]), add_proto("solid%d" % len(protos), *geo))
                print("export: real 3D %s for %d game draws, %s" % (sorted({cfg["cards"][label_of(d[0])]["kind"] for d, _ in kept}), len(kept), sorted({labels[d[0]][0].rsplit("/", 1)[1] for d, _ in kept})))
                continue
            else:
                # the same thickness in the world, whatever scale the game places this model at
                P, N = solid.plate(game_rgba(label_of(ds[0][0]))[..., 3], spec["size"], spec["depth"] / np.linalg.norm(ds[0][1][:3]),
                                   tol=spec["tol"], min_area=spec["area"], repeat=spec.get("repeat", 1))
                pieces = T if spec.get("each_draw") else [(pos[t], uv[t], col[t]) for t in solid.islands(pos)]  # a railing's sides touch but each repeats the paint
                p, n, u, c = (np.concatenate(x) for x in zip(*(solid.on_card(P, N, *q, spec["size"]) for q in pieces)))
            if "unbake" in LEVEL:  # a night level bakes its light into these: the moon does the shading now
                c = c ** LEVEL["unbake"]
            vc = dds.to_linear(c) if spec.get("mat") is None else np.ones_like(p)
            m = np.full(len(p), solid_mat(label_of(ds[0][0]), spec.get("tint", (1, 1, 1))) if spec.get("mat") is None else MAT_ID[spec["mat"]])
        else:
            mats = [solid_mat(label_of(d[0])) for d in ds]
            tex = np.concatenate([np.full(len(t[0]), i) for i, t in enumerate(T)])
            cac = [i for i, d in enumerate(ds) if any(fnmatch.fnmatch(label_of(d[0]), pat) for pat in LEVEL.get("cacti", ()))]
            if cac:  # a low-poly cactus model: a modelled saguaro or barrel over its footprint, and its flower if it has one
                rng_ = np.random.default_rng(solid.key_of(ds[0][4]) & 0xffff)
                W = np.concatenate([T[i][0].reshape(-1, 3) for i in cac])
                colour = np.clip(np.mean([game_rgba(label_of(ds[i][0]))[..., :3].reshape(-1, 3).mean(0) for i in cac], 0), 0, 1)
                pp, nn, cc = cactus_geo(W, colour, rng_, all(any(fnmatch.fnmatch(label_of(ds[i][0]), pat) for pat in LEVEL.get("armed_cacti", ())) for i in cac))
                for i in set(range(len(ds))) - set(cac):
                    q = T[i][0].reshape(-1, 3)
                    f_p, f_n, f_c = props3d.flower(q.mean(0), 0.5 * np.ptp(q, 0).max(), paint_families(game_rgba(label_of(ds[i][0]))[..., :3].reshape(-1, 3))[0], (0.95, 0.8, 0.2), rng_)
                    pp, nn, cc = np.concatenate([pp, f_p]), np.concatenate([nn, f_n]), np.concatenate([cc, f_c])
                p, n, u, m, vc = pp, nn, np.zeros((len(pp), 2)), np.full(len(pp), MAT_ID["prop"]), dds.to_linear(cc)
            else:
                p, n, u, mi = solid.rounded(np.concatenate([t[0] for t in T]), np.concatenate([t[1] for t in T]), tex)
                m, vc = np.array(mats)[mi], np.ones_like(p)
        pi = add_proto("solid%d" % len(protos), p.astype(np.float32), n.astype(np.float32), vc.astype(np.float32), u.astype(np.float32), m)
        print("export: replaces %d game draws, %s: %d triangles" % (len(ds), sorted({labels[d[0]][0].rsplit("/", 1)[1] for d in ds}), len(p) // 3))
        for d in ds:
            solids.setdefault((solid.key_of(d[4]), d[0]), pi)  # the same model can come in several paints

def cluster_geo(kind, T, labs, rng):
    """One reimagined fir for a cluster of tree cards, or icicles for each ledge card."""
    W = np.concatenate([t[0].reshape(-1, 3) for t in T])
    paint = np.concatenate([game_rgba(l)[::4, ::4].reshape(-1, 4) for l in sorted(set(labs))])
    fam = paint_families(paint[paint[:, 3] > 0.5, :3])
    lit = np.clip(np.concatenate([t[2].reshape(-1, 3) for t in T]).mean(0), 0.3, 1)  # the baked light, as on the game's cards
    c = np.clip(fam[0] * lit, 0, 1)
    if kind == "icicles":
        got = []
        for dp, du, dc in T:
            for t in solid.card_pieces(dp, du) or ():
                tu, size = du[t], solid.repeat_size(dp[t], du[t])
                v_ = solid.uv_axes(dp[t], tu)[1]
                a = game_rgba(labs[0])[..., 3] > 0.5
                fu = tu.reshape(-1, 2)
                u0, u1, v0, v1 = fu[:, 0].min(), fu[:, 0].max(), fu[:, 1].min(), fu[:, 1].max()
                down = 1 if v_[1] < 0 else -1  # v runs down the wall
                width, n = (u1 - u0) * size[0], max(2, int((u1 - u0) * size[0] / 48))  # few chunky icicles read better than a comb
                xs = np.linspace(0.5, n - 0.5, n) / n
                col_ = ((u0 + xs * (u1 - u0)) % 1 * a.shape[1]).astype(int)
                run = a[:, col_][::down].mean(0) * (v1 - v0) * size[1]  # paint below the ledge in each column
                P, N, C = props3d.icicles(width, (xs + rng.uniform(-0.2, 0.2, n) / n) * width, run * rng.uniform(0.55, 1.15, n), min(0.4 * width / n, 20.0), np.clip(c * 0.7 + 0.3, 0, 1), (0.96, 0.98, 1.0))
                top = v0 if down > 0 else v1
                Q = np.c_[u0 + P[:, 0] / size[0], top + down * P[:, 1] / size[1], P[:, 2]]
                Q = np.r_[Q, [[2.0, 0, 0]]]  # u past 1: on_card takes u as given
                q = solid.on_card(Q, np.r_[N * [1, down, 1], [[0, 0, 1.0]]], dp[t], tu, dc[t], size)
                got.append((q[0][:-1], q[1][:-1], C))
        return [np.concatenate(x) for x in zip(*got)] if got else None
    base, height, _ = props3d.footprint(W)
    tint = c if fam[0][1] < fam[0][0] or fam[0][2] > fam[0][1] else np.array((0.2, 0.58, 0.42)) * lit  # the white-and-green paint: an evergreen
    return props3d.pine(base, height, 0.52 * np.ptp(W[:, [0, 2]], 0).max(), tint, np.clip(lit * 1.05, 0, 1), rng, kind == "frost")


for pats, kind in LEVEL.get("clusters", ()):  # cards that together draw one tree, or a fringe of icicles: a model each
    known_ = {dress.base_name(m.name.split(":", 1)[1]) for m in bpy.data.materials if m.name.startswith(("lit:", "lit+:"))}
    labs_ = {tex_hash[l]: l for l in tex_hash if l in known_ and any(fnmatch.fnmatch(l, p) for p in pats)}
    got_ = {}
    for d in solid.capture(captures, set(labs_)):
        got_.setdefault((solid.key_of(d[4]), d[0]), d)
    items = []
    for k, d in got_.items():
        if k in solids or k in static_done:
            continue
        t = solid.triangles(d[2], d[3], d[4])
        e1, e2 = t[1][:, 1] - t[1][:, 0], t[1][:, 2] - t[1][:, 0]
        t = tuple(x[np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 1e-6] for x in t)  # a strip's stitches carry no paint
        if not len(t[0]):
            continue
        # one static draw can carry cards all over the level: each piece on its own
        items += [(k, d, tuple(x[i] for x in t)) for i in solid.islands(t[0])] if solid._identity(d[1]) else [(k, d, t)]
    def fits(t, size):  # standing or leaning cards of the usual size: the same paint also lies on the ground or spans a hill
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        return len(t) and np.abs(n[:, 1]).sum() < (0.5 if kind == "icicles" else 0.85) * np.linalg.norm(n, axis=1).sum() and np.ptp(t.reshape(-1, 3), 0).max() < 3 * size
    size_ = np.median([np.ptp(it[2][0].reshape(-1, 3), 0).max() for it in items]) if items else 0
    left = [it for it in items if not fits(it[2][0], size_)]
    items = [it for it in items if fits(it[2][0], size_)]
    items.sort(key=lambda it: -np.ptp(it[2][0].reshape(-1, 3), 0).max())
    groups = []  # biggest first: each card joins the first seed it stands within, so a forest doesn't chain into one tree
    for it in items:
        q = it[2][0].reshape(-1, 3)
        cen, w = q.mean(0), np.ptp(q[:, [0, 2]], 0).max()
        g = None if kind == "icicles" else next((g for g in groups if g[0] == tuple(np.round(it[1][1], 3)) and np.hypot(*(cen - g[1])[[0, 2]]) < max(0.45 * max(g[2], w), 1.3 * size_)), None)
        g[3].append(it) if g else groups.append((tuple(np.round(it[1][1], 3)), cen, w, [it]))
    n_ = 0
    for _, _, _, members in groups:
        rng_ = np.random.default_rng(members[0][0][0] & 0xffff)
        geo = cluster_geo(kind, [m[2] for m in members], [labs_[m[1][0]] for m in members], rng_)
        if geo is None:
            continue
        p, n, c = geo
        g = (p.astype(np.float32), n.astype(np.float32), dds.to_linear(np.clip(c, 0, 1)).astype(np.float32), np.zeros((len(p), 2), np.float32), np.full(len(p), MAT_ID["prop"]))
        n_ += len(p) // 3
        if solid._identity(members[0][1][1]):
            static_parts.append(g)
            static_hide.update(m[1][0] for m in members)
            static_done.update(m[0] for m in members)
        else:
            pi = add_proto("cluster%d" % len(protos), *g)
            for m in members:
                solids[m[0]] = pi
    for k, d, (dp, du, dc) in left:  # the hidden paint's other static draws stay, redrawn from the capture
        if d[0] in static_hide and solid._identity(d[1]):
            static_done.add(k)
            nrm = np.cross(dp[:, 1] - dp[:, 0], dp[:, 2] - dp[:, 0])
            nrm = np.repeat(nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9), 3, 0)
            static_parts.append((dp.reshape(-1, 3).astype(np.float32), nrm.astype(np.float32), dds.to_linear(dc.reshape(-1, 3)).astype(np.float32),
                                 du.reshape(-1, 2).astype(np.float32), np.full(len(dp) * 3, card_mat(labs_[d[0]]))))
    print("export: real 3D %s for %d game draws in %d models, %d triangles; %d draws kept" % (kind, len(items), len(groups), n_, len(left)))

if static_parts:  # the static world's stand-ins, merged per chunk: one proto each, not one per card (fewer draws)
    p, n, c, u, m = (np.concatenate(x) for x in zip(*static_parts))
    cen = p.reshape(-1, 3, 3).mean(1)
    cell = (np.floor(cen[:, 0] / CHUNK).astype(np.int64) << 32) + np.floor(cen[:, 2] / CHUNK).astype(np.int64)
    for cid in np.unique(cell):
        t = np.where(cell == cid)[0]
        k = (t[:, None] * 3 + [0, 1, 2]).ravel()
        place.append((add_proto("standins.%d" % (cid & 0xffff), p[k], n[k], c[k], u[k], m[k]), None))

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
hide, shade, binds, glows, hash_of = set(static_hide), set(), {}, {}, {}


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
    elif role in HIDDEN_ROLES or role == LEVEL.get("dome") or label in (LEVEL.get("wire"), LEVEL.get("chain"), LEVEL.get("grill")):
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
            if w[ix].sum() < 2.0 or not cfg["pool_power"]:   # a stray warm vertex is not a light
                continue
            q = np.average(p[ix], 0, weights=w[ix])
            out.append(((q[0], q[2] + cfg["pool_height"], q[1]), cfg["pool_radius"], colour * cfg["pool_power"], cfg["pool_cone"]))
    print("export: %d lamps, %d baked pools" % (len(lamps), len(out) - len(lamps)))
    out += [((x, z, y), r, np.array(kit.srgb(c)) * p, cone[0] if cone else -0.2) for x, y, z, r, c, p, *cone in cfg.get("extra", ())]  # optional 7th: a spot's cone
    return [(*(np.array(p) * K), r * K, *c, cone) for p, r, c, cone in out[:64]]


lights = level_lights(LEVEL["lamps"]) if "lamps" in LEVEL else []

# ---------------------------------------------------------------- sky
sky_scale, sky_bytes = 1.0, 0
if not LEVEL.get("game_sky"):  # otherwise the game's own painted backdrop stays
    eye = bpy.data.objects["hero camera"].matrix_world.translation.copy() if "hero camera" in bpy.data.objects else Vector()
    sky = np.asarray(bake.bake_sky(cache, sc, eye, panels=LEVEL.get("sky_panels", False), night=LEVEL.get("night_sky", True)), np.float32)
    if not LEVEL.get("night_sky", True):
        sky = bake.fill_ceiling(sky)
    if "sea" in LEVEL:  # the sea painted under the horizon, seen past the level's edge
        sky = bake.sea_below(sky, kit.srgb(LEVEL["sea"]), kit.srgb(LEVEL["sea_horizon"]) if "sea_horizon" in LEVEL else None)
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
    if lights or glows or swaps or solids:  # optional sections, absent for a level without local lights
        f.write(struct.pack("<I", len(lights)) + b"".join(struct.pack("<8f", *l) for l in lights))
        f.write(struct.pack("<I", len(glows)) + b"".join(struct.pack("<Q3fI", h, *glows[h]) for h in sorted(glows)))
        f.write(struct.pack("<I", len(swaps)) + b"".join(struct.pack("<Q4f", *s_, 2.0) for s_ in swaps))
    if solids:
        f.write(struct.pack("<I", len(solids)) + b"".join(struct.pack("<QQI", *k, solids[k]) for k in sorted(solids)))

# ---------------------------------------------------------------- level.ini
sun, grade, sk = LV["sun"], LV["grade"], LV["sky"]
az, el = math.radians(sun["sun_azimuth"]), math.radians(sun["sun_elevation"])
amb = np.array(kit.srgb(sk["ambient"])) * grade["ambient_strength"]
fog_start = grade["fog_start"] * SC * K
vals = [
    ("sun_dir", (math.cos(az) * math.cos(el), math.sin(el), math.sin(az) * math.cos(el))),
    ("sun_color", np.array(kit.srgb(sun["sun_color"])) * sun["sun_strength"] / math.pi),
    ("sky_ambient", amb), ("ground_ambient", amb * np.array(LEVEL.get("ground_tint", (0.55, 0.47, 0.38)))),
    ("shadow_softness", math.tan(math.radians(1.0))), ("ao_radius", 2.5 * SC * K), ("ao_strength", 1.0),
    ("fog_color", kit.srgb(LEVEL.get("fog_color", "#b8d6f2"))), ("fog_start", fog_start),
    ("fog_end", fog_start + grade["fog_depth"] * SC * K / grade["fog"]),  # Blender's fog tops out at this 7%
    ("exposure", 2 ** grade["exposure"]), ("bloom_threshold", LEVEL.get("bloom_threshold", 0.9)), ("bloom_strength", grade["bloom"]),
    ("saturation", grade["saturation"]), ("contrast", LEVEL.get("contrast", 1.15)),
    ("water_height", water_y), ("water_color", kit.srgb(LEVEL.get("water_color", "#2aa6c8"))), ("water_clarity", LEVEL.get("water_clarity", 0.72)),
    ("grass_fade_start", 5000.0), ("grass_fade_end", 10000.0), ("sky_scale", sky_scale * LEVEL.get("sky_gain", 1.0)),
] + [(k, LEVEL[k]) for k in ("unbake", "unbake_keep", "char_fill", "char_keep", "char_lamp", "hold", "shadow_floor", "glow_add") if k in LEVEL]
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
if not bind_list and any(LEVEL.get(k) for k in ("binds", "detail")):  # a level with material rules always binds some
    raise RuntimeError("export bound no game textures to materials: the level would draw as plain HD paint")
prev = json.load(open(os.path.join(cache, "report.json"))).get("binds") if os.path.exists(os.path.join(cache, "report.json")) else None
print("export: %d binds (previous export %s)" % (len(bind_list), prev))
json.dump(report, open(os.path.join(cache, "report.json"), "w"), indent=1)
swap(tmp, out)
print("export:", json.dumps({k: v for k, v in report.items() if k != "brick_masks"}))
