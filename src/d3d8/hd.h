// Look level 4: the renderer on the real Direct3D 9 device. No Direct3D 8 types here, since d3d8.h and
// d3d9.h can't be in one file: look.c classifies the game's draws, hd.c does the rendering.
#pragma once
struct IDirect3DDevice9;
typedef struct IDirect3DDevice9 *hd_dev;
struct IDirect3DVertexBuffer9;
struct IDirect3DIndexBuffer9;

int hd_load(hd_dev d, int scene);       // 0: no data for this scene
void hd_unload(void);
int hd_loaded(void);
void hd_reset(void);                    // before a device Reset
int capture_tests(void);                // tests=1 in the ini
int hd_lost(void);                      // since the last call, a Reset dropped the scene's data
int hd_hidden(unsigned long long hash); // a game texture whose world draws are dropped
int hd_has_bind(unsigned long long hash);
int hd_shade(unsigned long long hash);  // a baked shadow decal, dropped everywhere

void hd_redirect(hd_dev d);             // the game's next 3D draws land in our HDR target
void hd_rebind(hd_dev d);               // the game set the back buffer again
int hd_redirected(void);
int hd_post_done(void);
void hd_post(hd_dev d);                 // resolve, bloom, tone map to the back buffer
void hd_frame_end(hd_dev d);

void hd_camera(hd_dev d);               // reads the game's view and projection
const float *hd_view(void);             // 4x4
const float *hd_proj(void);

// Depth of the world and additions (AO, water), once per frame, before the world is shaded.
int hd_prepass_needed(void);
void hd_prepass_begin(hd_dev d);
void hd_prepass_end(hd_dev d);

// Static sun map, built once per scene from the same draws.
int hd_shadow_needed(void);
void hd_shadow_begin(hd_dev d);
void hd_shadow_end(hd_dev d);

// Characters' sun map, per frame.
void hd_cmap_begin(hd_dev d, const float *centre);
const float *hd_cmap_clip(void);        // 4x4 clip rows
void hd_cmap_draw(hd_dev d, struct IDirect3DVertexBuffer9 *v, unsigned stride, int type, unsigned start, unsigned count,
                  const float *bones, const float *light, int nbones);
void hd_cmap_end(hd_dev d);

// Game surfaces through our shaders.
void hd_world_begin(hd_dev d, const float *world);  // saves state, sets shaders' common state
void hd_world_material(hd_dev d, unsigned long long hash);
void hd_world_end(hd_dev d);
void hd_world_quick(hd_dev d, const float *world, unsigned long long hash); // one draw: no state save
int hd_swapped(unsigned long long h, const float *at); // at NULL: on any replaced object
void hd_world_float(hd_dev d, float y); // after hd_world_quick: nothing below y
void hd_world_quick_end(hd_dev d);
void hd_merge_buffers(hd_dev d, struct IDirect3DVertexBuffer9 *v, struct IDirect3DIndexBuffer9 *i);
void hd_merge_draw(hd_dev d, unsigned nverts, unsigned first, unsigned tris);
void hd_invalidate(void);                 // the game changed the camera or wrote our constants
void hd_sky(hd_dev d);                  // once per frame, before the game's first 3D draw
void hd_additions(hd_dev d);            // additions and water, once per frame after the first world flush
int hd_additions_done(void);

// One additive game sprite, blended so it can't burn out.
void hd_glow_begin(hd_dev d, float scale, float strength);
void hd_glow_end(hd_dev d, unsigned long dest_blend);

// Characters: pixel shader and constants around one draw.
struct IDirect3DTexture9;
void hd_char_begin(hd_dev d, const float *model_rows, float use_tex, float use_colour, float scale, const float *style, struct IDirect3DTexture9 *fur);
void hd_char_end(hd_dev d);
