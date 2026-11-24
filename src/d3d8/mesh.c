// Character model replacement. taz-hd\meshes\<fingerprint>.bin replaces a character's whole vertex
// buffer (fingerprint: FNV-1a of the buffer's bytes; tools/meshpack.py writes these). The game draws a
// character as a pass of small batches, each uploading its own few bone matrices, and draws every pass
// in the same order. We skip those draws, keeping each batch's matrices and texture, and at the pass's
// last batch draw the replacement in groups of up to 16 bones. Replacements are already dense and
// smooth (tools/subdivide.py), so they skip smooth.c's tessellation.
// Springs are extra bones the game doesn't have: each hangs off a game bone and lags behind it when
// it moves, then swings back, so ears, fur and tails bounce.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define DIR "taz-hd\\meshes"
#define REPS 128 // headers are read at startup, the rest (Taz-sized: ~3.5 MB) when the game first draws that model
#define SEEN 1024

#pragma pack(push, 1)
struct head { DWORD magic, nbatches, nbones, nsprings, ngroups, nverts, nindices; UINT64 hash; };
struct batch { DWORD start, count, type; };
struct source { WORD batch, reg; }; // bone i's matrix is register reg of batch's palette
// Bone nbones + i: swings about pivot (bind pose) after its parent bone; tip is where it points.
// It turns by amount times the angle its simulated tip lags by, easing off towards limit radians.
struct spring { DWORD parent; float pivot[3], tip[3], stiffness, damping, amount, limit; };
struct group { DWORD first, tris, texbatch, nbones, base, nverts; WORD bones[16]; }; // indices count from base
#pragma pack(pop)
// File: head, batch[nbatches] (draw order), source[nbones], spring[nsprings], group[ngroups],
// 52-byte vertices[nverts], WORD indices[nindices] (triangle lists).
// "TZM5" files have, before the indices, 96 bytes per vertex: where each of its six bones alone puts it
// (float[6][3]), then weights and palette registers of bones 4-6 (float[3] each; tools/subdivide.py).
// The game's shaders move one position with three bones; a copy of each shader reads the places
// instead (shader_created). That is exactly how the original model's flat faces stretch between bones,
// so skin a bone slides a long way (Gossamer's brows, Taz's jaw) keeps its shape. The 52-byte position
// is the old single one, kept for the fur's bind-pose map.
#define TZM3 0x334d5a54
#define TZM5 0x354d5a54
#define PLACES 96

const DWORD mesh_places_decl[17] = { 0x20000000, 0x40020000, 0x40020001, 0x40050002, 0x40020003, 0x40040004, 0x40010005, 0x20000001,
                                     0x40020006, 0x40020007, 0x40020008, 0x40020009, 0x4002000a, 0x4002000b, 0x4002000c, 0x4002000d, 0xffffffff };

static UINT places_size(DWORD magic) { return magic == TZM5 ? PLACES : 0; }

struct rep {
    char path[MAX_PATH + 16];
    struct head head, *h; // h: the whole file once read
    struct batch *batches;
    struct source *sources;
    struct spring *springs;
    struct group *groups;
    BYTE *verts;
    WORD *indices;
    float (*bones)[12];     // game bones, then springs
    float (*swing)[10];     // per spring: tip position and velocity (world), started, where the tip should have been last frame
    DWORD frame;
    LARGE_INTEGER when;
    IDirect3DBaseTexture8 **tex;
    IDirect3DVertexBuffer8 *vb, *places;
    IDirect3DIndexBuffer8 *ib;
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
        struct rep *r = &reps[nreps];
        snprintf(r->path, sizeof r->path, DIR "\\%s", fd.cFileName);
        FILE *in = fopen(r->path, "rb");
        int ok = in && nreps < REPS && fread(&r->head, sizeof r->head, 1, in) == 1 && (r->head.magic == TZM3 || places_size(r->head.magic));
        if (in) fclose(in);
        if (ok) nreps++;
        else log_line("mesh: skipped %s", r->path);
    } while (FindNextFileA(f, &fd));
    FindClose(f);
}

