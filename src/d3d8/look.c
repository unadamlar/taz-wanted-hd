// Look level 4 (tests=1 and look=4, or a taz-hd\look file holding 4 or 0): sorts the game's draws for hd.c, which
// renders the level's look data on the Direct3D 9 device. A taz-hd\measure file (N) logs the next N frames' timing.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "game.h"
#include "hd.h"

// Shader tokens (vs_1_1), for the copy of each lit character shader.
enum { RT_TEMP, RT_INPUT, RT_CONST, RT_ADDR, RT_RASTOUT, RT_ATTROUT, RT_TEXCRDOUT };
#define REG(t, n) ((DWORD)(t) << 28 | (DWORD)(n))
#define r(n) REG(RT_TEMP, n)
#define c(n) REG(RT_CONST, n)
#define oT(n) REG(RT_TEXCRDOUT, n)
#define D(reg, mask) (0x80000000u | (reg) | (DWORD)(mask) << 16)
#define S(reg) (0x80000000u | (reg) | 0xe40000u)
enum { MOV = 1, MAD = 4, DP3 = 8, DP4 = 9 };

struct rec { IDirect3DVertexBuffer8 *vb; DWORD shader; UINT stride, start, count; D3DPRIMITIVETYPE type; float m[96][4]; };

#define NOWN 512
static IDirect3DBaseTexture8 *own_tex[NOWN];
static UINT nown;
static int level, loaded_scene = -1;
static struct rec *recs; static UINT nrecs, cap_recs;     // this frame's character draws, for their sun map
static HRESULT (WINAPI *draw_real)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT);
static struct { int frames, want; double look_ms, frame_ms, present_ms; UINT world, game, pieces, merged; LARGE_INTEGER last; } m;
static UINT stat_world, stat_game;

void look_install(void *dp)
{
    draw_real = dp;
    char v[8];
    settings_get("look", "0", v, sizeof v);
    level = settings.tests && atoi(v) ? 4 : 0;
}

static double now_ms(void)
{
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t), QueryPerformanceFrequency(&f);
    return t.QuadPart * 1000.0 / f.QuadPart;
}

static void drop_recs(void)
{
    for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
    nrecs = 0;
}

// Before a device Reset: everything in the default pool goes, or Reset fails. Reloaded by look_frame.
void look_reset(IDirect3DDevice8 *dev)
{
    hd_reset();
    nown = 0;
    drop_recs();
    merge_device_reset();
}

static DWORD avail_mb(void)
{
    MEMORYSTATUS s;
    s.dwLength = sizeof s;
    GlobalMemoryStatus(&s);
    return (DWORD)(s.dwAvailVirtual >> 20);
}

