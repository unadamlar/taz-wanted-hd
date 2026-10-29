// Texture dump and replacement.
// The game fills each texture with LockRect/UnlockRect on level 0. At unlock we fingerprint the
// pixels; before each draw call we swap in a replacement from taz-hd\textures when one exists, found by the
// texture's original pak name (via taz-hd\fingerprints.tsv from tools/pak.py) or by <fingerprint>.png.
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "image.h"

#define DUMP_DIR "taz-hd\\dump"
#define REPLACE_DIR "taz-hd\\textures"
#define NAMES_FILE "taz-hd\\fingerprints.tsv"
#define TABLE 32768
#define MAX_UPDATES 8 // textures rewritten more often than this are animated; leave them alone

struct tex_entry { IDirect3DTexture8 *tex; UINT64 hash; BYTE *bits; INT pitch; int updates; };
struct rep_entry { UINT64 hash; IDirect3DTexture8 *rep; };
struct name_entry { UINT64 hash; char *path; };

static struct tex_entry texs[TABLE];
static struct rep_entry reps[TABLE];
static struct name_entry names[TABLE];
static int ntexs, nreps;
static CRITICAL_SECTION lock;
static IDirect3DDevice8 *device;
static int dumping, dumped, replaced;
static LONG draws, swaps;

static HRESULT (WINAPI *real_CreateTexture)(IDirect3DDevice8 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL, IDirect3DTexture8 **);
static HRESULT (WINAPI *real_SetTexture)(IDirect3DDevice8 *, DWORD, IDirect3DBaseTexture8 *);
static HRESULT (WINAPI *real_DrawPrimitive)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT);
static HRESULT (WINAPI *real_DrawIndexedPrimitive)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, UINT);
static HRESULT (WINAPI *real_DrawPrimitiveUP)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, CONST void *, UINT);
static HRESULT (WINAPI *real_DrawIndexedPrimitiveUP)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, CONST void *, D3DFORMAT, CONST void *, UINT);
static HRESULT (WINAPI *real_SetTextureStageState)(IDirect3DDevice8 *, DWORD, D3DTEXTURESTAGESTATETYPE, DWORD);
static HRESULT (WINAPI *real_LockRect)(IDirect3DTexture8 *, UINT, D3DLOCKED_RECT *, CONST RECT *, DWORD);
static HRESULT (WINAPI *real_UnlockRect)(IDirect3DTexture8 *, UINT);

static struct tex_entry *tex_lookup(IDirect3DTexture8 *t, int insert)
{
    UINT i = ((UINT_PTR)t >> 4) & (TABLE - 1);
    while (texs[i].tex && texs[i].tex != t)
        i = (i + 1) & (TABLE - 1);
    if (texs[i].tex) return &texs[i];
    if (!insert || ntexs >= TABLE * 3 / 4) return NULL;
    ntexs++;
    texs[i].tex = t;
    return &texs[i];
}

static struct rep_entry *rep_lookup(UINT64 hash, int *fresh)
{
    UINT i = (UINT)hash & (TABLE - 1);
    if (fresh) *fresh = 0; // NULL: look up only, don't insert
    while (reps[i].hash && reps[i].hash != hash)
        i = (i + 1) & (TABLE - 1);
    if (reps[i].hash) return &reps[i];
    if (!fresh || nreps >= TABLE * 3 / 4) return NULL;
    nreps++;
    *fresh = 1;
    reps[i].hash = hash;
    return &reps[i];
}

static UINT bytes_per_pixel(D3DFORMAT f)
{
    switch (f) {
    case D3DFMT_A8R8G8B8: case D3DFMT_X8R8G8B8: return 4;
    case D3DFMT_R5G6B5: case D3DFMT_X1R5G5B5: case D3DFMT_A1R5G5B5: case D3DFMT_A4R4G4B4: return 2;
    default: return 0;
    }
}

#define X5(v) (BYTE)((((v) & 31) << 3) | (((v) & 31) >> 2))
#define X6(v) (BYTE)((((v) & 63) << 2) | (((v) & 63) >> 4))

