// Mesh capture for modelling work: a taz-hd\capture file records the next frame's character draws
// (or the next N frames, for a number N in it) into taz-hd\capture-NNN.bin, one file per frame. Records: 'V' buffer (id, size, bytes) once per buffer, then
// 'D' draw (buffer id, type, start, count, stage-0 texture fingerprint, constants c0-c95).
#include <stdio.h>
#include "proxy.h"

#define TRIGGER "taz-hd\\capture"

static FILE *out;
static void *seen[1024];
static int nseen;

void capture_frame(void)
{
    static int count, left;
    if (out) {
        log_line("capture: done, %d buffers", nseen);
        fclose(out);
        out = NULL;
    }
    FILE *f = left ? NULL : fopen(TRIGGER, "r");
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
