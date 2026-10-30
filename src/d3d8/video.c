// Intro videos: the game copies each 640x480 Bink frame into the middle of the back buffer. We take
// the copy into our own buffer instead and draw it at Present, scaled to the screen height. When
// taz-hd\videos\<name>\NNNN.jpg exist (tools/videos.py), a thread decodes them ahead and we show those;
// Bink still plays the sound and sets the pace.
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include "proxy.h"
#include "image.h"

#define BINKCOPY_SCALE 0x70000000 // the game's 2x and interlace modes; we always copy 1:1
#define AHEAD 8

static void *(WINAPI *real_Open)(const char *, UINT);
static int (WINAPI *real_CopyToBuffer)(void *, void *, int, UINT, UINT, UINT, UINT);
static void (WINAPI *real_Close)(void *);

static BYTE *frame; // Bink's own frame, for videos without upscaled files
static UINT frame_w, frame_h, fresh, playing;
static IDirect3DTexture8 *small_tex, *hd_tex, *shown;

static CRITICAL_SECTION lock;
static HANDLE wake;
static char hd_dir[MAX_PATH]; // empty when the playing video has no upscaled frames
static UINT video_no, frames, want, hd_w, hd_h; // video_no tells videos apart in the slots
static struct { UINT video, n; BYTE *px; } slots[AHEAD];

static int slot_of(UINT video, UINT n)
{
    for (int i = 0; i < AHEAD; i++)
        if (slots[i].px && slots[i].video == video && slots[i].n == n) return i;
    return -1;
}

static DWORD WINAPI decoder(void *arg)
{
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    for (;;) {
        WaitForSingleObject(wake, 100);
        EnterCriticalSection(&lock);
        UINT video = video_no, first = want, last = want + AHEAD - 1 < frames ? want + AHEAD - 1 : frames, n = 0;
        char path[MAX_PATH + 16] = "";
        for (UINT k = first; *hd_dir && k && k <= last && !n; k++)
            if (slot_of(video, k) < 0) n = k;
        if (n) snprintf(path, sizeof path, "%s\\%04u.jpg", hd_dir, n);
        LeaveCriticalSection(&lock);
        if (!n) continue;

        UINT w, h;
        BYTE *px = image_read(path, &w, &h);
        EnterCriticalSection(&lock);
        int free_slot = -1; // an empty slot, or one holding a frame already shown or from an old video
        for (int i = 0; i < AHEAD && free_slot < 0; i++)
            if (!slots[i].px || slots[i].video != video_no || slots[i].n < want) free_slot = i;
        if (!px || video != video_no || free_slot < 0 || (hd_w && (w != hd_w || h != hd_h))) {
            if (!px && video == video_no) {
                log_line("video: can't read %s, using the original frames", path);
                *hd_dir = 0;
            }
            free(px);
        } else {
            free(slots[free_slot].px);
            slots[free_slot].video = video;
            slots[free_slot].n = n;
            slots[free_slot].px = px;
            hd_w = w;
            hd_h = h;
        }
        LeaveCriticalSection(&lock);
        SetEvent(wake); // keep going until AHEAD frames are ready
    }
    return 0;
}

static void *WINAPI hook_Open(const char *name, UINT flags)
{
    void *bink = real_Open(name, flags);
    if (!bink) return bink;
    const char *base = strrchr(name, '\\') ? strrchr(name, '\\') + 1 : name;
    char dir[MAX_PATH];
    snprintf(dir, sizeof dir, "taz-hd\\videos\\%.*s", (int)strcspn(base, "."), base);
    int have = GetFileAttributesA(dir) != INVALID_FILE_ATTRIBUTES;
    log_line("video: %s, %u frames, %s", name, ((UINT *)bink)[2], have ? "upscaled" : "original");
    EnterCriticalSection(&lock);
    video_no++;
    frames = ((UINT *)bink)[2];
    want = 1;
    hd_w = hd_h = 0;
    strcpy(hd_dir, have ? dir : "");
    LeaveCriticalSection(&lock);
    SetEvent(wake);
    return bink;
}

static int WINAPI hook_CopyToBuffer(void *bink, void *dest, int pitch, UINT height, UINT x, UINT y, UINT flags)
{
    UINT w = ((UINT *)bink)[0], h = ((UINT *)bink)[1];
    if (!frame || w != frame_w || h != frame_h) {
        free(frame);
        frame = calloc(w * h, 4);
        frame_w = w;
        frame_h = h;
    }
    if (!frame || (flags & 0xf) != 3) return real_CopyToBuffer(bink, dest, pitch, height, x, y, flags); // 3 = 32-bit
    int skipped = real_CopyToBuffer(bink, frame, w * 4, h, 0, 0, flags & ~BINKCOPY_SCALE);
    EnterCriticalSection(&lock);
    want = ((UINT *)bink)[3]; // the frame Bink just decoded, counting from 1
    LeaveCriticalSection(&lock);
    SetEvent(wake);
    playing = fresh = 1;
    return skipped;
}

