"""Dresses a captured level with the look kit: game / lit / dressed, from the captured hero
camera (A) and hand-placed cameras (B, C). The level's data is its block in levels.py.

  blender -b --factory-startup --python-exit-code 1 -P tools/look/dress.py -- <game|lit|dressed> [--level zoohub] [--camera A|B|AB] [--samples 64] [--res 100]
  python3 tools/look/dress.py compose        # strips and the target comparison (needs PIL)

Inputs: the level's capture blend (never written). Outputs in its out folder: final-*.jpg,
<level>-lit.blend, <level>-dressed.blend.

Everything is driven by RULES (texture name -> role). The only hand-made items
are in HAND, kept short on purpose: how much is rules vs hand work is a result.
"""
import sys, os, math, fnmatch, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import levels

SCALE = 1.05  # Taz ~1.26 BU standing vs the kit's 1.2 m hero
MAX_SCATTER_TRIS = 8_000_000  # the zoo has 5.6M; a 36.6M draft was rendering when the GPU driver hung

RULES = []  # the selected level's texture -> role table


def select(name):
    """Makes this level's rules current and returns its block."""
    global RULES
    L = levels.LEVELS[name]
    RULES = L["rules"]
    return L


GAME_COLLS = ("hero", "hero placed", "sweep", "sweep placed")


def base_name(n):
    return n.split("@")[0].split("~")[0]


def role_of(name):
    b = base_name(name)
    for pat, r in RULES:
        if fnmatch.fnmatch(b, pat):
            return r
    return "lit"


