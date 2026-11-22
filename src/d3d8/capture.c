// The test rig's trigger files, read only with tests=1 in the ini (players' games never look for them).
// Mesh capture for modelling work: a taz-hd\capture file records the next frame's character draws
// (or the next N frames, for a number N in it) into taz-hd\capture-NNN.bin, one file per frame.
// A taz-hd\scene file holding a scene number (names at 0x646d9c; add "intro" to see a hub's intro again) sends
// the game there, an empty taz-hd\costume file puts the level's costume on Taz, and taz-hd\complete wins
// levels (below), for tests. Records: 'V' buffer (id, size, bytes) once per buffer, then 'D' draw
// (buffer id, type, start, count, stage-0 texture fingerprint, constants c0-c95).
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include "proxy.h"
#include "game.h"

#define TRIGGER "taz-hd\\capture"

static FILE *out;
static void *seen[1024];
static int nseen;

// Between game frames (quicksave.c): FUN_004a9730 is the game's scene change, as the attract demo uses it.
void capture_scene(void)
{
    if (!settings.tests) return;
    if (GetFileAttributesA("taz-hd\\costume") != INVALID_FILE_ATTRIBUTES) {
        DeleteFileA("taz-hd\\costume");
        void *taz = PLAYER;
        if (taz && SCENE >= 2) {
            ((void(__cdecl *)(void *))0x430160)(taz);
            log_line("capture: costume on (%d)", *(signed char *)(*(BYTE **)((BYTE *)taz + 0x1cc) + 0x10c));
        }
    }
    // taz-hd\complete: scene numbers mark those levels won in the save slot (hub outros load with the hub);
    // empty, it wins the current level the way the game does (FUN_004cd830), which plays its outro.
    FILE *f = fopen("taz-hd\\complete", "r");
    if (f) {
        int n, marked = 0, slot = *(int *)0x6c8eec;
        while (fscanf(f, "%d", &n) == 1)
            if (n >= 0 && n < 0x25 && slot >= 0) *(int *)(0x6c97c0 + slot * 0x13d4 + n * 0xa8) = 1, marked++;
        fclose(f);
        DeleteFileA("taz-hd\\complete");
        void *taz = PLAYER;
        log_line("capture: %d levels marked won%s", marked, !marked && taz ? ", winning this one" : "");
        if (!marked && taz && SCENE >= 2) ((void(__cdecl *)(void *, int))0x4cd830)(taz, 0);
    }
    f = fopen("taz-hd\\scene", "r");
    if (!f) return;
    char word[8] = "";
    int scene, ok = fscanf(f, "%d %7s", &scene, word) >= 1 && scene >= 0 && scene < 0x25 && SCENE >= 2; // in play, not menus
    fclose(f);
    DeleteFileA("taz-hd\\scene"); // first: loading runs game frames, which come back here
    if (ok && !strcmp(word, "intro")) *(BYTE *)(0x6c9860 + *(int *)0x6c8eec * 0x13d4 + scene * 0xa8) &= ~1; // hub intro not seen yet
    if (ok) {
        log_line("capture: going to scene %d", scene);
        ((void(__cdecl *)(void *, int))0x4a9730)(GAME, scene);
    }
}

static void world_frame(void);

void capture_frame(void)
{
    static int count, left;

    FILE *d = settings.tests ? fopen("taz-hd\\display", "r") : NULL; // "W H V [AA]": live size (0 0 keeps it), vsync and samples, for reset tests
    if (d) {
        UINT w = 0, h = 0, v = settings.vsync, aa = settings.antialiasing;
        fscanf(d, "%u %u %u %u", &w, &h, &v, &aa);
        settings.antialiasing = aa;
        fclose(d);
        DeleteFileA("taz-hd\\display");
        settings.vsync = v;
        display_change(w, h, v);
    }
    world_frame();
    if (out) {
        log_line("capture: done, %d buffers", nseen);
        fclose(out);
        out = NULL;
    }
    FILE *f = left || !settings.tests ? NULL : fopen(TRIGGER, "r");
    if (f) {
        if (fscanf(f, "%d", &left) != 1 || left < 1) left = 1;
        fclose(f);
        DeleteFileA(TRIGGER);
    }
    if (!left) return;
    left--;
    char path[MAX_PATH];
    snprintf(path, sizeof path, "taz-hd\\capture-%03d.bin", ++count);
    out = fopen(path, "wb");
    nseen = 0;
}

