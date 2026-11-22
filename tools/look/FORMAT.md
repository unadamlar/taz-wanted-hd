# Look data, version 3

Written by `tools/look/export.py`, read by `src/d3d8/look.c`. Installed per scene:

```
<game>/taz-hd/look/scene<NN>/
  scene.bin   geometry, instances, materials, bindings to the game's textures
  level.ini   lighting and grade; re-read when a taz-hd\look-reload file appears
  sky.dds     cube map, A8R8G8B8 sRGB, 1024 per face, full mips
  tex/*.dds   DXT1 (opaque) or DXT5 (alpha), full mips; normal maps are DXT5 with x in alpha, y in green
```

Everything is little-endian. Positions are in game space (y up, 250 units = 1 Blender unit).

## scene.bin

```
char magic[4] = "TZLK"; u32 version = 3
u32 nhide;  u64 hide[nhide]    game textures whose draws are dropped from level 1 up
u32 nshade; u64 shade[nshade]  baked shadow decals, dropped once real shadows are on
u32 nmat;   material mat[nmat]
u32 nbind;  bind binds[nbind]
u32 nproto; proto protos[nproto]
u32 nchunk; chunk chunks[nchunk]
u32 nlight; light lights[nlight]   optional: a level without lamps or glows ends at the chunks
u32 nglow;  glow glows[nglow]
```

```
material (128 bytes)
  char name[32], albedo[32], normal[32]   texture names without .dds; empty = none
  u16  kind    0 opaque, 1 card (alpha cut), 2 grass, 3 water
  u16  flags   1 triplanar, 2 two-sided, 4 wind
  f32  tile    game units per texture repeat; 0 = use the mesh UVs
  f32  tint[3] linear multiplier
  f32  rough
  f32  normal_strength
  f32  alpha_cut

bind (24 bytes): how a game texture's world surface gets a material
  u64 fingerprint
  u32 material
  u32 mask     0 whole surface
               1 where the game texture is redder than green (painted dirt; grass paint stays)
               2 where its brightness is above the threshold (brick faces, not mortar)
               3 where its lowest channel is above the threshold (pale trim painted on brick)
  f32 lo, hi   smoothstep range for the mask
               x = r - g (mask 1), 0.3r + 0.59g + 0.11b (mask 2) or min(r, g, b) (mask 3), on the game texture's raw sRGB values
               t = saturate((x - lo) / (hi - lo)); m = t * t * (3 - 2 * t). lo > hi inverts the mask.
               A fingerprint can have several binds: apply them in file order, each over the last.
               Where the masks leave a pixel uncovered, the game's texture shows.

proto
  u32 nv, ni, nsub
  vertex v[nv]      f32 pos[3], f32 normal[3], u32 color (BGRA, sRGB), f32 uv[2]   (36 bytes)
  u32 index[ni]
  sub s[nsub]       u32 material, first_index, index_count

chunk
  f32 lo[3], hi[3]  world bounds
  u32 nruns
  run               u32 proto, n; f32 rows[n][12]   3x4 instance matrices, shuffled so a prefix thins evenly

light (32 bytes): a street lamp or a pool of light; at most 64
  f32 pos[3], radius   falloff (1 - d^2 / r^2)^2
  f32 color[3]         linear, multiplies albedo directly
  f32 cone             cosine from straight down where it starts to fade; -1 lights all round

glow (24 bytes): a game texture that emits, added after lighting
  u64 fingerprint
  f32 strength, lo, hi over the texture's own colour; lo, hi as a bind's smoothstep on brightness
  u32 mask             0 the whole texture, 2 by brightness
```

Conventions:

- A vertex colour multiplies the albedo; on a material with no albedo it is the colour.
- tile > 0 maps by world position: triplanar with the flag, else top-down on world x, z. Row 0 of a DDS is the top of
  the image and v runs down, so on walls v = -y / tile keeps a texture upright. Mesh UVs are already in this convention.
- Normal maps are tangent space with +x along +u and +y towards the top of the image (OpenGL style).
- sky.dds is sampled with the game-space view direction as is.

## level.ini

One `[level]` section, floats, colours linear RGB as three numbers:

```
sun_dir, sun_color, sky_ambient, ground_ambient
shadow_softness, ao_radius, ao_strength
fog_color, fog_start, fog_end
exposure, bloom_threshold, bloom_strength, saturation, contrast
water_height, water_color, water_clarity
grass_fade_start, grass_fade_end
sky_scale
unbake     optional. Above 0 the game's vertex colours are baked light (a night level): their tint is dropped
           and their brightness v becomes v^unbake
char_fill  optional, three numbers: extra ambient on characters only, so they read away from a night level's lamps
```

- sun_dir points towards the sun, in game space. sun_color already includes the 1/pi: diffuse = albedo * sun_color * N.L.
- Sky samples are linear after sRGB decoding; multiply them by sky_scale (clouds are brighter than 1).
- exposure is a linear multiplier. Fog is linear from fog_start to fog_end, in game units.
- water_clarity: 0 opaque, 1 clear, looking straight down.

Change this file together with both sides of the format.
