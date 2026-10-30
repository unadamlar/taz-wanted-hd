#pragma once
#include <windows.h>
#include <d3d8.h>

void log_line(const char *fmt, ...);
void patch(void **slot, void *hook, void **orig);
void textures_install(IDirect3DDevice8 *dev);
void textures_report(void);
void textures_frame(void);
void textures_dump_recent(void);
void widescreen_patch(void);

struct settings { int hd_textures, vsync, fps_limit; float menu_speed; int exe_known, passthrough; };
extern struct settings settings;
void settings_load(void);
void menuspeed_patch(float speed);
void menuspeed_set(float speed);
void input_patch(void);
void asserts_patch(void);
void *patch_import(const char *dll, const char *func, void *hook);
extern int overlay_open; // the game sees no keyboard input while set
void overlay_frame(IDirect3DDevice8 *dev);
struct vertex { float x, y, z, rhw; DWORD color; float u, v; };
#define FVF (D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1)
void draw_2d(IDirect3DDevice8 *dev, IDirect3DTexture8 *tex, const struct vertex *v, int triangles);
void video_patch(void);
void startup_patch(void);
void video_frame(IDirect3DDevice8 *dev);
void settings_save(const char *key, const char *value);
void to_bgra(D3DFORMAT f, const BYTE *src, UINT n, BYTE *out);
void queue_png(const char *path, UINT w, UINT h, BYTE *bgra);
void screenshot_frame(IDirect3DDevice8 *dev);
void quicksave_patch(void);
void overlay_toast(const char *msg);
extern DWORD textures_created; // Direct3D textures taz.exe has created so far
void widescreen_apply(void);
void textures_apply(void);
