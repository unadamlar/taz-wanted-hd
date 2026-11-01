// Smoother characters. Characters are skinned in a vertex shader (up to 3 bones per vertex, bone
// matrices uploaded per small batch), lit through a cel-shading ramp from the vertex normal, and
// outlined by a second pass that pushes the same vertices out along the normal. Each batch is drawn
// with DrawPrimitive from a managed vertex buffer, so we replace every batch with a cached
// tessellated copy: each triangle becomes a curved PN triangle (Vlachos et al. 2001) split LEVEL x
// LEVEL ways. New vertices blend their corners' bones (keeping the 3 heaviest), normals, colours
// and texture coordinates. Both passes draw the same copy, so the outline still fits the body.
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#undef FVF // proxy.h's overlay format; we need the vertex buffer field of that name

#define LEVEL 3
#define TABLE 16384
#define MESHES 256
#define SHARP 0.75f // corners whose normals differ more than this (cos) at one position keep straight edges

#pragma pack(push, 1)
struct cvert { float p[3], w[3]; BYTE idx[4]; float n[3]; DWORD color; float uv[2]; };
#pragma pack(pop)
_Static_assert(sizeof(struct cvert) == 52, "character vertex layout");

// The vertex declaration every character shader uses: position, 3 weights, bone indices, normal,
// colour, texture coordinates.
static const DWORD DECL[] = { 0x20000000, 0x40020000, 0x40020001, 0x40050002, 0x40020003, 0x40040004, 0x40010005, 0xffffffff };

struct entry { IDirect3DVertexBuffer8 *src, *vb; UINT start, count, tris; D3DPRIMITIVETYPE type; };
struct mesh { IDirect3DVertexBuffer8 *src; UINT n; float (*gn)[3]; BYTE *sharp; }; // per-position normals

static struct entry table[TABLE];
static struct mesh meshes[MESHES];
static int nentries, nmeshes;
static DWORD shaders[16];
static int nshaders;

static HRESULT (WINAPI *real_CreateVertexShader)(IDirect3DDevice8 *, CONST DWORD *, CONST DWORD *, DWORD *, DWORD);
static HRESULT (WINAPI *real_CreateVertexBuffer)(IDirect3DDevice8 *, UINT, DWORD, DWORD, D3DPOOL, IDirect3DVertexBuffer8 **);

static void flush(void)
{
    for (int i = 0; i < TABLE; i++)
        if (table[i].vb) IDirect3DVertexBuffer8_Release(table[i].vb);
    for (int i = 0; i < nmeshes; i++) free(meshes[i].gn), free(meshes[i].sharp);
    memset(table, 0, sizeof table);
    memset(meshes, 0, sizeof meshes);
    nentries = nmeshes = 0;
}

static HRESULT WINAPI hook_CreateVertexShader(IDirect3DDevice8 *dev, CONST DWORD *decl, CONST DWORD *fn, DWORD *h, DWORD usage)
{
    HRESULT hr = real_CreateVertexShader(dev, decl, fn, h, usage);
    if (SUCCEEDED(hr) && decl && !memcmp(decl, DECL, sizeof DECL) && nshaders < 16) shaders[nshaders++] = *h;
    return hr;
}

// A new buffer at the address of one we cached means the old one is gone.
static HRESULT WINAPI hook_CreateVertexBuffer(IDirect3DDevice8 *dev, UINT len, DWORD usage, DWORD fvf, D3DPOOL pool, IDirect3DVertexBuffer8 **vb)
{
    HRESULT hr = real_CreateVertexBuffer(dev, len, usage, fvf, pool, vb);
    if (SUCCEEDED(hr))
        for (int i = 0; i < nmeshes; i++)
            if (meshes[i].src == *vb) { flush(); break; }
    return hr;
}

static UINT32 pos_hash(const float *p)
{
    const UINT32 *u = (const UINT32 *)p;
    return (u[0] * 73856093u) ^ (u[1] * 19349663u) ^ (u[2] * 83492791u);
}

