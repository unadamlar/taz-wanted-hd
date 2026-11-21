// Look test (prototype, tests=1 only): draws the look kit's additions (grass, clutter, trees, fences,
// cliff rocks; tools/look/export.py -> taz-hd\look-sceneNN.bin) inside the game's 3D pass, and at
// level 2 lights the game's world and the additions with one sun and shadow maps.
// Level: ini look=N, or a taz-hd\look file holding N (read every frame). 0 off; 1 additions (sun
// N.L, no shadows) with the game draws they replace hidden; 2 adds shadows: a static map of the
// world and additions made once, a per-frame map of the characters around player one, the game's
// world drawn through our shaders (texture x vertex colour x 2 as before, baked shadow tint made
// neutral, x (ambient + sun N.L shadow)). A taz-hd\measure file (N) logs the next N frames' timing.
// Additions are instanced through vertex shader constants (D3D8 has no instancing): each prototype's
// buffer holds 64 copies tagged with a copy number, and each draw loads 64 instance matrices.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "game.h"
#include "image.h"

// Shader tokens (vs_1_1 / ps_1_4), as in style.c.
enum { RT_TEMP, RT_INPUT, RT_CONST, RT_ADDR, RT_RASTOUT, RT_ATTROUT, RT_TEXCRDOUT };
#define REG(t, n) ((DWORD)(t) << 28 | (DWORD)(n))
#define r(n) REG(RT_TEMP, n)
#define v(n) REG(RT_INPUT, n)
#define c(n) REG(RT_CONST, n)
#define t(n) REG(RT_ADDR, n)
#define oT(n) REG(RT_TEXCRDOUT, n)
#define oD(n) REG(RT_ATTROUT, n)
#define oPos REG(RT_RASTOUT, 0)
#define oFog REG(RT_RASTOUT, 1)
#define a0 REG(RT_ADDR, 0)
enum { X = 1, Y = 2, Z = 4, W = 8, XYZ = 7, ALL = 15 };
#define D(reg, mask) (0x80000000u | (reg) | (DWORD)(mask) << 16)
#define S(reg) (0x80000000u | (reg) | 0xe40000u)
#define SR(reg, k) (0x80000000u | (reg) | (DWORD)((k) * 0x55) << 16)
#define SWZ(reg, a, b, c_, d) (0x80000000u | (reg) | (DWORD)((a) | (b) << 2 | (c_) << 4 | (d) << 6) << 16)
#define NEG (1u << 24)
#define REL (1u << 13)
#define X2 (1u << 24)
#define X8 (3u << 24)
#define SAT (1u << 20)
enum { MOV = 1, ADD, SUB, MAD, MUL, RCP, RSQ, DP3, DP4, MIN, MAX, SLT = 12, LRP = 18, TEXLD = 0x42 };
static DWORD code[256];
static int len;
static void op(DWORD o, DWORD d, DWORD s0, DWORD s1, DWORD s2, int n)
{
    code[len++] = o, code[len++] = d;
    if (n > 0) code[len++] = s0;
    if (n > 1) code[len++] = s1;
    if (n > 2) code[len++] = s2;
}
#define OP1(o, d, a) op(o, d, a, 0, 0, 1)
#define OP2(o, d, a, b) op(o, d, a, b, 0, 2)
#define OP3(o, d, a, b, cc) op(o, d, a, b, cc, 3)

// Vertex shader constants: c0-c3 clip rows (camera, or light for depth), c4-c6 static shadow
// (u, v, depth), c7-c9 character shadow, c10-c12 world rows (game draws), c13 towards the sun, c14
// (0, 1, 0.5, 1e-4), c15 the baked shade tint, c16 view z row, c17 fog (end, 1 / (end - start)),
// c18 colour scale, c20.. instance rows. Pixel shader: c1 sun, c2 ambient.
enum { INST = 0, WORLD = 1, DEPTH = 2 };
static void make_vs(int kind)
{
    len = 0;
    code[len++] = 0xfffe0101;
    if (kind & WORLD) {
        for (int k = 0; k < 3; k++) OP2(DP4, D(r(0), 1 << k), S(v(0)), S(c(10 + k)));
        for (int k = 0; k < 3; k++) OP2(DP3, D(r(1), 1 << k), S(v(1)), S(c(10 + k)));
    } else {
        OP1(MOV, D(a0, X), SR(v(3), 0));
        for (int k = 0; k < 3; k++) OP2(DP4, D(r(0), 1 << k), S(v(0)), S(c(20 + k)) | REL);
        for (int k = 0; k < 3; k++) OP2(DP3, D(r(1), 1 << k), S(v(1)), S(c(20 + k)) | REL);
    }
    OP1(MOV, D(r(0), W), SR(c(14), 1));
    for (int k = 0; k < 4; k++) OP2(DP4, D(oPos, 1 << k), S(r(0)), S(c(k)));
    if (kind & DEPTH) {
        code[len++] = 0xffff;
        return;
    }
    for (int k = 0; k < 3; k++) OP2(DP4, D(oT(1), 1 << k), S(r(0)), S(c(4 + k)));
    for (int k = 0; k < 3; k++) OP2(DP4, D(oT(2), 1 << k), S(r(0)), S(c(7 + k)));
    OP1(MOV, D(oT(1), W), SR(c(14), 1));
    OP1(MOV, D(oT(2), W), SR(c(14), 1));
    OP2(DP3, D(r(1), W), S(r(1)), S(r(1)));
    OP1(RSQ, D(r(1), W), SR(r(1), 3));
    OP2(MUL, D(r(1), XYZ), S(r(1)), SR(r(1), 3));
    OP2(DP3, D(r(2), X), S(r(1)), S(c(13)));
    if (kind & WORLD) OP2(MAX, D(oD(1), ALL), SR(r(2), 0), SR(c(14), 0));
    else OP2(MAX, D(oD(1), ALL), SR(r(2), 0), SR(r(2), 0) | NEG); // blades and leaves: lit from either side
    OP2(DP4, D(r(3), X), S(r(0)), S(c(16)));                       // fog as the game's (linear, view depth)
    OP2(ADD, D(r(3), X), SR(c(17), 0), SR(r(3), 0) | NEG);
    OP2(MUL, D(oFog, X), SR(r(3), 0), SR(c(17), 1));
    if (kind & WORLD) {
        OP1(MOV, D(oT(0), X | Y), S(v(3)));
        OP2(MUL, D(oT(3), X | Y), SWZ(r(0), 0, 2, 2, 2), SR(c(19), 0)); // ground tiling: world x, z
        OP2(ADD, D(r(4), XYZ), S(v(2)), S(c(15)) | NEG);            // the baked lilac shade becomes the lit grey
        OP2(DP3, D(r(4), W), S(r(4)), S(r(4)));
        OP2(SLT, D(r(4), W), SR(r(4), 3), SR(c(14), 3));
        OP2(ADD, D(r(5), ALL), SR(v(2), 2), S(v(2)) | NEG);
        OP3(MAD, D(oD(0), XYZ), S(r(5)), SR(r(4), 3), S(v(2)));
        OP1(MOV, D(oD(0), W), SR(v(2), 3));
    } else {
        OP1(MOV, D(oT(0), X | Y), SR(c(14), 0));
        OP2(MUL, D(oD(0), ALL), S(v(2)), S(c(18)));
    }
    code[len++] = 0xffff;
}

