// Look level 4: loads the art data (tools/look/FORMAT.md) and renders it on the real Direct3D 9 device.
// The game's 3D pass lands in a float target, gamma-encoded so its own draws and MSAA edges behave as
// before; at the first 2D draw we resolve it, add bloom, tone map to the back buffer and let the HUD
// draw on top. All default-pool objects are dropped in hd_reset and remade on demand.
#define COBJMACROS
#include <windows.h>
#include <d3d9.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hd.h"
#include "look_shaders.h"

void log_line(const char *fmt, ...);

#define SMAP 4096
#define CMAP 2048
#define NBLOOM 5
#define INST_STRIDE 48
#define MAX_TEX 512
#define NEAR_END 175 // scenery closer than this fades towards the camera (scene.hlsl)
enum { OPAQUE_KIND, CARD, GRASS, WATER_KIND, GLASS_KIND, CASTER_KIND };
enum { F_TRIPLANAR = 1, F_TWOSIDED = 2, F_WIND = 4 };
enum { PASS_COLOUR, PASS_DEPTH, PASS_SHADOW, PASS_GLASS, PASS_NEAR_Z, PASS_NEAR };
// Our samplers sit above the stages the game uses (it never enables stage 7), so its state caching never sees them.
enum { SMP_FUR = 5, SMP_LIGHTS = 6, SMP_DEPTH = 7, SMP_NORMAL, SMP_ALBEDO, SMP_SKY, SMP_SHADOW, SMP_CMAP, SMP_AO, SMP_ALBEDO2, SMP_NORMAL2 };

#pragma pack(push, 1)
struct file_mat { char name[32], albedo[32], normal[32]; WORD kind, flags; float tile, tint[3], rough, nstrength, cut; };
struct file_bind { UINT64 hash; UINT mat, mask; float lo, hi; };
struct file_glow { UINT64 hash; float strength, lo, hi; UINT mask; };
#pragma pack(pop)

struct mat { IDirect3DTexture9 *albedo, *normal; int kind, flags; float tile, tint[3], rough, nstrength, cut; };
struct bind { UINT64 hash; int mat, mask; float lo, hi; };
struct sub { UINT mat, first, count; };
struct proto { UINT base, nv, sub0, nsub, run0, nrun; };
struct run { UINT chunk, first, n; };
struct chunk { float lo[3], hi[3]; };
struct light { float p[3], r, c[3], cone; };
struct target { IDirect3DTexture9 *t; IDirect3DSurface9 *s; UINT w, h; };

static struct level {
    float sun[3], sun_col[3], sky[3], ground[3], soft, ao_radius, ao_strength, fog[3], fog_start, fog_end;
    float exposure, bloom_t, bloom_s, sat, contrast, water_h, water[3], clarity, fade0, fade1, sky_scale, unbake, unbake_keep, char_fill[3], char_keep, hold, shadow_y, glow_add;
} lv;

static int scene_no = -1;
static struct mat *mats; static UINT nmats;
static struct bind *binds; static UINT nbinds;
// A game texture's binds in file order (the data has at most two), each over the last, and its glow. Worked out once
// per texture and scene: scanning every bind and glow per world draw was the look's biggest cost per draw.
static struct wmat { UINT64 hash; int n; float emit[4], c[6][4], w[2][4]; IDirect3DBaseTexture9 *t[4]; } wmats[1024];
static UINT64 *hides; static UINT nhides, nshades; // the last nshades are baked shadow decals
static struct light *lights; static UINT nlights;
static float char_at[3] = { 1e30f }; // where the last character's nearest lamps were found
static struct file_glow *glows; static UINT nglows;
static struct { UINT64 hash; float p[3], r; } *swaps; static UINT nswaps;
static struct solid { UINT64 key, tex; UINT proto; } *solids; static UINT nsolids;
static UINT64 solid_tex[256]; static UINT nsolid_tex; // sorted
static int cmp_u64(const void *a, const void *b) { UINT64 x = *(const UINT64 *)a, y = *(const UINT64 *)b; return x < y ? -1 : x > y; }
static struct { UINT proto; float world[12]; } solid_done[128]; static UINT ndone; // already drawn this frame
static IDirect3DTexture9 *light_tex;
static int skin_mat = -1, has_glass;
static float origin[3]; // where this load's additions are shifted to
static struct { UINT64 hash; IDirect3DTexture9 *t; } paints[8]; static UINT npaints; // redrawn backdrop panels
static float light_grid[4];
static struct proto *protos; static UINT nprotos;
static struct sub *subs;
static struct run *runs;
static struct chunk *chunks; static UINT nchunks;
static BYTE *vis;
static IDirect3DVertexBuffer9 *vb, *ivb;
static IDirect3DIndexBuffer9 *ib;
static IDirect3DCubeTexture9 *sky_tex;
static IDirect3DTexture9 *white, *flat;
static struct { char name[32]; IDirect3DTexture9 *t; } texs[MAX_TEX];
static UINT ntexs;

// Shaders, vertex declarations
static IDirect3DVertexShader9 *v_world, *v_inst, *v_water, *v_world_float, *v_wind, *v_grass, *v_world_z, *v_inst_z, *v_grass_z, *v_sky, *v_quad, *v_char_z, *v_prop;
static IDirect3DPixelShader9 *p_space, *p_glass, *p_depth, *p_world, *p_mat, *p_mat2, *p_tiled, *p_inst, *p_card, *p_grass, *p_water, *p_sky, *p_char, *p_glow;
static IDirect3DPixelShader9 *p_bright, *p_down, *p_up, *p_final, *p_ao, *p_blur, *p_ao_up;
static IDirect3DVertexDeclaration9 *d_world, *d_inst, *d_quad, *d_char;
static int atoc;

// Targets
static IDirect3DSurface9 *hdr_ms, *z_depth, *null_s, *null_c;
static IDirect3DSurface9 *preview; // a map preview's target: its pass goes to the top left of the plain HDR texture
static D3DVIEWPORT9 pvp;          // and covers this much of it
static struct target hdr, zt, ao[2], bloom[NBLOOM], zq, aq[2];
static int lowres; // test runs (taz-hd\lowres file): 1 AO, 2 bloom, 3 both from quarter-size targets
static IDirect3DTexture9 *smap, *cmap;
static IDirect3DSurface9 *smap_s, *cmap_s;
static IDirect3DStateBlock9 *sb;
static UINT tw, th;
static D3DMULTISAMPLE_TYPE tms;
static DWORD tq;
static int broken;

static float shadow_hw, player[4]; // position and 1 / radius of the grass pressed under his feet
static int sky_done, redirected, post_done, additions_done, prepass_done, shadow_built, cmap_used;
static float view[4][4], proj[4][4], clip_rows[4][4], srows[3][4], crows[3][4], cclip[4][4], eye[3], now_s;
static IDirect3DSurface9 *saved_rt, *saved_ds;
static D3DVIEWPORT9 saved_vp;