// Averages the normals of vertices sharing a position, so neighbouring batches curve their shared
// edges the same way, and marks positions where those normals disagree (hard edges).
static struct mesh *mesh_of(IDirect3DVertexBuffer8 *src, const struct cvert *v, UINT n)
{
    for (int i = 0; i < nmeshes; i++)
        if (meshes[i].src == src) return &meshes[i];
    if (nmeshes == MESHES) flush();
    struct mesh *m = &meshes[nmeshes++];
    m->src = src;
    m->n = n;
    m->gn = calloc(n, sizeof *m->gn);
    m->sharp = calloc(n, 1);
    UINT size = 1;
    while (size < n * 2) size <<= 1;
    int *slot = malloc(size * sizeof *slot), *first = malloc(n * sizeof *first);
    memset(slot, -1, size * sizeof *slot);
    for (UINT i = 0; i < n; i++) { // first[i]: the first vertex with i's position
        UINT32 k = pos_hash(v[i].p) & (size - 1);
        while (slot[k] >= 0 && memcmp(v[slot[k]].p, v[i].p, 12)) k = (k + 1) & (size - 1);
        if (slot[k] < 0) slot[k] = i;
        first[i] = slot[k];
        for (int c = 0; c < 3; c++) m->gn[first[i]][c] += v[i].n[c];
    }
    int sharp = 0;
    for (UINT i = 0; i < n; i++) {
        float *g = m->gn[first[i]];
        if (first[i] == (int)i) {
            float l = sqrtf(g[0] * g[0] + g[1] * g[1] + g[2] * g[2]);
            if (l > 1e-6f) g[0] /= l, g[1] /= l, g[2] /= l;
            else m->sharp[i] = 1;
        }
    }
    for (UINT i = 0; i < n; i++) {
        const float *g = m->gn[first[i]], *a = v[i].n;
        float la = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        if (la > 1e-6f && (g[0] * a[0] + g[1] * a[1] + g[2] * a[2]) / la < SHARP) m->sharp[first[i]] = 1;
    }
    for (UINT i = 0; i < n; i++) {
        if (first[i] != (int)i) memcpy(m->gn[i], m->gn[first[i]], 12), m->sharp[i] = m->sharp[first[i]];
        sharp += m->sharp[i];
    }
    free(slot);
    free(first);
    log_line("smooth: mesh %p, %u vertices, %d on hard edges", (void *)src, n, sharp);
    return m;
}

// Normal, colour, texture coordinates and bones of a point blended from n corners with weights k.
// Each bone's weight is summed over the corners; the 3 heaviest are kept.
static void blend(struct cvert *o, const struct cvert *const *c, const float *k, int n)
{
    memset(o->n, 0, sizeof o->n);
    memset(o->uv, 0, sizeof o->uv);
    float col[4] = { 0 };
    BYTE bi[9];
    float bw[9];
    int nb = 0;
    for (int t = 0; t < n; t++) {
        for (int a = 0; a < 3; a++) o->n[a] += c[t]->n[a] * k[t];
        for (int a = 0; a < 2; a++) o->uv[a] += c[t]->uv[a] * k[t];
        for (int a = 0; a < 4; a++) col[a] += ((const BYTE *)&c[t]->color)[a] * k[t];
        for (int s = 0; s < 3; s++) {
            float x = c[t]->w[s] * k[t];
            if (x <= 0) continue;
            int q = 0;
            while (q < nb && bi[q] != c[t]->idx[s]) q++;
            if (q == nb) bi[nb] = c[t]->idx[s], bw[nb++] = 0;
            bw[q] += x;
        }
    }
    float l = sqrtf(o->n[0] * o->n[0] + o->n[1] * o->n[1] + o->n[2] * o->n[2]);
    if (l > 1e-6f) o->n[0] /= l, o->n[1] /= l, o->n[2] /= l;
    for (int a = 0; a < 4; a++) ((BYTE *)&o->color)[a] = (BYTE)(col[a] + 0.5f);
    float total = 0, kept = 0;
    for (int q = 0; q < nb; q++) total += bw[q];
    memset(o->idx, 0, 4);
    memset(o->w, 0, sizeof o->w);
    for (int s = 0; s < 3 && nb; s++) {
        int best = 0;
        for (int q = 1; q < nb; q++)
            if (bw[q] > bw[best]) best = q;
        o->idx[s] = bi[best];
        o->w[s] = bw[best];
        kept += bw[best];
        for (int q = best; q < nb - 1; q++) bi[q] = bi[q + 1], bw[q] = bw[q + 1];
        nb--;
    }
    if (kept > 0)
        for (int s = 0; s < 3; s++) o->w[s] *= total / kept;
}

// Control point next to corner a on edge a-b: a third of the way along, pulled onto a's tangent plane.
static void edge_point(float *out, const float *a, const float *b, const float *na, int flat)
{
    float d = flat ? 0 : (b[0] - a[0]) * na[0] + (b[1] - a[1]) * na[1] + (b[2] - a[2]) * na[2];
    for (int k = 0; k < 3; k++) out[k] = (2 * a[k] + b[k] - d * na[k]) / 3;
}

struct corner { const struct cvert *v; const float *g; BYTE sharp; };