static void make_ps(int debug)
{
    len = 0;
    code[len++] = 0xffff0104;
    OP1(TEXLD, D(r(0), ALL), S(t(0)));
    if (debug == 1) { // ground: tiling dirt where the game's texture is orange, its own colour where it paints grass
        OP1(TEXLD, D(r(3), ALL), S(t(3)));
        OP2(ADD, D(r(4), ALL) | X8 | SAT, SR(r(0), 1), SR(r(0), 0) | NEG);
        OP3(LRP, D(r(0), XYZ), SR(r(4), 0), S(r(0)), S(r(3)));
        debug = 0;
    }
    OP1(TEXLD, D(r(1), ALL), S(t(1)));                                // depth compare: 1 lit, 0 shadow
    OP1(TEXLD, D(r(2), ALL), S(t(2)));
    if (debug) OP1(MOV, D(r(3), XYZ), S(r(2))), OP1(MOV, D(r(2), XYZ), S(r(1)));
    OP2(MUL, D(r(1), XYZ), SR(r(1), 0), SR(r(2), 0));
    OP2(MUL, D(r(1), XYZ), S(r(1)), S(REG(RT_INPUT, 1)));
    OP3(MAD, D(r(1), XYZ), S(r(1)), S(c(1)), S(c(2)));
    OP2(MUL, D(r(0), ALL) | X2, S(r(0)), S(REG(RT_INPUT, 0)));
    OP2(MUL, D(r(0), XYZ), S(r(0)), S(r(1)));
    if (debug) OP1(MOV, D(r(0), XYZ), S(r(2 + debug - 2)));        // 2: static map sample, 3: character map
    code[len++] = 0xffff;
}

// Grade: saturation up by c1 (the kit's 1.28), a touch of contrast around c3.
static void make_grade(void)
{
    len = 0;
    code[len++] = 0xffff0104;
    OP1(TEXLD, D(r(0), ALL), S(t(0)));
    OP2(DP3, D(r(1), ALL), S(r(0)), S(c(0)));
    OP2(ADD, D(r(2), ALL), S(r(0)), S(r(1)) | NEG);
    OP3(MAD, D(r(0), XYZ), S(r(2)), S(c(1)), S(r(0)));
    OP2(ADD, D(r(3), ALL), S(r(0)), S(c(3)) | NEG);
    OP3(MAD, D(r(0), XYZ) | SAT, S(r(3)), S(c(2)), S(r(0)));
    code[len++] = 0xffff;
}

static const DWORD inst_decl[] = { 0x20000000, 0x40020000, 0x40020001, 0x40040002, 0x40050003, 0xffffffff };
static const DWORD world_decl[] = { 0x20000000, 0x40020000, 0x40020001, 0x40040002, 0x40010003, 0xffffffff }; // FVF 0x152
#define COPIES 64
#define SMAP 4096
#define CMAP 1024

struct proto { UINT nv, ni; float (*v)[7]; UINT *ix; IDirect3DVertexBuffer8 *vb; IDirect3DIndexBuffer8 *ib; UINT copies; };
struct run { UINT proto, n; float (*m)[12]; };
struct chunk { float lo[3], hi[3]; UINT nruns; struct run *runs; };
struct rec { IDirect3DVertexBuffer8 *vb; DWORD shader; UINT stride, start, count; D3DPRIMITIVETYPE type; float m[96][4]; };

static int level, loaded_scene = -1, failed, injected, seen_vs, built, recording;
static UINT64 *hide, *ground; static UINT nhide, nhide_all, nground; // first nhide: always; up to nhide_all: from level 2
static struct proto *protos; static UINT nprotos;
static struct chunk *chunks; static UINT nchunks;
static BYTE *file;
static DWORD vs_inst, vs_world, vs_inst_depth, vs_world_depth, ps, ps_ground, ps_grade, ps_debug[2], debug, in_grade; // debug (look=8 or 9): show a shadow map's samples
static IDirect3DTexture8 *white, *smap, *cmap, *dirt, *frame_tex;
static IDirect3DSurface8 *smap_rt, *cmap_rt;
static struct rec *recs; static UINT nrecs, cap_recs;     // static world (once), then characters (per frame)
static float cam_view[4][4], cam_proj[4][4], sun[3], srows[3][4], sclip[4][4], crows[3][4], cclip[4][4];
static HRESULT (WINAPI *draw_real)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT);
static HRESULT (WINAPI *draw_indexed_real)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, UINT);
static struct { int frames, want; double look_ms, frame_ms, present_ms; UINT draws, tris, world, game, pieces, merged; LARGE_INTEGER last; } m;
static UINT stat_draws, stat_tris, stat_world, stat_game;
// What of ours is still bound, so a run of world draws doesn't set it all again: textures and sampler
// states on stages 1-3 (the game sets those only for characters), and the vertex constants' matrices.
static int bound_ok, ground_ok;
static float last_m[3][4][4];
static DWORD merge_sb;

void look_state_changed(void) { bound_ok = ground_ok = 0; }

void look_install(void *dp, void *dip)
{
    draw_real = dp, draw_indexed_real = dip;
    char v[8];
    settings_get("look", "0", v, sizeof v);
    level = settings.tests ? atoi(v) : 0;
}

static double now_ms(void)
{
    LARGE_INTEGER t, f;
    QueryPerformanceCounter(&t), QueryPerformanceFrequency(&f);
    return t.QuadPart * 1000.0 / f.QuadPart;
}

static void unload(void)
{
    for (UINT i = 0; i < nprotos; i++) {
        if (protos[i].vb) IDirect3DVertexBuffer8_Release(protos[i].vb);
        if (protos[i].ib) IDirect3DIndexBuffer8_Release(protos[i].ib);
    }
    for (UINT i = 0; i < nchunks; i++) free(chunks[i].runs);
    free(protos), free(chunks), free(file), free(hide);
    protos = NULL, chunks = NULL, file = NULL, hide = NULL, ground = NULL, nprotos = nchunks = nhide = nhide_all = nground = 0;
    for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
    nrecs = 0, built = 0, recording = 0;
    merge_reset();
}