static float dot3(const float *a, const float *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
static void norm3(float *a) { float l = sqrtf(dot3(a, a)); if (l > 0) a[0] /= l, a[1] /= l, a[2] /= l; }

// --- data ---------------------------------------------------------------------------------------
static BYTE *read_file(const char *path, long *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    BYTE *p = malloc(n);
    if (p && fread(p, 1, n, f) != (size_t)n) free(p), p = NULL;
    fclose(f);
    if (size) *size = n;
    return p;
}

static UINT level_size(D3DFORMAT fmt, UINT w, UINT h, UINT *pitch, UINT *rows)
{
    if (fmt == D3DFMT_DXT1 || fmt == D3DFMT_DXT5) {
        UINT bw = (w + 3) / 4, bh = (h + 3) / 4, block = fmt == D3DFMT_DXT1 ? 8 : 16;
        bw = bw ? bw : 1, bh = bh ? bh : 1;
        *pitch = bw * block, *rows = bh;
    } else {
        *pitch = w * 4, *rows = h;
    }
    return *pitch * *rows;
}

static int dds_header(const BYTE *p, long n, UINT *w, UINT *h, UINT *mips, D3DFORMAT *fmt)
{
    if (n < 128 || memcmp(p, "DDS ", 4)) return 0;
    *h = *(UINT *)(p + 12), *w = *(UINT *)(p + 16), *mips = *(UINT *)(p + 28);
    if (!*mips) *mips = 1;
    DWORD four = *(DWORD *)(p + 84);
    *fmt = four == MAKEFOURCC('D', 'X', 'T', '1') ? D3DFMT_DXT1 : four == MAKEFOURCC('D', 'X', 'T', '5') ? D3DFMT_DXT5 : D3DFMT_A8R8G8B8;
    return 1;
}

static IDirect3DTexture9 *load_dds(hd_dev d, const char *path)
{
    long n;
    BYTE *p = read_file(path, &n);
    UINT w, h, mips, pitch, rows;
    D3DFORMAT fmt;
    IDirect3DTexture9 *t = NULL;
    if (!p) return log_line("hd: missing %s", path), NULL;
    IDirect3DTexture9 *up = NULL;
    if (dds_header(p, n, &w, &h, &mips, &fmt) && SUCCEEDED(IDirect3DDevice9_CreateTexture(d, w, h, mips, 0, fmt, D3DPOOL_SYSTEMMEM, &up, NULL))) {
        const BYTE *src = p + 128;
        for (UINT m = 0; m < mips; m++) {
            UINT mw = w >> m ? w >> m : 1, mh = h >> m ? h >> m : 1, size = level_size(fmt, mw, mh, &pitch, &rows);
            D3DLOCKED_RECT lr;
            if (src + size > p + n || FAILED(IDirect3DTexture9_LockRect(up, m, &lr, NULL, 0))) break;
            for (UINT y = 0; y < rows; y++) memcpy((BYTE *)lr.pBits + y * lr.Pitch, src + y * pitch, pitch);
            IDirect3DTexture9_UnlockRect(up, m);
            src += size;
        }
        if (SUCCEEDED(IDirect3DDevice9_CreateTexture(d, w, h, mips, 0, fmt, D3DPOOL_DEFAULT, &t, NULL)))
            IDirect3DDevice9_UpdateTexture(d, (IDirect3DBaseTexture9 *)up, (IDirect3DBaseTexture9 *)t);
        IDirect3DTexture9_Release(up);
    }
    free(p);
    return t;
}

static IDirect3DCubeTexture9 *load_cube(hd_dev d, const char *path)
{
    long n;
    BYTE *p = read_file(path, &n);
    UINT w, h, mips, pitch, rows;
    D3DFORMAT fmt;
    IDirect3DCubeTexture9 *t = NULL;
    if (!p) return NULL;
    IDirect3DCubeTexture9 *up = NULL;
    if (dds_header(p, n, &w, &h, &mips, &fmt) && SUCCEEDED(IDirect3DDevice9_CreateCubeTexture(d, w, mips, 0, fmt, D3DPOOL_SYSTEMMEM, &up, NULL))) {
        const BYTE *src = p + 128;
        for (int face = 0; face < 6; face++)
            for (UINT m = 0; m < mips; m++) {
                UINT mw = w >> m ? w >> m : 1, size = level_size(fmt, mw, mw, &pitch, &rows);
                D3DLOCKED_RECT lr;
                if (src + size > p + n || FAILED(IDirect3DCubeTexture9_LockRect(up, face, m, &lr, NULL, 0))) break;
                for (UINT y = 0; y < rows; y++) memcpy((BYTE *)lr.pBits + y * lr.Pitch, src + y * pitch, pitch);
                IDirect3DCubeTexture9_UnlockRect(up, face, m);
                src += size;
            }
        if (SUCCEEDED(IDirect3DDevice9_CreateCubeTexture(d, w, mips, 0, fmt, D3DPOOL_DEFAULT, &t, NULL)))
            IDirect3DDevice9_UpdateTexture(d, (IDirect3DBaseTexture9 *)up, (IDirect3DBaseTexture9 *)t);
        IDirect3DCubeTexture9_Release(up);
    }
    free(p);
    return t;
}

static IDirect3DTexture9 *named_tex(hd_dev d, const char *name)
{
    char path[MAX_PATH];
    if (!name[0]) return NULL;
    for (UINT i = 0; i < ntexs; i++)
        if (!strncmp(texs[i].name, name, 32)) return texs[i].t;
    if (ntexs == MAX_TEX) return NULL;
    snprintf(path, sizeof path, "taz-hd\\look\\scene%02d\\tex\\%.32s.dds", scene_no, name);
    memcpy(texs[ntexs].name, name, 32);
    return texs[ntexs++].t = load_dds(d, path);
}

static void defaults(void)
{
    memset(&lv, 0, sizeof lv);
    float t = 3.14159265f / 180, az = 45 * t, el = 38 * t;
    lv.sun[0] = cosf(el) * cosf(az), lv.sun[1] = sinf(el), lv.sun[2] = cosf(el) * sinf(az);
    memcpy(lv.sun_col, (float[3]){ 3.2f, 2.9f, 2.4f }, 12);
    memcpy(lv.sky, (float[3]){ 0.62f, 0.78f, 1.0f }, 12);
    memcpy(lv.ground, (float[3]){ 0.34f, 0.28f, 0.2f }, 12);
    lv.soft = 3, lv.ao_radius = 90, lv.ao_strength = 0.8f;
    memcpy(lv.fog, (float[3]){ 0.62f, 0.76f, 0.95f }, 12);
    lv.fog_start = 7500, lv.fog_end = 40000;
    lv.exposure = 0.72f, lv.bloom_t = 1.1f, lv.bloom_s = 0.12f, lv.sat = 1.08f, lv.contrast = 1.04f;
    lv.water_h = -1e9f, lv.clarity = 0.004f, lv.fade0 = 2600, lv.fade1 = 4200, lv.sky_scale = 1;
    memcpy(lv.water, (float[3]){ 0.03f, 0.2f, 0.28f }, 12);
}

static void read_ini(void)
{
    char path[MAX_PATH], line[256];
    snprintf(path, sizeof path, "taz-hd\\look\\scene%02d\\level.ini", scene_no);
    FILE *f = fopen(path, "r");
    defaults();
    if (!f) return;
    static const struct { const char *key; size_t at; int n; } keys[] = {
#define K(name, field, n) { name, offsetof(struct level, field), n }
        K("sun_dir", sun, 3), K("sun_color", sun_col, 3), K("sky_ambient", sky, 3), K("ground_ambient", ground, 3),
        K("shadow_softness", soft, 1), K("ao_radius", ao_radius, 1), K("ao_strength", ao_strength, 1),
        K("fog_color", fog, 3), K("fog_start", fog_start, 1), K("fog_end", fog_end, 1), K("exposure", exposure, 1),
        K("bloom_threshold", bloom_t, 1), K("bloom_strength", bloom_s, 1), K("saturation", sat, 1), K("contrast", contrast, 1),
        K("water_height", water_h, 1), K("water_color", water, 3), K("water_clarity", clarity, 1),
        K("grass_fade_start", fade0, 1), K("grass_fade_end", fade1, 1), K("sky_scale", sky_scale, 1), K("unbake", unbake, 1), K("unbake_keep", unbake_keep, 1), K("char_fill", char_fill, 3), K("char_keep", char_keep, 1), K("hold", hold, 1), K("shadow_floor", shadow_y, 1), K("glow_add", glow_add, 1),
    };
    while (fgets(line, sizeof line, f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0;
        char key[64] = "";
        sscanf(line, "%63s", key);
        for (size_t i = 0; i < sizeof keys / sizeof *keys; i++) {
            if (strcmp(key, keys[i].key)) continue;
            float v[3];
            int got = sscanf(eq + 1, "%f %f %f", &v[0], &v[1], &v[2]);
            if (got >= keys[i].n) memcpy((BYTE *)&lv + keys[i].at, v, keys[i].n * 4);
        }
    }
    fclose(f);
    norm3(lv.sun);
}

// Test runs: taz-hd\\shaders\\NAME.cso overrides the built-in shader.
static DWORD *shader_file(const char *name)
{
    char path[64];
    snprintf(path, sizeof path, "taz-hd\\shaders\\%s.cso", name);
    FILE *f = capture_tests() ? fopen(path, "rb") : NULL;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    rewind(f);
    DWORD *code = malloc(n);
    if (code && fread(code, 1, n, f) != (size_t)n) free(code), code = NULL;
    fclose(f);
    return code;
}

static int load_shaders(hd_dev d)
{
    int ok = 1;
#define MAKE(kind, var, code) { IDirect3D##kind##Shader9 *s = NULL; DWORD *f = shader_file(#code); \
    if (SUCCEEDED(IDirect3DDevice9_Create##kind##Shader(d, f ? f : code, &s))) { if (var) IDirect3D##kind##Shader9_Release(var); var = s; } else ok = 0; \
    free(f); }
#define VS(var, code) MAKE(Vertex, var, code)
#define PS(var, code) MAKE(Pixel, var, code)
    VS(v_world, vs_world); VS(v_inst, vs_inst); VS(v_water, vs_water); VS(v_world_float, vs_world_float); VS(v_wind, vs_inst_wind); VS(v_grass, vs_grass);
    VS(v_world_z, vs_world_depth); VS(v_inst_z, vs_inst_depth); VS(v_grass_z, vs_grass_depth); VS(v_sky, vs_sky); VS(v_quad, vs_quad); VS(v_char_z, vs_char_depth); VS(v_prop, vs_prop);
    PS(p_depth, ps_depth); PS(p_world, ps_world); PS(p_mat, ps_world_mat); PS(p_mat2, ps_world_mat2); PS(p_tiled, ps_inst_tiled); PS(p_inst, ps_inst); PS(p_card, ps_card);
    PS(p_grass, ps_grass); PS(p_water, ps_water); PS(p_sky, ps_sky); PS(p_glass, ps_glass); PS(p_space, ps_space); PS(p_char, ps_char); PS(p_glow, ps_glow);
    PS(p_bright, ps_bright); PS(p_down, ps_down); PS(p_up, ps_up); PS(p_final, ps_final); PS(p_ao, ps_ao); PS(p_blur, ps_ao_blur); PS(p_ao_up, ps_ao_up);
    return ok;
}

static void check_reload(hd_dev d)
{
    if (GetFileAttributesA("taz-hd\\look-reload") == INVALID_FILE_ATTRIBUTES) return;
    DeleteFileA("taz-hd\\look-reload");
    if (scene_no >= 0) read_ini(), log_line("hd: level.ini reloaded");
    if (v_world) log_line("hd: shaders reloaded%s", load_shaders(d) ? "" : ", some FAILED");
}

static int make_shaders(hd_dev d)
{
    if (v_world) return 1;
    int ok = load_shaders(d);
    static const D3DVERTEXELEMENT9 e_world[] = {
        { 0, 0, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_POSITION, 0 }, { 0, 12, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_NORMAL, 0 },
        { 0, 24, D3DDECLTYPE_D3DCOLOR, 0, D3DDECLUSAGE_COLOR, 0 }, { 0, 28, D3DDECLTYPE_FLOAT2, 0, D3DDECLUSAGE_TEXCOORD, 0 }, D3DDECL_END() };
    static const D3DVERTEXELEMENT9 e_inst[] = {
        { 0, 0, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_POSITION, 0 }, { 0, 12, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_NORMAL, 0 },
        { 0, 24, D3DDECLTYPE_D3DCOLOR, 0, D3DDECLUSAGE_COLOR, 0 }, { 0, 28, D3DDECLTYPE_FLOAT2, 0, D3DDECLUSAGE_TEXCOORD, 0 },
        { 1, 0, D3DDECLTYPE_FLOAT4, 0, D3DDECLUSAGE_TEXCOORD, 1 }, { 1, 16, D3DDECLTYPE_FLOAT4, 0, D3DDECLUSAGE_TEXCOORD, 2 },
        { 1, 32, D3DDECLTYPE_FLOAT4, 0, D3DDECLUSAGE_TEXCOORD, 3 }, D3DDECL_END() };
    static const D3DVERTEXELEMENT9 e_quad[] = {
        { 0, 0, D3DDECLTYPE_FLOAT4, 0, D3DDECLUSAGE_POSITION, 0 }, { 0, 16, D3DDECLTYPE_FLOAT2, 0, D3DDECLUSAGE_TEXCOORD, 0 }, D3DDECL_END() };
    ok &= SUCCEEDED(IDirect3DDevice9_CreateVertexDeclaration(d, e_world, &d_world));
    ok &= SUCCEEDED(IDirect3DDevice9_CreateVertexDeclaration(d, e_inst, &d_inst));
    ok &= SUCCEEDED(IDirect3DDevice9_CreateVertexDeclaration(d, e_quad, &d_quad));
    static const D3DVERTEXELEMENT9 e_char[] = { // the game's 52-byte character vertex
        { 0, 0, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_POSITION, 0 }, { 0, 12, D3DDECLTYPE_FLOAT3, 0, D3DDECLUSAGE_TEXCOORD, 1 },
        { 0, 24, D3DDECLTYPE_UBYTE4, 0, D3DDECLUSAGE_TEXCOORD, 2 }, D3DDECL_END() };
    ok &= SUCCEEDED(IDirect3DDevice9_CreateVertexDeclaration(d, e_char, &d_char));
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(IDirect3DDevice9_CreateTexture(d, 1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &white, NULL))) {
        IDirect3DTexture9_LockRect(white, 0, &lr, NULL, 0), *(DWORD *)lr.pBits = 0xffffffff, IDirect3DTexture9_UnlockRect(white, 0);
    }
    if (SUCCEEDED(IDirect3DDevice9_CreateTexture(d, 1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &flat, NULL))) {
        IDirect3DTexture9_LockRect(flat, 0, &lr, NULL, 0), *(DWORD *)lr.pBits = 0x8080ff80, IDirect3DTexture9_UnlockRect(flat, 0);
    }
    IDirect3D9 *d3d = NULL;
    D3DDISPLAYMODE mode;
    IDirect3DDevice9_GetDirect3D(d, &d3d);
    if (d3d) {
        IDirect3DDevice9_GetDisplayMode(d, 0, &mode);
        atoc = SUCCEEDED(IDirect3D9_CheckDeviceFormat(d3d, 0, D3DDEVTYPE_HAL, mode.Format, 0, D3DRTYPE_SURFACE, (D3DFORMAT)MAKEFOURCC('A', 'T', 'O', 'C')));
        IDirect3D9_Release(d3d);
    }
    log_line("hd: shaders %s, alpha to coverage %s", ok ? "ready" : "FAILED", atoc ? "yes" : "no (alpha cut)");
    if (!ok) broken = 1;
    return ok;
}

// Grid over the lights' reach: each cell names its four nearest, in a float texture with the light table below it.
#define LIGHT_CELLS 64
static void build_lights(hd_dev d)
{
    if (!nlights || FAILED(IDirect3DDevice9_CreateTexture(d, LIGHT_CELLS, 128, 1, 0, D3DFMT_A32B32G32R32F, D3DPOOL_MANAGED, &light_tex, NULL))) return;
    float lo[2] = { 1e9f, 1e9f }, hi[2] = { -1e9f, -1e9f };
    for (UINT i = 0; i < nlights; i++)
        for (int a = 0; a < 2; a++) {
            float v = lights[i].p[a * 2], r = lights[i].r;
            if (v - r < lo[a]) lo[a] = v - r;
            if (v + r > hi[a]) hi[a] = v + r;
        }
    float cell = (hi[0] - lo[0] > hi[1] - lo[1] ? hi[0] - lo[0] : hi[1] - lo[1]) / LIGHT_CELLS * 1.001f;
    light_grid[0] = lo[0], light_grid[1] = lo[1], light_grid[2] = 1 / cell, light_grid[3] = 1;
    D3DLOCKED_RECT lr;
    if (FAILED(IDirect3DTexture9_LockRect(light_tex, 0, &lr, NULL, 0))) return;
    memset(lr.pBits, 0, lr.Pitch * 128);
    for (int z = 0; z < LIGHT_CELLS; z++)
        for (int x = 0; x < LIGHT_CELLS; x++) {
            float cx = lo[0] + (x + 0.5f) * cell, cz = lo[1] + (z + 0.5f) * cell, best[4] = { 1e30f, 1e30f, 1e30f, 1e30f }, id[4] = { 0 };
            for (UINT i = 0; i < nlights && i < LIGHT_CELLS; i++) {
                float dx = lights[i].p[0] - cx, dz = lights[i].p[2] - cz, reach = lights[i].r + cell * 0.71f, dd = dx * dx + dz * dz;
                if (dd > reach * reach) continue;
                for (int k = 0; k < 4; k++) {
                    if (dd >= best[k]) continue;
                    for (int m = 3; m > k; m--) best[m] = best[m - 1], id[m] = id[m - 1];
                    best[k] = dd, id[k] = (float)i + 1;
                    break;
                }
            }
            memcpy((BYTE *)lr.pBits + z * lr.Pitch + x * 16, (float[4]){ id[0], id[1], id[2], id[3] }, 16);
        }
    for (UINT i = 0; i < nlights && i < LIGHT_CELLS; i++) {
        const struct light *l = &lights[i];
        memcpy((BYTE *)lr.pBits + 64 * lr.Pitch + i * 16, (float[4]){ l->p[0], l->p[1], l->p[2], 1 / (l->r * l->r) }, 16);
        memcpy((BYTE *)lr.pBits + 65 * lr.Pitch + i * 16, (float[4]){ l->c[0], l->c[1], l->c[2], l->cone }, 16);
    }
    IDirect3DTexture9_UnlockRect(light_tex, 0);
}

void hd_set_origin(float x, float y, float z) { origin[0] = x, origin[1] = y, origin[2] = z; }

int hd_load(hd_dev d, int scene)
{
    char path[MAX_PATH];
    long n;
    snprintf(path, sizeof path, "taz-hd\\look\\scene%02d\\scene.bin", scene);
    if (broken || !make_shaders(d)) return 0;
    BYTE *file = read_file(path, &n);
    if (!file) return 0;
    if (n < 8 || memcmp(file, "TZLK", 4) || *(UINT *)(file + 4) != 3) {
        log_line("hd: %s is not format 3", path);
        free(file);
        return 0;
    }
    MEMORYSTATUS ms;
    ms.dwLength = sizeof ms;
    GlobalMemoryStatus(&ms);
    DWORD before = (DWORD)(ms.dwAvailVirtual >> 20);
    scene_no = scene;
    read_ini();
    const BYTE *p = file + 8;
#define U() (p += 4, *(const UINT *)(p - 4))
    UINT a = U();
    const UINT64 *h1 = (const UINT64 *)p; p += a * 8;
    UINT b = U();
    hides = malloc((a + b + 1) * 8);
    memcpy(hides, h1, a * 8), memcpy(hides + a, p, b * 8), p += b * 8;
    nhides = a + b, nshades = b;
    nmats = U();
    mats = calloc(nmats + 1, sizeof *mats);
    for (UINT i = 0; i < nmats; i++, p += sizeof(struct file_mat)) {
        const struct file_mat *f = (const void *)p;
        struct mat *m = &mats[i];
        m->albedo = named_tex(d, f->albedo), m->normal = named_tex(d, f->normal);
        m->kind = f->kind, m->flags = f->flags, m->tile = f->tile, m->rough = f->rough, m->nstrength = f->nstrength, m->cut = f->cut;
        memcpy(m->tint, f->tint, 12);
        if (!strncmp(f->name, "skin", 32)) skin_mat = (int)i;
        has_glass |= m->kind == GLASS_KIND;
    }
    nbinds = U();
    binds = calloc(nbinds + 1, sizeof *binds);
    for (UINT i = 0; i < nbinds; i++, p += sizeof(struct file_bind)) {
        const struct file_bind *f = (const void *)p;
        binds[i] = (struct bind){ f->hash, (int)f->mat, (int)f->mask, f->lo, f->hi };
    }
    nprotos = U();
    protos = calloc(nprotos + 1, sizeof *protos);
    // First walk: sizes, so one vertex and one index buffer hold every prototype.
    const BYTE *q = p;
    UINT tv = 0, ti = 0, ts = 0;
    for (UINT i = 0; i < nprotos; i++) {
        UINT nv = ((const UINT *)q)[0], ni = ((const UINT *)q)[1], ns = ((const UINT *)q)[2];
        q += 12 + nv * 36 + ni * 4 + ns * 12;
        tv += nv, ti += ni, ts += ns;
    }
    subs = calloc(ts + 1, sizeof *subs);
    BYTE *vp = NULL, *ip = NULL;
    if (tv && FAILED(IDirect3DDevice9_CreateVertexBuffer(d, tv * 36, D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &vb, NULL))) goto fail;
    if (ti && FAILED(IDirect3DDevice9_CreateIndexBuffer(d, ti * 4, D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_DEFAULT, &ib, NULL))) goto fail;
    if (vb) IDirect3DVertexBuffer9_Lock(vb, 0, 0, (void **)&vp, 0);
    if (ib) IDirect3DIndexBuffer9_Lock(ib, 0, 0, (void **)&ip, 0);
    UINT at_v = 0, at_i = 0, at_s = 0;
    for (UINT i = 0; i < nprotos; i++) {
        UINT nv = U(), ni = U(), ns = U();
        memcpy(vp + at_v * 36, p, nv * 36), p += nv * 36;
        memcpy(ip + at_i * 4, p, ni * 4), p += ni * 4;
        protos[i] = (struct proto){ at_v, nv, at_s, ns, 0, 0 };
        for (UINT k = 0; k < ns; k++, p += 12) {
            const UINT *s = (const UINT *)p;
            subs[at_s++] = (struct sub){ s[0], at_i + s[1], s[2] };
        }
        at_v += nv, at_i += ni;
    }
    if (vb) IDirect3DVertexBuffer9_Unlock(vb);
    if (ib) IDirect3DIndexBuffer9_Unlock(ib);
    // Second walk over chunks: runs grouped by prototype, so neighbouring chunks' instances are contiguous.
    nchunks = U();
    chunks = calloc(nchunks + 1, sizeof *chunks);
    vis = calloc(nchunks + 1, 1);
    q = p;
    UINT nruns = 0, ninst = 0;
    for (UINT i = 0; i < nchunks; i++) {
        q += 24;
        UINT nr = *(const UINT *)q; q += 4;
        for (UINT j = 0; j < nr; j++) {
            UINT pr = ((const UINT *)q)[0], c = ((const UINT *)q)[1];
            q += 8 + c * 48;
            if (pr < nprotos) protos[pr].nrun++;
            nruns++, ninst += c;
        }
    }
    runs = calloc(nruns + 1, sizeof *runs);
    UINT at = 0;
    for (UINT i = 0; i < nprotos; i++) protos[i].run0 = at, at += protos[i].nrun, protos[i].nrun = 0;
    const BYTE **src = calloc(nruns + 1, sizeof *src);
    for (UINT i = 0; i < nchunks; i++) {
        memcpy(&chunks[i], p, 24), p += 24;
        for (int a = 0; a < 3; a++) chunks[i].lo[a] += origin[a], chunks[i].hi[a] += origin[a];
        UINT nr = U();
        for (UINT j = 0; j < nr; j++) {
            UINT pr = U(), c = U();
            if (pr < nprotos) {
                UINT r = protos[pr].run0 + protos[pr].nrun++;
                runs[r] = (struct run){ i, 0, c };
                src[r] = p;
            }
            p += c * 48;
        }
    }
    BYTE *ip2 = NULL;
    if (ninst && SUCCEEDED(IDirect3DDevice9_CreateVertexBuffer(d, ninst * INST_STRIDE, D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &ivb, NULL))
        && SUCCEEDED(IDirect3DVertexBuffer9_Lock(ivb, 0, 0, (void **)&ip2, 0))) {
        UINT off = 0;
        for (UINT r = 0; r < nruns; r++) {
            runs[r].first = off;
            if (src[r]) memcpy(ip2 + off * INST_STRIDE, src[r], runs[r].n * INST_STRIDE);
            for (UINT k = 0; (origin[0] || origin[1] || origin[2]) && k < runs[r].n; k++)
                for (int a = 0; a < 3; a++) ((float *)(ip2 + (off + k) * INST_STRIDE))[a * 4 + 3] += origin[a];
            off += runs[r].n;
        }
        IDirect3DVertexBuffer9_Unlock(ivb);
    }
    free(src);
    if (p + 4 <= file + n) { // optional, after the chunks: lamps and glowing textures
        nlights = U();
        lights = malloc((nlights + 1) * sizeof *lights);
        memcpy(lights, p, nlights * sizeof *lights), p += nlights * sizeof *lights;
        nglows = U();
        glows = malloc((nglows + 1) * sizeof *glows);
        memcpy(glows, p, nglows * sizeof *glows), p += nglows * sizeof *glows;
        build_lights(d);
        if (p + 4 <= file + n) {
            nswaps = U();
            swaps = malloc((nswaps + 1) * sizeof *swaps);
            memcpy(swaps, p, nswaps * sizeof *swaps), p += nswaps * sizeof *swaps;
        }
    }
    if (p + 4 <= file + n) { // optional, sorted by key: game draws replaced by a prototype at the game's transform
        nsolids = U();
        solids = malloc((nsolids + 1) * sizeof *solids);
        for (UINT i = 0; i < nsolids; i++, p += 20) {
            memcpy(&solids[i].key, p, 8), memcpy(&solids[i].tex, p + 8, 8), memcpy(&solids[i].proto, p + 16, 4);
            UINT k = 0;
            while (k < nsolid_tex && solid_tex[k] != solids[i].tex) k++;
            if (k == nsolid_tex && k < 256) solid_tex[nsolid_tex++] = solids[i].tex;
        }
        qsort(solid_tex, nsolid_tex, sizeof *solid_tex, cmp_u64);
    }
    snprintf(path, sizeof path, "taz-hd\\look\\scene%02d\\sky.dds", scene);
    sky_tex = load_cube(d, path);
    snprintf(path, sizeof path, "taz-hd\\look\\scene%02d\\tex\\paint_*.dds", scene);
    WIN32_FIND_DATAA found;
    HANDLE list = FindFirstFileA(path, &found);
    for (BOOL more = list != INVALID_HANDLE_VALUE; more && npaints < 8; more = FindNextFileA(list, &found)) {
        char name[32];
        snprintf(name, sizeof name, "%.*s", (int)strlen(found.cFileName) - 4, found.cFileName);
        paints[npaints].hash = strtoull(name + 6, NULL, 16), paints[npaints++].t = named_tex(d, name);
    }
    if (list != INVALID_HANDLE_VALUE) FindClose(list);
    free(file);
    GlobalMemoryStatus(&ms);
    log_line("hd: scene %d: %u materials, %u binds, %u prototypes, %u chunks, %u instances, %u vertices, %u textures, sky %s, address space free %lu -> %lu MB",
             scene, nmats, nbinds, nprotos, nchunks, ninst, tv, ntexs, sky_tex ? "yes" : "no", before, (DWORD)(ms.dwAvailVirtual >> 20));
    return 1;
fail:
    log_line("hd: buffers failed");
    free(file);
    hd_unload();
    return 0;
}

void hd_unload(void)
{
    for (UINT i = 0; i < ntexs; i++) if (texs[i].t) IDirect3DTexture9_Release(texs[i].t);
    ntexs = 0;
    if (vb) IDirect3DVertexBuffer9_Release(vb), vb = NULL;
    if (ivb) IDirect3DVertexBuffer9_Release(ivb), ivb = NULL;
    if (ib) IDirect3DIndexBuffer9_Release(ib), ib = NULL;
    if (sky_tex) IDirect3DCubeTexture9_Release(sky_tex), sky_tex = NULL;
    if (light_tex) IDirect3DTexture9_Release(light_tex), light_tex = NULL;
    skin_mat = -1, has_glass = 0, npaints = 0;
    free(lights), free(glows), lights = NULL, glows = NULL, nlights = nglows = 0, light_grid[3] = 0;
    free(swaps), swaps = NULL, nswaps = 0;
    free(solids), solids = NULL, nsolids = nsolid_tex = ndone = 0;
    free(mats), free(binds), free(hides), free(protos), free(subs), free(runs), free(chunks), free(vis);
    mats = NULL, binds = NULL, hides = NULL, protos = NULL, subs = NULL, runs = NULL, chunks = NULL, vis = NULL;
    nmats = nbinds = nhides = nshades = nprotos = nchunks = 0;
    memset(wmats, 0, sizeof wmats);
    char_at[0] = 1e30f;
    scene_no = -1, shadow_built = 0;
}

int hd_loaded(void) { return scene_no >= 0; }

int hd_hidden(unsigned long long h)
{
    for (UINT i = 0; i < nhides - nshades; i++)
        if (hides[i] == h) return 1;
    return 0;
}

int hd_swapped(unsigned long long h, const float *at)
{
    for (UINT i = 0; i < nswaps; i++)
        if (swaps[i].hash == h && (!at || (fabsf(at[0] - swaps[i].p[0]) < swaps[i].r && fabsf(at[1] - swaps[i].p[1]) < swaps[i].r && fabsf(at[2] - swaps[i].p[2]) < swaps[i].r)))
            return 1;
    return 0;
}

int hd_shade(unsigned long long h)
{
    for (UINT i = nhides - nshades; i < nhides; i++)
        if (hides[i] == h) return 1;
    return 0;
}

// --- targets ------------------------------------------------------------------------------------
static void drop(struct target *t)
{
    if (t->s) IDirect3DSurface9_Release(t->s), t->s = NULL;
    if (t->t) IDirect3DTexture9_Release(t->t), t->t = NULL;
}

static void drop_targets(void)
{
    drop(&hdr), drop(&zt), drop(&ao[0]), drop(&ao[1]), drop(&zq), drop(&aq[0]), drop(&aq[1]);
    for (int i = 0; i < NBLOOM; i++) drop(&bloom[i]);
    IUnknown **list[] = { (IUnknown **)&preview, (IUnknown **)&hdr_ms, (IUnknown **)&z_depth, (IUnknown **)&null_s, (IUnknown **)&null_c, (IUnknown **)&smap,
                          (IUnknown **)&cmap, (IUnknown **)&smap_s, (IUnknown **)&cmap_s, (IUnknown **)&sb, (IUnknown **)&saved_rt, (IUnknown **)&saved_ds };
    for (size_t i = 0; i < sizeof list / sizeof *list; i++)
        if (*list[i]) IUnknown_Release(*list[i]), *list[i] = NULL;
    redirected = post_done = additions_done = prepass_done = shadow_built = cmap_used = 0;
    tw = th = 0;
}

// Everything of ours is in the default pool, which a device Reset needs gone. The next frame loads it again.
static int lost;
void hd_reset(void)
{
    drop_targets();
    if (scene_no >= 0) lost = 1, hd_unload();
}

int hd_lost(void) { int was = lost; lost = 0; return was; }

static int make_target(hd_dev d, struct target *t, UINT w, UINT h, D3DFORMAT fmt)
{
    t->w = w, t->h = h;
    if (FAILED(IDirect3DDevice9_CreateTexture(d, w, h, 1, D3DUSAGE_RENDERTARGET, fmt, D3DPOOL_DEFAULT, &t->t, NULL))) return 0;
    return SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(t->t, 0, &t->s));
}

static int make_targets(hd_dev d)
{
    IDirect3DSurface9 *bb = NULL;
    D3DSURFACE_DESC bd;
    if (broken || FAILED(IDirect3DDevice9_GetBackBuffer(d, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return 0;
    IDirect3DSurface9_GetDesc(bb, &bd);
    IDirect3DSurface9_Release(bb);
    if (hdr.t && tw == bd.Width && th == bd.Height && tms == bd.MultiSampleType && tq == bd.MultiSampleQuality) return 1;
    int kept_shadow = shadow_built;
    IDirect3DTexture9 *keep_s = smap, *keep_c = cmap;
    IDirect3DSurface9 *keep_ss = smap_s, *keep_cs = cmap_s, *keep_n = null_s, *keep_nc = null_c;
    IDirect3DStateBlock9 *keep_sb = sb;
    smap = cmap = NULL, smap_s = cmap_s = null_s = null_c = NULL, sb = NULL;
    drop_targets(); // a changed size or sample count: only the screen-sized targets go
    smap = keep_s, cmap = keep_c, smap_s = keep_ss, cmap_s = keep_cs, null_s = keep_n, null_c = keep_nc, sb = keep_sb, shadow_built = kept_shadow;
    UINT w = bd.Width, h = bd.Height;
    int ok = make_target(d, &hdr, w, h, D3DFMT_A16B16G16R16F);
    if (bd.MultiSampleType)
        ok = ok && SUCCEEDED(IDirect3DDevice9_CreateRenderTarget(d, w, h, D3DFMT_A16B16G16R16F, bd.MultiSampleType, bd.MultiSampleQuality, FALSE, &hdr_ms, NULL));
    ok = ok && make_target(d, &zt, w / 2, h / 2, D3DFMT_R32F);
    ok = ok && SUCCEEDED(IDirect3DDevice9_CreateDepthStencilSurface(d, w / 2, h / 2, D3DFMT_D24X8, D3DMULTISAMPLE_NONE, 0, TRUE, &z_depth, NULL));
    ok = ok && make_target(d, &ao[0], w / 2, h / 2, D3DFMT_A8R8G8B8) && make_target(d, &ao[1], w / 2, h / 2, D3DFMT_A8R8G8B8);
    UINT bw = w, bh = h;
    for (int i = 0; ok && i < NBLOOM; i++) {
        bw = bw > 3 ? bw / 2 : 2, bh = bh > 3 ? bh / 2 : 2;
        ok = make_target(d, &bloom[i], bw, bh, D3DFMT_A16B16G16R16F);
    }
    if (ok && !smap) {
        ok = SUCCEEDED(IDirect3DDevice9_CreateTexture(d, SMAP, SMAP, 1, D3DUSAGE_DEPTHSTENCIL, D3DFMT_D24S8, D3DPOOL_DEFAULT, &smap, NULL))
             && SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(smap, 0, &smap_s))
             && SUCCEEDED(IDirect3DDevice9_CreateTexture(d, CMAP, CMAP, 1, D3DUSAGE_DEPTHSTENCIL, D3DFMT_D24S8, D3DPOOL_DEFAULT, &cmap, NULL))
             && SUCCEEDED(IDirect3DTexture9_GetSurfaceLevel(cmap, 0, &cmap_s))
             && SUCCEEDED(IDirect3DDevice9_CreateRenderTarget(d, SMAP, SMAP, D3DFMT_R5G6B5, D3DMULTISAMPLE_NONE, 0, FALSE, &null_s, NULL))
             && SUCCEEDED(IDirect3DDevice9_CreateRenderTarget(d, CMAP, CMAP, D3DFMT_R5G6B5, D3DMULTISAMPLE_NONE, 0, FALSE, &null_c, NULL));
        shadow_built = 0;
    }
    if (!ok) {
        log_line("hd: render targets failed at %ux%u, %u samples", w, h, bd.MultiSampleType);
        broken = 1;
        return 0;
    }
    tw = w, th = h, tms = bd.MultiSampleType, tq = bd.MultiSampleQuality;
    log_line("hd: targets %ux%u, %u samples", w, h, tms);
    return 1;
}

static IDirect3DSurface9 *hdr_surface(void) { return hdr_ms && !preview ? hdr_ms : hdr.s; }

// Not the back buffer: a map preview, kept when its depth buffer (not multisampled) covers the HDR texture.
static int take_preview(hd_dev d, const D3DVIEWPORT9 *v)
{
    IDirect3DSurface9 *rt = NULL, *bb = NULL, *ds = NULL;
    D3DSURFACE_DESC dd = { 0 };
    IDirect3DDevice9_GetRenderTarget(d, 0, &rt);
    IDirect3DDevice9_GetBackBuffer(d, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    if (bb) IDirect3DSurface9_Release(bb);
    if (!rt || rt == bb) {
        if (rt) IDirect3DSurface9_Release(rt);
        return 1;
    }
    IDirect3DDevice9_GetDepthStencilSurface(d, &ds);
    if (ds) IDirect3DSurface9_GetDesc(ds, &dd), IDirect3DSurface9_Release(ds);
    if (dd.Width < tw || dd.Height < th || dd.MultiSampleType || v->X || v->Y) {
        IDirect3DSurface9_Release(rt);
        return 0;
    }
    preview = rt, pvp = *v;
    return 1;
}

void hd_redirect(hd_dev d)
{
    if (redirected || post_done || scene_no < 0 || !make_targets(d)) return;
    D3DVIEWPORT9 v;
    IDirect3DDevice9_GetViewport(d, &v);
    if (!take_preview(d, &v)) return;
    IDirect3DDevice9_SetRenderTarget(d, 0, hdr_surface());
    if (!preview) IDirect3DDevice9_SetViewport(d, &v); // a preview clears all of it: the bloom reaches past its part
    // Alpha starts at 1 and only character draws write it (hd_char_alpha): the bloom leaves them out.
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 8);
    IDirect3DDevice9_Clear(d, 0, NULL, D3DCLEAR_TARGET, 0xff000000, 1.0f, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 7);
    IDirect3DDevice9_SetViewport(d, &v);
    redirected = 1;
}

void hd_rebind(hd_dev d, int on_bb)
{
    if (!redirected) return;
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, on_bb ? 7 : 15); // the game's own targets keep their alpha
    if (!on_bb) return;
    D3DVIEWPORT9 v;
    IDirect3DDevice9_GetViewport(d, &v);
    IDirect3DDevice9_SetRenderTarget(d, 0, hdr_surface());
    IDirect3DDevice9_SetViewport(d, &v);
}

int hd_redirected(void) { return redirected; }
int hd_post_done(void) { return post_done; }
int hd_additions_done(void) { return additions_done; }

// --- common pass state --------------------------------------------------------------------------
// A block of only what our passes change (each set once while recording). D3DSBT_ALL also copied every transform
// and constant: 40 us per capture and again per apply, 18 of each a frame in the zoo hub.
static void record_block(hd_dev d)
{
    DWORD v;
    float c[128][4];
    IDirect3DDevice9_BeginStateBlock(d);
    for (DWORD s = D3DRS_ZENABLE; s <= D3DRS_BLENDOPALPHA; s++)
        if (SUCCEEDED(IDirect3DDevice9_GetRenderState(d, s, &v))) IDirect3DDevice9_SetRenderState(d, s, v);
    for (DWORD i = 0; i < 16; i++) {
        IDirect3DBaseTexture9 *t = NULL;
        IDirect3DDevice9_GetTexture(d, i, &t);
        IDirect3DDevice9_SetTexture(d, i, t);
        if (t) IDirect3DBaseTexture9_Release(t);
        for (DWORD s = D3DSAMP_ADDRESSU; s <= D3DSAMP_DMAPOFFSET; s++)
            if (SUCCEEDED(IDirect3DDevice9_GetSamplerState(d, i, s, &v))) IDirect3DDevice9_SetSamplerState(d, i, s, v);
        for (DWORD s = D3DTSS_COLOROP; i < 8 && s <= D3DTSS_CONSTANT; s++)
            if (SUCCEEDED(IDirect3DDevice9_GetTextureStageState(d, i, s, &v))) IDirect3DDevice9_SetTextureStageState(d, i, s, v);
    }
    IDirect3DVertexShader9 *vs = NULL;
    IDirect3DPixelShader9 *ps = NULL;
    IDirect3DVertexDeclaration9 *decl = NULL;
    IDirect3DIndexBuffer9 *ix = NULL;
    IDirect3DDevice9_GetVertexShader(d, &vs), IDirect3DDevice9_SetVertexShader(d, vs);
    IDirect3DDevice9_GetPixelShader(d, &ps), IDirect3DDevice9_SetPixelShader(d, ps);
    IDirect3DDevice9_GetVertexDeclaration(d, &decl), IDirect3DDevice9_SetVertexDeclaration(d, decl);
    IDirect3DDevice9_GetIndices(d, &ix), IDirect3DDevice9_SetIndices(d, ix);
    if (vs) IDirect3DVertexShader9_Release(vs);
    if (ps) IDirect3DPixelShader9_Release(ps);
    if (decl) IDirect3DVertexDeclaration9_Release(decl);
    if (ix) IDirect3DIndexBuffer9_Release(ix);
    for (UINT i = 0; i < 2; i++) {
        IDirect3DVertexBuffer9 *b = NULL;
        UINT off = 0, stride = 0;
        IDirect3DDevice9_GetStreamSource(d, i, &b, &off, &stride), IDirect3DDevice9_SetStreamSource(d, i, b, off, stride);
        if (b) IDirect3DVertexBuffer9_Release(b);
        UINT freq = 1;
        IDirect3DDevice9_GetStreamSourceFreq(d, i, &freq), IDirect3DDevice9_SetStreamSourceFreq(d, i, freq);
    }
    D3DVIEWPORT9 vp;
    IDirect3DDevice9_GetViewport(d, &vp), IDirect3DDevice9_SetViewport(d, &vp);
    IDirect3DDevice9_GetVertexShaderConstantF(d, 0, c[0], 128), IDirect3DDevice9_SetVertexShaderConstantF(d, 0, c[0], 128);
    IDirect3DDevice9_GetPixelShaderConstantF(d, 0, c[0], 40), IDirect3DDevice9_SetPixelShaderConstantF(d, 0, c[0], 40);
    IDirect3DDevice9_EndStateBlock(d, &sb);
}

static void save_state(hd_dev d)
{
    if (!sb) record_block(d);
    else IDirect3DStateBlock9_Capture(sb);
}

static int common_bound, quick_ok;

// The block holds the samplers as they were when it was captured, so ours need binding again after it.
static void restore_state(hd_dev d)
{
    if (sb) IDirect3DStateBlock9_Apply(sb);
    common_bound = quick_ok = 0;
}

static void sampler(hd_dev d, DWORD s, DWORD filter, DWORD mip, DWORD address)
{
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_MAGFILTER, filter == D3DTEXF_ANISOTROPIC ? D3DTEXF_LINEAR : filter);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_MINFILTER, filter);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_MIPFILTER, mip);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_MAXANISOTROPY, 8);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_ADDRESSU, address);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_ADDRESSV, address);
    IDirect3DDevice9_SetSamplerState(d, s, D3DSAMP_ADDRESSW, address);
}