// --- matrices (row-vector, as Direct3D) ---------------------------------------------------------
static void mul4(float o[4][4], const float a[4][4], const float b[4][4])
{
    float t[4][4];
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) t[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j];
    memcpy(o, t, sizeof t);
}
static void rows_of(float o[4][4], const float a[4][4]) // transpose: shader rows for clip = M p
{
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) o[i][j] = a[j][i];
}
static float dot3(const float *a, const float *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

static struct rec *add_rec(void)
{
    if (nrecs == cap_recs) {
        struct rec *grown = realloc(recs, (cap_recs = cap_recs ? cap_recs * 2 : 1024) * sizeof *recs);
        if (!grown) return NULL;
        recs = grown;
    }
    return &recs[nrecs++];
}

// --- level 4: the game's draws sorted for hd.c --------------------------------------------------
static int suspended;              // F11 is on HD or Original: everything stays loaded, nothing of ours draws
static int remaster(void) { return level && !suspended && hd_loaded(); }
int look_remaster_available(void) { return level && hd_loaded(); }
void look_set_remaster(int on) { suspended = !on; }
int look_redirected(void) { return remaster() && hd_redirected(); }

void look_bb_restored(IDirect3DDevice8 *dev)
{
    if (remaster()) hd_rebind(d3d9_device(dev));
}

static void depth_batch(IDirect3DDevice8 *dev, IDirect3DBaseTexture8 *tex, UINT nverts, UINT first, UINT tris)
{
    textures_bind_own(dev, 0, textures_effective(tex));
    hd_merge_draw(d3d9_device(dev), nverts, first, tris);
}

// Once a frame, with the camera set: the sun map if it isn't built, then depth and AO.
static void prepass(IDirect3DDevice8 *dev)
{
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    hd_camera(d);
    if (hd_shadow_needed() && merge_ready()) {
        hd_shadow_begin(d);
        merge_each(dev, depth_batch);
        hd_shadow_end(d);
    }
    hd_prepass_begin(d);
    merge_each(dev, depth_batch);
    hd_prepass_end(d);
    merge_state_changed();
}

// Hides and binds are for the level's own copies of a texture. A cutscene's pack loads its own copies with the same
// pixels, so during a cutscene only copies the level has used, or its static world draws, count. 0: leave it alone.

void look_texture_gone(IDirect3DBaseTexture8 *t)
{
    for (UINT i = 0; i < nown; i++)
        if (own_tex[i] == t) own_tex[i--] = own_tex[--nown];
}

UINT64 look_own_hash(IDirect3DDevice8 *dev, IDirect3DBaseTexture8 *t, UINT64 h)
{
    if (!level || !h || (!hd_hidden(h) && !hd_shade(h) && !hd_has_bind(h))) return h;
    for (UINT i = 0; i < nown; i++)
        if (own_tex[i] == t) return h;
    if (cutscene_playing() && !merge_hub_draw(dev)) return 0;
    if (nown < NOWN) own_tex[nown++] = t;
    return h;
}

// The lit pass of each character shader gets a copy that also outputs world position (oT2) and normal
// (oT3), from the skinned r0 and r2 through the model's world rows in c60-c62.
#define NCHAR 32
static struct { DWORD game, lit; int outline, bones; } chars[NCHAR];
static int ncopying;
int look_copying_shader(void) { return ncopying; }

void look_shader_created(IDirect3DDevice8 *dev, DWORD h, const DWORD *fn)
{
    static const DWORD ramp[] = { MOV, 0xe0020001, 0xa0ff0030 };             // mov oT1.y, c48.w
    static const DWORD push[] = { MAD, 0x80070000, 0x80e40002, 0xa0ff0031 }; // mad r0.xyz, r2, c49.w, r0
    DWORD out[1200], decl[16];
    int n = 0, lit = 0, outline = 0, k = 0;
    int skin = 0, pos = 0, nor = 2;
    for (; n < 1024 && fn[n] != 0xffff; n++) {
        out[n] = fn[n];
        if (fn[n] == DP4 && (fn[n + 1] & 0x70000000) == REG(RT_RASTOUT, 0) && (fn[n + 3] & 0x70001fff) == c(92)) pos = fn[n + 2] & 0x7ff;
        if (fn[n] == DP3 && (fn[n + 2] & 0x70000000) == REG(RT_TEMP, 0) && (fn[n + 3] & 0x70001fff) == c(48)) nor = fn[n + 2] & 0x7ff;
        skin += n >= 2 && fn[n - 2] == DP4 && (fn[n] & 0xf0001fff) == 0x90000000; // dp4 r, v0, c[a0 + row]
        lit |= !memcmp(fn + n, ramp, sizeof ramp);
        outline |= !memcmp(fn + n, push, sizeof push);
    }
    if ((!lit && !outline && !skin) || fn[n] != 0xffff) return;
    int slot = -1;
    for (int i = 0; i < NCHAR && slot < 0; i++) if (!chars[i].game) slot = i;
    if (slot < 0) return;
    chars[slot].game = h, chars[slot].outline = outline, chars[slot].lit = 0, chars[slot].bones = skin / 3;
    if (outline) return;
    if (!lit) { // the plain kind has no normal: skin one
        nor = 2;
        for (int k = 0; k < skin / 3; k++) {
            out[n++] = MOV, out[n++] = D(REG(RT_ADDR, 0), 1), out[n++] = 0x80000000u | REG(RT_INPUT, 2) | (DWORD)(k * 0x55) << 16;
            for (int row = 0; row < 3; row++)
                out[n++] = DP3, out[n++] = D(r(3), 1 << row), out[n++] = S(REG(RT_INPUT, 3)), out[n++] = S(c(row)) | 0x2000;
            DWORD w = 0x80000000u | REG(RT_INPUT, 1) | (DWORD)(k * 0x55) << 16;
            if (!k) out[n++] = 5, out[n++] = D(r(2), 7), out[n++] = S(r(3)), out[n++] = w;     // mul
            else out[n++] = MAD, out[n++] = D(r(2), 7), out[n++] = S(r(3)), out[n++] = w, out[n++] = S(r(2));
        }
    }
    for (int row = 0; row < 3; row++) {
        out[n++] = DP4, out[n++] = D(oT(2), 1 << row), out[n++] = S(r(pos)), out[n++] = S(c(60 + row));
    }
    for (int row = 0; row < 3; row++) {
        out[n++] = DP3, out[n++] = D(oT(3), 1 << row), out[n++] = S(r(nor)), out[n++] = S(c(60 + row));
    }
    out[n++] = MOV, out[n++] = D(oT(4), 7), out[n++] = S(REG(RT_INPUT, 0));   // bind pose, for the fur
    out[n++] = MOV, out[n++] = D(oT(5), 7), out[n++] = S(REG(RT_INPUT, 3));
    out[n] = 0xffff;
    DWORD size = 0;
    if (FAILED(IDirect3DDevice8_GetVertexShaderDeclaration(dev, h, NULL, &size)) || size > sizeof decl
        || FAILED(IDirect3DDevice8_GetVertexShaderDeclaration(dev, h, decl, &size))) {
        extern const DWORD smooth_decl[8];
        memcpy(decl, smooth_decl, sizeof smooth_decl);
        for (k = 0; k < 7 && decl[k] != 0xffffffff; k++) {}
        if (fn[0] && k == 7) decl[7] = 0xffffffff;
    }
    ncopying++;
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, decl, out, &chars[slot].lit, 0))) chars[slot].lit = 0, log_line("look: no lit copy of shader %#lx", h);
    ncopying--;
}

