// Short messages (quicksave) drawn before Present over the finished frame, and draw_2d for our 2D.
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define ATLAS_W 1024
#define ATLAS_H 512
#define MAX_QUADS 2048

static IDirect3DTexture8 *atlas;
static int glyph_x[96], glyph_row[96];
static float glyph_w[96], line_h;
static int ready;
static struct vertex quads[MAX_QUADS * 6];
static int nquads;

// Renders printable ASCII with GDI into the atlas; the top-left 4x4 block stays white for solid quads.
static void build_atlas(IDirect3DDevice8 *dev, UINT screen_h)
{
    int px = screen_h / 40 < 14 ? 14 : screen_h / 40;
    if (px > 56) px = 56;
    BITMAPINFO bi = { .bmiHeader = { sizeof bi.bmiHeader, ATLAS_W, -ATLAS_H, 1, 32, BI_RGB } };
    BYTE *bits;
    HDC dc = CreateCompatibleDC(NULL);
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, (void **)&bits, NULL, 0);
    HFONT font = CreateFontA(-px, 0, 0, 0, FW_BOLD, 0, 0, 0, ANSI_CHARSET, 0, 0, ANTIALIASED_QUALITY, 0, "Arial");
    if (!dc || !bmp || !font) goto done;
    SelectObject(dc, bmp);
    SelectObject(dc, font);
    SetTextColor(dc, RGB(255, 255, 255));
    SetBkColor(dc, RGB(0, 0, 0));
    SetBkMode(dc, OPAQUE);
    memset(bits, 0, ATLAS_W * ATLAS_H * 4);
    for (int y = 0; y < 4; y++) memset(bits + y * ATLAS_W * 4, 255, 16);
    TEXTMETRICA tm;
    GetTextMetricsA(dc, &tm);
    line_h = (float)tm.tmHeight;
    int x = 8, row = 0;
    for (int c = 32; c < 127; c++) {
        SIZE sz;
        char ch = (char)c;
        GetTextExtentPoint32A(dc, &ch, 1, &sz);
        if (x + sz.cx + 2 > ATLAS_W) {
            x = 8;
            row++;
        }
        TextOutA(dc, x, row * tm.tmHeight, &ch, 1);
        glyph_x[c - 32] = x;
        glyph_row[c - 32] = row;
        glyph_w[c - 32] = (float)sz.cx;
        x += sz.cx + 2;
    }
    GdiFlush();
    if (SUCCEEDED(IDirect3DDevice8_CreateTexture(dev, ATLAS_W, ATLAS_H, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &atlas))) {
        D3DLOCKED_RECT r;
        if (SUCCEEDED(IDirect3DTexture8_LockRect(atlas, 0, &r, NULL, 0))) {
            for (int y = 0; y < ATLAS_H; y++) {
                DWORD *dst = (DWORD *)((BYTE *)r.pBits + y * r.Pitch), *src = (DWORD *)(bits + y * ATLAS_W * 4);
                for (int i = 0; i < ATLAS_W; i++) dst[i] = ((src[i] & 0xff) << 24) | 0xffffff; // coverage as alpha
            }
            IDirect3DTexture8_UnlockRect(atlas, 0);
        }
    }
done:
    if (font) DeleteObject(font);
    if (bmp) DeleteObject(bmp);
    if (dc) DeleteDC(dc);
}

static void quad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, DWORD color)
{
    if (nquads >= MAX_QUADS) return;
    struct vertex *q = quads + nquads++ * 6;
    struct vertex a = { x0 - 0.5f, y0 - 0.5f, 0, 1, color, u0, v0 }, b = { x1 - 0.5f, y0 - 0.5f, 0, 1, color, u1, v0 };
    struct vertex c = { x0 - 0.5f, y1 - 0.5f, 0, 1, color, u0, v1 }, d = { x1 - 0.5f, y1 - 0.5f, 0, 1, color, u1, v1 };
    q[0] = a; q[1] = b; q[2] = c; q[3] = b; q[4] = d; q[5] = c;
}

