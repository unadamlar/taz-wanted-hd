// Keeps keyboard input away from the game while the overlay is open: taz.exe's import of
// DirectInput8Create is redirected so device vtables can be patched; keyboard reads come back empty.
#define COBJMACROS
#define DIRECTINPUT_VERSION 0x0800
#include <string.h>
#include <dinput.h>
#include "proxy.h"

int overlay_open;

static HRESULT (WINAPI *real_DirectInput8Create)(HINSTANCE, DWORD, REFIID, LPVOID *, LPUNKNOWN);
static HRESULT (WINAPI *real_CreateDevice)(IDirectInput8A *, REFGUID, LPDIRECTINPUTDEVICE8A *, LPUNKNOWN);
static HRESULT (WINAPI *real_GetDeviceState)(IDirectInputDevice8A *, DWORD, LPVOID);
static HRESULT (WINAPI *real_GetDeviceData)(IDirectInputDevice8A *, DWORD, LPDIDEVICEOBJECTDATA, LPDWORD, DWORD);

static HRESULT WINAPI hook_GetDeviceState(IDirectInputDevice8A *dev, DWORD size, LPVOID data)
{
    HRESULT hr = real_GetDeviceState(dev, size, data);
    if (overlay_open && SUCCEEDED(hr) && size == 256) memset(data, 0, size); // keyboard only; a zeroed joystick would steer
    return hr;
}

static HRESULT WINAPI hook_GetDeviceData(IDirectInputDevice8A *dev, DWORD size, LPDIDEVICEOBJECTDATA buf, LPDWORD count, DWORD flags)
{
    HRESULT hr = real_GetDeviceData(dev, size, buf, count, flags);
    if (overlay_open && SUCCEEDED(hr) && count) *count = 0;
    return hr;
}

static HRESULT WINAPI hook_CreateDevice(IDirectInput8A *di, REFGUID guid, LPDIRECTINPUTDEVICE8A *dev, LPUNKNOWN outer)
{
    HRESULT hr = real_CreateDevice(di, guid, dev, outer);
    if (SUCCEEDED(hr) && IsEqualGUID(guid, &GUID_SysKeyboard) && !real_GetDeviceState) {
        patch((void **)&(*dev)->lpVtbl->GetDeviceState, hook_GetDeviceState, (void **)&real_GetDeviceState);
        patch((void **)&(*dev)->lpVtbl->GetDeviceData, hook_GetDeviceData, (void **)&real_GetDeviceData);
    }
    return hr;
}

static HRESULT WINAPI hook_DirectInput8Create(HINSTANCE inst, DWORD version, REFIID iid, LPVOID *out, LPUNKNOWN outer)
{
    HRESULT hr = real_DirectInput8Create(inst, version, iid, out, outer);
    if (SUCCEEDED(hr) && !real_CreateDevice) {
        IDirectInput8A *di = *out;
        patch((void **)&di->lpVtbl->CreateDevice, hook_CreateDevice, (void **)&real_CreateDevice);
    }
    return hr;
}

void input_patch(void)
{
    real_DirectInput8Create = patch_import("DINPUT8.dll", "DirectInput8Create", hook_DirectInput8Create);
    if (!real_DirectInput8Create) log_line("input: DirectInput8Create import not found, overlay can't block keys");
}
