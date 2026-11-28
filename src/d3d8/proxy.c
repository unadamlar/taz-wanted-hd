// d3d8.dll proxy: runs the game on Direct3D 9 through d3d8to9 and patches vtable entries we care about.
#define COBJMACROS
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "proxy.h"
#include "game.h"

#define RETAIL_TIMESTAMP 0x3d3bc9b0 // taz.exe linked 2002-07-22

static FILE *logf;
static void (WINAPI *real_OutputDebugStringA)(LPCSTR);
static HRESULT (WINAPI *real_CreateDevice)(IDirect3D8 *, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS *, IDirect3DDevice8 **);
static HRESULT (WINAPI *real_Present)(IDirect3DDevice8 *, CONST RECT *, CONST RECT *, HWND, CONST RGNDATA *);

void log_line(const char *fmt, ...)
{
    if (!logf) return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(logf, "[%lu] ", GetCurrentProcessId());
    vfprintf(logf, fmt, ap);
    va_end(ap);
    fputc('\n', logf);
    fflush(logf);
}

// Compares the game's measured cycle-counter rate (bInitTimer, 0x750010/0x750018) with the real one.
static void timer_check(void)
{
    static LARGE_INTEGER q0;
    static UINT64 t0;
    LARGE_INTEGER q, f;
    UINT64 t = __builtin_ia32_rdtsc();
    QueryPerformanceCounter(&q);
    QueryPerformanceFrequency(&f);
    if (t0)
        log_line("game timer mode %u, game thinks %.1f MHz, measured %.1f MHz", *(UINT *)0x750010,
                 *(UINT64 *)0x750018 / 1e6, (t - t0) / ((double)(q.QuadPart - q0.QuadPart) / f.QuadPart) / 1e6);
    t0 = t;
    q0 = q;
}

// Sleeps until 1/fps after the previous frame; spins the last millisecond for accuracy.
static void limit_frame_rate(int fps)
{
    static LARGE_INTEGER next;
    LARGE_INTEGER now, f;
    QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&now);
    LONGLONG period = f.QuadPart / fps;
    if (!next.QuadPart || now.QuadPart - next.QuadPart > period) next = now;
    while (now.QuadPart < next.QuadPart) {
        LONGLONG left_ms = (next.QuadPart - now.QuadPart) * 1000 / f.QuadPart;
        if (left_ms > 1) Sleep((DWORD)(left_ms - 1));
        QueryPerformanceCounter(&now);
    }
    next.QuadPart += period;
}

// Logs the average frame rate every 10 seconds.
DWORD presents;

static HRESULT WINAPI hook_Present(IDirect3DDevice8 *dev, CONST RECT *src, CONST RECT *dst, HWND wnd, CONST RGNDATA *dirty)
{
    static DWORD start, frames;
    DWORD now = GetTickCount();
    presents++;
    if (!start) start = now;
    if (++frames, now - start >= 10000) {
        log_line("fps: %.1f", frames * 1000.0 / (now - start));
        timer_check();
        start = now;
        frames = 0;
    }
    static int scene = -1;
    if (settings.exe_known && SCENE != scene) log_line("scene %d", scene = SCENE);
    if (!settings.passthrough) {
        look_frame(dev);
        textures_frame();
        if (settings.exe_known) controls_frame();
        settings_frame();
        drawdist_frame();
        menu_frame();
        video_frame(dev);
        overlay_frame(dev);
        screenshot_frame(dev);
        capture_frame();
    }
    if (settings.fps_limit > 0) limit_frame_rate(settings.fps_limit);
    LARGE_INTEGER t0, t1, f;
    QueryPerformanceCounter(&t0);
    HRESULT hr = real_Present(dev, src, dst, wnd, dirty);
    QueryPerformanceCounter(&t1), QueryPerformanceFrequency(&f);
    look_present_ms((t1.QuadPart - t0.QuadPart) * 1000.0 / f.QuadPart);
    return hr;
}

// A key going down while the game is the window in front (keys typed into other programs don't count).
int key_pressed(int vk)
{
    static BYTE was[256];
    DWORD pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    int down = (GetAsyncKeyState(vk) & 0x8000) && pid == GetCurrentProcessId(), edge = down && !was[vk & 255];
    was[vk & 255] = (BYTE)down;
    return edge;
}

// The game's own debug prints (bkPrintf, asserts) go to OutputDebugString; keep them in our log.
static void WINAPI hook_OutputDebugStringA(LPCSTR s)
{
    char line[512];
    snprintf(line, sizeof line, "%s", s ? s : "");
    line[strcspn(line, "\r\n")] = 0;
    if (*line) log_line("game: %s", line);
    real_OutputDebugStringA(s);
}

