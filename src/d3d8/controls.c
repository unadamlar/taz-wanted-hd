// WASD and mouse look. Keys: after the game binds player 1's keyboard defaults (FUN_0048c100) we
// add W/A/S/D to the movement channels, Space to Jump, Shift to Tiptoe, the mouse buttons to Spin,
// Bite and Look Around, and move Rant from D to Q and the map from Space to Tab. The old keys still
// work. Mouse look: around the camera control (FUN_004e0f00) the mouse is added to the pad's
// camera stick for that call only, so the game's own camera rules still apply. The mouse is held
// (DirectInput exclusive, which hides it) only while that camera control runs, so menus get it back.
#include <math.h>
#include <string.h>
#include "proxy.h"

#define BIND_INPUT ((int (*)(void *, UINT, UINT))0x568860)
#define KEYBOARD_DEFAULTS ((void (*)(BYTE *, int))0x48c100)
#define CAMERA_CONTROL ((void (*)(void **))0x4e0f00)
#define KEY_TABLE ((const DWORD *)0x658770) // key code -> DIK
#define MOUSE_DX (*(const LONG *)0x751548)
#define MOUSE_DY (*(const LONG *)0x75154c)
#define MOUSE_DEVICE (*(IUnknown **)0x7513a4)
#define MOUSE_FLAGS (*(const BYTE *)0x751390)
#define GAME_WINDOW (*(HWND *)0x753724)
#define TURN_RATE (*(const float *)0x5f7364) // camera swing, radians per second at full stick
#define TILT_RATE (*(const float *)0x5f7360) // look-around tilt
#define FPS (*(const float *)0x642cdc)

enum { MOUSE_LEFT = 2, MOUSE_RIGHT = 3, MOUSE_MIDDLE = 4, DIGITAL = 0x100 };
enum { X1 = 0x38, Y1 = 0x3c, X1DB = 0x48, Y1DB = 0x4c, JUMP = 0x60, BITE = 0x64, SPIN = 0x68, RANT = 0x6c,
       TIPTOE = 0x74, LOOK = 0x80, MAP = 0x8c, DB = 0x40 }; // pad offsets of channel pointers; DB: debounced copy

static float pitch;             // held camera tilt from the mouse, -1..1 like the stick
static DWORD camera_frame, now; // frames: last camera control call, current
static int held;

static UINT key(DWORD dik)
{
    for (UINT c = 0x36; c <= 0xa0; c++)
        if (KEY_TABLE[c] == dik) return c;
    return 0;
}

static void *channel(BYTE *pad, int off) { return *(void **)(pad + off); }

// Replaces binding code `from` with `to` on a channel (codes sit at +0x24, one 0x1c-byte slot per binding).
static void rebind(void *ch, UINT from, UINT to)
{
    int n = *(int *)((BYTE *)ch + 0xcc);
    for (int k = 0; k < n; k++) {
        UINT *code = (UINT *)((BYTE *)ch + 0x24 + k * 0x1c);
        if (*code == from) *code = to;
    }
}

static void bind_both(BYTE *pad, int off, UINT code)
{
    BIND_INPUT(channel(pad, off), code, 0);
    BIND_INPUT(channel(pad, off + DB), code, 0);
}

static void __cdecl keyboard_defaults(BYTE *pad, int player)
{
    KEYBOARD_DEFAULTS(pad, player);
    if (player != 0) return;
    UINT w = key(0x11), a = key(0x1e), s = key(0x1f), d = key(0x20), q = key(0x10), space = key(0x39),
         tab = key(0x0f), shift = key(0x2a);
    if (!w || !a || !s || !d || !q || !space || !tab || !shift) {
        log_line("controls: keys not found, WASD not bound");
        return;
    }
    for (int off = RANT; off <= RANT + DB; off += DB) rebind(channel(pad, off), d, q);
    for (int off = MAP; off <= MAP + DB; off += DB) rebind(channel(pad, off), space, tab);
    BIND_INPUT(channel(pad, X1), d, a);
    BIND_INPUT(channel(pad, Y1), s, w);
    BIND_INPUT(channel(pad, X1DB), d | DIGITAL, a | DIGITAL);
    BIND_INPUT(channel(pad, Y1DB), s | DIGITAL, w | DIGITAL);
    bind_both(pad, JUMP, space);
    bind_both(pad, TIPTOE, shift);
    bind_both(pad, SPIN, MOUSE_LEFT);
    bind_both(pad, BITE, MOUSE_RIGHT);
    bind_both(pad, LOOK, MOUSE_MIDDLE);
    log_line("controls: WASD and mouse buttons bound");
}

