// Character model replacement. taz-hd\meshes\<fingerprint>.bin replaces a character's whole vertex
// buffer (fingerprint: FNV-1a of the buffer's bytes; tools/meshpack.py writes these). The game draws a
// character as a pass of small batches, each uploading its own few bone matrices, and draws every pass
// in the same order. We skip those draws, keeping each batch's matrices and texture, and at the pass's
// last batch draw the replacement in groups of up to 16 bones, smoothed like any character.
// Springs are extra bones the game doesn't have: each hangs off a game bone and lags behind it when
// it moves, then swings back, so ears, fur and tails bounce.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define DIR "taz-hd\\meshes"
#define REPS 16
#define SEEN 1024

#pragma pack(push, 1)
struct head { DWORD magic, nbatches, nbones, nsprings, ngroups, nverts; UINT64 hash; };
struct batch { DWORD start, count, type; };
struct source { WORD batch, reg; }; // bone i's matrix is register reg of batch's palette
// Bone nbones + i: swings about pivot (bind pose) after its parent bone; tip is where it points.
// It turns by amount times the angle its simulated tip lags by, easing off towards limit radians.
struct spring { DWORD parent; float pivot[3], tip[3], stiffness, damping, amount, limit; };
struct group { DWORD first, tris, texbatch, nbones; WORD bones[16]; };
#pragma pack(pop)
// File: head, batch[nbatches] (draw order), source[nbones], spring[nsprings], group[ngroups],
// 52-byte vertices[nverts].

struct rep {
    BYTE *file;
    struct head *h;
    struct batch *batches;
    struct source *sources;
    struct spring *springs;
    struct group *groups;
    BYTE *verts;
    float (*bones)[12];     // game bones, then springs
    float (*swing)[10];     // per spring: tip position and velocity (world), started, where the tip should have been last frame
    DWORD frame;
    LARGE_INTEGER when;
    IDirect3DBaseTexture8 **tex;
    IDirect3DVertexBuffer8 *vb;
    UINT next;
};

static struct rep reps[REPS];
static int nreps;
static struct { IDirect3DVertexBuffer8 *vb; struct rep *rep; } seen[SEEN]; // rep NULL: no replacement
static int nseen;

static void load(void)
{
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA(DIR "\\*.bin", &fd);
    if (f == INVALID_HANDLE_VALUE) return;
    do {
        char path[MAX_PATH + 16];
        snprintf(path, sizeof path, DIR "\\%s", fd.cFileName);
        FILE *in = fopen(path, "rb");
        if (!in || nreps == REPS) { if (in) fclose(in); continue; }
        BYTE *b = malloc(fd.nFileSizeLow);
        size_t n = fread(b, 1, fd.nFileSizeLow, in);
        fclose(in);
        struct rep *r = &reps[nreps];
        r->file = b;
        r->h = (struct head *)b;
        if (n < sizeof *r->h || r->h->magic != 0x324d5a54) { free(b); continue; } // "TZM2"
        r->batches = (struct batch *)(r->h + 1);
        r->sources = (struct source *)(r->batches + r->h->nbatches);
        r->springs = (struct spring *)(r->sources + r->h->nbones);
        r->groups = (struct group *)(r->springs + r->h->nsprings);
        r->verts = (BYTE *)(r->groups + r->h->ngroups);
        if (r->verts + r->h->nverts * 52 != b + n) { free(b); continue; }
        r->bones = calloc(r->h->nbones + r->h->nsprings, sizeof *r->bones);
        r->swing = calloc(r->h->nsprings, sizeof *r->swing);
        r->tex = calloc(r->h->nbatches, sizeof *r->tex);
        nreps++;
        log_line("mesh: %s, %lu vertices in %lu groups for %lu batches, %lu springs", path, r->h->nverts, r->h->ngroups, r->h->nbatches, r->h->nsprings);
    } while (FindNextFileA(f, &fd));
    FindClose(f);
}

