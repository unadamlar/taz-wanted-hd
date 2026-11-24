"""Look kit: stylized-remake dressing for flat-coloured low-poly game geometry.

Everything here is real-time-renderer friendly: Eevee, one shadow-mapped sun,
screen-space AO/GI, bloom, procedural 3D (world-position) materials with bump,
instanced grass/clutter, alpha-tested foliage cards. Nothing moves the game's
own vertices; dressing is added on top as new objects.

All sizes are in "hero metres" multiplied by `scale` (hero height / 1.2 m).

Tagging: a face's role comes from its material's ["look"] property, else the
object's ["look"] property, else `roles` name patterns passed to apply().
Surface roles: dirt lawn cliff cliff_top brick trim wood stone rock water bark
foliage. Prop roles (object hidden, replaced by a kit prop sized from its
bounds): tree fence boulder.
"""
import bpy, bmesh, math, fnmatch, os, time
import numpy as np
from mathutils import Vector, Matrix, kdtree, noise as mnoise
from mathutils.bvhtree import BVHTree
from pathlib import Path


def out_dir():
    if os.environ.get("TAZ_LOOK_OUT"):
        return Path(os.environ["TAZ_LOOK_OUT"])
    for p in Path(__file__).resolve().parents:
        if (p / "extracted").is_dir():
            return p / "extracted" / "look"
    raise RuntimeError("set TAZ_LOOK_OUT")


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


# ---------------------------------------------------------------- node helpers

def _sock(socks, k):
    if isinstance(k, int):
        return socks[k]
    for s in socks:
        if s.identifier == k and s.enabled:
            return s
    for s in socks:
        if s.name == k and s.enabled:
            return s
    for s in socks:
        if s.identifier == k or s.name == k:
            return s
    raise KeyError(f"{k} not in {[s.identifier for s in socks]}")


class _B:
    """Tiny node-graph builder: b('ShaderNodeMath', {0: x, 1: 2}, operation='MULTIPLY')."""

    def __init__(self, tree):
        self.t = tree

    def __call__(self, typ, inputs=None, **props):
        n = self.t.nodes.new(typ)
        for k, v in props.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(n, k, v)
        return n

    def set(self, n, k, v):
        s = _sock(n.inputs, k)
        if isinstance(v, bpy.types.Node):
            v = o(v)
        if isinstance(v, bpy.types.NodeSocket):
            self.t.links.new(v, s)
        else:
            if isinstance(v, (tuple, list)) and len(v) == 3 and s.type == "RGBA":
                v = (*v, 1.0)
            s.default_value = v

    # shorthands -----------------------------------------------------------
    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        return o(self("ShaderNodeMath", {0: a, 1: b, 2: c}, operation=op, use_clamp=clamp))

    def vmath(self, op, a, b=(0, 0, 0), out=0):
        if op == "SCALE":
            n = self("ShaderNodeVectorMath", {0: a}, operation=op)
            self.set(n, "Scale", b)
        else:
            n = self("ShaderNodeVectorMath", {0: a, 1: b}, operation=op)
        return n.outputs[out] if op not in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Value"]

    def mix(self, fac, a, b, blend="MIX"):
        return o(self("ShaderNodeMix", {"Factor_Float": fac, "A_Color": a, "B_Color": b},
                      data_type="RGBA", blend_type=blend), "Result_Color")

    def ramp(self, fac, stops, interp="LINEAR"):
        n = self("ShaderNodeValToRGB", {0: fac})
        cr = n.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for e, (p, c) in zip(cr.elements, stops):
            e.position = p
            e.color = (*c, 1.0) if len(c) == 3 else c
        return n.outputs["Color"]

    def fac_ramp(self, fac, a, b):
        """smoothstep-ish remap of fac from [a,b] to [0,1]."""
        return o(self("ShaderNodeMapRange", {"Value": fac, "From Min": a, "From Max": b},
                      interpolation_type="SMOOTHSTEP", clamp=True))

    def noise(self, vec, scale, detail=3.0, rough=0.5, distort=0.0, out="Fac"):
        return self("ShaderNodeTexNoise", {"Vector": vec, "Scale": scale, "Detail": detail,
                                           "Roughness": rough, "Distortion": distort}).outputs[out]

    def voronoi(self, vec, scale, feature="F1", out="Distance", rand=1.0):
        return self("ShaderNodeTexVoronoi", {"Vector": vec, "Scale": scale, "Randomness": rand},
                    feature=feature).outputs[out]

    def sep(self, v):
        n = self("ShaderNodeSeparateXYZ", {0: v})
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, x=0.0, y=0.0, z=0.0):
        return o(self("ShaderNodeCombineXYZ", {0: x, 1: y, 2: z}))


def o(n, name=None):
    if name is None:
        for s in n.outputs:
            if s.enabled:
                return s
    return _sock(n.outputs, name)


# ---------------------------------------------------------------- lighting/render

def setup_render(scene, camera=None, *, scale=1.0, res=(1920, 1080), samples=64,
                 sun_azimuth=215.0, sun_elevation=30.0, sun_strength=5.0,
                 sun_color="#ffe0b5", sun_angle=2.0, exposure=0.0,
                 look="AgX - Punchy", saturation=1.15,
                 bloom=0.35, fog=0.3, fog_start=18.0, fog_depth=90.0,
                 dof_target=None, fstop=2.8, clouds=True, ambient_strength=0.65, sky=None):
    """Sun + sky + Eevee + post. Azimuth: compass angle the sun shines FROM
    (0 = +X, 90 = +Y), degrees. Distances in hero metres (multiplied by scale)."""
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    r.image_settings.file_format = "JPEG"
    r.image_settings.quality = 93
    e = scene.eevee
    e.taa_render_samples = samples
    e.use_shadows = True
    e.shadow_ray_count = 2
    e.shadow_step_count = 8
    e.use_fast_gi = True
    e.fast_gi_method = "GLOBAL_ILLUMINATION"
    e.fast_gi_distance = 2.5 * scale
    e.fast_gi_quality = 0.5
    e.use_raytracing = True
    e.ray_tracing_method = "SCREEN"
    vs = scene.view_settings
    vs.view_transform = "AgX"
    try:
        vs.look = look
    except TypeError:
        pass
    vs.exposure = exposure

    for ob in [o_ for o_ in scene.objects if o_.type == "LIGHT" and o_.name.startswith("kit_sun")]:
        bpy.data.objects.remove(ob)
    ld = bpy.data.lights.new("kit_sun", "SUN")
    ld.energy = sun_strength
    ld.color = srgb(sun_color)
    ld.angle = math.radians(sun_angle)
    ld.shadow_maximum_resolution = 0.002 * scale
    ld.shadow_cascade_max_distance = 120 * scale
    sun = bpy.data.objects.new("kit_sun", ld)
    scene.collection.objects.link(sun)
    az, el = math.radians(sun_azimuth), math.radians(sun_elevation)
    d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
    sun.rotation_euler = d.to_track_quat("Z", "Y").to_euler()

    setup_sky(scene, clouds=clouds, ambient_strength=ambient_strength, **(sky or {}))
    if camera is not None:
        cd = camera.data
        cd.dof.use_dof = dof_target is not None
        if dof_target is not None:
            cd.dof.focus_object = dof_target
            cd.dof.aperture_fstop = fstop
    scene.view_layers[0].use_pass_mist = True
    scene.world.mist_settings.start = fog_start * scale
    scene.world.mist_settings.depth = fog_depth * scale
    scene.world.mist_settings.falloff = "QUADRATIC"
    _compositor(scene, bloom, saturation, fog)
    return sun


def setup_sky(scene, clouds=True, zenith="#2a66d6", horizon="#a8cff3",
              ambient="#c4d2e4", ambient_strength=0.65, horizon_warm="#e8e2d6", sky_strength=1.0, cloud_white=1.0,
              hdri=None, hdri_rotation=0.0, hdri_strength=1.0, hdri_saturation=1.2):
    """Camera sees a soft blue gradient with wispy clouds; lighting sees a flat
    pale-blue ambient (a game would use a fixed ambient/SH term)."""
    w = bpy.data.worlds.get("kit_sky") or bpy.data.worlds.new("kit_sky")
    scene.world = w
    w.use_nodes = True
    t = w.node_tree
    t.nodes.clear()
    b = _B(t)
    d = o(b("ShaderNodeTexCoord"), "Generated")
    d = b.vmath("NORMALIZE", d)
    x, y, z = b.sep(d)
    zc = b.math("MAXIMUM", z, 0.0)
    grad = b.ramp(b.math("POWER", zc, 0.55), [(0.0, srgb(horizon_warm)), (0.12, srgb(horizon)), (1.0, srgb(zenith))])
    col = grad
    if clouds:
        # project onto a cloud plane; stretch noise for wisps
        k = b.math("ADD", zc, 0.08)
        px = b.math("DIVIDE", x, k)
        py = b.math("DIVIDE", y, k)
        uv = b.comb(b.math("MULTIPLY", px, 0.8), b.math("MULTIPLY", py, 1.4), 0.0)
        # wisps: mildly stretched, distorted noise
        n1 = b.noise(uv, 1.1, detail=6, rough=0.6, distort=1.2)
        n2 = b.noise(uv, 4.0, detail=4, rough=0.6)
        wisp = b.fac_ramp(b.math("ADD", n1, b.math("MULTIPLY", b.math("SUBTRACT", n2, 0.5), 0.4)), 0.55, 0.72)
        # a few puffy clumps: isotropic noise gated by a sparse low-frequency mask
        uv2 = b.comb(px, py, 0.0)
        puff = b.fac_ramp(b.noise(uv2, 2.2, detail=5, rough=0.55), 0.5, 0.62)
        puff = b.math("MULTIPLY", puff, b.fac_ramp(b.noise(uv2, 0.45, 2), 0.55, 0.65))
        cm = b.math("MAXIMUM", b.math("MULTIPLY", wisp, 0.75), puff)
        fade = b.fac_ramp(z, 0.02, 0.25)
        cm = b.math("MULTIPLY", cm, fade)
        cm = b.math("MULTIPLY", cm, 0.95)
        col = b.mix(cm, grad, (cloud_white,) * 3)
    if hdri:
        # photographed clouds composited over the clean stylized gradient: cloud mask =
        # bright, unsaturated HDRI pixels (a game would bake this into its sky cubemap)
        tc = o(b("ShaderNodeTexCoord"), "Generated")
        mp = b("ShaderNodeMapping", {"Vector": tc, "Rotation": (0, 0, math.radians(hdri_rotation))})
        env = o(b("ShaderNodeTexEnvironment", {"Vector": o(mp)}, image=bpy.data.images.load(str(hdri), check_existing=True)))
        er, eg, eb = b.sep(env)
        cloud = b.fac_ramp(b.math("DIVIDE", b.math("ADD", er, eg), b.math("ADD", b.math("MULTIPLY", eb, 2.0), 1e-3)), 0.62, 0.9)
        lum = b.math("ADD", b.math("MULTIPLY", er, 0.3), b.math("ADD", b.math("MULTIPLY", eg, 0.59), b.math("MULTIPLY", eb, 0.11)))
        shade = b.math("MINIMUM", b.math("DIVIDE", lum, 1.2), 1.0)
        cc = b.mix(shade, (0.72, 0.78, 0.88), (cloud_white,) * 3)
        col = b.mix(b.math("MULTIPLY", cloud, b.fac_ramp(z, 0.0, 0.06)), grad, cc)
    bg_cam = b("ShaderNodeBackground", {"Color": col, "Strength": sky_strength})
    bg_amb = b("ShaderNodeBackground", {"Color": srgb(ambient), "Strength": ambient_strength})
    lp = b("ShaderNodeLightPath")
    ms = b("ShaderNodeMixShader", {0: o(lp, "Is Camera Ray"), 1: bg_amb, 2: bg_cam})
    b("ShaderNodeOutputWorld", {"Surface": ms})
    return w


def _compositor(scene, bloom, saturation, fog, fog_color="#b8d6f2"):
    t = bpy.data.node_groups.get("kit_post")
    if t:
        bpy.data.node_groups.remove(t)
    t = bpy.data.node_groups.new("kit_post", "CompositorNodeTree")
    t.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    b = _B(t)
    rl = b("CompositorNodeRLayers")
    img = o(rl, "Image")
    if fog > 0:
        mist = o(rl, "Mist")
        f = o(b("CompositorNodeMath", {0: mist, 1: fog}, operation="MULTIPLY") if hasattr(bpy.types, "CompositorNodeMath")
              else b("ShaderNodeMath", {0: mist, 1: fog}, operation="MULTIPLY"))
        mx = b("ShaderNodeMix", {"Factor_Float": f, "A_Color": img, "B_Color": (*srgb(fog_color), 1.0)},
               data_type="RGBA")
        img = o(mx, "Result_Color")
    if bloom > 0:
        g = b("CompositorNodeGlare", {"Image": img})
        g.inputs["Type"].default_value = "Bloom"
        b.set(g, "Highlights Threshold", 0.9)
        b.set(g, "Strength", bloom)
        b.set(g, "Size", 0.6)
        img = o(g, "Image")
    hs = b("CompositorNodeHueSat", {"Image": img})
    b.set(hs, "Saturation", saturation)
    img = o(hs)
    out = b("NodeGroupOutput")
    t.links.new(img, out.inputs[0])
    scene.compositing_node_group = t
    scene.render.use_compositing = True


# ---------------------------------------------------------------- materials

_MATS = {}


def _new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes.clear()
    return m, _B(m.node_tree)


def _wp(b, scale, s=1.0):
    p = o(b("ShaderNodeNewGeometry"), "Position")
    return b.vmath("SCALE", p, s / scale)


def _tintmul(tint, ref, amount):
    if tint is None:
        return (1.0, 1.0, 1.0)
    return tuple(max(0.35, min(2.5, 1 + amount * (t / max(r, 1e-3) - 1))) for t, r in zip(tint, ref))


def _finish(b, col, rough, normal=None, tint=None, ref=None, amount=0.35, spec=0.5, alpha=None, extra=None):
    tm = _tintmul(tint, ref, amount)
    if tm != (1.0, 1.0, 1.0):
        col = b.mix(1.0, col, tm, "MULTIPLY")
    ins = {"Base Color": col, "Roughness": rough, "Specular IOR Level": spec}
    if normal is not None:
        ins["Normal"] = normal
    if alpha is not None:
        ins["Alpha"] = alpha
    ins.update(extra or {})
    p = b("ShaderNodeBsdfPrincipled", ins)
    b("ShaderNodeOutputMaterial", {"Surface": p})
    return p


def _bump(b, h, strength, dist, normal=None):
    ins = {"Height": h, "Strength": strength, "Distance": dist}
    if normal is not None:
        ins["Normal"] = normal
    return o(b("ShaderNodeBump", ins))


def _wnormal(b):
    return o(b("ShaderNodeNewGeometry"), "Normal")


REF = {
    "lawn": srgb("#4f8f2a"), "dirt": srgb("#b0764a"), "cliff": srgb("#f0c8b0"),
    "brick": srgb("#a8462e"), "trim": srgb("#e6dcc4"), "wood": srgb("#ece8de"),
    "stone": srgb("#9b9a95"), "rock": srgb("#a09a8e"), "water": srgb("#2a8db8"),
    "bark": srgb("#6e4b30"), "foliage": srgb("#4c9a2c"), "lawn_far": srgb("#5c9a34"),
}


def material(role, tint=None, scale=1.0, amount=0.35):
    """Kit material for a role. tint: linear RGB of the game's flat colour (or None)."""
    key = (role, None if tint is None else tuple(round(c, 3) for c in tint), round(scale, 4))
    m = _MATS.get(key)
    if m and m.name in bpy.data.materials:
        return m
    fn = {"lawn": mat_grass_ground, "cliff_top": mat_grass_ground, "dirt": mat_dirt,
          "cliff": mat_sandstone, "brick": mat_brick, "trim": mat_trim_stone, "wood": mat_wood,
          "stone": mat_stone_blocks, "rock": mat_rock, "water": mat_water, "bark": mat_bark,
          "foliage": mat_foliage, "lawn_far": mat_far_grass}[role]
    m = fn(tint=tint, scale=scale, amount=amount)
    m["look"] = role
    _MATS[key] = m
    return m


def mat_grass_ground(tint=None, scale=1.0, amount=0.35):
    """Soil with mossy patches: what shows between grass tufts. It matches the
    dirt so thinned lawn edges fade into the path instead of showing the
    polygon's hard edge. The game's lawn colour is ignored on purpose."""
    m, b = _new_mat("kit_grass_ground")
    c, h = _grass_ground(b, _wp(b, scale))
    _finish(b, c, 0.92, _bump(b, h, 0.5, 0.03 * scale))
    return m


def _grass_ground(b, p):
    c, h = _dirt(b, p)
    c = b.mix(1.0, c, (0.8, 0.78, 0.72), "MULTIPLY")
    moss = b.fac_ramp(b.noise(p, 1.4, 4, 0.6), 0.45, 0.6)
    c = b.mix(b.math("MULTIPLY", moss, 0.75), c, b.ramp(b.noise(p, 5.0, 2), [(0.3, srgb("#3c5a1c")), (0.7, srgb("#557528"))]))
    return c, h


# ---- materials steered by the game's own painted texture (through its UVs) --------
# The game's UVs only place painted swatches, but where a texture paints *structure*
# (the grass fringe along path strips, cream quoins on brick) its own mapping is the
# exact outline, so it is used as a mask, never to project the new surface.

def _game_tex(b, image):
    tx = b("ShaderNodeTexImage", {"Vector": o(b("ShaderNodeUVMap", uv_map="UVMap"))}, image=image)
    return o(tx, "Color"), o(tx, "Alpha")


def green_mask_node(b, col):
    """1 where the game texture paints grass (green dominant)."""
    r, g, bl = b.sep(col)
    d = b.math("SUBTRACT", g, b.math("MAXIMUM", r, bl))
    return b.fac_ramp(d, 0.04, 0.12)


