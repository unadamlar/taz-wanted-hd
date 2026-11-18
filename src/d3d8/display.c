// Vsync and resolution changes without a restart. The game already recovers from a lost device
// (alt-tab): after each Present it asks TestCooperativeLevel, and on "lost", then "needs reset", it
// releases its textures and buffers, calls Reset with its own present parameters (0x7420a4) and
// rebuilds everything. For a change we report a lost device once and put the new size and interval
// into those parameters on the way into Reset; then we update the game's screen-size globals.
// Anti-aliasing (multisampling) goes the same way.
#define COBJMACROS
#include "proxy.h"
#include "game.h"

#define GAME_PP ((D3DPRESENT_PARAMETERS *)0x7420a4)
#define SETTLE_MS 600 // Left/Right through several resolutions makes one change, not one each

static HRESULT (WINAPI *real_TestCooperativeLevel)(IDirect3DDevice8 *);
static HRESULT (WINAPI *real_Reset)(IDirect3DDevice8 *, D3DPRESENT_PARAMETERS *);
static volatile LONG state; // 0 idle, 1 change requested, 2 reported lost, 3 reported needs reset
static UINT want_w, want_h, want_interval;
static DWORD asked_at;

// The game's render targets (reflections, effects): a list from 0x742e70, next at +0x60, ending at
// 0x742e10; +0x84 its depth buffer. Its alt-tab path frees that buffer and then, seeing 0, never makes
// a new one; we note which had one and put a non-zero mark back so its resume code creates it.
#define RT_FIRST (*(BYTE **)0x742e70)
#define RT_END ((BYTE *)0x742e10)
#define MAX_RTS 16
static BYTE *had_depth[MAX_RTS];
static int nhad;

static DWORD game_swap = D3DSWAPEFFECT_DISCARD, game_flags; // the game's own choices, for anti-aliasing off

// The highest sample count up to the setting that the back and depth buffers both support. Multisampling
// needs a discarding swap and a back buffer that isn't lockable (video.c covers the game's one lock).
void display_samples(IDirect3D8 *d3d, UINT adapter, D3DDEVTYPE type, D3DPRESENT_PARAMETERS *pp)
{
    if (!pp->MultiSampleType) game_swap = pp->SwapEffect, game_flags = pp->Flags;
    int n = settings.antialiasing > 16 ? 16 : settings.antialiasing;
    for (; n >= 2; n--)
        if (SUCCEEDED(IDirect3D8_CheckDeviceMultiSampleType(d3d, adapter, type, pp->BackBufferFormat, pp->Windowed, n)) &&
            (!pp->EnableAutoDepthStencil ||
             SUCCEEDED(IDirect3D8_CheckDeviceMultiSampleType(d3d, adapter, type, pp->AutoDepthStencilFormat, pp->Windowed, n))))
            break;
    if (n >= 2) {
        pp->MultiSampleType = n;
        pp->SwapEffect = D3DSWAPEFFECT_DISCARD;
        pp->Flags &= ~D3DPRESENTFLAG_LOCKABLE_BACKBUFFER;
    } else {
        pp->MultiSampleType = D3DMULTISAMPLE_NONE;
        pp->SwapEffect = game_swap;
        pp->Flags = game_flags;
    }
}

void display_change(UINT w, UINT h, int vsync)
{
    want_w = w;
    want_h = h;
    want_interval = vsync ? D3DPRESENT_INTERVAL_ONE : D3DPRESENT_INTERVAL_IMMEDIATE;
    asked_at = GetTickCount();
    if (real_Reset) InterlockedCompareExchange(&state, 1, 0);
}

static HRESULT WINAPI hook_TestCooperativeLevel(IDirect3DDevice8 *dev)
{
    HRESULT hr = real_TestCooperativeLevel(dev);
    if (FAILED(hr)) return hr; // really lost: the game's own recovery
    if (state == 1 && GetTickCount() - asked_at >= SETTLE_MS) return state = 2, D3DERR_DEVICELOST;
    if (state >= 2) {
        nhad = 0;
        for (BYTE *rt = RT_FIRST; rt && rt != RT_END && nhad < MAX_RTS; rt = *(BYTE **)(rt + 0x60))
            if (*(void **)(rt + 0x84)) had_depth[nhad++] = rt;
        return state = 3, D3DERR_DEVICENOTRESET;
    }
    return hr;
}

