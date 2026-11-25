// Static world merge (look level 2+). The game draws the hub's world as ~7,500 tiny DrawPrimitive calls
// from one buffer, already in texture order. Each one seen here becomes a piece: its vertices copied once
// into one merged buffer, its triangles a range of one index buffer. Later frames only look the piece up
// and mark it issued; the first draw that isn't a piece flushes what was issued, one indexed draw per run
// of same-texture pieces. So the game still decides what is drawn, and nothing changes order against the
// draws around it. Pieces are keyed by buffer, range, texture and render state, and dropped when any of
// those stops being true (buffer written or recreated, texture released, device reset, scene change).
#define COBJMACROS
#include <stdlib.h>
#include <string.h>
#include "proxy.h"
#include "hd.h"

#define WORLD_FVF 0x152 // position, normal, colour, one uv
#define STRIDE 36
#define SLOTS (1 << 17)
#define MAX_PIECES (SLOTS / 2)
#define NSTATE 9
#define NSAMPLER 4 // the game picks wrap or clamp per draw, even for one texture
#define NKEY (NSTATE + NSAMPLER)

static const DWORD tracked[NSTATE] = { D3DRS_ZENABLE, D3DRS_ZWRITEENABLE, D3DRS_ZFUNC, D3DRS_CULLMODE, D3DRS_ALPHATESTENABLE,
                                       D3DRS_ALPHAREF, D3DRS_ALPHAFUNC, D3DRS_FOGENABLE, D3DRS_ZBIAS };
static const DWORD samplers[NSAMPLER] = { D3DTSS_ADDRESSU, D3DTSS_ADDRESSV, D3DTSS_MAGFILTER, D3DTSS_MINFILTER };

struct piece { IDirect3DVertexBuffer8 *vb; IDirect3DBaseTexture8 *tex; UINT start, count, type, first, tris, rs_id, batch; DWORD frame; };
struct batch { IDirect3DBaseTexture8 *tex; UINT64 hash; UINT p0, n, issued, rs_id; };

static struct piece *pieces;
static int *slots;
static struct batch *batches;
static BYTE *verts;
static UINT *idx;
static UINT npieces, nbatches, nverts, nidx, room_v, room_i, uploaded, gpu_v, gpu_i, issued, last_new;
static DWORD (*rs_sets)[NKEY];
static UINT nrs;
static DWORD frame = 1;
static IDirect3DVertexBuffer8 *vb_gpu;
static IDirect3DIndexBuffer8 *ib_gpu;

// What the device has bound, kept by the hooks so a draw costs no Get calls.
static int dirty = 1, ok_state, on_bb = 1, world_id, flushing;
static DWORD cur_blend, cur_op0, cur_arg1, cur_op1, cur_tt;
static IDirect3DDevice8 *device;
static IDirect3DVertexBuffer8 *cur_vb;
static UINT cur_stride;
static DWORD cur_shader, cur_rs[NKEY];
static UINT cur_rs_id;

static IDirect3DVertexBuffer8 *banned[32], *sources[64];
static UINT nbanned, nsources;

int merge_stat_pieces, merge_stat_draws;

static HRESULT (WINAPI *real_SetRenderState)(IDirect3DDevice8 *, D3DRENDERSTATETYPE, DWORD);
static HRESULT (WINAPI *real_SetTransform)(IDirect3DDevice8 *, D3DTRANSFORMSTATETYPE, CONST D3DMATRIX *);
static HRESULT (WINAPI *real_SetViewport)(IDirect3DDevice8 *, CONST D3DVIEWPORT8 *);
static HRESULT (WINAPI *real_SetRenderTarget)(IDirect3DDevice8 *, IDirect3DSurface8 *, IDirect3DSurface8 *);
static HRESULT (WINAPI *real_GetRenderTarget)(IDirect3DDevice8 *, IDirect3DSurface8 **);
static HRESULT (WINAPI *real_SetVertexShader)(IDirect3DDevice8 *, DWORD);
static HRESULT (WINAPI *real_SetStreamSource)(IDirect3DDevice8 *, UINT, IDirect3DVertexBuffer8 *, UINT);
static HRESULT (WINAPI *real_Clear)(IDirect3DDevice8 *, DWORD, CONST D3DRECT *, DWORD, D3DCOLOR, float, DWORD);
static HRESULT (WINAPI *real_VBLock)(IDirect3DVertexBuffer8 *, UINT, UINT, BYTE **, DWORD);