def light_mask_node(b, col, lo=0.55, hi=0.7):
    """1 where the game texture is pale and unsaturated (cream stone trim)."""
    r, g, bl = b.sep(col)
    lum = b.math("ADD", b.math("MULTIPLY", r, 0.3), b.math("ADD", b.math("MULTIPLY", g, 0.59), b.math("MULTIPLY", bl, 0.11)))
    sat = b.math("SUBTRACT", b.math("MAXIMUM", r, b.math("MAXIMUM", g, bl)), b.math("MINIMUM", r, b.math("MINIMUM", g, bl)))
    return b.math("MULTIPLY", b.fac_ramp(lum, lo, hi), b.math("SUBTRACT", 1.0, b.fac_ramp(sat, 0.25, 0.45)))


def mat_cliff_overlay(image, mean, scale=1.0, tint=None, amount=0.25, strength=0.75, drips=True):
    """Kit sandstone keeping the game texture's painted strata (multiplied in)."""
    key = ("cliff_overlay", image.name, round(scale, 4), round(amount, 3), drips)
    if key in _MATS and _MATS[key].name in bpy.data.materials:
        return _MATS[key]
    m = mat_sandstone(tint, scale, amount, overlay=image, overlay_mean=mean, overlay_strength=strength, drips=drips)
    m.name = "kit_sandstone~" + image.name
    m["look"] = "cliff"
    _MATS[key] = m
    return m


def mat_ground_masked(image, scale=1.0, tint=None, amount=0.15):
    """Path ground: kit dirt, turning into grass soil where the game texture paints grass."""
    key = ("ground_masked", image.name, round(scale, 4))
    if key in _MATS and _MATS[key].name in bpy.data.materials:
        return _MATS[key]
    m, b = _new_mat("kit_ground~" + image.name)
    p = _wp(b, scale)
    col, _ = _game_tex(b, image)
    gm = green_mask_node(b, col)
    cd, hd = _dirt(b, p)
    tm = _tintmul(tint, REF["dirt"], amount)
    cd = b.mix(1.0, cd, tm, "MULTIPLY")
    cg, hg = _grass_ground(b, p)
    c = b.mix(gm, cd, cg)
    h = b.math("ADD", b.math("MULTIPLY", hd, b.math("SUBTRACT", 1.0, gm)), b.math("MULTIPLY", hg, gm))
    _finish(b, c, 0.9, _bump(b, h, 0.55, 0.03 * scale))
    m["look"] = "dirt"
    _MATS[key] = m
    return m


def mat_brick_masked(image, scale=1.0):
    """Brick where the game texture paints brick, pale dressed stone where it paints cream trim."""
    key = ("brick_masked", image.name, round(scale, 4))
    if key in _MATS and _MATS[key].name in bpy.data.materials:
        return _MATS[key]
    m, b = _new_mat("kit_brick~" + image.name)
    p = _wp(b, scale)
    col, _ = _game_tex(b, image)
    lm = light_mask_node(b, col)
    cb, hb = _brick(b, p)
    ct, ht = _trim(b, p)
    c = b.mix(lm, cb, ct)
    h = b.math("ADD", b.math("MULTIPLY", hb, b.math("SUBTRACT", 1.0, lm)), b.math("MULTIPLY", ht, lm))
    h = b.math("ADD", h, b.math("MULTIPLY", lm, 0.6))  # trim stands slightly proud
    _finish(b, c, 0.85, _bump(b, h, 0.7, 0.015 * scale))
    m["look"] = "brick"
    _MATS[key] = m
    return m


def mat_far_grass(tint=None, scale=1.0, amount=0.35):
    """Distant backdrop hills: grass read as soft colour patches (no scatter)."""
    m, b = _new_mat("kit_far_grass")
    p = _wp(b, scale)
    n1 = b.noise(p, 0.05, 4, 0.6)
    c = b.ramp(n1, [(0.3, srgb("#4f8a2e")), (0.7, srgb("#79ad40"))])
    _finish(b, c, 0.95, None, tint, REF["lawn_far"], amount)
    return m


def mat_dirt(tint=None, scale=1.0, amount=0.35):
    m, b = _new_mat("kit_dirt")
    c, h = _dirt(b, _wp(b, scale))
    _finish(b, c, 0.88, _bump(b, h, 0.6, 0.03 * scale), tint, REF["dirt"], amount)
    return m


# ---- optional CC0 texture sets (asset library). USE_ASSETS switches them in. --------
USE_ASSETS = False
ASSET_LIB = Path.home() / "Projects/personal-games/asset-library"
TEXSETS = {  # name -> (folder, colour, height, ao)
    "rocky_trail": ("polyhaven/ph-rocky_trail_02/content", "rocky_trail_02_diff_2k.jpg", "rocky_trail_02_disp_2k.jpg", "rocky_trail_02_ao_2k.jpg"),
    "red_brick": ("polyhaven/ph-red_brick/content", "red_brick_diff_2k.jpg", "red_brick_disp_2k.jpg", "red_brick_ao_2k.jpg"),
    "rock061": ("ambientcg/acg-Rock061/content", "Rock061_2K-JPG_Color.jpg", "Rock061_2K-JPG_Displacement.jpg", "Rock061_2K-JPG_AmbientOcclusion.jpg"),
    "bark": ("polyhaven/ph-bark_brown_01/content", "bark_brown_01_diff_2k.jpg", "bark_brown_01_disp_2k.jpg", "bark_brown_01_ao_2k.jpg"),
    "leaves024": ("ambientcg/acg-LeafSet024/content", "LeafSet024_2K-JPG_Color.jpg", "LeafSet024_2K-JPG_Opacity.jpg", None),
    "ivy017": ("ambientcg/acg-LeafSet017/content", "LeafSet017_2K-JPG_Color.jpg", "LeafSet017_2K-JPG_Opacity.jpg", None),
    "boulder_dry": ("polyhaven/ph-rock_boulder_dry/content", "rock_boulder_dry_diff_2k.jpg", "rock_boulder_dry_disp_2k.jpg", "rock_boulder_dry_ao_2k.jpg"),
    "stone_wall": ("polyhaven/ph-japanese_stone_wall/content", "japanese_stone_wall_diff_2k.jpg", "japanese_stone_wall_disp_2k.jpg", "japanese_stone_wall_ao_2k.jpg"),
    "old_sandstone": ("polyhaven/ph-old_sandstone_02/content", "old_sandstone_02_diff_2k.jpg", "old_sandstone_02_disp_2k.jpg", "old_sandstone_02_ao_2k.jpg"),
    "asphalt": ("polyhaven/ph-asphalt_02/content", "asphalt_02_diff_2k.jpg", "asphalt_02_disp_2k.jpg", "asphalt_02_ao_2k.jpg"),
    "paving": ("polyhaven/ph-concrete_pavement/content", "concrete_pavement_diff_2k.jpg", "concrete_pavement_disp_2k.jpg", "concrete_pavement_ao_2k.jpg"),
}


def _asset_img(rel, color):
    path = ASSET_LIB / rel
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "sRGB" if color else "Non-Color"
    return img


def _texset(b, name, vec, box=False):
    """World-projected texture set: returns (colour, height, ao) sockets. box=True
    uses box (triplanar-style) projection; otherwise vec.xy is used (top-down)."""
    folder, cf, hf, af = TEXSETS[name]
    out = []
    for f, colr in ((cf, True), (hf, False), (af, False)):
        if f is None:
            out.append(None)
            continue
        tx = b("ShaderNodeTexImage", {"Vector": vec}, image=_asset_img(f"{folder}/{f}", colr))
        if box:
            tx.projection, tx.projection_blend = "BOX", 0.3
        out.append(o(tx, "Color") if colr else o(tx, "Color"))
    return out


def _cartoonify(b, col, sat=1.3, val=1.1, tint=(1.0, 1.0, 1.0)):
    c = o(b("ShaderNodeHueSaturation", {"Color": col, "Saturation": sat, "Value": val}), "Color")
    return b.mix(1.0, c, tint, "MULTIPLY")


def mat_texset(name, scale=1.0, period=4.0, sat=1.0, val=1.0, tint=(1.0, 1.0, 1.0), rough=0.85):
    """A CC0 set laid flat in world space, pulled towards the look with a saturation, value and tint."""
    m, b = _new_mat("kit_" + name)
    col, hgt, ao = _texset(b, name, b.vmath("SCALE", _wp(b, scale), 1.0 / period))
    c = b.mix(1.0, _cartoonify(b, col, sat, val, tint), b.mix(0.5, (1, 1, 1), ao), "MULTIPLY")
    _finish(b, c, rough, _bump(b, o(b("ShaderNodeRGBToBW", {0: hgt})), 0.6, 0.02 * scale))
    return m


def _dirt(b, p):
    """Warm path soil: colour and height (for bump), from world position."""
    trail = None
    if USE_ASSETS:  # real soil relief and cavities; colour stays the clean stylized one
        _, hgt, ao = _texset(b, "rocky_trail", b.vmath("SCALE", p, 1.0 / 2.4))
        trail = (o(b("ShaderNodeRGBToBW", {0: hgt})), ao)
    big = b.noise(p, 0.18, 4, 0.55)
    mid = b.noise(p, 1.2, 4, 0.6)
    fine = b.noise(p, 9.0, 3, 0.6)
    c = b.ramp(big, [(0.25, srgb("#8e6040")), (0.5, srgb("#ad7d55")), (0.75, srgb("#9e6c44"))])
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", mid, 0.35), 0.9, clamp=True), c, srgb("#7a4c2e"))
    # embedded grit: small voronoi pebbles, lighter, slightly raised
    vd = b.voronoi(p, 7.0, "F1")
    vc = b.voronoi(p, 7.0, "F1", out="Color")
    peb = b.math("SUBTRACT", 1.0, b.fac_ramp(vd, 0.12, 0.22))
    peb = b.math("MULTIPLY", peb, b.math("GREATER_THAN", o(b("ShaderNodeSeparateColor", {0: vc})), 0.55))
    c = b.mix(b.math("MULTIPLY", peb, 0.7), c, b.ramp(fine, [(0.3, srgb("#c9a27a")), (0.7, srgb("#9a8670"))]))
    cracks = b.fac_ramp(b.voronoi(p, 1.6, "DISTANCE_TO_EDGE"), 0.0, 0.03)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, cracks), 0.06), c, srgb("#6e3d1c"))
    h = b.math("ADD", b.math("MULTIPLY", mid, 0.6), b.math("MULTIPLY", peb, 0.5))
    h = b.math("ADD", h, b.math("MULTIPLY", fine, 0.25))
    lump = b.noise(p, 0.6, 3, 0.5)
    h = b.math("ADD", h, b.math("MULTIPLY", lump, 1.5))
    if trail:
        h = b.math("ADD", b.math("MULTIPLY", h, 0.5), b.math("MULTIPLY", trail[0], 1.8))
        c = b.mix(1.0, c, b.mix(0.7, (1, 1, 1), trail[1]), "MULTIPLY")
    return c, h


def _tri_uv(b, p, n):
    """2D coords on vertical faces: (x,z) for faces facing Y, (y,z) facing X; (x,y) for tops."""
    x, y, z = b.sep(p)
    nx, ny, nz = b.sep(n)
    fx = b.math("GREATER_THAN", b.math("ABSOLUTE", nx), b.math("ABSOLUTE", ny))
    u = b.math("ADD", b.math("MULTIPLY", x, b.math("SUBTRACT", 1.0, fx)), b.math("MULTIPLY", y, fx))
    top = b.math("GREATER_THAN", b.math("ABSOLUTE", nz), 0.7)
    v = b.math("ADD", b.math("MULTIPLY", z, b.math("SUBTRACT", 1.0, top)), b.math("MULTIPLY", y, top))
    u = b.math("ADD", b.math("MULTIPLY", u, b.math("SUBTRACT", 1.0, top)), b.math("MULTIPLY", x, top))
    return b.comb(u, v, 0.0)


_STRATA = [(0.0, srgb("#dc9c80")), (0.25, srgb("#f3d6bc")), (0.5, srgb("#e2a688")),
           (0.75, srgb("#f8e4cc")), (1.0, srgb("#cf8c70"))]  # pink-cream, like the game's painted strata


def mat_sandstone(tint=None, scale=1.0, amount=0.35, overlay=None, overlay_mean=None, overlay_strength=0.75,
                  drips=True, base_dark=True):
    """Horizontal strata, soft bands, mossy tops and drips (drips use the
    per-vertex 'kit_h' height attribute written by prepare_cliffs())."""
    m, b = _new_mat("kit_sandstone")
    p = _wp(b, scale)
    n = _wnormal(b)
    x, y, z = b.sep(p)
    # natural strata: a few bands of uneven thickness, soft pink-cream banding,
    # occasional recessed ledges with chipped lips, sparse wandering vertical cracks
    warp = b.noise(b.vmath("MULTIPLY", p, (0.6, 0.6, 0.2)), 0.25, 3, 0.5)
    zz = b.math("ADD", z, b.math("MULTIPLY", b.math("SUBTRACT", warp, 0.5), 1.2))
    uneven = b.noise(b.comb(0, 0, b.math("MULTIPLY", zz, 0.35)), 1.0, 2, 0.5)
    L = b.math("ADD", b.math("DIVIDE", zz, 1.0), b.math("MULTIPLY", uneven, 1.6))
    layer = b.math("FLOOR", L)
    fr = b.math("SUBTRACT", L, layer)
    wn = o(b("ShaderNodeTexWhiteNoise", {"Vector": b.comb(layer, 0, 0)}, noise_dimensions="3D"), "Value")
    wn_prev = o(b("ShaderNodeTexWhiteNoise", {"Vector": b.comb(b.math("SUBTRACT", layer, 1.0), 0, 0)}, noise_dimensions="3D"), "Value")
    soft = b.mix(b.fac_ramp(fr, 0.0, 0.35), b.ramp(wn_prev, _STRATA), b.ramp(wn, _STRATA))  # banding blends softly
    mott = b.noise(p, 1.2, 5, 0.62)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", mott, 0.45), 0.6, clamp=True), soft, srgb("#c08466"))
    c = b.mix(b.math("MULTIPLY", b.noise(p, 6.0, 3), 0.15), c, srgb("#f4dcc4"))
    # ledge only at some layer boundaries; its lip is chipped by small voronoi bites
    ledge = b.math("GREATER_THAN", wn, 0.35)
    chip = b.fac_ramp(b.voronoi(p, 2.5, "F1"), 0.15, 0.45)
    lipw = b.math("ADD", 0.16, b.math("MULTIPLY", b.math("SUBTRACT", 1.0, chip), 0.18))
    groove = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.fac_ramp(fr, 0.0, lipw)), ledge)
    # sparse irregular vertical cracks: distorted stretched voronoi edges, masked by low noise
    cp = b.vmath("ADD", b.vmath("MULTIPLY", p, (1.0, 1.0, 0.12)),
                 b.vmath("SCALE", b("ShaderNodeTexNoise", {"Vector": p, "Scale": 0.8}).outputs["Color"], 0.4))
    crack = b.math("SUBTRACT", 1.0, b.fac_ramp(b.voronoi(cp, 0.35, "DISTANCE_TO_EDGE"), 0.0, 0.02))
    crack = b.math("MULTIPLY", crack, b.fac_ramp(b.noise(p, 0.3, 2), 0.55, 0.62))
    h = b.math("ADD", b.math("MULTIPLY", mott, 0.5), b.math("MULTIPLY", b.noise(p, 7.0, 2), 0.12))
    h = b.math("SUBTRACT", h, b.math("MULTIPLY", groove, 1.4))
    h = b.math("SUBTRACT", h, b.math("MULTIPLY", crack, 0.6))
    h = b.math("ADD", h, b.math("MULTIPLY", b.math("SINE", b.math("MULTIPLY", fr, math.pi)), 0.35))
    c = b.mix(b.math("MAXIMUM", b.math("MULTIPLY", b.math("POWER", groove, 1.5), 0.55), b.math("MULTIPLY", crack, 0.6)), c, srgb("#7a4a3a"))
    kh0 = o(b("ShaderNodeAttribute", attribute_name="kit_h", attribute_type="GEOMETRY"), "Fac")
    if base_dark:
        c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.fac_ramp(kh0, 0.0, 0.15)), 0.3), c, srgb("#9a6a52"))
    if overlay is not None:
        # keep the game's own painted strata lines: multiply by texture / its mean
        oc, _ = _game_tex(b, overlay)
        mean = overlay_mean or (0.8, 0.6, 0.5)
        ratio = b.mix(1.0, oc, tuple(1.0 / max(m_, 1e-3) for m_ in mean), "MULTIPLY")
        c = b.mix(overlay_strength, c, b.mix(1.0, c, ratio, "MULTIPLY"))
    # moss on tops + drips down from the top edge
    nx, ny, nz = b.sep(n)
    top = b.fac_ramp(nz, 0.55, 0.8)
    kh = o(b("ShaderNodeAttribute", attribute_name="kit_h", attribute_type="GEOMETRY"), "Fac")
    drip_n = b.noise(b.comb(b.math("MULTIPLY", x, 3.0), b.math("MULTIPLY", y, 3.0), b.math("MULTIPLY", z, 0.25)), 1.5, 2)
    drip = b.math("GREATER_THAN", kh, b.math("SUBTRACT", 1.0, b.math("MULTIPLY", b.math("POWER", drip_n, 3.0), 0.9)))
    moss = b.math("MAXIMUM", top, drip) if drips else top
    mc = b.ramp(b.noise(p, 3.0, 3), [(0.3, srgb("#3f7a22")), (0.7, srgb("#6a9d32"))])
    c = b.mix(moss, c, mc)
    if USE_ASSETS:  # real layered-rock relief and cavity shading on top of the stylized colour
        _, rh, rao = _texset(b, "rock061", b.vmath("SCALE", p, 1.0 / 3.0), box=True)
        h = b.math("ADD", h, b.math("MULTIPLY", o(b("ShaderNodeRGBToBW", {0: rh})), 1.6))
        c = b.mix(1.0, c, b.mix(0.55, (1, 1, 1), rao), "MULTIPLY")
    nrm = _bump(b, h, 0.8, 0.08 * scale)
    _finish(b, c, 0.9, nrm, tint, REF["cliff"], amount)
    return m


def mat_brick(tint=None, scale=1.0, amount=0.35, brick=(0.55, 0.2)):
    """Running-bond brick with per-brick colour/value variation (cell id computed
    here, not from the Brick node), recessed mortar, streaks and base grime."""
    m, b = _new_mat("kit_brick")
    c, h = _brick(b, _wp(b, scale), brick)
    _finish(b, c, 0.85, _bump(b, h, 0.8, 0.015 * scale), tint, REF["brick"], amount)
    return m


