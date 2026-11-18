// Texture dump and replacement.
// The game fills each texture with LockRect/UnlockRect on level 0. At unlock we fingerprint the
// pixels and, if taz-hd\textures has a replacement (by original pak name via taz-hd\fingerprints.tsv,
// or by <fingerprint>.png), a worker thread decodes it and builds mipmaps. Present uploads finished
// ones; SetTexture and replayed state blocks then bind the replacement instead of the original.
// A replacement is freed when the last game texture it stands in for is released (each level loads
// new ones; keeping them all ran the 32-bit game out of memory after a few levels) and loaded again
// if that texture comes back.
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "image.h"
#include "game.h"

#define DUMP_DIR "taz-hd\\dump"
#define REPLACE_DIR "taz-hd\\textures"
#define NAMES_FILE "taz-hd\\fingerprints.tsv"
#define TABLE 32768
#define MAX_UPDATES 8      // textures rewritten more often are animated or generated
#define UPLOADS_PER_FRAME 16
#define MAX_LEVELS 16

struct tex_entry { IDirect3DTexture8 *tex; UINT64 hash; BYTE *bits; INT pitch; int updates, counted; };
struct rep_entry { UINT64 hash; IDirect3DTexture8 *rep; int users, asked; }; // users: live game textures with this fingerprint
// A name can point at part of a bigger image (splash screens are split into tiles).
struct name_entry { UINT64 hash; char *path; UINT x, y, w, h, full_w, full_h; };

// Work for the decode thread, and its results waiting for upload on the render thread.
struct job {
    struct job *next;
    UINT64 hash;
    char path[MAX_PATH];
    const struct name_entry *crop;
    BYTE *dump; // non-NULL: write these BGRA pixels to path instead of loading
    UINT levels, w[MAX_LEVELS], h[MAX_LEVELS];
    BYTE *px[MAX_LEVELS];
};

static struct tex_entry texs[TABLE];
static struct rep_entry reps[TABLE];
static struct name_entry names[TABLE];
static int ntexs, nreps;
static CRITICAL_SECTION lock;
static IDirect3DDevice8 *device;
static int dumping, dumped, replaced, freed, rebind;
static struct job *todo, *done;
static HANDLE work;
static double decode_ms;
static DWORD frame_no; // Presents so far

static HRESULT (WINAPI *real_CreateTexture)(IDirect3DDevice8 *, UINT, UINT, UINT, DWORD, D3DFORMAT, D3DPOOL, IDirect3DTexture8 **);
static HRESULT (WINAPI *real_SetTexture)(IDirect3DDevice8 *, DWORD, IDirect3DBaseTexture8 *);
static HRESULT (WINAPI *real_ApplyStateBlock)(IDirect3DDevice8 *, DWORD);
static HRESULT (WINAPI *real_DrawPrimitive)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT);
static HRESULT (WINAPI *real_DrawIndexedPrimitive)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, UINT);
static HRESULT (WINAPI *real_DrawPrimitiveUP)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, CONST void *, UINT);
static HRESULT (WINAPI *real_DrawIndexedPrimitiveUP)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT, UINT, CONST void *, D3DFORMAT, CONST void *, UINT);
static HRESULT (WINAPI *real_SetTextureStageState)(IDirect3DDevice8 *, DWORD, D3DTEXTURESTAGESTATETYPE, DWORD);
static HRESULT (WINAPI *real_LockRect)(IDirect3DTexture8 *, UINT, D3DLOCKED_RECT *, CONST RECT *, DWORD);
static HRESULT (WINAPI *real_UnlockRect)(IDirect3DTexture8 *, UINT);
static ULONG (WINAPI *real_Release)(IDirect3DTexture8 *);

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

// Linear probing: later entries move back into the hole so lookups still find them.
static void tex_remove(struct tex_entry *e)
{
    UINT i = e - texs;
    memset(&texs[i], 0, sizeof texs[i]);
    ntexs--;
    for (UINT j = (i + 1) & (TABLE - 1); texs[j].tex; j = (j + 1) & (TABLE - 1)) {
        UINT home = ((UINT_PTR)texs[j].tex >> 4) & (TABLE - 1);
        if (i < j ? home <= i || home > j : home <= i && home > j) {
            texs[i] = texs[j];
            memset(&texs[j], 0, sizeof texs[j]);
            i = j;
        }
    }
}