int merge_on_backbuffer(void) { return on_bb; }
void merge_state_changed(void) { dirty = 1; }

// From the texture stage hook: only the states that decide whether a draw can merge.
void merge_stage_state(DWORD stage, DWORD type, DWORD value)
{
    if (stage == 0 && ((type == D3DTSS_COLOROP && value != cur_op0) || (type == D3DTSS_COLORARG1 && value != cur_arg1)
                       || (type == D3DTSS_TEXTURETRANSFORMFLAGS && value != cur_tt))) dirty = 1;
    if (stage == 1 && type == D3DTSS_COLOROP && value != cur_op1) dirty = 1;
    for (int i = 0; !stage && i < NSAMPLER; i++)
        if (samplers[i] == type && cur_rs[NSTATE + i] != value) dirty = 1;
}

void merge_reset(void)
{
    if (slots) memset(slots, 0, SLOTS * sizeof *slots);
    npieces = nbatches = nverts = nidx = uploaded = issued = nrs = nsources = 0;
    dirty = 1;
}

// Before a device Reset; the buffers are managed but nothing here should outlive a device change.
void merge_device_reset(void)
{
    merge_reset();
    nbanned = 0;
    on_bb = 1;
    if (vb_gpu) IDirect3DVertexBuffer8_Release(vb_gpu), vb_gpu = NULL;
    if (ib_gpu) IDirect3DIndexBuffer8_Release(ib_gpu), ib_gpu = NULL;
    gpu_v = gpu_i = 0;
}

static void refresh(IDirect3DDevice8 *dev)
{
    D3DMATRIX w;
    dirty = 0;
    IDirect3DDevice8_GetVertexShader(dev, &cur_shader);
    IDirect3DVertexBuffer8 *vb = NULL;
    IDirect3DDevice8_GetStreamSource(dev, 0, &vb, &cur_stride);
    if (vb) IDirect3DVertexBuffer8_Release(vb); // the game's binding keeps it alive
    cur_vb = vb;
    IDirect3DDevice8_GetTransform(dev, D3DTS_WORLD, &w);
    world_id = w._11 == 1 && w._22 == 1 && w._33 == 1 && !w._41 && !w._42 && !w._43 && !w._12 && !w._13 && !w._21 && !w._23 && !w._31 && !w._32;
    IDirect3DDevice8_GetRenderState(dev, D3DRS_ALPHABLENDENABLE, &cur_blend);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLOROP, &cur_op0);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_COLORARG1, &cur_arg1);
    IDirect3DDevice8_GetTextureStageState(dev, 1, D3DTSS_COLOROP, &cur_op1);
    IDirect3DDevice8_GetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, &cur_tt);
    for (int i = 0; i < NSTATE; i++) IDirect3DDevice8_GetRenderState(dev, tracked[i], &cur_rs[i]);
    for (int i = 0; i < NSAMPLER; i++) IDirect3DDevice8_GetTextureStageState(dev, 0, samplers[i], &cur_rs[NSTATE + i]);
    ok_state = !cur_blend && cur_op0 == D3DTOP_MODULATE2X && cur_arg1 == D3DTA_TEXTURE && cur_op1 == D3DTOP_DISABLE && !cur_tt && cur_rs[0] && cur_rs[1];
    cur_rs_id = (UINT)-1;
}

static UINT rs_id(void)
{
    if (cur_rs_id != (UINT)-1) return cur_rs_id;
    for (UINT i = 0; i < nrs; i++)
        if (!memcmp(rs_sets[i], cur_rs, sizeof cur_rs)) return cur_rs_id = i;
    DWORD (*grown)[NKEY] = realloc(rs_sets, (nrs + 1) * sizeof *rs_sets);
    if (!grown) return 0;
    rs_sets = grown;
    memcpy(rs_sets[nrs], cur_rs, sizeof cur_rs);
    return cur_rs_id = nrs++;
}