// Point s/LEVEL of the way from a to b on their shared curved edge. Both triangles on an edge get
// bit-identical points: the edge is always walked from the same end.
static void edge_vertex(struct cvert *o, struct corner a, struct corner b, int s)
{
    int swap = memcmp(a.v->p, b.v->p, 12);
    if (!swap) swap = memcmp(a.v->n, b.v->n, 12);
    if (swap > 0) { struct corner t = a; a = b; b = t; s = LEVEL - s; }
    float u = (float)s / LEVEL, w = (float)(LEVEL - s) / LEVEL;
    float ab[3], ba[3];
    int flat = a.sharp && b.sharp;
    edge_point(ab, a.v->p, b.v->p, a.g, flat);
    edge_point(ba, b.v->p, a.v->p, b.g, flat);
    for (int k = 0; k < 3; k++)
        o->p[k] = a.v->p[k] * w * w * w + b.v->p[k] * u * u * u + 3 * (ab[k] * w * w * u + ba[k] * w * u * u);
    const struct cvert *c[2] = { a.v, b.v };
    const float kw[2] = { w, u };
    blend(o, c, kw, 2);
}

static void tessellate(const struct corner c[3], struct cvert *out)
{
    const float *P1 = c[0].v->p, *P2 = c[1].v->p, *P3 = c[2].v->p;
    float b210[3], b120[3], b021[3], b012[3], b102[3], b201[3], b111[3];
    edge_point(b210, P1, P2, c[0].g, c[0].sharp && c[1].sharp);
    edge_point(b120, P2, P1, c[1].g, c[0].sharp && c[1].sharp);
    edge_point(b021, P2, P3, c[1].g, c[1].sharp && c[2].sharp);
    edge_point(b012, P3, P2, c[2].g, c[1].sharp && c[2].sharp);
    edge_point(b102, P3, P1, c[2].g, c[2].sharp && c[0].sharp);
    edge_point(b201, P1, P3, c[0].g, c[2].sharp && c[0].sharp);
    for (int k = 0; k < 3; k++) {
        float e = (b210[k] + b120[k] + b021[k] + b012[k] + b102[k] + b201[k]) / 6;
        float v = (P1[k] + P2[k] + P3[k]) / 3;
        b111[k] = e + (e - v) / 2;
    }

    struct cvert grid[(LEVEL + 1) * (LEVEL + 2) / 2];
    int at[LEVEL + 1][LEVEL + 1], n = 0;
    for (int j = 0; j <= LEVEL; j++)
        for (int i = 0; i + j <= LEVEL; i++) {
            struct cvert *o = &grid[n];
            at[i][j] = n++;
            if (i == 0 && j == 0) *o = *c[0].v; // corners stay exactly as they were
            else if (i == LEVEL) *o = *c[1].v;
            else if (j == LEVEL) *o = *c[2].v;
            else if (j == 0) edge_vertex(o, c[0], c[1], i);
            else if (i + j == LEVEL) edge_vertex(o, c[1], c[2], j);
            else if (i == 0) edge_vertex(o, c[2], c[0], LEVEL - j);
            else {
                float u = (float)i / LEVEL, v = (float)j / LEVEL, w = 1 - u - v; // weights of P2, P3, P1
                for (int k = 0; k < 3; k++)
                    o->p[k] = P1[k] * w * w * w + P2[k] * u * u * u + P3[k] * v * v * v
                            + 3 * (b210[k] * w * w * u + b120[k] * w * u * u + b201[k] * w * w * v
                                 + b021[k] * u * u * v + b102[k] * w * v * v + b012[k] * u * v * v)
                            + 6 * b111[k] * w * u * v;
                const struct cvert *cs[3] = { c[0].v, c[1].v, c[2].v };
                const float kw[3] = { w, u, v };
                blend(o, cs, kw, 3);
            }
        }
    for (int j = 0; j < LEVEL; j++)
        for (int i = 0; i + j < LEVEL; i++) {
            *out++ = grid[at[i][j]], *out++ = grid[at[i + 1][j]], *out++ = grid[at[i][j + 1]];
            if (i + j < LEVEL - 1)
                *out++ = grid[at[i + 1][j]], *out++ = grid[at[i + 1][j + 1]], *out++ = grid[at[i][j + 1]];
        }
}