void look_shader_deleted(IDirect3DDevice8 *dev, DWORD h)
{
    for (int i = 0; i < NCHAR; i++) {
        if (chars[i].game != h) continue;
        if (chars[i].lit) IDirect3DDevice8_DeleteVertexShader(dev, chars[i].lit);
        chars[i].game = chars[i].lit = 0;
    }
}

static int cam_on;
static D3DMATRIX real_view, real_proj; // the game's own camera, also while the test camera replaces it

// Inverse of the camera's clip rows, for turning a character's c92-c95 into its world rows.
static int invert(const float in[4][4], float out[4][4])
{
    float a[4][8];
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 8; x++) a[y][x] = x < 4 ? in[y][x] : (x - 4 == y);
    for (int col = 0; col < 4; col++) {
        int piv = col;
        for (int y = col + 1; y < 4; y++) if (fabsf(a[y][col]) > fabsf(a[piv][col])) piv = y;
        if (a[piv][col] == 0) return 0;
        for (int x = 0; x < 8; x++) { float tmp = a[col][x]; a[col][x] = a[piv][x]; a[piv][x] = tmp; }
        float d = a[col][col];
        for (int x = 0; x < 8; x++) a[col][x] /= d;
        for (int y = 0; y < 4; y++)
            if (y != col) {
                float k = a[y][col];
                for (int x = 0; x < 8; x++) a[y][x] -= k * a[col][x];
            }
    }
    for (int y = 0; y < 4; y++) memcpy(out[y], a[y] + 4, 16);
    return 1;
}

