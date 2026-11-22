// Look level 4, the world: game surfaces, instanced additions, sky, depth, characters.
// Colour leaves these shaders gamma-encoded (HDR kept above 1), so MSAA edges resolve like the game's
// own draws, which land in the same target. post.hlsl decodes it.

// Vertex constants
float4 VP[4]     : register(c0);    // clip rows
float4 WORLD[3]  : register(c10);   // game draws: world rows
float4 EYE_TIME  : register(c13);
float4 WIND      : register(c14);   // strength, speed, grass fade start, 1 / fade length
float4 PRESS     : register(c15);   // the player, 1 / radius of the grass pressed under his feet

// Pixel constants
float4 SUN       : register(c0);
float4 SUN_COL   : register(c1);
float4 SKY_AMB   : register(c2);
float4 GND_AMB   : register(c3);
float4 FOG_COL   : register(c4);    // rgb, w start
float4 FOG       : register(c5);    // 1 / length, water clarity, water height, softness in texels
float4 EYE       : register(c6);
float4 SCREEN    : register(c7);    // 1 / w, 1 / h, AO strength, 1 / depth far
float4 SROW[3]   : register(c8);    // static shadow rows
float4 CROW[3]   : register(c11);   // character shadow rows
float4 TEXEL     : register(c14);   // static texel, character texel
float4 WATER     : register(c15);
float4 MAT       : register(c16);   // 1 / tile, normal strength, roughness, alpha cut
float4 TINT      : register(c17);
float4 MASK      : register(c18);   // mode, lo, 1 / (hi - lo), triplanar
float4 MAT2      : register(c19);   // second bind of the same game texture, over the first
float4 TINT2     : register(c20);
float4 MASK2     : register(c21);
float4 MWEIGHT   : register(c22);
float4 MWEIGHT2  : register(c23);
float4 CHARK     : register(c24);   // characters: texture on, colour on, scale, as the game's stage 0
float4 EMIT      : register(c26);   // glow: strength, lo, 1 / (hi - lo); w: baked-light exponent, 0 keeps vertex colours
float4 HOLD      : register(c28);   // x: how much painted surfaces keep their colour through the tone curve; y exposure, z contrast, w lowest shadowed height
float4 LGRID     : register(c27);   // lights: grid x0, z0, 1 / cell, 1 if the level has any

float4 NEAR      : register(c32);   // x: 1 in the blended near pass; y: 1 keep far side, -1 keep near side

sampler2D BASE     : register(s0);
sampler2D TNORMAL  : register(s8);
sampler2D TALBEDO  : register(s9);
samplerCUBE SKY    : register(s10);
sampler2D SHADOW   : register(s11);
sampler2D CSHADOW  : register(s12);
sampler2D AO       : register(s13);
sampler2D DEPTH    : register(s7);
sampler2D TALBEDO2 : register(s14);
sampler2D TNORMAL2 : register(s15);
sampler2D LIGHTS   : register(s6);   // 64 wide: rows 0-63 the grid (up to 4 light numbers + 1), row 64 position, 1 / r^2, row 65 colour, cone

float3 to_linear(float3 c) { return c * c * (0.3 * c + 0.7); }
float3 to_gamma(float3 c)  { return pow(max(c, 0.00001), 1 / 2.2); }

struct WorldIn { float4 p : POSITION; float3 n : NORMAL; float4 c : COLOR0; float2 uv : TEXCOORD0; };
struct InstIn  { float4 p : POSITION; float3 n : NORMAL; float4 c : COLOR0; float2 uv : TEXCOORD0;
                 float4 r0 : TEXCOORD1; float4 r1 : TEXCOORD2; float4 r2 : TEXCOORD3; };
struct V2P     { float4 p : POSITION; float2 uv : TEXCOORD0; float4 wp : TEXCOORD1; float3 n : TEXCOORD2; float4 c : COLOR0; };

float4 clip_of(float3 w)
{
    float4 q = float4(w, 1);
    return float4(dot(VP[0], q), dot(VP[1], q), dot(VP[2], q), dot(VP[3], q));
}

float4 WATERLINE : register(c16);

