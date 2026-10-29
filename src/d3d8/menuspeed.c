// Menu speed. In the frontend scenes (0 language select, 1 frontend; current scene byte at 0x704cf0)
// the main loop's frame rate is divided by menu_speed, so everything there, camera flights included,
// runs faster. Menu page effects (slides, fades) use the unpaused frame time at 0x6c7ee0; their 42
// reads are pointed at a copy scaled by menu_speed, which also speeds up the in-game pause menu.
#include <string.h>
#include "proxy.h"

// Used only from the asm below, by name.
__attribute__((used)) static float menu_time, menu_speed = 1.0f;

static const DWORD SITES[] = {
    0x535990, 0x535a0c, 0x536637, 0x536644, 0x536687, 0x536694, 0x5367d2, 0x5367df, 0x5367fc, 0x536809,
    0x536974, 0x536981, 0x53699e, 0x5369ab, 0x536b8b, 0x536b98, 0x536dad, 0x536dba, 0x53751f, 0x537530,
    0x5375c0, 0x5375cd, 0x5375e9, 0x5375f6, 0x53785a, 0x537867, 0x537884, 0x537891, 0x5378ed, 0x5378fa,
    0x537922, 0x53792f, 0x537df6, 0x537e0b, 0x53811a, 0x53812e, 0x53814e, 0x53815b, 0x538175, 0x538182,
    0x5381be, 0x5381cb,
};

// Replaces "fstps 0x6c7ee0" at 0x4dc124: keep the real value, store the scaled copy.
__attribute__((naked)) static void store_frame_time(void)
{
    __asm__("fsts 0x6c7ee0\n\t"
            "fmuls _menu_speed\n\t"
            "fstps _menu_time\n\t"
            "ret");
}

// Replaces "call 0x578650" (ticks to frames per second) at 0x4dc13c in the main loop's timing.
__attribute__((naked)) static void frontend_fps(void)
{
    __asm__("pushl 8(%esp)\n\t"
            "pushl 8(%esp)\n\t"
            "movl $0x578650, %eax\n\t"
            "call *%eax\n\t"
            "addl $8, %esp\n\t"
            "cmpb $1, 0x704cf0\n\t"
            "ja 1f\n\t"
            "fdivs _menu_speed\n"
            "1:\n\t"
            "ret");
}

// Replaces "movl $0,0x6c7ee0" at 0x4dc10c (frames where time stands still).
__attribute__((naked)) static void zero_frame_time(void)
{
    __asm__("movl $0, 0x6c7ee0\n\t"
            "movl $0, _menu_time\n\t"
            "ret");
}

static int write_code(BYTE *at, const BYTE *bytes, SIZE_T n)
{
    DWORD old;
    if (!VirtualProtect(at, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy(at, bytes, n);
    VirtualProtect(at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, n);
    return 1;
}

static int call_at(BYTE *at, SIZE_T len, const BYTE *expect, void *target)
{
    BYTE code[16] = { 0xe8 };
    if (memcmp(at, expect, len)) return 0;
    *(INT32 *)(code + 1) = (INT32)((BYTE *)target - (at + 5));
    memset(code + 5, 0x90, len - 5);
    return write_code(at, code, len);
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
    static const BYTE fps_call[] = { 0xe8, 0x0f, 0xc5, 0x09, 0x00 }; // call 0x578650
    if (memcmp((BYTE *)0x4dc124, store, sizeof store) || memcmp((BYTE *)0x4dc10c, zero, sizeof zero) ||
        memcmp((BYTE *)0x4dc13c, fps_call, sizeof fps_call)) {
        log_line("menu speed: unexpected frame-time code, not patching");
        return;
    }
    menu_speed = speed;
    call_at((BYTE *)0x4dc124, sizeof store, store, store_frame_time);
    call_at((BYTE *)0x4dc10c, sizeof zero, zero, zero_frame_time);
    call_at((BYTE *)0x4dc13c, sizeof fps_call, fps_call, frontend_fps);
    float *copy = &menu_time;
    for (UINT i = 0; i < sizeof SITES / sizeof *SITES; i++)
        write_code(operand[i], (BYTE *)&copy, 4);
    log_line("menu speed: %.2fx (%u sites)", speed, (UINT)(sizeof SITES / sizeof *SITES));
}