def _brick(b, p, brick=(0.55, 0.2)):
    if USE_ASSETS:
        col, hgt, ao = _texset(b, "red_brick", b.vmath("SCALE", p, 1.0 / 4.6), box=True)
        c = _cartoonify(b, col, 1.15, 1.05, (1.02, 0.95, 0.92))
        c = b.mix(1.0, c, b.mix(0.5, (1, 1, 1), ao), "MULTIPLY")
        kh = o(b("ShaderNodeAttribute", attribute_name="kit_h", attribute_type="GEOMETRY"), "Fac")
        base = b.math("SUBTRACT", 1.0, b.fac_ramp(kh, 0.0, 0.18))
        c = b.mix(b.math("MULTIPLY", base, 0.3), c, srgb("#4a3a2a"))
        return c, b.math("MULTIPLY", o(b("ShaderNodeRGBToBW", {0: hgt})), 1.5)
    uv = _tri_uv(b, p, _wnormal(b))
    u, v, _ = b.sep(uv)
    row = b.math("FLOOR", b.math("DIVIDE", v, brick[1]))
    off = b.math("MULTIPLY", b.math("MODULO", row, 2.0), 0.5)
    col = b.math("FLOOR", b.math("ADD", b.math("DIVIDE", u, brick[0]), off))
    cell = b.comb(row, col, 0)
    r1 = o(b("ShaderNodeTexWhiteNoise", {"Vector": cell}, noise_dimensions="3D"), "Value")
    r2 = o(b("ShaderNodeTexWhiteNoise", {"Vector": b.vmath("ADD", cell, (7.3, 1.1, 0))}, noise_dimensions="3D"), "Value")
    c = b.ramp(r1, [(0.0, srgb("#8e3f2e")), (0.35, srgb("#a24b36")), (0.65, srgb("#b05c43")), (0.85, srgb("#9a5240")),
                    (1.0, srgb("#7a3a2c"))])
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", r2, 0.5), 0.5, clamp=True), c, srgb("#c08060"))
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 0.5, r2), 0.6, clamp=True), c, srgb("#5e2e24"))
    br = b("ShaderNodeTexBrick", {"Vector": uv, "Scale": 1.0, "Mortar Size": 0.02, "Mortar Smooth": 0.35,
                                   "Brick Width": brick[0], "Row Height": brick[1]}, offset=0.5, squash=1.0)
    mort = o(br, "Fac")
    n = b.noise(p, 3.0, 4, 0.6)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", n, 0.45), 0.5, clamp=True), c, srgb("#6e3a2c"))
    c = b.mix(mort, c, b.ramp(n, [(0.3, srgb("#9a8f7e")), (0.7, srgb("#b5aa96"))]))
    # rain streaks (stretched vertically) and grime toward the base
    x, y, z = b.sep(p)
    streak = b.fac_ramp(b.noise(b.comb(b.math("MULTIPLY", x, 4.0), b.math("MULTIPLY", y, 4.0), b.math("MULTIPLY", z, 0.3)), 1.0, 3), 0.55, 0.75)
    c = b.mix(b.math("MULTIPLY", streak, 0.3), c, srgb("#4f4038"))
    kh = o(b("ShaderNodeAttribute", attribute_name="kit_h", attribute_type="GEOMETRY"), "Fac")
    base = b.math("SUBTRACT", 1.0, b.fac_ramp(kh, 0.0, 0.18))
    c = b.mix(b.math("MULTIPLY", base, b.math("ADD", 0.25, b.math("MULTIPLY", n, 0.3))), c, srgb("#4a3a2a"))
    c = o(b("ShaderNodeHueSaturation", {"Color": c, "Saturation": 0.85}), "Color")
    h = b.math("ADD", b.math("SUBTRACT", 1.0, mort), b.math("MULTIPLY", n, 0.15))
    h = b.math("ADD", h, b.math("MULTIPLY", r2, 0.12))
    return c, h


def mat_trim_stone(tint=None, scale=1.0, amount=0.35):
    """Pale dressed stone for caps, corners and trims."""
    m, b = _new_mat("kit_trim_stone")
    c, h = _trim(b, _wp(b, scale))
    _finish(b, c, 0.8, _bump(b, h, 0.5, 0.01 * scale), tint, REF["trim"], amount)
    return m


def _trim(b, p):
    if USE_ASSETS:
        col, hgt, ao = _texset(b, "stone_wall", b.vmath("SCALE", p, 1.0 / 2.6), box=True)
        lum = o(b("ShaderNodeRGBToBW", {0: col}))
        c = b.mix(1.0, srgb("#eadcc0"), b.ramp(lum, [(0.1, (0.72, 0.68, 0.6)), (0.5, (1.05, 1.03, 1.0))]), "MULTIPLY")
        c = b.mix(1.0, c, b.mix(0.5, (1, 1, 1), ao), "MULTIPLY")
        return c, b.math("MULTIPLY", o(b("ShaderNodeRGBToBW", {0: hgt})), 1.5)
    uv = _tri_uv(b, p, _wnormal(b))
    br = b("ShaderNodeTexBrick", {"Vector": uv, "Scale": 1.0, "Mortar Size": 0.012, "Mortar Smooth": 0.5,
                                   "Brick Width": 0.7, "Row Height": 0.35,
                                   "Color1": srgb("#e9dfc8"), "Color2": srgb("#d8ccb0"), "Mortar": srgb("#a49a86")})
    c = o(br, "Color")
    n = b.noise(p, 4.0, 4, 0.6)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", n, 0.4), 0.5, clamp=True), c, srgb("#b8aa90"))
    h = b.math("ADD", b.math("SUBTRACT", 1.0, o(br, "Fac")), b.math("MULTIPLY", n, 0.3))
    return c, h


def mat_wood(tint=None, scale=1.0, amount=0.35):
    """Weathered white paint on wood. Grain runs along the per-vertex
    'kit_gdir' axis (object space) written by the prop builders; falls back to X."""
    m, b = _new_mat("kit_wood")
    p = o(b("ShaderNodeTexCoord"), "Object")
    p = b.vmath("SCALE", p, 1.0 / scale)
    gd = o(b("ShaderNodeAttribute", attribute_name="kit_gdir", attribute_type="GEOMETRY"), "Vector")
    ga = b.vmath("ABSOLUTE", gd)
    stretch = b.vmath("SUBTRACT", (1.0, 1.0, 1.0), b.vmath("MULTIPLY", ga, (0.96, 0.96, 0.96)))
    q = b.vmath("MULTIPLY", p, stretch)
    q = b.vmath("ADD", q, b.vmath("SCALE", b("ShaderNodeTexNoise", {"Vector": q, "Scale": 2.0}).outputs["Color"], 0.15))
    grain = b("ShaderNodeTexWave", {"Vector": q, "Scale": 9.0, "Distortion": 6.0, "Detail": 3.0,
                                     "Detail Scale": 2.0}, wave_type="RINGS", rings_direction="SPHERICAL")
    g = o(grain, "Fac")
    lines = b.fac_ramp(g, 0.75, 0.95)
    peel = b.noise(b.vmath("MULTIPLY", p, (3, 3, 3)), 2.0, 5, 0.65)
    bare = b.fac_ramp(b.math("ADD", peel, b.math("MULTIPLY", lines, 0.25)), 0.66, 0.72)
    c = b.mix(b.math("MULTIPLY", lines, 0.35), srgb("#f1eee6"), srgb("#b9b4a8"))
    c = b.mix(bare, c, srgb("#8a7a64"))
    grime = b.noise(p, 1.0, 3)
    c = b.mix(b.math("MULTIPLY", b.fac_ramp(grime, 0.5, 0.8), 0.25), c, srgb("#7d776a"))
    h = b.math("ADD", b.math("MULTIPLY", lines, -0.6), b.math("MULTIPLY", bare, -0.5))
    _finish(b, c, 0.75, _bump(b, h, 0.5, 0.006 * scale), tint, REF["wood"], amount)
    return m


def mat_stone_blocks(tint=None, scale=1.0, amount=0.35, block=0.6):
    m, b = _new_mat("kit_stone_blocks")
    p = _wp(b, scale)
    p2 = b.vmath("MULTIPLY", p, (1.0, 1.0, 1.6))
    ed = b.voronoi(p2, 1.0 / block, "DISTANCE_TO_EDGE")
    cc = b.voronoi(p2, 1.0 / block, "F1", out="Color")
    cv = o(b("ShaderNodeSeparateColor", {0: cc}))
    c = b.ramp(cv, [(0.0, srgb("#7f7d78")), (0.5, srgb("#9d9b95")), (1.0, srgb("#b3afa6"))])
    n = b.noise(p, 5.0, 4, 0.6)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", n, 0.4), 0.6, clamp=True), c, srgb("#6c6a64"))
    bev = b.fac_ramp(ed, 0.0, 0.06)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, bev), 0.5), c, srgb("#5f5d58"))
    nz = b.sep(_wnormal(b))[2]
    moss = b.math("MULTIPLY", b.fac_ramp(nz, 0.6, 0.9), b.fac_ramp(b.noise(p, 1.5, 3), 0.5, 0.65))
    c = b.mix(moss, c, srgb("#55782c"))
    h = b.math("ADD", bev, b.math("MULTIPLY", n, 0.2))
    _finish(b, c, 0.85, _bump(b, h, 0.8, 0.03 * scale), tint, REF["stone"], amount)
    return m


def mat_rock(tint=None, scale=1.0, amount=0.35):
    m, b = _new_mat("kit_rock")
    p = _wp(b, scale)
    rnd = o(b("ShaderNodeObjectInfo"), "Random")
    p = b.vmath("ADD", p, b.comb(rnd, b.math("MULTIPLY", rnd, 7.0), 0.0))
    n1 = b.noise(p, 1.2, 5, 0.6)
    n2 = b.noise(p, 6.0, 3, 0.6)
    c = b.ramp(n1, [(0.3, srgb("#8a8478")), (0.55, srgb("#a8a294")), (0.75, srgb("#9a9183"))])
    c = b.mix(b.math("MULTIPLY", rnd, 0.4), c, srgb("#a08a74"))
    cr = b.fac_ramp(b.voronoi(p, 1.8, "DISTANCE_TO_EDGE"), 0.0, 0.04)
    c = b.mix(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, cr), 0.15), c, srgb("#5a564e"))
    nz = b.sep(_wnormal(b))[2]
    moss = b.math("MULTIPLY", b.fac_ramp(nz, 0.5, 0.85), b.fac_ramp(n2, 0.45, 0.6))
    c = b.mix(b.math("MULTIPLY", moss, 0.8), c, srgb("#5f8a30"))
    h = b.math("ADD", n1, b.math("MULTIPLY", n2, 0.3))
    h = b.math("SUBTRACT", h, b.math("MULTIPLY", b.math("SUBTRACT", 1.0, cr), 0.12))
    _finish(b, c, 0.8, _bump(b, h, 0.6, 0.04 * scale), tint, REF["rock"], amount)
    return m


def mat_water(tint=None, scale=1.0, amount=0.35):
    """Glossy rippled water; sun glints are a stylized emissive sparkle on ripple
    crests (games fake these too), so they show whatever the sun direction."""
    m, b = _new_mat("kit_water")
    p = _wp(b, scale)
    q = b.vmath("MULTIPLY", p, (1.0, 1.0, 0.0))
    r1 = b.noise(q, 1.6, 3, 0.55)
    r2 = b.noise(b.vmath("MULTIPLY", q, (1.0, 2.2, 0.0)), 5.0, 3, 0.55)
    h = b.math("ADD", r1, b.math("MULTIPLY", r2, 0.6))
    c = b.ramp(b.noise(q, 0.4, 2), [(0.3, srgb("#1569a8")), (0.7, srgb("#1f86bf"))])
    lw = o(b("ShaderNodeLayerWeight", {"Blend": 0.3}), "Facing")
    c = b.mix(b.math("MULTIPLY", lw, 0.7), c, srgb("#8fd2ee"))
    sp = b.noise(b.vmath("MULTIPLY", q, (1.0, 1.8, 0.0)), 6.0, 1, 0.5)
    glint = b.fac_ramp(b.math("ADD", sp, b.math("MULTIPLY", r1, 0.3)), 0.9, 0.95)
    _finish(b, c, 0.03, _bump(b, h, 0.6, 0.04 * scale), tint, REF["water"], amount, spec=1.0,
            extra={"Emission Color": (1.0, 0.97, 0.9, 1.0), "Emission Strength": b.math("MULTIPLY", glint, 4.0)})
    return m


def mat_bark(tint=None, scale=1.0, amount=0.35):
    m, b = _new_mat("kit_bark")
    p = o(b("ShaderNodeTexCoord"), "Object")
    p = b.vmath("SCALE", p, 1.0 / scale)
    if USE_ASSETS:
        col, hgt, ao = _texset(b, "bark", b.vmath("SCALE", p, 1.0 / 1.2), box=True)
        c = _cartoonify(b, col, 1.1, 0.9, (1.0, 0.85, 0.7))
        _finish(b, c, 0.85, _bump(b, o(b("ShaderNodeRGBToBW", {0: hgt})), 0.9, 0.03 * scale), tint, REF["bark"], amount)
        return m
    q = b.vmath("MULTIPLY", p, (6.0, 6.0, 0.7))
    n = b.noise(q, 3.0, 5, 0.6, 1.5)
    c = b.ramp(n, [(0.3, srgb("#4e3422")), (0.6, srgb("#7a5538")), (0.8, srgb("#8d6a4c"))])
    _finish(b, c, 0.9, _bump(b, n, 0.8, 0.02 * scale), tint, REF["bark"], amount)
    return m


def mat_foliage(tint=None, scale=1.0, amount=0.35, cards=False):
    """Canopy material. Shading normal comes from the mesh's custom normals
    (clump-spherical), so cards light like soft round blobs. With cards=True,
    alpha-tested by the generated leaf-cluster texture."""
    m, b = _new_mat("kit_foliage_cards" if cards else "kit_foliage")
    p = _wp(b, scale)
    rnd = o(b("ShaderNodeObjectInfo"), "Random")
    n1 = b.noise(p, 0.6, 3)
    base = b.ramp(b.math("ADD", n1, b.math("MULTIPLY", rnd, 0.3)),
                  [(0.3, srgb("#3d8a22")), (0.6, srgb("#58a52e")), (0.85, srgb("#7cbb38"))])
    # darker toward canopy interior: kit_ao written by tree builder (0 inside .. 1 outside)
    ao = o(b("ShaderNodeAttribute", attribute_name="kit_ao", attribute_type="GEOMETRY"), "Fac")
    c = b.mix(b.math("SUBTRACT", 1.0, ao), base, srgb("#1f4a14"))
    alpha = None
    extra = {}
    if cards and USE_ASSETS:
        uvn = o(b("ShaderNodeUVMap"))
        folder, cf, af, _ = TEXSETS["leaves024"]
        tc = b("ShaderNodeTexImage", {"Vector": uvn}, image=_asset_img(f"{folder}/{cf}", True))
        ta = b("ShaderNodeTexImage", {"Vector": uvn}, image=_asset_img(f"{folder}/{af}", False))
        leaf = _cartoonify(b, o(tc, "Color"), 1.25, 1.15)
        c = b.mix(0.55, c, leaf)  # keep the canopy's colour variation and inner shading
        alpha = b.math("GREATER_THAN", o(b("ShaderNodeRGBToBW", {0: o(ta, "Color")})), 0.5)
        m.surface_render_method = "DITHERED"
    elif cards:
        img = _leaf_image()
        tx = b("ShaderNodeTexImage", {"Vector": o(b("ShaderNodeUVMap"))}, image=img)
        shade = o(tx, "Color")
        c = b.mix(0.5, c, shade, "MULTIPLY")
        c = b.mix(1.0, c, (1.6, 1.6, 1.6), "MULTIPLY")
        alpha = b.math("GREATER_THAN", o(tx, "Alpha"), 0.5)
        m.surface_render_method = "DITHERED"
    extra = {"Subsurface Weight": 0.0}
    em = b.mix(1.0, c, (0.12, 0.12, 0.12), "MULTIPLY")
    extra.update({"Emission Color": em, "Emission Strength": 1.0})  # cheap wrap/translucency term
    _finish(b, c, 0.75, None, tint, REF["foliage"], amount, spec=0.3, alpha=alpha, extra=extra)
    return m


def _leaf_image(size=512, seed=3):
    name = "kit_leaf_cluster"
    if name in bpy.data.images:
        return bpy.data.images[name]
    path = out_dir() / "tex" / "leaf_cluster.png"
    if not path.exists():
        rng = np.random.default_rng(seed)
        yy, xx = np.mgrid[0:size, 0:size] / size
        rgba = np.zeros((size, size, 4), np.float32)
        for _ in range(46):
            r = abs(rng.normal(0, 0.2))
            a = rng.uniform(0, 2 * np.pi)
            cx, cy = 0.5 + r * np.cos(a) * 0.9, 0.5 + r * np.sin(a) * 0.9
            ang = a + rng.normal(0, 0.6)
            L, W = rng.uniform(0.16, 0.26), rng.uniform(0.32, 0.45)
            dx, dy = xx - cx, yy - cy
            u = dx * np.cos(ang) + dy * np.sin(ang) + L * 0.15
            v = -dx * np.sin(ang) + dy * np.cos(ang)
            t = np.clip(u / L, 0, 1)
            inside = (u > 0) & (u < L) & (np.abs(v) < W * L * np.sin(np.pi * t) ** 0.8)
            val = rng.uniform(0.6, 1.0) * (0.75 + 0.25 * t) * (1 - 0.25 * (np.abs(v) < 0.006))
            rgba[inside, :3] = val[inside][:, None]
            rgba[inside, 3] = 1.0
        rgba[..., :3] = np.where(rgba[..., 3:] > 0, rgba[..., :3], 0.5)
        path.parent.mkdir(parents=True, exist_ok=True)
        img = bpy.data.images.new(name, size, size, alpha=True)
        img.pixels.foreach_set(rgba[::-1].ravel())
        img.filepath_raw = str(path)
        img.file_format = "PNG"
        img.save()
        return img
    img = bpy.data.images.load(str(path))
    img.name = name
    return img


