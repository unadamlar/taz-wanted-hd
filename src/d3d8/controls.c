// WASD and mouse look (the Controls setting; Classic is the game's own keys). Keys: after the game
// binds player 1's keyboard defaults (FUN_0048c100) we bind each action to the keys in taz-hd.ini
// (key_jump=Space, key_spin=LShift MouseRight, ...), first taking those keys off whatever the game
// had them do, so D moves instead of ranting and Space jumps instead of opening the map. Keys the
// layout doesn't use keep their old jobs (C, F, R, X, V, E, T, arrows). Mouse look: around the
// camera control (FUN_004e0f00) the mouse is added to the pad's camera stick for that call only, so
// the game's own camera rules still apply, except that the camera doesn't trail Taz for a moment
// after. The mouse is held (DirectInput exclusive, which hides it) only while that camera control
// runs, so menus get it back. Gamepad: see bind_gamepad.
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "proxy.h"
#include "game.h"
#include <dinput.h>
#include <shlwapi.h>

#define BIND_INPUT ((int (*)(void *, UINT, UINT))0x568860)
#define KEYBOARD_DEFAULTS ((void (*)(BYTE *, int))0x48c100)
#define CAMERA_CONTROL ((void (*)(void **))0x4e0f00)
#define CAMERA_UPDATE ((void (*)(BYTE *))0x4dfef0)
#define KEY_TABLE ((const DWORD *)0x658770) // key code -> DIK
#define MOUSE_DX (*(const LONG *)0x751548)
#define MOUSE_DY (*(const LONG *)0x75154c)
#define MOUSE_DEVICE (*(IUnknown **)0x7513a4)
#define MOUSE_FLAGS (*(const BYTE *)0x751390)
#define TURN_RATE (*(const float *)0x5f7364) // camera swing, radians per second at full stick
#define TILT_RATE (*(const float *)0x5f7360) // look-around tilt
#define TILT_SWING (*(const float *)0x5f73ec) // camera tilt at full stick, radians...
#define TILT_REST (*(const float *)0x649b44)  // ...around this resting tilt
#define READ_DEVICES ((void (*)(void))0x57bb20)
#define KEY_STATE ((BYTE *)0x751438)      // DirectInput keyboard state, by DIK
#define MOUSE_BUTTONS ((BYTE *)0x751554)  // this frame's mouse buttons
#define MOUSE_HELD ((BYTE *)0x751544)     // the copy the game's channels read

enum { MOUSE_LEFT = 2, MOUSE_RIGHT = 3, MOUSE_MIDDLE = 4, DIGITAL = 0x100 };
enum { X1 = 0x38, Y1 = 0x3c, X1DB = 0x48, Y1DB = 0x4c, JUMP = 0x60, BITE = 0x64, SPIN = 0x68, RANT = 0x6c,
       X2 = 0x40, Y2 = 0x44, TIPTOE = 0x74, LOOK = 0x80, MAP = 0x8c, DB = 0x40 }; // pad offsets of channel pointers; DB: debounced copy

// The channels FUN_0048c100 binds for player 1.
static const int GAME_KEYS[] = { X1, Y1, X1DB, Y1DB, 0x60, 0x64, 0x68, 0x6c, 0x70, 0x74, 0x7c, 0x80, 0x88, 0x8c,
                                 0xa0, 0xa4, 0xa8, 0xac, 0xb0, 0xb4, 0xbc, 0xc0, 0xc8, 0xcc };

// Actions players can rebind. Movement takes one key per direction; the rest up to two inputs.
static const struct action { const char *label, *key, *def; int off; } ACTIONS[] = {
    { "Forward", "key_forward", "W", -1 }, { "Back", "key_back", "S", -1 }, { "Left", "key_left", "A", -1 },
    { "Right", "key_right", "D", -1 }, { "Jump", "key_jump", "Space", JUMP },
    { "Spin", "key_spin", "LShift MouseRight", SPIN }, { "Bite", "key_bite", "MouseLeft", BITE },
    { "Rant", "key_rant", "Q", RANT }, { "Tiptoe", "key_tiptoe", "LCtrl", TIPTOE },
    { "Look Around", "key_look", "MouseMiddle", LOOK }, { "Map", "key_map", "Tab", MAP },
};
#define ACTION_COUNT (int)(sizeof ACTIONS / sizeof *ACTIONS)