// Before a device Reset: everything in the default pool goes, or Reset fails. Remade by look_frame.
void look_reset(IDirect3DDevice8 *dev)
{
    IDirect3DTexture8 **tex[] = { &smap, &cmap, &frame_tex };
    IDirect3DSurface8 **surf[] = { &smap_rt, &cmap_rt };
    for (int i = 0; i < 3; i++) if (*tex[i]) IDirect3DTexture8_Release(*tex[i]), *tex[i] = NULL;
    for (int i = 0; i < 2; i++) if (*surf[i]) IDirect3DSurface8_Release(*surf[i]), *surf[i] = NULL;
    for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
    nrecs = 0, built = 0, recording = 0;
    if (merge_sb) IDirect3DDevice8_DeleteStateBlock(dev, merge_sb), merge_sb = 0;
    merge_device_reset();
}

static DWORD avail_mb(void)
{
    MEMORYSTATUS s;
    s.dwLength = sizeof s;
    GlobalMemoryStatus(&s);
    return (DWORD)(s.dwAvailVirtual >> 20);
}

static int load(IDirect3DDevice8 *dev, int scene)
{
    char path[MAX_PATH];
    snprintf(path, sizeof path, "taz-hd\\look-scene%02d.bin", scene);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    double t0 = now_ms();
    DWORD before = avail_mb();
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    file = malloc(n);
    fread(file, 1, n, f);
    fclose(f);
    BYTE *p = file + 8;
#define U32() (p += 4, *(UINT *)(p - 4))
    UINT a = U32();
    UINT64 *h1 = (UINT64 *)p; p += a * 8;
    UINT b = U32();
    hide = malloc((a + b) * 8);
    memcpy(hide, h1, a * 8), memcpy(hide + a, p, b * 8), p += b * 8;
    nhide = a, nhide_all = a + b;
    if (((UINT *)file)[1] >= 2) nground = U32(), ground = (UINT64 *)p, p += nground * 8;
    nprotos = U32();
    protos = calloc(nprotos, sizeof *protos);
    for (UINT i = 0; i < nprotos; i++) {
        struct proto *q = &protos[i];
        q->nv = U32(), q->ni = U32();
        q->v = (void *)p, p += q->nv * 28;
        q->ix = (void *)p, p += q->ni * 4;
    }
    nchunks = U32();
    chunks = calloc(nchunks, sizeof *chunks);
    UINT most[4096] = { 0 };
    for (UINT i = 0; i < nchunks; i++) {
        struct chunk *k = &chunks[i];
        memcpy(k->lo, p, 12), memcpy(k->hi, p + 12, 12), p += 24;
        k->nruns = U32();
        k->runs = calloc(k->nruns, sizeof *k->runs);
        for (UINT j = 0; j < k->nruns; j++) {
            k->runs[j].proto = U32(), k->runs[j].n = U32();
            k->runs[j].m = (void *)p, p += k->runs[j].n * 48;
            if (k->runs[j].n > most[k->runs[j].proto % 4096]) most[k->runs[j].proto % 4096] = k->runs[j].n;
        }
    }
    UINT bytes = 0;
    for (UINT i = 0; i < nprotos; i++) { // COPIES copies of each prototype, each vertex tagged with 3 x its copy number
        struct proto *q = &protos[i];
        q->copies = most[i] < COPIES ? (most[i] ? most[i] : 1) : COPIES;
        UINT nv = q->nv * q->copies, big = nv > 65535;
        BYTE *vp;
        if (FAILED(IDirect3DDevice8_CreateVertexBuffer(dev, nv * 32, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &q->vb))
            || FAILED(IDirect3DDevice8_CreateIndexBuffer(dev, q->ni * q->copies * (big ? 4 : 2), D3DUSAGE_WRITEONLY,
                                                         big ? D3DFMT_INDEX32 : D3DFMT_INDEX16, D3DPOOL_MANAGED, &q->ib)))
            return log_line("look: buffers failed"), 0;
        IDirect3DVertexBuffer8_Lock(q->vb, 0, 0, &vp, 0);
        for (UINT c = 0; c < q->copies; c++)
            for (UINT k = 0; k < q->nv; k++) {
                BYTE *o = vp + (c * q->nv + k) * 32;
                memcpy(o, q->v[k], 28);
                o[28] = (BYTE)(3 * c), o[29] = o[30] = o[31] = 0;
            }
        IDirect3DVertexBuffer8_Unlock(q->vb);
        IDirect3DIndexBuffer8_Lock(q->ib, 0, 0, &vp, 0);
        for (UINT c = 0; c < q->copies; c++)
            for (UINT k = 0; k < q->ni; k++)
                if (big) ((UINT *)vp)[c * q->ni + k] = q->ix[k] + c * q->nv;
                else ((WORD *)vp)[c * q->ni + k] = (WORD)(q->ix[k] + c * q->nv);
        IDirect3DIndexBuffer8_Unlock(q->ib);
        bytes += nv * 32 + q->ni * q->copies * (big ? 4 : 2);
    }
    log_line("look: %s, %u prototypes, %u chunks, %.1f MB file, %.1f MB buffers, %.0f ms, address space free %lu -> %lu MB",
             path, nprotos, nchunks, n / 1e6, bytes / 1e6, now_ms() - t0, before, avail_mb());
    return 1;
}

// Depth textures sampled with a depth compare (hardware shadow maps); each needs a colour target as big.
static int make_targets(IDirect3DDevice8 *dev)
{
    if (smap) return 1;
    if (FAILED(IDirect3DDevice8_CreateTexture(dev, SMAP, SMAP, 1, D3DUSAGE_DEPTHSTENCIL, D3DFMT_D24S8, D3DPOOL_DEFAULT, &smap))
        || FAILED(IDirect3DDevice8_CreateTexture(dev, CMAP, CMAP, 1, D3DUSAGE_DEPTHSTENCIL, D3DFMT_D24S8, D3DPOOL_DEFAULT, &cmap))
        || FAILED(IDirect3DDevice8_CreateRenderTarget(dev, SMAP, SMAP, D3DFMT_R5G6B5, D3DMULTISAMPLE_NONE, FALSE, &smap_rt))
        || FAILED(IDirect3DDevice8_CreateRenderTarget(dev, CMAP, CMAP, D3DFMT_R5G6B5, D3DMULTISAMPLE_NONE, FALSE, &cmap_rt)))
        return log_line("look: shadow map textures failed"), 0;
    return 1;
}