static void __cdecl camera_control(void **cc)
{
    BYTE *cam = cc[1];
    float *pad = cc[2];
    camera_frame = now;
    if (*(int *)((BYTE *)pad + 0x180) != 0 || !settings.mouse || !held || FPS <= 0) { // keyboard player only
        CAMERA_CONTROL(cc);
        return;
    }
    float sens = settings.mouse * 0.0003f, per_frame = TURN_RATE / FPS;
    float yaw = -MOUSE_DX * sens / per_frame; // in stick units: the game turns per_frame * stick
    float saved[8];
    memcpy(saved, pad, sizeof saved);
    if (*(DWORD *)(cam + 0x74) & 0x800) { // look around (first person): left stick turns and tilts
        pad[4] -= yaw; // this mode turns the other way round
        pad[5] -= MOUSE_DY * sens / (TILT_RATE / FPS);
        if (pad[4] || pad[5]) pad[2] = 1;
    } else {
        pitch -= MOUSE_DY * sens * 2;
        pitch = pitch > 1 ? 1 : pitch < -1 ? -1 : pitch;
        pad[6] += yaw;
        pad[7] += pitch;
        if (pad[6] || pad[7]) pad[3] = 1;
    }
    float *c = (float *)cam, before = atan2f(c[10] - c[6], c[8] - c[4]);
    CAMERA_CONTROL(cc);
    // The game turns where the camera is heading (+0x20) and eases the camera after it, which lags
    // behind a mouse. Turn the camera itself (+0x00) by the same amount around Taz (+0x10, y up).
    float turn = atan2f(c[10] - c[6], c[8] - c[4]) - before;
    if (MOUSE_DX && turn) {
        float x = c[0] - c[4], z = c[2] - c[6], cs = cosf(turn), sn = sinf(turn);
        c[0] = c[4] + x * cs - z * sn;
        c[2] = c[6] + x * sn + z * cs;
    }
    memcpy(pad, saved, sizeof saved);
}

// IDirectInputDevice8 vtable slots.
typedef HRESULT (WINAPI *device_fn)(IUnknown *);
typedef HRESULT (WINAPI *level_fn)(IUnknown *, HWND, DWORD);

static void hold_mouse(int on)
{
    IUnknown *m = MOUSE_DEVICE;
    held = on;
    if (!m || !(MOUSE_FLAGS & 1)) return;
    void **vt = *(void ***)m;
    ((device_fn)vt[8])(m); // Unacquire
    ((level_fn)vt[13])(m, GAME_WINDOW, on ? 5 : 6); // exclusive or not, foreground
    ((device_fn)vt[7])(m); // Acquire
}

void controls_frame(void)
{
    now++;
    int want = settings.mouse && now - camera_frame <= 2 && GetForegroundWindow() == GAME_WINDOW;
    if (want != held) hold_mouse(want);
}

static int calls(BYTE *at, void *fn) { return at[0] == 0xe8 && at + 5 + *(INT32 *)(at + 1) == fn; }

void controls_patch(void)
{
    if (!calls((BYTE *)0x48ad3c, KEYBOARD_DEFAULTS) || !calls((BYTE *)0x48ad74, KEYBOARD_DEFAULTS)
        || !calls((BYTE *)0x480e5d, CAMERA_CONTROL)) {
        log_line("controls: unexpected code, not patching");
        return;
    }
    redirect_call((BYTE *)0x48ad3c, KEYBOARD_DEFAULTS, keyboard_defaults);
    redirect_call((BYTE *)0x48ad74, KEYBOARD_DEFAULTS, keyboard_defaults);
    redirect_call((BYTE *)0x480e5d, CAMERA_CONTROL, camera_control);
}