static const struct { const char *name; BYTE dik; } KEYS[] = {
    { "Esc", 0x01 }, { "1", 0x02 }, { "2", 0x03 }, { "3", 0x04 }, { "4", 0x05 }, { "5", 0x06 }, { "6", 0x07 },
    { "7", 0x08 }, { "8", 0x09 }, { "9", 0x0a }, { "0", 0x0b }, { "Minus", 0x0c }, { "Equals", 0x0d },
    { "Backspace", 0x0e }, { "Tab", 0x0f }, { "Q", 0x10 }, { "W", 0x11 }, { "E", 0x12 }, { "R", 0x13 },
    { "T", 0x14 }, { "Y", 0x15 }, { "U", 0x16 }, { "I", 0x17 }, { "O", 0x18 }, { "P", 0x19 }, { "LBracket", 0x1a },
    { "RBracket", 0x1b }, { "Enter", 0x1c }, { "LCtrl", 0x1d }, { "A", 0x1e }, { "S", 0x1f }, { "D", 0x20 },
    { "F", 0x21 }, { "G", 0x22 }, { "H", 0x23 }, { "J", 0x24 }, { "K", 0x25 }, { "L", 0x26 }, { "Semicolon", 0x27 },
    { "Apostrophe", 0x28 }, { "Grave", 0x29 }, { "LShift", 0x2a }, { "Backslash", 0x2b }, { "Z", 0x2c },
    { "X", 0x2d }, { "C", 0x2e }, { "V", 0x2f }, { "B", 0x30 }, { "N", 0x31 }, { "M", 0x32 }, { "Comma", 0x33 },
    { "Period", 0x34 }, { "Slash", 0x35 }, { "RShift", 0x36 }, { "LAlt", 0x38 }, { "Space", 0x39 },
    { "CapsLock", 0x3a }, { "F1", 0x3b }, { "F2", 0x3c }, { "F3", 0x3d }, { "F4", 0x3e }, { "F6", 0x40 },
    { "F7", 0x41 }, { "F8", 0x42 }, { "F10", 0x44 }, { "Num7", 0x47 }, { "Num8", 0x48 },
    { "Num9", 0x49 }, { "NumMinus", 0x4a }, { "Num4", 0x4b }, { "Num5", 0x4c }, { "Num6", 0x4d },
    { "NumPlus", 0x4e }, { "Num1", 0x4f }, { "Num2", 0x50 }, { "Num3", 0x51 }, { "Num0", 0x52 },
    { "NumEnter", 0x9c }, { "RCtrl", 0x9d }, { "RAlt", 0xb8 }, { "Home", 0xc7 }, { "Up", 0xc8 }, { "PgUp", 0xc9 },
    { "Left", 0xcb }, { "Right", 0xcd }, { "End", 0xcf }, { "Down", 0xd0 }, { "PgDn", 0xd1 }, { "Insert", 0xd2 },
    { "Delete", 0xd3 },
};

static float pitch;             // held camera tilt from the mouse, -1..1 like the stick
static BYTE *tilt_cam;          // camera whose tilt the mouse holds this frame
static BYTE *mouse_cam;         // camera the mouse last turned...
static DWORD mouse_time;        // ...and when (ms)
static DWORD camera_frame, now; // frames: last camera control call, current
static int held;                // mouse held exclusively
static BYTE *p1_pad;            // player 1's pad as set up for the keyboard...
static void *p1_x1;             // ...and its movement channel then, to tell a pad set up again since

// Horizontal angle of p around o, and turning p around o by a (y up).
static float heading(const float *p, const float *o) { return atan2f(p[2] - o[2], p[0] - o[0]); }
static float wrap(float a) { return a > 3.14159265f ? a - 6.2831853f : a < -3.14159265f ? a + 6.2831853f : a; }
static void spin(float *p, const float *o, float a)
{
    float x = p[0] - o[0], z = p[2] - o[2], cs = cosf(a), sn = sinf(a);
    p[0] = o[0] + x * cs - z * sn;
    p[2] = o[2] + x * sn + z * cs;
}

static void *channel(BYTE *pad, int off) { return *(void **)(pad + off); }