def _flat(name, hexcol, rough=0.7, rand=0.0):
    """Small solid material for scatter variants (flowers, leaves...)."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m, b = _new_mat(name)
    c = srgb(hexcol)
    if rand:
        rnd = o(b("ShaderNodeObjectInfo"), "Random")
        c = b.mix(b.math("MULTIPLY", rnd, rand), c, (0.25, 0.2, 0.15))
    _finish(b, c, rough)
    return m


def _pebble_mat(scale=1.0):
    name = "kit_pebble"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m, b = _new_mat(name)
    rnd = o(b("ShaderNodeObjectInfo"), "Random")
    c = b.ramp(rnd, [(0.0, srgb("#7a7268")), (0.4, srgb("#a08f78")), (0.7, srgb("#8a6a52")), (1.0, srgb("#b5a690"))])
    n = b.noise(_wp(b, scale), 8.0, 3)
    c = b.mix(b.math("MULTIPLY", n, 0.3), c, srgb("#6e665c"))
    _finish(b, c, 0.6, _bump(b, n, 0.3, 0.01 * scale))
    return m


def _grass_blade_mat(scale=1.0):
    name = "kit_grass_blades"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m, b = _new_mat(name)
    p = _wp(b, scale)
    rnd = o(b("ShaderNodeObjectInfo"), "Random")
    tip = o(b("ShaderNodeAttribute", attribute_name="kit_tip", attribute_type="GEOMETRY"), "Fac")
    patch = b.noise(p, 0.3, 3, 0.55)
    v = b.math("ADD", b.math("MULTIPLY", patch, 0.8), b.math("MULTIPLY", rnd, 0.35))
    tipc = b.ramp(v, [(0.2, srgb("#3f8f22")), (0.45, srgb("#62b02e")), (0.75, srgb("#86c63a")), (0.97, srgb("#b2c94c"))])
    basec = srgb("#1e4410")
    c = b.mix(b.math("POWER", tip, 0.8), basec, tipc)
    # mostly-up shading normal: lawn lights as one soft surface, like game grass
    up = b.vmath("NORMALIZE", b.vmath("ADD", b.vmath("SCALE", _wnormal(b), 0.35), (0, 0, 1)))
    _finish(b, c, 0.7, up, spec=0.35, extra={"Emission Color": b.mix(1.0, c, (0.08, 0.1, 0.04), "MULTIPLY"),
                                             "Emission Strength": 1.0})
    return m


# ---------------------------------------------------------------- mesh utils

def _mesh(name, verts, faces, attrs=None, mats=None, face_mats=None, smooth=True, uvs=None, normals=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    for k, (dom, typ, vals) in (attrs or {}).items():
        a = me.attributes.new(k, typ, dom)
        key = "vector" if typ == "FLOAT_VECTOR" else "value"
        a.data.foreach_set(key, np.asarray(vals, np.float32).ravel())
    for m in mats or []:
        me.materials.append(m)
    if face_mats is not None:
        me.polygons.foreach_set("material_index", np.asarray(face_mats, np.int32))
    if smooth:
        me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    if uvs is not None:
        uv = me.uv_layers.new(name="UVMap")
        uv.data.foreach_set("uv", np.asarray(uvs, np.float32).ravel())
    if normals is not None:
        me.normals_split_custom_set_from_vertices([tuple(n) for n in normals])
    me.validate()
    return me


def _obj(name, me, coll=None):
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def _coll(name, parent=None, hidden=False):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or bpy.context.scene.collection
    if c.name not in par.children:
        par.children.link(c)
    if hidden:
        def find(lc):
            if lc.collection == c:
                return lc
            for ch in lc.children:
                r = find(ch)
                if r:
                    return r
        lc = find(bpy.context.view_layer.layer_collection)
        if lc:
            lc.exclude = True
    return c


def tri_count(ob):
    me = ob.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def _world_tris(ob):
    me = ob.data
    me.calc_loop_triangles()
    nv = len(me.vertices)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(ob.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    nt = len(me.loop_triangles)
    tv = np.empty(nt * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", tv)
    tp = np.empty(nt, np.int32)
    me.loop_triangles.foreach_get("polygon_index", tp)
    return co, tv.reshape(-1, 3), tp


# ---------------------------------------------------------------- roles

def face_roles(ob, roles=None):
    """Per-polygon role strings (None when untagged)."""
    me = ob.data
    slot_role = []
    for slot in ob.material_slots:
        m = slot.material
        r = m.get("look") if m else None
        if r is None and roles and m:
            r = next((v for pat, v in roles.items() if fnmatch.fnmatch(m.name, pat)), None)
        slot_role.append(r or ob.get("look"))
    if not slot_role:
        slot_role = [ob.get("look")]
    mi = np.zeros(len(me.polygons), np.int32)
    me.polygons.foreach_get("material_index", mi)
    mi = np.clip(mi, 0, len(slot_role) - 1)
    return np.array(slot_role, dtype=object)[mi]


def game_color(m):
    if m is None:
        return None
    if "game_color" in m:
        return tuple(m["game_color"])
    if m.use_nodes:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                return tuple(n.inputs["Base Color"].default_value[:3])
    return tuple(m.diffuse_color[:3])


def assign_materials(objects, scale=1.0, roles=None, tint_amount=0.15):
    """Swap each tagged slot's material for the kit material of its role,
    tinted by the slot's original flat colour."""
    for ob in objects:
        if ob.type != "MESH":
            continue
        if not ob.material_slots:
            r = ob.get("look")
            if r in REF or r == "cliff_top":
                ob.data.materials.append(material(r, None, scale))
            continue
        for slot in ob.material_slots:
            m = slot.material
            r = (m.get("look") if m else None)
            if r is None and roles and m:
                r = next((v for pat, v in roles.items() if fnmatch.fnmatch(m.name, pat)), None)
            r = r or ob.get("look")
            if r in REF or r == "cliff_top":
                if r in ("cliff", "brick"):
                    prepare_cliffs([ob])
                slot.link = "OBJECT" if slot.link == "OBJECT" else slot.link
                slot.material = material(r, game_color(m), scale, tint_amount)


def prepare_cliffs(objects):
    """Write 'kit_h' (0 at bottom .. 1 at top of each connected island) for drip moss."""
    for ob in objects:
        me = ob.data
        if "kit_h" in me.attributes:
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        h = np.zeros(len(bm.verts), np.float32)
        seen = set()
        for v0 in bm.verts:
            if v0.index in seen:
                continue
            stack, isl = [v0], []
            seen.add(v0.index)
            while stack:
                v = stack.pop()
                isl.append(v)
                for e in v.link_edges:
                    w = e.other_vert(v)
                    if w.index not in seen:
                        seen.add(w.index)
                        stack.append(w)
            zs = np.array([(ob.matrix_world @ v.co).z for v in isl])
            lo, hi = zs.min(), zs.max()
            for v, z in zip(isl, zs):
                h[v.index] = (z - lo) / max(hi - lo, 1e-6)
        bm.free()
        a = me.attributes.new("kit_h", "FLOAT", "POINT")
        a.data.foreach_set("value", h)


# ---------------------------------------------------------------- sampling

def sample_surface_ex(objects, select, density, seed=0, region=None):
    """Like sample_surface, but also returns per point: UV (from 'UVMap'), the
    object index into `objects` and the polygon index. Dict of arrays."""
    rng = np.random.default_rng(seed)
    out = {k: [] for k in ("P", "N", "UV", "ob", "poly")}
    for oi, ob in enumerate(objects):
        if ob.type != "MESH":
            continue
        mask = select(ob)
        if mask is None or not np.any(mask):
            continue
        me = ob.data
        co, tv, tp = _world_tris(ob)
        nt = len(tp)
        tl = np.empty(nt * 3, np.int32)
        me.loop_triangles.foreach_get("loops", tl)
        tl = tl.reshape(-1, 3)
        uvl = me.uv_layers.get("UVMap")
        if uvl is not None:
            uv = np.empty(len(me.loops) * 2, np.float32)
            uvl.data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2)
        else:
            uv = np.zeros((len(me.loops), 2), np.float32)
        keep = mask[tp]
        tv, tl, tpk = tv[keep], tl[keep], tp[keep]
        a, b_, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
        cr = np.cross(b_ - a, c - a)
        area = np.linalg.norm(cr, axis=1) * 0.5
        nrm = cr / np.maximum(area[:, None] * 2, 1e-9)
        n = rng.poisson(area * density)
        idx = np.repeat(np.arange(len(tv)), n)
        if not len(idx):
            continue
        u, v = rng.random(len(idx)), rng.random(len(idx))
        flip = u + v > 1
        u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
        out["P"].append(a[idx] + (b_[idx] - a[idx]) * u[:, None] + (c[idx] - a[idx]) * v[:, None])
        ua, ub, uc = uv[tl[idx, 0]], uv[tl[idx, 1]], uv[tl[idx, 2]]
        out["UV"].append(ua + (ub - ua) * u[:, None] + (uc - ua) * v[:, None])
        out["N"].append(nrm[idx])
        out["ob"].append(np.full(len(idx), oi))
        out["poly"].append(tpk[idx])
    if not out["P"]:
        return {"P": np.zeros((0, 3)), "N": np.zeros((0, 3)), "UV": np.zeros((0, 2)), "ob": np.zeros(0, int), "poly": np.zeros(0, int)}
    r = {k: np.concatenate(v) for k, v in out.items()}
    if region is not None:
        x0, y0, x1, y1 = region
        k = (r["P"][:, 0] > x0) & (r["P"][:, 0] < x1) & (r["P"][:, 1] > y0) & (r["P"][:, 1] < y1)
        r = {kk: vv[k] for kk, vv in r.items()}
    return r


def image_sampler(image, fn, blur=0):
    """numpy lookup into a Blender image: returns f(uv)->values of fn(rgba array).
    REPEAT wrapping; optional box blur (pixels) to soften painted edges."""
    w, h = image.size
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    a = fn(px.reshape(h, w, 4))
    for _ in range(blur):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
    def f(uv):
        x = (np.floor(np.mod(uv[:, 0], 1.0) * w)).astype(int) % w
        y = (np.floor(np.mod(uv[:, 1], 1.0) * h)).astype(int) % h
        return a[y, x]
    return f


def green_fraction(rgba):
    d = rgba[..., 1] - np.maximum(rgba[..., 0], rgba[..., 2])
    return np.clip((d - 0.04) / 0.08, 0, 1)


def sample_surface(objects, select, density, seed=0, region=None):
    """Area-uniform random points on faces where select(ob, roles_per_poly) is True.
    density: points per world m^2. region: (xmin, ymin, xmax, ymax) world clip.
    Returns points (N,3), normals (N,3)."""
    rng = np.random.default_rng(seed)
    P, Nn = [], []
    for ob in objects:
        if ob.type != "MESH":
            continue
        mask = select(ob)
        if mask is None or not np.any(mask):
            continue
        co, tv, tp = _world_tris(ob)
        keep = mask[tp]
        tv = tv[keep]
        a, b_, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
        cr = np.cross(b_ - a, c - a)
        area = np.linalg.norm(cr, axis=1) * 0.5
        nrm = cr / np.maximum(area[:, None] * 2, 1e-9)
        n = rng.poisson(area * density)
        idx = np.repeat(np.arange(len(tv)), n)
        if not len(idx):
            continue
        u, v = rng.random(len(idx)), rng.random(len(idx))
        flip = u + v > 1
        u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
        pts = a[idx] + (b_[idx] - a[idx]) * u[:, None] + (c[idx] - a[idx]) * v[:, None]
        P.append(pts)
        Nn.append(nrm[idx])
    if not P:
        return np.zeros((0, 3)), np.zeros((0, 3))
    P, Nn = np.concatenate(P), np.concatenate(Nn)
    if region is not None:
        x0, y0, x1, y1 = region
        k = (P[:, 0] > x0) & (P[:, 0] < x1) & (P[:, 1] > y0) & (P[:, 1] < y1)
        P, Nn = P[k], Nn[k]
    return P, Nn


def boundary_segments(objects, select):
    """World-space edges on the border of the selected faces (selection boundary)."""
    segs = []
    for ob in objects:
        if ob.type != "MESH":
            continue
        mask = select(ob)
        if mask is None or not np.any(mask):
            continue
        me = ob.data
        ls = np.empty(len(me.polygons), np.int32)
        lt = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("loop_start", ls)
        me.polygons.foreach_get("loop_total", lt)
        le = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("edge_index", le)
        sel_loops = np.repeat(mask, lt)
        cnt = np.bincount(le[sel_loops], minlength=len(me.edges))
        ev = np.empty(len(me.edges) * 2, np.int32)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)[cnt == 1]
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(ob.matrix_world)
        co = co @ M[:3, :3].T + M[:3, 3]
        segs.append(np.stack([co[ev[:, 0]], co[ev[:, 1]]], 1))
    return np.concatenate(segs) if segs else np.zeros((0, 2, 3))


def dist_to_segments(P, segs, chunk=4096):
    if not len(segs):
        return np.full(len(P), 1e9)
    a, b = segs[:, 0, :2], segs[:, 1, :2]
    ab = b - a
    L2 = np.maximum((ab ** 2).sum(1), 1e-12)
    out = np.empty(len(P))
    for i in range(0, len(P), chunk):
        p = P[i:i + chunk, None, :2]
        t = np.clip(((p - a) * ab).sum(2) / L2, 0, 1)
        d = np.linalg.norm(p - (a + t[..., None] * ab), axis=2)
        out[i:i + chunk] = d.min(1)
    return out


def _noise2(P, freq, seed=0):
    return np.array([mnoise.noise(Vector((x * freq + seed * 17.3, y * freq, 0.0))) for x, y, _ in P])


def _occluded(P, blockers, up=3.0, eps=0.004):
    """True where something from `blockers` lies above the point (within `up`)."""
    if not blockers or not len(P):
        return np.zeros(len(P), bool)
    verts, polys = [], []
    off = 0
    for ob in blockers:
        co, tv, _ = _world_tris(ob)
        verts.append(co)
        polys.append(tv + off)
        off += len(co)
    bvh = BVHTree.FromPolygons(np.concatenate(verts).tolist(), np.concatenate(polys).tolist())
    d = Vector((0, 0, 1))
    return np.array([bvh.ray_cast(Vector((x, y, z + eps)), d, up)[0] is not None for x, y, z in P])


# ---------------------------------------------------------------- instancing