static void WINAPI hook_Close(void *bink)
{
    playing = 0;
    EnterCriticalSection(&lock);
    *hd_dir = 0;
    for (int i = 0; i < AHEAD; i++) free(slots[i].px), slots[i].px = NULL;
    LeaveCriticalSection(&lock);
    real_Close(bink);
}

static void upload(IDirect3DDevice8 *dev, IDirect3DTexture8 **tex, UINT w, UINT h, const BYTE *px)
{
    D3DSURFACE_DESC d;
    if (*tex && SUCCEEDED(IDirect3DTexture8_GetLevelDesc(*tex, 0, &d)) && (d.Width != w || d.Height != h))
        IDirect3DTexture8_Release(*tex), *tex = NULL;
    if (!*tex && FAILED(IDirect3DDevice8_CreateTexture(dev, w, h, 1, 0, D3DFMT_X8R8G8B8, D3DPOOL_MANAGED, tex))) {
        log_line("video: could not create a %ux%u texture", w, h);
        *tex = NULL;
        return;
    }
    D3DLOCKED_RECT r;
    if (FAILED(IDirect3DTexture8_LockRect(*tex, 0, &r, NULL, 0))) return;
    for (UINT row = 0; row < h; row++) memcpy((BYTE *)r.pBits + row * r.Pitch, px + row * w * 4, w * 4);
    IDirect3DTexture8_UnlockRect(*tex, 0);
    shown = *tex;
}

void video_frame(IDirect3DDevice8 *dev)
{
    if (!playing) {
        if (small_tex) IDirect3DTexture8_Release(small_tex), small_tex = NULL;
        if (hd_tex) IDirect3DTexture8_Release(hd_tex), hd_tex = NULL;
        shown = NULL;
        return;
    }
    if (fresh) {
        EnterCriticalSection(&lock);
        int i = *hd_dir ? slot_of(video_no, want) : -1;
        if (i >= 0) upload(dev, &hd_tex, hd_w, hd_h, slots[i].px);
        LeaveCriticalSection(&lock);
        if (i < 0) upload(dev, &small_tex, frame_w, frame_h, frame); // upscaled frame missing or late
        fresh = 0;
    }
    if (!shown) return;
    IDirect3DSurface8 *bb;
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    IDirect3DSurface8_Release(bb);
    // Fit the video's shape (Bink's size) to the screen, whichever texture is shown.
    float s = (float)d.Width / frame_w < (float)d.Height / frame_h ? (float)d.Width / frame_w : (float)d.Height / frame_h;
    float x0 = (d.Width - frame_w * s) / 2 - 0.5f, y0 = (d.Height - frame_h * s) / 2 - 0.5f;
    float x1 = x0 + frame_w * s, y1 = y0 + frame_h * s;
    struct vertex v[6] = { { x0, y0, 0, 1, ~0u, 0, 0 }, { x1, y0, 0, 1, ~0u, 1, 0 }, { x0, y1, 0, 1, ~0u, 0, 1 },
                           { x1, y0, 0, 1, ~0u, 1, 0 }, { x1, y1, 0, 1, ~0u, 1, 1 }, { x0, y1, 0, 1, ~0u, 0, 1 } };
    IDirect3DDevice8_Clear(dev, 0, NULL, D3DCLEAR_TARGET, 0xff000000, 1, 0);
    draw_2d(dev, shown, v, 2);
}

void video_patch(void)
{
    real_Open = patch_import("binkw32.dll", "_BinkOpen@8", hook_Open);
    real_CopyToBuffer = patch_import("binkw32.dll", "_BinkCopyToBuffer@28", hook_CopyToBuffer);
    real_Close = patch_import("binkw32.dll", "_BinkClose@4", hook_Close);
    if (!real_Open || !real_CopyToBuffer || !real_Close) {
        log_line("video: Bink imports not found, videos stay small");
        return;
    }
    InitializeCriticalSection(&lock);
    wake = CreateEventA(NULL, FALSE, FALSE, NULL);
    CloseHandle(CreateThread(NULL, 0, decoder, NULL, 0, NULL));
}
