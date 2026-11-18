// Aspect ratio: the engine computes its field of view from an aspect it only ever sets to 4:3, or 16:9
// with its own Widescreen option. We make the 4:3 branch use the screen's shape (at startup from the
// resolution in taz.dat, later from the game's screen size) and turn the game's option off, since a
// forced 16:9 is wrong on any other screen.
#include <stdio.h>
#include <string.h>
#include "proxy.h"
#include "game.h"

// FUN_0048fd20(on): "mov al,[esp+4]" at entry; its 4:3 branch: movb $4,0x6c6b88 ; movb $3,0x6c6b89
static BYTE *const ASPECT_FN = (BYTE *)0x48fd20;
static BYTE *const ASPECT_CODE = (BYTE *)0x48fd70;
static const BYTE ENTRY_ORIG[4] = { 0x8a, 0x44, 0x24, 0x04 };
static const BYTE ASPECT_ORIG[14] = { 0xc6, 0x05, 0x88, 0x6b, 0x6c, 0x00, 0x04, 0xc6, 0x05, 0x89, 0x6b, 0x6c, 0x00, 0x03 };
static int patched;

static UINT gcd(UINT a, UINT b)
{
    while (b) {
        UINT t = a % b;
        a = b;
        b = t;
    }
    return a;
}

static void set_aspect(UINT w, UINT h)
{
    UINT g = gcd(w, h), ax = w / g, ay = h / g;
    while (ax > 255 || ay > 255) { // the engine stores each side in a byte
        ax = (ax + 1) / 2;
        ay = (ay + 1) / 2;
    }
    write_code(ASPECT_CODE + 6, NULL, (BYTE[]){ (BYTE)ax }, 1);
    write_code(ASPECT_CODE + 13, NULL, (BYTE[]){ (BYTE)ay }, 1);
    log_line("aspect: %ux%u, %u:%u", w, h, ax, ay);
}

// After a resolution change, on the game thread between frames.
void widescreen_apply(void)
{
    UINT w = SCREEN_W, h = SCREEN_H;
    if (!patched || !w || !h) return;
    set_aspect(w, h);
    ((void (*)(int))ASPECT_FN)(0); // the game's own: sets the aspect, rebuilds the cameras
}

void widescreen_patch(void)
{
    if (memcmp(ASPECT_CODE, ASPECT_ORIG, sizeof ASPECT_ORIG) || memcmp(ASPECT_FN, ENTRY_ORIG, sizeof ENTRY_ORIG)) {
        log_line("aspect: unexpected code at %p, not patching (different exe?)", ASPECT_FN);
        return;
    }
    patched = 1;
    write_code(ASPECT_FN, NULL, (const BYTE[]){ 0x31, 0xc0, 0x90, 0x90 }, 4); // xor eax,eax: the game's option is always off
    UINT size[2] = { 0, 0 };
    FILE *f = fopen("taz.dat", "rb");
    if (f) {
        fseek(f, 0x24, SEEK_SET);
        if (fread(size, sizeof size, 1, f) != 1) size[0] = 0;
        fclose(f);
    }
    if (size[0] && size[1]) set_aspect(size[0], size[1]);
    else log_line("aspect: no resolution in taz.dat, leaving 4:3");
}