// A channel's bindings: slot k at +0x24 + k * 0x1c holds its codes, the count of slots is at +0xcc.
static UINT *slot(void *ch, int k) { return (UINT *)((BYTE *)ch + 0x24 + k * 0x1c); }
static int *slots(void *ch) { return (int *)((BYTE *)ch + 0xcc); }

// Game input code for a key or mouse button name, 0 if unknown.
static UINT code_of(const char *name)
{
    if (!_stricmp(name, "MouseLeft")) return MOUSE_LEFT;
    if (!_stricmp(name, "MouseRight")) return MOUSE_RIGHT;
    if (!_stricmp(name, "MouseMiddle")) return MOUSE_MIDDLE;
    for (UINT i = 0; i < sizeof KEYS / sizeof *KEYS; i++)
        if (!_stricmp(name, KEYS[i].name))
            for (UINT c = 0x36; c <= 0xa0; c++)
                if (KEY_TABLE[c] == KEYS[i].dik) return c;
    return 0;
}

// Up to two codes from an action's setting ("LShift MouseRight").
static int codes_of(const struct action *a, UINT *out)
{
    char v[64], *save = NULL;
    int n = 0;
    settings_get(a->key, a->def, v, sizeof v);
    for (char *t = strtok_r(v, " ,", &save); t && n < 2; t = strtok_r(NULL, " ,", &save)) {
        UINT c = code_of(t);
        if (c && c != code_of("Esc")) out[n++] = c;
        else log_line("controls: %s: unknown or reserved key %s", a->key, t);
    }
    return n;
}

// Takes a code off every channel the game bound keys to, so it only does what the layout says.
static void free_code(BYTE *pad, UINT code)
{
    for (UINT i = 0; i < sizeof GAME_KEYS / sizeof *GAME_KEYS; i++) {
        void *ch = channel(pad, GAME_KEYS[i]);
        for (int k = 0; k < *slots(ch); k++)
            if ((slot(ch, k)[0] & 0xff) == code || (slot(ch, k)[1] & 0xff) == code) {
                memmove(slot(ch, k), slot(ch, k + 1), (*slots(ch) - k - 1) * 0x1c);
                --*slots(ch), k--;
            }
    }
}

static void bind_layout(BYTE *pad)
{
    UINT codes[sizeof ACTIONS / sizeof *ACTIONS][2] = { { 0 } };
    int count[sizeof ACTIONS / sizeof *ACTIONS];
    for (UINT i = 0; i < sizeof ACTIONS / sizeof *ACTIONS; i++) {
        count[i] = codes_of(&ACTIONS[i], codes[i]);
        for (int k = 0; k < count[i]; k++) free_code(pad, codes[i][k]);
    }
    UINT fwd = codes[0][0], back = codes[1][0], left = codes[2][0], right = codes[3][0];
    if (right && left) BIND_INPUT(channel(pad, X1), right, left), BIND_INPUT(channel(pad, X1DB), right | DIGITAL, left | DIGITAL);
    if (back && fwd) BIND_INPUT(channel(pad, Y1), back, fwd), BIND_INPUT(channel(pad, Y1DB), back | DIGITAL, fwd | DIGITAL);
    for (UINT i = 4; i < sizeof ACTIONS / sizeof *ACTIONS; i++)
        for (int k = 0; k < count[i]; k++) {
            BIND_INPUT(channel(pad, ACTIONS[i].off), codes[i][k], 0);
            BIND_INPUT(channel(pad, ACTIONS[i].off + DB), codes[i][k], 0);
        }
    log_line("controls: WASD and mouse");
}

// Gamepad. The game only uses one after its 2002 config tool has saved a layout for it; with none saved
// it binds keys alone. It opens every joystick at startup all the same, so player 1 gets the first one
// here, if it is an Xbox-style pad (what Windows, Steam Input and Wine show any modern pad as; others
// number their buttons and axes differently). The game has a camera stick, but its config tool can't
// bind one.
#define JOYSTICK ((BYTE *)0x75105c) // first joystick: +0 flags (1 = opened), +0x14 its DirectInput device
enum { AXIS = 0x2a, BUTTON = 10 }; // joystick codes: axes X Y Z Rx Ry Rz, then buttons from 10

