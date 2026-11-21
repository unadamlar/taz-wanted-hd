#pragma once
#include <windows.h>
#include <d3d8.h>

IDirect3D8 *d3d8to9_create(void);
struct IDirect3DDevice9 *d3d9_device(IDirect3DDevice8 *dev); // the real device under d3d8to9
#define IS_VERTEX_SHADER(handle) ((handle) & 0x80000000) // otherwise an FVF code
void log_line(const char *fmt, ...);
void patch(void **slot, void *hook, void **orig);
void textures_install(IDirect3DDevice8 *dev);
void textures_report(void);
void textures_frame(void);
void textures_dump_recent(void);
void widescreen_patch(void);

struct settings { int hd_textures, hd_models, vsync, antialiasing, fps_limit, smooth, wasd, mouse, draw; float menu_speed; int exe_known, passthrough, taz_style, tests; };
extern struct settings settings;
void settings_load(void);
void settings_frame(void);
void menuspeed_patch(float speed);
void menuspeed_set(float speed);
void asserts_patch(void);
void *patch_import(const char *dll, const char *func, void *hook);
int write_code(BYTE *at, const BYTE *expect, const void *bytes, SIZE_T n);
int write_jump(BYTE *at, const BYTE *expect, SIZE_T n, BYTE op, void *to);
int key_pressed(int vk);
void textures_bind_own(IDirect3DDevice8 *dev, DWORD stage, IDirect3DBaseTexture8 *t);
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
enum { PAGE_FRONT = 1, PAGE_PAUSE = 2, PAGE_GFX = 4, PAGE_KEYS = 8 }; // menus with our rows
int setting_on_page(int i, int page);
int setting_find(const char *key);
int setting_is_link(int i);
void menu_frame(void);
void setting_step(int i, int dir);
void settings_refresh(void);
void menu_patch(void);
void drawdist_patch(void);
void drawdist_frame(void);
void preview_patch(void);
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
extern int capture_world_on;
void look_install(void *draw, void *draw_indexed);
int look_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count);
void look_frame(IDirect3DDevice8 *dev);
void look_present_ms(double ms);
void look_state_changed(void);
void look_reset(IDirect3DDevice8 *dev);
int look_hidden(UINT64 hash);
void look_merge_begin(IDirect3DDevice8 *dev, IDirect3DVertexBuffer8 *vb, IDirect3DIndexBuffer8 *ib);
void look_merge_texture(IDirect3DDevice8 *dev, IDirect3DBaseTexture8 *tex, UINT64 hash, const DWORD *rs, const DWORD *ids, int n);
void look_merge_draw(IDirect3DDevice8 *dev, UINT nverts, UINT first, UINT tris);
void look_merge_end(IDirect3DDevice8 *dev);
void merge_install(IDirect3DDevice8 *dev);
int merge_draw(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT start, UINT count);
void merge_flush(IDirect3DDevice8 *dev);
void merge_frame(IDirect3DDevice8 *dev);
void merge_reset(void);
void merge_device_reset(void);
int merge_on_backbuffer(void);
void merge_state_changed(void);
void merge_stage_state(DWORD stage, DWORD type, DWORD value);
void merge_vb_created(IDirect3DVertexBuffer8 *vb);
void merge_texture_gone(IDirect3DBaseTexture8 *t);
extern int merge_stat_pieces, merge_stat_draws;
IDirect3DBaseTexture8 *textures_effective(IDirect3DBaseTexture8 *game);
int textures_scrolling(IDirect3DBaseTexture8 *t);
void capture_world(IDirect3DDevice8 *dev, int api, D3DPRIMITIVETYPE type, UINT count, UINT first, UINT nverts, UINT start_index,
                   const void *data, UINT stride, const void *idx, D3DFORMAT fmt);
UINT64 textures_bound_hash(DWORD stage);
IDirect3DBaseTexture8 *textures_bound(DWORD stage);
int smooth_character(IDirect3DDevice8 *dev);
void mesh_forget(IDirect3DVertexBuffer8 *vb);
void mesh_shader_created(IDirect3DDevice8 *dev, DWORD h, const DWORD *fn);
void mesh_shader_deleted(IDirect3DDevice8 *dev, DWORD h);
HRESULT mesh_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                  HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT));
extern DWORD presents; // frames shown so far
extern const DWORD smooth_decl[8];
extern int style_player;
void style_shader_created(DWORD h, const DWORD *fn);
void style_shader_deleted(DWORD h);
int style_is_player(IDirect3DVertexBuffer8 *vb);
HRESULT style_draw(IDirect3DDevice8 *dev, D3DPRIMITIVETYPE type, UINT start, UINT count,
                   HRESULT (WINAPI *draw)(IDirect3DDevice8 *, D3DPRIMITIVETYPE, UINT, UINT));