V2P vs_world(WorldIn i)
{
    V2P o;
    float4 q = float4(i.p.xyz, 1);
    float3 w = float3(dot(WORLD[0], q), dot(WORLD[1], q), dot(WORLD[2], q));
#ifdef AT_WATERLINE
    w.y = max(w.y, WATERLINE.x);  // drawn after the water, so what floats below it would show through
#endif
    o.n = float3(dot(WORLD[0].xyz, i.n), dot(WORLD[1].xyz, i.n), dot(WORLD[2].xyz, i.n));
    o.p = clip_of(w);
    o.wp = float4(w, o.p.w);
    o.uv = i.uv;
    // The game's baked shade is lilac 109/100/127 on lit grey 127: real shadows replace it.
    float3 d = i.c.rgb - float3(109, 100, 127) / 255;
    o.c = float4(dot(d, d) < 0.0005 ? float3(0.498, 0.498, 0.498) : i.c.rgb, i.c.a);
    return o;
}

V2P vs_inst(InstIn i)
{
    V2P o;
    float4 q = float4(i.p.xyz, 1);
    float3 w = float3(dot(i.r0, q), dot(i.r1, q), dot(i.r2, q));
    float3 root = float3(i.r0.w, i.r1.w, i.r2.w);
    float dist = length(root - EYE_TIME.xyz);
#ifdef GRASS
    // Blades sink into the ground as they fade, so distance never pops.
    float rnd = frac(dot(root.xz, float2(0.7131, 0.5293)));
    float fade = saturate((1 - (dist - WIND.z) * WIND.w) * 2 - rnd);
    float2 away = root.xz - PRESS.xz;
    float near_feet = saturate(1 - length(away) * PRESS.w) * saturate(1 - abs(root.y - PRESS.y) / 300);
    w.y = root.y + (w.y - root.y) * fade * (1 - 0.72 * near_feet);
    w.xz += away * near_feet * saturate((w.y - root.y) / 20) * 0.35;
#endif
#ifdef WINDY
    float h = saturate((w.y - root.y) / 60);
    float t = EYE_TIME.w * WIND.y + dot(root.xz, float2(0.0031, 0.0023));
    float s = sin(t) + 0.5 * sin(2.3 * t + 1.1);
    w.xz += float2(0.8, 0.5) * WIND.x * s * h * h;
#endif
    o.n = float3(dot(i.r0.xyz, i.n), dot(i.r1.xyz, i.n), dot(i.r2.xyz, i.n));
    o.p = clip_of(w);
#ifdef GRASS
    o.wp = float4(w, fade);
#else
    o.wp = float4(w, o.p.w);
#endif
#ifdef WATER_SURFACE
    o.p.z = 0.5 * o.p.w; // ps_water writes the real depth, so the near plane can't cut a hole by a low camera
#endif
    o.uv = i.uv;
    o.c = i.c;
    return o;
}

struct DepthOut { float4 p : POSITION; float2 uv : TEXCOORD0; float z : TEXCOORD1; };

DepthOut vs_world_depth(WorldIn i)
{
    DepthOut o;
    float4 q = float4(i.p.xyz, 1);
    o.p = clip_of(float3(dot(WORLD[0], q), dot(WORLD[1], q), dot(WORLD[2], q)));
    o.uv = i.uv;
    o.z = o.p.w;
    return o;
}

DepthOut vs_inst_depth(InstIn i)
{
    DepthOut o;
    V2P v = vs_inst(i);
    o.p = v.p;
    o.uv = i.uv;
    o.z = v.p.w;
    return o;
}

// Depth pass: linear depth for AO and the water, cut by the texture's alpha.
float4 ps_depth(DepthOut i) : COLOR
{
    clip(tex2D(BASE, i.uv).a - MAT.w);
    return i.z;
}

float tap(float2 uv, float z, float2 d) { return tex2Dproj(SHADOW, float4(uv + d, z, 1)).r; }
float ctap(float2 uv, float z, float2 d) { return tex2Dproj(CSHADOW, float4(uv + d, z, 1)).r; }

