// Taz styles (setting taz_style): other looks for player one's Taz, drawn with our own shaders in
// place of the game's. The game lights characters per vertex through a 2-tone ramp texture (u = N.L)
// and outlines them with a second pass pushed out along the normals. Ours light per pixel from
// lookup textures made here: (N.L, N.V) gives the shading and a rim light, N.H a highlight on the
// eyes and nose, and a fur pattern mapped from the bind pose (so it sticks to the body) breaks up his
// coat. The outline thins on the lit side and, in Fur Detail, zigzags over the brown fur. Draw state
// is put back after each draw, so nothing else sees our shaders or textures.
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "game.h"

enum { CURRENT, CARTOON, SOFT, FUR, STYLES };

// Shader tokens (D3D8 vs_1_1 / ps_1_4).
enum { RT_TEMP, RT_INPUT, RT_CONST, RT_ADDR, RT_RASTOUT, RT_ATTROUT, RT_TEXCRDOUT };
#define RT_TEX RT_ADDR // pixel shader texture coordinates share the type number
#define REG(t, n) ((DWORD)(t) << 28 | (DWORD)(n))
#define r(n) REG(RT_TEMP, n)
#define v(n) REG(RT_INPUT, n)
#define c(n) REG(RT_CONST, n)
#define t(n) REG(RT_TEX, n)
#define oT(n) REG(RT_TEXCRDOUT, n)
#define oD(n) REG(RT_ATTROUT, n)
#define oPos REG(RT_RASTOUT, 0)
#define oFog REG(RT_RASTOUT, 1)
#define a0 REG(RT_ADDR, 0)
enum { X = 1, Y = 2, Z = 4, W = 8, XYZ = 7, ALL = 15 };
#define SW(a, b, c, d) ((a) | (b) << 2 | (c) << 4 | (d) << 6)
#define D(reg, mask) (0x80000000u | (reg) | (DWORD)(mask) << 16)          // destination
#define S(reg) (0x80000000u | (reg) | (DWORD)SW(0, 1, 2, 3) << 16)        // source
#define SR(reg, k) (0x80000000u | (reg) | (DWORD)SW(k, k, k, k) << 16)    // source, one component
#define NEG (1u << 24)
#define COMP (6u << 24) // pixel shader source: 1 - x
#define REL (1u << 13)
#define X2 (1u << 24) // destination shift: result times 2
enum { MOV = 1, ADD, SUB, MAD, MUL, RCP, RSQ, DP3, DP4, MIN, MAX, LRP = 18, TEXCRD = 0x40, TEXLD = 0x42, EXPP = 0x4e, PHASE = 0xfffd };

static DWORD code[512]; // the outline shader is ~260 tokens
static int len;
static void op(DWORD o, DWORD d, DWORD s0, DWORD s1, DWORD s2, int n) // n operands after the destination
{
    code[len++] = o;
    code[len++] = d;
    if (n > 0) code[len++] = s0;
    if (n > 1) code[len++] = s1;
    if (n > 2) code[len++] = s2;
}
#define OP1(o, d, a) op(o, d, a, 0, 0, 1)
#define OP2(o, d, a, b) op(o, d, a, b, 0, 2)
#define OP3(o, d, a, b, cc) op(o, d, a, b, cc, 3)

// Skinning as the game's shaders do it: up to 3 bones (palette offsets in v2, weights in v1), world
// position in r0 (w = 1), unit normal in r2.
static void skin(void)
{
    for (int k = 0; k < 3; k++) {
        OP1(MOV, D(a0, X), SR(v(2), k));
        for (int row = 0; row < 3; row++) OP2(DP4, D(r(1), 1 << row), S(v(0)), S(c(row)) | REL);
        for (int row = 0; row < 3; row++) OP2(DP3, D(r(3), 1 << row), S(v(3)), S(c(row)) | REL);
        if (!k) {
            OP2(MUL, D(r(0), XYZ), S(r(1)), SR(v(1), 0));
            OP2(MUL, D(r(2), XYZ), S(r(3)), SR(v(1), 0));
        } else {
            OP3(MAD, D(r(0), XYZ), S(r(1)), SR(v(1), k), S(r(0)));
            OP3(MAD, D(r(2), XYZ), S(r(3)), SR(v(1), k), S(r(2)));
        }
    }
    OP1(MOV, D(r(0), W), SR(v(0), 3));
    OP2(DP3, D(r(2), W), S(r(2)), S(r(2)));
    OP1(RSQ, D(r(2), W), SR(r(2), 3));
    OP2(MUL, D(r(2), XYZ), S(r(2)), SR(r(2), 3));
}