static int known = -1; // first joystick is an Xbox-style pad; -1 not looked at yet

static int xbox_pad(void)
{
    if (known >= 0) return known;
    DIDEVICEINSTANCEA info = { .dwSize = sizeof info };
    IDirectInputDevice8A *dev = *(IDirectInputDevice8A **)(JOYSTICK + 0x14);
    known = (*JOYSTICK & 1) && dev && SUCCEEDED(IDirectInputDevice8_GetDeviceInfo(dev, &info))
            && (StrStrIA(info.tszProductName, "xbox") || StrStrIA(info.tszProductName, "x-box") || StrStrIA(info.tszProductName, "xinput"));
    if (*JOYSTICK & 1) log_line("controls: gamepad \"%s\"%s", info.tszProductName, known ? "" : " is not Xbox-style, left to the game's config tool");
    return known;
}

// With no pad saved by the config tool the game still reserves player 1's joystick for the saved one
// (an all-ones id that nothing has), so it turns every pad away. Free the place.
#define INIT_INPUT ((void (*)(int))0x57b020)
#define WANTED_JOYSTICK (*(const BYTE **)0x751a98) // id of the joystick saved for player 1, if any

static void __cdecl init_input(int flags)
{
    static const BYTE NONE[16] = { [0 ... 15] = 0xff };
    if (WANTED_JOYSTICK && !memcmp(WANTED_JOYSTICK, NONE, 16)) WANTED_JOYSTICK = NULL;
    INIT_INPUT(flags);
}

// Binds a joystick code to a channel unless it already is (a pad plugged in again is bound again).
static void bind_once(BYTE *pad, int off, UINT code)
{
    void *ch = channel(pad, off);
    for (int k = 0; k < *slots(ch); k++)
        if (slot(ch, k)[0] == code) return;
    BIND_INPUT(ch, code, 0);
}

static void bind_gamepad(BYTE *pad, int menus)
{
    static const struct { int off, button; } BUTTONS[] = { // A B X Y LB RB Back Start L3 R3 are buttons 0-9
        { JUMP, 0 }, { SPIN, 1 }, { RANT, 2 }, { BITE, 3 }, { 0x70, 4 }, { 0x7c, 5 }, { MAP, 6 }, { 0x88, 7 },
        { LOOK, 9 },
    };
    if (!xbox_pad()) return;
    enum { LX = AXIS, LY, LZ, RX, RY };
    bind_once(pad, X1, LX), bind_once(pad, X1DB, LX | DIGITAL);
    bind_once(pad, Y1, LY), bind_once(pad, Y1DB, LY | DIGITAL);
    *slots(channel(pad, X2)) = *slots(channel(pad, Y2)) = *slots(channel(pad, X2 + 0x10)) = 0; // ours alone
    bind_once(pad, X2, RX), bind_once(pad, X2 + 0x10, RX | DIGITAL);
    bind_once(pad, Y2, RY);
    for (UINT i = 0; i < sizeof BUTTONS / sizeof *BUTTONS; i++) {
        bind_once(pad, BUTTONS[i].off, BUTTON + BUTTONS[i].button);
        bind_once(pad, BUTTONS[i].off + DB, BUTTON + BUTTONS[i].button);
    }
    // Either trigger: they share axis Z (left pushes it up, right down) and a button channel is on for both.
    bind_once(pad, TIPTOE, LZ), bind_once(pad, TIPTOE + DB, LZ);
    if (!menus) return;
    bind_once(pad, 0x168, BUTTON + 1), bind_once(pad, 0x178, BUTTON + 1); // B is Back, as well as the game's Y
    for (int set = 0x144; set <= 0x154; set += 0x10) { // menu up, down, left, right, twice over
        bind_once(pad, set, LY | DIGITAL), bind_once(pad, set + 4, LY);
        bind_once(pad, set + 8, LX | DIGITAL), bind_once(pad, set + 12, LX);
    }
}