// Twelve filtered taps, the disc turned per pixel.
float sun_shadow(float3 w, float2 vpos)
{
    float4 q = float4(w, 1);
    float3 s = float3(dot(SROW[0], q), dot(SROW[1], q), dot(SROW[2], q));
    float3 c = float3(dot(CROW[0], q), dot(CROW[1], q), dot(CROW[2], q));
    float a = frac(52.9829 * frac(dot(vpos, float2(0.0671, 0.00584)))) * 6.2832;
    float2 r = float2(cos(a), sin(a)), u = float2(-r.y, r.x);
    float2 k = FOG.w * TEXEL.x, m = 1.6 * TEXEL.y;
    float lit = tap(s.xy, s.z, k * (0.18 * r + 0.10 * u)) + tap(s.xy, s.z, k * (-0.31 * r + 0.22 * u))
              + tap(s.xy, s.z, k * (0.45 * r - 0.26 * u)) + tap(s.xy, s.z, k * (-0.12 * r - 0.58 * u))
              + tap(s.xy, s.z, k * (0.63 * r + 0.39 * u)) + tap(s.xy, s.z, k * (-0.71 * r + 0.34 * u))
              + tap(s.xy, s.z, k * (0.26 * r + 0.84 * u)) + tap(s.xy, s.z, k * (-0.49 * r - 0.78 * u))
              + tap(s.xy, s.z, k * (0.93 * r - 0.17 * u)) + tap(s.xy, s.z, k * (-0.97 * r - 0.12 * u))
              + tap(s.xy, s.z, k * (0.52 * r - 0.83 * u)) + tap(s.xy, s.z, k * (0.05 * r + 0.99 * u));
    float ch = ctap(c.xy, c.z, m * (0.5 * r + 0.5 * u)) + ctap(c.xy, c.z, m * (-0.5 * r + 0.5 * u))
             + ctap(c.xy, c.z, m * (0.5 * r - 0.5 * u)) + ctap(c.xy, c.z, m * (-0.5 * r - 0.5 * u));
    return lit / 12 * (ch / 4);
}

// Street lamps: the grid cell under the point names the few that reach it, so the cost doesn't grow with their number.
float3 local_lights(float3 n, float3 w)
{
    float3 sum = 0;
    if (LGRID.w > 0) {
        float2 g = floor((w.xz - LGRID.xy) * LGRID.z);
        if (g.x >= 0 && g.y >= 0 && g.x < 64 && g.y < 64) {
            float4 ids = tex2Dlod(LIGHTS, float4((g + 0.5) / float2(64, 128), 0, 0));
            for (int k = 0; k < 4; k++) {
                float id = k == 0 ? ids.x : k == 1 ? ids.y : k == 2 ? ids.z : ids.w;
                if (id < 0.5) break;
                float u = (id - 0.5) / 64;
                float4 p = tex2Dlod(LIGHTS, float4(u, 64.5 / 128, 0, 0)), col = tex2Dlod(LIGHTS, float4(u, 65.5 / 128, 0, 0));
                float3 d = p.xyz - w;
                float l2 = dot(d, d), fall = saturate(1 - l2 * p.w);
                float3 dir = d / sqrt(max(l2, 1));
                float cone = saturate((dir.y - col.w) / max(1 - col.w, 0.01) * 4);
                sum += col.rgb * fall * fall * cone * saturate(dot(n, dir) * 0.8 + 0.2);
            }
        }
    }
    return sum;
}

float3 shade(float3 albedo, float3 n, float3 w, float2 vpos, float ao, float spec_mask)
{
    float3 v = normalize(EYE.xyz - w);
    float nl = saturate(dot(n, SUN.xyz));
    float sh = nl > 0 ? sun_shadow(w, vpos) : 0;
    float3 amb = lerp(GND_AMB.rgb, SKY_AMB.rgb, n.y * 0.5 + 0.5) * ao;
    float3 h = normalize(v + SUN.xyz);
    float gloss = 2 / max(MAT.z * MAT.z * MAT.z * MAT.z, 0.002);
    float sp = spec_mask * pow(saturate(dot(n, h)), gloss) * (gloss + 2) * 0.012;
    // Shadows dim lamps too: removing only the blue moonlight left a yellow stain in lamp pools.
    float3 lamps = local_lights(n, w) * (nl > 0 ? 0.6 + 0.4 * sh : 1);
    return albedo * (amb + SUN_COL.rgb * nl * sh + lamps) + SUN_COL.rgb * sp * nl * sh;
}

float3 fogged(float3 c, float3 w)
{
    float f = saturate((distance(w, EYE.xyz) - FOG_COL.w) * FOG.x);
    return lerp(c, FOG_COL.rgb, f);
}

// Tangent space, x along +u, y towards the top of the image.
float3 unpack_normal(float4 t, float strength)
{
    float2 xy = (float2(t.a, t.g) * 2 - 1) * strength;
    return float3(xy, sqrt(saturate(1 - dot(xy, xy))));
}