static struct rep_entry *rep_lookup(UINT64 hash, int *fresh);

// A game texture with this fingerprint went away (or changed); free the replacement if it was the last.
static void unuse(struct tex_entry *e)
{
    struct rep_entry *r = e->counted ? rep_lookup(e->hash, NULL) : NULL;
    e->counted = 0;
    if (!r || --r->users > 0) return;
    r->users = 0;
    if (r->rep) {
        IDirect3DTexture8_Release(r->rep);
        r->rep = NULL;
        if (++freed % 250 == 0) log_line("%d replacements freed with the textures they stood in for", freed);
    }
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

static const struct name_entry *name_of(UINT64 hash)
{
    UINT i = (UINT)hash & (TABLE - 1);
    while (names[i].hash && names[i].hash != hash)
        i = (i + 1) & (TABLE - 1);
    return names[i].hash ? &names[i] : NULL;
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

void to_bgra(D3DFORMAT f, const BYTE *src, UINT n, BYTE *out)
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

static BYTE *crop(BYTE *px, UINT *w, UINT *h, const struct name_entry *n)
{
    double sx = (double)*w / n->full_w, sy = (double)*h / n->full_h;
    UINT x0 = (UINT)(n->x * sx + 0.5), y0 = (UINT)(n->y * sy + 0.5);
    UINT cw = (UINT)(n->w * sx + 0.5), ch = (UINT)(n->h * sy + 0.5);
    if (x0 + cw > *w || y0 + ch > *h || !cw || !ch) return px;
    BYTE *out = malloc((size_t)cw * ch * 4);
    if (!out) return px;
    for (UINT y = 0; y < ch; y++)
        memcpy(out + (size_t)y * cw * 4, px + ((size_t)(y0 + y) * *w + x0) * 4, (size_t)cw * 4);
    free(px);
    *w = cw;
    *h = ch;
    return out;
}

// Decode thread: the only thread that touches WIC, so COM setup stays out of the game's threads.
static DWORD WINAPI worker(void *arg)
{
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    for (;;) {
        WaitForSingleObject(work, INFINITE);
        for (;;) {
            EnterCriticalSection(&lock);
            struct job *j = todo;
            if (j) todo = j->next;
            LeaveCriticalSection(&lock);
            if (!j) break;

            if (j->dump) {
                if (png_write(j->path, j->w[0], j->h[0], j->dump)) dumped++;
                else if (!dumped) log_line("could not write %s", j->path);
                free(j->dump);
                free(j);
                continue;
            }
            LARGE_INTEGER t0, t1, freq;
            QueryPerformanceCounter(&t0);
            UINT w, h;
            BYTE *px = image_read(j->path, &w, &h);
            if (!px) log_line("could not read %s", j->path);
            if (px && j->crop) px = crop(px, &w, &h, j->crop);
            for (j->levels = 0; px && j->levels < MAX_LEVELS; j->levels++) {
                j->w[j->levels] = w;
                j->h[j->levels] = h;
                j->px[j->levels] = px;
                if (w == 1 && h == 1) {
                    j->levels++;
                    break;
                }
                px = halve(px, w, h, &w, &h);
            }
            QueryPerformanceCounter(&t1);
            QueryPerformanceFrequency(&freq);
            decode_ms += (t1.QuadPart - t0.QuadPart) * 1000.0 / freq.QuadPart;

            EnterCriticalSection(&lock);
            j->next = done;
            done = j;
            LeaveCriticalSection(&lock);
        }
    }
    return 0;
}

// The lock and the decode thread start on first use (screenshots can come before textures_install).
static BOOL CALLBACK init_worker(INIT_ONCE *once, void *param, void **ctx)
{
    InitializeCriticalSection(&lock);
    work = CreateEventA(NULL, FALSE, FALSE, NULL);
    CloseHandle(CreateThread(NULL, 0, worker, NULL, 0, NULL));
    return TRUE;
}

static void start_worker(void)
{
    static INIT_ONCE once = INIT_ONCE_STATIC_INIT;
    InitOnceExecuteOnce(&once, init_worker, NULL, NULL);
}

static void queue(struct job *j)
{
    start_worker();
    EnterCriticalSection(&lock);
    j->next = todo;
    todo = j;
    LeaveCriticalSection(&lock);
    SetEvent(work);
}

// Writes bgra to path on the decode thread and frees it.
void queue_png(const char *path, UINT w, UINT h, BYTE *bgra)
{
    struct job *j = calloc(1, sizeof *j);
    if (!j) {
        free(bgra);
        return;
    }
    snprintf(j->path, sizeof j->path, "%s", path);
    j->dump = bgra;
    j->w[0] = w;
    j->h[0] = h;
    queue(j);
}

static void queue_dump(UINT64 hash, const D3DSURFACE_DESC *d, const BYTE *bits, INT pitch)
{
    struct job *j = calloc(1, sizeof *j);
    if (!j) return;
    snprintf(j->path, sizeof j->path, DUMP_DIR "\\%016llx.png", hash);
    if (GetFileAttributesA(j->path) != INVALID_FILE_ATTRIBUTES || !(j->dump = malloc((size_t)d->Width * d->Height * 4))) {
        free(j);
        return;
    }
    for (UINT y = 0; y < d->Height; y++)
        to_bgra(d->Format, bits + y * pitch, d->Width, j->dump + (size_t)y * d->Width * 4);
    j->w[0] = d->Width;
    j->h[0] = d->Height;
    queue(j);
}

static void queue_load(UINT64 hash, const struct name_entry *n)
{
    char path[MAX_PATH];
    snprintf(path, sizeof path, REPLACE_DIR "\\%s", n ? n->path : "");
    if (!n || GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) {
        n = NULL;
        snprintf(path, sizeof path, REPLACE_DIR "\\%016llx.png", hash);
        if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return;
    }
    struct job *j = calloc(1, sizeof *j);
    if (!j) return;
    j->hash = hash;
    strcpy(j->path, path);
    j->crop = n && n->full_w ? n : NULL;
    queue(j);
}

// Called once per frame on the render thread: uploads a few finished replacements.
void textures_frame(void)
{
    frame_no++;
    if (!real_CreateTexture) return;
    for (int n = 0; n < UPLOADS_PER_FRAME; n++) {
        EnterCriticalSection(&lock);
        struct job *j = done;
        if (j) done = j->next;
        LeaveCriticalSection(&lock);
        if (!j) break;

        IDirect3DTexture8 *t = NULL;
        if (j->levels && SUCCEEDED(real_CreateTexture(device, j->w[0], j->h[0], j->levels, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t))) {
            for (UINT l = 0; l < j->levels; l++) {
                D3DLOCKED_RECT r;
                if (SUCCEEDED(real_LockRect(t, l, &r, NULL, 0))) {
                    for (UINT y = 0; y < j->h[l]; y++)
                        memcpy((BYTE *)r.pBits + y * r.Pitch, j->px[l] + (size_t)y * j->w[l] * 4, (size_t)j->w[l] * 4);
                    real_UnlockRect(t, l);
                }
            }
            EnterCriticalSection(&lock);
            struct rep_entry *r = rep_lookup(j->hash, NULL);
            if (r) r->asked = 0;
            if (r && r->users > 0 && !r->rep) r->rep = t, t = NULL;
            rebind = 1; // the original may be bound right now
            LeaveCriticalSection(&lock);
            if (t) IDirect3DTexture8_Release(t); // its texture went away while it loaded
            if (++replaced % 250 == 0) log_line("%d textures replaced, %.0f ms decoding them (off the render thread)", replaced, decode_ms);
        } else if (j->levels) {
            log_line("could not create %ux%u texture for %s", j->w[0], j->h[0], j->path);
        }
        for (UINT l = 0; l < j->levels; l++)
            free(j->px[l]);
        free(j);
    }
}

static DWORD WINAPI load_missing(void *arg)
{
    static UINT64 hashes[TABLE];
    int n = 0;
    EnterCriticalSection(&lock);
    for (int i = 0; i < TABLE; i++)
        if (reps[i].hash && !reps[i].rep && reps[i].users && !reps[i].asked) reps[i].asked = 1, hashes[n++] = reps[i].hash;
    LeaveCriticalSection(&lock);
    for (int i = 0; i < n; i++) queue_load(hashes[i], name_of(hashes[i]));
    log_line("hd textures on: %d to load", n);
    return 0;
}

// HD textures were switched in game. Loaded replacements are kept while off, so switching back is quick;
// textures first seen while off are loaded now.
void textures_apply(void)
{
    static HANDLE loading;
    EnterCriticalSection(&lock);
    rebind = 1;
    LeaveCriticalSection(&lock);
    if (!settings.hd_textures || !real_CreateTexture) return;
    if (loading && WaitForSingleObject(loading, 0) == WAIT_TIMEOUT) return;
    if (loading) CloseHandle(loading);
    loading = CreateThread(NULL, 0, load_missing, NULL, 0, NULL);
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
        char *path = strchr(line, '\t'), *rect;
        if (!path) continue;
        *path++ = 0;
        path[strcspn(path, "\r\n")] = 0;
        if ((rect = strchr(path, '\t'))) *rect++ = 0;
        for (char *c = path; *c; c++)
            if (*c == '/') *c = '\\';
        UINT64 hash = _strtoui64(line, NULL, 16);
        UINT i = (UINT)hash & (TABLE - 1);
        while (names[i].hash && names[i].hash != hash)
            i = (i + 1) & (TABLE - 1);
        if (names[i].hash) continue; // pixel-identical textures share the first name
        names[i].hash = hash;
        names[i].path = _strdup(path);
        if (rect && sscanf(rect, "%u %u %u %u %u %u", &names[i].x, &names[i].y, &names[i].w, &names[i].h,
                           &names[i].full_w, &names[i].full_h) != 6)
            names[i].full_w = 0;
        n++;
    }
    fclose(f);
    log_line("%d texture names from %s", n, NAMES_FILE);
}

static void fingerprint(IDirect3DTexture8 *t, struct tex_entry *e)
{
    D3DSURFACE_DESC d;
    UINT bpp;
    struct tex_entry old = *e;
    e->hash = 0;
    e->counted = 0;
    if (FAILED(IDirect3DTexture8_GetLevelDesc(t, 0, &d)) || !(bpp = bytes_per_pixel(d.Format))) {
        unuse(&old);
        return;
    }

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

    // Animated textures cycle through known frames; generated ones produce endless new content.
    const struct name_entry *n = name_of(e->hash);
    int busy = ++e->updates > MAX_UPDATES, fresh;
    struct rep_entry *r = busy && !n ? NULL : rep_lookup(e->hash, &fresh);
    if (r) r->users++, e->counted = 1;
    unuse(&old); // after counting this one, so an unchanged texture keeps its replacement
    if (!r) return;
    if (dumping && fresh && !busy) queue_dump(e->hash, &d, e->bits, e->pitch);
    if (settings.hd_textures && !r->rep && !r->asked) r->asked = 1, queue_load(e->hash, n);
}

static IDirect3DBaseTexture8 *replacement_for(IDirect3DBaseTexture8 *bt)
{
    if (!settings.hd_textures) return NULL;
    EnterCriticalSection(&lock);
    struct tex_entry *e = tex_lookup((IDirect3DTexture8 *)bt, 0);
    struct rep_entry *r = e && e->hash ? rep_lookup(e->hash, NULL) : NULL;
    IDirect3DBaseTexture8 *rep = r ? (IDirect3DBaseTexture8 *)r->rep : NULL;
    LeaveCriticalSection(&lock);
    return rep;
}

static HRESULT WINAPI hook_LockRect(IDirect3DTexture8 *t, UINT level, D3DLOCKED_RECT *r, CONST RECT *rect, DWORD flags)
{
    HRESULT hr = real_LockRect(t, level, r, rect, flags);
    if (SUCCEEDED(hr) && level == 0 && !(flags & D3DLOCK_READONLY)) {
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(t, 0); // the game's textures only (hook_CreateTexture)
        if (e) {
            e->bits = rect ? NULL : r->pBits; // partial updates can't be fingerprinted
            e->pitch = r->Pitch;
            if (rect) unuse(e), e->hash = 0;
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

DWORD textures_created;

static ULONG WINAPI hook_Release(IDirect3DTexture8 *t)
{
    ULONG n = real_Release(t);
    if (!n) {
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(t, 0);
        if (e) unuse(e), tex_remove(e);
        LeaveCriticalSection(&lock);
    }
    return n;
}

static HRESULT WINAPI hook_CreateTexture(IDirect3DDevice8 *dev, UINT w, UINT h, UINT levels, DWORD usage,
                                         D3DFORMAT fmt, D3DPOOL pool, IDirect3DTexture8 **tex)
{
    HRESULT hr = real_CreateTexture(dev, w, h, levels, usage, fmt, pool, tex);
    if (SUCCEEDED(hr)) {
        // Only the game's textures are tracked and fingerprinted. Ours (video frames, the overlay's font,
        // the Taz style's lookups) are created from this DLL; hashing each upscaled video frame cost 38 ms.
        static BYTE *exe, *exe_end;
        if (!exe) {
            exe = (BYTE *)GetModuleHandleA(NULL);
            exe_end = exe + ((IMAGE_NT_HEADERS *)(exe + ((IMAGE_DOS_HEADER *)exe)->e_lfanew))->OptionalHeader.SizeOfImage;
        }
        BYTE *caller = __builtin_return_address(0);
        int game = caller >= exe && caller < exe_end;
        textures_created += game;
        EnterCriticalSection(&lock);
        struct tex_entry *e = tex_lookup(*tex, 0);
        if (e) unuse(e), tex_remove(e); // a freed texture's address can be reused; forget what was there
        if (game) tex_lookup(*tex, 1);
        LeaveCriticalSection(&lock);
    }
    return hr;
}

// Scrolling textures (waterfalls, escalators): each frame the game copies a window of a big texture
// into a small one, FUN_00574960(big handle, small handle, offset u, offset v), called from its
// scroll update at 0x4db7d1. A window of an HD texture can't be copied into the small original, so
// the HD big texture is bound instead and a texture transform picks the window, which starts at
// offset * small size. We hook that call to learn the Direct3D textures (**(handle + 0x24)) while
// the game is using them: its scroll table can hold freed handles, so it is never read directly.
#define STAGES 4
#define SCROLLS 6
static struct { IDirect3DTexture8 *big, *small; float u, v; DWORD frame; } scrolls[SCROLLS];
static int scroll_stage[STAGES] = { -1, -1, -1, -1 };
static HRESULT (WINAPI *real_SetTransform)(IDirect3DDevice8 *, D3DTRANSFORMSTATETYPE, CONST D3DMATRIX *);
static HRESULT (WINAPI *real_GetTransform)(IDirect3DDevice8 *, D3DTRANSFORMSTATETYPE, D3DMATRIX *);

#define POINTER(p) ((UINT_PTR)(p) >= 0x10000 && (UINT_PTR)(p) < 0x7fff0000 && !((UINT_PTR)(p) & 3))

static IDirect3DTexture8 *d3d_of(DWORD handle)
{
    DWORD *p = POINTER(handle) ? *(DWORD **)(handle + 0x24) : NULL;
    p = POINTER(p) ? (DWORD *)*p : NULL;
    return POINTER(p) ? (IDirect3DTexture8 *)p : NULL;
}

static void __cdecl scroll_copy(DWORD big, DWORD small, float u, float v)
{
    IDirect3DTexture8 *b = d3d_of(big), *sm = d3d_of(small);
    int free_slot = -1;
    for (int i = 0; b && sm && i < SCROLLS; i++) {
        if (scrolls[i].small == sm || (free_slot < 0 && frame_no - scrolls[i].frame > 1)) free_slot = i;
        if (scrolls[i].small == sm) break;
    }
    if (free_slot >= 0) {
        scrolls[free_slot].big = b;
        scrolls[free_slot].small = sm;
        scrolls[free_slot].u = u;
        scrolls[free_slot].v = v;
        scrolls[free_slot].frame = frame_no;
    }
    ((void(__cdecl *)(DWORD, DWORD, float, float))0x574960)(big, small, u, v);
}

// Index of the live scroll record whose small texture is bt, or -1. Compares pointer values only.
static int scroller_of(IDirect3DBaseTexture8 *bt)
{
    for (int i = 0; i < SCROLLS; i++)
        if (frame_no - scrolls[i].frame <= 1 && (IDirect3DBaseTexture8 *)scrolls[i].small == bt) return i;
    return -1;
}

// What the game has bound on each stage, and what each recorded state block binds. These are the
// game's own pointers used only as lookup keys: a state block can hold a texture the game has
// already released, so they are never dereferenced (asking Direct3D with GetTexture crashed).
#define BLOCKS 256
static IDirect3DBaseTexture8 *bound[STAGES];
static struct { DWORD token; BYTE set; IDirect3DBaseTexture8 *tex[STAGES]; } blocks[BLOCKS], recorded;
static int recording;
static HRESULT (WINAPI *real_BeginStateBlock)(IDirect3DDevice8 *);
static HRESULT (WINAPI *real_EndStateBlock)(IDirect3DDevice8 *, DWORD *);
static HRESULT (WINAPI *real_DeleteStateBlock)(IDirect3DDevice8 *, DWORD);

// Binds the replacement for the game's texture bt (for a scrolling texture, the HD big texture).
// Returns 0 when there is none, leaving the binding to the caller.
static int bind_replacement(IDirect3DDevice8 *dev, DWORD stage, IDirect3DBaseTexture8 *bt)
{
    IDirect3DBaseTexture8 *rep = NULL;
    int k = bt ? scroller_of(bt) : -1;
    if (k >= 0 && !(rep = replacement_for((IDirect3DBaseTexture8 *)scrolls[k].big))) k = -1;
    if (k < 0 && bt) rep = replacement_for(bt);
    if (stage < STAGES) scroll_stage[stage] = k;
    if (rep) real_SetTexture(dev, stage, rep);
    return rep != NULL;
}

// Binds one of the mod's own textures (or none), which have no replacements and aren't the game's
// binding: what the game bound stays on record.
void textures_bind_own(IDirect3DDevice8 *dev, DWORD stage, IDirect3DBaseTexture8 *t)
{
    if (real_SetTexture) real_SetTexture(dev, stage, t);
    else IDirect3DDevice8_SetTexture(dev, stage, t);
}

IDirect3DBaseTexture8 *textures_bound(DWORD stage)
{
    return stage < STAGES ? bound[stage] : NULL;
}

// Fingerprint of the game's texture bound at stage (0 if none or unknown).
UINT64 textures_bound_hash(DWORD stage)
{
    EnterCriticalSection(&lock);
    struct tex_entry *e = stage < STAGES && bound[stage] ? tex_lookup((IDirect3DTexture8 *)bound[stage], 0) : NULL;
    UINT64 h = e ? e->hash : 0;
    LeaveCriticalSection(&lock);
    return h;
}

// The last texture binds, for crash reports.
static struct { DWORD stage; void *tex, *caller; } recent[16];
static DWORD nrecent; // unsigned: it wraps after a day or so of play

void textures_dump_recent(void)
{
    for (DWORD i = nrecent - (nrecent > 16 ? 16 : nrecent); i != nrecent; i++)
        log_line("crash: recent SetTexture(%lu, %p) from %p", recent[i % 16].stage, recent[i % 16].tex, recent[i % 16].caller);
}

static HRESULT WINAPI hook_SetTexture(IDirect3DDevice8 *dev, DWORD stage, IDirect3DBaseTexture8 *bt)
{
    DWORD n = nrecent++ % 16;
    recent[n].stage = stage;
    recent[n].tex = bt;
    recent[n].caller = __builtin_return_address(0);
    if (stage < STAGES) {
        bound[stage] = bt;
        if (recording) {
            recorded.tex[stage] = bt;
            recorded.set |= 1 << stage;
        }
    }
    return bind_replacement(dev, stage, bt) ? D3D_OK : real_SetTexture(dev, stage, bt);
}

static HRESULT WINAPI hook_BeginStateBlock(IDirect3DDevice8 *dev)
{
    recording = 1;
    recorded.set = 0;
    return real_BeginStateBlock(dev);
}

static HRESULT WINAPI hook_EndStateBlock(IDirect3DDevice8 *dev, DWORD *token)
{
    HRESULT hr = real_EndStateBlock(dev, token);
    recording = 0;
    if (FAILED(hr) || !recorded.set) return hr;
    for (int i = 0; i < BLOCKS; i++)
        if (!blocks[i].token) {
            blocks[i] = recorded;
            blocks[i].token = *token;
            break;
        }
    return hr;
}

static HRESULT WINAPI hook_DeleteStateBlock(IDirect3DDevice8 *dev, DWORD token)
{
    for (int i = 0; i < BLOCKS; i++)
        if (blocks[i].token == token) blocks[i].token = 0;
    return real_DeleteStateBlock(dev, token);
}

// State blocks bind textures without SetTexture; swap in replacements for the ones they set.
static HRESULT WINAPI hook_ApplyStateBlock(IDirect3DDevice8 *dev, DWORD token)
{
    HRESULT hr = real_ApplyStateBlock(dev, token);
    for (int i = 0; SUCCEEDED(hr) && i < BLOCKS; i++) {
        if (blocks[i].token != token) continue;
        for (DWORD stage = 0; stage < STAGES; stage++)
            if (blocks[i].set & (1 << stage)) {
                bound[stage] = blocks[i].tex[stage];
                bind_replacement(dev, stage, bound[stage]);
            }
        break;
    }
    return hr;
}

struct saved { DWORD flags; D3DMATRIX m; };

// Returns a mask of stages whose texture transform was changed for a scrolling texture.
static int before_draw(IDirect3DDevice8 *dev, struct saved *saved)
{
    if (rebind) { // a replacement finished loading or HD textures were switched; rebind what the game bound
        rebind = 0;
        for (DWORD stage = 0; stage < STAGES; stage++)
            if (!bind_replacement(dev, stage, bound[stage]) && stage < 2) // the game unbinds 0 and 1 before freeing
                real_SetTexture(dev, stage, bound[stage]);
    }
    int mask = 0;
    for (DWORD stage = 0; stage < STAGES; stage++) {
        int k = scroll_stage[stage];
        if (k < 0) continue;
        D3DSURFACE_DESC big, small;
        IDirect3DTexture8 *b = scrolls[k].big, *s = scrolls[k].small;
        if (!b || !s || FAILED(IDirect3DTexture8_GetLevelDesc(b, 0, &big)) || FAILED(IDirect3DTexture8_GetLevelDesc(s, 0, &small)))
            continue;
        float ku = (float)small.Width / big.Width, kv = (float)small.Height / big.Height;
        D3DMATRIX m = { 0 };
        m._11 = ku;
        m._22 = kv;
        m._31 = scrolls[k].u * ku;
        m._32 = scrolls[k].v * kv;
        m._33 = m._44 = 1.0f;
        IDirect3DDevice8_GetTextureStageState(dev, stage, D3DTSS_TEXTURETRANSFORMFLAGS, &saved[stage].flags);
        real_GetTransform(dev, D3DTS_TEXTURE0 + stage, &saved[stage].m);
        real_SetTextureStageState(dev, stage, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_COUNT2);
        real_SetTransform(dev, D3DTS_TEXTURE0 + stage, &m);
        mask |= 1 << stage;
    }
    return mask;
}

static void after_draw(IDirect3DDevice8 *dev, int mask, struct saved *saved)
{
    for (DWORD stage = 0; mask; stage++, mask >>= 1) {
        if (!(mask & 1)) continue;
        real_SetTextureStageState(dev, stage, D3DTSS_TEXTURETRANSFORMFLAGS, saved[stage].flags);
        real_SetTransform(dev, D3DTS_TEXTURE0 + stage, &saved[stage].m);
    }
}

#define DRAW(call)                                  \
    struct saved saved[STAGES];                     \
    int mask = before_draw(dev, saved);             \
    HRESULT hr = call;                              \
    if (mask) after_draw(dev, mask, saved);         \
    return hr

static HRESULT WINAPI hook_DrawPrimitive(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT start, UINT count)
{
    DRAW((t == D3DPT_TRIANGLESTRIP || t == D3DPT_TRIANGLELIST) ? mesh_draw(dev, t, start, count, real_DrawPrimitive) : real_DrawPrimitive(dev, t, start, count));
}

static HRESULT WINAPI hook_DrawIndexedPrimitive(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT min, UINT n, UINT start, UINT count)
{
    DRAW(real_DrawIndexedPrimitive(dev, t, min, n, start, count));
}

static HRESULT WINAPI hook_DrawPrimitiveUP(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT count, CONST void *data, UINT stride)
{
    DRAW(real_DrawPrimitiveUP(dev, t, count, data, stride));
}

static HRESULT WINAPI hook_DrawIndexedPrimitiveUP(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE t, UINT min, UINT n, UINT count,
                                                  CONST void *idx, D3DFORMAT fmt, CONST void *data, UINT stride)
{
    DRAW(real_DrawIndexedPrimitiveUP(dev, t, min, n, count, idx, fmt, data, stride));
}

// The game never asks for mip filtering because its textures have no mips; ours do.
static HRESULT WINAPI hook_SetTextureStageState(IDirect3DDevice8 *dev, DWORD stage, D3DTEXTURESTAGESTATETYPE type, DWORD value)
{
    if (type == D3DTSS_MIPFILTER && value == D3DTEXF_NONE) value = D3DTEXF_LINEAR;
    return real_SetTextureStageState(dev, stage, type, value);
}

// After a device Reset: the game recreated all its textures, so every texture we tracked is gone.
void textures_reset(IDirect3DDevice8 *dev)
{
    EnterCriticalSection(&lock);
    memset(texs, 0, sizeof texs);
    ntexs = 0;
    for (int i = 0; i < TABLE; i++) reps[i].users = 0; // counted again as the game refills them
    LeaveCriticalSection(&lock);
    memset(scrolls, 0, sizeof scrolls);
    memset(bound, 0, sizeof bound);
    for (DWORD s = 0; s < STAGES; s++) {
        scroll_stage[s] = -1;
        real_SetTextureStageState(dev, s, D3DTSS_MIPFILTER, D3DTEXF_LINEAR); // Reset cleared it; the game thinks it's set
    }
}

// Paper books (boss rules, tutorials) draw each page every frame into one shared 512x256 render target
// (0x69c33c; whichever of six effects needs it first makes it with bdCreateRenderTarget 0x56c500) and
// stretch it over a page about 1100x1300 pixels on an 1800-pixel-high screen. 1024x1024 keeps HD detail.
static void *__cdecl page_target(int w, int h, int rgb, int z, int flags)
{
    return ((void *(__cdecl *)(int, int, int, int, int))CREATE_TARGET)(w * 2, h * 4, rgb, z, flags);
}

void textures_install(IDirect3DDevice8 *dev)
{
    if (real_CreateTexture) return;
    static const DWORD page_targets[] = { 0x4562c5, 0x456607, 0x4566b0, 0x4567e5, 0x456bde, 0x4581bb };
    int n = 0;
    for (int i = 0; i < 6; i++) n += redirect_call((BYTE *)page_targets[i], CREATE_TARGET, page_target);
    if (n < 6) log_line("paper book pages: %d of 6 render target sites patched (unknown exe)", n);
    start_worker();
    device = dev;
    DWORD attr = GetFileAttributesA(DUMP_DIR);
    dumping = attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
    log_line("texture dump %s", dumping ? "on (" DUMP_DIR ")" : "off (create " DUMP_DIR " to enable)");
    load_names();

    IDirect3DDevice8Vtbl *vt = dev->lpVtbl;
    patch((void **)&vt->CreateTexture, hook_CreateTexture, (void **)&real_CreateTexture);
    patch((void **)&vt->SetTexture, hook_SetTexture, (void **)&real_SetTexture);
    real_SetTransform = vt->SetTransform;
    real_GetTransform = vt->GetTransform;
    log_line(redirect_call((BYTE *)0x4db7d1, (void *)0x574960, scroll_copy) ? "scrolling textures handled"
                                                                              : "scrolling textures left alone (unknown exe)");
    patch((void **)&vt->ApplyStateBlock, hook_ApplyStateBlock, (void **)&real_ApplyStateBlock);
    patch((void **)&vt->BeginStateBlock, hook_BeginStateBlock, (void **)&real_BeginStateBlock);
    patch((void **)&vt->EndStateBlock, hook_EndStateBlock, (void **)&real_EndStateBlock);
    patch((void **)&vt->DeleteStateBlock, hook_DeleteStateBlock, (void **)&real_DeleteStateBlock);
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
        patch((void **)&probe->lpVtbl->Release, hook_Release, (void **)&real_Release);
        IDirect3DTexture8_Release(probe);
    }
    for (DWORD s = 0; s < 8; s++)
        real_SetTextureStageState(dev, s, D3DTSS_MIPFILTER, D3DTEXF_LINEAR);
}

void textures_report(void)
{
    log_line("textures: %d tracked, %d unique, %d dumped, %d replaced, %d freed", ntexs, nreps, dumped, replaced, freed);
}