// A pad plugged in after the game started: the game only looks for joysticks once, so while it has
// none and Windows reports an Xbox-style pad, have it look again (its own search, joysticks only).
// Also after a quickload to before the pad was there.
static void find_gamepad(void)
{
    static DWORD (WINAPI *state)(DWORD, void *);
    static int loaded;
    if (*JOYSTICK & 1) return;
    known = -1;
    for (int i = 0; !loaded && i < 3; i++) {
        static const char *DLLS[] = { "xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll" };
        HMODULE x = LoadLibraryA(DLLS[i]);
        if (x && (state = (void *)GetProcAddress(x, "XInputGetState"))) break;
    }
    loaded = 1;
    BYTE st[32];
    IDirectInput8A *di = *(IDirectInput8A **)0x751058;
    if (!state || !di || state(0, st) != 0) return;
    IDirectInput8_EnumDevices(di, DI8DEVCLASS_GAMECTRL, (LPDIENUMDEVICESCALLBACKA)0x57b0e0, NULL, DIEDFL_ATTACHEDONLY);
    if (p1_pad && channel(p1_pad, X1) == p1_x1) bind_gamepad(p1_pad, 1);
}

static void __cdecl keyboard_defaults(BYTE *pad, int player)
{
    KEYBOARD_DEFAULTS(pad, player);
    if (player != 0) return;
    p1_pad = pad;
    p1_x1 = channel(pad, X1);
    if (settings.wasd) bind_layout(pad);
    bind_gamepad(pad, 1);
}

// Rebinds player 1's current pad for the Controls setting or changed keys: back to the game's own
// keys, then the layout. A pad set up again since then already follows the settings.
void controls_apply(void)
{
    if (!p1_pad || channel(p1_pad, X1) != p1_x1) return;
    for (UINT i = 0; i < sizeof GAME_KEYS / sizeof *GAME_KEYS; i++) *slots(channel(p1_pad, GAME_KEYS[i])) = 0;
    KEYBOARD_DEFAULTS(p1_pad, 0);
    if (settings.wasd) bind_layout(p1_pad);
    else log_line("controls: classic keys");
    bind_gamepad(p1_pad, 0);
}

// Key capture for the Controls page. Its rows: Move (the four directions, asked for in turn), then
// one per other action. After the player picks a row, the next key or mouse button pressed becomes
// the key. Input is swallowed meanwhile so menus don't react, and until everything is released,
// both before (the Select press) and after (the new key).
static int capturing = -1, capture_last, capture_phase; // action, last action of the row; 0 wait for release, 1 press, 2 release
static void (*capture_done)(void);
#define MOVES 4 // Forward, Back, Left, Right: one row

static const char *name_of_dik(int dik)
{
    for (UINT i = 0; i < sizeof KEYS / sizeof *KEYS; i++)
        if (KEYS[i].dik == dik) return KEYS[i].name;
    return NULL;
}

static void __cdecl read_devices(void)
{
    READ_DEVICES();
    if (capturing < 0) return;
    int any = 0, pressed = -1;
    for (int k = 1; k < 256; k++)
        if (KEY_STATE[k] & 0x80) any = 1, pressed = pressed < 0 ? k : pressed;
    for (int b = 0; b < 3; b++)
        if (MOUSE_BUTTONS[b] & 0x80) any = 1, pressed = pressed < 0 ? 0x100 + b : pressed;
    memset(KEY_STATE, 0, 256);
    memset(MOUSE_BUTTONS, 0, 4);
    memset(MOUSE_HELD, 0, 4);
    if (capture_phase == 0 && !any) capture_phase = 1;
    else if (capture_phase == 1 && pressed >= 0) {
        static const char *MOUSE[] = { "MouseLeft", "MouseRight", "MouseMiddle" };
        const char *name = pressed >= 0x100 ? MOUSE[pressed - 0x100] : name_of_dik(pressed);
        if (pressed == 0x01) capture_last = capturing; // Esc keeps the rest as they are
        else if (!name || !code_of(name)) log_line("controls: key %#x can't be used", pressed);
        else {
            settings_save(ACTIONS[capturing].key, name);
            log_line("controls: %s = %s", ACTIONS[capturing].key, name);
        }
        capture_phase = 2;
        if (capture_done) capture_done();
    } else if (capture_phase == 2 && !any) {
        if (capturing < capture_last) {
            capturing++, capture_phase = 1;
        } else {
            capturing = -1;
            controls_apply();
        }
        if (capture_done) capture_done();
    }
}

int controls_row_count(void) { return ACTION_COUNT - MOVES + 1; }

int controls_capturing(void) { return capturing >= 0; }