def _instancer(name, P, rot, scl, pick, variants_coll, coll=None):
    """Point mesh + tiny geometry-nodes Instance on Points (real GPU instances)."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(P))
    me.vertices.foreach_set("co", np.asarray(P, np.float32).ravel())
    for k, typ, vals in (("kit_rot", "FLOAT_VECTOR", rot), ("kit_scl", "FLOAT_VECTOR", scl), ("kit_pick", "INT", pick)):
        a = me.attributes.new(k, typ, "POINT")
        a.data.foreach_set("vector" if typ == "FLOAT_VECTOR" else "value",
                           np.asarray(vals, np.int32 if typ == "INT" else np.float32).ravel())
    ob = _obj(name, me, coll)
    ng = bpy.data.node_groups.new(name + "_gn", "GeometryNodesTree") if False else bpy.data.node_groups.new(name + "_gn", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ng.is_modifier = True
    b = _B(ng)
    gi = b("NodeGroupInput")
    go = b("NodeGroupOutput")
    ci = b("GeometryNodeCollectionInfo", {"Separate Children": True, "Reset Children": True})
    ci.inputs["Collection"].default_value = variants_coll
    ar = o(b("GeometryNodeInputNamedAttribute", {"Name": "kit_rot"}, data_type="FLOAT_VECTOR"), "Attribute")
    asc = o(b("GeometryNodeInputNamedAttribute", {"Name": "kit_scl"}, data_type="FLOAT_VECTOR"), "Attribute")
    ap = o(b("GeometryNodeInputNamedAttribute", {"Name": "kit_pick"}, data_type="INT"), "Attribute")
    rot_s = o(b("FunctionNodeEulerToRotation", {0: ar}))
    iop = b("GeometryNodeInstanceOnPoints", {"Points": o(gi), "Instance": o(ci), "Pick Instance": True,
                                              "Instance Index": ap, "Rotation": rot_s, "Scale": asc})
    ng.links.new(o(iop), go.inputs[0])
    md = ob.modifiers.new("kit_instances", "NODES")
    md.node_group = ng
    tris = [tri_count(v) for v in sorted(variants_coll.objects, key=lambda x: x.name)]
    ntri = int(sum(tris[i] for i in np.asarray(pick)))
    ob["kit_instances"] = len(P)
    ob["kit_tris"] = ntri
    return ob


def _variants(name, builders):
    """Hidden collection of variant meshes, ordered by name (= pick index)."""
    c = bpy.data.collections.get(name)
    if c:
        return c
    root = _coll("kit_assets", hidden=True)
    c = _coll(name, parent=root)
    for i, (me) in enumerate(builders):
        ob = bpy.data.objects.new(f"{name}_{i:02d}", me)
        c.objects.link(ob)
    return c


# ---- variant meshes (unit size; instance scale sets real size) ------------

def _tuft_mesh(name, rng, mat, blades=11, radius=0.32, width=0.085):
    V, F, T = [], [], []
    for _ in range(blades):
        a = rng.uniform(0, 2 * np.pi)
        r = radius * np.sqrt(rng.random())
        bx, by = r * np.cos(a), r * np.sin(a)
        h = rng.uniform(0.5, 1.0)
        ld = a + rng.normal(0, 0.7)
        lean = rng.uniform(0.15, 0.55)
        fa = ld + np.pi / 2 + rng.normal(0, 0.3)
        wx, wy = np.cos(fa), np.sin(fa)
        segs = 3
        base = len(V)
        for i in range(segs + 1):
            t = i / segs
            cx = bx + np.cos(ld) * lean * h * t * t
            cy = by + np.sin(ld) * lean * h * t * t
            cz = h * t * (1 - 0.25 * lean * t)
            w = width * (1 - t ** 1.5) * 0.5
            if i < segs:
                V += [(cx - wx * w, cy - wy * w, cz), (cx + wx * w, cy + wy * w, cz)]
                T += [t, t]
            else:
                V.append((cx, cy, cz))
                T.append(1.0)
        for i in range(segs - 1):
            k = base + 2 * i
            F.append((k, k + 1, k + 3, k + 2))
        k = base + 2 * (segs - 1)
        F.append((k, k + 1, k + 2))
    return _mesh(name, V, F, {"kit_tip": ("POINT", "FLOAT", T)}, [mat])


def _leafshape(V, F, origin, d, side, L, W, lift=0.25, start=None):
    """Simple 4-vert leaf (diamond) from origin along direction d, width along side."""
    o_ = np.asarray(origin, float)
    d = np.asarray(d, float) / np.linalg.norm(d)
    s = np.asarray(side, float) / np.linalg.norm(side)
    up = np.cross(s, d)
    k = len(V)
    V += [tuple(o_), tuple(o_ + d * L * 0.45 + s * W * 0.5 + up * lift * L * 0.2),
          tuple(o_ + d * L), tuple(o_ + d * L * 0.45 - s * W * 0.5 + up * lift * L * 0.2)]
    F.append((k, k + 1, k + 2, k + 3))


def _flower_mesh(name, rng, petal_mat, stem_mat, center_mat):
    V, F, FM = [], [], []
    h = rng.uniform(0.6, 1.0)
    # stem: thin crossed ribbon
    w = 0.012
    for ax in ((1, 0), (0, 1)):
        k = len(V)
        V += [(-w * ax[0], -w * ax[1], 0), (w * ax[0], w * ax[1], 0), (w * ax[0], w * ax[1], h), (-w * ax[0], -w * ax[1], h)]
        F.append((k, k + 1, k + 2, k + 3)); FM.append(1)
    # a couple of leaves
    for j in range(2):
        a = rng.uniform(0, 2 * np.pi)
        d = (np.cos(a), np.sin(a), 0.6)
        _leafshape(V, F, (0, 0, h * 0.25), d, (-np.sin(a), np.cos(a), 0), 0.22, 0.09); FM.append(1)
    # head: 5 petals around a center, tilted
    n = 5
    r = rng.uniform(0.17, 0.22)
    for i in range(n):
        a = i / n * 2 * np.pi + rng.uniform(-0.2, 0.2)
        d = (np.cos(a), np.sin(a), 0.25)
        _leafshape(V, F, (0, 0, h), d, (-np.sin(a), np.cos(a), 0), r, r * 0.9, lift=0.0); FM.append(0)
    k = len(V)
    c = r * 0.32
    V += [(c * np.cos(a), c * np.sin(a), h + 0.012) for a in np.linspace(0, 2 * np.pi, 6, endpoint=False)]
    F.append(tuple(range(k, k + 6))); FM.append(2)
    return _mesh(name, V, F, None, [petal_mat, stem_mat, center_mat], FM)


def _weed_mesh(name, rng, mat):
    V, F = [], []
    n = rng.integers(5, 8)
    for i in range(n):
        a = i / n * 2 * np.pi + rng.uniform(-0.3, 0.3)
        el = rng.uniform(0.35, 0.9)
        d = (np.cos(a) * np.cos(el), np.sin(a) * np.cos(el), np.sin(el))
        _leafshape(V, F, (0, 0, 0.01), d, (-np.sin(a), np.cos(a), 0), rng.uniform(0.7, 1.0), rng.uniform(0.45, 0.6), lift=0.5)
    return _mesh(name, V, F, None, [mat])


def _rock_mesh(name, rng, mat, subdiv=1, squash=0.6, rough=0.25):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=0.5)
    off = Vector(rng.uniform(-50, 50, 3))
    for v in bm.verts:
        n = mnoise.noise(v.co * 2.2 + off)
        v.co *= 1 + rough * n
        v.co.z *= squash
        v.co.x *= rng.uniform(0.9, 1.25) if False else 1.0
    bm.verts.ensure_lookup_table()
    sx, sy = rng.uniform(0.8, 1.3), rng.uniform(0.7, 1.1)
    for v in bm.verts:
        v.co.x *= sx; v.co.y *= sy
        if v.co.z < -0.1:
            v.co.z = -0.1 + (v.co.z + 0.1) * 0.3
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    return me


def _fallen_leaf_mesh(name, rng, mat):
    V, F = [], []
    L, W = 1.0, rng.uniform(0.5, 0.7)
    # gently curled leaf: 3 segments along length
    for i in range(4):
        t = i / 3
        w = W * 0.5 * np.sin(np.pi * min(max(t, 0.05), 0.95)) if 0 < i < 3 else 0.0
        z = 0.08 * np.sin(np.pi * t)
        if 0 < i < 3:
            V += [(t * L, -w, z + 0.06), (t * L, w, z + 0.06), (t * L, 0, z)]
        else:
            V.append((t * L, 0, z))
    # indices: 0 tip0; 1,2,3 ring1 (l,r,c); 4,5,6 ring2; 7 tip1
    F = [(0, 1, 3), (0, 3, 2), (1, 4, 6, 3), (3, 6, 5, 2), (4, 7, 6), (6, 7, 5)]
    V = [(x - 0.5, y, z) for x, y, z in V]
    return _mesh(name, V, F, None, [mat])


def _vine_mesh(name, rng, mat, length):
    """Hanging strand: leaves along a wavy line from z=0 down to -length, facing +Y.
    With USE_ASSETS each leaf is a textured ivy card (LeafSet017 atlas, 2x3 cells)."""
    if USE_ASSETS:
        return _ivy_mesh(name, rng, length)
    V, F = [], []
    n = max(4, int(length / 0.07))
    ph = rng.uniform(0, 6)
    for i in range(n):
        t = i / (n - 1)
        z = -length * t
        x = 0.05 * np.sin(t * 9 + ph) * (0.3 + t)
        y = 0.015 + 0.03 * t
        side = 1 if i % 2 else -1
        a = side * rng.uniform(0.6, 1.2)
        d = (np.sin(a) * 0.8, 0.35, -np.cos(a) * 0.6)
        sz = rng.uniform(0.07, 0.11) * (1.0 - 0.35 * t)
        _leafshape(V, F, (x, y, z), d, (np.cos(a), 0, np.sin(a)), sz, sz * 0.75, lift=0.4)
    # stem ribbon
    k0 = len(V)
    for i in range(n):
        t = i / (n - 1)
        x = 0.05 * np.sin(t * 9 + ph) * (0.3 + t)
        V += [(x - 0.006, 0.012 + 0.03 * t, -length * t), (x + 0.006, 0.012 + 0.03 * t, -length * t)]
    for i in range(n - 1):
        k = k0 + 2 * i
        F.append((k, k + 1, k + 3, k + 2))
    return _mesh(name, V, F, None, [mat])


def _ivy_mat():
    name = "kit_ivy"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m, b = _new_mat(name)
    uvn = o(b("ShaderNodeUVMap"))
    folder, cf, af, _ = TEXSETS["ivy017"]
    tc = b("ShaderNodeTexImage", {"Vector": uvn}, image=_asset_img(f"{folder}/{cf}", True))
    ta = b("ShaderNodeTexImage", {"Vector": uvn}, image=_asset_img(f"{folder}/{af}", False))
    rnd = o(b("ShaderNodeObjectInfo"), "Random")
    c = _cartoonify(b, o(tc, "Color"), 1.35, 1.1)
    c = b.mix(b.math("MULTIPLY", rnd, 0.35), c, srgb("#3f8f2a"))
    alpha = b.math("GREATER_THAN", o(b("ShaderNodeRGBToBW", {0: o(ta, "Color")})), 0.5)
    m.surface_render_method = "DITHERED"
    em = b.mix(1.0, c, (0.1, 0.12, 0.06), "MULTIPLY")
    _finish(b, c, 0.6, None, spec=0.35, alpha=alpha, extra={"Emission Color": em, "Emission Strength": 1.0})
    return m


def _ivy_mesh(name, rng, length):
    V, F, UV = [], [], []
    n = max(4, int(length / 0.06))
    ph = rng.uniform(0, 6)
    for i in range(n):
        t = i / (n - 1)
        x = 0.05 * np.sin(t * 9 + ph) * (0.3 + t)
        base = np.array([x, 0.02 + 0.04 * t, -length * t])
        a = (1 if i % 2 else -1) * rng.uniform(0.5, 1.3)
        d = np.array([np.sin(a) * 0.7, 0.45, -np.cos(a) * 0.55 + 0.3])
        d /= np.linalg.norm(d)
        side = np.cross(d, [0, 1, 0.2])
        side /= np.linalg.norm(side)
        sz = rng.uniform(0.09, 0.14) * (1.0 - 0.3 * t)
        k = len(V)
        V += [tuple(base - side * sz * 0.5), tuple(base + side * sz * 0.5), tuple(base + side * sz * 0.5 + d * sz),
              tuple(base - side * sz * 0.5 + d * sz)]
        F.append((k, k + 1, k + 2, k + 3))
        cu, cv = rng.integers(0, 2) * 0.5, rng.integers(0, 3) / 3
        UV += [(cu, cv), (cu + 0.5, cv), (cu + 0.5, cv + 1 / 3), (cu, cv + 1 / 3)]
    return _mesh(name, V, F, None, [_ivy_mat()], uvs=UV)


def mat_boulder_dry(scale=1.0, tint="#c9a07c"):
    """Rubble/boulders: Rock Boulder Dry (tinted warm, softened) when assets are on."""
    name = "kit_boulder_dry"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    if not USE_ASSETS:
        return material("rock", None, scale)
    m, b = _new_mat(name)
    p = _wp(b, scale)
    col, hgt, ao = _texset(b, "boulder_dry", b.vmath("SCALE", p, 1.0 / 1.4), box=True)
    c = _cartoonify(b, col, 1.2, 1.05, srgb(tint))
    c = b.mix(1.0, c, (1.25, 1.2, 1.15), "MULTIPLY")
    nz = b.sep(_wnormal(b))[2]
    moss = b.math("MULTIPLY", b.fac_ramp(nz, 0.55, 0.85), b.fac_ramp(b.noise(p, 2.0, 3), 0.45, 0.6))
    c = b.mix(b.math("MULTIPLY", moss, 0.8), c, srgb("#5f8a30"))
    c = b.mix(1.0, c, b.mix(0.5, (1, 1, 1), ao), "MULTIPLY")
    _finish(b, c, 0.8, _bump(b, o(b("ShaderNodeRGBToBW", {0: hgt})), 0.7, 0.05 * scale))
    return m


# ---------------------------------------------------------------- water: see-through with a bed
def mat_water_clear(scale=1.0):
    """Alpha-blended water: clear and teal where you look down, reflective at grazing
    angles; ripples, glints. The tint of what's below comes from the bed material."""
    m, b = _new_mat("kit_water_clear")
    p = _wp(b, scale)
    q = b.vmath("MULTIPLY", p, (1.0, 1.0, 0.0))
    r1 = b.noise(q, 1.6, 3, 0.55)
    r2 = b.noise(b.vmath("MULTIPLY", q, (1.0, 2.2, 0.0)), 5.0, 3, 0.55)
    h = b.math("ADD", r1, b.math("MULTIPLY", r2, 0.6))
    fres = o(b("ShaderNodeLayerWeight", {"Blend": 0.25}), "Facing")
    c = b.mix(fres, srgb("#2aa6c8"), srgb("#bfe8f6"))
    alpha = b.math("ADD", 0.28, b.math("MULTIPLY", fres, 0.62))
    sp = b.noise(b.vmath("MULTIPLY", q, (1.0, 1.8, 0.0)), 6.0, 1, 0.5)
    glint = b.fac_ramp(b.math("ADD", sp, b.math("MULTIPLY", r1, 0.3)), 0.88, 0.94)
    alpha = b.math("MAXIMUM", alpha, glint)
    _finish(b, c, 0.03, _bump(b, h, 0.5, 0.04 * scale), spec=1.0, alpha=alpha,
            extra={"Emission Color": (1.0, 0.97, 0.9, 1.0), "Emission Strength": b.math("MULTIPLY", glint, 5.0)})
    m.surface_render_method = "BLENDED"
    m.use_backface_culling = False
    return m


def mat_water_bed(water_z, depth, scale=1.0):
    """Pond bed and walls: sand and pebbles, fading to deep teal with depth below the
    surface (the same depth-fog a game applies under water), plus soft caustic lines."""
    m, b = _new_mat("kit_water_bed")
    p = _wp(b, scale)
    c, h = _dirt(b, p)
    c = b.mix(1.0, c, (0.85, 0.9, 0.8), "MULTIPLY")
    z = b.sep(o(b("ShaderNodeNewGeometry"), "Position"))[2]
    d = b.fac_ramp(b.math("SUBTRACT", water_z, z), 0.0, depth)
    caus = b.math("SUBTRACT", 1.0, b.fac_ramp(b.voronoi(b.vmath("MULTIPLY", p, (1, 1, 0)), 2.2, "DISTANCE_TO_EDGE"), 0.0, 0.06))
    c = b.mix(b.math("MULTIPLY", caus, 0.35), c, (1.0, 1.0, 0.9))
    c = b.mix(b.math("ADD", 0.5, b.math("MULTIPLY", d, 0.45)), c, srgb("#0b4f6c"))
    _finish(b, c, 0.9, _bump(b, h, 0.4, 0.03 * scale))
    return m


def water_dress(objects, select, scale=1.0, *, depth=0.7, foam=0.35, walls=True, region=None, coll=None, name="kit_water"):
    """Under each selected (horizontal) water face: a tub (walls + bed) `depth` deep, so
    see-through water has something to show; plus a soft foam ribbon inside the shore."""
    bm = bmesh.new()
    fbm = bmesh.new()
    fuv = fbm.loops.layers.uv.new("UVMap")
    zs = []
    for ob in objects:
        mask = select(ob)
        if mask is None or not mask.any():
            continue
        M = ob.matrix_world
        me = ob.data
        tmp = bmesh.new()
        tmp.from_mesh(me)
        tmp.transform(M)
        tmp.faces.ensure_lookup_table()
        keep = [f for f in tmp.faces if mask[f.index] and f.normal.z > 0.8 and
                (region is None or region[0] < f.calc_center_median().x < region[2] and region[1] < f.calc_center_median().y < region[3])]
        if not keep:
            tmp.free()
            continue
        kset = set(keep)
        vmap = {}
        for f in keep:
            vs = []
            for v in f.verts:
                if v not in vmap:
                    vmap[v] = (bm.verts.new(v.co), bm.verts.new(v.co - Vector((0, 0, depth * scale))))
                vs.append(vmap[v])
            try:
                bm.faces.new([b_ for _, b_ in vs])  # bed
            except ValueError:
                pass
            zs.append(f.calc_center_median().z)
        for f in keep:
            cen = f.calc_center_median()
            for e in f.edges:
                if sum(1 for g in e.link_faces if g in kset) != 1:
                    continue
                a, c = e.verts
                ta, ba = vmap[a]
                tc, bc = vmap[c]
                try:
                    if walls:
                        bm.faces.new([ta, tc, bc, ba])
                except ValueError:
                    pass
                # foam ribbon, from the shore inward
                mid = (a.co + c.co) / 2
                inward = Vector((cen.x - mid.x, cen.y - mid.y, 0))
                if inward.length < 1e-6 or not foam:
                    continue
                inward.normalize()
                up = Vector((0, 0, 0.01 * scale))
                q = [fbm.verts.new(a.co + up), fbm.verts.new(c.co + up),
                     fbm.verts.new(c.co + up + inward * foam * scale), fbm.verts.new(a.co + up + inward * foam * scale)]
                ff = fbm.faces.new(q)
                for lp, uvv in zip(ff.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                    lp[fuv].uv = uvv
        tmp.free()
    if not bm.faces:
        bm.free(); fbm.free()
        return None, None
    wz = float(np.median(zs))
    me = bpy.data.meshes.new(name + "_bed")
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat_water_bed(wz, depth * scale, scale))
    bed = _obj(name + "_bed", me, coll)
    fm = bpy.data.meshes.new(name + "_foam")
    fbm.to_mesh(fm)
    fbm.free()
    m, b = _new_mat("kit_foam")
    v = b.sep(o(b("ShaderNodeUVMap")))[1]
    n = b.noise(_wp(b, scale), 3.0, 3)
    a_ = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.fac_ramp(v, 0.0, 1.0)), b.fac_ramp(n, 0.3, 0.6))
    _finish(b, (0.95, 0.98, 1.0), 0.5, alpha=b.math("MULTIPLY", a_, 0.75))
    m.surface_render_method = "BLENDED"
    fm.materials.append(m)
    foam_ob = _obj(name + "_foam", fm, coll)
    return bed, foam_ob


