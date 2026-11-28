# Blender: rebuilds a scene from DLL world captures (taz-hd\world-NNN.bin, see capture.c) as a .blend.
# usage: blender -b -P tools/worldview.py -- <out.blend> <hero.bin> [sweep.bin...]
# The first capture's first frame is the hero frame: its draws go in the "hero" collections and its
# camera becomes the scene camera; later frames and files add "sweep" collections with what else was
# seen. One object per texture for world-space draws, one per world matrix for separately placed
# objects, characters posed on the CPU from their bone constants. Materials draw it as the game does
# (texture x vertex colour by the stage ops, alpha test/blend, vertex fog) with raw sRGB values, so
# the scene renders with the Raw view transform; textures are the HD ones from extracted/upscaled.
# Space: game x, y (up), z (forward), left-handed -> Blender x, z, y; 1 Blender unit = 250 game units.
import bpy, struct, sys, os, math, hashlib, collections
from mathutils import Matrix, Vector

SCALE = 1 / 250
args = sys.argv[sys.argv.index('--') + 1:]
out, caps = args[0], args[1:]
here = os.path.dirname(os.path.abspath(__file__))
ext = os.path.join(here, '..', 'extracted')
if not os.path.isdir(os.path.join(ext, 'textures')):  # a worktree: use the main checkout's extracted data
    ext = os.path.join(here, '..', '..', '..', '..', 'extracted')
PAK = os.environ.get('WORLD_PAK', 'zoohub')  # the scene's own pak: textures shared with other paks are named after their copy here
files, occurs = {}, collections.defaultdict(list)
for line in open(os.path.join(ext, 'textures', 'fingerprints.tsv')):
    h, n = line.rstrip('\n').split('\t')[:2]
    files.setdefault(int(h, 16), n)
for line in list(open(os.path.join(ext, 'textures', 'index.tsv')))[1:]:
    pak, name, w, h, f = line.rstrip('\n').split('\t')
    occurs[f].append(pak + '/' + os.path.splitext(name)[0])
def label(f):
    o = occurs.get(f, [f[:-4]])
    return next((n for n in o if n.startswith(PAK + '/')), next((n for n in o if n.startswith(PAK)), o[0]))
names = {h: label(f) for h, f in files.items()}

# Direct3D 8 constants used below.
RS = dict(ZWRITE=14, ATEST=15, SRC=19, DST=20, CULL=22, ZFUNC=23, AREF=24, AFUNC=25, BLEND=27, FOG=28, FOGCOLOR=34,
          FOGSTART=36, FOGEND=37, TFACTOR=60)
COLOROP, CARG1, CARG2, ALPHAOP, AARG1, AARG2, ADDRU, ADDRV, MAGF, TTF = 1, 2, 3, 4, 5, 6, 13, 14, 16, 24


def is_vs(d): return d['shader'] & 0x80000000  # otherwise an FVF code


def load(path):
    b = open(path, 'rb').read()
    _, nrs, ntss = struct.unpack_from('<3I', b, 0)
    o = 12
    rs = struct.unpack_from('<%dI' % nrs, b, o); o += 4 * nrs
    tss = struct.unpack_from('<%dI' % ntss, b, o); o += 4 * ntss
    draws = []
    while o < len(b):
        m, = struct.unpack_from('<I', b, o)
        if m == ord('F'):
            o += 12
            continue
        d = dict(zip('magic frame api type count shader stride nverts nidx vb first bound'.split(), struct.unpack_from('<12I', b, o)))
        q = o + 48
        d['tex'] = struct.unpack_from('<2Q', b, q); q += 16
        mats = struct.unpack_from('<80f', b, q); q += 320
        d['world'], d['view'], d['proj'], d['t0'], d['t1'] = [mats[i * 16:i * 16 + 16] for i in range(5)]
        d['size'] = struct.unpack_from('<2I', b, q + 8); q += 24  # viewport x, y, w, h, min z, max z
        d['rs'] = dict(zip(rs, struct.unpack_from('<%dI' % nrs, b, q))); q += 4 * nrs
        d['tss'] = [dict(zip(tss, struct.unpack_from('<%dI' % ntss, b, q + 4 * ntss * s))) for s in range(3)]; q += 12 * ntss
        if is_vs(d):
            d['c'] = struct.unpack_from('<384f', b, q); q += 1536
        d['verts'] = b[q:q + d['nverts'] * d['stride']]; q += d['nverts'] * d['stride']
        d['idx'] = struct.unpack_from('<%dI' % d['nidx'], b, q) if d['nidx'] else None; q += 4 * d['nidx']
        draws.append(d)
        o = q
    return draws


