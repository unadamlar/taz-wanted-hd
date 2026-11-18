// Saves frames to taz-hd\shots: F12 saves the next frame. With tests=1 in the ini, so does an empty
// taz-hd\shot file; a number N in it saves the next N frames at 1/8 size, or 1/S for "N S" (for
// checking motion in scripted tests).
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include "proxy.h"

#define TRIGGER "taz-hd\\shot"
#define SHOT_DIR "taz-hd\\shots"

static int burst_scale = 8;

static int requested(void)
{
    int n = 1;
    if (key_pressed(VK_F12)) return 1;
    FILE *f = settings.tests ? fopen(TRIGGER, "r") : NULL;
    if (!f) return 0;
    burst_scale = 8;
    if (fscanf(f, "%d %d", &n, &burst_scale) < 1 || n < 1) n = 1;
    if (burst_scale < 1) burst_scale = 1;
    fclose(f);
    DeleteFileA(TRIGGER);
    return n;
}

void screenshot_frame(IDirect3DDevice8 *dev)
{
    static int count, burst, burst_frame;
    int n = requested();
    if (n > 1) {
        burst = n;
        burst_frame = 0;
    } else if (!n && !burst) {
        return;
    }
    int scale = burst ? burst_scale : 1;

    IDirect3DSurface8 *bb = NULL, *resolved = NULL, *copy = NULL;
    D3DSURFACE_DESC d;
    D3DLOCKED_RECT r;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    // An anti-aliased back buffer can't be read directly; a copy into a plain render target resolves it.
    if (d.MultiSampleType &&
        SUCCEEDED(IDirect3DDevice8_CreateRenderTarget(dev, d.Width, d.Height, d.Format, D3DMULTISAMPLE_NONE, FALSE, &resolved)))
        IDirect3DDevice8_CopyRects(dev, bb, NULL, 0, resolved, NULL);
    if (SUCCEEDED(IDirect3DDevice8_CreateImageSurface(dev, d.Width, d.Height, d.Format, &copy)) &&
        SUCCEEDED(IDirect3DDevice8_CopyRects(dev, resolved ? resolved : bb, NULL, 0, copy, NULL)) &&
        SUCCEEDED(IDirect3DSurface8_LockRect(copy, &r, NULL, D3DLOCK_READONLY))) {
        UINT w = d.Width / scale, h = d.Height / scale;
        BYTE *px = malloc((size_t)d.Width * 4 * h), *row = malloc((size_t)d.Width * 4);
        if (px && row) {
            char path[MAX_PATH];
            for (UINT y = 0; y < h; y++) {
                to_bgra(d.Format, (BYTE *)r.pBits + (size_t)y * scale * r.Pitch, d.Width, row);
                for (UINT x = 0; x < w; x++)
                    ((DWORD *)px)[(size_t)y * w + x] = ((DWORD *)row)[x * scale];
            }
            CreateDirectoryA(SHOT_DIR, NULL);
            if (burst) snprintf(path, sizeof path, SHOT_DIR "\\burst-%04d.png", ++burst_frame);
            else do snprintf(path, sizeof path, SHOT_DIR "\\shot-%03d.png", ++count); // after earlier sessions' shots
                while (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES);
            queue_png(path, w, h, px);
            px = NULL;
            LARGE_INTEGER t, f;
            QueryPerformanceCounter(&t);
            QueryPerformanceFrequency(&f);
            log_line("screenshot %s (%ux%u) at %.1f ms", path, w, h, t.QuadPart * 1000.0 / f.QuadPart);
        }
        free(px);
        free(row);
        IDirect3DSurface8_UnlockRect(copy);
    } else {
        log_line("screenshot failed");
    }
    if (copy) IDirect3DSurface8_Release(copy);
    if (resolved) IDirect3DSurface8_Release(resolved);
    IDirect3DSurface8_Release(bb);
    if (burst && burst_frame >= burst) burst = 0;
}
