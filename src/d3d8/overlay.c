// In-game settings panel (F1), drawn before Present over the finished frame. Changes are written to
// taz-hd.ini; menu speed and the frame cap apply at once, the rest on the next start.
#define COBJMACROS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define ATLAS_W 1024
#define ATLAS_H 512
#define MAX_QUADS 2048

struct vertex { float x, y, z, rhw; DWORD color; float u, v; };
#define FVF (D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1)

struct item {
    const char *label, *key, *def;
    const char *choices[12];
    int count, live, cur;
};

static struct item items[] = {
    { "Resolution", "resolution", "auto", { "auto" }, 1, 0, 0 },
    { "Widescreen", "widescreen", "1", { "0", "1" }, 2, 0, 0 },
    { "HD textures", "hd_textures", "1", { "0", "1" }, 2, 0, 0 },
    { "Vsync", "vsync", "1", { "0", "1" }, 2, 0, 0 },
    { "Frame cap", "fps_limit", "0", { "0", "30", "60", "120", "144" }, 5, 1, 0 },
    { "Menu speed", "menu_speed", "1", { "1", "1.5", "2", "3" }, 4, 1, 0 },
};
#define ITEMS (int)(sizeof items / sizeof *items)

static IDirect3DTexture8 *atlas;
static int glyph_x[96], glyph_row[96];
static float glyph_w[96], line_h;
static DWORD state_block;
static int selected, changed_restart, ready;
static struct vertex quads[MAX_QUADS * 6];
static int nquads;

static char resolutions[11][16];

static void fill_resolutions(struct item *it)
{
    DEVMODEA m = { .dmSize = sizeof m };
    it->count = 1;
    for (DWORD i = 0; EnumDisplaySettingsA(NULL, i, &m) && it->count < 12; i++) {
        char s[16];
        snprintf(s, sizeof s, "%lux%lu", m.dmPelsWidth, m.dmPelsHeight);
        int dup = 0;
        for (int k = 1; k < it->count; k++) dup |= !strcmp(it->choices[k], s);
        if (dup || m.dmPelsWidth < 800) continue;
        strcpy(resolutions[it->count - 1], s);
        it->choices[it->count] = resolutions[it->count - 1];
        it->count++;
    }
}

static const char *shown(const struct item *it)
{
    const char *v = it->choices[it->cur];
    if (!strcmp(it->key, "fps_limit") && !strcmp(v, "0")) return "off";
    if (!strcmp(it->key, "menu_speed")) {
        static char s[8];
        snprintf(s, sizeof s, "%sx", v);
        return s;
    }
    if (it->count == 2 && !strcmp(it->choices[0], "0")) return it->cur ? "on" : "off";
    return v;
}

static void load_current(void)
{
    char v[32];
    fill_resolutions(&items[0]);
    for (int i = 0; i < ITEMS; i++) {
        GetPrivateProfileStringA("taz-hd", items[i].key, items[i].def, v, sizeof v, ".\\taz-hd.ini");
        items[i].cur = 0;
        for (int k = 0; k < items[i].count; k++)
            if (!_stricmp(items[i].choices[k], v)) items[i].cur = k;
    }
}

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

static int pressed(int vk)
{
    static BYTE was[256];
    int down = (GetAsyncKeyState(vk) & 0x8000) != 0, edge = down && !was[vk];
    was[vk] = (BYTE)down;
    return edge;
}

static void apply(struct item *it)
{
    const char *v = it->choices[it->cur];
    settings_save(it->key, v);
    log_line("overlay: %s = %s", it->key, v);
    if (!strcmp(it->key, "menu_speed")) menuspeed_set(settings.menu_speed = (float)atof(v));
    else if (!strcmp(it->key, "fps_limit")) settings.fps_limit = atoi(v);
    if (!it->live) changed_restart = 1;
}

static void handle_keys(void)
{
    int f1 = pressed(VK_F1), esc = pressed(VK_ESCAPE), up = pressed(VK_UP), down = pressed(VK_DOWN);
    int left = pressed(VK_LEFT), right = pressed(VK_RIGHT), enter = pressed(VK_RETURN);
    if (!overlay_open) {
        if (f1) {
            load_current();
            overlay_open = 1;
            log_line("overlay: open");
        }
        return;
    }
    if (f1 || esc) {
        overlay_open = 0;
        log_line("overlay: closed");
        return;
    }
    if (up) selected = (selected + ITEMS - 1) % ITEMS;
    if (down) selected = (selected + 1) % ITEMS;
    struct item *it = &items[selected];
    if (left || right || enter) {
        it->cur = (it->cur + (left ? it->count - 1 : 1)) % it->count;
        apply(it);
    }
}

void overlay_frame(IDirect3DDevice8 *dev)
{
    handle_keys();
    if (!overlay_open) return;

    IDirect3DSurface8 *bb;
    D3DSURFACE_DESC d;
    if (FAILED(IDirect3DDevice8_GetBackBuffer(dev, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) return;
    IDirect3DSurface8_GetDesc(bb, &d);
    IDirect3DSurface8_Release(bb);
    if (!ready) {
        ready = 1;
        build_atlas(dev, d.Height);
        IDirect3DDevice8_CreateStateBlock(dev, D3DSBT_ALL, &state_block);
        if (!atlas || !state_block) log_line("overlay: could not set up (atlas %p, state block %lu)", atlas, state_block);
    }
    if (!atlas || !state_block) return;

    // Layout, in pixels.
    float pad = line_h * 0.8f, row = line_h * 1.35f, w = line_h * 18, h = pad * 2 + row * (ITEMS + 3.2f);
    float x0 = (d.Width - w) / 2, y0 = (d.Height - h) / 2, y = y0 + pad;
    nquads = 0;
    rect(x0, y0, x0 + w, y0 + h, 0xf0101828);
    rect(x0, y0, x0 + w, y0 + line_h * 0.15f, 0xffffa020);
    text(x0 + pad, y, "Taz: Wanted HD", 0xffffc040);
    text(x0 + w - pad - text_width("F1 closes"), y, "F1 closes", 0xff8090a0);
    y += row * 1.4f;
    for (int i = 0; i < ITEMS; i++, y += row) {
        DWORD c = i == selected ? 0xffffffff : 0xffb0b8c8;
        if (i == selected) rect(x0 + pad * 0.5f, y - row * 0.12f, x0 + w - pad * 0.5f, y + row * 0.88f, 0x40ffffff);
        text(x0 + pad, y, items[i].label, c);
        char v[40];
        snprintf(v, sizeof v, "< %s >%s", shown(&items[i]), items[i].live ? "" : " *");
        text(x0 + w - pad - text_width(v), y, v, c);
    }
    y += row * 0.4f;
    text(x0 + pad, y, changed_restart ? "* applies after restarting the game" : "Up/Down select, Left/Right change", 0xff8090a0);

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
    IDirect3DDevice8_SetTexture(dev, 0, (IDirect3DBaseTexture8 *)atlas);
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
    IDirect3DDevice8_DrawPrimitiveUP(dev, D3DPT_TRIANGLELIST, nquads * 2, quads, sizeof *quads);
    IDirect3DDevice8_EndScene(dev);
    IDirect3DDevice8_ApplyStateBlock(dev, state_block);
}
