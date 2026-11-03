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

struct settings { int hd_textures, hd_models, vsync, antialiasing, fps_limit, smooth, wasd, mouse; float menu_speed; int exe_known, passthrough; };
extern struct settings settings;
void settings_load(void);
void settings_frame(void);
void menuspeed_patch(float speed);
void menuspeed_set(float speed);
void asserts_patch(void);
void *patch_import(const char *dll, const char *func, void *hook);
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
void textures_reset(IDirect3DDevice8 *dev);
void overlay_reset(IDirect3DDevice8 *dev);
void display_install(IDirect3DDevice8 *dev);
void display_change(UINT w, UINT h, int vsync); // w, h 0: keep the size
void display_samples(IDirect3D8 *d3d, UINT adapter, D3DDEVTYPE type, D3DPRESENT_PARAMETERS *pp);
int settings_resolution(const char *value, UINT *w, UINT *h);
int setting_count(void);
const char *setting_label(int i);
const char *setting_shown(int i);
const char *setting_about(int i);
int setting_on_page(int i, int pause);
int setting_find(const char *key);
int setting_is_link(int i);
void menu_open_keys(void);
void menu_frame(void);
void setting_step(int i, int dir);
void settings_refresh(void);
void menu_patch(void);
void smooth_install(IDirect3DDevice8 *dev);
void controls_patch(void);
void controls_frame(void);
void controls_apply(void);
int controls_row_count(void);
int controls_capturing(void);
void controls_capture(int row, void (*done)(void));
void controls_row_text(int row, char *out, int size);
void controls_reset_keys(void);
void settings_get(const char *key, const char *def, char *out, DWORD size);
int redirect_call(BYTE *at, void *expect, void *to);
HRESULT smooth_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                    HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT));
void capture_frame(void);
void capture_scene(void);
void capture_draw(IDirect3DDevice8 *dev, IDirect3DVertexBuffer8 *vb, D3DPRIMITIVETYPE type, UINT start, UINT count);
UINT64 textures_bound_hash(DWORD stage);
IDirect3DBaseTexture8 *textures_bound(DWORD stage);
int smooth_character(IDirect3DDevice8 *dev);
void mesh_forget(IDirect3DVertexBuffer8 *vb);
HRESULT mesh_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                  HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT));
extern DWORD presents; // frames shown so far
extern int smooth_keep_normals;