// The engine's screen size, as its display start-up and scene change set it.
static void resize_game(UINT w, UINT h)
{
    *(UINT *)0x741f74 = w;
    *(UINT *)0x741f78 = h;
    *(UINT *)0x741f7c = w / 2;
    *(UINT *)0x741f80 = h / 2;
    *(float *)0x741f94 = (float)h / w * 0.5f;
    ((void (*)(void))0x56afb0)(); // 2D projection
    SCREEN_W = w;
    SCREEN_H = h;
    ((void (*)(int, int))0x48fac0)(*(BYTE *)0x6f4b18, *(int *)0x6f4b20); // camera rectangles, split screen
    widescreen_apply();
    for (BYTE *p = (BYTE *)0x708d38; p < (BYTE *)0x710b50; p += 0x3f0c) // per player: full-screen fade quads
        ((void (__fastcall *)(void *))0x435530)(p);
}

static HRESULT WINAPI hook_Reset(IDirect3DDevice8 *dev, D3DPRESENT_PARAMETERS *pp)
{
    if (state != 3 || pp != GAME_PP) return real_Reset(dev, pp);
    state = 0;
    D3DPRESENT_PARAMETERS old = *pp;
    if (want_w && want_h) pp->BackBufferWidth = want_w, pp->BackBufferHeight = want_h;
    if (!pp->Windowed) pp->FullScreen_PresentationInterval = want_interval;
    IDirect3D8 *d3d;
    D3DDEVICE_CREATION_PARAMETERS cp;
    if (SUCCEEDED(IDirect3DDevice8_GetDirect3D(dev, &d3d))) {
        if (SUCCEEDED(IDirect3DDevice8_GetCreationParameters(dev, &cp))) display_samples(d3d, cp.AdapterOrdinal, cp.DeviceType, pp);
        IDirect3D8_Release(d3d);
    }
    // The game has released its buffers and render targets, but some are still bound to the device,
    // which keeps them alive and makes Reset fail.
    IDirect3DSurface8 *bb;
    for (DWORD i = 0; i < 8; i++) IDirect3DDevice8_SetTexture(dev, i, NULL), IDirect3DDevice8_SetStreamSource(dev, i, NULL, 0);
    IDirect3DDevice8_SetIndices(dev, NULL, 0);
    if (SUCCEEDED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb)))
        IDirect3DDevice8_SetRenderTarget(dev, bb, NULL), IDirect3DSurface8_Release(bb);
    ((void (*)(void))0x573400)(); // the game's alt-tab path forgets its index buffers too
    overlay_reset(dev);
    HRESULT hr = real_Reset(dev, pp);
    if (FAILED(hr)) {
        log_line("display: %ux%u interval %u samples %u failed (0x%08lx), keeping %ux%u", pp->BackBufferWidth,
                 pp->BackBufferHeight, pp->FullScreen_PresentationInterval, pp->MultiSampleType, hr, old.BackBufferWidth,
                 old.BackBufferHeight);
        *pp = old;
        hr = real_Reset(dev, pp);
    } else {
        log_line("display: %ux%u, %s, %u samples", pp->BackBufferWidth, pp->BackBufferHeight,
                 pp->FullScreen_PresentationInterval == D3DPRESENT_INTERVAL_IMMEDIATE ? "vsync off" : "vsync on",
                 pp->MultiSampleType);
    }
    ((void (*)(void))0x573510)();
    for (int i = 0; i < nhad; i++) *(void **)(had_depth[i] + 0x84) = (void *)1;
    textures_reset(dev);
    if (SUCCEEDED(hr) && (pp->BackBufferWidth != old.BackBufferWidth || pp->BackBufferHeight != old.BackBufferHeight))
        resize_game(pp->BackBufferWidth, pp->BackBufferHeight);
    return hr;
}

void display_install(IDirect3DDevice8 *dev)
{
    if (!settings.exe_known || real_Reset) return; // the addresses above are the retail exe's
    patch((void **)&dev->lpVtbl->TestCooperativeLevel, hook_TestCooperativeLevel, (void **)&real_TestCooperativeLevel);
    patch((void **)&dev->lpVtbl->Reset, hook_Reset, (void **)&real_Reset);
}
