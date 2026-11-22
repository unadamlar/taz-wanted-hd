// Quicksave (F5) and quickload (F9). Between two frames, copies all the game's own memory: its one
// heap block (bInitHeap, allocated once at startup) and taz.exe's globals; quickload copies it back.
// Textures and sound buffers live outside that memory and are replaced when a level loads or the
// display is reset, so a quicksave only loads in the same level, before any new textures were created.
#include <string.h>
#include "proxy.h"
#include "game.h"
#include <tlhelp32.h>

#define FRAME_CALL ((BYTE *)0x4dc12a) // call FUN_004a9f50, one game frame; nothing of the game's is on the stack
#define GAME_FRAME ((BYTE *)0x4a9f50)
#define HEAP_BASE (*(BYTE **)0x73f704)
#define HEAP_SIZE (*(DWORD *)0x73f79c)
#define GLOBALS ((BYTE *)0x630000) // .data and .data1, up to .rsrc
#define GLOBALS_SIZE 0x12e000
#define MAX_LOCKS 256

// Kept as they are now on quickload: the frame clock (or the first frame would cover the time since the
// save), the game's critical sections (their owners and wait handles belong to the present), and the
// sound channels: a saved one can point at a DirectSound buffer the game has since released.
#define SOUND_CHANNELS 0x750040
#define CHANNEL_SIZE 0x54
#define CHANNEL_COUNT 40
static const struct { DWORD at, size; } KEEP[] = {
    { 0x6c8c18, 0x18 }, { 0x642cdc, 8 }, { 0x6c7ee0, 4 }, { 0x6f4c48, 4 }, { 0x6c6c14, 4 },
    { SOUND_CHANNELS, CHANNEL_COUNT * CHANNEL_SIZE },
};
static CRITICAL_SECTION *locks[MAX_LOCKS];
static int nlocks;

static void (*game_frame)(void) = (void (*)(void))GAME_FRAME;
static void (WINAPI *real_InitializeCriticalSection)(CRITICAL_SECTION *);
static BYTE *saved_heap, *saved_globals, *saved_heap_base;
static DWORD saved_heap_size, saved_textures;
static int saved_scene = -1;

static void WINAPI hook_InitializeCriticalSection(CRITICAL_SECTION *cs)
{
    if (nlocks < MAX_LOCKS) locks[nlocks++] = cs;
    real_InitializeCriticalSection(cs);
}

// Other threads (sound streaming, background loading) must not touch game memory mid-copy.
static int threads(HANDLE *out, int max, int suspend)
{
    int n = 0;
    if (!suspend) {
        for (int i = 0; i < max; i++) ResumeThread(out[i]), CloseHandle(out[i]);
        return 0;
    }
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    THREADENTRY32 te = { .dwSize = sizeof te };
    for (BOOL ok = Thread32First(snap, &te); ok && n < max; ok = Thread32Next(snap, &te)) {
        if (te.th32OwnerProcessID != GetCurrentProcessId() || te.th32ThreadID == GetCurrentThreadId()) continue;
        HANDLE h = OpenThread(THREAD_SUSPEND_RESUME, FALSE, te.th32ThreadID);
        if (h && SuspendThread(h) != (DWORD)-1) out[n++] = h;
        else if (h) CloseHandle(h);
    }
    CloseHandle(snap);
    return n;
}

static void copy_all(int load)
{
    HANDLE held[64];
    int n = threads(held, 64, 1);
    if (load) {
        static BYTE keep[0x40 + CHANNEL_COUNT * CHANNEL_SIZE], lock_now[MAX_LOCKS][sizeof(CRITICAL_SECTION)];
        BYTE *k = keep;
        for (size_t i = 0; i < sizeof KEEP / sizeof *KEEP; k += KEEP[i++].size) memcpy(k, (void *)KEEP[i].at, KEEP[i].size);
        for (int i = 0; i < nlocks; i++) memcpy(lock_now[i], locks[i], sizeof(CRITICAL_SECTION));
        memcpy(HEAP_BASE, saved_heap, saved_heap_size);
        memcpy(GLOBALS, saved_globals, GLOBALS_SIZE);
        k = keep;
        for (size_t i = 0; i < sizeof KEEP / sizeof *KEEP; k += KEEP[i++].size) memcpy((void *)KEEP[i].at, k, KEEP[i].size);
        for (int i = 0; i < nlocks; i++) memcpy(locks[i], lock_now[i], sizeof(CRITICAL_SECTION));
    } else {
        memcpy(saved_heap, HEAP_BASE, saved_heap_size);
        memcpy(saved_globals, GLOBALS, GLOBALS_SIZE);
    }
    threads(held, n, 0);
}