static int read_rep(struct rep *r)
{
    FILE *in = fopen(r->path, "rb");
    if (!in) return 0;
    fseek(in, 0, SEEK_END);
    long n = ftell(in);
    fseek(in, 0, SEEK_SET);
    const struct head *h = &r->head;
    long want = sizeof *h + h->nbatches * sizeof(struct batch) + h->nbones * sizeof(struct source) + h->nsprings * sizeof(struct spring)
              + h->ngroups * sizeof(struct group) + h->nverts * (52 + places_size(h->magic)) + h->nindices * 2;
    BYTE *b = n == want ? malloc(n) : NULL;
    if (b && (fread(b, 1, n, in) != (size_t)n || memcmp(b, h, sizeof *h))) free(b), b = NULL;
    fclose(in);
    if (!b) {
        r->head.hash = 0; // don't try again
        log_line("mesh: %s is damaged or changed", r->path);
        return 0;
    }
    r->h = (struct head *)b;
    r->batches = (struct batch *)(r->h + 1);
    r->sources = (struct source *)(r->batches + r->h->nbatches);
    r->springs = (struct spring *)(r->sources + r->h->nbones);
    r->groups = (struct group *)(r->springs + r->h->nsprings);
    r->verts = (BYTE *)(r->groups + r->h->ngroups);
    r->indices = (WORD *)(r->verts + r->h->nverts * (52 + places_size(h->magic)));
    r->bones = calloc(r->h->nbones + r->h->nsprings, sizeof *r->bones);
    r->swing = calloc(r->h->nsprings, sizeof *r->swing);
    r->tex = calloc(r->h->nbatches, sizeof *r->tex);
    log_line("mesh: %s, %lu vertices, %lu triangles in %lu groups for %lu batches, %lu springs", r->path, r->h->nverts,
             r->h->nindices / 3, r->h->ngroups, r->h->nbatches, r->h->nsprings);
    return 1;
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
            if (reps[i].head.hash == h && (reps[i].h || read_rep(&reps[i]))) r = &reps[i];
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

// The game has each kind of character shader (lit, outline, a plain one) for 1, 2 and 3 bones per
// vertex and picks by the model, so a one-bone character such as Gossamer arrives with a shader that
// ignores the blended weights of a dense replacement: its in-between points snapped to one bone (brows
// with sawtooth edges). Replacements are drawn with the 3-bone shader of the same kind, and those with
// places with a copy of it in which each bone moves its own place (v6-v11, stream 1) instead of all
// moving v0: the blocks of "dp4 r, v0, c[a0 + row]", one per bone, plus three more made from the third
// (weights v12, palette registers v13).
static struct vshader { DWORD game, bent; int kind, bones; DWORD uses; } vshaders[16]; // uses: which of c48.. it reads
static int nvshaders;

void mesh_shader_created(IDirect3DDevice8 *dev, DWORD h, const DWORD *fn)
{
    static const DWORD ramp[] = { 1, 0xe0020001, 0xa0ff0030 };          // mov oT1.y, c48.w: lit
    static const DWORD push[] = { 4, 0x80070000, 0x80e40002, 0xa0ff0031 }; // mad r0.xyz, r2, c49.w, r0: outline
    DWORD code[1024];
    int n = 0, found = 0, kind = 0;
    DWORD uses = 0;
    if (nvshaders == 16) return;
    for (; n < 1023 && fn[n] != 0xffff; n++) {
        code[n] = fn[n];
        if ((fn[n] & 0xf0002000) == 0xa0000000 && (fn[n] & 0x7ff) >= 48 && (fn[n] & 0x7ff) < 80) uses |= 1u << ((fn[n] & 0x7ff) - 48);
        if (n >= 2 && fn[n - 2] == 9 && (fn[n] & 0xf0001fff) == 0x90000000) code[n] |= 6 + found++ / 3; // dp4, source v0
        if (!memcmp(fn + n, ramp, sizeof ramp)) kind = 1;
        if (!memcmp(fn + n, push, sizeof push)) kind = 2;
    }
    int from = 0, to = 0; // the third bone's block: from its palette read to just after its last weight
    for (int i = 0; i < n; i++) {
        if (code[i] == 1 && code[i + 2] == 0x90aa0002) from = i;
        if (code[i] == 0x90aa0001) to = i + 2;
    }
    int len = to - from;
    if (found == 9 && from && len > 0 && n + 3 * len < 1023) {
        memmove(code + to + 3 * len, code + to, (n - to) * sizeof *code);
        for (DWORD k = 0; k < 3; k++)
            for (int i = 0; i < len; i++) {
                DWORD t = code[from + i], part = 0x90000000 | k * 0x55 << 16;
                code[to + k * len + i] = t == 0x90aa0002 ? part | 13 : t == 0x90e40008 ? 0x90e40009 + k : t == 0x90aa0001 ? part | 12 : t;
            }
        n += 3 * len;
    }
    code[n] = 0xffff;
    struct vshader *v = &vshaders[nvshaders++];
    v->game = h, v->kind = kind, v->bones = found / 3, v->uses = uses;
    if (found == 9 && FAILED(IDirect3DDevice8_CreateVertexShader(dev, mesh_places_decl, code, &v->bent, 0))) v->bent = 0, log_line("mesh: no per-bone copy of shader %#lx", h);
}

void mesh_shader_deleted(IDirect3DDevice8 *dev, DWORD h)
{
    for (int i = 0; i < nvshaders; i++) {
        if (vshaders[i].game != h) continue;
        DWORD bent = vshaders[i].bent;
        vshaders[i--] = vshaders[--nvshaders];
        if (bent) IDirect3DDevice8_DeleteVertexShader(dev, bent);
    }
}

// 1 or 2 when vs is the per-bone copy of a lit or outline shader.
int mesh_places_kind(DWORD vs)
{
    for (int i = 0; i < nvshaders; i++)
        if (vshaders[i].bent == vs) return vshaders[i].kind;
    return 0;
}

// What to draw a replacement with in place of the game's shader vs; *bent says it reads the places.
static DWORD shader_for(DWORD vs, int places, int *bent)
{
    const struct vshader *now = NULL;
    for (int i = 0; i < nvshaders; i++)
        if (vshaders[i].game == vs) now = &vshaders[i];
    for (int i = 0; i < nvshaders && now; i++)
        if (vshaders[i].kind == now->kind && vshaders[i].uses == now->uses && vshaders[i].bones == 3) // levels without fog lay their constants out differently
            return (*bent = places && vshaders[i].bent) ? vshaders[i].bent : vshaders[i].game;
    return vs;
}

static UINT group_verts;
static HRESULT WINAPI draw_indexed(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    return IDirect3DDevice8_DrawIndexedPrimitive(dev, type, 0, group_verts, start, count);
}

static void draw_replacement(IDirect3DDevice8 *dev, struct rep *r, IDirect3DVertexBuffer8 *game)
{
    BYTE *p;
    if (!r->vb && SUCCEEDED(IDirect3DDevice8_CreateVertexBuffer(dev, r->h->nverts * 52, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &r->vb))
        && SUCCEEDED(IDirect3DVertexBuffer8_Lock(r->vb, 0, 0, &p, 0))) {
        memcpy(p, r->verts, r->h->nverts * 52);
        IDirect3DVertexBuffer8_Unlock(r->vb);
    }
    if (!r->ib && SUCCEEDED(IDirect3DDevice8_CreateIndexBuffer(dev, r->h->nindices * 2, D3DUSAGE_WRITEONLY, D3DFMT_INDEX16, D3DPOOL_MANAGED, &r->ib))
        && SUCCEEDED(IDirect3DIndexBuffer8_Lock(r->ib, 0, 0, &p, 0))) {
        memcpy(p, r->indices, r->h->nindices * 2);
        IDirect3DIndexBuffer8_Unlock(r->ib);
    }
    if (!r->vb || !r->ib) return;
    DWORD vs = 0;
    int bent = 0;
    if (r->h->magic == TZM5 && !r->places && SUCCEEDED(IDirect3DDevice8_CreateVertexBuffer(dev, r->h->nverts * PLACES, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &r->places))
        && SUCCEEDED(IDirect3DVertexBuffer8_Lock(r->places, 0, 0, &p, 0))) {
        memcpy(p, r->verts + r->h->nverts * 52, r->h->nverts * PLACES);
        IDirect3DVertexBuffer8_Unlock(r->places);
    }
    IDirect3DDevice8_GetVertexShader(dev, &vs);
    DWORD use = shader_for(vs, r->places != NULL, &bent);
    if (bent) IDirect3DDevice8_SetStreamSource(dev, 1, r->places, PLACES);
    if (use != vs) IDirect3DDevice8_SetVertexShader(dev, use);
    pose_springs(r);
    float saved[48][4], c[48][4];
    IDirect3DDevice8_GetVertexShaderConstant(dev, 0, saved, 48);
    IDirect3DBaseTexture8 *cur = textures_bound(0);
    IDirect3DIndexBuffer8 *gib = NULL;
    UINT gbase = 0;
    IDirect3DDevice8_GetIndices(dev, &gib, &gbase);
    IDirect3DDevice8_SetStreamSource(dev, 0, r->vb, 52);
    for (UINT i = 0; i < r->h->ngroups; i++) {
        const struct group *g = &r->groups[i];
        for (UINT k = 0; k < g->nbones; k++)
            memcpy(c[k * 3], r->bones[g->bones[k]], sizeof r->bones[0]);
        IDirect3DDevice8_SetVertexShaderConstant(dev, 0, c, g->nbones * 3);
        IDirect3DDevice8_SetTexture(dev, 0, r->tex[g->texbatch]);
        IDirect3DDevice8_SetIndices(dev, r->ib, g->base);
        group_verts = g->nverts;
        style_draw(dev, D3DPT_TRIANGLELIST, g->first, g->tris, draw_indexed);
    }
    IDirect3DDevice8_SetIndices(dev, gib, gbase);
    if (gib) IDirect3DIndexBuffer8_Release(gib);
    IDirect3DDevice8_SetTexture(dev, 0, cur);
    IDirect3DDevice8_SetStreamSource(dev, 0, game, 52);
    if (bent) IDirect3DDevice8_SetStreamSource(dev, 1, NULL, 0);
    if (use != vs) IDirect3DDevice8_SetVertexShader(dev, vs);
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
    style_player = style_is_player(src); // the model's draws below, ours or the game's, get the Taz style
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
        draw_replacement(dev, r, src);
    }
    IDirect3DVertexBuffer8_Release(src);
    return D3D_OK;
}