static void model_rows(const float wvp[4][4], float rows[4][4])
{
    float vp[4][4], vc[4][4], inv[4][4];
    mul4(vp, (const float (*)[4])&real_view, (const float (*)[4])&real_proj);
    rows_of(vc, vp);
    if (!invert(vc, inv)) { memset(rows, 0, 64); rows[0][0] = rows[1][1] = rows[2][2] = rows[3][3] = 1; return; }
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 4; x++)
            rows[y][x] = inv[y][0] * wvp[0][x] + inv[y][1] * wvp[1][x] + inv[y][2] * wvp[2][x] + inv[y][3] * wvp[3][x];
}

int look_char_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                   HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT), HRESULT *hr)
{
    if (!remaster() || !hd_redirected()) return 0;
    DWORD vs = 0;
    IDirect3DDevice8_GetVertexShader(dev, &vs);
    for (int i = 0; i < NCHAR; i++) {
        if (chars[i].game != vs) continue;
        if (chars[i].outline) return *hr = D3D_OK, 1; // no black outline in this light
        if (!chars[i].lit) return 0;
        static float last[4][4], rows[4][4];
        float wvp[4][4];
        IDirect3DDevice8_GetVertexShaderConstant(dev, 92, wvp, 4);
        if (memcmp(last, wvp, 64)) memcpy(last, wvp, 64), model_rows(wvp, rows);
        struct IDirect3DDevice9 *d = d3d9_device(dev);
        DWORD op;
        IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLOROP, &op);
        float style[4];
        IDirect3DTexture8 *fur = style_look(dev, style);
        hd_char_begin(d, rows[0], op == D3DTOP_SELECTARG2 || !textures_bound(0) ? 0 : 1, op == D3DTOP_SELECTARG1 ? 0 : 1, op == D3DTOP_MODULATE2X ? 2 : 1, style, d3d9_texture(fur));
        if (cam_on) { // the test camera: place the character through it
            float vp[4][4], clip[4][4], moved[4][4];
            mul4(vp, (const float (*)[4])hd_view(), (const float (*)[4])hd_proj());
            rows_of(clip, vp);
            for (int a = 0; a < 4; a++)
                for (int b = 0; b < 4; b++) moved[a][b] = clip[a][0] * rows[0][b] + clip[a][1] * rows[1][b] + clip[a][2] * rows[2][b] + clip[a][3] * rows[3][b];
            IDirect3DDevice8_SetVertexShaderConstant(dev, 92, moved, 4);
        }
        IDirect3DDevice8_SetVertexShader(dev, chars[i].lit);
        *hr = draw(dev, type, start, count);
        IDirect3DDevice8_SetVertexShader(dev, vs);
        if (cam_on) IDirect3DDevice8_SetVertexShaderConstant(dev, 92, wvp, 4);
        hd_char_end(d);
        return 1;
    }
    return 0;
}

static void record_char(IDirect3DDevice8 *dev, DWORD shader, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    DWORD cull;
    IDirect3DVertexBuffer8 *vb;
    UINT stride;
    IDirect3DDevice8_GetRenderState(dev, D3DRS_CULLMODE, &cull);
    if (cull == D3DCULL_CW || FAILED(IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride)) || !vb) return;
    struct rec *e = add_rec();
    if (!e) { IDirect3DVertexBuffer8_Release(vb); return; }
    e->vb = vb, e->shader = shader, e->stride = stride, e->start = start, e->count = count, e->type = type;
    IDirect3DDevice8_GetVertexShaderConstant(dev, 0, e->m, 96);
}

