// Level previews on a level's map ("Video"): the game renders the level entrance's camera into a
// 256x256 render target and shows it over 3/8 of the screen width, so at HD sizes it was a smear.
// The target is now made about the size it is shown at (powers of two, as the engine requires), with
// its own depth buffer: the shared one is multisampled with anti-aliasing on, and doesn't fit it.
#define COBJMACROS
#include "proxy.h"
#include "game.h"

#define SET_VIEWPORT ((BYTE *)0x569a10)  // FUN_00569a10(x, y, w, h)
#define TARGET (*(BYTE **)0x6f8c9c)      // the preview's target; +0x80 surface, +0x84 depth, +0x90/+0x94 size
#define DEVICE (*(IDirect3DDevice8 **)0x741fc4)

static UINT pow2(UINT n)
{
    UINT p = 256;
    while (p < n && p < 2048) p <<= 1;
    return p;
}

// The preview's colour surface, while it exists.
IDirect3DSurface8 *preview_surface(void) { return TARGET ? *(IDirect3DSurface8 **)(TARGET + 0x80) : NULL; }

static BYTE *create_target(UINT w, UINT h, int bits, int depth_bits, int flags)
{
    UINT sw = SCREEN_W, sh = SCREEN_H; // shown at 240/640 x 180/448 of the screen
    BYTE *rt = ((BYTE * (*)(UINT, UINT, int, int, int)) CREATE_TARGET)(pow2(sw * 3 / 8), pow2(sh * 180 / 448), bits, depth_bits, flags);
    IDirect3DSurface8 *shared, *own;
    D3DSURFACE_DESC d;
    if (!rt || *(void **)(rt + 0x84) || FAILED(IDirect3DDevice8_GetDepthStencilSurface(DEVICE, &shared))) return rt;
    IDirect3DSurface8_GetDesc(shared, &d);
    IDirect3DSurface8_Release(shared);
    // Screen-sized at least: the Remaster draws the preview into part of its screen-sized HDR texture with it.
    UINT dw = *(UINT *)(rt + 0x90), dh = *(UINT *)(rt + 0x94);
    if (SUCCEEDED(IDirect3DDevice8_CreateDepthStencilSurface(DEVICE, dw > sw ? dw : sw, dh > sh ? dh : sh, d.Format,
                                                            D3DMULTISAMPLE_NONE, &own)))
        *(void **)(rt + 0x84) = own; // released with the target
    return rt;
}

static void set_viewport(int x, int y, int w, int h)
{
    if (TARGET) w = *(int *)(TARGET + 0x90), h = *(int *)(TARGET + 0x94);
    ((void (*)(int, int, int, int))SET_VIEWPORT)(x, y, w, h);
}

void preview_patch(void)
{
    // The viewport first: alone, it still matches the original target.
    if (!redirect_call((BYTE *)0x4a8452, SET_VIEWPORT, set_viewport) || !redirect_call((BYTE *)0x4ab9fd, CREATE_TARGET, create_target))
        log_line("map previews: unexpected code, left at 256x256");
}