float3 detail_normal(float2 uv) { return unpack_normal(tex2D(TNORMAL, uv), MAT.y); }

// World-mapped material: from above (u = x, v = z), or from three axes with v = -y on walls.
#define WORLD_MATERIAL(name, A, N, M, K)                                                                       \
void name(float3 w, float3 n, out float3 albedo, out float3 nor)                                               \
{                                                                                                              \
    float k = M.x;                                                                                             \
    if (K > 0.5) {                                                                                             \
        float3 b = pow(abs(n), 6);                                                                             \
        b /= b.x + b.y + b.z;                                                                                  \
        float2 ux = float2(w.z, -w.y) * k, uy = w.xz * k, uz = float2(w.x, -w.y) * k;                          \
        albedo = to_linear(tex2D(A, ux).rgb * b.x + tex2D(A, uy).rgb * b.y + tex2D(A, uz).rgb * b.z);          \
        float3 tx = unpack_normal(tex2D(N, ux), M.y), ty = unpack_normal(tex2D(N, uy), M.y), tz = unpack_normal(tex2D(N, uz), M.y); \
        float3 sn = sign(n);                                                                                   \
        float3 dx = float3(sn.x * tx.z - sn.x, tx.y, tx.x), dy = float3(ty.x, sn.y * ty.z - sn.y, -ty.y), dz = float3(tz.x, tz.y, sn.z * tz.z - sn.z); \
        nor = normalize(n + dx * b.x + dy * b.y + dz * b.z);                                                   \
    } else {                                                                                                   \
        albedo = to_linear(tex2D(A, w.xz * k).rgb);                                                            \
        float3 t = unpack_normal(tex2D(N, w.xz * k), M.y);                                                     \
        nor = normalize(n + float3(t.x, t.z - 1, -t.y));                                                       \
    }                                                                                                          \
}
WORLD_MATERIAL(material, TALBEDO, TNORMAL, MAT, MASK.w)
WORLD_MATERIAL(material2, TALBEDO2, TNORMAL2, MAT2, MASK2.w)

// The mask's x is a weighted sum (r - g, or brightness) plus w times the lowest channel; lo > hi inverts.
float bind_mask(float3 raw, float4 w, float4 mk)
{
    float t = saturate((dot(raw, w.xyz) + w.w * min(raw.r, min(raw.g, raw.b)) - mk.y) * mk.z);
    return t * t * (3 - 2 * t);
}

// A normal map on mesh UVs: the tangent frame comes from screen derivatives.
float3 uv_normal(float3 n, float3 w, float2 uv)
{
    float3 dx = ddx(w), dy = ddy(w);
    float2 ux = ddx(uv), uy = ddy(uv);
    float3 px = cross(dy, n), py = cross(n, dx);
    float3 t = px * ux.x + py * uy.x, b = px * ux.y + py * uy.y;
    float scale = sqrt(max(max(dot(t, t), dot(b, b)), 1e-12));
    float3 m = detail_normal(uv);
    return normalize(t / scale * m.x - b / scale * m.y + n * m.z);
}

// The scene value the tone curve (post.hlsl film) turns into this colour.
float3 held(float3 c)
{
    float3 s = clamp(pow(saturate(to_gamma(c)), 1 / HOLD.z) - 0.5, -0.47, 0.44);
    float3 x = s / sqrt(1 - 4 * s * s) / 2.4 + 0.606;
    return 0.18 * pow(2, 16.5 * x - 10) / HOLD.y;
}