void hd_camera(hd_dev d)
{
    float v[4][4], p[4][4], t[4][4];
    IDirect3DDevice9_GetTransform(d, D3DTS_VIEW, (D3DMATRIX *)v);
    IDirect3DDevice9_GetTransform(d, D3DTS_PROJECTION, (D3DMATRIX *)p);
    if (p[2][3] != 1) return; // a flat 2D projection: keep the last camera
    memcpy(view, v, 64), memcpy(proj, p, 64);
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) t[i][j] = v[i][0] * p[0][j] + v[i][1] * p[1][j] + v[i][2] * p[2][j] + v[i][3] * p[3][j];
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++) clip_rows[i][j] = t[j][i];
    for (int a = 0; a < 3; a++) eye[a] = -(v[3][0] * v[a][0] + v[3][1] * v[a][1] + v[3][2] * v[a][2]);
}

const float *hd_view(void) { return view[0]; }
const float *hd_proj(void) { return proj[0]; }

static void vs_constants(hd_dev d, const float rows[4][4], const float *world)
{
    static const float id[3][4] = { { 1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 0, 0, 1, 0 } };
    float c[16][4] = { { 0 } };
    memcpy(c[0], rows, 64);
    memcpy(c[10], world ? world : id[0], 48);
    c[13][0] = eye[0], c[13][1] = eye[1], c[13][2] = eye[2], c[13][3] = now_s;
    float span = lv.fade1 - lv.fade0;
    c[14][0] = 7, c[14][1] = 1.6f, c[14][2] = lv.fade0, c[14][3] = 1 / (span > 1 ? span : 1);
    memcpy(c[15], player, 16);
    IDirect3DDevice9_SetVertexShaderConstantF(d, 0, c[0], 16);
}