static UINT slot_of(IDirect3DVertexBuffer8 *vb, IDirect3DBaseTexture8 *tex, UINT start, UINT count, UINT type, UINT rs)
{
    UINT h = ((UINT)(UINT_PTR)vb >> 4) * 2654435761u ^ ((UINT)(UINT_PTR)tex >> 4) * 40503u ^ start * 977u ^ count * 16777619u ^ type ^ rs << 8;
    h &= SLOTS - 1;
    while (slots[h]) {
        const struct piece *p = &pieces[slots[h] - 1];
        if (p->vb == vb && p->tex == tex && p->start == start && p->count == count && p->type == type && p->rs_id == rs) break;
        h = (h + 1) & (SLOTS - 1);
    }
    return h;
}

static int known_vb(IDirect3DVertexBuffer8 *vb)
{
    for (UINT i = 0; i < nsources; i++)
        if (sources[i] == vb) return 1;
    return 0;
}

// Copies the draw's vertices and writes its triangles as a list, keeping each triangle's winding.
static int add_piece(UINT slot, IDirect3DVertexBuffer8 *vb, IDirect3DBaseTexture8 *tex, UINT64 hash, UINT type, UINT start, UINT count, UINT rs)
{
    UINT nv = type == D3DPT_TRIANGLESTRIP ? count + 2 : count * 3;
    BYTE *src;
    if (npieces >= MAX_PIECES || (!known_vb(vb) && nsources == 64) || FAILED(real_VBLock(vb, start * STRIDE, nv * STRIDE, &src, D3DLOCK_READONLY))) return 0;
    if (!known_vb(vb)) sources[nsources++] = vb;
    if (nverts + nv > room_v) {
        UINT room = (nverts + nv) * 2;
        BYTE *grown = realloc(verts, room * STRIDE);
        if (!grown) return IDirect3DVertexBuffer8_Unlock(vb), 0;
        verts = grown, room_v = room;
    }
    if (nidx + count * 3 > room_i) {
        UINT room = (nidx + count * 3) * 2, *grown = realloc(idx, room * sizeof *idx);
        if (!grown) return IDirect3DVertexBuffer8_Unlock(vb), 0;
        idx = grown, room_i = room;
    }
    memcpy(verts + nverts * STRIDE, src, nv * STRIDE);
    IDirect3DVertexBuffer8_Unlock(vb);
    struct piece *p = &pieces[npieces];
    *p = (struct piece){ vb, tex, start, count, type, nidx, 0, rs, 0, 0 };
    for (UINT t = 0; t < count; t++) {
        UINT a = type == D3DPT_TRIANGLESTRIP ? t : t * 3, b = a + 1, c = a + 2;
        if (type == D3DPT_TRIANGLESTRIP && (t & 1)) { UINT x = a; a = b; b = x; }
        if (type == D3DPT_TRIANGLESTRIP && (!memcmp(verts + (nverts + a) * STRIDE, verts + (nverts + b) * STRIDE, 12) ||
                                            !memcmp(verts + (nverts + b) * STRIDE, verts + (nverts + c) * STRIDE, 12) ||
                                            !memcmp(verts + (nverts + a) * STRIDE, verts + (nverts + c) * STRIDE, 12))) continue;
        idx[nidx++] = nverts + a, idx[nidx++] = nverts + b, idx[nidx++] = nverts + c, p->tris++;
    }
    nverts += nv;
    if (!nbatches || batches[nbatches - 1].tex != tex || batches[nbatches - 1].rs_id != rs) {
        struct batch *grown = realloc(batches, (nbatches + 1) * sizeof *batches);
        if (!grown) return 0;
        batches = grown;
        batches[nbatches++] = (struct batch){ tex, hash, npieces, 0, 0, rs };
    }
    p->batch = nbatches - 1;
    batches[p->batch].n++;
    slots[slot] = ++npieces;
    last_new = presents;
    return 1;
}