float4 ps_world(V2P i, float2 vpos : VPOS) : COLOR
{
    float4 tex = tex2D(BASE, i.uv);
    float3 vc = i.c.rgb;
    // A night level's colour is baked into its vertices as blue light: keep how bright, not the tint.
    if (EMIT.w > 0) vc = pow(saturate(max(vc.r, max(vc.g, vc.b)) * 2), EMIT.w) * 0.5;
    float3 game = to_linear(saturate(tex.rgb * vc * 2));
    float3 n = normalize(i.n);
    float3 albedo = game, nor = n;
    float spec = 0;
#ifdef MATERIAL
    float m = bind_mask(tex.rgb, MWEIGHT, MASK);
    float3 ma, mn;
    material(i.wp.xyz, n, ma, mn);
    albedo = lerp(game, ma * TINT.rgb * (MASK.x > 3.5 ? game : 1), m);  // mask 4: the game's paint with this grain
    nor = normalize(lerp(n, mn, m));
    spec = m * (1 - MAT.z);
#ifdef MATERIAL2
    float m2 = bind_mask(tex.rgb, MWEIGHT2, MASK2);
    material2(i.wp.xyz, n, ma, mn);
    albedo = lerp(albedo, ma * TINT2.rgb * (MASK2.x > 3.5 ? game : 1), m2);
    nor = normalize(lerp(nor, mn, m2));
    spec = lerp(spec, 1 - MAT2.z, m2);
#endif
#endif
    float ao = lerp(1, tex2D(AO, (vpos + 0.5) * SCREEN.xy).r, SCREEN.z);
    float3 c = shade(albedo, nor, i.wp.xyz, vpos, ao, spec);
    if (HOLD.x > 0) {
        // Below HOLD.w the doors' shadows would only streak down the outside of the planet.
        float sh = i.wp.y > HOLD.w ? sun_shadow(i.wp.xyz, vpos) : 1;
        float light = (0.62 + 0.6 * saturate(dot(nor, SUN.xyz))) * lerp(0.62, 1, sh) * ao;
        c = lerp(c, held(albedo) * light + shade(0, nor, i.wp.xyz, vpos, ao, spec), HOLD.x);
    }
    if (EMIT.x > 0) { // lit windows and signs
        float t = saturate((dot(tex.rgb, float3(0.3, 0.59, 0.11)) - EMIT.y) * EMIT.z);
        c += to_linear(tex.rgb) * t * t * (3 - 2 * t) * EMIT.x;
    }
    return float4(to_gamma(fogged(c, i.wp.xyz)), tex.a * i.c.a * 2);
}

// Additions: card, grass or solid.
float4 ps_inst(V2P i, float2 vpos : VPOS, float face : VFACE) : COLOR
{
    // What the camera is about to pass through fades out. The normal pass keeps the far side of the fade (NEAR.y 1),
    // a blended pass at the end of the 3D draws the near side (NEAR.y -1), so no dots show.
    float closeness = saturate((distance(EYE.xyz, i.wp.xyz) - 45) / 130);
    clip((closeness - 0.999) * NEAR.y);
#ifdef TILED
    float3 tiled, tn;
    float3 fn = normalize(i.n);
    fn = dot(fn, EYE.xyz - i.wp.xyz) < 0 ? -fn : fn;
    material(i.wp.xyz, fn, tiled, tn);
    float4 tex = 1;
#else
    float4 tex = tex2D(BASE, i.uv);
#endif
#ifdef CUT
    // Sharpened alpha: the edge stays one pixel wide at any mip, for alpha to coverage.
    float cut = (tex.a - MAT.w) / max(fwidth(tex.a), 0.0001) + 0.5;
    #ifdef GRASS
    cut *= saturate(i.wp.w * 4);
    #endif
    clip(cut);
    cut = saturate(cut);
#else
    float cut = 1;
#endif
    float3 albedo = to_linear(tex.rgb * i.c.rgb) * TINT.rgb;
    float3 n = normalize(i.n);
    n = dot(n, EYE.xyz - i.wp.xyz) < 0 ? -n : n; // two-sided, and instance matrices can mirror
#ifdef TILED
    albedo = tiled * to_linear(i.c.rgb) * TINT.rgb;
    n = tn;
#elif !defined(CUT)
    n = uv_normal(n, i.wp.xyz, i.uv);
#endif
#ifdef CUT
    // Thin leaves let some sun through, so their shaded side isn't dead.
    float through = saturate(dot(-n, SUN.xyz)) * 0.35;
    n = normalize(n + float3(0, 0.6, 0));
#else
    float through = 0;
#endif
    float ao = lerp(1, tex2D(AO, (vpos + 0.5) * SCREEN.xy).r, SCREEN.z);
    float3 c = shade(albedo, n, i.wp.xyz, vpos, ao, 0);
    c += albedo * SUN_COL.rgb * through * sun_shadow(i.wp.xyz, vpos);
    return float4(to_gamma(fogged(c, i.wp.xyz)), cut * lerp(1, closeness, NEAR.x));
}