static struct rep *rep_of(IDirect3DVertexBuffer8 *vb)
{
    for (int i = 0; i < nseen; i++)
        if (seen[i].vb == vb) return seen[i].rep;
    struct rep *r = NULL;
    D3DVERTEXBUFFER_DESC d;
    BYTE *p;
    if (nreps && SUCCEEDED(IDirect3DVertexBuffer8_GetDesc(vb, &d)) && d.Pool != D3DPOOL_DEFAULT
        && SUCCEEDED(IDirect3DVertexBuffer8_Lock(vb, 0, 0, &p, D3DLOCK_READONLY))) {
        UINT64 h = 0xcbf29ce484222325ULL;
        for (UINT i = 0; i < d.Size; i++) h = (h ^ p[i]) * 0x100000001b3ULL;
        IDirect3DVertexBuffer8_Unlock(vb);
        for (int i = 0; i < nreps; i++)
            if (reps[i].h->hash == h) r = &reps[i];
        if (r) log_line("mesh: replacing buffer %p (%016llx)", (void *)vb, h);
    }
    if (nseen == SEEN) nseen = 0;
    seen[nseen].vb = vb;
    seen[nseen++].rep = r;
    return r;
}

void mesh_forget(IDirect3DVertexBuffer8 *vb)
{
    for (int i = 0; i < nseen; i++)
        if (seen[i].vb == vb) seen[i] = seen[--nseen];
}

static void apply(const float *m, const float *p, float *out) // 3x4 bone matrix (rows) times point
{
    for (int i = 0; i < 3; i++) out[i] = m[i * 4] * p[0] + m[i * 4 + 1] * p[1] + m[i * 4 + 2] * p[2] + m[i * 4 + 3];
}

static float dot(const float *a, const float *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

// Steps each spring's tip toward where its parent puts it (once per frame), then poses the spring
// bones: the parent's matrix turned about the pivot by the angle between where the tip should be and
// where it is.
static void pose_springs(struct rep *r)
{
    LARGE_INTEGER now, freq;
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&freq);
    float dt = 0;
    if (r->frame != presents) {
        dt = r->frame ? (float)(now.QuadPart - r->when.QuadPart) / freq.QuadPart : 0;
        if (dt > 0.1f) dt = 0; // a hitch or a long pause: settle instead of flinging
        r->frame = presents;
        r->when = now;
    }
    for (UINT i = 0; i < r->h->nsprings; i++) {
        const struct spring *sp = &r->springs[i];
        const float *m = r->bones[sp->parent];
        float *st = r->swing[i], x[3], t[3], a[3], b[3];
        apply(m, sp->pivot, x);
        apply(m, sp->tip, t);
        for (int k = 0; k < 3; k++) a[k] = t[k] - x[k];
        float len = sqrtf(dot(a, a)), d2 = 0;
        for (int k = 0; k < 3; k++) d2 += (st[k] - t[k]) * (st[k] - t[k]);
        if (!st[6] || d2 > 4 * len * len) { // new or teleported: start at rest
            for (int k = 0; k < 3; k++) st[k] = st[7 + k] = t[k], st[3 + k] = 0;
            st[6] = 1;
        }
        if (dt) { // damped against the parent's own motion: only speeding up, slowing and turning swing it
            float vt[3], p0[3];
            for (int k = 0; k < 3; k++) vt[k] = (t[k] - st[7 + k]) / dt, p0[k] = st[7 + k];
            for (float done = 0; done < dt; done += 1.0f / 240) {
                float h = dt - done < 1.0f / 240 ? dt - done : 1.0f / 240;
                for (int k = 0; k < 3; k++) {
                    float want = p0[k] + vt[k] * (done + h);
                    st[3 + k] += (sp->stiffness * (want - st[k]) - sp->damping * (st[3 + k] - vt[k])) * h;
                    st[k] += st[3 + k] * h;
                }
            }
            for (int k = 0; k < 3; k++) st[7 + k] = t[k];
        }
        for (int k = 0; k < 3; k++) b[k] = st[k] - x[k];
        float lb = sqrtf(dot(b, b));
        if (lb > 1e-6f)
            for (int k = 0; k < 3; k++) st[k] = x[k] + b[k] * len / lb, b[k] *= len / lb; // keeps its length
        // Rotation taking a to b, at most limit radians (Rodrigues).
        float ax[3] = { a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0] };
        float s = sqrtf(dot(ax, ax)), c = dot(a, b), ang = sp->limit * tanhf(atan2f(s, c) * sp->amount / sp->limit);
        float R[9] = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
        if (s > 1e-9f) {
            for (int k = 0; k < 3; k++) ax[k] /= s;
            float co = cosf(ang), si = sinf(ang), oc = 1 - co;
            float X = ax[0], Y = ax[1], Z = ax[2];
            float m3[9] = { co + X * X * oc, X * Y * oc - Z * si, X * Z * oc + Y * si,
                            Y * X * oc + Z * si, co + Y * Y * oc, Y * Z * oc - X * si,
                            Z * X * oc - Y * si, Z * Y * oc + X * si, co + Z * Z * oc };
            memcpy(R, m3, sizeof R);
        }
        float *o = r->bones[r->h->nbones + i];
        for (int row = 0; row < 3; row++) {
            for (int col = 0; col < 3; col++)
                o[row * 4 + col] = R[row * 3] * m[col] + R[row * 3 + 1] * m[4 + col] + R[row * 3 + 2] * m[8 + col];
            float tr = 0;
            for (int k = 0; k < 3; k++) tr += R[row * 3 + k] * (m[k * 4 + 3] - x[k]);
            o[row * 4 + 3] = tr + x[row];
        }
    }
}

