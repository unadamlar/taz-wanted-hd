// WASD and mouse look (the Controls setting; Classic is the game's own keys). Keys: after the game
// binds player 1's keyboard defaults (FUN_0048c100) we bind each action to the keys in taz-hd.ini
// (key_jump=Space, key_spin=LShift MouseRight, ...), first taking those keys off whatever the game
// had them do, so D moves instead of ranting and Space jumps instead of opening the map. Keys the
// layout doesn't use keep their old jobs (C, F, R, X, V, E, T, arrows). Mouse look: around the
// camera control (FUN_004e0f00) the mouse is added to the pad's camera stick for that call only, so
// the game's own camera rules still apply. The mouse is held (DirectInput exclusive, which hides it)
// only while that camera control runs, so menus get it back.
#include <math.h>
#include <stdio.h>
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
#define READ_DEVICES ((void (*)(void))0x57bb20)
#define KEY_STATE ((BYTE *)0x751438)      // DirectInput keyboard state, by DIK
#define MOUSE_BUTTONS ((BYTE *)0x751554)  // this frame's mouse buttons
#define MOUSE_HELD ((BYTE *)0x751544)     // the copy the game's channels read

enum { MOUSE_LEFT = 2, MOUSE_RIGHT = 3, MOUSE_MIDDLE = 4, DIGITAL = 0x100 };
enum { X1 = 0x38, Y1 = 0x3c, X1DB = 0x48, Y1DB = 0x4c, JUMP = 0x60, BITE = 0x64, SPIN = 0x68, RANT = 0x6c,
       TIPTOE = 0x74, LOOK = 0x80, MAP = 0x8c, DB = 0x40 }; // pad offsets of channel pointers; DB: debounced copy

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
static DWORD camera_frame, now; // frames: last camera control call, current
static int held;                // mouse held exclusively
static BYTE *p1_pad;            // player 1's pad as set up for the keyboard...
static void *p1_x1;             // ...and its movement channel then, to tell a pad set up again since

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

static void __cdecl keyboard_defaults(BYTE *pad, int player)
{
    KEYBOARD_DEFAULTS(pad, player);
    if (player != 0) return;
    p1_pad = pad;
    p1_x1 = channel(pad, X1);
    if (settings.wasd) bind_layout(pad);
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

static void __cdecl camera_control(void **cc)
{
    BYTE *cam = cc[1];
    float *pad = cc[2];
    camera_frame = now;
    if (*(int *)((BYTE *)pad + 0x180) != 0 || !settings.wasd || !settings.mouse || !held || FPS <= 0) { // keyboard player only
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
    int want = settings.wasd && settings.mouse && now - camera_frame <= 2 && GetForegroundWindow() == GAME_WINDOW;
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
    if (calls((BYTE *)0x568b25, READ_DEVICES)) redirect_call((BYTE *)0x568b25, READ_DEVICES, read_devices);
}