# =================================================================== Blender side
def blender_main(argv):
    import bpy, argparse
    import numpy as np
    from mathutils import Vector, Matrix
    import kit

    ap = argparse.ArgumentParser()
    ap.add_argument("version", choices=["game", "lit", "dressed"])
    ap.add_argument("--level", default="zoohub", choices=sorted(levels.LEVELS))
    ap.add_argument("--camera", default="", help="preview renders, A and/or B; Eevee needs the GPU, so none by default")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--res", type=int, default=100)
    ap.add_argument("--out", default=None, help="subfolder of extracted/look (default: the level's; '' = pass 1 location)")
    ap.add_argument("--pass1", action="store_true", help="pass 1 look (baked sun, old cliffs/trees)")
    ap.add_argument("--procedural", action="store_true", help="don't use the CC0 texture sets")
    ap.add_argument("--procedural-sky", action="store_true", help="procedural clouds instead of the HDRI's")
    a = ap.parse_args(argv)
    L = select(a.level)
    HAND, LEVEL, HDRI, HDRI_ROT, PASS1 = L["hand"], L["look"], L["hdri"], L["hdri_rotation"], levels.ZOO_PASS1
    a.out = L["out"] if a.out is None else a.out
    kit.USE_ASSETS = not (a.procedural or a.pass1)
    src = kit.out_dir()
    if a.out.rstrip("/") == "pass2":
        raise SystemExit("pass2/ is frozen (read by the in-game renderer test)")
    out = src / a.out if a.out else src
    out.mkdir(parents=True, exist_ok=True)
    look = PASS1 if a.pass1 else LEVEL
    bpy.ops.wm.open_mainfile(filepath=str(src / L["blend"]))
    sc = bpy.context.scene
    cam_a = sc.camera
    stats = {}

    world = [o for c in GAME_COLLS if c in bpy.data.collections for o in bpy.data.collections[c].objects if o.type == "MESH"]
    chars = [o for o in bpy.data.collections["characters"].objects if o.type == "MESH"]
    taz = [o for o in chars if o.name.startswith("zoohub_aquadone") or o.name.startswith("zoohub_intro")]
    eleph = [o for o in chars if o not in taz]

    # ---- cameras B and C (hand) -------------------------------------------------------
    def hand_camera(key):
        cb = HAND[key]
        cd = bpy.data.cameras.new(key)
        cd.lens, cd.sensor_width = cb["lens"], 36
        cd.clip_start, cd.clip_end = 0.05, 600
        cam = bpy.data.objects.new(key.replace("_", " "), cd)
        sc.collection.objects.link(cam)
        cam.location = cb["loc"]
        cam.rotation_euler = (Vector(cb["look_at"]) - Vector(cb["loc"])).to_track_quat("-Z", "Y").to_euler()
        return cam, cd
    cam_b, cdb = hand_camera("camera_B")
    cam_c, _ = hand_camera("camera_C")

    def frame(cam):
        if cam == "A":
            sc.camera = cam_a
            sc.render.resolution_x, sc.render.resolution_y = 2880, 1800
            sc.render.pixel_aspect_x = 1.0714287757873535
        else:
            sc.camera = cam_b if cam == "B" else cam_c
            sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
            sc.render.pixel_aspect_x = 1.0
        sc.render.resolution_percentage = a.res

    def move_chars(cam):
        for objs, key in ((taz, "taz_offset_B"), (eleph, "elephant_offset_B")):
            for o in objs:
                if "kit_home" not in o:
                    o["kit_home"] = list(o.location)
                home = Vector(o["kit_home"])
                o.location = home + (Vector(HAND[key]) if cam == "B" else Vector())

    def render(path):
        t = time.time()
        sc.render.filepath = str(path)
        sc.render.image_settings.file_format = "JPEG"
        sc.render.image_settings.quality = 93
        bpy.ops.render.render(write_still=True)
        return round(time.time() - t, 1)

    # ---- game version: the capture's own emission materials ---------------------------
    if a.version == "game":
        sc.render.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = 16
        for c in a.camera:
            if c == "A":
                continue
            move_chars(c)
            frame(c)
            stats["render_" + c] = render(out / f"final-{c}-game.jpg")
        print("ZOOHUB", stats)
        return

    # ---- shared: lit materials (game texture as base colour, baked shade removed) -----
    for img in bpy.data.images:
        if img.source == "FILE":
            img.colorspace_settings.name = "sRGB"

    def clean_vcol(ob):
        """kit_vcol: the game's vertex colour with the baked two-tone shade dropped
        (lilac shade -> neutral grey); real tints are kept."""
        me = ob.data
        if "kit_vcol" in me.color_attributes or "game_color" not in me.color_attributes:
            return
        src = me.color_attributes["game_color"]
        c = np.empty(len(src.data) * 4, np.float32)
        src.data.foreach_get("color", c)
        c = c.reshape(-1, 4)
        r, g, b = c[:, 0] * 255, c[:, 1] * 255, c[:, 2] * 255
        shade = (np.abs(b - 127) <= 3) & (np.abs(r - 109) <= 5) & (np.abs(g - 100) <= 5)
        c[shade, :3] = 127 / 255
        dst = me.color_attributes.new("kit_vcol", "FLOAT_COLOR", "CORNER")
        dst.data.foreach_set("color", c.ravel())

    def game_image(m):
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    return n.image, n.interpolation
        return None, "Linear"

    lit_cache = {}
    hidden = bpy.data.materials.new("kit_hidden")
    hidden.use_nodes = True
    hidden.node_tree.nodes.clear()
    hb = kit._B(hidden.node_tree)
    hb("ShaderNodeOutputMaterial", {"Surface": hb("ShaderNodeBsdfTransparent")})
    hidden.surface_render_method = "DITHERED"


    def backdrop_material(m):
        """Skybox as a far hill band: its painted sky (bright, blue-dominant) is cut
        away so the kit sky shows; hills/mountains stay as unlit backdrop."""
        img, interp = game_image(m)
        nm, b = kit._new_mat("backdrop:" + m.name)
        tx = b("ShaderNodeTexImage", {"Vector": kit.o(b("ShaderNodeUVMap", uv_map="UVMap"))}, image=img)
        col = kit.o(tx, "Color")
        r_, g_, b_ = b.sep(col)
        sky = b.math("MULTIPLY", b.fac_ramp(b_, 0.75, 0.9), b.math("MAXIMUM", b.fac_ramp(g_, 0.55, 0.75),
                                                                   b.math("SUBTRACT", 1.0, b.fac_ramp(r_, 0.15, 0.3))))
        keep = b.math("SUBTRACT", 1.0, sky)
        # and only near the horizon: the band seen within ~12 degrees above eye level
        inc = kit.o(b("ShaderNodeNewGeometry"), "Incoming")
        elev = b.math("MULTIPLY", b.sep(inc)[2], -1.0)
        keep = b.math("MULTIPLY", keep, b.math("LESS_THAN", elev, 0.2))
        hz = b.mix(0.25, col, kit.srgb("#cfe6ff"))  # a touch of aerial haze
        em = b("ShaderNodeEmission", {"Color": hz, "Strength": 1.0})
        tr = b("ShaderNodeBsdfTransparent")
        b("ShaderNodeOutputMaterial", {"Surface": b("ShaderNodeMixShader", {0: b.math("GREATER_THAN", keep, 0.5), 1: tr, 2: em})})
        nm.surface_render_method = "DITHERED"
        return nm

    def panel_material(m):
        """A level whose own painted sky is kept: texture x vertex colour x 2 in sRGB, as the game draws it, unlit."""
        img, _ = game_image(m)
        img.colorspace_settings.name = "Non-Color"
        nm, b = kit._new_mat("backdrop:" + m.name)
        tx = b("ShaderNodeTexImage", {"Vector": kit.o(b("ShaderNodeUVMap", uv_map="UVMap"))}, image=img)
        vc = kit.o(b("ShaderNodeVertexColor", layer_name="game_color"), "Color")
        col = b.mix(1.0, kit.o(tx, "Color"), b.mix(1.0, vc, vc, "ADD"), "MULTIPLY")
        col = kit.o(b("ShaderNodeGamma", {"Color": col, "Gamma": 2.2}))
        b("ShaderNodeOutputMaterial", {"Surface": b("ShaderNodeEmission", {"Color": col, "Strength": 1.0})})
        return nm

    def lit_material(m, character=False, stylized=False, punch=False):
        key = m.name + ("~s" if stylized else "") + ("~p" if punch else "")
        if key in lit_cache:
            return lit_cache[key]
        img, interp = game_image(m)
        nm, b = kit._new_mat(("lit+:" if stylized else "lit:") + m.name)
        nm["src"] = m.name
        alpha = None
        if img is not None:
            tx = b("ShaderNodeTexImage", {"Vector": kit.o(b("ShaderNodeUVMap", uv_map="UVMap"))}, image=img)
            tx.interpolation = interp
            col, alpha = kit.o(tx, "Color"), kit.o(tx, "Alpha")
        else:
            col = (0.8, 0.8, 0.8)
        if not character or img is None:
            vc = kit.o(b("ShaderNodeVertexColor", layer_name="kit_vcol" if not character else "game_color"), "Color")
            if character:  # raw sRGB bytes -> linear
                vc2 = kit.o(b("ShaderNodeGamma", {"Color": vc, "Gamma": 2.2}))
            else:
                vc2 = b.mix(1.0, vc, vc, "ADD")  # world draws are modulate2x
            col = b.mix(1.0, col, vc2, "MULTIPLY") if img is not None else vc2
        a_test, a_blend = m.get("alpha_test", 0), m.get("alpha_blend", 0)
        al = None
        if (a_test or a_blend) and alpha is not None:
            ref = m.get("alpha_ref", 0) / 255
            al = b.math("GREATER_THAN", alpha, max(ref, 0.5 if not a_blend else ref))
            if a_blend:
                al = b.math("MULTIPLY", alpha, b.math("GREATER_THAN", alpha, ref))
            nm.surface_render_method = "BLENDED" if a_blend and not a_test else "DITHERED"
        if punch:  # gameplay objects: keep their saturated game colours under the bright grade
            col = kit.o(b("ShaderNodeHueSaturation", {"Color": col, "Saturation": 1.25, "Value": 0.82}), "Color")
        nrm = None
        if stylized and img is not None:
            # the minimum that stops untouched pieces looking pasted in next to kit surfaces:
            # the kit's light response (roughness/spec), world-space value break-up, and
            # relief read from the painted texture's own luminance
            p = kit._wp(b, SCALE)
            nz = b.noise(p, 1.5, 3, 0.55)
            col = b.mix(1.0, col, b.ramp(nz, [(0.3, (0.88, 0.88, 0.88)), (0.7, (1.06, 1.06, 1.06))]), "MULTIPLY")
            lum = kit.o(b("ShaderNodeRGBToBW", {0: kit.o(tx, "Color")}))
            nrm = kit._bump(b, b.math("ADD", lum, b.math("MULTIPLY", nz, 0.3)), 0.25, 0.02 * SCALE)
        kit._finish(b, col, 0.7 if stylized else 0.75, nrm, spec=0.35 if stylized else 0.3, alpha=al)
        nm.use_backface_culling = False
        lit_cache[key] = nm
        return nm

    counts = {"objects_hidden": 0, "faces_hidden": 0}
    for ob in world:
        clean_vcol(ob)
        roles = [role_of(s.material.name) if s.material else "lit" for s in ob.material_slots]
        if all(s.material and "shadowsub" in s.material.name for s in ob.material_slots) or \
                (a.pass1 and all(r == "sky" for r in roles)):
            ob.hide_render = True  # baked blob shadow -> real shadows (pass 1 also dropped the skybox)
            counts["objects_hidden"] += 1
            continue
        if all(r == "sky" for r in roles):
            for s in ob.material_slots:  # side panels carry the hill band; top/bottom panels go
                s.material = (panel_material(s.material) if L.get("sky_panels") else
                              backdrop_material(s.material) if "second" in s.material.name else hidden)
            ob.visible_shadow = False
            continue
        for s in ob.material_slots:
            if s.material:
                s.material = lit_material(s.material, punch=not a.pass1 and role_of(s.material.name) == "gameplay")
    for ob in chars:
        for s in ob.material_slots:
            if s.material:
                s.material = lit_material(s.material, character=True)

    def dress_characters():
        """Taz: soft fur (sheen, fine strand bump), browns pulled back from red.
        Elephant: smooth shading + one subdivision level, grey skin with wrinkle bump."""
        for ob in taz:
            for sl in ob.material_slots:
                m0 = sl.material
                if not m0:
                    continue
                src_m = bpy.data.materials.get(m0.get("src", ""), m0)
                img, interp = game_image(src_m)
                if img is None:
                    continue
                nm, b = kit._new_mat("fur:" + src_m.name)
                tx = b("ShaderNodeTexImage", {"Vector": kit.o(b("ShaderNodeUVMap", uv_map="UVMap"))}, image=img)
                col = kit.o(b("ShaderNodeHueSaturation", {"Color": kit.o(tx, "Color"), "Hue": 0.52, "Saturation": 0.95,
                                                          "Value": 0.88}), "Color")
                p = kit.o(b("ShaderNodeTexCoord"), "Object")
                strands = b.noise(b.vmath("SCALE", p, 1.0 / SCALE), 90.0, 2, 0.5)
                kit._finish(b, col, 0.75, kit._bump(b, strands, 0.12, 0.004), spec=0.25,
                            extra={"Sheen Weight": 0.2, "Sheen Roughness": 0.5, "Sheen Tint": (0.6, 0.4, 0.25, 1.0)})
                sl.material = nm
        for ob in eleph:
            me = ob.data
            me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
            if me.has_custom_normals:
                me.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(me.loops))
            if ob.name.startswith("untextured"):
                md = ob.modifiers.new("kit_subsurf", "SUBSURF")
                md.levels = md.render_levels = 1
                for sl in ob.material_slots:
                    nm, b = kit._new_mat("skin:elephant")
                    vc = kit.o(b("ShaderNodeVertexColor", layer_name="game_color"), "Color")
                    base = kit.o(b("ShaderNodeGamma", {"Color": vc, "Gamma": 2.2}))
                    p = kit.o(b("ShaderNodeTexCoord"), "Object")
                    q = b.vmath("SCALE", p, 1.0 / SCALE)
                    var = b.noise(q, 1.2, 3, 0.5)
                    base = b.mix(1.0, base, b.ramp(var, [(0.3, (0.62, 0.63, 0.67)), (0.7, (0.76, 0.74, 0.72))]), "MULTIPLY")
                    wr = b.noise(b.vmath("MULTIPLY", q, (1.0, 1.0, 7.0)), 6.0, 3, 0.6)
                    pores = b.noise(q, 60.0, 2, 0.5)
                    h = b.math("ADD", b.math("MULTIPLY", wr, 1.0), b.math("MULTIPLY", pores, 0.25))
                    kit._finish(b, base, 0.7, kit._bump(b, h, 0.35, 0.01 * SCALE), spec=0.3,
                                extra={"Sheen Weight": 0.05})
                    sl.material = nm

    sky = dict(look["sky"])
    if not (a.procedural_sky or a.pass1 or HDRI is None):
        sky.update(hdri=kit.ASSET_LIB / HDRI, hdri_rotation=HDRI_ROT, hdri_strength=1.0)
    kit.setup_render(sc, cam_a, scale=SCALE, samples=a.samples, dof_target=taz[0] if taz else None, fstop=4.0,
                     sky=sky, **look["sun"], **look["grade"])

    # ---- dressed -----------------------------------------------------------------------
    if a.version == "dressed":
        t0 = time.time()
        props = kit._coll("kit_props")
        tex_roles = {}
        img_of = {}
        for ob in world:
            for s in ob.material_slots:
                if s.material:
                    orig = s.material.name.split(":", 1)[-1]
                    tex_roles[orig] = role_of(orig)
                    img_of[s.material.name] = game_image(s.material)[0]

        def slot_role(s):
            if not s.material:
                return "lit"
            return role_of(s.material.name.split(":", 1)[-1])

        # per-face roles for the kit's selectors
        for ob in world:
            for s in ob.material_slots:
                if s.material:
                    s.material["look"] = slot_role(s)

        slot_roles = {ob.name: [slot_role(s) for s in ob.material_slots] or ["lit"] for ob in world}

        def rail_polyline(ob, isl, ztop):
            """Top edge of a rail card island: mesh edges whose both ends lie on the
            card's top line (straight runs, L-corners and the moat ring alike)."""
            M = ob.matrix_world
            me = ob.data
            out = []
            for pi in isl:
                vs = list(me.polygons[pi].vertices)
                for i in range(len(vs)):
                    a_, b_ = M @ me.vertices[vs[i]].co, M @ me.vertices[vs[(i + 1) % len(vs)]].co
                    if a_.z > ztop - 0.05 and b_.z > ztop - 0.05 and (a_ - b_).length > 0.3:
                        out.append((a_, b_))
            return out

        def poly_mask(ob, wanted):
            rr = slot_roles[ob.name] + ["hidden"] * (len(ob.material_slots) - len(slot_roles[ob.name]))
            mi = np.zeros(len(ob.data.polygons), np.int32)
            ob.data.polygons.foreach_get("material_index", mi)
            return np.isin(np.array(rr, dtype=object)[np.clip(mi, 0, len(rr) - 1)].astype(str), list(wanted))

        def hide_faces(ob, mask):
            if not mask.any():
                return
            if "kit_hidden" not in [m.name for m in ob.data.materials if m]:
                ob.data.materials.append(hidden)
            hi = [m.name if m else "" for m in ob.data.materials].index("kit_hidden")
            mi = np.zeros(len(ob.data.polygons), np.int32)
            ob.data.polygons.foreach_get("material_index", mi)
            mi[mask] = hi
            ob.data.polygons.foreach_set("material_index", mi)
            counts["faces_hidden"] += int(mask.sum())

        live = [o for o in world if not o.hide_render]
        bpy.context.view_layer.update()

        # 1. trees: cluster trunk + canopy islands of tree textures -> kit tree in the footprint
        def named(ob, pats):
            hit = np.array([bool(s.material) and any(fnmatch.fnmatch(base_name(s.material.name.split(":", 1)[-1]), p) for p in pats)
                            for s in ob.material_slots] or [False])
            mi = np.zeros(len(ob.data.polygons), np.int32)
            ob.data.polygons.foreach_get("material_index", mi)
            return hit[np.clip(mi, 0, len(hit) - 1)]

        boxes, feet = [], []
        for ob in live:
            m = poly_mask(ob, ("tree",))
            if "trees" in L and named(ob, L["trees"][:1]).any():  # leaves shared with potted plants count only on a tree
                m = named(ob, L["trees"])
                ob["kit_replaced"] = True
            bark = m & named(ob, ("*/tazwood02a",))
            for isl, _, _ in kit.islands(ob, bark) if bark.any() else ():
                pts = [ob.matrix_world @ ob.data.vertices[v].co for p in isl for v in ob.data.polygons[p].vertices]
                low = min(p.z for p in pts)
                foot = [p for p in pts if p.z < low + 0.3]
                c = sum(foot, Vector()) / len(foot)
                r = max(math.hypot(p.x - c.x, p.y - c.y) for p in foot)
                tall = max(p.z for p in pts) - low > 2.5  # shorter islands are branches and the pond's logs
                if tall and r > 0.3 and not any(math.hypot(c.x - q.x, c.y - q.y) < 0.2 for q, _ in feet):  # close: a repeated capture
                    feet.append((c, r))
            if m.any():
                boxes += [(lo, hi) for _, lo, hi in kit.islands(ob, m)]
                hide_faces(ob, m)
        # one tree per game trunk, on it: railings are built around the trunks
        parts, rest = {}, []
        for b in boxes:
            c = (b[0] + b[1]) / 2
            k = min(range(len(feet)), key=lambda j: math.hypot(feet[j][0].x - c.x, feet[j][0].y - c.y), default=None)
            if k is not None and math.hypot(feet[k][0].x - c.x, feet[k][0].y - c.y) < 7:
                parts.setdefault(k, []).append(b)
            else:
                rest.append(b)
        planned = [((Vector(np.min([b[0] for b in bs], 0)), Vector(np.max([b[1] for b in bs], 0))), feet[k]) for k, bs in parts.items()]
        planned += [(bx, None) for bx in kit.merge_boxes(rest, pad=0.3) if bx[1].z - bx[0].z > 2.0]
        trees = [bx for bx, _ in planned]
        tri_props = 0
        for i, ((lo, hi), foot) in enumerate(planned):
            at, trunk_r = foot or (None, None)
            tr, can = kit.tree_from_bbox(lo, hi, SCALE, at=at, trunk_r=trunk_r, seed=i, name=f"kit_tree_{i:02d}", coll=props)
            tri_props += kit.tri_count(tr) + kit.tri_count(can)
        stats["trees"] = len(trees)

        # 2. fences: each rail card island -> its top edge polyline -> kit fence segments;
        #    posts and caps standing on those lines are hidden
        segs = []
        for ob in live:
            m = poly_mask(ob, ("fence_rail",))
            if not m.any():
                continue
            M = ob.matrix_world
            for isl, lo, hi in kit.islands(ob, m):
                segs += rail_polyline(ob, isl, hi.z)
            hide_faces(ob, m)
        uniq = {}  # captures repeat cards (hero + sweep copies): dedupe by rounded ends
        for p0, p1 in segs:
            k = tuple(sorted([(round(p0.x, 1), round(p0.y, 1)), (round(p1.x, 1), round(p1.y, 1))]))
            uniq[k] = (p0, p1)
        nonground = ("fence_rail", "fence_post", "fence_cap", "tree", "hide", "sky", "hidden")
        blk = [o for o in live if not poly_mask(o, nonground).all()]
        verts, polys, off = [], [], 0
        for o in blk:
            co, tv, tp = kit._world_tris(o)
            keep = ~poly_mask(o, nonground)[tp]
            verts.append(co); polys.append(tv[keep] + off); off += len(co)
        from mathutils.bvhtree import BVHTree
        ground_bvh = BVHTree.FromPolygons(np.concatenate(verts).tolist(), np.concatenate(polys).tolist())

        def ground_z(p):
            hit = ground_bvh.ray_cast(Vector((p.x, p.y, p.z + 0.01)), Vector((0, 0, -1)), 4.0)
            return hit[0].z if hit[0] is not None else p.z - 1.0

        fences = []
        for i, (p0, p1) in enumerate(uniq.values()):
            # level fence hung from the game's rail line; posts sink to the lowest ground
            g0, g1 = ground_z(p0), ground_z(p1)
            top = (p0.z + p1.z) / 2
            h = min(max(top - max(g0, g1), 0.7 * SCALE), 1.15 * SCALE)
            base = top - h
            f = kit.fence((p0.x, p0.y, base), (p1.x, p1.y, base), SCALE, height=h / SCALE,
                          sink=max(0.0, base - min(g0, g1)) + 0.1 * SCALE, name=f"kit_fence_{i:02d}", coll=props)
            fences.append(f)
            tri_props += kit.tri_count(f)
        stats["fence_segments"] = len(fences)
        # hide game posts/caps near any rail line
        lines = np.array([[p0.x, p0.y, p1.x, p1.y] for p0, p1 in uniq.values()])
        for ob in live:
            m = poly_mask(ob, ("fence_post", "fence_cap"))
            if not m.any():
                continue
            hm = np.zeros(len(m), bool)
            for isl, lo, hi in kit.islands(ob, m):
                c = (lo + hi) / 2
                seg = np.stack([lines[:, :2], lines[:, 2:]], 1)
                seg3 = np.concatenate([seg, np.zeros((len(seg), 2, 1))], 2)
                if kit.dist_to_segments(np.array([[c.x, c.y, 0]]), seg3)[0] < 0.4:
                    hm[isl] = True
            hide_faces(ob, hm)
        # drips and the blob shadow
        for ob in live:
            hide_faces(ob, poly_mask(ob, ("hide",)))

        # 3. materials by role
        cliff_means = []
        for ob in live:
            if poly_mask(ob, ("cliff", "cliff_lilac", "brick")).any():
                kit.prepare_cliffs([ob])
            for s in ob.material_slots:
                m = s.material
                if not m or m.name == "kit_hidden":
                    continue
                r = slot_roles[ob.name][s.slot_index] if hasattr(s, "slot_index") else slot_role(s)
                img = img_of.get(m.name)
                tint = kit.REF.get("cliff")
                if r == "ground" and img is not None:
                    s.material = kit.mat_ground_masked(img, SCALE)
                elif r == "lawn":
                    s.material = kit.material("lawn", None, SCALE)
                elif r in ("cliff", "cliff_lilac"):
                    mean = None
                    if img is not None:
                        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
                        img.pixels.foreach_get(px)
                        px = px.reshape(-1, 4)
                        mean = tuple(px[px[:, 3] > 0.5, :3].mean(0)) if (px[:, 3] > 0.5).any() else None
                    if mean is not None:
                        cliff_means.append(mean)
                    if img is not None and mean is not None:
                        s.material = kit.mat_cliff_overlay(img, mean, SCALE, mean, 0.25, drips=a.pass1)
                    else:
                        s.material = kit.material("cliff", mean, SCALE, 0.25)
                elif r == "brick" and img is not None:
                    s.material = kit.mat_brick_masked(img, SCALE)
                elif r == "water":
                    s.material = kit.material("water", None, SCALE) if a.pass1 else kit.mat_water_clear(SCALE)
                elif r == "lit" and not a.pass1 and "src" in m and m["src"] in bpy.data.materials:
                    s.material = lit_material(bpy.data.materials[m["src"]], stylized=True)
                s.material["look"] = r

        # 3b. overlay rock scenery on the cliff slabs (rule: every cliff-role vertical panel)
        overlay = None
        mass_edges = []
        if not a.pass1:
            # 3b. replace the cliffs: rock masses grown from the game's cliff volumes
            cliffs_o = [o for o in live if poly_mask(o, ("cliff",)).any()]
            lawn_o = [o for o in live if poly_mask(o, ("lawn",)).any()]
            ground_o = [o for o in live if not poly_mask(o, nonground).all() and o not in cliffs_o]
            rmat = kit.mat_sandstone(kit.srgb("#d98e62"), SCALE, 0.7, drips=False, base_dark=False)
            rmat.name = "kit_sandstone_mass"
            t_m = time.time()
            rock, rubble, mass_edges, covered = (kit.cliff_masses(cliffs_o, lawn_o, ground_o, SCALE, seed=9, coll=props,
                                                                  mat=rmat, rubble_mat=kit.mat_boulder_dry(SCALE),
                                                                  **look["cliff"]) if cliffs_o else (None, None, [], None))
            if rock:
                overlay = rock
                stats["cliff_mass_tris"] = kit.tri_count(rock)
                stats["cliff_mass_seconds"] = round(time.time() - t_m, 1)
                tri_props += kit.tri_count(rock)
                if rubble:
                    stats["rubble"] = rubble["kit_count"]
                    tri_props += kit.tri_count(rubble)
                # hide the game's cliff faces now inside the rock
                for ob in cliffs_o:
                    m = poly_mask(ob, ("cliff",))
                    cen = np.array([tuple(ob.matrix_world @ p_.center) for p_ in ob.data.polygons])
                    hide_faces(ob, m & covered(cen))

        # 3c. water: a bed and walls under the hub's water so it can be see-through, and a foam rim
        if not a.pass1:
            bed, foam = kit.water_dress([o for o in live if poly_mask(o, ("water",)).any()],
                                        lambda o: poly_mask(o, ("water",)), SCALE, depth=0.7,
                                        region=L["hub"], coll=props)
            if bed:
                stats["water_bed_tris"] = kit.tri_count(bed) + kit.tri_count(foam)
                tri_props += stats["water_bed_tris"]

        # 3d. characters (not collision): smooth shading, fur and skin materials
        if not a.pass1 and L.get("dress_characters"):
            dress_characters()

        # 4. scatter
        gameplay_boxes = []
        for ob in live if L.get("clear_islands") else live + chars:  # there, characters walk and props share objects with scenery
            if ob in chars or poly_mask(ob, ("gameplay",)).all():
                lo, hi = kit.world_bbox(ob)
                gameplay_boxes.append((lo, hi))
            elif L.get("clear_islands") and poly_mask(ob, ("gameplay",)).any():
                gameplay_boxes += [(lo, hi) for _, lo, hi in kit.islands(ob, poly_mask(ob, ("gameplay",)))]
        hub = L["hub"]
        masks = {}

        def gmask(img):
            if img.name not in masks:
                masks[img.name] = kit.image_sampler(img, kit.green_fraction, blur=3)
            return masks[img.name]

        def ground_info(density, seed, sel=("ground",)):
            r = kit.sample_surface_ex(live, lambda o: poly_mask(o, sel) & _up(o, 0.5), density, seed, hub)
            g = np.zeros(len(r["P"]))
            for oi in np.unique(r["ob"]):
                ob = live[oi]
                k = r["ob"] == oi
                mi = np.array([ob.data.polygons[pp].material_index for pp in r["poly"][k]])
                for m_i in np.unique(mi):
                    mat = ob.data.materials[m_i]
                    img = None
                    for n in (mat.node_tree.nodes if mat and mat.node_tree else []):
                        if n.type == "TEX_IMAGE" and n.image and "upscaled" in n.image.filepath:
                            img = n.image  # the game's own texture (not a kit/asset map)
                    if img is None:
                        continue
                    kk = np.where(k)[0][mi == m_i]
                    g[kk] = gmask(img)(r["UV"][kk])
            return r, g

        def _up(o, t):
            me = o.data
            n = np.empty(len(me.polygons) * 3, np.float32)
            me.polygons.foreach_get("normal", n)
            nz = (n.reshape(-1, 3) @ np.array(o.matrix_world)[:3, :3].T)
            nz = nz[:, 2] / np.maximum(np.linalg.norm(nz, axis=1), 1e-9)
            return nz > t

        dens = 95.0 / SCALE ** 2
        rng = np.random.default_rng(7)
        lawn = kit.sample_surface_ex(live, lambda o: poly_mask(o, ("lawn",)) & _up(o, 0.35), dens, 11, hub)
        gr, gg = ground_info(dens, 12)
        keep = rng.random(len(gg)) < np.clip(gg * 1.15, 0, 1) ** 1.3
        print("ZOOHUB points: lawn", len(lawn["P"]), "ground", len(gr["P"]), "ground kept", int(keep.sum()),
              "gameplay boxes", len(gameplay_boxes))
        P = np.concatenate([lawn["P"], gr["P"][keep]])
        N = np.concatenate([lawn["N"], gr["N"][keep]])
        hm = np.concatenate([np.ones(len(lawn["P"])), 0.45 + 0.55 * gg[keep]])
        covers = [o for o in live if poly_mask(o, ("water", "brick", "cliff", "cliff_lilac", "gameplay", "lit")).any()]
        if overlay:
            covers.append(overlay)
        grass = kit.scatter_grass(live, SCALE, points=(P, N, hm), blockers=None if L.get("clear_islands") else covers, exclude=gameplay_boxes, seed=3,
                                  **L.get("grass_opts", {}))

        def clutter_sampler(density, seed):
            r, g = ground_info(density, seed)
            return r["P"][g < 0.05]
        leaf_centers = [((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, max(1.5, min(hi.x - lo.x, hi.y - lo.y) * 0.45)) for lo, hi in trees]
        clutter = kit.scatter_clutter(live, SCALE, sampler=clutter_sampler, blockers=covers, exclude=gameplay_boxes, seed=4,
                                      leaves=2.5 if not a.pass1 else 5.0, leaf_centers=None if a.pass1 else leaf_centers) if L.get("clutter", True) else []
        cliffs = [o for o in live if poly_mask(o, ("cliff", "cliff_lilac")).any()]
        solid = [o for o in live if not poly_mask(o, ("hide", "sky", "fence_rail", "tree")).all()]
        edges = kit.top_edges_open(cliffs, ("cliff", "cliff_lilac"), blockers=solid) if cliffs else []
        if overlay:  # vines hang from the rock mass rim (also where tops border grass objects)
            edges = mass_edges
        vines = [v for v in (kit.scatter_vines(edges, SCALE, seed=5, per_m=3.0 if overlay else 5.0),
                             kit.scatter_ledge_moss(edges, SCALE, seed=6)) if v] if edges else []
        scat = grass + clutter + vines
        stats["scatter"] = {o.name: (o["kit_instances"], o["kit_tris"]) for o in scat}
        stats["instances"] = sum(o["kit_instances"] for o in scat)
        stats["scatter_tris"] = sum(o["kit_tris"] for o in scat)
        if stats["scatter_tris"] > MAX_SCATTER_TRIS:
            raise RuntimeError(f"{stats['scatter_tris']:,} scatter triangles, limit {MAX_SCATTER_TRIS:,}: lower this level's density")
        stats["prop_tris"] = tri_props
        stats["top_edges"] = len(edges)
        stats["dress_seconds"] = round(time.time() - t0, 1)
        # what camera B sees: instances whose point projects inside B's frame (no occlusion test)
        from bpy_extras.object_utils import world_to_camera_view
        sc.render.resolution_x, sc.render.resolution_y, sc.render.pixel_aspect_x = 1920, 1080, 1.0
        seen_i = seen_t = 0
        for o in scat:
            me = o.data
            pts = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", pts)
            pts = pts.reshape(-1, 3)
            M = np.array(cam_b.matrix_world.inverted())
            pc = pts @ M[:3, :3].T + M[:3, 3]
            z = -pc[:, 2]
            fx = cdb.lens / cdb.sensor_width * 2
            x = pc[:, 0] / np.maximum(z, 1e-6) * fx
            y = pc[:, 1] / np.maximum(z, 1e-6) * fx * 1920 / 1080
            vis = (z > 0) & (np.abs(x) < 1.05) & (np.abs(y) < 1.05)
            seen_i += int(vis.sum())
            seen_t += int(o["kit_tris"] * vis.mean()) if len(vis) else 0
        stats["camera_B_instances"], stats["camera_B_tris_est"] = seen_i, seen_t
        stats.update(counts)

    tag = a.version
    for c in a.camera:
        move_chars(c)
        frame(c)
        stats[f"render_{c}"] = render(out / f"final-{c}-{tag}.jpg")
    move_chars("A")
    sc.camera = cam_a
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{a.level}-{tag}.blend"))
    print("ZOOHUB", stats)


# =================================================================== composition (plain python + PIL)
def compose(sub="pass2"):
    from PIL import Image
    base = Path(__file__).resolve()
    for p in base.parents:
        if (p / "extracted").is_dir():
            base = p / "extracted" / "look"
            break
    out = base / sub if sub else base

    def strip(paths, h, dst):
        ims = []
        for p in paths:
            if not Path(p).exists():
                return
            im = Image.open(p).convert("RGB")
            ims.append(im.resize((round(im.width * h / im.height), h), Image.LANCZOS))
        gap = 12
        s_ = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), h), (16, 16, 16))
        x = 0
        for i in ims:
            s_.paste(i, (x, 0))
            x += i.width + gap
        s_.save(dst, quality=92)

    Image.open(base / "hero-hd.png").convert("RGB").save(out / "final-A-game.jpg", quality=93)
    a_lit = out / "final-A-lit.jpg"
    strip([out / "final-A-game.jpg"] + ([a_lit] if a_lit.exists() else []) + [out / "final-A-dressed.jpg"], 800, out / "final-A-strip.jpg")
    strip([out / "final-B-game.jpg", out / "final-B-lit.jpg", out / "final-B-dressed.jpg"], 720, out / "final-B-strip.jpg")
    strip([out / "final-C-game.jpg", out / "final-C-dressed.jpg"], 720, out / "final-C-strip.jpg")
    strip([out / "final-B-dressed.jpg", base / "target.jpg"], 1080, out / "final-B-vs-target.jpg")
    if sub == "pass2":
        strip([base / "final-B-dressed.jpg", out / "final-B-dressed.jpg"], 1080, out / "final-B-pass1-vs-pass2.jpg")
    elif sub == "pass3":
        for c, h in (("B", 1080), ("A", 900)):
            strip([base / "pass2" / f"final-{c}-dressed.jpg", out / f"final-{c}-dressed.jpg"], h, out / f"final-{c}-pass2-vs-pass3.jpg")
    print("composed", out)


if __name__ == "__main__":
    if "bpy" in sys.modules or any(a.endswith("blender") for a in sys.argv[:1]):
        blender_main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    elif len(sys.argv) > 1 and sys.argv[1] == "compose":
        compose(sys.argv[2] if len(sys.argv) > 2 else "pass2")