def f32(u): return struct.unpack('<f', struct.pack('<I', u))[0]
def rgba(u): return ((u >> 16 & 255) / 255, (u >> 8 & 255) / 255, (u & 255) / 255, (u >> 24) / 255)
def identity(m): return all(abs(m[i] - (i % 5 == 0)) < 1e-6 for i in range(16))
def game_point(x, y, z): return Vector((x * SCALE, z * SCALE, y * SCALE))

S = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
def game_matrix(m):  # row-vector game matrix -> Blender matrix_world (axes swapped, translation scaled)
    b = S @ Matrix([m[0:4], m[4:8], m[8:12], m[12:16]]).transposed() @ S
    b.translation *= SCALE
    return b


def triangles(d):
    t, n = d['type'], d['count']
    if t == 4: tri = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(n)]
    elif t == 5: tri = [(i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2) for i in range(n)]
    elif t == 6: tri = [(0, i + 1, i + 2) for i in range(n)]
    else: return []
    return [tuple(d['idx'][k] for k in f) for f in tri] if d['idx'] else tri


def skin(d):  # 52-byte character vertices posed by their bone rows (c[reg..reg+2]), then placed in the world
    c, out = d['c'], []
    wvp = Matrix([c[92 * 4 + r * 4:92 * 4 + r * 4 + 4] for r in range(4)])  # c92-c95: (world x view x projection), transposed
    place = camera_vp.inverted() @ wvp
    for k in range(d['nverts']):
        v = struct.unpack_from('<3f3f4B3fI2f', d['verts'], k * 52)
        p, n = [0.0] * 3, [0.0] * 3
        for s in range(3):
            w, r = v[3 + s], v[6 + s]
            if w <= 0: continue
            for a in range(3):
                row = c[(r + a) * 4:(r + a) * 4 + 4]
                p[a] += w * (row[0] * v[0] + row[1] * v[1] + row[2] * v[2] + row[3])
                n[a] += w * (row[0] * v[10] + row[1] * v[11] + row[2] * v[12])
        out.append((tuple(place @ Vector(p)), tuple(place.to_3x3() @ Vector(n)), v[13], v[14], v[15]))
    return out


def vertices(d):  # (position, normal, colour, u, v) in the draw's own space
    if d['stride'] == 52: return skin(d)
    out = []
    for k in range(d['nverts']):
        x, y, z, nx, ny, nz, col, u, v = struct.unpack_from('<6fI2f', d['verts'], k * 36)
        if d['tss'][0][TTF] == 2:  # texture transform (scrolling textures): bake into the UVs
            m = d['t0']
            u, v = u * m[0] + v * m[4] + m[8], u * m[1] + v * m[5] + m[9]
        out.append(((x, y, z), (nx, ny, nz), col, u, v))
    return out


# --- which draws to build -------------------------------------------------------------------------
frames = [load(p) for p in caps]
hero = [d for d in frames[0] if d['frame'] == 1]
persp = [d for d in hero if not is_vs(d) and d['proj'][11] == 1]  # a screen full of text can outnumber the 3D draws
cam = collections.Counter(tuple(d['view']) + tuple(d['proj']) for d in (persp or [d for d in hero if not is_vs(d)])).most_common(1)[0][0]
view, proj = cam[:16], cam[16:]
camera_vp = (Matrix([view[0:4], view[4:8], view[8:12], view[12:16]]) @ Matrix([proj[0:4], proj[4:8], proj[8:12], proj[12:16]])).transposed()
skipped = collections.Counter()

def same_camera(d): return abs(d['proj'][0] - proj[0]) < 1e-3 and abs(d['proj'][5] - proj[5]) < 1e-3