void capture_draw(IDirect3DDevice8 *dev, IDirect3DVertexBuffer8 *vb, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    if (!out) return;
    int known = 0;
    for (int i = 0; i < nseen; i++) known |= seen[i] == vb;
    if (!known && nseen < 1024) {
        D3DVERTEXBUFFER_DESC d;
        BYTE *p;
        if (SUCCEEDED(IDirect3DVertexBuffer8_GetDesc(vb, &d)) && SUCCEEDED(IDirect3DVertexBuffer8_Lock(vb, 0, 0, &p, D3DLOCK_READONLY))) {
            DWORD head[3] = { 'V', (DWORD)(UINT_PTR)vb, d.Size };
            fwrite(head, sizeof head, 1, out);
            fwrite(p, d.Size, 1, out);
            IDirect3DVertexBuffer8_Unlock(vb);
            seen[nseen++] = vb;
        }
    }
    float c[96][4];
    IDirect3DDevice8_GetVertexShaderConstant(dev, 0, c, 96);
    UINT64 tex = textures_bound_hash(0);
    DWORD head[5] = { 'D', (DWORD)(UINT_PTR)vb, type, start, count };
    fwrite(head, sizeof head, 1, out);
    fwrite(&tex, sizeof tex, 1, out);
    fwrite(c, sizeof c, 1, out);
}

// World capture: a taz-hd\world file ("N S": N frames, every S-th; default 1 1) records the 3D draws to
// the back buffer into taz-hd\world-NNN.bin, with everything needed to draw them again. The first frame
// is the hero frame (also saved as a screenshot; vertex-shader draws only there, with c0-c95); later
// frames add only draws not seen yet (same vertices, textures and states within 64 units), for sweeps.
// Records: 'H' (state ids below), 'F' (frame, presents), 'W' (struct world, c0-c95 for shader draws,
// vertices, u32 indices relative to the first vertex).
static const DWORD rs_ids[] = { D3DRS_ZENABLE, D3DRS_FILLMODE, D3DRS_SHADEMODE, D3DRS_ZWRITEENABLE, D3DRS_ALPHATESTENABLE,
    D3DRS_SRCBLEND, D3DRS_DESTBLEND, D3DRS_CULLMODE, D3DRS_ZFUNC, D3DRS_ALPHAREF, D3DRS_ALPHAFUNC, D3DRS_ALPHABLENDENABLE,
    D3DRS_FOGENABLE, D3DRS_FOGCOLOR, D3DRS_FOGTABLEMODE, D3DRS_FOGSTART, D3DRS_FOGEND, D3DRS_FOGDENSITY, D3DRS_ZBIAS,
    D3DRS_TEXTUREFACTOR, D3DRS_LIGHTING, D3DRS_FOGVERTEXMODE, D3DRS_COLORVERTEX, D3DRS_BLENDOP };
static const DWORD tss_ids[] = { D3DTSS_COLOROP, D3DTSS_COLORARG1, D3DTSS_COLORARG2, D3DTSS_ALPHAOP, D3DTSS_ALPHAARG1,
    D3DTSS_ALPHAARG2, D3DTSS_TEXCOORDINDEX, D3DTSS_ADDRESSU, D3DTSS_ADDRESSV, D3DTSS_MAGFILTER, D3DTSS_TEXTURETRANSFORMFLAGS,
    D3DTSS_COLORARG0, D3DTSS_ALPHAARG0, D3DTSS_RESULTARG };