static HRESULT WINAPI hook_CreateDevice(IDirect3D8 *d3d, UINT adapter, D3DDEVTYPE type, HWND wnd, DWORD flags,
                                        D3DPRESENT_PARAMETERS *pp, IDirect3DDevice8 **dev)
{
    log_line("CreateDevice %ux%u backbuffer_format=%d windowed=%d refresh=%u interval=%u flags=0x%lx swap=%d pp_flags=0x%lx "
             "depth_format=%d", pp->BackBufferWidth, pp->BackBufferHeight, pp->BackBufferFormat, pp->Windowed,
             pp->FullScreen_RefreshRateInHz, pp->FullScreen_PresentationInterval, flags, pp->SwapEffect, pp->Flags,
             pp->EnableAutoDepthStencil ? pp->AutoDepthStencilFormat : 0);
    if (!settings.vsync && !pp->Windowed) pp->FullScreen_PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    D3DPRESENT_PARAMETERS game = *pp;
    if (!settings.passthrough) display_samples(d3d, adapter, type, pp);
    HRESULT hr = real_CreateDevice(d3d, adapter, type, wnd, flags, pp, dev);
    if (FAILED(hr) && pp->MultiSampleType) *pp = game, hr = real_CreateDevice(d3d, adapter, type, wnd, flags, pp, dev);
    log_line("CreateDevice -> 0x%08lx, %u samples", hr, pp->MultiSampleType);
    if (SUCCEEDED(hr) && !real_Present) {
        patch((void **)&(*dev)->lpVtbl->Present, hook_Present, (void **)&real_Present);
        if (!settings.passthrough) textures_install(*dev), display_install(*dev), smooth_install(*dev), merge_install(*dev);
    }
    return hr;
}

static DWORD exe_timestamp(void)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    return ((IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew))->FileHeader.TimeDateStamp;
}

// Tells the player once when taz.exe isn't the build our code patches were made for (each patch checks
// its bytes and skips itself; textures and videos work regardless).
static void check_version(void)
{
    if (settings.exe_known) return;
    log_line("taz.exe build %08lx is not the 2002 retail one (%08x)", exe_timestamp(), RETAIL_TIMESTAMP);
    if (!GetPrivateProfileIntA("taz-hd", "version_warning", 1, ".\\taz-hd.ini")) return;
    settings_save("version_warning", "0");
    MessageBoxA(NULL, "This taz.exe is not the 2002 retail PC version that Taz: Wanted HD was made for.\n\n"
                "HD textures and videos still work, but the screen shape, menu speed and other fixes may stay off. "
                "Details are in taz-hd.log in the game folder.", "Taz: Wanted HD", MB_OK | MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND);
}

static int in_game; // false in the 2002 launcher's config.exe, which also loads this DLL

__declspec(dllexport) IDirect3D8 *WINAPI Direct3DCreate8(UINT sdk)
{
    static int checked;
    if (!checked++ && in_game && !settings.passthrough) check_version();
    IDirect3D8 *d3d = d3d8to9_create();
    log_line("Direct3DCreate8(%u) -> %p (on Direct3D 9)", sdk, d3d);
    if (d3d && in_game && !real_CreateDevice)
        patch((void **)&d3d->lpVtbl->CreateDevice, hook_CreateDevice, (void **)&real_CreateDevice);
    return d3d;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH) {
        char dir[MAX_PATH]; // everything (game data, our ini and log) is relative to the game folder
        DWORD n = GetModuleFileNameA(NULL, dir, sizeof dir);
        while (n && dir[n - 1] != '\\') n--;
        in_game = !_stricmp(dir + n, "taz.exe");
        if (!in_game) return TRUE;
        dir[n] = 0;
        if (n) SetCurrentDirectoryA(dir);
        logf = fopen("taz-hd.log", "a"); // the game relaunches itself; both processes log here
        log_line("taz-hd proxy loaded: %s", GetCommandLineA());
        settings_load();
        settings.exe_known = exe_timestamp() == RETAIL_TIMESTAMP; // the one test for "the exe game.h describes"
        if (settings.passthrough) return TRUE;
        startup_patch();
        widescreen_patch();
        menuspeed_patch(settings.menu_speed); // also at 1x, so the overlay can change it live
        video_patch();
        quicksave_patch();
        outro_patch();
        menu_patch();
        drawdist_patch();
        preview_patch();
        controls_patch();
        asserts_patch();
        real_OutputDebugStringA = patch_import("KERNEL32.dll", "OutputDebugStringA", hook_OutputDebugStringA);
    } else if (reason == DLL_PROCESS_DETACH) {
        if (!game_quit) log_line("process ending, and the game did not ask to quit (Wine or a driver ended it)");
        textures_report();
    }
    return TRUE;
}