static int ready(IDirect3DDevice8 *dev)
{
    if (ps || failed) return !failed;
    failed = 1;
    D3DLOCKED_RECT lr;
    make_vs(INST);
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, inst_decl, code, &vs_inst, 0))) return log_line("look: vs failed"), 0;
    make_vs(INST | DEPTH);
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, inst_decl, code, &vs_inst_depth, 0))) return log_line("look: vs failed"), 0;
    make_vs(WORLD);
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, world_decl, code, &vs_world, 0))) return log_line("look: vs failed"), 0;
    make_vs(WORLD | DEPTH);
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, world_decl, code, &vs_world_depth, 0))) return log_line("look: vs failed"), 0;
    make_ps(0);
    if (FAILED(IDirect3DDevice8_CreatePixelShader(dev, code, &ps))) return log_line("look: ps failed"), 0;
    make_ps(1);
    if (FAILED(IDirect3DDevice8_CreatePixelShader(dev, code, &ps_ground))) return log_line("look: ps failed"), 0;
    make_grade();
    if (FAILED(IDirect3DDevice8_CreatePixelShader(dev, code, &ps_grade))) return log_line("look: ps failed"), 0;
    UINT w, h;
    BYTE *px = image_read("taz-hd\\look-dirt.png", &w, &h);
    if (px && SUCCEEDED(IDirect3DDevice8_CreateTexture(dev, w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &dirt))) {
        IDirect3DTexture8_LockRect(dirt, 0, &lr, NULL, 0);
        for (UINT y = 0; y < h; y++) memcpy((BYTE *)lr.pBits + y * lr.Pitch, px + y * w * 4, w * 4);
        IDirect3DTexture8_UnlockRect(dirt, 0);
    }
    free(px);
    for (int k = 0; k < 2; k++) {
        make_ps(2 + k);
        if (FAILED(IDirect3DDevice8_CreatePixelShader(dev, code, &ps_debug[k]))) return log_line("look: ps failed"), 0;
    }
    if (FAILED(IDirect3DDevice8_CreateTexture(dev, 1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &white))) return 0;
    IDirect3DTexture8_LockRect(white, 0, &lr, NULL, 0);
    *(DWORD *)lr.pBits = 0xffffffff;
    IDirect3DTexture8_UnlockRect(white, 0);
    if (!make_targets(dev)) return 0;
    float t = 3.14159265f / 180, az = 45 * t, el = 38 * t; // Blender azimuth/elevation of the kit's sun; game y up
    sun[0] = cosf(el) * cosf(az), sun[1] = sinf(el), sun[2] = cosf(el) * sinf(az);
    failed = 0;
    log_line("look: shaders ready");
    return 1;
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

// Light rows for an orthographic map along the sun: centre, half sizes (side, up), depth range.
static void light_rows(float rows[3][4], float clip[4][4], const float ctr[3], float hw, float dmin, float dmax, float bias)
{
    float f[3] = { -sun[0], -sun[1], -sun[2] }, hint[3] = { 0, 0, 1 }, rt[3], up[3];
    rt[0] = hint[1] * f[2] - hint[2] * f[1], rt[1] = hint[2] * f[0] - hint[0] * f[2], rt[2] = hint[0] * f[1] - hint[1] * f[0];
    float l = sqrtf(dot3(rt, rt));
    for (int k = 0; k < 3; k++) rt[k] /= l;
    up[0] = f[1] * rt[2] - f[2] * rt[1], up[1] = f[2] * rt[0] - f[0] * rt[2], up[2] = f[0] * rt[1] - f[1] * rt[0];
    for (int k = 0; k < 3; k++) {
        rows[0][k] = rt[k] / (2 * hw), rows[1][k] = -up[k] / (2 * hw), rows[2][k] = f[k] / (dmax - dmin);
    }
    rows[0][3] = 0.5f - dot3(ctr, rt) / (2 * hw);
    rows[1][3] = 0.5f + dot3(ctr, up) / (2 * hw);
    rows[2][3] = -(dot3(ctr, f) + dmin) / (dmax - dmin);
    for (int k = 0; k < 4; k++) {
        clip[0][k] = 2 * rows[0][k] - (k == 3), clip[1][k] = -2 * rows[1][k] + (k == 3), clip[2][k] = rows[2][k], clip[3][k] = k == 3;
    }
    rows[2][3] -= bias;
}

static void consts(IDirect3DDevice8 *dev, const float clip[4][4], const float world[4][4], const float view[4][4], float scale)
{
    float c[20][4] = { 0 };
    memcpy(c[0], clip, 64);
    memcpy(c[4], built ? srows : (float[3][4]){ { 0, 0, 0, 0.5f }, { 0, 0, 0, 0.5f }, { 0, 0, 0, 0 } }, 48);
    memcpy(c[7], level >= 2 ? crows : (float[3][4]){ { 0, 0, 0, 0.5f }, { 0, 0, 0, 0.5f }, { 0, 0, 0, 0 } }, 48);
    if (world)
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 4; j++) c[10 + i][j] = world[j][i];
    memcpy(c[13], sun, 12);
    memcpy(c[14], (float[4]){ 0, 1, 0.5f, 1e-4f }, 16);
    memcpy(c[15], (float[4]){ 109 / 255.0f, 100 / 255.0f, 127 / 255.0f, 0 }, 16);
    if (view) for (int i = 0; i < 4; i++) c[16][i] = view[i][2];
    c[17][0] = 560000, c[17][1] = 1 / 504000.0f; // the zoo hub's fog (56000..560000)
    c[18][0] = c[18][1] = c[18][2] = scale, c[18][3] = 1;
    c[19][0] = 1 / 600.0f; // the kit's dirt repeats every 2.4 m
    IDirect3DDevice8_SetVertexShaderConstant(dev, 0, c, 20);
}

static void bind_shadows(IDirect3DDevice8 *dev)
{
    IDirect3DBaseTexture8 *t1 = built ? (IDirect3DBaseTexture8 *)smap : (IDirect3DBaseTexture8 *)white;
    IDirect3DBaseTexture8 *t2 = level >= 2 && cmap ? (IDirect3DBaseTexture8 *)cmap : (IDirect3DBaseTexture8 *)white;
    textures_bind_own(dev, 1, t1), textures_bind_own(dev, 2, t2);
    for (DWORD s = 1; s < 3; s++) {
        IDirect3DDevice8_SetTextureStageState(dev, s, D3DTSS_ADDRESSU, D3DTADDRESS_CLAMP);
        IDirect3DDevice8_SetTextureStageState(dev, s, D3DTSS_ADDRESSV, D3DTADDRESS_CLAMP);
        IDirect3DDevice8_SetTextureStageState(dev, s, D3DTSS_MAGFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, s, D3DTSS_MINFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, s, D3DTSS_MIPFILTER, D3DTEXF_NONE);
    }
}

