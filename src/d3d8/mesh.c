// Character model replacement. taz-hd\meshes\<fingerprint>.bin replaces a character's whole vertex
// buffer (fingerprint: FNV-1a of the buffer's bytes; tools/meshpack.py writes these). The game draws a
// character as a pass of small batches, each uploading its own few bone matrices, and draws every pass
// in the same order. We skip those draws, keeping each batch's matrices and texture, and at the pass's
// last batch draw the replacement in groups of up to 16 bones, smoothed like any character.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define DIR "taz-hd\\meshes"
#define REPS 16
#define SEEN 1024

#pragma pack(push, 1)
struct head { DWORD magic, nbatches, nbones, ngroups, nverts; UINT64 hash; };
struct batch { DWORD start, count, type; };
struct source { WORD batch, reg; }; // bone i's matrix is register reg of batch's palette
struct group { DWORD first, tris, texbatch, nbones; WORD bones[16]; };
#pragma pack(pop)
// File: head, batch[nbatches] (draw order), source[nbones], group[ngroups], 52-byte vertices[nverts].

struct rep {
    BYTE *file;
    struct head *h;
    struct batch *batches;
    struct source *sources;
    struct group *groups;
    BYTE *verts;
    float (*bones)[12];
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
        if (n < sizeof *r->h || r->h->magic != 0x314d5a54) { free(b); continue; } // "TZM1"
        r->batches = (struct batch *)(r->h + 1);
        r->sources = (struct source *)(r->batches + r->h->nbatches);
        r->groups = (struct group *)(r->sources + r->h->nbones);
        r->verts = (BYTE *)(r->groups + r->h->ngroups);
        if (r->verts + r->h->nverts * 52 != b + n) { free(b); continue; }
        r->bones = calloc(r->h->nbones, sizeof *r->bones);
        r->tex = calloc(r->h->nbatches, sizeof *r->tex);
        nreps++;
        log_line("mesh: %s, %lu vertices in %lu groups for %lu batches", path, r->h->nverts, r->h->ngroups, r->h->nbatches);
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
        smooth_draw(dev, D3DPT_TRIANGLELIST, g->first, g->tris, draw);
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