void controls_capture(int row, void (*done)(void))
{
    capturing = row ? row + MOVES - 1 : 0;
    capture_last = row ? capturing : MOVES - 1;
    capture_phase = 0;
    capture_done = done;
}

static void key_names(int i, char *out, int size, const char *sep)
{
    static const struct { const char *name, *shown; } NICE[] = {
        { "LShift", "Left Shift" }, { "RShift", "Right Shift" }, { "LCtrl", "Left Ctrl" }, { "RCtrl", "Right Ctrl" },
        { "LAlt", "Left Alt" }, { "RAlt", "Right Alt" }, { "MouseLeft", "Left Click" },
        { "MouseRight", "Right Click" }, { "MouseMiddle", "Middle Click" },
    };
    char v[64], *save = NULL;
    int n = 0;
    out[0] = 0;
    settings_get(ACTIONS[i].key, ACTIONS[i].def, v, sizeof v);
    for (char *t = strtok_r(v, " ,", &save); t && n < size; t = strtok_r(NULL, " ,", &save)) {
        const char *shown = t;
        for (UINT k = 0; k < sizeof NICE / sizeof *NICE; k++)
            if (!_stricmp(t, NICE[k].name)) shown = NICE[k].shown;
        n += snprintf(out + n, size - n, "%s%s", n ? sep : "", shown);
    }
}

// "Move: W A S D", "Spin: Left Shift or Right Click"; "Jump: press a key" while capturing it.
void controls_row_text(int row, char *out, int size)
{
    char k[48];
    if (!row) {
        static const char *DIR[] = { "forward", "back", "left", "right" };
        if (capturing >= 0 && capturing < MOVES) {
            snprintf(out, size, "Move: press %s", DIR[capturing]);
            return;
        }
        static const int SHOWN[] = { 0, 2, 1, 3 }; // forward, left, back, right: "W A S D"
        int n = snprintf(out, size, "Move:");
        for (int i = 0; i < MOVES && n < size; i++) key_names(SHOWN[i], k, sizeof k, " "), n += snprintf(out + n, size - n, " %s", k);
        return;
    }
    int i = row + MOVES - 1;
    if (i == capturing) snprintf(out, size, "%s: press a key", ACTIONS[i].label);
    else key_names(i, k, sizeof k, " or "), snprintf(out, size, "%s: %s", ACTIONS[i].label, k);
}

void controls_reset_keys(void)
{
    for (int i = 0; i < ACTION_COUNT; i++) settings_save(ACTIONS[i].key, NULL);
    controls_apply();
}

// The camera stick with a dead zone, so a worn stick's drift doesn't creep the held tilt.
static float stick(float v)
{
    float m = fabsf(v);
    return m < 0.2f ? 0 : (v < 0 ? -1 : 1) * (m - 0.2f) / 0.8f;
}