static void ps_constants(hd_dev d)
{
    float c[16][4] = { { 0 } };
    float texel = 2 * shadow_hw / SMAP, soft = lv.soft * 900 / (texel > 0 ? texel : 1);
    memcpy(c[0], lv.sun, 12), memcpy(c[1], lv.sun_col, 12), memcpy(c[2], lv.sky, 12), memcpy(c[3], lv.ground, 12);
    c[2][3] = lv.sky_scale;
    memcpy(c[4], lv.fog, 12), c[4][3] = lv.fog_start;
    c[5][0] = 1 / (lv.fog_end > lv.fog_start ? lv.fog_end - lv.fog_start : 1), c[5][1] = lv.clarity, c[5][2] = lv.water_h, c[5][3] = soft < 1.2f ? 1.2f : soft > 6 ? 6 : soft;
    memcpy(c[6], eye, 12), c[6][3] = now_s;
    float sw = preview ? pvp.Width : tw, sh = preview ? pvp.Height : th; // what the depth prepass covered
    c[7][0] = sw ? 1.0f / sw : 0, c[7][1] = sh ? 1.0f / sh : 0, c[7][2] = prepass_done ? lv.ao_strength : 0;
    memcpy(c[8], srows, 48), memcpy(c[11], crows, 48);
    c[14][0] = 1.0f / SMAP, c[14][1] = 1.0f / CMAP;
    memcpy(c[15], lv.water, 12);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 0, c[0], 16);
    float lit[3][4] = { { light_grid[0], light_grid[1], light_grid[2], light_grid[3] }, { lv.hold, lv.exposure, lv.contrast * 1.26f, lv.shadow_y + origin[1] },
                        { lv.unbake_keep, 0, 0, 0 } }; // c27 lights, c28 hold, c29 unbake (the world's; characters overwrite them)
    IDirect3DDevice9_SetPixelShaderConstantF(d, 27, lit[0], 3);
}