// Visible chunks' instances, nearest-first thinning of the many small ones with distance.
static void draw_additions(IDirect3DDevice8 *dev, const float clip[4][4], const float *eye, int depth)
{
    IDirect3DDevice8_SetVertexShader(dev, depth ? vs_inst_depth : vs_inst);
    for (UINT i = 0; i < nchunks; i++) {
        struct chunk *k = &chunks[i];
        int out[6] = { 0 };
        for (int corner = 0; corner < 8; corner++) {
            float p[4] = { corner & 1 ? k->hi[0] : k->lo[0], corner & 2 ? k->hi[1] : k->lo[1], corner & 4 ? k->hi[2] : k->lo[2], 1 }, q[4];
            for (int a = 0; a < 4; a++) q[a] = dot3(clip[a], p) + clip[a][3];
            out[0] += q[0] < -q[3], out[1] += q[0] > q[3], out[2] += q[1] < -q[3], out[3] += q[1] > q[3], out[4] += q[2] < 0, out[5] += q[2] > q[3];
        }
        if (out[0] == 8 || out[1] == 8 || out[2] == 8 || out[3] == 8 || out[4] == 8 || out[5] == 8) continue;
        float keep = 1;
        if (eye) {
            float d = 0;
            for (int a = 0; a < 3; a++) {
                float e = eye[a] < k->lo[a] ? k->lo[a] - eye[a] : eye[a] > k->hi[a] ? eye[a] - k->hi[a] : 0;
                d += e * e;
            }
            d = sqrtf(d);
            keep = d < 2500 ? 1 : d > 9000 ? 0.08f : 1 - 0.92f * (d - 2500) / 6500;
        }
        for (UINT j = 0; j < k->nruns; j++) {
            struct run *run = &k->runs[j];
            struct proto *q = &protos[run->proto];
            UINT n = run->n > 1 ? (UINT)(run->n * keep + 0.999f) : run->n;
            IDirect3DDevice8_SetStreamSource(dev, 0, q->vb, 32);
            IDirect3DDevice8_SetIndices(dev, q->ib, 0);
            for (UINT s = 0; s < n; s += q->copies) {
                UINT b = n - s < q->copies ? n - s : q->copies;
                IDirect3DDevice8_SetVertexShaderConstant(dev, 20, run->m[s], b * 3);
                draw_indexed_real(dev, D3DPT_TRIANGLELIST, 0, b * q->nv, 0, b * q->ni / 3);
                stat_draws++, stat_tris += b * q->ni / 3;
            }
        }
    }
}

static void get_matrix(IDirect3DDevice8 *dev, D3DTRANSFORMSTATETYPE t, float o[4][4])
{
    IDirect3DDevice8_GetTransform(dev, t, (D3DMATRIX *)o);
}

// Inside the game's 3D pass, with its camera: the additions, depth-tested against what it drew.
static void inject(IDirect3DDevice8 *dev)
{
    DWORD sb;
    float view[4][4], proj[4][4], vp[4][4], clip[4][4], inv[3];
    if (FAILED(IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &sb))) return;
    get_matrix(dev, D3DTS_VIEW, view), get_matrix(dev, D3DTS_PROJECTION, proj);
    mul4(vp, view, proj), rows_of(clip, vp);
    for (int a = 0; a < 3; a++) inv[a] = -(view[3][0] * view[a][0] + view[3][1] * view[a][1] + view[3][2] * view[a][2]); // eye
    consts(dev, clip, NULL, view, 0.5f);
    float pc[2][4] = { { 0.95f, 0.9f, 0.8f, 0 }, { 0.5f, 0.55f, 0.62f, 1 } };
    IDirect3DDevice8_SetPixelShaderConstant(dev, 1, pc, 2);
    IDirect3DDevice8_SetPixelShader(dev, debug ? ps_debug[debug - 8] : ps);
    textures_bind_own(dev, 0, (IDirect3DBaseTexture8 *)white);
    bind_shadows(dev);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHATESTENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    draw_additions(dev, clip, inv, 0);
    IDirect3DDevice8_ApplyStateBlock(dev, sb);
    IDirect3DDevice8_DeleteStateBlock(dev, sb);
    look_state_changed(), last_m[0][0][0] = 1e30f;
}

// Renders depth from the sun into map (rt is its colour twin): the static world draws recorded,
// the additions, or the characters recorded this frame.
static void shadow_pass(IDirect3DDevice8 *dev, IDirect3DTexture8 *map, IDirect3DSurface8 *rt, UINT size, const float clip[4][4], int what)
{
    DWORD sb;
    IDirect3DSurface8 *ds, *old_rt = NULL, *old_ds = NULL;
    if (FAILED(IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &sb))) return;
    IDirect3DDevice8_BeginScene(dev);
    IDirect3DDevice8_GetRenderTarget(dev, &old_rt), IDirect3DDevice8_GetDepthStencilSurface(dev, &old_ds);
    IDirect3DTexture8_GetSurfaceLevel(map, 0, &ds);
    IDirect3DDevice8_SetRenderTarget(dev, rt, ds);
    D3DVIEWPORT8 vp = { 0, 0, size, size, 0, 1 };
    IDirect3DDevice8_SetViewport(dev, &vp);
    IDirect3DDevice8_Clear(dev, 0, NULL, D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHATESTENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_FOGENABLE, FALSE);
    IDirect3DDevice8_SetPixelShader(dev, 0);
    for (DWORD s = 0; s < 4; s++) textures_bind_own(dev, s, NULL);
    if (what == 0) {
        IDirect3DDevice8_SetVertexShader(dev, vs_world_depth);
        for (UINT i = 0; i < nrecs; i++) {
            float c[13][4] = { 0 };
            memcpy(c[0], clip, 64);
            for (int a = 0; a < 3; a++)
                for (int b = 0; b < 4; b++) c[10 + a][b] = recs[i].m[b][a];
            IDirect3DDevice8_SetVertexShaderConstant(dev, 0, c, 13);
            IDirect3DDevice8_SetStreamSource(dev, 0, recs[i].vb, recs[i].stride);
            draw_real(dev, recs[i].type, recs[i].start, recs[i].count);
        }
        IDirect3DDevice8_SetVertexShaderConstant(dev, 0, clip, 4);
        draw_additions(dev, clip, NULL, 1);
    } else { // characters with their own shaders, placed by the light instead of the camera
        for (UINT i = 0; i < nrecs; i++) {
            struct rec *e = &recs[i];
            float lc[4][4]; // light clip x world (both column form); world kept in m[88..91] by look_frame
            for (int a = 0; a < 4; a++)
                for (int b = 0; b < 4; b++) lc[a][b] = clip[a][0] * e->m[88][b] + clip[a][1] * e->m[89][b] + clip[a][2] * e->m[90][b] + clip[a][3] * e->m[91][b];
            IDirect3DDevice8_SetVertexShader(dev, e->shader);
            IDirect3DDevice8_SetVertexShaderConstant(dev, 0, e->m, 92);
            IDirect3DDevice8_SetVertexShaderConstant(dev, 92, lc, 4);
            IDirect3DDevice8_SetStreamSource(dev, 0, e->vb, e->stride);
            draw_real(dev, e->type, e->start, e->count);
        }
    }
    IDirect3DDevice8_SetRenderTarget(dev, old_rt, old_ds);
    IDirect3DDevice8_EndScene(dev);
    IDirect3DDevice8_ApplyStateBlock(dev, sb);
    IDirect3DDevice8_DeleteStateBlock(dev, sb);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0xf);
    if (ds) IDirect3DSurface8_Release(ds);
    if (old_rt) IDirect3DSurface8_Release(old_rt);
    if (old_ds) IDirect3DSurface8_Release(old_ds);
}