// Fog and position as the game does, with the camera position in cam and fog range in fog.
static void finish(int cam, int fog)
{
    OP2(ADD, D(r(4), XYZ), S(c(cam)), S(r(0)) | NEG);
    OP2(DP3, D(r(4), W), S(r(4)), S(r(4)));
    OP1(RSQ, D(r(5), W), SR(r(4), 3));
    OP1(RCP, D(r(5), X), SR(r(5), 3));
    OP2(ADD, D(r(5), X), SR(c(fog), 0), SR(r(5), 0) | NEG);
    OP2(MUL, D(oFog, X), SR(r(5), 0), SR(c(fog), 1));
    for (int k = 0; k < 4; k++) OP2(DP4, D(oPos, 1 << k), S(r(0)), S(c(92 + k)));
    OP1(MOV, D(oT(0), X | Y), S(v(5)));
}

// Constants we add: c80 light (kept from the lit pass for the outline), c81 outline (N.L slope,
// width at N.L = 0, thinnest, 0), c82 outline colour, c83 fur map scale (x, y), c84 and c85 tuft
// waves (direction / period), c86 (0.5, tuft height, 0, threshold), c87 (|x| where tufts end, 1 /
// fade length, 0, 1), c88 fur map mix (slope, offset).

// Tufts: two crossing triangle waves over the bind pose; where both are high, r3.y (world units) is
// how far the outline juts out, so it zigzags like inked fur. (Pushing the body out the same way
// made ragged shards, not tufts.)
static void tuft(void)
{
    for (int k = 0; k < 2; k++) {
        OP2(DP3, D(r(5 + k), X), S(v(0)), S(c(84 + k)));
        OP1(EXPP, D(r(5 + k), Y), SR(r(5 + k), 0));                 // fraction
        OP2(ADD, D(r(5 + k), Y), SR(r(5 + k), 1), SR(c(86), 0) | NEG);
        OP2(MAX, D(r(5 + k), Y), SR(r(5 + k), 1), SR(r(5 + k), 1) | NEG);
    }
    OP2(ADD, D(r(5), Y), SR(r(5), 1), SR(r(6), 1));
    OP2(ADD, D(r(5), Y), SR(r(5), 1), SR(c(86), 3) | NEG);
    OP2(MAX, D(r(5), Y), SR(r(5), 1), SR(c(86), 2));
    OP2(MUL, D(r(3), Y), SR(r(5), 1), SR(c(86), 1));
    OP2(MAX, D(r(5), X), SR(v(0), 0), SR(v(0), 0) | NEG);           // none on the hands: fade out along the arms
    OP2(ADD, D(r(5), X), SR(c(87), 0), SR(r(5), 0) | NEG);
    OP2(MUL, D(r(5), X), SR(r(5), 0), SR(c(87), 1));
    OP2(MIN, D(r(5), X), SR(r(5), 0), SR(c(87), 3));
    OP2(MAX, D(r(5), X), SR(r(5), 0), SR(c(86), 2));
    OP2(MUL, D(r(3), Y), SR(r(3), 1), SR(r(5), 0));
}