#define NRS (sizeof rs_ids / sizeof *rs_ids)
#define NTSS (sizeof tss_ids / sizeof *tss_ids)
struct world {
    DWORD magic, frame, api, type, count, shader, stride, nverts, nidx, vb, first, bound; // bound: bit s = stage s has a texture (fingerprint 0 if unknown)
    UINT64 tex[2];
    D3DMATRIX world, view, proj, texm[2];
    D3DVIEWPORT8 vp;
    DWORD rs[NRS], tss[3][NTSS];
};
#define KEYS (1 << 18)
static UINT64 keys[KEYS];
static FILE *wout;
static int wframe, wleft, wstep, wtick, wdraws;
int capture_world_on;

static UINT64 fnv(UINT64 h, const void *p, size_t n)
{
    for (const BYTE *b = p; n--; b++) h = (h ^ *b) * 0x100000001b3ull;
    return h;
}

static void world_frame(void)
{
    capture_world_on = 0;
    if (wout && !wleft) {
        log_line("capture: world done, %d frames, %d draws", wframe, wdraws);
        fclose(wout);
        wout = NULL;
    }
    if (!wout) {
        static int files;
        FILE *f = settings.tests ? fopen("taz-hd\\world", "r") : NULL;
        if (!f) return;
        wleft = wstep = 1;
        fscanf(f, "%d %d", &wleft, &wstep);
        fclose(f);
        DeleteFileA("taz-hd\\world");
        if (wleft < 1) wleft = 1;
        if (wstep < 1) wstep = 1;
        char path[MAX_PATH];
        snprintf(path, sizeof path, "taz-hd\\world-%03d.bin", ++files);
        if (!(wout = fopen(path, "wb"))) return;
        DWORD head[3] = { 'H', NRS, NTSS };
        fwrite(head, sizeof head, 1, wout);
        fwrite(rs_ids, sizeof rs_ids, 1, wout);
        fwrite(tss_ids, sizeof tss_ids, 1, wout);
        memset(keys, 0, sizeof keys);
        wframe = wtick = wdraws = 0;
        if ((f = fopen("taz-hd\\shot", "w"))) fclose(f); // screenshot.c saves the next frame: the hero frame
    } else if (++wtick % wstep) {
        return;
    }
    wleft--;
    DWORD head[3] = { 'F', ++wframe, presents };
    fwrite(head, sizeof head, 1, wout);
    capture_world_on = 1;
}

static UINT vertices_for(D3DPRIMITIVETYPE t, UINT n)
{
    return t == D3DPT_TRIANGLELIST ? 3 * n : t == D3DPT_LINELIST ? 2 * n : t == D3DPT_LINESTRIP ? n + 1 : t == D3DPT_POINTLIST ? n : n + 2;
}