static void to_bgra(D3DFORMAT f, const BYTE *src, UINT n, BYTE *out)
{
    for (UINT i = 0; i < n; i++, out += 4) {
        UINT v = bytes_per_pixel(f) == 2 ? ((const WORD *)src)[i] : 0;
        switch (f) {
        case D3DFMT_A8R8G8B8: memcpy(out, src + i * 4, 4); break;
        case D3DFMT_X8R8G8B8: memcpy(out, src + i * 4, 3); out[3] = 255; break;
        case D3DFMT_R5G6B5: out[0] = X5(v); out[1] = X6(v >> 5); out[2] = X5(v >> 11); out[3] = 255; break;
        case D3DFMT_A4R4G4B4: out[0] = (v & 15) * 17; out[1] = (v >> 4 & 15) * 17; out[2] = (v >> 8 & 15) * 17; out[3] = (v >> 12) * 17; break;
        default: out[0] = X5(v); out[1] = X5(v >> 5); out[2] = X5(v >> 10); out[3] = f == D3DFMT_A1R5G5B5 && !(v >> 15) ? 0 : 255; break;
        }
    }
}

static void dump(UINT64 hash, const D3DSURFACE_DESC *d, const BYTE *bits, INT pitch)
{
    char path[MAX_PATH];
    snprintf(path, sizeof path, DUMP_DIR "\\%016llx.png", hash);
    if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) return;
    BYTE *px = malloc((size_t)d->Width * d->Height * 4);
    if (!px) return;
    for (UINT y = 0; y < d->Height; y++)
        to_bgra(d->Format, bits + y * pitch, d->Width, px + (size_t)y * d->Width * 4);
    if (png_write(path, d->Width, d->Height, px)) dumped++;
    else if (!dumped) log_line("could not write %s", path);
    free(px);
}

// 2x2 box filter; odd edges repeat the last row/column.
static BYTE *halve(const BYTE *px, UINT w, UINT h, UINT *nw, UINT *nh)
{
    *nw = w > 1 ? w / 2 : 1;
    *nh = h > 1 ? h / 2 : 1;
    BYTE *out = malloc((size_t)*nw * *nh * 4);
    if (!out) return NULL;
    for (UINT y = 0; y < *nh; y++) {
        UINT y0 = y * 2, y1 = y0 + 1 < h ? y0 + 1 : y0;
        for (UINT x = 0; x < *nw; x++) {
            UINT x0 = x * 2, x1 = x0 + 1 < w ? x0 + 1 : x0;
            for (int c = 0; c < 4; c++)
                out[((size_t)y * *nw + x) * 4 + c] = (px[((size_t)y0 * w + x0) * 4 + c] + px[((size_t)y0 * w + x1) * 4 + c] +
                                                      px[((size_t)y1 * w + x0) * 4 + c] + px[((size_t)y1 * w + x1) * 4 + c] + 2) / 4;
        }
    }
    return out;
}

static void load_names(void)
{
    FILE *f = fopen(NAMES_FILE, "r");
    char line[512];
    int n = 0;
    if (!f) {
        log_line("no %s: replacements by fingerprint only", NAMES_FILE);
        return;
    }
    while (fgets(line, sizeof line, f) && n < TABLE * 3 / 4) {
        char *path = strchr(line, '\t');
        if (!path) continue;
        *path++ = 0;
        path[strcspn(path, "\r\n")] = 0;
        for (char *c = path; *c; c++)
            if (*c == '/') *c = '\\';
        UINT64 hash = _strtoui64(line, NULL, 16);
        UINT i = (UINT)hash & (TABLE - 1);
        while (names[i].hash && names[i].hash != hash)
            i = (i + 1) & (TABLE - 1);
        if (names[i].hash) continue; // pixel-identical textures share the first name
        names[i].hash = hash;
        names[i].path = _strdup(path);
        n++;
    }
    fclose(f);
    log_line("%d texture names from %s", n, NAMES_FILE);
}

static const char *name_of(UINT64 hash)
{
    UINT i = (UINT)hash & (TABLE - 1);
    while (names[i].hash && names[i].hash != hash)
        i = (i + 1) & (TABLE - 1);
    return names[i].path;
}