static struct entry *build(IDirect3DDevice8 *dev, struct entry *e)
{
    D3DVERTEXBUFFER_DESC d;
    BYTE *src;
    if (FAILED(IDirect3DVertexBuffer8_GetDesc(e->src, &d)) || d.Pool == D3DPOOL_DEFAULT) return NULL;
    UINT n = d.Size / sizeof(struct cvert);
    UINT verts = e->type == D3DPT_TRIANGLESTRIP ? e->count + 2 : e->count * 3;
    if (e->start + verts > n || FAILED(IDirect3DVertexBuffer8_Lock(e->src, 0, 0, &src, D3DLOCK_READONLY))) return NULL;
    const struct cvert *v = (const struct cvert *)src;
    struct mesh *m = mesh_of(e->src, v, n);

    static struct cvert *out; // scratch, grown as needed
    static UINT room;
    if (e->count * LEVEL * LEVEL * 3 > room) {
        free(out);
        room = e->count * LEVEL * LEVEL * 3 * 2;
        out = malloc(room * sizeof *out);
    }
    UINT tris = 0;
    for (UINT t = 0; t < e->count; t++) {
        UINT a, b, c;
        if (e->type == D3DPT_TRIANGLESTRIP) a = e->start + t, b = a + 1, c = a + 2;
        else a = e->start + t * 3, b = a + 1, c = a + 2;
        if (e->type == D3DPT_TRIANGLESTRIP && (t & 1)) { UINT x = a; a = b; b = x; } // keep the winding
        if (!memcmp(v[a].p, v[b].p, 12) || !memcmp(v[b].p, v[c].p, 12) || !memcmp(v[a].p, v[c].p, 12)) continue;
        const struct corner cs[3] = { { &v[a], m->gn[a], m->sharp[a] }, { &v[b], m->gn[b], m->sharp[b] }, { &v[c], m->gn[c], m->sharp[c] } };
        tessellate(cs, out + tris * 3);
        tris += LEVEL * LEVEL;
    }
    IDirect3DVertexBuffer8_Unlock(e->src);

    BYTE *dst;
    if (!tris || FAILED(IDirect3DDevice8_CreateVertexBuffer(dev, tris * 3 * sizeof *out, d.Usage & ~D3DUSAGE_DYNAMIC, d.FVF, D3DPOOL_MANAGED, &e->vb)))
        return NULL;
    if (SUCCEEDED(IDirect3DVertexBuffer8_Lock(e->vb, 0, 0, &dst, 0))) {
        memcpy(dst, out, tris * 3 * sizeof *out);
        IDirect3DVertexBuffer8_Unlock(e->vb);
    }
    e->tris = tris;
    nentries++;
    return e;
}

HRESULT smooth_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                    HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT))
{
    DWORD vs = 0;
    int ours = 0;
    if (settings.smooth && (type == D3DPT_TRIANGLESTRIP || type == D3DPT_TRIANGLELIST) && nshaders
        && SUCCEEDED(IDirect3DDevice8_GetVertexShader(dev, &vs)))
        for (int i = 0; i < nshaders; i++) ours |= shaders[i] == vs;
    IDirect3DVertexBuffer8 *src = NULL;
    UINT stride = 0;
    if (!ours || FAILED(IDirect3DDevice8_GetStreamSource(dev, 0, &src, &stride)) || !src || stride != sizeof(struct cvert)) {
        if (src) IDirect3DVertexBuffer8_Release(src);
        return draw(dev, type, start, count);
    }

    UINT32 h = ((UINT32)(UINT_PTR)src >> 4) * 2654435761u ^ start * 40503u ^ count * 977u ^ type;
    UINT i = h & (TABLE - 1);
    while (table[i].src && !(table[i].src == src && table[i].start == start && table[i].count == count && table[i].type == type))
        i = (i + 1) & (TABLE - 1);
    struct entry *e = &table[i];
    if (!e->src) {
        if (nentries > TABLE / 2) { // full: start over
            flush();
            i = h & (TABLE - 1);
            e = &table[i];
        }
        *e = (struct entry){ .src = src, .start = start, .count = count, .type = type };
        build(dev, e);
    }
    HRESULT hr;
    if (e->vb) {
        IDirect3DDevice8_SetStreamSource(dev, 0, e->vb, stride);
        hr = draw(dev, D3DPT_TRIANGLELIST, 0, e->tris);
        IDirect3DDevice8_SetStreamSource(dev, 0, src, stride);
    } else {
        hr = draw(dev, type, start, count);
    }
    IDirect3DVertexBuffer8_Release(src);
    return hr;
}

void smooth_install(IDirect3DDevice8 *dev)
{
    IDirect3DDevice8Vtbl *vt = dev->lpVtbl;
    patch((void **)&vt->CreateVertexShader, hook_CreateVertexShader, (void **)&real_CreateVertexShader);
    patch((void **)&vt->CreateVertexBuffer, hook_CreateVertexBuffer, (void **)&real_CreateVertexBuffer);
}
