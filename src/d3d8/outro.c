// Level endings: the game blacks out the screen, then asks for the scene's music and waits for it
// (~3.9 s: the old track fades and stops, the new one buffers). Asking when the level is won buffers it
// during the camera hold before the scene; it stays paused until the scene starts, so they stay in sync.
#include "proxy.h"

#define OUTRO (*(BYTE **)0x704d38)
#define OUTRO_STATE(c) (*(int *)((c) + 0x3f4c)) // 1 loading, 2 set up, 3 waiting for music, 4 playing

static BYTE *held;

int outro_music_held(void)
{
    if (held && (held != OUTRO || OUTRO_STATE(held) < 1 || OUTRO_STATE(held) > 2)) held = NULL;
    return held != NULL;
}

static int __fastcall load_outro(BYTE *c)
{
    int loading = ((int (__fastcall *)(BYTE *))0x4e31d0)(c);
    // Flag 2 scenes have no music of their own.
    if ((char)loading && !(c[0x4050] & 2) && c[0x4160]) {
        held = c;
        ((void (__fastcall *)(void *, int, int, int, int, const char *))0x4b9670)((void *)0x6fa1a8, 0, 0, 0, 0, (char *)c + 0x4160);
    }
    return loading;
}

static int __cdecl stream_buffered(void *stream, int flag)
{
    return outro_music_held() ? 0 : ((int (__cdecl *)(void *, int))0x580d80)(stream, flag);
}

void outro_patch(void)
{
    if (!redirect_call((BYTE *)0x4ba113, (void *)0x580d80, stream_buffered) ||
        !redirect_call((BYTE *)0x4cd9f0, (void *)0x4e31d0, load_outro))
        log_line("outro: unexpected code, ending music not prepared early");
}