// Short white dashes on the water: at most one per grid cell, each lying along the current and glinting in its own time.
float dashes(float2 p, float t)
{
    p = float2(p.x * 0.91 + p.y * 0.42, p.y * 0.91 - p.x * 0.42) + float2(0.018, 0.006) * t;
    float2 cell = floor(p);
    float r = frac(sin(dot(cell, float2(12.9898, 78.233))) * 43758.5453);
    float2 d = (frac(p) - float2(0.2 + 0.6 * r, 0.2 + 0.6 * frac(r * 7.3))) / float2(0.1, 0.028);
    float soft = max(fwidth(p.y) / 0.028, 0.25);
    return saturate((1 - length(d)) / soft) * saturate(sin(t * (0.5 + r) + r * 40) * 2.6 - 0.7);
}

// Water on the game's own surface: depth colour over the bed, sky reflection, soft shore.
// A redrawn backdrop panel: unlit, its painted colour held through the tone curve.
float4 ps_space(float2 uv : TEXCOORD0) : COLOR
{
    float3 c = tex2D(BASE, uv).rgb;
    float peak = max(c.r, max(c.g, c.b)), low = min(c.r, min(c.g, c.b));
    // a saturated colour held near white comes out of the tone curve pink, so it stops a little lower
    c *= min(1, (0.72 + 0.28 * low / max(peak, 0.01)) / max(peak, 0.01));
    c = held(to_linear(c));
    float l = dot(c, float3(0.2126, 0.7152, 0.0722));
    return float4(to_gamma(max(l + (c - l) / 0.86, 0)), 1); // the curve's own desaturation, undone
}

// The dome: clear glass with a sheen at grazing angles and the sun's glint, or its steel frame (MAT.y 1). Like the game's,
// what is right by the camera doesn't draw, so no bar crosses the view.
float4 ps_glass(V2P i, float2 vpos : VPOS) : COLOR
{
    float3 v = normalize(EYE.xyz - i.wp.xyz), n = normalize(i.n);
    if (dot(n, v) < 0) n = -n;
    float far = saturate((distance(EYE.xyz, i.wp.xyz) - 520) / 360);
    far *= far * (3 - 2 * far);
    if (MAT.y > 0.5) return float4(to_gamma(shade(TINT.rgb, n, i.wp.xyz, vpos, 1, 1 - MAT.z)) * far, far);
    float3 r = reflect(-v, n);
    float f = 0.03 + 0.5 * pow(1 - saturate(dot(n, v)), 4);
    float up = saturate(r.y * 0.5 + 0.5), sun = saturate(dot(r, SUN.xyz));
    float3 sheen = lerp(float3(0.05, 0.07, 0.2), float3(0.55, 0.7, 1.0), up * up) * f + SUN_COL.rgb * (pow(sun, 120) * 0.05 + pow(sun, 1500) * 5);
    return float4(to_gamma(sheen) * far, f * far);
}

float4 ZPROJ : register(c33); // projection's z scale and offset

float4 ps_water(V2P i, float2 vpos : VPOS, out float z : DEPTH) : COLOR
{
    z = saturate(ZPROJ.x + ZPROJ.y / i.wp.w);
    float3 v = normalize(EYE.xyz - i.wp.xyz);
    float t = EYE.w;
    float2 p = i.wp.xz * MAT.x;
    float3 a = detail_normal(p + float2(0.021, 0.013) * t), b = detail_normal(p * 1.7 - float2(0.017, 0.026) * t);
    float3 n = normalize(float3(a.x + b.x, 2.5, -a.y - b.y));
    float bed = tex2D(DEPTH, (vpos + 0.5) * SCREEN.xy).r;
    float depth = max(bed - i.wp.w, 0);
    float clear = FOG.y * exp(-depth * 0.0012);  // water_clarity: what shows through, looking straight down
    float shore = saturate(depth * 0.02);
    float fres = 0.03 + 0.97 * pow(1 - saturate(dot(n, v)), 5);
    float3 r = reflect(-v, n);
    r.y = abs(r.y);
    float3 sky = to_linear(texCUBE(SKY, r).rgb) * SKY_AMB.w;
    float nl = saturate(dot(n, SUN.xyz));
    float lit = sun_shadow(i.wp.xyz, vpos);
    float3 body = WATER.rgb * (1.5 * SKY_AMB.rgb + 1.2 * SUN_COL.rgb * nl * lit);
    float3 h = normalize(v + SUN.xyz);
    float3 glint = SUN_COL.rgb * pow(saturate(dot(n, h)), 400) * 2;
    float fleck = saturate(dashes(i.wp.xz / 210, t) + dashes(i.wp.zx / 330 + 0.37, t * 0.8)) * lit * shore;
    float alpha = saturate((1 - clear) * 0.62 + fres) * shore;
    float3 c = lerp(body, sky, fres) + glint * shore + (1.5 * SUN_COL.rgb + SKY_AMB.rgb) * fleck;
    return float4(to_gamma(fogged(c, i.wp.xyz)), saturate(max(alpha, 0.04 * shore) + fleck));
}