# ---------------------------------------------------------------- cliff masses
def cliff_masses(cliff_objs, top_objs, ground_objs, scale=1.0, *, top_min_z=-1e9, cell=0.25, pad=1.5,
                 dilate=0.3, voxel=0.16, band=(0.8, 1.7), ledge=0.45, erosion=0.16, top_break=0.22,
                 seed=0, mat=None, rubble_mat=None, coll=None, name="kit_cliff_mass"):
    """Real rock masses built from the game's cliff volumes (2.5D): a grid is ray-cast
    from above; cells whose first hit is a cliff face or a high cliff-top face (z >
    top_min_z) are rock, at that height. The rock columns are fused by voxel remesh,
    then carved: thick uneven strata bands with overhanging ledges, vertical erosion
    grooves, a broken top rim. Tops stay just under the game's walkable cliff tops;
    walls grow by `dilate` past the game's faces. Returns (rock, rubble, rim_edges)."""
    rng = np.random.default_rng(seed)

    def bvh_of(objs, sel=None):
        verts, polys, off = [], [], 0
        for o_ in objs:
            co, tv, tp = _world_tris(o_)
            if sel is not None:
                tv = tv[sel(o_)[tp]]
            verts.append(co); polys.append(tv + off); off += len(co)
        if not verts or off == 0:
            return None
        return BVHTree.FromPolygons(np.concatenate(verts).tolist(), np.concatenate(polys).tolist())
    lo = np.full(3, 1e9); hi = np.full(3, -1e9)
    for o_ in cliff_objs:
        co, _, _ = _world_tris(o_)
        lo = np.minimum(lo, co.min(0)); hi = np.maximum(hi, co.max(0))
    if lo[0] > hi[0]:
        return None, None, [], None
    C = bvh_of(cliff_objs + top_objs)
    G = bvh_of(ground_objs)
    c_ = cell * scale
    xs = np.arange(lo[0] - pad * scale, hi[0] + pad * scale, c_)
    ys = np.arange(lo[1] - pad * scale, hi[1] + pad * scale, c_)
    nx, ny = len(xs), len(ys)
    H = np.full((nx, ny), np.nan)
    Gz = np.full((nx, ny), np.nan)
    down = Vector((0, 0, -1))
    ztop = hi[2] + 5
    top_ids = set()
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            o0 = Vector((x, y, ztop))
            hc = C.ray_cast(o0, down, 200)
            hg = G.ray_cast(o0, down, 200) if G else (None,)
            if hg[0] is not None:
                Gz[i, j] = hg[0].z
            if hc[0] is not None and (hg[0] is None or hc[0].z >= hg[0].z - 0.02) and hc[0].z > top_min_z:
                H[i, j] = hc[0].z
    inside = ~np.isnan(H)
    if not inside.any():
        return None, None, [], None
    gfill = np.where(np.isnan(Gz), np.nanmin(Gz) if not np.all(np.isnan(Gz)) else lo[2], Gz)
    base = float(np.nanmin(gfill)) - 0.3 * scale
    # dilate: neighbour cells inherit a height a little below the cliff edge
    k = max(1, int(round(dilate / cell)))
    Hd = H.copy()
    for _ in range(k):
        nb = np.full_like(Hd, np.nan)
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(np.roll(Hd, di, 0), dj, 1)
            nb = np.fmax(nb, sh)
        grow = np.isnan(Hd) & ~np.isnan(nb)
        Hd[grow] = nb[grow] - 0.04 * scale
    ins = ~np.isnan(Hd)
    # columns -> one mesh -> voxel remesh
    bm = bmesh.new()
    for i, j in zip(*np.nonzero(ins)):
        h = Hd[i, j]
        res = bmesh.ops.create_cube(bm, size=1.0)
        for v in res["verts"]:
            v.co = Vector((xs[i] + v.co.x * c_ * 1.02, ys[j] + v.co.y * c_ * 1.02,
                           base + (v.co.z + 0.5) * (h - base)))
    me = bpy.data.meshes.new(name + "_cols")
    bm.to_mesh(me)
    bm.free()
    tmp = _obj(name + "_tmp", me, coll)
    md = tmp.modifiers.new("remesh", "REMESH")
    md.mode, md.voxel_size = "VOXEL", voxel * scale
    sm = tmp.modifiers.new("smooth", "SMOOTH")
    sm.factor, sm.iterations = 0.5, 2
    dg = bpy.context.evaluated_depsgraph_get()
    rm = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(me)
    # carve
    n_ = len(rm.vertices)
    co = np.empty(n_ * 3, np.float32); rm.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    nr = np.empty(n_ * 3, np.float32); rm.vertices.foreach_get("normal", nr); nr = nr.reshape(-1, 3)

    def Hat(x, y):
        i = np.clip(((x - xs[0]) / c_).round().astype(int), 0, nx - 1)
        j = np.clip(((y - ys[0]) / c_).round().astype(int), 0, ny - 1)
        return Hd[i, j]
    hz = Hat(co[:, 0], co[:, 1])
    hz = np.where(np.isnan(hz), co[:, 2], hz)
    off3 = rng.uniform(-50, 50, 3)
    nzv = np.array([mnoise.noise(Vector((x * 0.3 / scale, y * 0.3 / scale, 0)) + Vector(off3)) for x, y, _ in co])
    # Bedding planes dip across the level, so the bands never read as stacked discs.
    dip = (co[:, 0] * 0.13 + co[:, 1] * 0.07) / scale
    L = (co[:, 2] - base + dip * scale) / (np.mean(band) * scale) + nzv * 0.45
    idx = np.floor(L)
    f = L - idx
    bd = np.array([((int(ii) * 7919 + seed * 31) % 97) / 97.0 for ii in idx])
    prof = ledge * scale * (bd - 0.35) + 0.14 * scale * (f - 0.5)                # each band stands at its own depth
    prof -= 0.1 * scale * (f < 0.07)                                             # dark seam under it
    w = np.clip(1.0 - np.abs(nr[:, 2]) * 1.4, 0, 1)
    nh = nr[:, :2] / np.maximum(np.linalg.norm(nr[:, :2], axis=1, keepdims=True), 1e-6)
    moved = co.copy()
    moved[:, :2] += nh * (prof * w)[:, None]
    # Each band breaks into blocks, wider than tall; every block is cut to one flat plane, which makes the hard edges.
    seeds = moved[np.unique(np.floor(moved / (np.array((1.5, 1.5, 0.9)) * scale)).astype(int), axis=0, return_index=True)[1]]
    tree = kdtree.KDTree(len(seeds))
    for i_, q in enumerate(seeds):
        tree.insert((q[0], q[1], q[2] * 1.7), i_)
    tree.balance()
    near = np.array([tree.find((x, y, z * 1.7))[1] for x, y, z in moved])
    _, block = np.unique(np.stack([near, idx.astype(np.int64)], 1), axis=0, return_inverse=True)
    block = block.ravel()
    count = np.bincount(block)
    centre = np.stack([np.bincount(block, moved[:, a_]) for a_ in range(3)], 1) / count[:, None]
    plane = np.stack([np.bincount(block, nr[:, a_]) for a_ in range(3)], 1) / count[:, None]
    plane += rng.normal(0, 0.2, plane.shape) * (1, 1, 0.6)
    plane /= np.maximum(np.linalg.norm(plane, axis=1, keepdims=True), 1e-6)
    jut = rng.uniform(-0.05, 0.16, len(count)) * scale
    along = ((moved - centre[block]) * plane[block]).sum(1)
    cut = moved + plane[block] * (jut[block] - along)[:, None]
    co = co + (cut - co) * w[:, None]
    # Never behind the game's wall: its face stays inside the rock.
    out = (co[:, :2] - moved[:, :2] + nh * (prof * w)[:, None]) * nh
    short = np.minimum(out.sum(1) + dilate * 0.75 * scale, 0)
    co[:, :2] -= nh * short[:, None]
    # tops: just under the walkable cliff top; the rim gets a broken outline
    top = nr[:, 2] > 0.5
    rim = (w > 0.25) & (co[:, 2] > hz - 0.35 * scale)
    co[top, 2] = np.minimum(co[top, 2], hz[top] - 0.03 * scale)
    bump = np.array([max(0.0, mnoise.noise(Vector((x * 0.9 / scale, y * 0.9 / scale, 3.0)))) for x, y, _ in co[rim]])
    co[rim, 2] = np.minimum(co[rim, 2] + bump * top_break * scale, hz[rim] - 0.03 * scale)
    rm.vertices.foreach_set("co", co.ravel())
    rm.update()
    rm.materials.clear()
    rm.materials.append(mat or mat_sandstone(None, scale, drips=False, base_dark=False))
    # Flat faces merged: crisp edges, and far fewer triangles than the voxel grid.
    tmp = _obj(name + "_tmp", rm, coll)
    dc = tmp.modifiers.new("flat", "DECIMATE")
    dc.decimate_type, dc.angle_limit = "DISSOLVE", math.radians(5)
    flat_me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(rm)
    rm = flat_me
    rm.name = name
    rm.polygons.foreach_set("use_smooth", np.zeros(len(rm.polygons), bool))
    rock = _obj(name, rm, coll)
    # rim edges for vines/overgrowth: boundary cells of the (undilated) cliff, outward normals
    edges = []
    for i, j in zip(*np.nonzero(inside)):
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ii, jj = i + di, j + dj
            if 0 <= ii < nx and 0 <= jj < ny and not inside[ii, jj] and H[i, j] - gfill[ii, jj] > 1.0 * scale:
                out = Vector((di, dj, 0))
                c0 = Vector((xs[i], ys[j], H[i, j])) + out * (c_ * 0.5 + dilate * scale + ledge * scale * 0.6)
                t = Vector((-dj, di, 0)) * c_ * 0.5
                edges.append((c0 - t, c0 + t, out))
    # rubble along the base
    rb = bmesh.new()
    nrub = 0
    for i, j in zip(*np.nonzero(inside)):
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ii, jj = i + di, j + dj
            if not (0 <= ii < nx and 0 <= jj < ny) or inside[ii, jj] or H[i, j] - gfill[ii, jj] < 1.0 * scale:
                continue
            if rng.random() > 0.18:
                continue
            r = rng.uniform(0.15, 0.5) * scale
            res = bmesh.ops.create_icosphere(rb, subdivisions=2, radius=r)
            oo = Vector(rng.uniform(-40, 40, 3))
            cpos = Vector((xs[i] + di * (c_ + dilate * scale + rng.uniform(0, 0.5) * scale),
                           ys[j] + dj * (c_ + dilate * scale + rng.uniform(0, 0.5) * scale), gfill[ii, jj] + r * 0.35))
            for v in res["verts"]:
                v.co = Vector((v.co.x * rng.uniform(1, 1.4), v.co.y, v.co.z * 0.7)) * (1 + 0.32 * mnoise.noise(v.co * 2.2 / max(r, 1e-3) + oo))
                v.co = cpos + v.co
            nrub += 1
    rubble = None
    if nrub:
        rmesh = bpy.data.meshes.new(name + "_rubble")
        rb.to_mesh(rmesh)
        rmesh.materials.append(rubble_mat or mat_rock(scale=scale))
        rmesh.polygons.foreach_set("use_smooth", np.zeros(len(rmesh.polygons), bool))
        rubble = _obj(name + "_rubble", rmesh, coll)
        rubble["kit_count"] = nrub
    rb.free()
    rock["kit_cells"] = int(inside.sum())

    def covered(P):
        i = np.clip(((P[:, 0] - xs[0]) / c_).round().astype(int), 0, nx - 1)
        j = np.clip(((P[:, 1] - ys[0]) / c_).round().astype(int), 0, ny - 1)
        inb = (P[:, 0] >= xs[0] - c_) & (P[:, 0] <= xs[-1] + c_) & (P[:, 1] >= ys[0] - c_) & (P[:, 1] <= ys[-1] + c_)
        return inb & ins[i, j]
    return rock, rubble, edges, covered


# ---------------------------------------------------------------- scatter API

def _sel_roles(roles_wanted, roles=None, top_only=False):
    def f(ob):
        r = face_roles(ob, roles)
        m = np.isin(r.astype(str), list(roles_wanted))
        if top_only and np.any(m):
            me = ob.data
            nz = np.empty(len(me.polygons) * 3, np.float32)
            me.polygons.foreach_get("normal", nz)
            nz = (nz.reshape(-1, 3) @ np.array(ob.matrix_world)[:3, :3].T)[:, 2]
            m &= nz > 0.6
        return m
    return f


def scatter_grass(objects, scale=1.0, *, select_roles=("lawn", "cliff_top"), roles=None,
                  density=110.0, height=(0.12, 0.34), edge_width=0.3, edge_noise=0.8,
                  spill_roles=("dirt",), spill=0.5, flowers=0.05, weeds=0.025,
                  region=None, lod_origin=None, lod_dist=14.0, blockers=None, seed=1, name="kit_grass",
                  points=None, exclude=None):
    """Grass tufts + flowers + broad weeds on faces with the given roles.
    points=(P, N, hmul) skips the sampling (caller decides where grass grows);
    exclude=[(lo, hi), ...] world boxes kept clear (gameplay objects).
    Thins and shortens toward the selection boundary (noisy, so edges are ragged)
    and spills a little onto neighbouring `spill_roles` faces.
    density: tufts per hero m^2. height: blade height range, hero metres.
    lod_origin: (x,y) world; beyond lod_dist*scale density falls off ~1/d^1.5."""
    rng = np.random.default_rng(seed)
    s2 = scale * scale
    if points is not None:
        P, N, hmul = points
        return _grass_from_points(P, N, hmul, scale, rng, height, flowers, weeds, lod_origin, lod_dist, blockers,
                                  exclude, seed, name)
    sel = _sel_roles(select_roles, roles, top_only=True)
    P, N = sample_surface(objects, sel, density / s2, seed, region)
    segs = boundary_segments(objects, sel)
    d = dist_to_segments(P, segs) / scale
    nz = _noise2(P / scale, 0.9, seed)
    edge = np.clip((d + nz * edge_noise * edge_width) / edge_width, 0, 1)
    keep = rng.random(len(P)) < (edge ** 1.5 * 0.97 + 0.03)
    hmul = 0.45 + 0.55 * edge
    if spill > 0 and spill_roles:
        Ps, Ns = sample_surface(objects, _sel_roles(spill_roles, roles), density * 0.6 / s2, seed + 7, region)
        ds = dist_to_segments(Ps, segs) / scale
        nzs = _noise2(Ps / scale, 0.9, seed)
        prob = np.clip(1 - ds / (spill * (1 + nzs)), 0, 1) ** 2
        ks = rng.random(len(Ps)) < prob
        # spill points must not be inside the lawn itself (they'd sit under it)
        Ps, Ns, ds = Ps[ks], Ns[ks], ds[ks]
        P = np.concatenate([P, Ps]); N = np.concatenate([N, Ns])
        keep = np.concatenate([keep, np.ones(len(Ps), bool)])
        hmul = np.concatenate([hmul, 0.35 + 0.3 * np.clip(1 - ds / spill, 0, 1)])
    P, N, hmul = P[keep], N[keep], hmul[keep]
    return _grass_from_points(P, N, hmul, scale, rng, height, flowers, weeds, lod_origin, lod_dist, blockers,
                              exclude, seed, name)


def outside_boxes(P, boxes, pad=0.0):
    k = np.ones(len(P), bool)
    for lo, hi in boxes or []:
        k &= ~((P[:, 0] > lo[0] - pad) & (P[:, 0] < hi[0] + pad) & (P[:, 1] > lo[1] - pad) & (P[:, 1] < hi[1] + pad)
               & (P[:, 2] > lo[2] - 1.0) & (P[:, 2] < hi[2] + 0.2))
    return k


def _grass_from_points(P, N, hmul, scale, rng, height, flowers, weeds, lod_origin, lod_dist, blockers, exclude, seed, name):
    if exclude:
        k = outside_boxes(P, exclude, 0.35 * scale)
        P, N, hmul = P[k], N[k], hmul[k]
    if lod_origin is not None:
        dd = np.hypot(P[:, 0] - lod_origin[0], P[:, 1] - lod_origin[1]) / scale
        pk = np.clip((lod_dist / np.maximum(dd, 1e-3)) ** 1.5, 0, 1)
        k = rng.random(len(P)) < pk
        P, N, hmul = P[k], N[k], hmul[k] / np.sqrt(np.sqrt(pk[k]))  # fewer, larger tufts far away
        hmul = np.minimum(hmul, 1.8)
    if blockers:
        k = ~_occluded(P, blockers, up=1.2 * scale)
        P, N, hmul = P[k], N[k], hmul[k]
    n = len(P)
    # variety: patches of taller/shorter grass and denser clumps (low-frequency noise)
    patch = _noise2(P / scale, 0.22, seed + 11)
    clump = _noise2(P / scale, 0.9, seed + 12)
    hmul = hmul * (1.0 + 0.45 * patch) * np.where(clump > 0.45, 1.45, 1.0)
    edge = hmul < 0.85  # points from thinned edges (lawn fringe on the path)
    kind = rng.random(n)
    weeds_p = np.where(edge, weeds * 3.0, weeds)
    flowers_p = np.where(edge, flowers * 2.0, flowers)
    grass_i = kind >= flowers_p + weeds_p
    flower_i = kind < flowers_p
    weed_i = ~grass_i & ~flower_i
    # flower patches: only keep flowers where a low-frequency noise is high
    fn = _noise2(P / scale, 0.35, seed + 3)
    flower_i &= ((fn > 0.0) | edge) & (rng.random(n) < 0.3)
    grass_i |= (kind < flowers_p) & ~flower_i
    # each surviving flower point seeds a small single-colour cluster
    fP, fpick = [], []
    for c in P[flower_i]:
        k = rng.integers(3, 8)
        r = 0.28 * scale * np.sqrt(rng.random(k))
        a = rng.uniform(0, 2 * np.pi, k)
        fP.append(c + np.stack([r * np.cos(a), r * np.sin(a), np.zeros(k)], 1))
        fpick.append(rng.integers(0, 3) + 3 * rng.integers(0, 2, k))
    fP = np.concatenate(fP) if fP else np.zeros((0, 3))
    fpick = np.concatenate(fpick) if fpick else np.zeros(0, int)

    gm = _grass_blade_mat(scale)
    vg = _variants("kit_v_grass", [_tuft_mesh(f"kit_tuft_{i}", np.random.default_rng(100 + i), gm) for i in range(8)])
    pink, white, blue = _flat("kit_petal_pink", "#f39ac2", 0.6), _flat("kit_petal_white", "#f7f4ee", 0.6), _flat("kit_petal_blue", "#7fa6f0", 0.6)
    stem, ctr = _flat("kit_stem", "#3f7a24", 0.8), _flat("kit_flower_center", "#f2c43a", 0.6)
    vf = _variants("kit_v_flower", [_flower_mesh(f"kit_flower_{i}", np.random.default_rng(200 + i), m, stem, ctr)
                                    for i, m in enumerate([pink, white, blue, pink, white, blue])])
    vw = _variants("kit_v_weed", [_weed_mesh(f"kit_weed_{i}", np.random.default_rng(300 + i),
                                             _flat("kit_weed_leaf", "#3c7d25", 0.6, rand=0.6)) for i in range(4)])
    coll = _coll(name)
    out = []
    if len(fP):
        m = len(fP)
        h = rng.uniform(0.6, 0.9, m) * height[1] * scale
        rot = np.stack([rng.normal(0, 0.1, m), rng.normal(0, 0.1, m), rng.uniform(0, 2 * np.pi, m)], 1)
        out.append(_instancer(f"{name}_flowers", fP, rot, np.stack([h, h, h], 1), fpick, vf, coll))
    for mask, vc, nv, hr, nm in ((grass_i, vg, 8, height, "tufts"), (weed_i, vw, 4, (0.08, 0.2), "weeds")):
        if not mask.any():
            continue
        m = mask.sum()
        h = rng.uniform(*hr, m) * hmul[mask] * scale
        rot = np.stack([rng.normal(0, 0.06, m), rng.normal(0, 0.06, m), rng.uniform(0, 2 * np.pi, m)], 1)
        sc = np.stack([h, h, h], 1)
        if nm == "tufts":
            sc[:, :2] *= rng.uniform(0.85, 1.25, (m, 1))
        pick = rng.integers(0, nv, m)
        out.append(_instancer(f"{name}_{nm}", P[mask], rot, sc, pick, vc, coll))
    return out