def key(d): return (hashlib.md5(d['verts']).digest(), d['tex'], tuple(round(x, 1) for x in d['world']), d['rs'][RS['BLEND']])

chosen, seen = [], set()
# Characters: the lit and plain passes (the outline pass left out). A model the mod
# replaces has its game batches captured but not drawn; its indexed replacement follows them.
replaced = {hero[i - 1]['vb'] for i in range(1, len(hero)) if hero[i]['api'] == 1 and is_vs(hero[i]) and hero[i - 1]['api'] == 0}
for d in hero:
    vs = is_vs(d)
    if not same_camera(d) and not vs: skipped['other camera (screen-space)'] += 1; continue
    if vs and d['rs'][RS['CULL']] == 2: skipped['character outline pass'] += 1; continue
    if vs and d['api'] == 0 and d['vb'] in replaced: skipped['character batch replaced by HD model'] += 1; continue
    if d['type'] not in (4, 5, 6): skipped['points/lines'] += 1; continue
    d['set'] = 'characters' if vs else 'hero'
    chosen.append(d)
    seen.add(key(d))
# Sweep: things the camera turn saw. Vertex sets seen in 20+ frames of a capture move every frame
# (insects, leaves, fish): only their hero-frame copies are kept.
for draws in [frames[0][len(hero):]] + frames[1:]:
    perframe = collections.defaultdict(set)
    for d in draws: perframe[hashlib.md5(d['verts']).digest()].add(d['frame'])
    for d in draws:
        if is_vs(d) or d['type'] not in (4, 5, 6): continue
        if not same_camera(d): skipped['other camera (screen-space)'] += 1; continue
        if len(perframe[hashlib.md5(d['verts']).digest()]) >= 20: skipped['moving every frame (sweep copies)'] += 1; continue
        k = key(d)
        if k in seen: continue
        seen.add(k)
        d['set'] = 'sweep'
        chosen.append(d)

# --- materials ----------------------------------------------------------------------------------
images = {}
def texname(h, bound): return names.get(h, '%016x' % h) if bound else 'untextured'

def image(h):
    if h not in images:
        n = files.get(h)
        path = next((p for p in (os.path.join(ext, 'upscaled', n or '-'), os.path.join(ext, 'textures', n or '-')) if os.path.isfile(p)), None)
        img = bpy.data.images.load(path, check_existing=True) if path else None
        if img: img.colorspace_settings.name = 'Non-Color'  # the game multiplies sRGB values as they are
        images[h] = img
    return images[h]

def matkey(d):
    t0, t1 = d['tss'][0], d['tss'][1]
    st = lambda t: tuple(t[k] for k in (COLOROP, CARG1, CARG2, ALPHAOP, AARG1, AARG2))
    r = d['rs']
    return (d['tex'][0], d['bound'] & 1, st(t0), st(t1) if t1[COLOROP] != 1 else (), r[RS['TFACTOR']] if t1[COLOROP] != 1 else 0,
            r[RS['BLEND']], r[RS['SRC']], r[RS['DST']], r[RS['ATEST']], r[RS['AREF']], r[RS['AFUNC']], r[RS['ZWRITE']], r[RS['ZFUNC']],
            t0[ADDRU], t0[ADDRV], t0[MAGF], r[RS['FOG']], r[RS['FOGCOLOR']], r[RS['FOGSTART']], r[RS['FOGEND']], d['stride'])