void hd_invalidate(void) { quick_ok = 0; }

// Bound once a frame, after the depth pass has produced what they read.
static void bind_common(hd_dev d)
{
    if (common_bound) return;
    common_bound = 1;
    IDirect3DDevice9_SetTexture(d, SMP_SKY, (IDirect3DBaseTexture9 *)sky_tex);
    sampler(d, SMP_SKY, D3DTEXF_LINEAR, D3DTEXF_LINEAR, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetTexture(d, SMP_SHADOW, shadow_built ? (IDirect3DBaseTexture9 *)smap : (IDirect3DBaseTexture9 *)white);
    IDirect3DDevice9_SetTexture(d, SMP_CMAP, cmap_used ? (IDirect3DBaseTexture9 *)cmap : (IDirect3DBaseTexture9 *)white);
    sampler(d, SMP_SHADOW, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    sampler(d, SMP_CMAP, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetTexture(d, SMP_AO, prepass_done ? (IDirect3DBaseTexture9 *)ao[1].t : (IDirect3DBaseTexture9 *)white);
    sampler(d, SMP_AO, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetTexture(d, SMP_DEPTH, prepass_done ? (IDirect3DBaseTexture9 *)zt.t : (IDirect3DBaseTexture9 *)white);
    sampler(d, SMP_DEPTH, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    sampler(d, SMP_NORMAL, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    sampler(d, SMP_ALBEDO, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    sampler(d, SMP_NORMAL2, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    sampler(d, SMP_ALBEDO2, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    sampler(d, SMP_FUR, D3DTEXF_LINEAR, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    if (light_tex) {
        IDirect3DDevice9_SetTexture(d, SMP_LIGHTS, (IDirect3DBaseTexture9 *)light_tex);
        sampler(d, SMP_LIGHTS, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    }
}

static void unbind_common(hd_dev d)
{
    if (!common_bound) return;
    for (DWORD s = light_tex ? SMP_LIGHTS : SMP_DEPTH; s <= SMP_NORMAL2; s++) IDirect3DDevice9_SetTexture(d, s, NULL);
    common_bound = 0, quick_ok = 0;
}

// --- additions ----------------------------------------------------------------------------------
static void cull(const float rows[4][4], const float *from, float reach)
{
    for (UINT i = 0; i < nchunks; i++) {
        const struct chunk *k = &chunks[i];
        int out[6] = { 0 };
        for (int corner = 0; corner < 8; corner++) {
            float p[3] = { corner & 1 ? k->hi[0] : k->lo[0], corner & 2 ? k->hi[1] : k->lo[1], corner & 4 ? k->hi[2] : k->lo[2] }, q[4];
            for (int a = 0; a < 4; a++) q[a] = dot3(rows[a], p) + rows[a][3];
            out[0] += q[0] < -q[3], out[1] += q[0] > q[3], out[2] += q[1] < -q[3], out[3] += q[1] > q[3], out[4] += q[2] < 0, out[5] += q[2] > q[3];
        }
        vis[i] = !(out[0] == 8 || out[1] == 8 || out[2] == 8 || out[3] == 8 || out[4] == 8 || out[5] == 8);
        if (vis[i] && from) { // bit 1: within grass range
            float dd = 0;
            for (int a = 0; a < 3; a++) {
                float e = from[a] < k->lo[a] ? k->lo[a] - from[a] : from[a] > k->hi[a] ? from[a] - k->hi[a] : 0;
                dd += e * e;
            }
            if (dd < reach * reach) vis[i] |= 2;
            if (dd < NEAR_END * NEAR_END) vis[i] |= 4;
        }
    }
}

static void bind_material(hd_dev d, const struct mat *m, int pass)
{
    float c[3][4] = { { m->tile > 0 ? 1 / m->tile : 0, m->nstrength, m->rough, m->kind == CARD || m->kind == GRASS ? m->cut : 0.02f },
                      { m->tint[0], m->tint[1], m->tint[2], 1 }, { 0, 0, 1, m->flags & F_TRIPLANAR ? 1.0f : 0 } };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 16, c[0], 3);
    IDirect3DDevice9_SetTexture(d, 0, m->albedo ? (IDirect3DBaseTexture9 *)m->albedo : (IDirect3DBaseTexture9 *)white);
    IDirect3DVertexShader9 *vs = m->kind == GRASS ? v_grass : m->flags & F_WIND ? v_wind : v_inst;
    if (pass == PASS_GLASS) { // steel is solid: its own back and the bars behind it mustn't blend through
        IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, m->nstrength > 0.5f ? D3DCULL_CW : D3DCULL_NONE);
        IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, m->nstrength > 0.5f);
        IDirect3DDevice9_SetVertexShader(d, v_inst);
        IDirect3DDevice9_SetPixelShader(d, p_glass);
        return;
    }
    if (pass == PASS_NEAR_Z) { // the colour pass's vertex shaders, so its depth matches exactly
        IDirect3DDevice9_SetVertexShader(d, vs);
        IDirect3DDevice9_SetPixelShader(d, p_depth);
        IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, m->flags & F_TWOSIDED || m->kind == GRASS || m->kind == CARD ? D3DCULL_NONE : D3DCULL_CW);
        return;
    }
    if (pass != PASS_COLOUR && pass != PASS_NEAR) {
        IDirect3DDevice9_SetVertexShader(d, m->kind == GRASS ? v_grass_z : v_inst_z);
        IDirect3DDevice9_SetPixelShader(d, p_depth);
        return;
    }
    IDirect3DDevice9_SetTexture(d, SMP_NORMAL, m->normal ? (IDirect3DBaseTexture9 *)m->normal : (IDirect3DBaseTexture9 *)flat);
    IDirect3DDevice9_SetTexture(d, SMP_ALBEDO, m->albedo ? (IDirect3DBaseTexture9 *)m->albedo : (IDirect3DBaseTexture9 *)white);
    IDirect3DDevice9_SetVertexShader(d, vs);
    IDirect3DDevice9_SetPixelShader(d, m->kind == GRASS ? p_grass : m->kind == CARD ? p_card : m->tile > 0 ? p_tiled : p_inst);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, m->flags & F_TWOSIDED || m->kind == GRASS || m->kind == CARD ? D3DCULL_NONE : D3DCULL_CW);
    int cov = atoc && tms && pass == PASS_COLOUR && (m->kind == CARD || m->kind == GRASS);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ADAPTIVETESS_Y, cov ? MAKEFOURCC('A', 'T', 'O', 'C') : 0);
}

static int chunk_on(UINT chunk, int pass, int kind)
{
    if (pass == PASS_SHADOW) return 1;
    if (pass >= PASS_NEAR_Z) return vis[chunk] & 4;
    return vis[chunk] & (kind == GRASS ? 2 : 1);
}

static void draw_instances(hd_dev d, int pass)
{
    if (!ivb || !vb || !ib) return;
    IDirect3DDevice9_SetVertexDeclaration(d, d_inst);
    IDirect3DDevice9_SetStreamSource(d, 0, vb, 0, 36);
    IDirect3DDevice9_SetIndices(d, ib);
    IDirect3DDevice9_SetStreamSourceFreq(d, 1, D3DSTREAMSOURCE_INSTANCEDATA | 1);
    sampler(d, 0, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    for (UINT i = 0; i < nprotos; i++) {
        const struct proto *q = &protos[i];
        if (!q->nrun) continue;
        for (UINT s = q->sub0; s < q->sub0 + q->nsub; s++) {
            const struct sub *e = &subs[s];
            if (e->mat >= nmats || !e->count) continue;
            const struct mat *m = &mats[e->mat];
            if (m->kind == WATER_KIND || (m->kind == GLASS_KIND) != (pass == PASS_GLASS) || (m->kind == CASTER_KIND && pass != PASS_SHADOW)) continue;
            if (pass == PASS_SHADOW && m->kind == GRASS) continue; // grass shadowing itself is what made the dark speckle
            bind_material(d, m, pass);
            for (UINT r = q->run0; r < q->run0 + q->nrun; ) {
                const struct run *a = &runs[r];
                int on = chunk_on(a->chunk, pass, m->kind);
                if (!on) { r++; continue; }
                UINT n = a->n, e2 = r + 1;
                for (; e2 < q->run0 + q->nrun; e2++) { // neighbouring visible chunks go in one draw
                    int on2 = chunk_on(runs[e2].chunk, pass, m->kind);
                    if (!on2 || runs[e2].first != a->first + n) break;
                    n += runs[e2].n;
                }
                IDirect3DDevice9_SetStreamSource(d, 1, ivb, a->first * INST_STRIDE, INST_STRIDE);
                IDirect3DDevice9_SetStreamSourceFreq(d, 0, D3DSTREAMSOURCE_INDEXEDDATA | n);
                IDirect3DDevice9_DrawIndexedPrimitive(d, D3DPT_TRIANGLELIST, q->base, 0, q->nv, e->first, e->count / 3);
                r = e2;
            }
        }
    }
    IDirect3DDevice9_SetStreamSourceFreq(d, 0, 1);
    IDirect3DDevice9_SetStreamSourceFreq(d, 1, 1);
    IDirect3DDevice9_SetStreamSource(d, 1, NULL, 0, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ADAPTIVETESS_Y, 0);
}

static void plain_states(hd_dev d)
{
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHATESTENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_FOGENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_STENCILENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 7);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRGBWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DEPTHBIAS, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SLOPESCALEDEPTHBIAS, 0);
}

// First thing in the 3D pass, so whatever backdrop the game itself draws (a paper book's stars) lands over it.
void hd_sky(hd_dev d)
{
    if (sky_done || !sky_tex || scene_no < 0) return;
    sky_done = 1;
    hd_camera(d);
    save_state(d);
    plain_states(d);
    ps_constants(d);
    float p00 = proj[0][0] ? proj[0][0] : 1, p11 = proj[1][1] ? proj[1][1] : 1, ray[3][4];
    for (int i = 0; i < 3; i++) ray[i][0] = view[i][0] / p00, ray[i][1] = view[i][1] / p11, ray[i][2] = view[i][2], ray[i][3] = 0;
    IDirect3DDevice9_SetVertexShaderConstantF(d, 4, ray[0], 3);
    IDirect3DDevice9_SetTexture(d, SMP_SKY, (IDirect3DBaseTexture9 *)sky_tex);
    sampler(d, SMP_SKY, D3DTEXF_LINEAR, D3DTEXF_LINEAR, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetVertexDeclaration(d, d_quad);
    IDirect3DDevice9_SetVertexShader(d, v_sky);
    IDirect3DDevice9_SetPixelShader(d, p_sky);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    float q[4][6] = { { -1, 1, 0, 1, 0, 0 }, { 1, 1, 0, 1, 1, 0 }, { -1, -1, 0, 1, 0, 1 }, { 1, -1, 0, 1, 1, 1 } };
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, q, 24);
    IDirect3DDevice9_SetTexture(d, SMP_SKY, NULL);
    restore_state(d);
}

// Water protos, blended over the bed the depth pass saw.
static void draw_water(hd_dev d)
{
    if (!ivb || !vb || !ib) return;
    vs_constants(d, clip_rows, NULL);
    ps_constants(d);
    IDirect3DDevice9_SetVertexDeclaration(d, d_inst);
    IDirect3DDevice9_SetStreamSource(d, 0, vb, 0, 36);
    IDirect3DDevice9_SetIndices(d, ib);
    IDirect3DDevice9_SetStreamSourceFreq(d, 1, D3DSTREAMSOURCE_INSTANCEDATA | 1);
    IDirect3DDevice9_SetVertexShader(d, v_water);
    IDirect3DDevice9_SetPixelShader(d, p_water);
    float zproj[4] = { proj[2][2], proj[3][2], 0, 0 };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 33, zproj, 1);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    for (UINT i = 0; i < nprotos; i++) {
        const struct proto *q = &protos[i];
        for (UINT s = q->sub0; s < q->sub0 + q->nsub; s++) {
            const struct sub *e = &subs[s];
            if (e->mat >= nmats || mats[e->mat].kind != WATER_KIND || !e->count) continue;
            const struct mat *m = &mats[e->mat];
            float c[4] = { m->tile > 0 ? 1 / m->tile : 0, m->nstrength, m->rough, 0 };
            IDirect3DDevice9_SetPixelShaderConstantF(d, 16, c, 1);
            IDirect3DDevice9_SetTexture(d, SMP_NORMAL, m->normal ? (IDirect3DBaseTexture9 *)m->normal : (IDirect3DBaseTexture9 *)flat);
            for (UINT r = q->run0; r < q->run0 + q->nrun; r++) {
                if (!(vis[runs[r].chunk] & 1)) continue;
                IDirect3DDevice9_SetStreamSource(d, 1, ivb, runs[r].first * INST_STRIDE, INST_STRIDE);
                IDirect3DDevice9_SetStreamSourceFreq(d, 0, D3DSTREAMSOURCE_INDEXEDDATA | runs[r].n);
                IDirect3DDevice9_DrawIndexedPrimitive(d, D3DPT_TRIANGLELIST, q->base, 0, q->nv, e->first, e->count / 3);
            }
        }
    }
    IDirect3DDevice9_SetStreamSourceFreq(d, 0, 1);
    IDirect3DDevice9_SetStreamSourceFreq(d, 1, 1);
    IDirect3DDevice9_SetStreamSource(d, 1, NULL, 0, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, FALSE);
}

void hd_additions(hd_dev d)
{
    if (additions_done || scene_no < 0) return;
    additions_done = 1;
    save_state(d);
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    if (atoc && tms) IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHATESTENABLE, TRUE), IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHAFUNC, D3DCMP_GREATER), IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHAREF, 0);
    vs_constants(d, clip_rows, NULL);
    ps_constants(d);
    bind_common(d);
    cull(clip_rows, eye, lv.fade1);
    float fade[4] = { 0, 1, 0, 0 };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 32, fade, 1);
    draw_instances(d, PASS_COLOUR);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHATESTENABLE, FALSE);
    draw_water(d);
    restore_state(d);
    quick_ok = 0;
}