static void build_static(IDirect3DDevice8 *dev)
{
    // The play area: chunks within 7000 units of the additions' centre of mass (the far cliffs and hills keep
    // the map from covering what the player walks on otherwise).
    float ctr[3] = { 0 }, hw = 0;
    for (UINT i = 0; i < nchunks; i++)
        for (int a = 0; a < 3; a++) ctr[a] += (chunks[i].lo[a] + chunks[i].hi[a]) / 2 / nchunks;
    for (UINT i = 0; i < nchunks; i++) {
        float d = 0;
        for (int a = 0; a < 3; a += 2) d += powf((chunks[i].lo[a] + chunks[i].hi[a]) / 2 - ctr[a], 2);
        if (sqrtf(d) < 7000 && sqrtf(d) + 1000 > hw) hw = sqrtf(d) + 1000;
    }
    double t0 = now_ms();
    light_rows(srows, sclip, ctr, hw, -2 * hw, 2 * hw, 0.001f);
    shadow_pass(dev, smap, smap_rt, SMAP, sclip, 0);
    built = 1;
    log_line("look: static shadow map from %u world draws and the additions, %.0f units across, %.1f ms", nrecs, 2 * hw, now_ms() - t0);
    for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
    nrecs = 0;
}

static int hidden(UINT64 h)
{
    UINT n = level >= 2 ? nhide_all : nhide;
    for (UINT i = 0; i < n; i++)
        if (hide[i] == h) return 1;
    return 0;
}

static struct rec *add_rec(void)
{
    if (nrecs == cap_recs) {
        struct rec *grown = realloc(recs, (cap_recs = cap_recs ? cap_recs * 2 : 1024) * sizeof *recs);
        if (!grown) return NULL;
        recs = grown;
    }
    return &recs[nrecs++];
}

// Before each game draw. Returns 1 to skip it. A world draw it can light is drawn here (returns 1).
int look_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    stat_game++;
    if (!level || !protos || !ps || in_grade) return 0;
    double t0 = now_ms();
    DWORD shader, value;
    int result = 0;
    if (level >= 2 && built && !recording && merge_draw(dev, api, type, start, count)) { result = 1; goto done; }
    if (!merge_on_backbuffer()) goto done;
    IDirect3DDevice8_GetVertexShader(dev, &shader);
    if (IS_VERTEX_SHADER(shader)) {
        seen_vs = 1;
        last_m[0][0][0] = 1e30f; // characters load their own constants
        IDirect3DDevice8_GetRenderState(dev, D3DRS_CULLMODE, &value);
        IDirect3DVertexBuffer8 *vb;
        UINT stride;
        struct rec *e;
        if (level >= 2 && built && api == 0 && value != D3DCULL_CW && SUCCEEDED(IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride)) && vb) {
            if (!(e = add_rec())) { IDirect3DVertexBuffer8_Release(vb); goto done; }
            e->vb = vb, e->shader = shader, e->stride = stride, e->start = start, e->count = count, e->type = type;
            IDirect3DDevice8_GetVertexShaderConstant(dev, 0, e->m, 96);
        }
        goto done;
    }
    if ((shader & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW) {
        if (!injected && seen_vs) injected = 1, inject(dev); // no blended world pass this frame: before the 2D
        goto done;
    }
    UINT64 h = textures_bound_hash(0);
    if (h && hidden(h)) { result = 1; goto done; }
    float world[4][4];
    get_matrix(dev, D3DTS_WORLD, world);
    float pv[4][4], pp[4][4];
    get_matrix(dev, D3DTS_VIEW, pv), get_matrix(dev, D3DTS_PROJECTION, pp);
    if (pp[2][3] == 1) memcpy(cam_view, pv, 64), memcpy(cam_proj, pp, 64); // perspective: the camera (a few later draws are flat 2D)
    IDirect3DDevice8_GetRenderState(dev, D3DRS_ALPHABLENDENABLE, &value);
    int ident = world[0][0] == 1 && world[1][1] == 1 && world[2][2] == 1 && !world[3][0] && !world[3][1] && !world[3][2];
    if (value && ident && seen_vs && !injected) injected = 1, inject(dev); // the game's blended world pass starts
    if (level < 2 || api != 0 || shader != 0x152) goto done;
    DWORD op0, a1, a2, op1;
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLOROP, &op0);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLORARG1, &a1);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLORARG2, &a2);
    IDirect3DDevice8_GetTextureStageState(dev, 1, D3DTSS_COLOROP, &op1);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, &value);
    if (op0 != D3DTOP_MODULATE2X || a1 != D3DTA_TEXTURE || op1 != D3DTOP_DISABLE || !textures_bound(0) || value) goto done; // scrolling: needs the transform
    IDirect3DDevice8_GetRenderState(dev, D3DRS_ALPHABLENDENABLE, &value);
    IDirect3DVertexBuffer8 *vb;
    UINT stride;
    if (recording && !value && SUCCEEDED(IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride)) && vb) {
        struct rec *e = add_rec();
        if (e) e->vb = vb, e->stride = stride, e->start = start, e->count = count, e->type = type, memcpy(e->m, world, 64);
        else IDirect3DVertexBuffer8_Release(vb);
    }
    if (memcmp(last_m[0], world, 64) || memcmp(last_m[1], pv, 64) || memcmp(last_m[2], pp, 64)) {
        float vp[4][4], clip[4][4];
        mul4(vp, pv, pp), rows_of(clip, vp);
        consts(dev, clip, world, pv, 1);
        memcpy(last_m[0], world, 64), memcpy(last_m[1], pv, 64), memcpy(last_m[2], pp, 64);
    }
    float pc[2][4] = { { 0.7f, 0.66f, 0.58f, 0 }, { 0.5f, 0.53f, 0.6f, 1 } };
    IDirect3DDevice8_SetPixelShaderConstant(dev, 1, pc, 2);
    if (!bound_ok) bind_shadows(dev), bound_ok = 1;
    int is_ground = 0;
    for (UINT i = 0; level >= 3 && dirt && i < nground; i++) is_ground |= ground[i] == h;
    if (is_ground && !ground_ok) {
        textures_bind_own(dev, 3, (IDirect3DBaseTexture8 *)dirt);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_ADDRESSU, D3DTADDRESS_WRAP);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_ADDRESSV, D3DTADDRESS_WRAP);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MAGFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MINFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MIPFILTER, D3DTEXF_NONE);
        ground_ok = bound_ok = 1; // the calls above went through the hook, which clears both
    }
    IDirect3DDevice8_SetVertexShader(dev, vs_world);
    IDirect3DDevice8_SetPixelShader(dev, debug ? ps_debug[debug - 8] : is_ground ? ps_ground : ps);
    draw_real(dev, type, start, count);
    IDirect3DDevice8_SetPixelShader(dev, 0);
    IDirect3DDevice8_SetVertexShader(dev, shader); // our stage 1-3 textures stay: the game's draws here leave those stages off
    stat_world++;
    result = 1;