// The characters' sun map for the next frame, from the draws recorded in this one.
static void char_shadows(IDirect3DDevice8 *dev)
{
    if (!nrecs) return;
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    float vp[4][4], vc[4][4], inv[4][4], ctr[3] = { 0 }, best = 1e30f, eye[3];
    const float *v = hd_view();
    mul4(vp, (const float (*)[4])&real_view, (const float (*)[4])&real_proj);
    rows_of(vc, vp);
    for (int k = 0; k < 3; k++) eye[k] = -(v[12] * v[k * 4] + v[13] * v[k * 4 + 1] + v[14] * v[k * 4 + 2]);
    if (invert(vc, inv)) {
        for (UINT i = 0; i < nrecs; i++) {
            struct rec *e = &recs[i];
            for (int y = 0; y < 4; y++)
                for (int x = 0; x < 4; x++)
                    e->m[88 + y][x] = inv[y][0] * e->m[92][x] + inv[y][1] * e->m[93][x] + inv[y][2] * e->m[94][x] + inv[y][3] * e->m[95][x];
            float dd = 0;
            for (int k = 0; k < 3; k++) dd += powf(e->m[88 + k][3] - eye[k], 2);
            if (dd < best) best = dd, ctr[0] = e->m[88][3], ctr[1] = e->m[89][3], ctr[2] = e->m[90][3];
        }
        DWORD old = 0;
        IDirect3DDevice8_GetVertexShader(dev, &old);
        IDirect3DDevice8_BeginScene(dev);
        hd_cmap_begin(d, ctr);
        const float (*clip)[4] = (const float (*)[4])hd_cmap_clip();
        for (UINT i = 0; i < nrecs; i++) {
            struct rec *e = &recs[i];
            float lc[4][4];
            for (int a = 0; a < 4; a++)
                for (int b = 0; b < 4; b++) lc[a][b] = clip[a][0] * e->m[88][b] + clip[a][1] * e->m[89][b] + clip[a][2] * e->m[90][b] + clip[a][3] * e->m[91][b];
            IDirect3DVertexBuffer8_AddRef(e->vb);
            if (IDirect3DVertexBuffer8_Release(e->vb) <= 1) continue; // freed by a scene change since: drawing it crashes in DXVK
            int bones = 3;
            for (int c = 0; c < NCHAR; c++) if (chars[c].game == e->shader) bones = chars[c].bones;
            hd_cmap_draw(d, d3d9_vb(e->vb), e->stride, e->type, e->start, e->count, e->m[0], lc[0], bones);
        }
        hd_cmap_end(d);
        IDirect3DDevice8_EndScene(dev);
        IDirect3DDevice8_SetVertexShader(dev, old);
        merge_state_changed();
    }
    drop_recs();
}

// Test aid: a taz-hd\look-cam file "ex ey ez tx ty tz p00 p11" replaces the game's camera at the Remaster look, so
// shots match the Blender views; an empty file ends it.
static D3DMATRIX cam_view_m;
static float cam_p00, cam_p11;

static void read_camera(void)
{
    FILE *f = settings.tests ? fopen("taz-hd\\look-cam", "r") : NULL;
    if (!f) return;
    float e[3], t[3], z[3], x[3], y[3];
    cam_on = fscanf(f, "%f %f %f %f %f %f %f %f", &e[0], &e[1], &e[2], &t[0], &t[1], &t[2], &cam_p00, &cam_p11) == 8;
    fclose(f);
    DeleteFileA("taz-hd\\look-cam");
    if (!cam_on) return;
    for (int k = 0; k < 3; k++) z[k] = t[k] - e[k];
    float l = sqrtf(dot3(z, z));
    for (int k = 0; k < 3; k++) z[k] /= l;
    x[0] = z[2], x[1] = 0, x[2] = -z[0]; // up (0, 1, 0) x z
    l = sqrtf(dot3(x, x));
    for (int k = 0; k < 3; k++) x[k] /= l;
    y[0] = z[1] * x[2] - z[2] * x[1], y[1] = z[2] * x[0] - z[0] * x[2], y[2] = z[0] * x[1] - z[1] * x[0];
    float m[4][4] = { { x[0], y[0], z[0], 0 }, { x[1], y[1], z[1], 0 }, { x[2], y[2], z[2], 0 }, { -dot3(x, e), -dot3(y, e), -dot3(z, e), 1 } };
    memcpy(&cam_view_m, m, 64);
}

