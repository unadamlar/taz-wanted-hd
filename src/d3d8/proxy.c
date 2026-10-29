// d3d8.dll proxy: loads the system d3d8 and patches vtable entries we care about.
#define COBJMACROS
#include <stdarg.h>
#include <stdio.h>
#include "proxy.h"

static FILE *logf;
static HRESULT (WINAPI *real_CreateDevice)(IDirect3D8 *, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS *, IDirect3DDevice8 **);

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

void patch(void **slot, void *hook, void **orig)
{
    DWORD old;
    VirtualProtect(slot, sizeof *slot, PAGE_EXECUTE_READWRITE, &old);
    if (orig) *orig = *slot;
    *slot = hook;
    VirtualProtect(slot, sizeof *slot, old, &old);
}

static HRESULT WINAPI hook_CreateDevice(IDirect3D8 *d3d, UINT adapter, D3DDEVTYPE type, HWND wnd, DWORD flags,
                                        D3DPRESENT_PARAMETERS *pp, IDirect3DDevice8 **dev)
{
    log_line("CreateDevice %ux%u backbuffer_format=%d windowed=%d refresh=%u interval=%u flags=0x%lx",
             pp->BackBufferWidth, pp->BackBufferHeight, pp->BackBufferFormat, pp->Windowed,
             pp->FullScreen_RefreshRateInHz, pp->FullScreen_PresentationInterval, flags);
    HRESULT hr = real_CreateDevice(d3d, adapter, type, wnd, flags, pp, dev);
    log_line("CreateDevice -> 0x%08lx", hr);
    if (SUCCEEDED(hr))
        textures_install(*dev);
    return hr;
}

__declspec(dllexport) IDirect3D8 *WINAPI Direct3DCreate8(UINT sdk)
{
    char path[MAX_PATH];
    GetSystemDirectoryA(path, MAX_PATH);
    strcat(path, "\\d3d8.dll");
    HMODULE real = LoadLibraryA(path);
    IDirect3D8 *(WINAPI *create)(UINT) = real ? (void *)GetProcAddress(real, "Direct3DCreate8") : NULL;
    if (!create) {
        log_line("could not load %s", path);
        return NULL;
    }
    IDirect3D8 *d3d = create(sdk);
    log_line("Direct3DCreate8(%u) -> %p", sdk, d3d);
    if (d3d && !real_CreateDevice)
        patch((void **)&d3d->lpVtbl->CreateDevice, hook_CreateDevice, (void **)&real_CreateDevice);
    return d3d;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH) {
        logf = fopen("taz-hd.log", "a"); // the game relaunches itself; both processes log here
        log_line("taz-hd proxy loaded: %s", GetCommandLineA());
    } else if (reason == DLL_PROCESS_DETACH) {
        textures_report();
    }
    return TRUE;
}