static void draw_replacement(IDirect3DDevice8 *dev, struct rep *r, IDirect3DVertexBuffer8 *game,
                             HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT))
{
    if (!r->vb) {
        BYTE *p;
        UINT size = r->h->nverts * 52;
        if (FAILED(IDirect3DDevice8_CreateVertexBuffer(dev, size, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &r->vb))) return;
        if (SUCCEEDED(IDirect3DVertexBuffer8_Lock(r->vb, 0, 0, &p, 0))) {
            memcpy(p, r->verts, size);
            IDirect3DVertexBuffer8_Unlock(r->vb);
        }
    }
    pose_springs(r);
    float saved[48][4], c[48][4];
    IDirect3DDevice8_GetVertexShaderConstant(dev, 0, saved, 48);
    IDirect3DBaseTexture8 *cur = textures_bound(0);
    IDirect3DDevice8_SetStreamSource(dev, 0, r->vb, 52);
    for (UINT i = 0; i < r->h->ngroups; i++) {
        const struct group *g = &r->groups[i];
        for (UINT k = 0; k < g->nbones; k++)
            memcpy(c[k * 3], r->bones[g->bones[k]], sizeof r->bones[0]);
        IDirect3DDevice8_SetVertexShaderConstant(dev, 0, c, g->nbones * 3);
        IDirect3DDevice8_SetTexture(dev, 0, r->tex[g->texbatch]);
        smooth_keep_normals = 1; // tools/normals.py already evened them out
        smooth_draw(dev, D3DPT_TRIANGLELIST, g->first, g->tris, draw);
        smooth_keep_normals = 0;
    }
    IDirect3DDevice8_SetTexture(dev, 0, cur);
    IDirect3DDevice8_SetStreamSource(dev, 0, game, 52);
    IDirect3DDevice8_SetVertexShaderConstant(dev, 0, saved, 48);
}

HRESULT mesh_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                  HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT))
{
    static int loaded;
    if (!loaded) loaded = 1, load();
    IDirect3DVertexBuffer8 *src = NULL;
    UINT stride = 0;
    if (!smooth_character(dev) || FAILED(IDirect3DDevice8_GetStreamSource(dev, 0, &src, &stride)) || !src || stride != 52) {
        if (src) IDirect3DVertexBuffer8_Release(src);
        return draw(dev, type, start, count);
    }
    capture_draw(dev, src, type, start, count);
    struct rep *r = settings.hd_models ? rep_of(src) : NULL;
    UINT i = r ? r->next : 0;
    if (r && (i >= r->h->nbatches || r->batches[i].start != start || r->batches[i].count != count || r->batches[i].type != (DWORD)type))
        for (i = 0; i < r->h->nbatches; i++)
            if (r->batches[i].start == start && r->batches[i].count == count && r->batches[i].type == (DWORD)type) break;
    if (!r || i == r->h->nbatches) {
        IDirect3DVertexBuffer8_Release(src);
        return smooth_draw(dev, type, start, count, draw);
    }
    float c[48][4];
    IDirect3DDevice8_GetVertexShaderConstant(dev, 0, c, 48);
    for (UINT b = 0; b < r->h->nbones; b++) // few bones per batch; a scan of ~50 is cheap
        if (r->sources[b].batch == i) memcpy(r->bones[b], c[r->sources[b].reg], sizeof r->bones[0]);
    r->tex[i] = textures_bound(0);
    r->next = i + 1;
    if (r->next == r->h->nbatches) {
        r->next = 0;
        draw_replacement(dev, r, src, draw);
    }
    IDirect3DVertexBuffer8_Release(src);
    return D3D_OK;
}