// Scenery by the camera, faded: its nearest surface only (depth first), over everything else the 3D pass drew.
static void draw_near(hd_dev d)
{
    UINT any = 0;
    for (UINT i = 0; i < nchunks; i++) any |= vis[i] & 4;
    if (!any) return;
    save_state(d);
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    vs_constants(d, clip_rows, NULL);
    ps_constants(d);
    bind_common(d);
    float fade[4] = { 1, -1, 0, 0 };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 32, fade, 1);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 0);
    draw_instances(d, PASS_NEAR_Z);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 7);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    draw_instances(d, PASS_NEAR);
    restore_state(d);
    quick_ok = 0;
}

// A backdrop panel the look data redraws: its own texture, kept at its painted colour through the tone curve.
int hd_space_begin(hd_dev d, unsigned long long hash)
{
    IDirect3DTexture9 *t = NULL;
    for (UINT i = 0; i < npaints; i++)
        if (paints[i].hash == hash) t = paints[i].t;
    if (!t) return 0;
    save_state(d);
    float hold[4] = { 1, lv.exposure, lv.contrast * 1.26f, 0 };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 28, hold, 1);
    IDirect3DDevice9_SetTexture(d, 0, (IDirect3DBaseTexture9 *)t);
    sampler(d, 0, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetPixelShader(d, p_space);
    return 1;
}

void hd_space_end(hd_dev d) { restore_state(d); }

// Over everything the 3D pass drew, so what is behind the glass stays sharp.
static void draw_glass(hd_dev d)
{
    if (!has_glass) return;
    save_state(d);
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    vs_constants(d, clip_rows, NULL);
    ps_constants(d);
    draw_instances(d, PASS_GLASS);
    restore_state(d);
    quick_ok = 0;
}

// --- depth pass and shadow maps -----------------------------------------------------------------
int hd_prepass_needed(void) { return !prepass_done && scene_no >= 0 && redirected; }

void hd_prepass_begin(hd_dev d)
{
    unbind_common(d);
    save_state(d);
    plain_states(d);
    IDirect3DDevice9_GetRenderTarget(d, 0, &saved_rt);
    IDirect3DDevice9_GetDepthStencilSurface(d, &saved_ds);
    IDirect3DDevice9_GetViewport(d, &saved_vp);
    IDirect3DDevice9_SetRenderTarget(d, 0, zt.s);
    IDirect3DDevice9_SetDepthStencilSurface(d, z_depth);
    IDirect3DDevice9_Clear(d, 0, NULL, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, 0xffffffff, 1.0f, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    vs_constants(d, clip_rows, NULL);
    float mat[4] = { 0, 0, 0, 0.02f };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 16, mat, 1);
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetVertexShader(d, v_world_z);
    IDirect3DDevice9_SetPixelShader(d, p_depth);
}

static float quad_u = 1, quad_v = 1; // how much of the source a full-screen pass reads

static void fullscreen(hd_dev d, const struct target *to, IDirect3DPixelShader9 *ps, IDirect3DTexture9 *t0, IDirect3DTexture9 *t1, float tx, float ty)
{
    IDirect3DDevice9_SetRenderTarget(d, 0, to->s);
    float c[4] = { tx, ty, 1.0f / to->w, 1.0f / to->h };
    IDirect3DDevice9_SetVertexShaderConstantF(d, 0, c, 1);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 0, c, 1);
    IDirect3DDevice9_SetPixelShader(d, ps);
    IDirect3DDevice9_SetTexture(d, 0, (IDirect3DBaseTexture9 *)t0);
    IDirect3DDevice9_SetTexture(d, 1, (IDirect3DBaseTexture9 *)t1);
    float q[4][6] = { { -1, 1, 0, 1, 0, 0 }, { 1, 1, 0, 1, quad_u, 0 }, { -1, -1, 0, 1, 0, quad_v }, { 1, -1, 0, 1, quad_u, quad_v } };
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, q, 24);
}

static void quad_states(hd_dev d)
{
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 15);
    IDirect3DDevice9_SetDepthStencilSurface(d, NULL);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetVertexDeclaration(d, d_quad);
    IDirect3DDevice9_SetVertexShader(d, v_quad);
}

static int quarter_ao(hd_dev d)
{
    if (zq.t) return 1;
    if (make_target(d, &zq, zt.w / 2, zt.h / 2, D3DFMT_R32F) && make_target(d, &aq[0], zq.w, zq.h, D3DFMT_A8R8G8B8)
        && make_target(d, &aq[1], zq.w, zq.h, D3DFMT_A8R8G8B8)) return 1;
    drop(&zq), drop(&aq[0]), drop(&aq[1]);
    return 0;
}