static void make_lit_vs(void)
{
    len = 0;
    code[len++] = 0xfffe0101;
    skin();
    finish(49, 50);                                         // r4.xyz = to camera, r5.w = 1 / distance
    OP2(MUL, D(r(4), XYZ), S(r(4)), SR(r(5), 3));           // V
    OP2(ADD, D(r(6), XYZ), S(c(48)), S(r(4)));
    OP2(DP3, D(r(6), W), S(r(6)), S(r(6)));
    OP1(RSQ, D(r(6), W), SR(r(6), 3));
    OP2(MUL, D(oT(3), XYZ), S(r(6)), SR(r(6), 3));          // H
    OP1(MOV, D(oT(1), XYZ), S(r(2)));                       // N
    OP1(MOV, D(oT(2), XYZ), S(r(4)));
    OP2(MUL, D(oT(4), X | Y), S(v(0)), S(c(83)));            // fur, front: bind x, y
    OP1(MOV, D(r(8), X), SR(v(0), 2));                      // fur, side: bind z, y + x / 2, so his top isn't streaks
    OP3(MAD, D(r(8), Y), SR(v(0), 0), SR(c(83), 2), SR(v(0), 1)); // (a third map for the top swirled where it met this one)
    OP2(MUL, D(oT(5), X | Y), S(r(8)), S(c(83)));
    OP2(MUL, D(r(7), X), SR(v(3), 2), SR(v(3), 2));         // how much it faces front or back, steepened so
    OP3(MAD, D(oD(1), ALL), SR(r(7), 0), SR(c(88), 0), SR(c(88), 1)); // the two maps only mix in a narrow band (half and half wove a cross-hatch)
    OP2(MUL, D(oD(0), ALL), S(v(4)), S(c(51)));
    code[len++] = 0xffff;
}

static void make_outline_vs(void)
{
    len = 0;
    code[len++] = 0xfffe0101;
    skin();
    OP2(DP3, D(r(3), X), S(r(2)), S(c(80)));
    OP3(MAD, D(r(3), X), SR(r(3), 0), SR(c(81), 0), SR(c(81), 1));
    OP2(MAX, D(r(3), X), SR(r(3), 0), SR(c(81), 2));
    tuft();
    OP3(MAD, D(r(3), X), SR(r(3), 0), SR(c(49), 3), SR(r(3), 1));
    OP3(MAD, D(r(0), XYZ), S(r(2)), SR(r(3), 0), S(r(0)));
    OP1(MOV, D(oD(0), ALL), S(c(82)));
    finish(50, 51);
    code[len++] = 0xffff;
}

// c0 light, c2 0.5, c3 highlight colour, c4 fur strength, c5 highlight row.
static void make_ps(void)
{
    len = 0;
    code[len++] = 0xffff0104;
    OP1(TEXCRD, D(r(1), XYZ), S(t(1)));
    OP1(TEXCRD, D(r(2), XYZ), S(t(2)));
    OP1(TEXCRD, D(r(3), XYZ), S(t(3)));
    OP2(DP3, D(r(4), X), S(r(1)), S(c(0)));                 // N.L
    OP2(DP3, D(r(4), Y), S(r(1)), S(r(2)));                 // N.V
    OP3(MAD, D(r(4), X), S(r(4)), S(c(2)), S(c(2)));        // to 0..1
    OP2(DP3, D(r(5), X), S(r(1)), S(r(3)));                 // N.H
    OP1(MOV, D(r(5), Y), S(c(5)));
    code[len++] = PHASE;
    OP1(TEXLD, D(r(0), ALL), S(t(0)));
    OP1(TEXLD, D(r(2), ALL), S(t(5)));
    OP1(TEXLD, D(r(3), ALL), S(t(4)));
    OP1(TEXLD, D(r(4), ALL), S(r(4)));
    OP1(TEXLD, D(r(5), ALL), S(r(5)));
    OP2(MUL, D(r(5), XYZ), S(r(5)), S(r(0)) | COMP);        // highlight on dark paint only: the nose and pupils, not the cream around them
    OP3(LRP, D(r(3), ALL), SR(v(1), 3), S(r(3)), S(r(2)));  // fur, front and side maps blended
    OP3(LRP, D(r(3), ALL), S(c(4)), S(r(3)), S(c(2)));      // 0.5 is no change
    OP2(MUL, D(r(0), ALL) | X2, S(r(0)), S(v(0)));          // as the game: texture x colour x 2
    OP2(MUL, D(r(0), XYZ) | X2, S(r(0)), S(r(3)));
    OP2(MUL, D(r(0), XYZ) | X2, S(r(0)), S(r(4)));          // shading, stored halved
    OP3(MAD, D(r(0), XYZ), SR(r(4), 3), S(r(0)), S(r(0)));  // rim: a lighter shade of the fur (added cream light turned the brown pink)
    OP3(MAD, D(r(0), XYZ), S(r(5)), S(c(3)), S(r(0)));      // highlight
    code[len++] = 0xffff;
}

