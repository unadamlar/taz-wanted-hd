// Menu text speed. Menu item effects (slides, letters flying off, fades; PageItemFX.cpp) use the
// unpaused frame time at 0x6c7ee0; the transitions' reads are pointed at a copy scaled by menu_speed.
// Camera flights, characters and looping effects keep their pace. Also applies to the pause menu.
#include <string.h>
#include "proxy.h"

// Used only from the asm below, by name.
__attribute__((used)) static float menu_time, menu_speed = 1.0f;

// Reads in the one-shot transitions: slides, fades, drops, letters flying off. Left out on purpose:
// the highlight blink (0x536ad0), the sine wobble (0x535950) and the looping letter wave (0x537dd0),
// which would just run faster.
static const DWORD SITES[] = {
    0x536637, 0x536644, 0x536687, 0x536694, 0x5367d2, 0x5367df, 0x5367fc, 0x536809, 0x536974, 0x536981,
    0x53699e, 0x5369ab, 0x536dad, 0x536dba, 0x53751f, 0x537530, 0x5375c0, 0x5375cd, 0x5375e9, 0x5375f6,
    0x53785a, 0x537867, 0x537884, 0x537891, 0x5378ed, 0x5378fa, 0x537922, 0x53792f, 0x53811a, 0x53812e,
    0x53814e, 0x53815b, 0x538175, 0x538182, 0x5381be, 0x5381cb,
};

// Replaces "fstps 0x6c7ee0" at 0x4dc124: keep the real value, store the scaled copy.
__attribute__((naked)) static void store_frame_time(void)
{
    __asm__("fsts 0x6c7ee0\n\t"
            "fmuls _menu_speed\n\t"
            "fstps _menu_time\n\t"
            "ret");
}

// Replaces "movl $0,0x6c7ee0" at 0x4dc10c (frames where time stands still).
__attribute__((naked)) static void zero_frame_time(void)
{
    __asm__("movl $0, 0x6c7ee0\n\t"
            "movl $0, _menu_time\n\t"
            "ret");
}

// The slide-in update (FUN_00537840) caps each time step at 0.05 s and damps its landing wobble by a
// fixed factor per call, so a scaled clock alone barely speeds it up. Run it several times a frame
// instead, each with a normal-sized step, as if the game ran that much faster for this effect.
static DWORD *const SLIDE_SLOT = (DWORD *)0x5f8940; // its vtable entry
static char (__fastcall *real_slide)(void *, int);

static char __fastcall slide_update(void *fx, int unused)
{
    int steps = (int)(menu_speed + 0.99f);
    float t = menu_time;
    char done = 0;
    menu_time = t / steps;
    for (int i = 0; i < steps && !done; i++) done = real_slide(fx, 0);
    menu_time = t;
    return done;
}

void menuspeed_set(float speed)
{
    menu_speed = speed;
}

void menuspeed_patch(float speed)
{
    static const BYTE store[] = { 0xd9, 0x1d, 0xe0, 0x7e, 0x6c, 0x00 };
    static const BYTE zero[] = { 0xc7, 0x05, 0xe0, 0x7e, 0x6c, 0x00, 0x00, 0x00, 0x00, 0x00 };
    static const BYTE addr[] = { 0xe0, 0x7e, 0x6c, 0x00 };

    // Check every site before changing anything, so a different exe stays untouched.
    BYTE *operand[sizeof SITES / sizeof *SITES];
    for (UINT i = 0; i < sizeof SITES / sizeof *SITES; i++) {
        operand[i] = NULL;
        for (BYTE *p = (BYTE *)SITES[i]; p < (BYTE *)SITES[i] + 8 && !operand[i]; p++)
            if (!memcmp(p, addr, 4)) operand[i] = p;
        if (!operand[i]) {
            log_line("menu speed: unexpected code at %#lx, not patching", SITES[i]);
            return;
        }
    }
    if (memcmp((BYTE *)0x4dc124, store, sizeof store) || memcmp((BYTE *)0x4dc10c, zero, sizeof zero)) {
        log_line("menu speed: unexpected frame-time code, not patching");
        return;
    }
    menu_speed = speed;
    write_jump((BYTE *)0x4dc124, store, sizeof store, 0xe8, store_frame_time);
    write_jump((BYTE *)0x4dc10c, zero, sizeof zero, 0xe8, zero_frame_time);
    float *copy = &menu_time;
    for (UINT i = 0; i < sizeof SITES / sizeof *SITES; i++)
        write_code(operand[i], NULL, &copy, 4);
    if (*SLIDE_SLOT == (DWORD)0x537840) {
        real_slide = (void *)*SLIDE_SLOT;
        DWORD to = (DWORD)slide_update;
        write_code((BYTE *)SLIDE_SLOT, NULL, &to, 4);
    }
    log_line("menu speed: %.2fx (%u sites)", speed, (UINT)(sizeof SITES / sizeof *SITES));
}