void hd_prepass_end(hd_dev d)
{
    cull(clip_rows, eye, lv.fade1);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHATESTENABLE, FALSE);
    draw_instances(d, PASS_DEPTH);
    quad_states(d);
    sampler(d, 0, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    sampler(d, 1, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    float pr[4] = { proj[0][0] ? 1 / proj[0][0] : 1, proj[1][1] ? 1 / proj[1][1] : 1, lv.ao_radius, lv.ao_strength };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 3, pr, 1);
    if (lowres & 1 && quarter_ao(d)) {
        // AO at quarter size on a point-sampled copy of the depth, then back to half size along depth edges
        IDirect3DDevice9_StretchRect(d, zt.s, NULL, zq.s, NULL, D3DTEXF_POINT);
        float qx = 1.0f / zq.w, qy = 1.0f / zq.h;
        fullscreen(d, &aq[0], p_ao, zq.t, NULL, qx, qy);
        sampler(d, 0, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
        fullscreen(d, &aq[1], p_blur, aq[0].t, zq.t, qx, 0);
        fullscreen(d, &aq[0], p_blur, aq[1].t, zq.t, 0, qy);
        fullscreen(d, &aq[1], p_blur, aq[0].t, zq.t, qx * 0.5f, qy * 0.5f);
        sampler(d, 0, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
        sampler(d, 2, D3DTEXF_POINT, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
        IDirect3DDevice9_SetTexture(d, 2, (IDirect3DBaseTexture9 *)zt.t);
        fullscreen(d, &ao[1], p_ao_up, aq[1].t, zq.t, qx, qy);
        IDirect3DDevice9_SetTexture(d, 2, NULL);
    } else {
        float tx = 1.0f / zt.w, ty = 1.0f / zt.h;
        fullscreen(d, &ao[0], p_ao, zt.t, NULL, tx, ty);
        sampler(d, 0, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
        fullscreen(d, &ao[1], p_blur, ao[0].t, zt.t, tx, 0);
        fullscreen(d, &ao[0], p_blur, ao[1].t, zt.t, 0, ty);
        fullscreen(d, &ao[1], p_blur, ao[0].t, zt.t, tx * 0.5f, ty * 0.5f);
    }
    IDirect3DDevice9_SetTexture(d, 0, NULL), IDirect3DDevice9_SetTexture(d, 1, NULL);
    IDirect3DDevice9_SetRenderTarget(d, 0, saved_rt);
    IDirect3DDevice9_SetDepthStencilSurface(d, saved_ds);
    IDirect3DSurface9_Release(saved_rt), saved_rt = NULL;
    IDirect3DSurface9_Release(saved_ds), saved_ds = NULL;
    restore_state(d);
    IDirect3DDevice9_SetViewport(d, &saved_vp);
    prepass_done = 1;
}

int hd_shadow_needed(void) { return !shadow_built && scene_no >= 0 && smap && hdr.t; }

// Orthographic light rows: uv + depth (rows) and clip (for rendering), centred on ctr.
static void light_rows(float rows[3][4], float cl[4][4], const float *ctr, float hw, float dmin, float dmax, float bias)
{
    float f[3] = { -lv.sun[0], -lv.sun[1], -lv.sun[2] }, hint[3] = { 0, 0, 1 }, rt[3], up[3];
    rt[0] = hint[1] * f[2] - hint[2] * f[1], rt[1] = hint[2] * f[0] - hint[0] * f[2], rt[2] = hint[0] * f[1] - hint[1] * f[0];
    norm3(rt);
    up[0] = f[1] * rt[2] - f[2] * rt[1], up[1] = f[2] * rt[0] - f[0] * rt[2], up[2] = f[0] * rt[1] - f[1] * rt[0];
    for (int k = 0; k < 3; k++)
        rows[0][k] = rt[k] / (2 * hw), rows[1][k] = -up[k] / (2 * hw), rows[2][k] = f[k] / (dmax - dmin);
    rows[0][3] = 0.5f - dot3(ctr, rt) / (2 * hw);
    rows[1][3] = 0.5f + dot3(ctr, up) / (2 * hw);
    rows[2][3] = -(dot3(ctr, f) + dmin) / (dmax - dmin);
    for (int k = 0; k < 4; k++)
        cl[0][k] = 2 * rows[0][k] - (k == 3), cl[1][k] = -2 * rows[1][k] + (k == 3), cl[2][k] = rows[2][k], cl[3][k] = k == 3;
    rows[2][3] -= bias;
}

static void shadow_target(hd_dev d, IDirect3DSurface9 *color, IDirect3DSurface9 *depth, UINT size)
{
    IDirect3DDevice9_GetRenderTarget(d, 0, &saved_rt);
    IDirect3DDevice9_GetDepthStencilSurface(d, &saved_ds);
    IDirect3DDevice9_GetViewport(d, &saved_vp);
    IDirect3DDevice9_SetRenderTarget(d, 0, color);
    IDirect3DDevice9_SetDepthStencilSurface(d, depth);
    D3DVIEWPORT9 v = { 0, 0, size, size, 0, 1 };
    IDirect3DDevice9_SetViewport(d, &v);
    IDirect3DDevice9_Clear(d, 0, NULL, D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 0);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
    union { float f; DWORD u; } slope = { 1.6f }, bias = { 0.00004f };
    IDirect3DDevice9_SetRenderState(d, D3DRS_SLOPESCALEDEPTHBIAS, slope.u);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DEPTHBIAS, bias.u);
    unbind_common(d);
}

static void shadow_done(hd_dev d)
{
    IDirect3DDevice9_SetRenderTarget(d, 0, saved_rt);
    IDirect3DDevice9_SetDepthStencilSurface(d, saved_ds);
    IDirect3DSurface9_Release(saved_rt), saved_rt = NULL;
    IDirect3DSurface9_Release(saved_ds), saved_ds = NULL;
    restore_state(d);
    IDirect3DDevice9_SetViewport(d, &saved_vp);
}

void hd_shadow_begin(hd_dev d)
{
    // The whole level's additions, plus a margin: a stable map made once.
    float lo[3] = { 1e9f, 1e9f, 1e9f }, hi[3] = { -1e9f, -1e9f, -1e9f }, ctr[3], hw = 0;
    for (UINT i = 0; i < nchunks; i++)
        for (int a = 0; a < 3; a++) {
            if (chunks[i].lo[a] < lo[a]) lo[a] = chunks[i].lo[a];
            if (chunks[i].hi[a] > hi[a]) hi[a] = chunks[i].hi[a];
        }
    for (int a = 0; a < 3; a++) ctr[a] = (lo[a] + hi[a]) / 2;
    for (int a = 0; a < 3; a += 2) if ((hi[a] - lo[a]) / 2 > hw) hw = (hi[a] - lo[a]) / 2;
    hw = hw * 1.15f + 800;
    shadow_hw = hw;
    float cl[4][4];
    light_rows(srows, cl, ctr, hw, -2 * hw, 2 * hw, 0.0004f);
    save_state(d);
    shadow_target(d, null_s, smap_s, SMAP);
    vs_constants(d, cl, NULL);
    float mat[4] = { 0, 0, 0, 0.1f };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 16, mat, 1);
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetVertexShader(d, v_world_z);
    IDirect3DDevice9_SetPixelShader(d, p_depth);
    memcpy(cclip, cl, 64);
    log_line("hd: static shadow map covers %.0f units", 2 * hw);
}

void hd_shadow_end(hd_dev d)
{
    float cl[4][4];
    memcpy(cl, cclip, 64);
    vs_constants(d, cl, NULL);
    draw_instances(d, PASS_SHADOW);
    IDirect3DDevice9_SetTexture(d, 0, NULL);
    shadow_done(d);
    shadow_built = 1;
}

void hd_cmap_begin(hd_dev d, const float *centre)
{
    float cl[4][4], snapped[3];
    memcpy(player, centre, 12), player[3] = 1 / 130.0f;
    // Move the map in whole texels along its two axes, so a walking character's shadow edge doesn't shimmer.
    float f[3] = { -lv.sun[0], -lv.sun[1], -lv.sun[2] }, rt[3] = { -f[1], f[0], 0 }, up[3], texel = 2 * 1400.0f / CMAP;
    norm3(rt);
    up[0] = f[1] * rt[2] - f[2] * rt[1], up[1] = f[2] * rt[0] - f[0] * rt[2], up[2] = f[0] * rt[1] - f[1] * rt[0];
    float x = dot3(centre, rt), y = dot3(centre, up), dx = floorf(x / texel) * texel - x, dy = floorf(y / texel) * texel - y;
    for (int k = 0; k < 3; k++) snapped[k] = centre[k] + rt[k] * dx + up[k] * dy;
    light_rows(crows, cl, snapped, 1400, -3000, 3000, 0.001f);
    memcpy(cclip, cl, 64);
    save_state(d);
    shadow_target(d, null_c, cmap_s, CMAP);
    IDirect3DDevice9_SetPixelShader(d, NULL);
    for (DWORD s = 0; s < 8; s++) IDirect3DDevice9_SetTexture(d, s, NULL);
    IDirect3DDevice9_SetVertexDeclaration(d, d_char);
    IDirect3DDevice9_SetVertexShader(d, v_char_z);
    cmap_used = 1;
}

const float *hd_cmap_clip(void) { return cclip[0]; }

void hd_cmap_draw(hd_dev d, struct IDirect3DVertexBuffer9 *v, unsigned stride, int type, unsigned start, unsigned count,
                  const float *bones, const float *light, int nbones)
{
    float n[4] = { (float)nbones, 0, 0, 0 };
    IDirect3DDevice9_SetVertexShaderConstantF(d, 0, bones, 48);
    IDirect3DDevice9_SetVertexShaderConstantF(d, 92, light, 4);
    IDirect3DDevice9_SetVertexShaderConstantF(d, 96, n, 1);
    IDirect3DDevice9_SetStreamSource(d, 0, v, 0, stride);
    IDirect3DDevice9_DrawPrimitive(d, (D3DPRIMITIVETYPE)type, start, count);
}

void hd_cmap_end(hd_dev d) { shadow_done(d); }

// --- game surfaces ------------------------------------------------------------------------------
static void make_wmat(struct wmat *e, UINT64 hash)
{
    const struct bind *b[2] = { NULL, NULL };
    int n = 0;
    memset(e, 0, sizeof *e);
    e->hash = hash;
    memcpy(e->emit, (float[4]){ 0, 0, 1, lv.unbake }, 16);
    for (UINT i = 0; i < nglows; i++)
        if (glows[i].hash == hash) {
            float span = glows[i].hi - glows[i].lo;
            e->emit[0] = glows[i].strength, e->emit[1] = glows[i].mask ? glows[i].lo : -1, e->emit[2] = glows[i].mask ? 1 / (fabsf(span) < 0.001f ? 0.001f : span) : 1;
        }
    for (UINT i = 0; i < nbinds && n < 2; i++)
        if (binds[i].hash == hash && (UINT)binds[i].mat < nmats) b[n++] = &binds[i];
    for (int k = 0; k < n; k++) {
        const struct mat *m = &mats[b[k]->mat];
        static const float weights[4][4] = { { 0, 0, 0, 0 }, { 1, -1, 0, 0 }, { 0.3f, 0.59f, 0.11f, 0 }, { 0, 0, 0, 1 } };
        memcpy(e->w[k], weights[b[k]->mask & 3], 16);
        float span = b[k]->hi - b[k]->lo;
        if (fabsf(span) < 0.001f) span = 0.001f;
        float c[3][4] = { { m->tile > 0 ? 1 / m->tile : 0, m->nstrength, m->rough, 0 }, { m->tint[0], m->tint[1], m->tint[2], 1 },
                          { (float)b[k]->mask, b[k]->mask ? b[k]->lo : -1, b[k]->mask ? 1 / span : 1, m->flags & F_TRIPLANAR ? 1.0f : 0 } };
        memcpy(e->c[k * 3], c, sizeof c);
        e->t[k * 2] = m->normal ? (IDirect3DBaseTexture9 *)m->normal : (IDirect3DBaseTexture9 *)flat;
        e->t[k * 2 + 1] = m->albedo ? (IDirect3DBaseTexture9 *)m->albedo : (IDirect3DBaseTexture9 *)white;
    }
    e->n = n;
}

void hd_world_material(hd_dev d, unsigned long long hash)
{
    struct wmat *e = NULL, spare;
    for (UINT i = (UINT)hash & 1023, tries = 0; hash && tries < 64 && !e; i = (i + 1) & 1023, tries++)
        if (wmats[i].hash == hash) e = &wmats[i];
        else if (!wmats[i].hash) make_wmat(e = &wmats[i], hash);
    if (!e) make_wmat(e = &spare, hash);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 26, e->emit, 1);
    if (!e->n) {
        IDirect3DDevice9_SetPixelShader(d, p_world);
        return;
    }
    for (int k = 0; k < e->n; k++) {
        IDirect3DDevice9_SetTexture(d, k ? SMP_NORMAL2 : SMP_NORMAL, e->t[k * 2]);
        IDirect3DDevice9_SetTexture(d, k ? SMP_ALBEDO2 : SMP_ALBEDO, e->t[k * 2 + 1]);
    }
    IDirect3DDevice9_SetPixelShaderConstantF(d, 16, e->c[0], e->n * 3);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 22, e->w[0], e->n);
    IDirect3DDevice9_SetPixelShader(d, e->n == 2 ? p_mat2 : p_mat);
}

void hd_world_begin(hd_dev d, const float *world)
{
    save_state(d);
    vs_constants(d, clip_rows, world);
    ps_constants(d);
    bind_common(d);
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetVertexShader(d, v_world);
    IDirect3DDevice9_SetRenderState(d, D3DRS_FOGENABLE, FALSE);
}

void hd_world_end(hd_dev d)
{
    restore_state(d);
    quick_ok = 0;
}

// A single game draw: only the world rows change between draws.
void hd_world_quick(hd_dev d, const float *world, unsigned long long hash)
{
    if (!quick_ok) {
        hd_camera(d);
        vs_constants(d, clip_rows, world);
        ps_constants(d);
        bind_common(d);
        quick_ok = 1;
    } else {
        IDirect3DDevice9_SetVertexShaderConstantF(d, 10, world, 3);
    }
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetVertexShader(d, v_world);
    hd_world_material(d, hash);
}

void hd_world_float(hd_dev d, float y)
{
    float c[4] = { y, 0, 0, 0 };
    IDirect3DDevice9_SetVertexShaderConstantF(d, 16, c, 1);
    IDirect3DDevice9_SetVertexShader(d, v_world_float);
}

void hd_world_quick_end(hd_dev d)
{
    IDirect3DDevice9_SetPixelShader(d, NULL);
}

int hd_solid_texture(unsigned long long h)
{
    UINT64 *p = bsearch(&h, solid_tex, nsolid_tex, sizeof *solid_tex, cmp_u64);
    return p != NULL;
}

// Sorted by key, then texture: one model can be placed in several paints.
int hd_solid_proto(unsigned long long key, unsigned long long tex)
{
    UINT lo = 0, hi = nsolids;
    while (lo < hi) {
        UINT mid = (lo + hi) / 2;
        if (solids[mid].key < key || (solids[mid].key == key && solids[mid].tex < tex)) lo = mid + 1;
        else hi = mid;
    }
    return lo < nsolids && solids[lo].key == key && solids[lo].tex == tex && solids[lo].proto < nprotos ? (int)solids[lo].proto : -1;
}

// A model is several game draws: the first one seen at a transform draws it all.
int hd_solid_claim(int proto, const float *world)
{
    for (UINT i = 0; i < ndone; i++)
        if (solid_done[i].proto == (UINT)proto && !memcmp(solid_done[i].world, world, 48)) return 0;
    if (ndone < 128) solid_done[ndone].proto = proto, memcpy(solid_done[ndone++].world, world, 48);
    return 1;
}