// Sky: a full-screen triangle at the far plane; rays from the inverse camera in c4-c6.
float4 RAY[3] : register(c4);
struct SkyOut { float4 p : POSITION; float3 ray : TEXCOORD0; };

SkyOut vs_sky(float4 p : POSITION)
{
    SkyOut o;
    o.p = float4(p.xy, 1, 1);
    o.ray = float3(dot(RAY[0], float4(p.xy, 1, 0)), dot(RAY[1], float4(p.xy, 1, 0)), dot(RAY[2], float4(p.xy, 1, 0)));
    return o;
}

float4 ps_sky(SkyOut i) : COLOR
{
    float3 c = to_linear(texCUBE(SKY, normalize(i.ray)).rgb);
    return float4(to_gamma(c * SKY_AMB.w), 1);
}

// The game's additive sprites (glows, sparkles, flames) are blended as a screen: src + dst * (1 - src). Plain
// addition has no ceiling in a float target, so stacked sprites burned to white and flooded the bloom.
float4 GLOW : register(c25);   // x: the game's stage 0 scale, y: strength

float4 ps_glow(float2 uv : TEXCOORD0, float4 col : COLOR0) : COLOR
{
    float4 c = saturate(tex2D(BASE, uv) * col * GLOW.x);
    // The faint skirt of many stacked sprites is what hazes the view, so it is cut; the core keeps its gold through
    // the tone curve, which would otherwise wash it to cream.
    float a = saturate((c.a - 0.14) / 0.5);
    a = a * a * (3 - 2 * a);
    c.rgb = pow(c.rgb, float3(0.8, 1.2, 2.2));
    return float4(saturate(c.rgb * a * GLOW.y), a);
}

// Characters into the sun map: the game's skinning (palette offsets are register numbers), our own shader.
float4 BONES[48]  : register(c0);
float4 LIGHT[4]   : register(c92);
float4 NBONES     : register(c96);

float4 vs_char_depth(float3 p : POSITION, float3 weight : TEXCOORD1, float4 palette : TEXCOORD2) : POSITION
{
    float4 q = float4(p, 1), m = 0;
    float3 w = weight;
    w.z *= step(2.5, NBONES.x);
    w.y *= step(1.5, NBONES.x);
    w /= max(w.x + w.y + w.z, 0.001);
    for (int k = 0; k < 3; k++) {
        int b = (int)(palette[k] + 0.5);
        m.xyz += w[k] * float3(dot(BONES[b], q), dot(BONES[b + 1], q), dot(BONES[b + 2], q));
    }
    m.w = 1;
    return float4(dot(LIGHT[0], m), dot(LIGHT[1], m), dot(LIGHT[2], m), dot(LIGHT[3], m));
}

// Characters: the game's vs_1_1 skinning, patched to also output world position (oT2) and normal (oT3).
struct CharIn { float2 uv : TEXCOORD0; float3 w : TEXCOORD2; float3 n : TEXCOORD3; float3 bp : TEXCOORD4; float3 bn : TEXCOORD5; float4 c : COLOR0; };
float4 CHAR_LIGHT[4] : register(c26);  // the two nearest lamps: position, 1 / r^2; colour
float4 CHAR_STYLE    : register(c31);  // shading band offset, slope, fur strength, highlight
sampler2D FUR : register(s5);
float4 CHAR_FILL     : register(c30);  // keeps characters readable away from the lamps of a night level