void capture_world(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT count, UINT first, UINT nverts, UINT start_index,
                   const void *data, UINT stride, const void *idx, D3DFORMAT fmt)
{
    struct world w;
    memset(&w, 0, sizeof w);
    w.magic = 'W', w.frame = wframe, w.api = api, w.type = type, w.count = count;
    IDirect3DSurface8 *rt = NULL, *bb = NULL;
    IDirect3DDevice8_GetRenderTarget(dev, &rt);
    IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    if (rt) IDirect3DSurface8_Release(rt);
    if (bb) IDirect3DSurface8_Release(bb);
    IDirect3DDevice8_GetVertexShader(dev, &w.shader);
    int vs = IS_VERTEX_SHADER(w.shader) != 0;
    if (rt != bb || (vs && wframe > 1) || (!vs && (w.shader & D3DFVF_POSITION_MASK) == D3DFVF_XYZRHW)) return;

    IDirect3DVertexBuffer8 *vb = NULL;
    IDirect3DIndexBuffer8 *ib = NULL;
    UINT base = 0, n = vertices_for(type, count), isize = fmt == D3DFMT_INDEX32 ? 4 : 2;
    const BYTE *v = data, *ix = idx;
    if (api < 2) {
        D3DVERTEXBUFFER_DESC d;
        if (FAILED(IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &stride)) || !vb) return;
        if (api == 1 && (FAILED(IDirect3DDevice8_GetIndices(dev, &ib, &base)) || !ib)) goto done;
        UINT at = api ? base + first : first;
        w.vb = (DWORD)(UINT_PTR)vb;
        if (FAILED(IDirect3DVertexBuffer8_GetDesc(vb, &d)) || (at + (api ? nverts : n)) * stride > d.Size
            || FAILED(IDirect3DVertexBuffer8_Lock(vb, at * stride, (api ? nverts : n) * stride, (BYTE **)&v, D3DLOCK_READONLY))) {
            v = NULL;
            goto done;
        }
        if (ib) {
            D3DINDEXBUFFER_DESC id;
            IDirect3DIndexBuffer8_GetDesc(ib, &id);
            isize = id.Format == D3DFMT_INDEX32 ? 4 : 2;
            if ((start_index + n) * isize > id.Size || FAILED(IDirect3DIndexBuffer8_Lock(ib, start_index * isize, n * isize, (BYTE **)&ix, D3DLOCK_READONLY))) {
                ix = NULL;
                goto done;
            }
        }
    } else if (api == 3) {
        v += first * stride;
    }
    w.first = first;
    w.stride = stride;
    w.nverts = api & 1 ? nverts : n;
    w.nidx = api & 1 ? n : 0;
    w.bound = (textures_bound(0) != NULL) | (textures_bound(1) != NULL) << 1;
    w.tex[0] = textures_bound_hash(0);
    w.tex[1] = textures_bound_hash(1);
    IDirect3DDevice8_GetTransform(dev, D3DTS_WORLD, &w.world);
    IDirect3DDevice8_GetTransform(dev, D3DTS_VIEW, &w.view);
    IDirect3DDevice8_GetTransform(dev, D3DTS_PROJECTION, &w.proj);
    IDirect3DDevice8_GetTransform(dev, D3DTS_TEXTURE0, &w.texm[0]);
    IDirect3DDevice8_GetTransform(dev, D3DTS_TEXTURE1, &w.texm[1]);
    IDirect3DDevice8_GetViewport(dev, &w.vp);
    for (UINT i = 0; i < NRS; i++) IDirect3DDevice8_GetRenderState(dev, rs_ids[i], &w.rs[i]);
    for (UINT s = 0; s < 3; s++)
        for (UINT i = 0; i < NTSS; i++) IDirect3DDevice8_GetTextureStageState(dev, s, tss_ids[i], &w.tss[s][i]);
    UINT32 *ind = w.nidx ? malloc(w.nidx * 4) : NULL;
    for (UINT i = 0; ind && i < w.nidx; i++) ind[i] = (isize == 4 ? ((const UINT32 *)ix)[i] : ((const WORD *)ix)[i]) - first;
    // Same vertices, textures and states near the same place: animated and scrolling things count once.
    UINT64 k = fnv(0xcbf29ce484222325ull, &w.api, offsetof(struct world, world) - offsetof(struct world, api));
    k = fnv(k, &w.vp, sizeof w - offsetof(struct world, vp));
    k = fnv(k, v, (size_t)w.nverts * stride);
    if (ind) k = fnv(k, ind, w.nidx * 4);
    int cell[3] = { (int)(w.world._41 / 64), (int)(w.world._42 / 64), (int)(w.world._43 / 64) };
    k = fnv(k, cell, sizeof cell) | 1;
    UINT h = (UINT)k & (KEYS - 1);
    while (keys[h] && keys[h] != k) h = (h + 1) & (KEYS - 1);
    if (!keys[h] || wframe == 1) {
        keys[h] = k;
        wdraws++;
        fwrite(&w, sizeof w, 1, wout);
        if (vs) {
            float c[96][4];
            IDirect3DDevice8_GetVertexShaderConstant(dev, 0, c, 96);
            fwrite(c, sizeof c, 1, wout);
        }
        fwrite(v, stride, w.nverts, wout);
        if (ind) fwrite(ind, 4, w.nidx, wout);
    }
    free(ind);
done:
    if (ix && ib) IDirect3DIndexBuffer8_Unlock(ib);
    if (v && vb) IDirect3DVertexBuffer8_Unlock(vb);
    if (ib) IDirect3DIndexBuffer8_Release(ib);
    if (vb) IDirect3DVertexBuffer8_Release(vb);
}