const D3DMATRIX *look_camera(D3DTRANSFORMSTATETYPE t, const D3DMATRIX *m, D3DMATRIX *tmp)
{
    if (t == D3DTS_VIEW && !(m->_11 == 1 && m->_22 == 1 && m->_33 == 1 && !m->_41 && !m->_42 && !m->_43)) real_view = *m;
    if (t == D3DTS_PROJECTION && m->_34 == 1) real_proj = *m;
    if (!cam_on || !remaster()) return m;
    if (t == D3DTS_PROJECTION && m->_34 == 1) return *tmp = *m, tmp->_11 = cam_p00, tmp->_22 = cam_p11, tmp;
    if (t == D3DTS_VIEW && !(m->_11 == 1 && m->_22 == 1 && m->_33 == 1 && !m->_41 && !m->_42 && !m->_43)) return &cam_view_m;
    return m;
}

static DWORD glowing; // the game's destination blend while one of its glows draws through ours
static int backdrop;

void look_after_draw(IDirect3DDevice8 *dev)
{
    if (glowing) hd_glow_end(d3d9_device(dev), glowing), glowing = 0;
}

// A game draw with a solid replacement: drawn at the game's own transform, so it follows whatever the game does.
static int swap_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    DWORD fvf;
    IDirect3DVertexBuffer8 *vb = NULL;
    UINT stride = 0, n = type == D3DPT_TRIANGLESTRIP ? count + 2 : type == D3DPT_TRIANGLELIST ? count * 3 : 0;
    BYTE *v;
    if (api || !n || !hd_swap_texture(textures_bound_hash(0))) return 0;
    IDirect3DDevice8_GetVertexShader(dev, &fvf);
    if (fvf != 0x152 || FAILED(IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride)) || !vb) return 0;
    UINT64 key = 0xcbf29ce484222325ULL;
    int ok = stride == 36 && SUCCEEDED(IDirect3DVertexBuffer8_Lock(vb, start * 36, n * 36, &v, D3DLOCK_READONLY));
    if (ok) {
        for (UINT i = 0; i < n * 36; i += 36) {
            for (int b = 0; b < 12; b++) key = (key ^ v[i + b]) * 0x100000001b3ULL;
            for (int b = 28; b < 36; b++) key = (key ^ v[i + b]) * 0x100000001b3ULL;
        }
        IDirect3DVertexBuffer8_Unlock(vb);
    }
    IDirect3DVertexBuffer8_Release(vb);
    int proto = ok ? hd_swap_proto(key) : -1;
    if (proto < 0) return 0;
    float w[4][4], rows[3][4];
    IDirect3DDevice8_GetTransform(dev, D3DTS_WORLD, (D3DMATRIX *)w);
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 4; j++) rows[i][j] = w[j][i];
    if (!hd_swap_claim(proto, rows[0])) return 1;
    merge_flush(dev);
    if (hd_prepass_needed()) prepass(dev);
    hd_swap_draw(d3d9_device(dev), proto, rows[0]);
    merge_state_changed();
    return 1;
}