materials, variants = {}, collections.defaultdict(int)
def material(d):
    k = matkey(d)
    if k in materials: return materials[k]
    base = texname(d['tex'][0], d['bound'] & 1)
    variants[base] += 1
    m = bpy.data.materials.new(base if variants[base] == 1 else '%s~%d' % (base, variants[base]))
    materials[k] = m
    r, t = d['rs'], d['tss']
    blend, atest = r[RS['BLEND']], r[RS['ATEST']]
    for name, v in (('fingerprint', '%016x' % d['tex'][0]), ('alpha_blend', blend), ('src_blend', r[RS['SRC']]), ('dest_blend', r[RS['DST']]),
                    ('alpha_test', atest), ('alpha_ref', r[RS['AREF']]), ('alpha_func', r[RS['AFUNC']]), ('z_write', r[RS['ZWRITE']]),
                    ('z_func', r[RS['ZFUNC']]), ('cull', r[RS['CULL']]), ('fog', r[RS['FOG']]), ('texture_factor', '%08x' % r[RS['TFACTOR']]),
                    ('stage0', '%d %d %d / %d %d %d' % k[2]), ('stage1', '%d %d %d / %d %d %d' % k[3] if k[3] else 'off'),
                    ('address_uv', '%d %d' % (t[0][ADDRU], t[0][ADDRV])), ('character', d['stride'] == 52)):
        m[name] = v
    m.use_backface_culling = False
    nt = m.node_tree if m.node_tree else None
    if nt is None:
        m.use_nodes = True
        nt = m.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    vc = N('ShaderNodeVertexColor'); vc.layer_name = 'game_color'
    tex = None
    if d['bound'] & 1 and image(d['tex'][0]):
        tex = N('ShaderNodeTexImage'); tex.image = image(d['tex'][0])
        tex.interpolation = 'Closest' if t[0][MAGF] == 1 else 'Linear'
        tex.extension = 'EXTEND' if t[0][ADDRU] == 3 and t[0][ADDRV] == 3 else 'REPEAT'
    elif d['bound'] & 1:
        m['missing_texture'] = True
    tf = rgba(r[RS['TFACTOR']])

    def const(c):
        n = N('ShaderNodeRGB'); n.outputs[0].default_value = (c[0], c[1], c[2], 1)
        a = N('ShaderNodeValue'); a.outputs[0].default_value = c[3]
        return n.outputs[0], a.outputs[0]
    white = None
    def arg(a, cur):
        nonlocal white
        a &= 15
        if a == 0 or (a == 1 and cur is None): return vc.outputs['Color'], vc.outputs['Alpha']
        if a == 1: return cur
        if a == 2:
            if tex and cur is None: return tex.outputs['Color'], tex.outputs['Alpha']
            if cur is not None: m['stage1_texture_ignored'] = True  # only characters' cel ramp, looked up by N.L in their shader
            white = white or const((1, 1, 1, 1))  # no texture: Direct3D reads white
            return white
        if a == 3: return const(tf)
        return vc.outputs['Color'], vc.outputs['Alpha']
    def mul(x, y, times, alpha):
        if alpha:
            n = N('ShaderNodeMath'); n.operation = 'MULTIPLY'; n.use_clamp = True
            L(x, n.inputs[0]); L(y, n.inputs[1]); out = n.outputs[0]
            if times > 1:
                s = N('ShaderNodeMath'); s.operation = 'MULTIPLY'; s.use_clamp = True
                L(out, s.inputs[0]); s.inputs[1].default_value = times; out = s.outputs[0]
            return out
        n = N('ShaderNodeMix'); n.data_type = 'RGBA'; n.blend_type = 'MULTIPLY'; n.clamp_result = True
        n.inputs['Factor'].default_value = 1
        L(x, n.inputs['A']); L(y, n.inputs['B']); out = n.outputs['Result']
        for _ in range({1: 0, 2: 1, 4: 2}[times]):
            a2 = N('ShaderNodeMix'); a2.data_type = 'RGBA'; a2.blend_type = 'ADD'; a2.clamp_result = True
            a2.inputs['Factor'].default_value = 1
            L(out, a2.inputs['A']); L(out, a2.inputs['B']); out = a2.outputs['Result']
        return out
    def op(o, a1, a2, alpha, cur):
        x, y = arg(a1, cur), arg(a2, cur)
        x, y = (x[1], y[1]) if alpha else (x[0], y[0])
        if o == 1: return (cur[1] if alpha else cur[0]) if cur else arg(0, None)[alpha]
        if o == 2: return x
        if o == 3: return y
        if o in (4, 5, 6): return mul(x, y, {4: 1, 5: 2, 6: 4}[o], alpha)
        m['unhandled_op'] = o
        return mul(x, y, 1, alpha)
    cur = None
    for s in (0, 1):
        ts = t[s]
        if ts[COLOROP] == 1: break
        cur = (op(ts[COLOROP], ts[CARG1], ts[CARG2], False, cur), op(ts[ALPHAOP], ts[AARG1], ts[AARG2], True, cur))
    color, alpha = cur if cur else arg(0, None)
    if r[RS['FOG']]:  # linear vertex fog on view depth: f = (end - z) / (end - start)
        cd = N('ShaderNodeCameraData')
        fz = N('ShaderNodeMapRange'); fz.clamp = True
        L(cd.outputs['View Z Depth'], fz.inputs['Value'])
        fz.inputs['From Min'].default_value = f32(r[RS['FOGSTART']]) * SCALE
        fz.inputs['From Max'].default_value = f32(r[RS['FOGEND']]) * SCALE
        mix = N('ShaderNodeMix'); mix.data_type = 'RGBA'
        L(fz.outputs['Result'], mix.inputs['Factor']); L(color, mix.inputs['A'])
        mix.inputs['B'].default_value = rgba(r[RS['FOGCOLOR']])[:3] + (1,)
        color = mix.outputs['Result']
    if atest:  # passes where alpha > ref (func 5 GREATER; 7 GREATEREQUAL treated alike)
        g = N('ShaderNodeMath'); g.operation = 'GREATER_THAN'
        L(alpha, g.inputs[0]); g.inputs[1].default_value = r[RS['AREF']] / 255 - (1e-4 if r[RS['AFUNC']] == 7 else 0)
        if blend:
            a3 = N('ShaderNodeMath'); a3.operation = 'MULTIPLY'; L(alpha, a3.inputs[0]); L(g.outputs[0], a3.inputs[1]); alpha = a3.outputs[0]
        else:
            alpha = g.outputs[0]
    em = N('ShaderNodeEmission'); L(color, em.inputs['Color'])
    outn = N('ShaderNodeOutputMaterial')
    if blend and r[RS['SRC']] == 1 and r[RS['DST']] == 4:  # ZERO, INVSRCCOLOR: darkens what is behind by the colour
        inv = N('ShaderNodeInvert'); L(color, inv.inputs['Color'])
        tr = N('ShaderNodeBsdfTransparent'); L(inv.outputs[0], tr.inputs['Color'])
        L(tr.outputs[0], outn.inputs['Surface'])
    elif blend or atest:
        tr = N('ShaderNodeBsdfTransparent')
        mx = N('ShaderNodeMixShader'); L(alpha, mx.inputs[0]); L(tr.outputs[0], mx.inputs[1]); L(em.outputs[0], mx.inputs[2])
        L(mx.outputs[0], outn.inputs['Surface'])
        if blend and r[RS['SRC']] != 5 or blend and r[RS['DST']] != 6: m['approximate_blend'] = True
    else:
        L(em.outputs[0], outn.inputs['Surface'])
    m.surface_render_method = 'BLENDED' if blend else 'DITHERED'
    return m