static float clamp01(float x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
static float smooth(float a, float b, float x) { x = clamp01((x - a) / (b - a)); return x * x * (3 - 2 * x); }
static float mix(float a, float b, float k) { return a + (b - a) * k; }
static BYTE to_byte(float x) { return (BYTE)(clamp01(x) * 255 + 0.5f); }

#define LW 256
#define LH 64
// Shading lookup: u = N.L (-1..1 as 0..1), v = N.V. Colour is the light (halved), alpha the rim.
static void shade(int style, float nl, float nv, float *rgb, float *rim)
{
    if (style == SOFT) {
        float d = smooth(-0.55f, 0.9f, nl), warm = expf(-(nl * nl) / 0.06f) * 0.05f;
        rgb[0] = mix(0.56f, 1.10f, d) + warm, rgb[1] = mix(0.54f, 1.08f, d) + warm * 0.4f, rgb[2] = mix(0.68f, 1.04f, d);
        *rim = powf(1 - nv, 3) * (0.12f + 0.25f * smooth(-0.6f, 0.6f, nl));
        return;
    }
    float lit = smooth(0.0f, 0.06f, nl), top = smooth(0.9f, 0.93f, nl) * 0.06f;
    rgb[0] = mix(0.78f, 1.0f, lit) + top, rgb[1] = mix(0.72f, 1.0f, lit) + top, rgb[2] = mix(0.66f, 1.0f, lit) + top; // warm shadow; a bluish one greyed the cream
    *rim = smooth(0.3f, 0.24f, nv) * smooth(-0.3f, 0.2f, nl) * 0.3f;
}

// Highlight lookup: u = N.H; top rows broad (soft style's sheen), bottom rows a small sharp dot.
static float shine(int style, int sharp, float nh)
{
    if (sharp) return style == SOFT ? powf(nh, 160) + powf(nh, 24) * 0.25f : smooth(0.972f, 0.98f, nh);
    return style == SOFT ? powf(nh, 18) : 0;
}

static IDirect3DTexture8 *make_texture(IDirect3DDevice8 *dev, UINT w, UINT h, UINT levels, const BYTE *bgra)
{
    IDirect3DTexture8 *t;
    D3DLOCKED_RECT lr;
    if (FAILED(IDirect3DDevice8_CreateTexture(dev, w, h, levels, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t))) return NULL;
    BYTE *px = malloc(w * h * 4);
    memcpy(px, bgra, w * h * 4);
    for (UINT l = 0; l < levels; l++) {
        if (SUCCEEDED(IDirect3DTexture8_LockRect(t, l, &lr, NULL, 0))) {
            for (UINT y = 0; y < h; y++) memcpy((BYTE *)lr.pBits + y * lr.Pitch, px + y * w * 4, w * 4);
            IDirect3DTexture8_UnlockRect(t, l);
        }
        for (UINT y = 0; y < h / 2; y++) // next level: 2x2 averages
            for (UINT x = 0; x < w / 2; x++)
                for (int k = 0; k < 4; k++)
                    px[(y * (w / 2) + x) * 4 + k] = (px[(2 * y * w + 2 * x) * 4 + k] + px[(2 * y * w + 2 * x + 1) * 4 + k]
                                                    + px[((2 * y + 1) * w + 2 * x) * 4 + k] + px[((2 * y + 1) * w + 2 * x + 1) * 4 + k] + 2) / 4;
        w /= 2, h /= 2;
    }
    free(px);
    return t;
}

// Fur: a tiling grey pattern around 0.5 of layered pointed tufts hanging down, each lit on one side,
// shaded on the other and darker towards its tip.
#define FW 128
static float rnd(void)
{
    static unsigned seed = 12345;
    return ((seed = seed * 1103515245u + 12345u) >> 8 & 0xffff) / 65535.0f;
}

static IDirect3DTexture8 *make_fur(IDirect3DDevice8 *dev)
{
    static float f[FW][FW];
    static BYTE px[FW * FW * 4];
    for (int y = 0; y < FW; y++)
        for (int x = 0; x < FW; x++) f[y][x] = 0.5f;
    for (int i = 0; i < 420; i++) {
        float cx = rnd() * FW, cy = rnd() * FW, w = 3 + rnd() * 3.5f, len = 12 + rnd() * 10, tilt = (rnd() - 0.5f) * 0.6f, base = (rnd() - 0.5f) * 0.06f;
        for (int yy = 0; yy <= len; yy++) {
            float v = yy / len, half = w * powf(1 - v, 0.8f), xc = cx + tilt * yy;
            for (int xx = (int)(xc - half) - 1; xx <= (int)(xc + half) + 1; xx++) {
                float u = (xx + 0.5f - xc) / (half > 0.3f ? half : 0.3f);
                if (fabsf(u) > 1) continue;
                float edge = clamp01((1 - fabsf(u)) * half * 0.9f), val = 0.5f + base - 0.1f * u - 0.08f * v;
                float *at = &f[(int)(cy + yy) % FW][(xx % FW + FW) % FW];
                *at += (val - *at) * edge;
            }
        }
    }
    for (int y = 0; y < FW; y++)
        for (int x = 0; x < FW; x++) {
            BYTE g = to_byte(f[y][x]), *p = px + (y * FW + x) * 4;
            p[0] = p[1] = p[2] = g, p[3] = 255;
        }
    return make_texture(dev, FW, FW, 8, px);
}

// Taz's open eye (eyeblink3.frame0) redrawn crisp, with a catchlight in the pupil.
#define EW 128
static IDirect3DTexture8 *make_eye(IDirect3DDevice8 *dev)
{
    static BYTE px[EW * EW * 4];
    for (int y = 0; y < EW; y++)
        for (int x = 0; x < EW; x++) {
            float u = (x + 0.5f) / EW, v = (y + 0.5f) / EW;
            float pupil = hypotf(u - 0.511f, v - 0.477f), shine = hypotf(u - 0.488f, v - 0.452f);
            float g = clamp01((pupil - 0.082f) * EW) + clamp01((0.026f - shine) * EW); // 1 px soft edges
            BYTE *p = px + (y * EW + x) * 4;
            p[0] = p[1] = p[2] = to_byte(g), p[3] = 255;
        }
    return make_texture(dev, EW, EW, 8, px);
}

static struct { IDirect3DTexture8 *light, *shine; } looks[STYLES];
static IDirect3DTexture8 *fur, *eye;
static DWORD lit_vs, outline_vs, ps, lit_shader, outline_shader;
static int failed;
static float light[4] = { 0.7f, 0.2f, -0.7f, 0 };
int style_player; // set by mesh.c while it draws player one's model

static int ready(IDirect3DDevice8 *dev)
{
    if (lit_vs || failed) return !failed;
    failed = 1;
    make_lit_vs();
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, smooth_decl, code, &lit_vs, 0))) return log_line("style: lit shader failed"), 0;
    make_outline_vs();
    if (FAILED(IDirect3DDevice8_CreateVertexShader(dev, smooth_decl, code, &outline_vs, 0))) return log_line("style: outline shader failed"), 0;
    make_ps();
    if (FAILED(IDirect3DDevice8_CreatePixelShader(dev, code, &ps))) return log_line("style: pixel shader failed"), 0;
    static BYTE px[LW * LH * 4];
    for (int s = CARTOON; s < STYLES; s++) {
        for (int y = 0; y < LH; y++)
            for (int x = 0; x < LW; x++) {
                float rgb[3], rim;
                shade(s, (x + 0.5f) / LW * 2 - 1, (y + 0.5f) / LH, rgb, &rim);
                BYTE *p = px + (y * LW + x) * 4;
                p[0] = to_byte(rgb[2] / 2), p[1] = to_byte(rgb[1] / 2), p[2] = to_byte(rgb[0] / 2), p[3] = to_byte(rim);
            }
        looks[s].light = make_texture(dev, LW, LH, 1, px);
        for (int y = 0; y < 16; y++)
            for (int x = 0; x < LW; x++) {
                BYTE *p = px + (y * LW + x) * 4;
                p[0] = p[1] = p[2] = to_byte(shine(s, y >= 8, (x + 0.5f) / LW)), p[3] = 255;
            }
        looks[s].shine = make_texture(dev, LW, 16, 1, px);
    }
    fur = make_fur(dev);
    eye = make_eye(dev);
    failed = 0;
    log_line("style: shaders and lookups ready");
    return 1;
}