def scatter_clutter(objects, scale=1.0, *, select_roles=("dirt",), roles=None, pebbles=16.0, stones=1.2,
                    leaves=5.0, region=None, blockers=None, near=None, near_boost=2.5, seed=2, name="kit_clutter",
                    sampler=None, exclude=None, leaf_centers=None):
    """Pebbles, stones and fallen leaves on dirt faces. Counts are per hero m^2.
    near: boundary segments (e.g. lawn edges); density rises near them.
    sampler(density, seed) -> P replaces face sampling; exclude: boxes kept clear."""
    rng = np.random.default_rng(seed)
    s2 = scale * scale
    sel = _sel_roles(select_roles, roles, top_only=True)
    rockm = _pebble_mat(scale)
    leafm = [_flat(f"kit_leaf_{c}", c, 0.8, rand=0.4) for c in ("#b8742e", "#a88a3a", "#6f8a3a", "#7a5530")]
    vp = _variants("kit_v_pebble", [_rock_mesh(f"kit_pebble_{i}", np.random.default_rng(400 + i), rockm, 1, 0.55) for i in range(6)])
    vs = _variants("kit_v_stone", [_rock_mesh(f"kit_stone_{i}", np.random.default_rng(500 + i), rockm, 2, 0.8, 0.3) for i in range(4)])
    vl = _variants("kit_v_leaf", [_fallen_leaf_mesh(f"kit_fleaf_{i}", np.random.default_rng(600 + i), leafm[i]) for i in range(4)])
    coll = _coll(name)
    out = []
    for dens, vc, nv, size, sink, nm, sd in ((pebbles, vp, 6, (0.02, 0.055), 0.45, "pebbles", 0),
                                              (stones, vs, 4, (0.1, 0.24), 0.3, "stones", 1),
                                              (leaves, vl, 4, (0.07, 0.12), 0.0, "leaves", 2)):
        dd = dens * (near_boost if near is not None else 1.0) / s2
        P = sampler(dd, seed + sd) if sampler else sample_surface(objects, sel, dd, seed + sd, region)[0]
        if exclude:
            P = P[outside_boxes(P, exclude, 0.2 * scale)]
        cl = _noise2(P / scale, 0.25, seed + sd)
        prob = np.clip(0.55 + cl, 0.05, 1)
        if near is not None:
            d = dist_to_segments(P, near) / scale
            prob *= (1 / near_boost) + (1 - 1 / near_boost) * np.exp(-d / 1.2)
        if nm == "leaves" and leaf_centers:  # fallen leaves gather under trees
            lc = np.array(leaf_centers)
            dd = np.hypot(P[:, None, 0] - lc[None, :, 0], P[:, None, 1] - lc[None, :, 1]) / lc[None, :, 2]
            prob = prob * np.clip(np.exp(-(dd.min(1) - 1.0)), 0.03, 1.0)
        P = P[rng.random(len(P)) < prob]
        if blockers:
            P = P[~_occluded(P, blockers, up=1.2 * scale)]
        m = len(P)
        if not m:
            continue
        sz = rng.uniform(*size, m) * scale
        sz *= np.where(rng.random(m) < 0.1, 1.6, 1.0)
        P = P.copy()
        P[:, 2] -= sz * sink * 0.5
        if nm == "leaves":
            P[:, 2] += 0.004 * scale
            rot = np.stack([rng.normal(0, 0.04, m), rng.normal(0, 0.04, m), rng.uniform(0, 2 * np.pi, m)], 1)
        else:
            rot = np.stack([rng.normal(0, 0.2, m), rng.normal(0, 0.2, m), rng.uniform(0, 2 * np.pi, m)], 1)
        sc = np.stack([sz, sz, sz], 1)
        out.append(_instancer(f"{name}_{nm}", P, rot, sc, rng.integers(0, nv, m), vc, coll))
    return out


def scatter_lumps(P, scale, colour, *, size=(0.14, 0.42), squash=0.42, seed=8, name="kit_clutter_lumps"):
    """Soft low mounds at points P, gathered in patches."""
    rng = np.random.default_rng(seed)
    mat = _flat("kit_snow_lump", colour, 0.8)
    vs = _variants("kit_v_lump", [_rock_mesh(f"kit_lump_{i}", np.random.default_rng(700 + i), mat, 2, squash, 0.2) for i in range(5)])
    P = P[rng.random(len(P)) < np.clip(0.45 + 1.6 * _noise2(P / scale, 0.18, seed), 0.02, 1)].copy()
    m = len(P)
    sz = rng.uniform(*size, m) * scale * np.where(rng.random(m) < 0.12, 1.9, 1.0)
    P[:, 2] -= sz * 0.1
    rot = np.stack([rng.normal(0, 0.06, m), rng.normal(0, 0.06, m), rng.uniform(0, 2 * np.pi, m)], 1)
    return _instancer(name, P, rot, np.stack([sz, sz, sz], 1), rng.integers(0, 5, m), vs, _coll("kit_clutter"))


def top_edges(objects, select_roles=("cliff",), roles=None, min_len=0.05):
    """Convex edges where an up-facing face meets a near-vertical face.
    Returns list of (p0, p1, outward_normal) in world space."""
    res = []
    for ob in objects:
        if ob.type != "MESH":
            continue
        r = face_roles(ob, roles).astype(str)
        if not np.isin(r, list(select_roles)).any():
            continue
        M = ob.matrix_world
        R = M.to_3x3().inverted().transposed()
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        for e in bm.edges:
            if len(e.link_faces) != 2:
                continue
            f1, f2 = e.link_faces
            if r[f1.index] not in select_roles and r[f2.index] not in select_roles:
                continue
            n1, n2 = (R @ f1.normal).normalized(), (R @ f2.normal).normalized()
            if n1.z < n2.z:
                n1, n2 = n2, n1
            if n1.z > 0.7 and abs(n2.z) < 0.45:
                p0, p1 = M @ e.verts[0].co, M @ e.verts[1].co
                if (p1 - p0).length >= min_len:
                    out = Vector((n2.x, n2.y, 0)).normalized()
                    res.append((p0, p1, out))
        bm.free()
    return res


def top_edges_open(objects, select_roles=("cliff",), roles=None, blockers=None, min_len=0.05, up=6.0):
    """Upper edges of near-vertical faces with nothing above them. Works when the
    cliff faces and their tops are separate objects (one per texture), where
    top_edges() finds no shared edges. Returns (p0, p1, outward) world tuples."""
    res = []
    for ob in objects:
        if ob.type != "MESH":
            continue
        r = face_roles(ob, roles).astype(str)
        sel = np.isin(r, list(select_roles))
        if not sel.any():
            continue
        M = ob.matrix_world
        R = M.to_3x3().inverted().transposed()
        me = ob.data
        for p in me.polygons:
            if not sel[p.index]:
                continue
            n = (R @ p.normal).normalized()
            if abs(n.z) > 0.45:
                continue
            vs = [M @ me.vertices[i].co for i in p.vertices]
            ztop = max(v.z for v in vs)
            zlo = min(v.z for v in vs)
            for i in range(len(vs)):
                a, b2 = vs[i], vs[(i + 1) % len(vs)]
                if (b2 - a).length < min_len or abs(a.z - b2.z) > 0.35 * (b2 - a).length:
                    continue
                if min(a.z, b2.z) < ztop - 0.1 * max(ztop - zlo, 1e-3):
                    continue
                out = Vector((n.x, n.y, 0)).normalized()
                res.append((a, b2, out))
    if blockers and res:
        verts, polys, off = [], [], 0
        for ob in blockers:
            co, tv, _ = _world_tris(ob)
            verts.append(co); polys.append(tv + off); off += len(co)
        bvh = BVHTree.FromPolygons(np.concatenate(verts).tolist(), np.concatenate(polys).tolist())
        keep = []
        for a, b2, out in res:
            m = (a + b2) / 2 + out * 0.05 + Vector((0, 0, 0.05))
            if bvh.ray_cast(m, Vector((0, 0, 1)), up)[0] is None:
                keep.append((a, b2, out))
        res = keep
    return res


def cliff_overlay(objects, select_roles=("cliff",), roles=None, scale=1.0, *, max_depth=0.28, band=(0.55, 1.3),
                  seed=0, name="kit_cliff_overlay", coll=None, mat=None, boulder_every=2.6, top_rise=0.22,
                  min_area=0.25, space_bvh=None):
    """Overlay rock scenery on near-vertical cliff faces, without moving them:
    bevelled strata slabs of uneven thickness standing proud of the face by at
    most max_depth*scale (a guideline of ~1/4 hero height), a broken silhouette
    along the top and small boulders tucked at the base.
    Coplanar connected faces are merged into panels; each band's width follows
    the panel's outline at that height, so trapezoids and triangles are handled.
    Returns the overlay object (one mesh) or None."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    kh = bm.verts.layers.float.new("kit_h")
    nboulders = 0
    for ob in objects:
        if ob.type != "MESH":
            continue
        r = face_roles(ob, roles).astype(str)
        sel = np.isin(r, list(select_roles))
        if not sel.any():
            continue
        M = ob.matrix_world
        R3 = M.to_3x3().inverted().transposed()
        me = ob.data
        # group coplanar vertical faces (normal within ~10 degrees, same plane offset)
        panels = []
        for p in me.polygons:
            if not sel[p.index]:
                continue
            n = (R3 @ p.normal).normalized()
            if abs(n.z) > 0.6:
                continue
            nh = Vector((n.x, n.y, 0)).normalized()
            vs = [M @ me.vertices[i].co for i in p.vertices]
            off = nh.dot(sum(vs, Vector()) / len(vs))
            for pan in panels:
                if pan["n"].dot(nh) > 0.96 and abs(pan["off"] - off) < 0.3 * scale:
                    pan["tris"].append(vs)
                    break
            else:
                panels.append({"n": nh, "off": off, "tris": [vs]})
        for pan in panels:
            nh = pan["n"]
            if space_bvh is not None:
                # the game draws without culling, so a face's normal may point into the rock:
                # build on the side that has open space in front of it
                cen = sum((v for vs in pan["tris"] for v in vs), Vector()) / sum(len(vs) for vs in pan["tris"])
                fwd = space_bvh.ray_cast(cen + nh * 0.03, nh, 0.8 * scale)[0] is not None
                back = space_bvh.ray_cast(cen - nh * 0.03, -nh, 0.8 * scale)[0] is not None
                if fwd and not back:
                    nh = -nh
                    pan["off"] = -pan["off"]
                elif fwd and back:
                    continue  # buried between rocks: nothing to dress
            t = Vector((-nh.y, nh.x, 0))
            polys = [[(t.dot(v), v.z) for v in vs] for vs in pan["tris"]]
            area = sum(abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pp, pp[1:] + pp[:1]))) / 2 for pp in polys)
            if area < min_area * scale * scale:
                continue
            zb = min(z for pp in polys for _, z in pp)
            zt = max(z for pp in polys for _, z in pp)
            # point on the plane at u=0, z=0
            origin = nh * pan["off"]

            def span(z):
                us = []
                for pp in polys:
                    for (u1, z1), (u2, z2) in zip(pp, pp[1:] + pp[:1]):
                        if (z1 - z) * (z2 - z) <= 0 and z1 != z2:
                            us.append(u1 + (u2 - u1) * (z - z1) / (z2 - z1))
                return (min(us), max(us)) if len(us) >= 2 else None

            def W(u, z, d):
                return origin + t * u + Vector((0, 0, z)) + nh * d

            z = zb
            bands = []
            while z < zt - 0.05 * scale:
                h = rng.uniform(*band) * scale
                if zt - (z + h) < 0.35 * scale:
                    h = zt - z
                bands.append((z, min(z + h, zt)))
                z += h
            for bi, (z0, z1) in enumerate(bands):
                zm = (z0 + z1) / 2
                spm = span(zm)
                if not spm:
                    continue
                ua, ub = spm  # follow the outline at mid band height
                if ub - ua < 0.3 * scale:
                    continue
                top = bi == len(bands) - 1
                npieces = int(np.clip(round((ub - ua) / (rng.uniform(1.6, 3.2) * scale)), 1, 6))
                cuts = np.sort(rng.uniform(ua, ub, npieces - 1)) if npieces > 1 else np.array([])
                edges_u = [ua] + list(cuts) + [ub]
                for k in range(npieces):
                    u0, u1 = edges_u[k] + 0.03 * scale, edges_u[k + 1] - 0.03 * scale
                    if u1 - u0 < 0.2 * scale:
                        continue
                    d = rng.uniform(0.35, 1.0) * max_depth * scale
                    zz1 = z1 + (rng.uniform(-0.12, top_rise) * scale if top else rng.uniform(-0.04, 0.04) * scale)
                    zz0 = z0 + rng.uniform(0.0, 0.04) * scale
                    cs = [W(u, zz, dd) for zz in (zz0, zz1) for u in (u0, u1) for dd in (-0.06 * scale, d)]
                    # box corners: order (u0,z0,-),(u0,z0,+),(u1,z0,-),(u1,z0,+),(u0,z1,..)...
                    vs = [bm.verts.new(c) for c in cs]
                    for v in vs:
                        v[kh] = (v.co.z - zb) / max(zt - zb, 1e-3)
                    idx = lambda iu, iz, idd: vs[iz * 4 + iu * 2 + idd]
                    faces = [(idx(0, 0, 0), idx(1, 0, 0), idx(1, 0, 1), idx(0, 0, 1)),
                             (idx(0, 1, 0), idx(0, 1, 1), idx(1, 1, 1), idx(1, 1, 0)),
                             (idx(0, 0, 1), idx(1, 0, 1), idx(1, 1, 1), idx(0, 1, 1)),
                             (idx(0, 0, 0), idx(0, 0, 1), idx(0, 1, 1), idx(0, 1, 0)),
                             (idx(1, 0, 0), idx(1, 1, 0), idx(1, 1, 1), idx(1, 0, 1)),
                             (idx(0, 0, 0), idx(0, 1, 0), idx(1, 1, 0), idx(1, 0, 0))]
                    fs = []
                    for f in faces:
                        try:
                            fs.append(bm.faces.new(f))
                        except ValueError:
                            pass
                    bmesh.ops.recalc_face_normals(bm, faces=fs)
                    edges = list({e for f in fs for e in f.edges})
                    bev = min(d * 0.45, (zz1 - zz0) * 0.3, (u1 - u0) * 0.25)
                    bmesh.ops.bevel(bm, geom=edges, offset=bev, segments=2, affect="EDGES", profile=0.55)
            # boulders tucked at the base
            if boulder_every:
                spb = span(zb + 0.05 * scale)
                if spb and zt - zb > 0.9 * scale:
                    nb = int((spb[1] - spb[0]) / (boulder_every * scale) * rng.uniform(0.6, 1.2))
                    for _ in range(nb):
                        u = rng.uniform(spb[0] + 0.3 * scale, max(spb[0] + 0.31 * scale, spb[1] - 0.3 * scale))
                        rad = rng.uniform(0.14, 0.22) * scale  # stays within max_depth of the face
                        res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rad)
                        off3 = Vector(rng.uniform(-30, 30, 3))
                        c = W(u, zb + rad * 0.45, 0.0)
                        for v in res["verts"]:
                            v.co = Vector((v.co.x * rng.uniform(1.0, 1.3), v.co.y, v.co.z * 0.75)) * (1 + 0.12 * mnoise.noise(v.co * 3 + off3))
                            v.co = c + v.co
                            v[kh] = 0.0
                        nboulders += 1
    if not bm.verts:
        bm.free()
        return None
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat or mat_sandstone(None, scale, drips=False))
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    ob = _obj(name, me, coll)
    ob["kit_boulders"] = nboulders
    return ob


def islands(ob, mask=None):
    """Connected face groups of a mesh (optionally only masked polygons).
    Returns list of (poly_indices, lo, hi) with world-space bounds."""
    me = ob.data
    M = ob.matrix_world
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    seen, out = set(), []
    for f0 in bm.faces:
        if f0.index in seen or (mask is not None and not mask[f0.index]):
            continue
        st, isl = [f0], []
        seen.add(f0.index)
        while st:
            f = st.pop()
            isl.append(f.index)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen and (mask is None or mask[g.index]):
                        seen.add(g.index)
                        st.append(g)
        pts = [M @ v.co for i in isl for v in bm.faces[i].verts]
        lo = Vector([min(p[k] for p in pts) for k in range(3)])
        hi = Vector([max(p[k] for p in pts) for k in range(3)])
        out.append((isl, lo, hi))
    bm.free()
    return out


def merge_boxes(boxes, pad=0.0):
    """Union-find merge of world boxes overlapping in XY (pad grows them)."""
    boxes = [(Vector(lo), Vector(hi)) for lo, hi in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for lo, hi in boxes:
            for j, (l2, h2) in enumerate(out):
                if lo.x - pad <= h2.x and hi.x + pad >= l2.x and lo.y - pad <= h2.y and hi.y + pad >= l2.y:
                    out[j] = (Vector(map(min, l2, lo)), Vector(map(max, h2, hi)))
                    changed = True
                    break
            else:
                out.append((lo, hi))
        boxes = out
    return boxes


def scatter_vines(edges, scale=1.0, *, per_m=5.0, length=(0.4, 2.6), gap=0.35, seed=4, name="kit_vines"):
    """Hanging vine strands along top edges (from top_edges())."""
    rng = np.random.default_rng(seed)
    lengths = [0.35, 0.6, 0.9, 1.3, 1.8, 2.6]
    mat = _flat("kit_vine_leaf", "#3f8a26", 0.6, rand=0.7)
    vc = _variants("kit_v_vine", [_vine_mesh(f"kit_vine_{i}", np.random.default_rng(700 + i), mat, L) for i, L in enumerate(lengths)])
    P, rot, sc, pick = [], [], [], []
    for p0, p1, out in edges:
        L = (p1 - p0).length / scale
        n = rng.poisson(L * per_m)
        for _ in range(n):
            t = rng.random()
            p = p0.lerp(p1, t)
            if mnoise.noise(p / scale * 0.5 + Vector((seed, 0, 0))) < -gap:
                continue
            P.append(tuple(p + out * 0.01 * scale + Vector((0, 0, 0.03 * scale))))
            rot.append((0, 0, math.atan2(out.y, out.x) - math.pi / 2 + rng.normal(0, 0.1)))
            want = rng.uniform(*length) * (0.5 + 0.5 * (mnoise.noise(p / scale * 0.8) + 1))
            pick.append(int(np.argmin([abs(x - want) for x in lengths])))
            s = scale * rng.uniform(0.85, 1.15)
            sc.append((s, s, s))
    if not P:
        return None
    return _instancer(name, np.array(P), np.array(rot), np.array(sc), np.array(pick), vc, _coll("kit_vines"))


def scatter_ledge_moss(edges, scale=1.0, *, seed=5, name="kit_ledge"):
    """Overhanging grassy lip along top edges: low bush clumps half over the edge."""
    rng = np.random.default_rng(seed)
    vc = _variants("kit_v_bush", [_bush_mesh(f"kit_bush_{i}", np.random.default_rng(800 + i), scale) for i in range(4)])
    P, rot, sc, pick = [], [], [], []
    for p0, p1, out in edges:
        L = (p1 - p0).length / scale
        n = max(1, int(L * 1.1))
        for i in range(n):
            p = p0.lerp(p1, (i + rng.random()) / n)
            if rng.random() < 0.25:
                continue
            P.append(tuple(p + out * rng.uniform(-0.25, 0.15) * scale - Vector((0, 0, rng.uniform(0.05, 0.3) * scale))))
            rot.append((rng.normal(0, 0.2), rng.normal(0, 0.2), rng.uniform(0, 6.28)))
            s = scale * rng.uniform(0.45, 1.25)
            sc.append((s, s, s * rng.uniform(0.6, 0.9)))
            pick.append(int(rng.integers(0, 4)))
    if not P:
        return None
    return _instancer(name, np.array(P), np.array(rot), np.array(sc), np.array(pick), vc, _coll("kit_vines"))


def _bush_mesh(name, rng, scale, clumps=5):
    centers = [(Vector((rng.normal(0, 0.4), rng.normal(0, 0.4), rng.uniform(0.15, 0.45))), rng.uniform(0.3, 0.5))
               for _ in range(clumps)]
    return _canopy_mesh(name, centers, 1.0, rng, 26, scale, (0.35, 0.5))


# ---------------------------------------------------------------- props

def _box(bm, c, size, bevel=0.0, layer=None, value=None, warp=None):
    """Box with optional per-vertex layer value and a warp(co)->co applied before bevelling."""
    vs = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in vs:
        co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2])) + Vector(c)
        v.co = warp(co) if warp else co
        if layer is not None:
            v[layer] = value
    if bevel > 0:
        edges = list({e for v in vs for e in v.link_edges})
        bmesh.ops.bevel(bm, geom=edges + vs, offset=bevel, segments=2, affect="EDGES", profile=0.6)


def fence(p0, p1, scale=1.0, *, height=1.05, post_spacing=2.2, post_w=0.19, rail_h=0.17, rail_t=0.07,
          rails=(0.42, 0.82), name="kit_fence", coll=None, sink=0.0):
    """Chunky white post-and-rail fence from p0 to p1 (world; z of each end is the ground).
    sink: extra post length below the base (world units) for uneven ground."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = Vector((d.x, d.y, 0)).length
    H, pw, rh, rt = height * scale, post_w * scale, rail_h * scale, rail_t * scale
    nseg = max(1, round(L / (post_spacing * scale)))
    bm = bmesh.new()
    gd = bm.verts.layers.float_vector.new("kit_gdir")
    rng = np.random.default_rng(int(abs(p0.x * 13 + p0.y * 7)) % 1000)

    for i in range(nseg + 1):
        x = L * i / nseg
        z0 = (p0.z + (p1.z - p0.z) * i / nseg) - p0.z
        tilt = rng.normal(0, 0.02)
        _box(bm, (x, 0, z0 + (H + 0.04 * scale) / 2 - 0.05 * scale - sink / 2), (pw, pw, H + 0.1 * scale + sink), 0.018 * scale,
             gd, (0, 0, 1), lambda co, t=tilt, z0=z0: co + Vector((t * (co.z - z0), 0, 0)))
        # pointed-ish cap: pull top centre up
        cap = bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=pw * 0.74, radius2=0.0, depth=0.09 * scale)
        for v in cap["verts"]:
            v.co = Matrix.Rotation(math.pi / 4, 3, "Z") @ v.co + Vector((x + tilt * H, 0, z0 + H + 0.04 * scale))
        for v in cap["verts"]:
            v[gd] = (0, 0, 1)
    for rz in rails:
        for i in range(nseg):
            xa, xb = L * i / nseg, L * (i + 1) / nseg
            za = (p1.z - p0.z) * i / nseg
            zb = (p1.z - p0.z) * (i + 1) / nseg
            sag = rng.normal(0, 0.012) * scale
            _box(bm, ((xa + xb) / 2, pw * 0.5 + rt * 0.5, rz * H + (za + zb) / 2 + sag), (xb - xa + pw * 0.9, rt, rh),
                 0.012 * scale, gd, (1, 0, 0),
                 lambda co, xa=xa, xb=xb, dz=zb - za: co + Vector((0, 0, dz * ((co.x - xa) / max(xb - xa, 1e-6) - 0.5))))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material("wood", None, scale))
    me.polygons.foreach_set("use_smooth", np.zeros(len(me.polygons), bool))
    ob = _obj(name, me, coll)
    ob.location = p0
    ob.rotation_euler = (0, 0, math.atan2(d.y, d.x))
    return ob