done:
    m.look_ms += now_ms() - t0;
    return result;
}

int look_hidden(UINT64 h) { return hidden(h); }

// The merged static world: state as the per-draw path above sets it, once per flush.
void look_merge_begin(IDirect3DDevice8 *dev, IDirect3DVertexBuffer8 *vb, IDirect3DIndexBuffer8 *ib)
{
    static const float identity[4][4] = { { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, 0, 1 } };
    float pv[4][4], pp[4][4], vp[4][4], clip[4][4];
    if (!merge_sb) IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &merge_sb);
    else IDirect3DDevice8_CaptureStateBlock(dev, merge_sb);
    get_matrix(dev, D3DTS_VIEW, pv), get_matrix(dev, D3DTS_PROJECTION, pp);
    if (pp[2][3] == 1) memcpy(cam_view, pv, 64), memcpy(cam_proj, pp, 64);
    mul4(vp, pv, pp), rows_of(clip, vp);
    consts(dev, clip, identity, pv, 1);
    float pc[2][4] = { { 0.7f, 0.66f, 0.58f, 0 }, { 0.5f, 0.53f, 0.6f, 1 } };
    IDirect3DDevice8_SetPixelShaderConstant(dev, 1, pc, 2);
    bind_shadows(dev);
    if (level >= 3 && dirt) {
        textures_bind_own(dev, 3, (IDirect3DBaseTexture8 *)dirt);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_ADDRESSU, D3DTADDRESS_WRAP);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_ADDRESSV, D3DTADDRESS_WRAP);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MAGFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MINFILTER, D3DTEXF_LINEAR);
        IDirect3DDevice8_SetTextureStageState(dev, 3, D3DTSS_MIPFILTER, D3DTEXF_NONE);
    }
    IDirect3DDevice8_SetVertexShader(dev, vs_world);
    IDirect3DDevice8_SetStreamSource(dev, 0, vb, 36);
    IDirect3DDevice8_SetIndices(dev, ib, 0);
}

void look_merge_texture(IDirect3DDevice8 *dev, IDirect3DBaseTexture8 *tex, UINT64 hash)
{
    int is_ground = 0;
    for (UINT i = 0; level >= 3 && dirt && i < nground; i++) is_ground |= ground[i] == hash;
    textures_bind_own(dev, 0, textures_effective(tex));
    IDirect3DDevice8_SetPixelShader(dev, debug ? ps_debug[debug - 8] : is_ground ? ps_ground : ps);
}

void look_merge_draw(IDirect3DDevice8 *dev, UINT nverts, UINT first, UINT tris)
{
    draw_indexed_real(dev, D3DPT_TRIANGLELIST, 0, nverts, first, tris);
    stat_world++;
}

void look_merge_end(IDirect3DDevice8 *dev)
{
    if (merge_sb) IDirect3DDevice8_ApplyStateBlock(dev, merge_sb);
    look_state_changed(), last_m[0][0][0] = 1e30f;
}

// Level 3: the finished frame (HUD included, for now) through the grade.
static void grade(IDirect3DDevice8 *dev)
{
    IDirect3DSurface8 *bb = NULL, *s = NULL;
    D3DSURFACE_DESC d;
    DWORD sb;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    static UINT fw, fh;
    if (frame_tex && (fw != d.Width || fh != d.Height)) IDirect3DTexture8_Release(frame_tex), frame_tex = NULL;
    if (!frame_tex && SUCCEEDED(IDirect3DDevice8_CreateTexture(dev, d.Width, d.Height, 1, D3DUSAGE_RENDERTARGET, d.Format, D3DPOOL_DEFAULT, &frame_tex)))
        fw = d.Width, fh = d.Height;
    if (frame_tex && SUCCEEDED(IDirect3DTexture8_GetSurfaceLevel(frame_tex, 0, &s)) && SUCCEEDED(IDirect3DDevice8_CopyRects(dev, bb, NULL, 0, s, NULL))
        && SUCCEEDED(IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &sb))) {
        in_grade = 1;
        IDirect3DDevice8_BeginScene(dev);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_ZENABLE, FALSE);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHATESTENABLE, FALSE);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_FOGENABLE, FALSE);
        IDirect3DDevice8_SetRenderState(dev, D3DRS_STENCILENABLE, FALSE);
        IDirect3DDevice8_SetVertexShader(dev, FVF);
        IDirect3DDevice8_SetPixelShader(dev, ps_grade);
        float pc[4][4] = { { 0.3f, 0.59f, 0.11f, 0 }, { 0.28f, 0.28f, 0.28f, 0 }, { 0.08f, 0.08f, 0.08f, 0 }, { 0.45f, 0.45f, 0.45f, 0 } };
        IDirect3DDevice8_SetPixelShaderConstant(dev, 0, pc, 4);
        textures_bind_own(dev, 0, (IDirect3DBaseTexture8 *)frame_tex);
        IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_MAGFILTER, D3DTEXF_POINT);
        IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_MINFILTER, D3DTEXF_POINT);
        IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
        float W = (float)d.Width - 0.5f, H = (float)d.Height - 0.5f;
        struct vertex q[4] = { { -0.5f, -0.5f, 0, 1, ~0u, 0, 0 }, { W, -0.5f, 0, 1, ~0u, 1, 0 }, { -0.5f, H, 0, 1, ~0u, 0, 1 }, { W, H, 0, 1, ~0u, 1, 1 } };
        IDirect3DDevice8_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, q, sizeof *q);
        IDirect3DDevice8_EndScene(dev);
        IDirect3DDevice8_ApplyStateBlock(dev, sb);
        IDirect3DDevice8_DeleteStateBlock(dev, sb);
        in_grade = 0;
    }
    if (s) IDirect3DSurface8_Release(s);
    IDirect3DSurface8_Release(bb);
}