// Solid replacements wait here and are drawn together, with one state save, at the next game draw that isn't one:
// one at a time, a few hundred placed plants cost up to 7 ms a frame.
static struct { int proto; float world[12]; } solid_queue[512];
static UINT nqueued;

void hd_solid_draw(hd_dev d, int proto, const float *world)
{
    if (nqueued == sizeof solid_queue / sizeof *solid_queue) hd_solid_flush(d);
    solid_queue[nqueued].proto = proto;
    memcpy(solid_queue[nqueued++].world, world, 48);
}

void hd_solid_flush(hd_dev d)
{
    static const float no_fade[4] = { 0, 0, 0, 0 };
    if (!nqueued) return;
    hd_camera(d);
    save_state(d);
    plain_states(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZWRITEENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ZFUNC, D3DCMP_LESSEQUAL);
    ps_constants(d);
    bind_common(d);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 32, no_fade, 1);
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetStreamSource(d, 0, vb, 0, 36);
    IDirect3DDevice9_SetIndices(d, ib);
    sampler(d, 0, D3DTEXF_ANISOTROPIC, D3DTEXF_LINEAR, D3DTADDRESS_WRAP);
    IDirect3DDevice9_SetVertexShader(d, v_world);
    IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE); // the game's transforms can mirror
    for (UINT k = 0; k < nqueued; k++) {
        const struct proto *q = &protos[solid_queue[k].proto];
        vs_constants(d, clip_rows, solid_queue[k].world);
        for (UINT s = q->sub0; s < q->sub0 + q->nsub; s++) {
            if (subs[s].mat >= nmats || !subs[s].count) continue;
            bind_material(d, &mats[subs[s].mat], PASS_COLOUR);
            IDirect3DDevice9_SetVertexShader(d, v_world);
            IDirect3DDevice9_SetRenderState(d, D3DRS_CULLMODE, D3DCULL_NONE);
            IDirect3DDevice9_DrawIndexedPrimitive(d, D3DPT_TRIANGLELIST, q->base, 0, q->nv, subs[s].first, subs[s].count / 3);
        }
    }
    nqueued = 0;
    restore_state(d);
}

void hd_merge_buffers(hd_dev d, struct IDirect3DVertexBuffer9 *v, struct IDirect3DIndexBuffer9 *i)
{
    IDirect3DDevice9_SetStreamSource(d, 0, v, 0, 36);
    IDirect3DDevice9_SetIndices(d, i);
}

void hd_merge_draw(hd_dev d, unsigned nverts, unsigned first, unsigned tris)
{
    IDirect3DDevice9_DrawIndexedPrimitive(d, D3DPT_TRIANGLELIST, 0, 0, nverts, first, tris);
}

// Character draws write alpha 0, colour unchanged: the bloom's first step leaves those pixels out (hd_post).
// Everything else keeps alpha at the 1 hd_redirect cleared to.
static DWORD char_blend, char_src, char_dst;
void hd_char_alpha(hd_dev d, int on)
{
    if (on) {
        IDirect3DDevice9_GetRenderState(d, D3DRS_ALPHABLENDENABLE, &char_blend);
        IDirect3DDevice9_GetRenderState(d, D3DRS_SRCBLEND, &char_src);
        IDirect3DDevice9_GetRenderState(d, D3DRS_DESTBLEND, &char_dst);
        if (!char_blend) // the same colour as unblended
            IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, TRUE), IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_ONE),
            IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, D3DBLEND_ZERO);
        IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 15);
        IDirect3DDevice9_SetRenderState(d, D3DRS_SEPARATEALPHABLENDENABLE, TRUE);
        IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLENDALPHA, D3DBLEND_ZERO);
        IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLENDALPHA, D3DBLEND_ZERO);
    } else {
        IDirect3DDevice9_SetRenderState(d, D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
        IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 7);
        IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, char_blend);
        IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, char_src);
        IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, char_dst);
    }
}

void hd_char_begin(hd_dev d, const float *model_rows, float use_tex, float use_colour, float scale, const float *style, struct IDirect3DTexture9 *fur)
{
    // c24 stage 0, c26-c29 the two lamps nearest this character, c30 fill, c31 style, c34 hold: one upload per draw
    static float c[11][4];
    float k[4] = { use_tex, use_colour, scale, 0 };
    if (skin_mat >= 0 && !use_tex) { // no paint of its own: the level's hide goes through the fur path
        memcpy(c[7], style, 16), c[7][2] = mats[skin_mat].cut;
        k[3] = mats[skin_mat].tile / 36, fur = (struct IDirect3DTexture9 *)mats[skin_mat].albedo;
    } else memcpy(c[7], style, 16);
    memcpy(c[0], k, 16);
    if (char_at[0] != model_rows[3] || char_at[1] != model_rows[7] || char_at[2] != model_rows[11]) { // a batch of another model
        float d0 = 1e30f, d1 = 1e30f, (*two)[4] = c + 2;
        char_at[0] = model_rows[3], char_at[1] = model_rows[7], char_at[2] = model_rows[11];
        memset(two, 0, 64);
        for (UINT i = 0; i < nlights; i++) {
            const struct light *l = &lights[i];
            float x = l->p[0] - char_at[0], y = l->p[1] - char_at[1], z = l->p[2] - char_at[2], dd = x * x + y * y + z * z;
            float e[2][4] = { { l->p[0], l->p[1], l->p[2], 1 / (l->r * l->r) }, { l->c[0], l->c[1], l->c[2], 0 } };
            if (dd < d0) memcpy(two[2], two[0], 32), d1 = d0, memcpy(two[0], e, 32), d0 = dd;
            else if (dd < d1) memcpy(two[2], e, 32), d1 = dd;
        }
    }
    memcpy(c[6], (float[4]){ lv.char_fill[0], lv.char_fill[1], lv.char_fill[2], lv.char_keep }, 16);
    memcpy(c[10], (float[4]){ lv.exposure, lv.contrast * 1.26f, lv.sat * 1.17f, 0 }, 16);
    IDirect3DDevice9_SetVertexShaderConstantF(d, 60, model_rows, 3);
    ps_constants(d);
    IDirect3DDevice9_SetPixelShaderConstantF(d, 24, c[0], 11);
    bind_common(d);
    IDirect3DDevice9_SetTexture(d, SMP_FUR, (IDirect3DBaseTexture9 *)fur);
    IDirect3DDevice9_SetPixelShader(d, p_char);
    quick_ok = 0;
}

// A costume piece the game attaches to a character, drawn as a world draw (stage 0 texture x2 vertex colour).
void hd_prop_begin(hd_dev d, const float *world, const float *style, struct IDirect3DTexture9 *fur)
{
    float start, end;
    IDirect3DDevice9_GetRenderState(d, D3DRS_FOGSTART, (DWORD *)&start);
    IDirect3DDevice9_GetRenderState(d, D3DRS_FOGEND, (DWORD *)&end);
    float fog[4] = { end, 1 / (end - start > 1 ? end - start : 1), 0, 0 };
    hd_camera(d);
    vs_constants(d, clip_rows, world);
    IDirect3DDevice9_SetVertexShaderConstantF(d, 17, fog, 1);
    hd_char_begin(d, world, 1, 1, 2, style, fur);
    IDirect3DDevice9_SetVertexDeclaration(d, d_world);
    IDirect3DDevice9_SetVertexShader(d, v_prop);
}

void hd_char_end(hd_dev d)
{
    IDirect3DDevice9_SetTexture(d, SMP_FUR, NULL);
    IDirect3DDevice9_SetPixelShader(d, NULL);
}

void hd_glow_begin(hd_dev d, float scale, float strength)
{
    float k[4] = { scale, strength, lv.glow_add, 0 };
    IDirect3DDevice9_SetPixelShaderConstantF(d, 25, k, 1);
    IDirect3DDevice9_SetPixelShader(d, p_glow);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, lv.glow_add > 0 ? D3DBLEND_ONE : D3DBLEND_INVSRCCOLOR);
}

void hd_glow_end(hd_dev d, unsigned long dest_blend)
{
    IDirect3DDevice9_SetPixelShader(d, NULL);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, dest_blend);
}

// --- post ---------------------------------------------------------------------------------------
static int paused;
void hd_set_paused(int on) { paused = on; }

void hd_post(hd_dev d)
{
    if (!redirected) return;
    redirected = 0, post_done = 1;
    IDirect3DSurface9 *bb = NULL, *ds = NULL;
    D3DVIEWPORT9 v;
    IDirect3DDevice9_GetViewport(d, &v);
    IDirect3DDevice9_GetDepthStencilSurface(d, &ds);
    if (FAILED(IDirect3DDevice9_GetBackBuffer(d, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    if (additions_done) draw_near(d), draw_glass(d);
    if (hdr_ms && !preview) IDirect3DDevice9_StretchRect(d, hdr_ms, NULL, hdr.s, NULL, D3DTEXF_NONE);
    save_state(d);
    quad_states(d);
    for (DWORD s = 0; s < 2; s++) sampler(d, s, D3DTEXF_LINEAR, D3DTEXF_NONE, D3DTADDRESS_CLAMP);
    // The ini's numbers are Blender's: its glow is subtler and its AgX curve punchier than ours at the same values.
    // Each level adds about the same energy, so a chain without the half-size level is scaled up to match.
    int b0 = lowres & 2 ? 1 : 0;
    float b[3][4] = { { 0 }, { lv.bloom_t, lv.bloom_t * 0.5f, lv.bloom_s * 0.3f * (b0 ? (float)NBLOOM / (NBLOOM - 1) : 1), lv.exposure }, { lv.sat * 1.17f, lv.contrast * 1.26f, 0, 0 } };
    if (paused) b[1][0] = b[1][1] = 0, b[1][2] = 1.0f / (NBLOOM - b0), b[2][2] = 1, b[2][3] = 0.36f; // the bloom chain, unthresholded, is a blur of the picture
    IDirect3DDevice9_SetPixelShaderConstantF(d, 1, b[1], 2);
    fullscreen(d, &bloom[b0], p_bright, hdr.t, NULL, 1.0f / hdr.w, 1.0f / hdr.h);
    for (int i = b0 + 1; i < NBLOOM; i++)
        fullscreen(d, &bloom[i], p_down, bloom[i - 1].t, NULL, 1.0f / bloom[i - 1].w, 1.0f / bloom[i - 1].h);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_SRCBLEND, D3DBLEND_ONE);
    IDirect3DDevice9_SetRenderState(d, D3DRS_DESTBLEND, D3DBLEND_ONE);
    for (int i = NBLOOM - 1; i > b0; i--)
        fullscreen(d, &bloom[i - 1], p_up, bloom[i].t, NULL, 1.0f / bloom[i].w, 1.0f / bloom[i].h);
    IDirect3DDevice9_SetRenderState(d, D3DRS_ALPHABLENDENABLE, FALSE);
    D3DSURFACE_DESC pd = { .Width = tw, .Height = th };
    if (preview) IDirect3DSurface9_GetDesc(preview, &pd), quad_u = (float)pvp.Width / hdr.w, quad_v = (float)pvp.Height / hdr.h;
    struct target back = { NULL, preview ? preview : bb, pd.Width, pd.Height };
    fullscreen(d, &back, p_final, hdr.t, bloom[b0].t, 1.0f / hdr.w, 1.0f / hdr.h);
    quad_u = quad_v = 1;
    if (preview) IDirect3DSurface9_Release(preview), preview = NULL;
    IDirect3DDevice9_SetTexture(d, 0, NULL), IDirect3DDevice9_SetTexture(d, 1, NULL);
    restore_state(d);
    IDirect3DDevice9_SetRenderState(d, D3DRS_COLORWRITEENABLE, 15);
    IDirect3DDevice9_SetDepthStencilSurface(d, ds);
    IDirect3DDevice9_SetViewport(d, &v);
    if (ds) IDirect3DSurface9_Release(ds);
    IDirect3DSurface9_Release(bb);
}

static void check_lowres(void)
{
    FILE *f = capture_tests() ? fopen("taz-hd\\lowres", "r") : NULL;
    if (!f) return;
    if (fscanf(f, "%d", &lowres) != 1) lowres = 0;
    fclose(f);
    DeleteFileA("taz-hd\\lowres");
    log_line("hd: lowres %d", lowres);
}

void hd_frame_end(hd_dev d)
{
    LARGE_INTEGER c, f; // the shaders' clock, once a frame: under Wine each read is a system call
    QueryPerformanceCounter(&c), QueryPerformanceFrequency(&f);
    now_s = (float)fmod((double)c.QuadPart / f.QuadPart, 3600.0);
    hd_solid_flush(d);
    if (redirected) hd_post(d);
    unbind_common(d);
    post_done = additions_done = prepass_done = sky_done = 0;
    ndone = 0;
    check_reload(d);
    check_lowres();
}