// The game's two character shaders: lit through the ramp, and the outline.
void style_shader_created(DWORD h, const DWORD *fn)
{
    static const DWORD ramp[] = { MOV, 0xe0020001, 0xa0ff0030 };          // mov oT1.y, c48.w
    static const DWORD push[] = { MAD, 0x80070000, 0x80e40002, 0xa0ff0031 }; // mad r0.xyz, r2, c49.w, r0
    for (int i = 0; i < 1024 && fn[i] != 0xffff; i++) {
        if (!memcmp(fn + i, ramp, sizeof ramp)) lit_shader = h;
        if (!memcmp(fn + i, push, sizeof push)) outline_shader = h;
    }
}

// Player one's vertex buffer: actor +0x130 -> +0x3c -> +0.
static IDirect3DVertexBuffer8 *player_vb(void)
{
    static DWORD frame = -1;
    static IDirect3DVertexBuffer8 *vb;
    if (frame == presents) return vb;
    frame = presents;
    vb = NULL;
    BYTE *p = PLAYER;
    for (int k = 0; k < 3 && p; k++) {
        MEMORY_BASIC_INFORMATION mi;
        BYTE *at = p + (k == 0 ? 0x130 : k == 1 ? 0x3c : 0);
        if (!VirtualQuery(at, &mi, sizeof mi) || mi.State != MEM_COMMIT || (mi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return NULL;
        p = *(BYTE **)at;
    }
    return vb = (IDirect3DVertexBuffer8 *)p;
}

int style_is_player(IDirect3DVertexBuffer8 *vb)
{
    return settings.taz_style && settings.exe_known && SCENE >= 2 && vb == player_vb();
}

// Taz's textures by fingerprint: eyes and nose get a highlight, his fur the strand pattern.
static int texture_kind(UINT64 h)
{
    switch (h) {
    case 0xe406f847d6d3fbe7ULL: return 5;                                           // eye, open
    case 0x3d4148b8b9490b1dULL: return 1;                                           // nose
    case 0xff79c4533bbe731dULL: return 2;                                           // body
    case 0x9d5e91e61454750bULL: return 4;                                           // feet
    case 0x11a8bb45be9eebd3ULL: return 3;                                           // muzzle
    }
    return 0;
}

// The outline pass draws the same batches untextured; it finds each one's texture kind here, kept
// from the lit pass.
#define KINDS 2048
static struct { void *vb; UINT start, count; int kind; } kinds[KINDS];

static int *kind_of(IDirect3DDevice8 *dev, UINT start, UINT count)
{
    IDirect3DVertexBuffer8 *vb = NULL;
    UINT stride;
    IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride);
    if (vb) IDirect3DVertexBuffer8_Release(vb);
    UINT i = ((UINT)(UINT_PTR)vb >> 4 ^ start * 40503u ^ count * 977u) & (KINDS - 1);
    if (kinds[i].vb != vb || kinds[i].start != start || kinds[i].count != count)
        kinds[i].vb = vb, kinds[i].start = start, kinds[i].count = count, kinds[i].kind = 0;
    return &kinds[i].kind;
}

static void set_tufts(IDirect3DDevice8 *dev, float height)
{
    const float t[4][4] = { { 1 / 14.0f, 0.55f / 14, 0.3f / 14, 0 }, { -0.3f / 14, 0.55f / 14, 1 / 14.0f, 0 }, { 0.5f, height, 0, 0.5f },
                            { 140, 1 / 30.0f, 0, 1 } };
    IDirect3DDevice8_SetVertexShaderConstant(dev, 84, t, 4);
}

#define TUFT 24.0f

HRESULT style_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                   HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT))
{
    int s = settings.taz_style;
    DWORD vs = 0;
    if (!style_player || s <= CURRENT || s >= STYLES || FAILED(IDirect3DDevice8_GetVertexShader(dev, &vs))
        || (vs != lit_shader && vs != outline_shader) || !ready(dev))
        return draw(dev, type, start, count);
    HRESULT hr;
    if (vs == outline_shader) {
        float c[3][4] = { { light[0], light[1], light[2], 0 } };
        if (s == SOFT) memcpy(c[1], (float[4]){ -0.15f, 0.35f, 0.2f, 0 }, 16), memcpy(c[2], (float[4]){ 0.12f, 0.06f, 0.05f, 1 }, 16);
        else memcpy(c[1], (float[4]){ -0.4f, 0.8f, 0.45f, 0 }, 16), memcpy(c[2], (float[4]){ 0.05f, 0.02f, 0.02f, 1 }, 16);
        IDirect3DDevice8_SetVertexShaderConstant(dev, 80, c, 3);
        set_tufts(dev, s == FUR && *kind_of(dev, start, count) == 2 ? TUFT : 0);
        IDirect3DDevice8_SetVertexShader(dev, outline_vs);
        hr = draw(dev, type, start, count);
        IDirect3DDevice8_SetVertexShader(dev, vs);
        return hr;
    }
    IDirect3DDevice8_GetVertexShaderConstant(dev, 48, light, 1);
    int kind = *kind_of(dev, start, count) = texture_kind(textures_bound_hash(0));
    float fs = s == FUR ? (kind == 2 || kind == 4 ? 1.0f : kind == 3 ? 0.4f : 0) : 0;
    int shiny = kind == 5 || (kind == 1 && s == SOFT); // the cartoon looks keep the nose's painted shine; ours whitened the whiskers beside it
    float sh = shiny ? 1.0f : s == SOFT && kind ? 0.22f : 0;
    float pc[6][4] = {
        { light[0], light[1], light[2], 0 },
        { 0 },
        { 0.5f, 0.5f, 0.5f, 0.5f },
        { sh, sh, sh, 0 },
        { fs, fs, fs, 0 },
        { 0, shiny ? 0.75f : 0.25f, 0, 0 },
    };
    float vc[4] = { 1 / 36.0f, 1 / 40.0f, 0.5f, 0 }, mixc[4] = { 4, -1.5f, 0, 0 };
    IDirect3DDevice8_SetVertexShaderConstant(dev, 83, vc, 1);
    IDirect3DDevice8_SetVertexShaderConstant(dev, 88, mixc, 1);
    IDirect3DDevice8_SetPixelShaderConstant(dev, 0, pc, 6);
    static const DWORD stages[] = { 2, 3, 4, 5 };
    IDirect3DBaseTexture8 *bind[] = { (IDirect3DBaseTexture8 *)fur, (IDirect3DBaseTexture8 *)fur,
                                      (IDirect3DBaseTexture8 *)looks[s].light, (IDirect3DBaseTexture8 *)looks[s].shine };
    static const D3DTEXTURESTAGESTATETYPE states[] = { D3DTSS_ADDRESSU, D3DTSS_ADDRESSV, D3DTSS_MAGFILTER, D3DTSS_MINFILTER, D3DTSS_MIPFILTER };
    DWORD saved[4][5];
    for (int i = 0; i < 4; i++) {
        int wrap = i < 2;
        DWORD want[5] = { wrap ? D3DTADDRESS_WRAP : D3DTADDRESS_CLAMP, wrap ? D3DTADDRESS_WRAP : D3DTADDRESS_CLAMP, D3DTEXF_LINEAR, D3DTEXF_LINEAR,
                          wrap ? D3DTEXF_LINEAR : D3DTEXF_NONE };
        for (int k = 0; k < 5; k++) {
            IDirect3DDevice8_GetTextureStageState(dev, stages[i], states[k], &saved[i][k]);
            IDirect3DDevice8_SetTextureStageState(dev, stages[i], states[k], want[k]);
        }
        textures_bind_own(dev, stages[i], bind[i]);
    }
    IDirect3DBaseTexture8 *game = textures_bound(0);
    if (kind == 5) textures_bind_own(dev, 0, (IDirect3DBaseTexture8 *)eye);
    IDirect3DDevice8_SetVertexShader(dev, lit_vs);
    IDirect3DDevice8_SetPixelShader(dev, ps);
    hr = draw(dev, type, start, count);
    IDirect3DDevice8_SetPixelShader(dev, 0);
    if (kind == 5) IDirect3DDevice8_SetTexture(dev, 0, game); // through our hook: its HD replacement comes back
    IDirect3DDevice8_SetVertexShader(dev, vs);
    for (int i = 0; i < 4; i++) {
        textures_bind_own(dev, stages[i], NULL);
        for (int k = 0; k < 5; k++) IDirect3DDevice8_SetTextureStageState(dev, stages[i], states[k], saved[i][k]);
    }
    return hr;
}
