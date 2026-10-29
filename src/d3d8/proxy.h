#pragma once
#include <windows.h>
#include <d3d8.h>

void log_line(const char *fmt, ...);
void patch(void **slot, void *hook, void **orig);
void textures_install(IDirect3DDevice8 *dev);
void textures_report(void);
void textures_frame(void);
void widescreen_patch(void);

struct settings { int widescreen, hd_textures, vsync, fps_limit; float menu_speed; };
extern struct settings settings;
void settings_load(void);
void menuspeed_patch(float speed);
void to_bgra(D3DFORMAT f, const BYTE *src, UINT n, BYTE *out);
void queue_png(const char *path, UINT w, UINT h, BYTE *bgra);
void screenshot_frame(IDirect3DDevice8 *dev);