static IDirect3DTexture8 *load_replacement(UINT64 hash)
{
    char path[MAX_PATH];
    UINT w, h;
    const char *name = name_of(hash);
    snprintf(path, sizeof path, REPLACE_DIR "\\%s", name ? name : "");
    if (!name || GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) {
        snprintf(path, sizeof path, REPLACE_DIR "\\%016llx.png", hash);
        if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return NULL;
    }
    BYTE *px = png_read(path, &w, &h);
    if (!px) {
        log_line("could not read %s", path);
        return NULL;
    }

    IDirect3DTexture8 *t = NULL;
    if (FAILED(real_CreateTexture(device, w, h, 0, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t))) {
        log_line("could not create %ux%u texture for %016llx", w, h, hash);
        free(px);
        return NULL;
    }
    log_line("replacing %016llx with %s (%ux%u)", hash, path, w, h);
    UINT levels = IDirect3DTexture8_GetLevelCount(t);
    for (UINT l = 0; l < levels && px; l++) {
        D3DLOCKED_RECT r;
        if (SUCCEEDED(real_LockRect(t, l, &r, NULL, 0))) {
            for (UINT y = 0; y < h; y++)
                memcpy((BYTE *)r.pBits + y * r.Pitch, px + (size_t)y * w * 4, w * 4);
            real_UnlockRect(t, l);
        }
        if (l + 1 < levels) {
            BYTE *next = halve(px, w, h, &w, &h);
            free(px);
            px = next;
        }
    }
    free(px);
    replaced++;
    return t;
}

static void fingerprint(IDirect3DTexture8 *t, struct tex_entry *e)
{
    D3DSURFACE_DESC d;
    UINT bpp;
    e->hash = 0;
    if (++e->updates > MAX_UPDATES) return;
    if (FAILED(IDirect3DTexture8_GetLevelDesc(t, 0, &d)) || !(bpp = bytes_per_pixel(d.Format))) return;

    UINT64 h = 0xcbf29ce484222325ULL;
    UINT shape[3] = { d.Width, d.Height, d.Format };
    for (UINT i = 0; i < sizeof shape; i++)
        h = (h ^ ((BYTE *)shape)[i]) * 0x100000001b3ULL;
    for (UINT y = 0; y < d.Height; y++) {
        const BYTE *row = e->bits + y * e->pitch;
        for (UINT x = 0; x < d.Width * bpp; x++)
            h = (h ^ row[x]) * 0x100000001b3ULL;
    }
    e->hash = h | 1;

    int fresh;
    struct rep_entry *r = rep_lookup(e->hash, &fresh);
    if (!r || !fresh) return;
    if (dumping) dump(e->hash, &d, e->bits, e->pitch);
    r->rep = load_replacement(e->hash);
}

static HRESULT WINAPI hook_LockRect(IDirect3DTexture8 *t, UINT level, D3DLOCKED_RECT *r, CONST RECT *rect, DWORD flags)
{
    HRESULT hr = real_LockRect(t, level, r, rect, flags);
    if (SUCCEEDED(hr) && level == 0 && !(flags & D3DLOCK_READONLY)) {
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(t, 1);
        if (e) {
            e->bits = rect ? NULL : r->pBits; // partial updates can't be fingerprinted
            e->pitch = r->Pitch;
            if (rect) e->hash = 0;
        }
        LeaveCriticalSection(&lock);
    }
    return hr;
}

static HRESULT WINAPI hook_UnlockRect(IDirect3DTexture8 *t, UINT level)
{
    if (level == 0) {
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(t, 0);
        if (e && e->bits) {
            fingerprint(t, e);
            e->bits = NULL;
        }
        LeaveCriticalSection(&lock);
    }
    return real_UnlockRect(t, level);
}

static HRESULT WINAPI hook_CreateTexture(IDirect3DDevice8 *dev, UINT w, UINT h, UINT levels, DWORD usage,
                                         D3DFORMAT fmt, D3DPOOL pool, IDirect3DTexture8 **tex)
{
    HRESULT hr = real_CreateTexture(dev, w, h, levels, usage, fmt, pool, tex);
    if (SUCCEEDED(hr)) {
        // A freed texture's address can be reused; forget what was there.
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(*tex, 0);
        if (e) {
            e->hash = 0;
            e->bits = NULL;
            e->updates = 0;
        }
        LeaveCriticalSection(&lock);
    }
    return hr;
}

