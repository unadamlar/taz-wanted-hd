// Look level 4, full-screen passes: AO, bloom, tone mapping and grade.
float4 TEXEL_SRC : register(c0);    // 1 / w, 1 / h of the source
float4 BLOOM     : register(c1);    // threshold, knee, strength, exposure
float4 GRADE     : register(c2);    // saturation, contrast, 1 = show only the blur, dimming
float4 PROJ      : register(c3);    // view-space x, y from uv: x scale, y scale, ao radius, ao strength

sampler2D SRC   : register(s0);
sampler2D SRC2  : register(s1);

struct Quad { float4 p : POSITION; float2 uv : TEXCOORD0; };
Quad vs_quad(float4 p : POSITION, float2 uv : TEXCOORD0)
{
    Quad o;
    o.p = float4(p.xy - float2(TEXEL_SRC.z, -TEXEL_SRC.w), 0, 1); // half-pixel offset of Direct3D 9
    o.uv = uv;
    return o;
}

float3 decode(float3 c) { return pow(max(c, 0), 2.2); }

// First bloom step: keeps what is over the threshold, with a soft knee.
float4 ps_bright(Quad i) : COLOR
{
    float2 t = TEXEL_SRC.xy;
    float3 c = decode(tex2D(SRC, i.uv + t * float2(-1, -1)).rgb) + decode(tex2D(SRC, i.uv + t * float2(1, -1)).rgb)
             + decode(tex2D(SRC, i.uv + t * float2(-1, 1)).rgb) + decode(tex2D(SRC, i.uv + t * float2(1, 1)).rgb);
    c = min(c * 0.25 * BLOOM.w, 32);
    float l = max(c.r, max(c.g, c.b));
    float soft = saturate((l - BLOOM.x + BLOOM.y) / (2 * BLOOM.y + 0.0001));
    float k = max(soft * soft * BLOOM.y, l - BLOOM.x) / max(l, 0.0001);
    return float4(c * saturate(k), 1);
}

float4 ps_down(Quad i) : COLOR
{
    float2 t = TEXEL_SRC.xy;
    float3 c = tex2D(SRC, i.uv).rgb * 4;
    c += tex2D(SRC, i.uv + t * float2(-1, -1)).rgb + tex2D(SRC, i.uv + t * float2(1, -1)).rgb;
    c += tex2D(SRC, i.uv + t * float2(-1, 1)).rgb + tex2D(SRC, i.uv + t * float2(1, 1)).rgb;
    return float4(c / 8, 1);
}

float4 ps_up(Quad i) : COLOR
{
    float2 t = TEXEL_SRC.xy;
    float3 c = tex2D(SRC, i.uv + t * float2(-1, 0)).rgb + tex2D(SRC, i.uv + t * float2(1, 0)).rgb;
    c += tex2D(SRC, i.uv + t * float2(0, -1)).rgb + tex2D(SRC, i.uv + t * float2(0, 1)).rgb;
    c = c * 2 + tex2D(SRC, i.uv + t * float2(-1, -1)).rgb + tex2D(SRC, i.uv + t * float2(1, -1)).rgb;
    c += tex2D(SRC, i.uv + t * float2(-1, 1)).rgb + tex2D(SRC, i.uv + t * float2(1, 1)).rgb;
    return float4(c / 12, 0.7);
}

// Filmic curve on log exposure: a sigmoid around mid grey (0.18 -> 0.5), so highlights roll off per channel and
// keep their hue. Output is display-encoded.
float3 film(float3 c)
{
    float l = dot(c, float3(0.2126, 0.7152, 0.0722));
    c = lerp(l, c, 0.86);
    float3 x = saturate((log2(max(c, 0.0001) / 0.18) + 10) / 16.5) - 0.606;
    float3 k = 2.4 * x;
    float3 y = 0.5 + k / sqrt(1 + 4 * k * k);
    return saturate(y);
}

float4 ps_final(Quad i) : COLOR
{
    float3 glow = tex2D(SRC2, i.uv).rgb * BLOOM.z;
    float3 c = lerp(decode(tex2D(SRC, i.uv).rgb) * BLOOM.w + glow, glow, GRADE.z);
    c = pow(film(c), GRADE.y);
    c.g = lerp(c.g, c.r, 0.07);  // strong reds lean to orange, as in the Blender look
    float l = dot(c, float3(0.2126, 0.7152, 0.0722));
    return float4(saturate(lerp(l, c, GRADE.x)) * (1 - GRADE.w), 1);
}

// Ambient occlusion from linear depth: eight directions, two radii, bent by distance.
float4 ps_ao(Quad i) : COLOR
{
    float z = tex2D(SRC, i.uv).r;
    if (z <= 0 || z > 60000) return 1;
    float3 p = float3((i.uv * 2 - 1) * float2(1, -1) * PROJ.xy, 1) * z;
    float2 t = TEXEL_SRC.xy;
    float3 dx = float3(((i.uv + float2(t.x, 0)) * 2 - 1) * float2(1, -1) * PROJ.xy, 1) * tex2D(SRC, i.uv + float2(t.x, 0)).r - p;
    float3 dy = float3(((i.uv + float2(0, t.y)) * 2 - 1) * float2(1, -1) * PROJ.xy, 1) * tex2D(SRC, i.uv + float2(0, t.y)).r - p;
    float3 n = normalize(cross(dy, dx));
    float a = frac(52.9829 * frac(dot(i.uv / t, float2(0.0671, 0.00584)))) * 6.2832;
    float2 rot = float2(cos(a), sin(a));
    float r = PROJ.z / max(z, 1), occ = 0;
    static const float2 dirs[8] = { { 1, 0 }, { 0.707, 0.707 }, { 0, 1 }, { -0.707, 0.707 }, { -1, 0 }, { -0.707, -0.707 }, { 0, -1 }, { 0.707, -0.707 } };
    for (int k = 0; k < 8; k++) {
        float2 d = float2(dirs[k].x * rot.x - dirs[k].y * rot.y, dirs[k].x * rot.y + dirs[k].y * rot.x);
        float s = (k & 1) ? 1.0 : 0.45;
        float2 uv = i.uv + d * r * s / PROJ.xy * float2(0.5, -0.5);
        float zs = tex2Dlod(SRC, float4(uv, 0, 0)).r;
        float3 q = float3((uv * 2 - 1) * float2(1, -1) * PROJ.xy, 1) * zs - p;
        float l2 = dot(q, q);
        occ += saturate(dot(q, n) / sqrt(l2 + 1) - 0.08) * saturate(1 - l2 / (PROJ.z * PROJ.z * 2.25));
    }
    return saturate(1 - PROJ.w * occ / 8 * 2.2);
}

// Keeps depth edges while it blurs; TEXEL_SRC.xy is the step direction.
float4 ps_ao_blur(Quad i) : COLOR
{
    float z = tex2D(SRC2, i.uv).r, sum = tex2D(SRC, i.uv).r, total = 1;
    for (int k = 1; k <= 3; k++)
        for (int side = -1; side <= 1; side += 2) {
            float2 uv = i.uv + TEXEL_SRC.xy * k * side;
            float w = saturate(1 - abs(tex2Dlod(SRC2, float4(uv, 0, 0)).r - z) / (z * 0.02 + 2)) * (4 - k);
            sum += tex2Dlod(SRC, float4(uv, 0, 0)).r * w;
            total += w;
        }
    return sum / total;
}