def boulder(center, size, scale=1.0, *, seed=0, name="kit_boulder", coll=None, sink=0.18):
    """Rounded boulder filling a bbox of `size` (world xyz) with its base at center.z."""
    rng = np.random.default_rng(seed)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=0.5)
    off = Vector(rng.uniform(-50, 50, 3))
    for v in bm.verts:
        n = mnoise.noise(v.co * 1.6 + off) * 0.16 + mnoise.noise(v.co * 4 + off) * 0.04
        v.co *= 1 + n
        if v.co.z < -0.25:
            v.co.z = -0.25 + (v.co.z + 0.25) * 0.2
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material("rock", None, scale))
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    ob = _obj(name, me, coll)
    sx, sy, sz = size
    ob.scale = (sx, sy, sz * 1.3)
    ob.location = Vector(center) + Vector((0, 0, sz * (0.5 - sink)))
    ob.rotation_euler = (0, 0, rng.uniform(0, 6.28))
    return ob


def tree(base, height, canopy_radius, scale=1.0, *, seed=0, name="kit_tree", coll=None, clumps=14, cards_per_clump=110, trunk_r=None):
    """Stylized tree: tapered bent trunk with branches + clumpy rounded canopy of
    sphere clumps wrapped in alpha-tested leaf cards with clump-spherical normals."""
    rng = np.random.default_rng(seed)
    base = Vector(base)
    H, R = height, canopy_radius
    cz = H - R * 0.95
    # trunk
    bm = bmesh.new()
    rings, segs = 6, 8
    r0 = trunk_r * 0.92 / 2.16 if trunk_r else max(0.09 * scale, R * 0.11)  # 2.16: the flare at its base
    lean = Vector((rng.normal(0, 0.06), rng.normal(0, 0.06), 0)) * H
    verts = []
    for i in range(rings + 1):
        t = i / rings
        c = lean * (t * t) + Vector((0, 0, cz * 1.02 * t))
        r = r0 * (1.35 - 0.6 * t) * (1 + 0.6 * max(0, 0.15 - t) / 0.15)
        ring = [bm.verts.new(c + Vector((math.cos(a) * r, math.sin(a) * r, 0))) for a in np.linspace(0, 2 * np.pi, segs, endpoint=False)]
        verts.append(ring)
    for i in range(rings):
        for j in range(segs):
            bm.faces.new((verts[i][j], verts[i][(j + 1) % segs], verts[i + 1][(j + 1) % segs], verts[i + 1][j]))
    # branches toward clump centres
    centers = []
    for k in range(clumps):
        if k == 0:
            c = Vector((0, 0, cz + R * 0.35))
        else:
            a = rng.uniform(0, 2 * np.pi)
            el = rng.uniform(-0.35, 0.75)
            rr = R * rng.uniform(0.45, 0.8)
            c = Vector((math.cos(a) * math.cos(el) * rr, math.sin(a) * math.cos(el) * rr * 0.9, cz + math.sin(el) * rr * 0.75))
        centers.append((c + lean, R * rng.uniform(0.36, 0.5) if k else R * 0.55))
    for c, _ in centers[1:5]:
        a0 = lean * 0.6 + Vector((0, 0, cz * 0.75))
        dv = c - a0
        br = bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=r0 * 0.5, radius2=r0 * 0.2, depth=dv.length)
        q = dv.to_track_quat("Z", "Y")
        for v in br["verts"]:
            v.co = q @ v.co + a0 + dv * 0.5
    tme = bpy.data.meshes.new(name + "_trunk")
    bm.to_mesh(tme)
    bm.free()
    tme.materials.append(material("bark", None, scale))
    tme.polygons.foreach_set("use_smooth", np.ones(len(tme.polygons), bool))
    trunk = _obj(name + "_trunk", tme, coll)
    trunk.location = base
    me = _canopy_mesh(name + "_canopy", centers, R, rng, cards_per_clump, scale, (0.15, 0.23))
    can = _obj(name + "_canopy", me, coll)
    can.location = base
    return trunk, can


def _canopy_mesh(name, centers, R, rng, cards_per_clump, scale, card_size=(0.24, 0.34)):
    """Clumps (solid icosphere cores) wrapped in alpha-tested leaf cards. Normals
    blend clump-radial and canopy-radial so it shades like soft blobs; kit_ao
    darkens the interior/underside."""
    V, F, N, AO, UV = [], [], [], [], []
    cc = sum((c for c, _ in centers), Vector()) / len(centers)
    for c, r in centers:
        bmc = bmesh.new()
        bmesh.ops.create_icosphere(bmc, subdivisions=3, radius=r * 0.82)
        k = len(V)
        for v in bmc.verts:
            p = v.co + c
            V.append(tuple(p))
            n = (v.co.normalized() * 0.6 + (p - cc).normalized() * 0.4).normalized()
            N.append(tuple(n))
            AO.append(float(np.clip(0.35 + 0.65 * ((p - cc).normalized().z * 0.5 + 0.5) * min(1, (p - cc).length / R), 0, 1)))
        for f in bmc.faces:
            F.append(tuple(k + v.index for v in f.verts))
            UV.append(None)
        bmc.free()
    nsolid = len(F)
    for c, r in centers:
        for _ in range(cards_per_clump):
            d = Vector(rng.normal(0, 1, 3)).normalized()
            if d.z < -0.6:
                d.z *= 0.5
                d.normalize()
            p = c + d * r * rng.uniform(0.85, 1.05)
            sz = R * rng.uniform(*card_size)
            t1 = d.orthogonal().normalized()
            t2 = d.cross(t1)
            ang = rng.uniform(0, 2 * np.pi)
            u = t1 * math.cos(ang) + t2 * math.sin(ang)
            w = d.cross(u)
            # tilt card so it is not exactly tangent: reads better at grazing angles
            w = (w + d * rng.uniform(-0.4, 0.4)).normalized()
            k = len(V)
            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                q = p + u * su * sz * 0.5 + w * sv * sz * 0.5
                V.append(tuple(q))
                n = ((q - c).normalized() * 0.6 + (q - cc).normalized() * 0.4).normalized()
                N.append(tuple(n))
                AO.append(float(np.clip(0.35 + 0.65 * ((q - cc).normalized().z * 0.5 + 0.5) * min(1, (q - cc).length / R), 0, 1)))
            F.append((k, k + 1, k + 2, k + 3))
            if USE_ASSETS:  # one leaf of the 3x3 atlas per card
                cu, cv = rng.integers(0, 3, 2) / 3.0
                UV.append([(cu, cv), (cu + 1 / 3, cv), (cu + 1 / 3, cv + 1 / 3), (cu, cv + 1 / 3)])
            else:
                UV.append([(0, 0), (1, 0), (1, 1), (0, 1)])
    uvs = []
    for f, uv in zip(F, UV):
        uvs += uv if uv else [(0.5, 0.5)] * len(f)
    fm = [0] * nsolid + [1] * (len(F) - nsolid)
    return _mesh(name, V, F, {"kit_ao": ("POINT", "FLOAT", AO)},
               [material("foliage", None, scale), _cards_mat(scale)], fm, uvs=uvs, normals=N)


def _cards_mat(scale):
    key = ("foliage_cards", None, round(scale, 4))
    m = _MATS.get(key)
    if m is None or m.name not in bpy.data.materials:
        m = mat_foliage(scale=scale, cards=True)
        _MATS[key] = m
    return m


# ---------------------------------------------------------------- props from game objects

def world_bbox(ob):
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def tree_from_bbox(lo, hi, scale=1.0, at=None, **kw):
    c = (lo + hi) / 2 if at is None else at
    H = hi.z - lo.z
    R0 = max(hi.x - lo.x, hi.y - lo.y) * 0.5
    R = min(R0 * 0.72, 0.36 * H)  # sensible canopy, leaving a visible trunk
    return tree((c.x, c.y, lo.z), H * 0.98, R, scale, **kw)


def fence_from_bbox(lo, hi, scale=1.0, **kw):
    if hi.x - lo.x >= hi.y - lo.y:
        cy = (lo.y + hi.y) / 2
        return fence((lo.x, cy, lo.z), (hi.x, cy, lo.z), scale, height=max(0.8, (hi.z - lo.z) / scale), **kw)
    cx = (lo.x + hi.x) / 2
    return fence((cx, lo.y, lo.z), (cx, hi.y, lo.z), scale, height=max(0.8, (hi.z - lo.z) / scale), **kw)


def boulder_from_bbox(lo, hi, scale=1.0, **kw):
    c = (lo + hi) / 2
    return boulder((c.x, c.y, lo.z), (hi.x - lo.x, hi.y - lo.y, hi.z - lo.z), scale, **kw)


# ---------------------------------------------------------------- one-call apply

def apply(objects=None, scale=1.0, *, roles=None, region=None, lod_origin=None, tint_amount=0.15, seed=0,
          grass=None, clutter=None, vines=True):
    """Dress a scene. objects: game meshes (default: all visible meshes).
    Returns a stats dict (instances, added triangles, per system)."""
    t0 = time.time()
    scn = bpy.context.scene
    bpy.context.view_layer.update()
    objects = [ob for ob in (objects or scn.objects) if ob.type == "MESH" and not ob.name.startswith("kit_")]
    props = bpy.data.collections.get("kit_props") or _coll("kit_props")
    stats = {"props": {}, "scatter": {}}
    # 1. replace prop objects
    surf = []
    for i, ob in enumerate(objects):
        r = ob.get("look")
        lo, hi = world_bbox(ob)
        if r == "tree":
            made = tree_from_bbox(lo, hi, scale, seed=seed + i, name=f"kit_tree_{ob.name}", coll=props)
        elif r == "fence":
            made = (fence_from_bbox(lo, hi, scale, name=f"kit_fence_{ob.name}", coll=props),)
        elif r == "boulder":
            made = (boulder_from_bbox(lo, hi, scale, seed=seed + i, name=f"kit_boulder_{ob.name}", coll=props),)
        else:
            surf.append(ob)
            continue
        ob.hide_render = ob.hide_viewport = True
        for m in made:
            stats["props"][m.name] = tri_count(m)
    # 2. materials
    assign_materials(surf, scale, roles, tint_amount)
    # 3. scatter
    blockers = [ob for ob in surf if np.isin(face_roles(ob, roles).astype(str),
                                             ["lawn", "cliff", "cliff_top", "brick", "trim", "stone", "water", "rock"]).any()]
    lawn_sel = _sel_roles(("lawn",), roles, top_only=True)
    lawn_edges = boundary_segments(surf, lawn_sel)
    gkw = dict(region=region, lod_origin=lod_origin, seed=seed + 1, blockers=blockers)
    gkw.update(grass or {})
    for ob in scatter_grass(surf, scale, roles=roles, **gkw):
        stats["scatter"][ob.name] = (ob["kit_instances"], ob["kit_tris"])
    ckw = dict(region=region, seed=seed + 2, near=lawn_edges,
               blockers=[b for b in blockers if not np.isin(face_roles(b, roles).astype(str), ["dirt"]).all()])
    ckw.update(clutter or {})
    for ob in scatter_clutter(surf, scale, roles=roles, **ckw):
        stats["scatter"][ob.name] = (ob["kit_instances"], ob["kit_tris"])
    if vines:
        edges = top_edges(surf, ("cliff",), roles)
        for ob in (scatter_vines(edges, scale, seed=seed + 4), scatter_ledge_moss(edges, scale, seed=seed + 5)):
            if ob:
                stats["scatter"][ob.name] = (ob["kit_instances"], ob["kit_tris"])
    stats["instances"] = sum(v[0] for v in stats["scatter"].values())
    stats["scatter_tris"] = sum(v[1] for v in stats["scatter"].values())
    stats["prop_tris"] = sum(stats["props"].values())
    stats["apply_seconds"] = round(time.time() - t0, 1)
    return stats


def save_library(path, scale=1.0):
    """Write a .blend holding every kit material, the scatter variant collections
    and one of each prop, for inspection or appending (bpy.ops.wm.append) elsewhere.
    The functions above stay the source of truth."""
    for r in list(REF) + ["cliff_top"]:
        material(r, None, scale).use_fake_user = True
    _cards_mat(scale).use_fake_user = True
    coll = _coll("kit_library_props")
    tree((0, 0, 0), 5 * scale, 2 * scale, scale, coll=coll, name="kit_lib_tree")
    fence((4 * scale, 0, 0), (10 * scale, 0, 0), scale, coll=coll, name="kit_lib_fence")
    boulder((-4 * scale, 0, 0), (1.2 * scale,) * 3, scale, coll=coll, name="kit_lib_boulder")
    _grass_blade_mat(scale)
    rng = np.random.default_rng(0)
    gm = _grass_blade_mat(scale)
    _variants("kit_v_grass", [_tuft_mesh(f"kit_tuft_{i}", np.random.default_rng(100 + i), gm) for i in range(8)])
    _variants("kit_v_bush", [_bush_mesh(f"kit_bush_{i}", np.random.default_rng(800 + i), scale) for i in range(4)])
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