# --- objects ------------------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
cols = {}
def collection(name):
    if name not in cols:
        c = bpy.data.collections.new(name); sc.collection.children.link(c); cols[name] = c
    return cols[name]

groups = collections.OrderedDict()
for d in chosen:
    placed = d['stride'] != 52 and not identity(d['world'])
    sub = d['set'] + (' placed' if placed else '')
    g = (sub, tuple(round(x, 4) for x in d['world'])) if placed else (sub, texname(d['tex'][0], d['bound'] & 1))
    groups.setdefault(g, []).append(d)

flipped = total = 0
stats = collections.Counter()
for (sub, ident), ds in groups.items():
    placed = sub.endswith('placed')
    verts, vindex, faces, corners, mats, mlist = [], {}, [], [], [], []
    for d in ds:
        m = material(d)
        if m not in mlist: mlist.append(m)
        V = vertices(d)
        conv = [(game_point(*p), Vector((n[0], n[2], n[1])), c, u, v) for p, n, c, u, v in V]
        for f in triangles(d):
            if max(f) >= len(conv): continue
            a, b, c = (conv[k] for k in f)
            fn = (b[0] - a[0]).cross(c[0] - a[0])
            if fn.length < 1e-9: continue
            total += 1
            # No culling anywhere (cull NONE), so face the side the game's normals point to.
            if fn.dot(a[1] + b[1] + c[1]) < 0: f, flipped = f[::-1], flipped + 1
            face = []
            for k in f:
                p = conv[k][0].freeze()
                pk = (round(p.x, 5), round(p.y, 5), round(p.z, 5))
                if pk not in vindex: vindex[pk] = len(verts); verts.append(p)
                face.append(vindex[pk])
                corners.append(conv[k][1:])
            if len(set(face)) < 3:
                del corners[-3:]
                continue
            faces.append(face)
            mats.append(mlist.index(m))
            stats[(m.name, d['set'])] += 1
    if not faces: continue
    name = mlist[0].name if not placed else mlist[0].name + '@placed'
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    uv = me.uv_layers.new(name='UVMap')
    col = me.color_attributes.new('game_color', 'FLOAT_COLOR', 'CORNER')  # raw bytes / 255, not linearised
    for i, (n, c, u, v) in enumerate(corners):
        uv.data[i].uv = (u, 1 - v)
        col.data[i].color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255, (c >> 24) / 255)
    for m in mlist: me.materials.append(m)
    for p, mi in zip(me.polygons, mats): p.material_index = mi
    me.normals_split_custom_set([tuple(n.normalized()) if n.length > 1e-6 else (0, 0, 1) for n, c, u, v in corners])
    ob = bpy.data.objects.new(name, me)
    if placed:
        ob.matrix_world = game_matrix(ds[0]['world'])
    ob['draws'] = len(ds)
    ob['triangles'] = len(faces)
    ob['textures'] = ', '.join(sorted({texname(d['tex'][0], d['bound'] & 1) for d in ds}))
    ob['game_world_matrix'] = list(ds[0]['world']) if placed else []
    collection(sub).objects.link(ob)