float4 ps_char(CharIn i) : COLOR
{
    float4 tex = lerp(1, tex2D(BASE, i.uv), CHARK.x), col = lerp(1, i.c, CHARK.y);
    float3 albedo = to_linear(saturate(tex.rgb * col.rgb * CHARK.z));
    // Fur from the bind pose, so it sticks to the body: front and side maps, mixed in a narrow band.
    float side = saturate(normalize(i.bn).z * i.bn.z * 4 - 1.5);
    float size = CHARK.w > 0 ? CHARK.w : 1;  // an untextured character wears the level's hide here, at its own scale
    float2 uvs = float2(i.bp.z / 36, (i.bp.y + i.bp.x / 2) / 40) / size, uvf = i.bp.xy / float2(36, 40) / size;
    float tuft = lerp(tex2D(FUR, uvs).r, tex2D(FUR, uvf).r, side);
    float hide = CHARK.w > 0 ? saturate((0.75 - col.r) * 8) : 1;  // the body is 0.5 grey, the tusks white and smooth
    albedo *= 1 + (tuft - 0.5) * (CHARK.w > 0 ? 3.5 : 1.4) * CHAR_STYLE.z * hide;
    float3 n = normalize(i.n), v = normalize(EYE.xyz - i.w);
    if (CHARK.w > 0) {  // its creases catch the light
        float3 dx = ddx(i.w), dy = ddy(i.w), r1 = cross(dy, n), r2 = cross(n, dx);
        float det = dot(dx, r1);
        n = normalize(abs(det) * n - 2.2 * hide * sign(det) * (ddx(tuft) * r1 + ddy(tuft) * r2));
    }
    float nl = dot(n, SUN.xyz), nv = saturate(dot(n, v));
    // A soft cartoon step: the shadow side stays colourful.
    float band = saturate((nl + CHAR_STYLE.x) * CHAR_STYLE.y);
    band = band * band * (3 - 2 * band);
    // A soft key from over the camera's left shoulder: a back turned to the player stays round when the sun can't shape it.
    float3 across = normalize(cross(float3(0, 1, 0), v));
    float shoulder = saturate(dot(n, normalize(v * 0.85 - across * 0.5 + float3(0, 0.55, 0))));
    shoulder *= shoulder;
    float4 q = float4(i.w, 1);
    float3 s = float3(dot(SROW[0], q), dot(SROW[1], q), dot(SROW[2], q));
    float2 d = 1.5 * TEXEL.x;
    float sh = (tex2Dproj(SHADOW, float4(s.xy + d, s.z, 1)).r + tex2Dproj(SHADOW, float4(s.xy - d, s.z, 1)).r
              + tex2Dproj(SHADOW, float4(s.xy + float2(d.x, -d.y), s.z, 1)).r + tex2Dproj(SHADOW, float4(s.xy + float2(-d.x, d.y), s.z, 1)).r) / 4;
    float3 amb = lerp(GND_AMB.rgb, SKY_AMB.rgb, n.y * 0.5 + 0.5) * (0.5 + 0.25 * saturate(n.y + 0.4) + 1.45 * shoulder);
    // Character paint is authored brighter and more saturated than the world's albedo. Pulled towards a warm
    // grey: a neutral one turned the brown fur magenta.
    float3 lamp = 0;
    for (int k = 0; k < 2; k++) {
        float3 d = CHAR_LIGHT[k * 2].xyz - i.w;
        float fall = saturate(1 - dot(d, d) * CHAR_LIGHT[k * 2].w);
        lamp += CHAR_LIGHT[k * 2 + 1].rgb * fall * fall * saturate(dot(n, normalize(d)) * 0.7 + 0.3);
    }
    float edge = 1 - nv;
    float3 rim = (SKY_AMB.rgb + CHAR_FILL.rgb + 0.5 * SUN_COL.rgb * sh) * edge * edge * edge * edge * 1.1;
    float3 c = albedo * 0.7 * (amb + CHAR_FILL.rgb * (0.55 + 0.75 * shoulder) + 0.85 * SUN_COL.rgb * band * sh * (0.55 + 0.45 * shoulder) + lamp + rim);
    c = lerp(dot(c, float3(0.3, 0.59, 0.11)) * float3(1.08, 0.94, 0.72), c, 0.62) * float3(1.02, 0.93, 0.76);
    float nh = saturate(dot(n, normalize(v + SUN.xyz)));
    float gloss = nh * nh; gloss *= gloss; gloss *= gloss; gloss *= gloss; gloss *= gloss; gloss *= gloss;   // ^64
    c += CHAR_STYLE.w * gloss * sh * saturate(1 - dot(tex.rgb, 0.45)) * (SUN_COL.rgb + CHAR_FILL.rgb);       // on dark paint: eyes, nose
    return float4(to_gamma(c), saturate(tex.a * col.a * CHARK.z));
}