static int upload(IDirect3DDevice8 *dev)
{
    BYTE *p;
    if (nverts > gpu_v || !vb_gpu) {
        if (vb_gpu) IDirect3DVertexBuffer8_Release(vb_gpu), vb_gpu = NULL;
        gpu_v = nverts + nverts / 4 + 1024;
        if (FAILED(IDirect3DDevice8_CreateVertexBuffer(dev, gpu_v * STRIDE, D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &vb_gpu))) return vb_gpu = NULL, gpu_v = 0, 0;
    }
    if (nidx > gpu_i || !ib_gpu) {
        if (ib_gpu) IDirect3DIndexBuffer8_Release(ib_gpu), ib_gpu = NULL;
        gpu_i = nidx + nidx / 4 + 4096;
        if (FAILED(IDirect3DDevice8_CreateIndexBuffer(dev, gpu_i * 4, D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_MANAGED, &ib_gpu))) return ib_gpu = NULL, gpu_i = 0, 0;
    }
    if (FAILED(real_VBLock(vb_gpu, 0, nverts * STRIDE, &p, 0))) return 0;
    memcpy(p, verts, nverts * STRIDE);
    IDirect3DVertexBuffer8_Unlock(vb_gpu);
    if (FAILED(IDirect3DIndexBuffer8_Lock(ib_gpu, 0, nidx * 4, &p, 0))) return 0;
    memcpy(p, idx, nidx * 4);
    IDirect3DIndexBuffer8_Unlock(ib_gpu);
    uploaded = npieces;
    log_line("merge: %u pieces, %u textures runs, %u vertices, %u triangles", npieces, nbatches, nverts, nidx / 3);
    return 1;
}

void merge_flush(IDirect3DDevice8 *dev)
{
    if (!issued || flushing) return;
    flushing = 1;
    look_merge_begin(dev, vb_gpu, ib_gpu);
    UINT applied = (UINT)-1;
    for (UINT b = 0; b < nbatches; b++) {
        struct batch *k = &batches[b];
        if (!k->issued) continue;
        look_merge_texture(dev, k->tex, k->hash);
        if (k->rs_id != applied) {
            const DWORD *set = rs_sets[applied = k->rs_id];
            for (int i = 0; i < NSTATE; i++) IDirect3DDevice8_SetRenderState(dev, tracked[i], set[i]);
            for (int i = 0; i < NSAMPLER; i++) IDirect3DDevice8_SetTextureStageState(dev, 0, samplers[i], set[NSTATE + i]);
        }
        UINT end = k->p0 + k->n, first = 0, tris = 0;
        for (UINT i = k->p0; i <= end; i++) {
            const struct piece *p = i < end ? &pieces[i] : NULL;
            if (p && p->frame == frame && i < uploaded && (!tris || p->first == first + tris * 3)) {
                if (!tris) first = p->first;
                tris += p->tris;
                continue;
            }
            if (tris) look_merge_draw(dev, nverts, first, tris), merge_stat_draws++;
            tris = 0;
            if (p && p->frame == frame && i < uploaded) first = p->first, tris = p->tris;
        }
        k->issued = 0;
    }
    look_merge_end(dev);
    issued = 0;
    frame++;
    flushing = 0;
}