# --- camera and render settings --------------------------------------------------------------------
V = Matrix([view[0:4], view[4:8], view[8:12], view[12:16]]).transposed()  # column form, world -> camera
C = V.inverted()
F = Matrix.Diagonal((1, 1, -1, 1))
bm = S @ C @ F
bm.translation = game_point(*C.translation)
cd = bpy.data.cameras.new('hero')
cam = bpy.data.objects.new('hero camera', cd)
cam.matrix_world = bm
W, H = hero[0]['size']
sc.collection.objects.link(cam)
sc.camera = cam
cd.sensor_fit = 'HORIZONTAL'
cd.angle = 2 * math.atan(1 / proj[0])
near = -proj[14] / proj[10]
cd.clip_start, cd.clip_end = near * SCALE, (near * proj[10] / (proj[10] - 1) if proj[10] != 1 else 1e6) * SCALE  # 1: no far plane
# Direct3D 8 puts pixel centres on integer coordinates, half a pixel off Blender's: shift right and down by that.
cd.shift_x = -proj[8] / 2 - 0.5 / W
cd.shift_y = -proj[9] / 2 * (proj[0] / proj[5]) + 0.5 / W
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.pixel_aspect_x = (proj[5] / proj[0]) / (W / H)  # the game's projection isn't the screen's shape
sc.view_settings.view_transform = 'Raw'  # materials output the game's sRGB values directly
sc['unit_scale'] = 'one Blender unit = 250 game units'
sc['game_view'], sc['game_projection'] = list(view), list(proj)
sc['skipped'] = str(dict(skipped))
sc.world = bpy.data.worlds.new('fog colour')
sc.world.color = rgba(hero[0]['rs'][RS['FOGCOLOR']])[:3]
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
print('worldview: %d draws (%d hero, %d sweep, %d character), %d objects, %d materials, %d triangles (%d turned to face their normals)'
      % (len(chosen), sum(d['set'] == 'hero' for d in chosen), sum(d['set'] == 'sweep' for d in chosen),
         sum(d['set'] == 'characters' for d in chosen), sum(len(c.objects) for c in cols.values()), len(materials), total, flipped))
print('worldview: skipped', dict(skipped))
print('worldview: missing textures', sorted({'%016x' % h for h, i in images.items() if i is None}))
with open(os.path.splitext(os.path.abspath(out))[0] + '-triangles.tsv', 'w') as f:
    for (n, s), c in sorted(stats.items(), key=lambda x: -x[1]): f.write('%s\t%s\t%d\n' % (n, s, c))
