// Draw distance: multiplies the far clip plane, the fog (which always ends at the far plane) and the
// distances at which objects fade out by settings.draw. Changes apply on the next frame.
#include <string.h>
#include "proxy.h"

#define PROJECTION ((BYTE *)0x56aca0) // FUN_0056aca0(near, far): projection, also used for culling
#define FOG_RANGE ((BYTE *)0x56c420)  // FUN_0056c420(start, end): fog states, kept for sprites too
#define FADE_LIST ((void *)0x475020)  // FUN_00475020(list, start, end, ...): object alpha by distance
static BYTE *const FADE_CALLS[] = { (BYTE *)0x4ac4f9, (BYTE *)0x4ac51c, (BYTE *)0x4ac53b,
                                    (BYTE *)0x4ac55d, (BYTE *)0x4ac57c, (BYTE *)0x4ac59b };

static void (*projection)(float, float);
static void (*fog_range)(float, float);
static float fog_start, fog_end, fog_scale;

// Jumps from fn to hook; returns a copy of fn's first n bytes (whole instructions) that continues in fn.
static void *hook_entry(BYTE *fn, const BYTE *orig, int n, void *hook)
{
    BYTE *t = memcmp(fn, orig, n) ? NULL : VirtualAlloc(NULL, n + 5, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t) return NULL;
    memcpy(t, fn, n);
    t[n] = 0xe9;
    *(INT32 *)(t + n + 1) = (INT32)(fn + n - (t + n + 5));
    return write_jump(fn, orig, n, 0xe9, hook) ? t : NULL;
}

static void hook_projection(float near_z, float far_z)
{
    projection(near_z, far_z * settings.draw);
}

static void hook_fog_range(float start, float end)
{
    fog_start = start, fog_end = end, fog_scale = settings.draw;
    fog_range(start * fog_scale, end * fog_scale);
}

static void fade_list(void *list, float start, float end, float a, float b, float per_radius)
{
    ((void (*)(void *, float, float, float, float, float))FADE_LIST)(list, start * settings.draw, end * settings.draw, a, b, per_radius);
}

// Per frame, between frames: re-applies the fog after the setting changed.
void drawdist_frame(void)
{
    if (fog_range && fog_end > 0 && fog_scale != settings.draw) hook_fog_range(fog_start, fog_end);
}

void drawdist_patch(void)
{
    static const BYTE proj_orig[] = { 0x8b, 0x44, 0x24, 0x04, 0x8b, 0x4c, 0x24, 0x08 }; // mov eax/ecx, [esp+4/8]
    static const BYTE fog_orig[] = { 0xa1, 0xc4, 0x1f, 0x74, 0x00 };                     // mov eax, [0x741fc4]
    int fades = 0;
    for (int i = 0; i < 6; i++) fades += redirect_call(FADE_CALLS[i], FADE_LIST, fade_list);
    projection = hook_entry(PROJECTION, proj_orig, sizeof proj_orig, hook_projection);
    fog_range = hook_entry(FOG_RANGE, fog_orig, sizeof fog_orig, hook_fog_range);
    if (fades < 6 || !projection || !fog_range)
        log_line("draw distance: unexpected code (fades %d, projection %d, fog %d)", fades, !!projection, !!fog_range);
}
