// Intro videos: the game copies each 640x480 Bink frame into the middle of the back buffer. We take
// the copy into our own buffer instead and draw it at Present, scaled to the screen height.
#define COBJMACROS
#include <stdlib.h>
#include "proxy.h"

#define BINKCOPY_SCALE 0x70000000 // the game's 2x and interlace modes; we always copy 1:1

static int (WINAPI *real_CopyToBuffer)(void *, void *, int, UINT, UINT, UINT, UINT);
static void (WINAPI *real_Close)(void *);
static BYTE *frame;
static UINT frame_w, frame_h, fresh;
static int playing;
static IDirect3DTexture8 *tex;

static int WINAPI hook_CopyToBuffer(void *bink, void *dest, int pitch, UINT height, UINT x, UINT y, UINT flags)
{
    UINT w = ((UINT *)bink)[0], h = ((UINT *)bink)[1];
    if (!frame || w != frame_w || h != frame_h) {
        free(frame);
        frame = calloc(w * h, 4);
        frame_w = w;
        frame_h = h;
    }
    if (!playing) log_line("video: %ux%u frames, copy flags 0x%x", w, h, flags);
    if (!frame || (flags & 0xf) != 3) return real_CopyToBuffer(bink, dest, pitch, height, x, y, flags); // 3 = 32-bit
    int skipped = real_CopyToBuffer(bink, frame, w * 4, h, 0, 0, flags & ~BINKCOPY_SCALE);
    playing = fresh = 1;
    return skipped;
}

static void WINAPI hook_Close(void *bink)
{
    playing = 0;
    real_Close(bink);
}

void video_frame(IDirect3DDevice8 *dev)
{
    if (!playing) {
        if (tex) IDirect3DTexture8_Release(tex), tex = NULL;
        return;
    }
    if (!tex && FAILED(IDirect3DDevice8_CreateTexture(dev, frame_w, frame_h, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_MANAGED, &tex))) {
        log_line("video: could not create a %ux%u texture", frame_w, frame_h);
        playing = 0;
        return;
    }
    D3DLOCKED_RECT r;
    if (fresh && SUCCEEDED(IDirect3DTexture8_LockRect(tex, 0, &r, NULL, 0))) {
        for (UINT row = 0; row < frame_h; row++) memcpy((BYTE *)r.pBits + row * r.Pitch, frame + row * frame_w * 4, frame_w * 4);
        IDirect3DTexture8_UnlockRect(tex, 0);
        fresh = 0;
    }
    IDirect3DSurface8 *bb;
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    IDirect3DSurface8_Release(bb);
    float s = (float)d.Width / frame_w < (float)d.Height / frame_h ? (float)d.Width / frame_w : (float)d.Height / frame_h;
    float x0 = (d.Width - frame_w * s) / 2 - 0.5f, y0 = (d.Height - frame_h * s) / 2 - 0.5f;
    float x1 = x0 + frame_w * s, y1 = y0 + frame_h * s;
    struct vertex v[6] = { { x0, y0, 0, 1, ~0u, 0, 0 }, { x1, y0, 0, 1, ~0u, 1, 0 }, { x0, y1, 0, 1, ~0u, 0, 1 },
                           { x1, y0, 0, 1, ~0u, 1, 0 }, { x1, y1, 0, 1, ~0u, 1, 1 }, { x0, y1, 0, 1, ~0u, 0, 1 } };
    IDirect3DDevice8_Clear(dev, 0, NULL, D3DCLEAR_TARGET, 0xff000000, 1, 0);
    draw_2d(dev, tex, v, 2);
}

void video_patch(void)
{
    real_CopyToBuffer = patch_import("binkw32.dll", "_BinkCopyToBuffer@28", hook_CopyToBuffer);
    real_Close = patch_import("binkw32.dll", "_BinkClose@4", hook_Close);
    if (!real_CopyToBuffer || !real_Close) log_line("video: Bink imports not found, videos stay small");
}
