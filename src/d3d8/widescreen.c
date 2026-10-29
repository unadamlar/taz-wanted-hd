// Widescreen: the engine computes its field of view from an aspect ratio it only ever sets to 4:3
// (or 16:9 on consoles). We replace the 4:3 constants with the aspect of the resolution in taz.dat.
#include <stdio.h>
#include <string.h>
#include "proxy.h"

// FUN_0048fd20, the 4:3 branch: movb $4,0x6c6b88 ; movb $3,0x6c6b89
static BYTE *const ASPECT_CODE = (BYTE *)0x48fd70;
static const BYTE ASPECT_ORIG[14] = { 0xc6, 0x05, 0x88, 0x6b, 0x6c, 0x00, 0x04, 0xc6, 0x05, 0x89, 0x6b, 0x6c, 0x00, 0x03 };

static UINT gcd(UINT a, UINT b)
{
    while (b) {
        UINT t = a % b;
        a = b;
        b = t;
    }
    return a;
}

void widescreen_patch(void)
{
    UINT size[2] = { 0, 0 };
    FILE *f = fopen("taz.dat", "rb");
    if (f) {
        fseek(f, 0x24, SEEK_SET);
        if (fread(size, sizeof size, 1, f) != 1) size[0] = 0;
        fclose(f);
    }
    if (!size[0] || !size[1]) {
        log_line("widescreen: no resolution in taz.dat, leaving 4:3");
        return;
    }
    if (memcmp(ASPECT_CODE, ASPECT_ORIG, sizeof ASPECT_ORIG)) {
        log_line("widescreen: unexpected code at %p, not patching (different exe?)", ASPECT_CODE);
        return;
    }
    UINT g = gcd(size[0], size[1]), ax = size[0] / g, ay = size[1] / g;
    while (ax > 255 || ay > 255) { // the engine stores each side in a byte
        ax = (ax + 1) / 2;
        ay = (ay + 1) / 2;
    }
    DWORD old;
    VirtualProtect(ASPECT_CODE, sizeof ASPECT_ORIG, PAGE_EXECUTE_READWRITE, &old);
    ASPECT_CODE[6] = (BYTE)ax;
    ASPECT_CODE[13] = (BYTE)ay;
    VirtualProtect(ASPECT_CODE, sizeof ASPECT_ORIG, old, &old);
    FlushInstructionCache(GetCurrentProcess(), ASPECT_CODE, sizeof ASPECT_ORIG);
    log_line("widescreen: %ux%u, aspect %u:%u", size[0], size[1], ax, ay);
}