static int draw4(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    if (!merge_on_backbuffer() || hd_post_done()) return 0;
    if (merge_is_2d(dev)) { // the HUD and menus: finish the 3D picture under them
        if (!hd_redirected()) { // no 3D yet: a paused frame's sky, or a screen the game composes itself (a paper book)
            UINT64 h2 = textures_bound_hash(0);
            backdrop |= h2 && !hd_hidden(h2);
            return 0;
        }
        merge_flush(dev);
        if (!hd_additions_done()) hd_additions(d);
        hd_post(d);
        merge_state_changed();
        return 0;
    }
    if (backdrop) return 0;   // tone mapping would paint over the 2D already on the back buffer
    hd_redirect(d);
    if (!hd_redirected()) return 0;
    hd_sky(d);
    if (swap_draw(dev, api, type, start, count)) return 1;
    if (merge_draw(dev, api, type, start, count)) return 1;
    DWORD shader, zwrite, blend, fog, src, dst, op;
    IDirect3DDevice8_GetRenderState(dev, D3DRS_ALPHABLENDENABLE, &blend);
    IDirect3DDevice8_GetRenderState(dev, D3DRS_SRCBLEND, &src);
    IDirect3DDevice8_GetRenderState(dev, D3DRS_DESTBLEND, &dst);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLOROP, &op);
    // The tutorial book's halo is one big alpha-blended quad of the ribbon's texture: it is what hazes the view up close.
    UINT64 sprite = api == 2 && blend && src == D3DBLEND_SRCALPHA && dst == D3DBLEND_INVSRCALPHA ? textures_bound_hash(0) : 0;
    int halo = sprite == 0x78c161107296791dULL || sprite == 0x23416f5ebf5678ffULL;
    if (halo || (blend && src == D3DBLEND_SRCALPHA && dst == D3DBLEND_ONE && textures_bound(0) && (op == D3DTOP_MODULATE || op == D3DTOP_MODULATE2X))) {
        if (!hd_additions_done()) { // sprites go over the finished world
            if (hd_prepass_needed()) prepass(dev);
            hd_additions(d), merge_state_changed();
        }
        hd_glow_begin(d, op == D3DTOP_MODULATE2X ? 2 : 1, halo ? 0.3f : 1.7f);
        glowing = dst;
        return 0;
    }
    IDirect3DDevice8_GetVertexShader(dev, &shader);
    if (IS_VERTEX_SHADER(shader)) {
        hd_invalidate();
        if (hd_prepass_needed()) prepass(dev);
        if (!hd_additions_done()) hd_additions(d), merge_state_changed();
        if (api == 0) record_char(dev, shader, type, start, count);
        return 0;
    }
    if ((shader & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW) return 0;
    UINT64 raw = textures_bound_hash(0);
    if (raw && hd_shade(raw)) return 1;
    UINT64 h = look_own_hash(dev, textures_bound(0), raw);
    if (h && hd_hidden(h)) return 1;
    IDirect3DDevice8_GetRenderState(dev, D3DRS_ZWRITEENABLE, &zwrite);
    IDirect3DDevice8_GetRenderState(dev, D3DRS_FOGENABLE, &fog);
    if (!zwrite && !fog && !blend && hd_hidden(raw)) return 1; // its sky, also a cutscene pack's copy of it
    if (hd_prepass_needed()) prepass(dev);
    if (blend && !hd_additions_done()) hd_additions(d), merge_state_changed();
    if (api != 0 || shader != 0x152) return 0;
    DWORD op0 = op, a1, op1, tt;
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLORARG1, &a1);
    IDirect3DDevice8_GetTextureStageState(dev, 1, D3DTSS_COLOROP, &op1);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, &tt);
    if (op0 != D3DTOP_MODULATE2X || a1 != D3DTA_TEXTURE || op1 != D3DTOP_DISABLE || !textures_bound(0) || tt) return 0;
    float w[4][4], rows[3][4];
    IDirect3DDevice8_GetTransform(dev, D3DTS_WORLD, (D3DMATRIX *)w);
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 4; j++) rows[i][j] = w[j][i];
    hd_world_quick(d, rows[0], h);
    draw_real(dev, type, start, count);
    hd_world_quick_end(d);
    IDirect3DDevice8_SetVertexShader(dev, shader);
    stat_world++;
    return 1;
}

// Before each game draw. Returns 1 to skip it.
int look_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    stat_game++;
    if (!remaster()) return 0;
    double t0 = now_ms();
    int result = draw4(dev, api, type, start, count);
    m.look_ms += now_ms() - t0;
    return result;
}

int look_hidden(UINT64 h) { return hd_hidden(h) || hd_shade(h); }