// A cutscene (level intro or outro) is on screen: one of the game's four cutscene slots is past loading.
// Its sound and models stream in from other threads; a quickload during a boss outro froze the game.
static int cutscene_playing(void)
{
    if (outro_music_held()) return 1;
    for (int i = 0; i < 4; i++) {
        BYTE *c = ((BYTE **)0x704d38)[i];
        if (c && *(DWORD *)(c + 0x3f4c) >= 2) return 1;
    }
    return 0;
}

static void quicksave(void)
{
    if (SCENE <= 1) { overlay_toast("Quicksave works in levels only"); return; }
    if (cutscene_playing()) { overlay_toast("No quicksave during a cutscene"); return; }
    if (!saved_heap || saved_heap_base != HEAP_BASE || saved_heap_size != HEAP_SIZE) {
        if (saved_heap) VirtualFree(saved_heap, 0, MEM_RELEASE);
        saved_heap = VirtualAlloc(NULL, HEAP_SIZE + GLOBALS_SIZE, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!saved_heap) {
            log_line("quicksave: no memory for %lu KB", (HEAP_SIZE + GLOBALS_SIZE) >> 10);
            overlay_toast("Quicksave failed: out of memory");
            return;
        }
        saved_globals = saved_heap + HEAP_SIZE;
        saved_heap_base = HEAP_BASE;
        saved_heap_size = HEAP_SIZE;
    }
    DWORD t = GetTickCount();
    copy_all(0);
    saved_scene = SCENE;
    saved_textures = textures_created;
    log_line("quicksave: scene %d, %lu KB in %lu ms", saved_scene, (saved_heap_size + GLOBALS_SIZE) >> 10, GetTickCount() - t);
    overlay_toast("Quicksaved");
}

// Sounds started since the save have no owner after the load, so a looping one would never stop.
static void stop_newer_sounds(void)
{
    for (int i = 0; i < CHANNEL_COUNT; i++) {
        DWORD at = SOUND_CHANNELS + i * CHANNEL_SIZE + 0x30;
        void *now = *(void **)at, *then = *(void **)(saved_globals + (at - (DWORD)GLOBALS));
        if (now && now != then) ((void (__cdecl *)(int))0x579ed0)(i);
    }
}

static void quickload(void)
{
    if (saved_scene < 0) { overlay_toast("No quicksave yet"); return; }
    if (cutscene_playing()) { overlay_toast("No quickload during a cutscene"); return; }
    if (SCENE != saved_scene || textures_created != saved_textures || HEAP_BASE != saved_heap_base) {
        log_line("quickload refused: scene %d (saved %d), textures %lu (saved %lu)", SCENE, saved_scene, textures_created, saved_textures);
        saved_scene = -1; // that level or display is gone; its quicksave can't come back
        overlay_toast("Quicksave lost: level or display changed since");
        return;
    }
    stop_newer_sounds();
    DWORD t = GetTickCount();
    copy_all(1);
    log_line("quickload: scene %d in %lu ms", saved_scene, GetTickCount() - t);
    overlay_toast("Quickloaded");
}

static void frame(void)
{
    int save = key_pressed(VK_F5), load = key_pressed(VK_F9);
    if (save) quicksave();
    else if (load) quickload();
    capture_scene();
    game_frame();
}

void quicksave_patch(void)
{
    if (!redirect_call(FRAME_CALL, GAME_FRAME, frame)) {
        log_line("quicksave: unexpected code at %p, F5/F9 disabled", FRAME_CALL);
        return;
    }
    real_InitializeCriticalSection = patch_import("KERNEL32.dll", "InitializeCriticalSection", hook_InitializeCriticalSection);
}