// One game draw (before it happens). Returns 1 when the merge has it and the game's call should be skipped.
int merge_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count)
{
    if (dirty) refresh(dev);
    IDirect3DBaseTexture8 *tex = textures_bound(0);
    if (api || !ok_state || !on_bb || !world_id || cur_shader != WORLD_FVF || cur_stride != STRIDE || !cur_vb || !tex || !count
        || (type != D3DPT_TRIANGLESTRIP && type != D3DPT_TRIANGLELIST) || textures_scrolling(tex)) {
        merge_flush(dev);
        return 0;
    }
    for (UINT i = 0; i < nbanned; i++)
        if (banned[i] == cur_vb) return merge_flush(dev), 0;
    if (!slots && !(slots = calloc(SLOTS, sizeof *slots))) return 0;
    if (!pieces && !(pieces = malloc(MAX_PIECES * sizeof *pieces))) return 0;
    UINT rs = rs_id(), h = slot_of(cur_vb, tex, start, count, type, rs);
    if (slots[h]) {
        struct piece *p = &pieces[slots[h] - 1];
        if ((UINT)slots[h] > uploaded) return merge_flush(dev), 0;
        if (p->frame == frame) merge_flush(dev); // issued twice in one run: a second pass, keep the order
        p->frame = frame;
        batches[p->batch].issued++;
        issued++;
        merge_stat_pieces++;
        return 1;
    }
    merge_flush(dev);
    if (cutscene_playing() && textures_from_cutscene(tex)) return 0; // its set comes and goes with its pack
    UINT64 hash = textures_bound_hash(0);
    if (hash && !look_hidden(hash)) add_piece(h, cur_vb, tex, hash, type, start, count, rs);
    return 0;
}

int merge_ready(void) { return npieces && uploaded == npieces; }

int merge_is_2d(IDirect3DDevice8 *dev)
{
    if (dirty) refresh(dev);
    return !cur_rs[0] || cur_rs[2] == D3DCMP_ALWAYS;
}

// Every uploaded run with its texture, for the depth and shadow passes. Binds the merged buffers.
void merge_each(IDirect3DDevice8 *dev, void (*batch)(IDirect3DDevice8 *, IDirect3DBaseTexture8 *, UINT, UINT, UINT))
{
    if (!uploaded || !vb_gpu || !ib_gpu) return;
    hd_merge_buffers(d3d9_device(dev), d3d9_vb(vb_gpu), d3d9_ib(ib_gpu));
    for (UINT b = 0; b < nbatches; b++) {
        const struct batch *k = &batches[b];
        UINT end = k->p0 + k->n < uploaded ? k->p0 + k->n : uploaded, tris = 0;
        for (UINT i = k->p0; i < end; i++) tris += pieces[i].tris;
        if (tris) batch(dev, k->tex, nverts, pieces[k->p0].first, tris);
    }
}

// At Present: the frame's last flush, and the merged buffers once new pieces have stopped appearing.
void merge_frame(IDirect3DDevice8 *dev)
{
    merge_flush(dev);
    frame++;
    if (npieces > uploaded && presents - last_new >= 2) upload(dev);
}

void merge_texture_gone(IDirect3DBaseTexture8 *t)
{
    for (UINT b = 0; b < nbatches; b++)
        if (batches[b].tex == t) { merge_flush(device), merge_reset(); return; }
}

// A new buffer at an address we hold pieces for: the old one is gone.
void merge_vb_created(IDirect3DVertexBuffer8 *vb)
{
    for (UINT i = 0; i < nbanned; i++)
        if (banned[i] == vb) banned[i] = banned[--nbanned];
    if (npieces && known_vb(vb)) merge_reset();
}

static HRESULT WINAPI hook_VBLock(IDirect3DVertexBuffer8 *vb, UINT off, UINT size, BYTE **out, DWORD flags)
{
    if (!(flags & D3DLOCK_READONLY) && npieces && vb != vb_gpu && known_vb(vb)) { // rewritten after we copied it: not static
        merge_flush(device);
        if (nbanned < 32) banned[nbanned++] = vb;
        merge_reset();
    }
    return real_VBLock(vb, off, size, out, flags);
}

static HRESULT WINAPI hook_SetRenderState(IDirect3DDevice8 *dev, D3DRENDERSTATETYPE state, DWORD value)
{
    if (state == D3DRS_ALPHABLENDENABLE && value != cur_blend) dirty = 1;
    for (int i = 0; i < NSTATE; i++)
        if (tracked[i] == (DWORD)state && cur_rs[i] != value) dirty = 1;
    return real_SetRenderState(dev, state, value);
}