// The merged static world, between the draws around it.
void look_merge_begin(IDirect3DDevice8 *dev, IDirect3DVertexBuffer8 *vb, IDirect3DIndexBuffer8 *ib)
{
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    hd_camera(d);
    if (hd_prepass_needed()) prepass(dev);
    hd_world_begin(d, NULL);
    hd_merge_buffers(d, d3d9_vb(vb), d3d9_ib(ib));
}

void look_merge_texture(IDirect3DDevice8 *dev, IDirect3DBaseTexture8 *tex, UINT64 hash)
{
    textures_bind_own(dev, 0, textures_effective(tex));
    hd_world_material(d3d9_device(dev), hash);
}

void look_merge_draw(IDirect3DDevice8 *dev, UINT nverts, UINT first, UINT tris)
{
    hd_merge_draw(d3d9_device(dev), nverts, first, tris);
    stat_world++;
}

void look_merge_end(IDirect3DDevice8 *dev)
{
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    hd_world_end(d);
    if (!hd_additions_done()) hd_additions(d);
    merge_state_changed();
}

// At Present: level and data, the characters' sun map, measurements.
void look_frame(IDirect3DDevice8 *dev)
{
    FILE *f = settings.tests ? fopen("taz-hd\\look", "r") : NULL;
    if (f) {
        int n = level;
        fscanf(f, "%d", &n);
        fclose(f);
        DeleteFileA("taz-hd\\look");
        n = n ? 4 : 0;
        if (n != level) log_line("look: level %d", n), merge_reset();
        level = n;
    }
    if ((f = settings.tests ? fopen("taz-hd\\measure", "r") : NULL)) {
        int n = 300;
        fscanf(f, "%d", &n);
        fclose(f);
        DeleteFileA("taz-hd\\measure");
        memset(&m, 0, sizeof m);
        m.frames = -30, m.want = n;
    }
    double t0 = now_ms();
    merge_frame(dev);
    int scene = settings.exe_known ? SCENE : -1;
    struct IDirect3DDevice9 *d = d3d9_device(dev);
    if (level) read_camera(), hd_frame_end(d);
    if (hd_loaded() && (scene != loaded_scene || !level)) hd_unload(), merge_reset(), loaded_scene = -1, nown = 0;
    if (level && !hd_loaded() && scene >= 2 && (scene != loaded_scene || hd_lost())) {
        loaded_scene = scene; // tried once per scene: a scene without data stays on HD
        if (hd_load(d, scene)) merge_reset();
    }
    if (scene < 2) loaded_scene = -1;
    if (remaster()) char_shadows(dev);
    else drop_recs();
    m.look_ms += now_ms() - t0;
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    if (m.frames < 0 && ++m.frames == 0) QueryPerformanceCounter(&m.last), m.look_ms = 0, m.world = m.game = m.pieces = m.merged = 0;
    else if (m.frames >= 0 && m.last.QuadPart) {
        m.frames++, m.world += stat_world, m.game += stat_game, m.pieces += merge_stat_pieces, m.merged += merge_stat_draws;
        if (m.frames == m.want) {
            LARGE_INTEGER fq;
            QueryPerformanceFrequency(&fq);
            double ms = (t.QuadPart - m.last.QuadPart) * 1000.0 / fq.QuadPart / m.frames;
            log_line("look: measured level %d%s: %.2f ms/frame (%.1f fps), look code %.2f ms, Present %.2f ms, %u world draws, game issued %u draws, %u of them merged into %u, address space free %lu MB",
                     level, remaster() ? "" : " (F11 away)", ms, 1000 / ms, m.look_ms / m.frames, m.present_ms / m.frames, m.world / m.frames, m.game / m.frames,
                     m.pieces / m.frames, m.merged / m.frames, avail_mb());
            m.last.QuadPart = 0;
        }
    }
    stat_world = stat_game = merge_stat_pieces = merge_stat_draws = 0;
}

void look_present_ms(double ms)
{
    backdrop = 0; // here, so the mod's own messages drawn at Present don't count as the game's 2D screen
    if (m.frames > 0 && m.last.QuadPart) m.present_ms += ms;
}