// Textures reach the device through SetTexture and through replayed state blocks, so swap at draw time.
static void bind_replacements(IDirect3DDevice8 *dev)
{
    for (DWORD stage = 0; stage < 4; stage++) {
        IDirect3DBaseTexture8 *bt = NULL;
        if (FAILED(IDirect3DDevice8_GetTexture(dev, stage, &bt)) || !bt) continue;
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup((IDirect3DTexture8 *)bt, 0);
        struct rep_entry *r = e && e->hash ? rep_lookup(e->hash, NULL) : NULL;
        IDirect3DTexture8 *rep = r ? r->rep : NULL;
        LeaveCriticalSection(&lock);
        IDirect3DBaseTexture8_Release(bt);
        if (rep) {
            real_SetTexture(dev, stage, (IDirect3DBaseTexture8 *)rep);
            swaps++;
        }
    }
    if (++draws % 200000 == 0) log_line("draws: %ld, texture swaps: %ld", draws, swaps);
}

static HRESULT WINAPI hook_DrawPrimitive(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT start, UINT count)
{
    bind_replacements(dev);
    return real_DrawPrimitive(dev, t, start, count);
}

static HRESULT WINAPI hook_DrawIndexedPrimitive(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT min, UINT n, UINT start, UINT count)
{
    bind_replacements(dev);
    return real_DrawIndexedPrimitive(dev, t, min, n, start, count);
}

static HRESULT WINAPI hook_DrawPrimitiveUP(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT count, CONST void *data, UINT stride)
{
    bind_replacements(dev);
    return real_DrawPrimitiveUP(dev, t, count, data, stride);
}

static HRESULT WINAPI hook_DrawIndexedPrimitiveUP(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT min, UINT n, UINT count,
                                                  CONST void *idx, D3DFORMAT fmt, CONST void *data, UINT stride)
{
    bind_replacements(dev);
    return real_DrawIndexedPrimitiveUP(dev, t, min, n, count, idx, fmt, data, stride);
}

// The game never asks for mip filtering because its textures have no mips; ours do.
static HRESULT WINAPI hook_SetTextureStageState(IDirect3DDevice8 *dev, DWORD stage, D3DTEXTURESTAGESTATETYPE type, DWORD value)
{
    if (type == D3DTSS_MIPFILTER && value == D3DTEXF_NONE) value = D3DTEXF_LINEAR;
    return real_SetTextureStageState(dev, stage, type, value);
}

void textures_install(IDirect3DDevice8 *dev)
{
    if (real_CreateTexture) return;
    InitializeCriticalSection(&lock);
    device = dev;
    DWORD attr = GetFileAttributesA(DUMP_DIR);
    dumping = attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
    log_line("texture dump %s", dumping ? "on (" DUMP_DIR ")" : "off (create " DUMP_DIR " to enable)");
    load_names();

    IDirect3DDevice8Vtbl *vt = dev->lpVtbl;
    patch((void **)&vt->CreateTexture, hook_CreateTexture, (void **)&real_CreateTexture);
    real_SetTexture = vt->SetTexture;
    patch((void **)&vt->DrawPrimitive, hook_DrawPrimitive, (void **)&real_DrawPrimitive);
    patch((void **)&vt->DrawIndexedPrimitive, hook_DrawIndexedPrimitive, (void **)&real_DrawIndexedPrimitive);
    patch((void **)&vt->DrawPrimitiveUP, hook_DrawPrimitiveUP, (void **)&real_DrawPrimitiveUP);
    patch((void **)&vt->DrawIndexedPrimitiveUP, hook_DrawIndexedPrimitiveUP, (void **)&real_DrawIndexedPrimitiveUP);
    patch((void **)&vt->SetTextureStageState, hook_SetTextureStageState, (void **)&real_SetTextureStageState);

    // All textures share one vtable; a throwaway texture gives us access to it.
    IDirect3DTexture8 *probe;
    if (SUCCEEDED(real_CreateTexture(dev, 1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &probe))) {
        patch((void **)&probe->lpVtbl->LockRect, hook_LockRect, (void **)&real_LockRect);
        patch((void **)&probe->lpVtbl->UnlockRect, hook_UnlockRect, (void **)&real_UnlockRect);
        IDirect3DTexture8_Release(probe);
    }
    for (DWORD s = 0; s < 8; s++)
        real_SetTextureStageState(dev, s, D3DTSS_MIPFILTER, D3DTEXF_LINEAR);
}

void textures_report(void)
{
    log_line("textures: %d tracked, %d unique, %d dumped, %d replaced", ntexs, nreps, dumped, replaced);
}