static void __cdecl camera_control(void **cc)
{
    BYTE *cam = cc[1];
    float *pad = cc[2];
    camera_frame = now;
    int mouse = settings.wasd && settings.mouse && held, p1 = *(int *)((BYTE *)pad + 0x180) == 0;
    if (p1) tilt_cam = NULL;
    if (!p1 || (!mouse && xbox_pad() <= 0) || FPS <= 0) { // player 1 only
        CAMERA_CONTROL(cc);
        return;
    }
    // The gamepad's camera stick is made to work like the mouse: the view turns the way it is pushed
    // and the tilt stays where it was left (the game turns the other way and springs back).
    float dx = mouse ? MOUSE_DX : 0, dy = mouse ? MOUSE_DY : 0, sx = stick(pad[6]), sy = stick(pad[7]);
    if (dx || dy || sx || sy) mouse_cam = cam, mouse_time = GetTickCount();
    float sens = settings.mouse * 0.0003f, per_frame = TURN_RATE / FPS;
    float yaw = -dx * sens / per_frame; // in stick units: the game turns per_frame * stick
    float saved[8];
    memcpy(saved, pad, sizeof saved);
    int look = *(DWORD *)(cam + 0x74) & 0x800;
    if ((*(DWORD *)(cam + 0x74) & 0x9800) == 0x1000 && SCENE != 0x14) tilt_cam = cam; // where the game lets the stick tilt
    if (look) { // look around (first person): left stick turns and tilts
        pad[4] -= yaw; // this mode turns the other way round
        pad[5] -= dy * sens / (TILT_RATE / FPS);
        if (pad[4] || pad[5]) pad[2] = 1;
    } else {
        pitch -= dy * sens * 2 + sy * 1.5f / FPS;
        pitch = pitch > 1 ? 1 : pitch < -1 ? -1 : pitch;
        pad[6] = yaw - sx;
        pad[7] = pitch;
        pad[3] = pad[6] || pad[7];
    }
    // Camera points (y up): +0x00 eye, +0x10 what it looks at (eased after +0x30), +0x20 where the
    // eye heads, +0x30 Taz. The game turns +0x20 around +0x10 and eases the eye after it, which lags a
    // mouse, and while Taz runs +0x10 trails him, so the turn came out smaller. Turn all three around
    // Taz by the angle the game gave instead.
    float *c = (float *)cam, dest[3] = { c[8], c[9], c[10] }, before = heading(c + 8, c + 4);
    CAMERA_CONTROL(cc);
    float turn = heading(c + 8, c + 4) - before;
    if ((dx || (sx && !look)) && turn) {
        if (look) spin(c, c + 4, turn);
        else memcpy(c + 8, dest, sizeof dest), spin(c, c + 12, turn), spin(c + 4, c + 12, turn), spin(c + 8, c + 12, turn);
    }
    memcpy(pad, saved, sizeof saved);
}

// The camera trails Taz on a leash (and in some states swings behind him), so running anywhere but
// straight ahead turns it, fighting the mouse. For a while after mouse input it keeps the direction
// it had around Taz, then gently hands back to the game. Taz's moves also set the tilt after the
// camera control ran (level while he spins, steeper while he falls), so the mouse's tilt is put back.
static void __cdecl camera_update(BYTE *cam)
{
    float *c = (float *)cam, before = heading(c + 8, c + 12), t = (GetTickCount() - mouse_time) / 1000.f;
    float keep = cam != mouse_cam || (*(DWORD *)(cam + 0x74) & 0x1b00) != 0x1000 || *(void **)(cam + 0xac) ? 0
               : t < 1.5f ? 1 : t < 3 ? (3 - t) / 1.5f : 0; // player camera, not scripted, look-around or catching up
    if (cam == tilt_cam && now - camera_frame <= 1 && !*(void **)(cam + 0xac))
        c[0x19] = TILT_REST - pitch * TILT_SWING, *(DWORD *)(cam + 0x74) |= 1;
    CAMERA_UPDATE(cam);
    if (keep) spin(c + 8, c + 12, wrap(before - heading(c + 8, c + 12)) * keep);
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
    if (now % 120 == 0) find_gamepad();
    int want = settings.wasd && settings.mouse && now - camera_frame <= 2 && GetForegroundWindow() == GAME_WINDOW;
    if (want != held) hold_mouse(want);
}

static int calls(BYTE *at, void *fn) { return at[0] == 0xe8 && at + 5 + *(INT32 *)(at + 1) == fn; }

void controls_patch(void)
{
    if (!calls((BYTE *)0x48ad3c, KEYBOARD_DEFAULTS) || !calls((BYTE *)0x48ad74, KEYBOARD_DEFAULTS)
        || !calls((BYTE *)0x480e5d, CAMERA_CONTROL) || !calls((BYTE *)0x4a8687, CAMERA_UPDATE)) {
        log_line("controls: unexpected code, not patching");
        return;
    }
    redirect_call((BYTE *)0x48ad3c, KEYBOARD_DEFAULTS, keyboard_defaults);
    redirect_call((BYTE *)0x48ad74, KEYBOARD_DEFAULTS, keyboard_defaults);
    redirect_call((BYTE *)0x480e5d, CAMERA_CONTROL, camera_control);
    redirect_call((BYTE *)0x4a8687, CAMERA_UPDATE, camera_update);
    if (calls((BYTE *)0x568450, INIT_INPUT)) redirect_call((BYTE *)0x568450, INIT_INPUT, init_input);
    if (calls((BYTE *)0x568b25, READ_DEVICES)) redirect_call((BYTE *)0x568b25, READ_DEVICES, read_devices);
}