static void rect(float x0, float y0, float x1, float y1, DWORD color)
{
    quad(x0, y0, x1, y1, 1.0f / ATLAS_W, 1.0f / ATLAS_H, 3.0f / ATLAS_W, 3.0f / ATLAS_H, color);
}

static float text_width(const char *s)
{
    float w = 0;
    for (; *s; s++)
        if (*s >= 32 && *s < 127) w += glyph_w[*s - 32];
    return w;
}

static void text(float x, float y, const char *s, DWORD color)
{
    for (; *s; s++) {
        if (*s < 32 || *s >= 127) continue;
        int g = *s - 32;
        float v0 = glyph_row[g] * line_h / ATLAS_H, v1 = (glyph_row[g] + 1) * line_h / ATLAS_H;
        quad(x, y, x + glyph_w[g], y + line_h, (float)glyph_x[g] / ATLAS_W, v0, (glyph_x[g] + glyph_w[g]) / ATLAS_W, v1, color);
        x += glyph_w[g];
    }
}

static DWORD state_block; // draw_2d's copy of the game's state; it holds the game's buffers

// Before a device Reset: the state block would keep the game's released buffers alive, and the font
// size follows the screen height.
void overlay_reset(IDirect3DDevice8 *dev)
{
    if (state_block) IDirect3DDevice8_DeleteStateBlock(dev, state_block), state_block = 0;
    if (atlas) IDirect3DTexture8_Release(atlas), atlas = NULL;
    ready = 0;
}

static char toast[64];
static DWORD toast_until;

// A short message in the top left corner for two seconds.
void overlay_toast(const char *msg)
{
    snprintf(toast, sizeof toast, "%s", msg);
    toast_until = GetTickCount() + 2000;
}

void overlay_frame(IDirect3DDevice8 *dev)
{
    if ((int)(toast_until - GetTickCount()) <= 0) return;

    IDirect3DSurface8 *bb;
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    IDirect3DSurface8_Release(bb);
    if (!ready) {
        ready = 1;
        build_atlas(dev, d.Height);
        if (!atlas) log_line("overlay: could not build the font atlas");
    }
    if (!atlas) return;
    nquads = 0;
    float pad = line_h * 0.6f, w = text_width(toast) + pad * 2, x0 = line_h, y0 = line_h; // top left: menus use the middle and bottom
    rect(x0, y0, x0 + w, y0 + line_h + pad, 0xd0101828);
    text(x0 + pad, y0 + pad / 2, toast, 0xffffffff);
    draw_2d(dev, atlas, quads, nquads * 2);
}

// Draws screen-space triangles over the frame, leaving the game's render state as it was.
void draw_2d(IDirect3DDevice8 *dev, IDirect3DTexture8 *tex, const struct vertex *v, int triangles)
{
    if (!state_block && FAILED(IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &state_block))) return;
    IDirect3DDevice8_CaptureStateBlock(dev, state_block);
    IDirect3DDevice8_BeginScene(dev);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_ALPHATESTENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_LIGHTING, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_FOGENABLE, FALSE);
    IDirect3DDevice8_SetRenderState(dev, D3DRS_STENCILENABLE, FALSE);
    IDirect3DDevice8_SetVertexShader(dev, FVF);
    IDirect3DDevice8_SetPixelShader(dev, 0);
    IDirect3DDevice8_SetTexture(dev, 0, (IDirect3DBaseTexture8 *)tex);
    IDirect3DDevice8_SetTexture(dev, 1, NULL);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_MINFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_MAGFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_ADDRESSU, D3DTADDRESS_CLAMP);
    IDirect3DDevice8_SetTextureStageState(dev, 0, D3DTSS_ADDRESSV, D3DTADDRESS_CLAMP);
    IDirect3DDevice8_SetTextureStageState(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    IDirect3DDevice8_DrawPrimitiveUP(dev, D3DPT_TRIANGLELIST, triangles, v, sizeof *v);
    IDirect3DDevice8_EndScene(dev);
    IDirect3DDevice8_ApplyStateBlock(dev, state_block);
}