// At Present: level and data, shadow maps, measurements.
void look_frame(IDirect3DDevice8 *dev)
{
    FILE *f = settings.tests ? fopen("taz-hd\\look", "r") : NULL;
    if (f) {
        int n = level;
        fscanf(f, "%d", &n);
        fclose(f);
        DeleteFileA("taz-hd\\look");
        if (n != level) log_line("look: level %d", n), merge_reset();
        debug = n >= 8 ? n : 0;
        level = n >= 8 ? 2 : n;
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
    if (protos && (scene != loaded_scene || !level)) unload(), loaded_scene = -1;
    if (level && !protos && scene >= 2 && scene != loaded_scene && ready(dev)) {
        loaded_scene = scene;
        if (!load(dev, scene)) unload();
    }
    if (protos && level >= 2 && make_targets(dev)) {
        if (!built && recording && nrecs) build_static(dev), recording = 0; // a loading frame draws no world: keep recording
        else if (!built && !recording) { // record this frame's world draws for the static map
            for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
            nrecs = 0, recording = 1;
        } else if (nrecs) { // characters: a small map around player one, every frame
            float ctr[3] = { 0 }, best = 0;
            int found = 0;
            float vp[4][4], vpc[4][4], a[4][8];
            mul4(vp, cam_view, cam_proj), rows_of(vpc, vp);
            for (int y = 0; y < 4; y++) // invert the camera's (column form) view x projection
                for (int x = 0; x < 8; x++) a[y][x] = x < 4 ? vpc[y][x] : (x - 4 == y);
            for (int col = 0; col < 4; col++) {
                int piv = col;
                for (int y = col + 1; y < 4; y++) if (fabsf(a[y][col]) > fabsf(a[piv][col])) piv = y;
                for (int x = 0; x < 8; x++) { float tmp = a[col][x]; a[col][x] = a[piv][x]; a[piv][x] = tmp; }
                float d = a[col][col];
                for (int x = 0; x < 8; x++) a[col][x] /= d;
                for (int y = 0; y < 4; y++)
                    if (y != col) {
                        float k = a[y][col];
                        for (int x = 0; x < 8; x++) a[y][x] -= k * a[col][x];
                    }
            }
            for (UINT i = 0; i < nrecs; i++) { // c92-c95 are (world x view x projection), transposed: world = inv(VP) x that
                struct rec *e = &recs[i];
                for (int y = 0; y < 4; y++)
                    for (int x = 0; x < 4; x++)
                        e->m[88 + y][x] = a[y][4] * e->m[92][x] + a[y][5] * e->m[93][x] + a[y][6] * e->m[94][x] + a[y][7] * e->m[95][x];
                float d = 0, eye[3];
                for (int k = 0; k < 3; k++) eye[k] = -(cam_view[3][0] * cam_view[k][0] + cam_view[3][1] * cam_view[k][1] + cam_view[3][2] * cam_view[k][2]);
                for (int k = 0; k < 3; k++) d += powf(e->m[88 + k][3] - eye[k], 2);
                if (!found || d < best) found = 1, best = d, ctr[0] = e->m[88][3], ctr[1] = e->m[89][3], ctr[2] = e->m[90][3]; // nearest: player one
            }
            if (found) {
                light_rows(crows, cclip, ctr, 1400, -3000, 3000, 0.002f);
                shadow_pass(dev, cmap, cmap_rt, CMAP, cclip, 1);
                static int told;
                if (!told++) log_line("look: character shadow map: %u draws around %.0f %.0f %.0f", nrecs, ctr[0], ctr[1], ctr[2]);
            }
            for (UINT i = 0; i < nrecs; i++) IDirect3DVertexBuffer8_Release(recs[i].vb);
            nrecs = 0;
        }
    }
    if (protos && level >= 3 && ps_grade) grade(dev);
    m.look_ms += now_ms() - t0;
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    if (m.frames < 0 && ++m.frames == 0) QueryPerformanceCounter(&m.last), m.look_ms = 0, m.draws = m.tris = m.world = m.game = m.pieces = m.merged = 0;
    else if (m.frames >= 0 && m.last.QuadPart) {
        m.frames++, m.draws += stat_draws, m.tris += stat_tris, m.world += stat_world, m.game += stat_game, m.pieces += merge_stat_pieces, m.merged += merge_stat_draws;
        if (m.frames == m.want) {
            LARGE_INTEGER fq;
            QueryPerformanceFrequency(&fq);
            double ms = (t.QuadPart - m.last.QuadPart) * 1000.0 / fq.QuadPart / m.frames;
            log_line("look: measured level %d: %.2f ms/frame (%.1f fps), look code %.2f ms, Present %.2f ms, additions %u draws %u triangles, %u world draws lit, game issued %u draws, %u of them merged into %u, address space free %lu MB",
                     level, ms, 1000 / ms, m.look_ms / m.frames, m.present_ms / m.frames, m.draws / m.frames, m.tris / m.frames, m.world / m.frames, m.game / m.frames, m.pieces / m.frames, m.merged / m.frames, avail_mb());
            m.last.QuadPart = 0;
        }
    }
    stat_draws = stat_tris = stat_world = stat_game = merge_stat_pieces = merge_stat_draws = 0;
    injected = seen_vs = 0;
    look_state_changed(), last_m[0][0][0] = 1e30f;
    if (protos) // stages 1-3 back to none for the frame's first draws (menus, 2D)
        for (DWORD st = 1; st < 4; st++) textures_bind_own(dev, st, NULL);
}

void look_present_ms(double ms)
{
    if (m.frames > 0 && m.last.QuadPart) m.present_ms += ms;
}