static HRESULT WINAPI hook_SetTransform(IDirect3DDevice8 *dev, D3DTRANSFORMSTATETYPE t, CONST D3DMATRIX *m)
{
    if (t == D3DTS_VIEW || t == D3DTS_PROJECTION) merge_flush(dev), hd_invalidate();
    if (t == D3DTS_WORLD)
        world_id = m->_11 == 1 && m->_22 == 1 && m->_33 == 1 && !m->_41 && !m->_42 && !m->_43 && !m->_12 && !m->_13 && !m->_21 && !m->_23 && !m->_31 && !m->_32;
    D3DMATRIX tmp;
    return real_SetTransform(dev, t, look_camera(t, m, &tmp));
}

static HRESULT WINAPI hook_SetViewport(IDirect3DDevice8 *dev, CONST D3DVIEWPORT8 *v)
{
    merge_flush(dev);
    return real_SetViewport(dev, v);
}

static HRESULT WINAPI hook_SetRenderTarget(IDirect3DDevice8 *dev, IDirect3DSurface8 *rt, IDirect3DSurface8 *ds)
{
    merge_flush(dev);
    // A map preview is drawn like the screen: its whole 3D pass, finished when the game leaves it.
    static int on_preview;
    IDirect3DSurface8 *preview = preview_surface();
    if (on_preview && rt != preview) look_preview_end(dev);
    HRESULT hr = real_SetRenderTarget(dev, rt, ds);
    if (SUCCEEDED(hr) && rt) {
        IDirect3DSurface8 *bb = NULL;
        IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
        on_preview = rt == preview;
        on_bb = rt == bb || on_preview;
        if (bb) IDirect3DSurface8_Release(bb);
        look_target_set(dev, on_bb);
    }
    return hr;
}

// While the 3D pass is redirected the game must keep seeing the back buffer as its target.
static HRESULT WINAPI hook_GetRenderTarget(IDirect3DDevice8 *dev, IDirect3DSurface8 **out)
{
    if (look_redirected() && out) return IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, out);
    return real_GetRenderTarget(dev, out);
}

static HRESULT WINAPI hook_SetVertexShader(IDirect3DDevice8 *dev, DWORD h)
{
    cur_shader = h;
    return real_SetVertexShader(dev, h);
}

static HRESULT WINAPI hook_SetStreamSource(IDirect3DDevice8 *dev, UINT n, IDirect3DVertexBuffer8 *vb, UINT stride)
{
    if (!n) cur_vb = vb, cur_stride = stride;
    return real_SetStreamSource(dev, n, vb, stride);
}

static HRESULT WINAPI hook_Clear(IDirect3DDevice8 *dev, DWORD n, CONST D3DRECT *r, DWORD flags, D3DCOLOR c, float z, DWORD s)
{
    merge_flush(dev);
    return real_Clear(dev, n, r, flags, c, z, s);
}

void merge_install(IDirect3DDevice8 *dev)
{
    IDirect3DDevice8Vtbl *vt = dev->lpVtbl;
    device = dev;
    patch((void **)&vt->SetRenderState, hook_SetRenderState, (void **)&real_SetRenderState);
    patch((void **)&vt->SetTransform, hook_SetTransform, (void **)&real_SetTransform);
    patch((void **)&vt->SetViewport, hook_SetViewport, (void **)&real_SetViewport);
    patch((void **)&vt->SetRenderTarget, hook_SetRenderTarget, (void **)&real_SetRenderTarget);
    patch((void **)&vt->GetRenderTarget, hook_GetRenderTarget, (void **)&real_GetRenderTarget);
    patch((void **)&vt->SetVertexShader, hook_SetVertexShader, (void **)&real_SetVertexShader);
    patch((void **)&vt->SetStreamSource, hook_SetStreamSource, (void **)&real_SetStreamSource);
    patch((void **)&vt->Clear, hook_Clear, (void **)&real_Clear);
    IDirect3DVertexBuffer8 *probe;
    if (SUCCEEDED(IDirect3DDevice8_CreateVertexBuffer(dev, 64, 0, 0, D3DPOOL_MANAGED, &probe))) {
        patch((void **)&probe->lpVtbl->Lock, hook_VBLock, (void **)&real_VBLock);
        IDirect3DVertexBuffer8_Release(probe);
    }
}
