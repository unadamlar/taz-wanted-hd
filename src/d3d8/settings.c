// taz-hd.ini in the game folder, replacing the 2002 launcher and config tool. Missing file or keys
// mean defaults. resolution=auto uses the desktop size and is written into taz.dat before the game
// reads it.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "proxy.h"

#define INI ".\\taz-hd.ini"

struct settings settings;

static void write_resolution(UINT w, UINT h)
{
    UINT cur[2] = { 0, 0 };
    FILE *f = fopen("taz.dat", "r+b");
    if (!f) {
        log_line("settings: no taz.dat, resolution left to the game");
        return;
    }
    fseek(f, 0x24, SEEK_SET);
    if (fread(cur, sizeof cur, 1, f) == 1 && (cur[0] != w || cur[1] != h)) {
        UINT size[2] = { w, h };
        fseek(f, 0x24, SEEK_SET);
        fwrite(size, sizeof size, 1, f);
        log_line("settings: resolution %ux%u (was %ux%u)", w, h, cur[0], cur[1]);
    }
    fclose(f);
}

// "auto" (the desktop size) or "WxH".
int settings_resolution(const char *value, UINT *w, UINT *h)
{
    static DEVMODEA desktop = { .dmSize = sizeof desktop }; // read once, before the game changes the mode
    static BOOL known;
    if (!known) known = EnumDisplaySettingsA(NULL, ENUM_CURRENT_SETTINGS, &desktop);
    *w = *h = 0;
    if (!_stricmp(value, "auto")) {
        if (known) {
            *w = desktop.dmPelsWidth;
            *h = desktop.dmPelsHeight;
        }
    } else if (sscanf(value, "%ux%u", w, h) != 2) {
        *w = *h = 0;
    }
    return *w && *h;
}

void settings_get(const char *key, const char *def, char *out, DWORD size)
{
    GetPrivateProfileStringA("taz-hd", key, def, out, size, INI);
}

void settings_save(const char *key, const char *value)
{
    WritePrivateProfileStringA("taz-hd", key, value, INI);
}

void settings_load(void)
{
    char res[32];
    settings.hd_textures = GetPrivateProfileIntA("taz-hd", "hd_textures", 1, INI);
    settings.hd_models = GetPrivateProfileIntA("taz-hd", "hd_models", 1, INI);
    settings.vsync = GetPrivateProfileIntA("taz-hd", "vsync", 1, INI);
    settings.fps_limit = GetPrivateProfileIntA("taz-hd", "fps_limit", 0, INI);
    settings.smooth = GetPrivateProfileIntA("taz-hd", "smooth_characters", 1, INI);
    settings.mouse = GetPrivateProfileIntA("taz-hd", "mouse_sensitivity", 5, INI);
    GetPrivateProfileStringA("taz-hd", "controls", "wasd", res, sizeof res, INI);
    settings.wasd = _stricmp(res, "classic") != 0;
    settings.passthrough = GetPrivateProfileIntA("taz-hd", "passthrough", 0, INI); // testing: no patches at all
    GetPrivateProfileStringA("taz-hd", "menu_text_speed", "3", res, sizeof res, INI);
    settings.menu_speed = (float)atof(res);
    if (settings.menu_speed < 0.25f || settings.menu_speed > 8.0f) settings.menu_speed = 3.0f;
    GetPrivateProfileStringA("taz-hd", "resolution", "auto", res, sizeof res, INI);
    UINT w, h;
    if (settings_resolution(res, &w, &h)) write_resolution(w, h); // taz.dat, where the game reads it
    log_line("settings: resolution=%s hd_textures=%d vsync=%d fps_limit=%d smooth_characters=%d controls=%s mouse_sensitivity=%d menu_text_speed=%.2f%s", res,
             settings.hd_textures, settings.vsync, settings.fps_limit, settings.smooth, settings.wasd ? "wasd" : "classic", settings.mouse, settings.menu_speed,
             settings.passthrough ? " passthrough" : "");
}

// The settings players change in game, in the game's option menus (menu.c). Changes apply at once.
struct item {
    const char *label, *about, *key, *def;
    const char *choices[12];
    int count, cur;
    int where; // 0 both menus, MAIN Game Options only, PAUSE pause menu (and the Controls page) only
};

enum { MAIN = 1, PAUSE = 2 };

static struct item items[] = {
    { "Resolution", "Desktop matches your screen", "resolution", "auto", { "auto" }, 1, 0, MAIN },
    { "HD Textures", "Sharper, upscaled textures", "hd_textures", "1", { "0", "1" }, 2, 0, 0 },
    { "Vsync", "Stops the picture tearing", "vsync", "1", { "0", "1" }, 2, 0, MAIN },
    { "Smooth Characters", "Rounder characters with smoother shading", "smooth_characters", "1", { "0", "1" }, 2, 0, 0 },
    { "Controls", "WASD and mouse, or the original keys", "controls", "wasd", { "wasd", "classic" }, 2, 0, PAUSE },
    { "Controls", "Keys, mouse look and layout", "keys", "", { "" }, 0, 0, MAIN },
    { "Mouse Look", "Camera speed when turning with the mouse", "mouse_sensitivity", "5", { "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10" }, 11, 0, PAUSE },
    { "Frame Cap", "Limits the frame rate", "fps_limit", "0", { "0", "30", "60", "120", "144" }, 5, 0, MAIN },
    { "Menu Text Speed", "How fast menu text slides in. 1x is the original speed", "menu_text_speed", "3", { "1", "2", "3", "4" }, 4, 0, 0 },
};

static char resolutions[11][16];

// Desktop first, then the screen's largest modes, biggest first.
static void fill_resolutions(struct item *it)
{
    DWORD best[11][2] = { { 0 } };
    DEVMODEA m = { .dmSize = sizeof m };
    for (DWORD i = 0; EnumDisplaySettingsA(NULL, i, &m); i++) {
        DWORD w = m.dmPelsWidth, h = m.dmPelsHeight, k = 0;
        if (w < 800) continue;
        while (k < 11 && (best[k][0] > w || (best[k][0] == w && best[k][1] > h))) k++;
        if (k == 11 || (best[k][0] == w && best[k][1] == h)) continue;
        memmove(best[k + 1], best[k], (10 - k) * sizeof best[0]);
        best[k][0] = w;
        best[k][1] = h;
    }
    it->count = 1;
    for (int k = 0; k < 11 && best[k][0]; k++) {
        snprintf(resolutions[k], sizeof resolutions[k], "%lux%lu", best[k][0], best[k][1]);
        it->choices[it->count++] = resolutions[k];
    }
}

int setting_count(void)
{
    return sizeof items / sizeof *items;
}

const char *setting_label(int i)
{
    return items[i].label;
}

int setting_is_link(int i)
{
    return items[i].count == 0;
}

int setting_on_page(int i, int pause)
{
    return items[i].where != (pause ? MAIN : PAUSE);
}

int setting_find(const char *key)
{
    for (int i = 0; i < setting_count(); i++)
        if (!strcmp(items[i].key, key)) return i;
    return 0;
}

const char *setting_about(int i)
{
    return items[i].about;
}

const char *setting_shown(int i)
{
    const struct item *it = &items[i];
    const char *v = it->choices[it->cur];
    static char s[24];
    if ((!strcmp(it->key, "fps_limit") || !strcmp(it->key, "mouse_sensitivity")) && !strcmp(v, "0")) return "Off";
    if (!strcmp(it->key, "menu_text_speed")) return snprintf(s, sizeof s, "%sx", v), s;
    if (!strcmp(it->key, "resolution") && !strcmp(v, "auto")) return "Desktop";
    if (!strcmp(it->key, "controls")) return strcmp(v, "classic") ? "WASD + Mouse" : "Classic";
    if (it->count == 2 && !strcmp(it->choices[0], "0")) return it->cur ? "On" : "Off";
    return v;
}

// Re-reads the saved values (and the screen's modes).
void settings_refresh(void)
{
    char v[32];
    fill_resolutions(&items[0]);
    for (int i = 0; i < setting_count(); i++) {
        GetPrivateProfileStringA("taz-hd", items[i].key, items[i].def, v, sizeof v, INI);
        items[i].cur = 0;
        for (int k = 0; k < items[i].count; k++)
            if (!_stricmp(items[i].choices[k], v)) items[i].cur = k;
    }
}

// Moves setting i to its next (dir 1) or previous (dir -1) value, applies and saves it.
void setting_step(int i, int dir)
{
    struct item *it = &items[i];
    if (!it->count) return;
    it->cur = (it->cur + it->count + dir) % it->count;
    const char *v = it->choices[it->cur];
    settings_save(it->key, v);
    log_line("setting: %s = %s", it->key, v);
    if (!strcmp(it->key, "menu_text_speed")) menuspeed_set(settings.menu_speed = (float)atof(v));
    else if (!strcmp(it->key, "fps_limit")) settings.fps_limit = atoi(v);
    else if (!strcmp(it->key, "smooth_characters")) settings.smooth = atoi(v);
    else if (!strcmp(it->key, "mouse_sensitivity")) settings.mouse = atoi(v);
    else if (!strcmp(it->key, "controls")) settings.wasd = strcmp(v, "classic") != 0, controls_apply();
    else if (!strcmp(it->key, "hd_textures")) settings.hd_textures = atoi(v), textures_apply();
    else if (!strcmp(it->key, "vsync")) settings.vsync = atoi(v), display_change(0, 0, settings.vsync);
    else if (!strcmp(it->key, "resolution")) {
        UINT w, h;
        if (settings_resolution(v, &w, &h)) write_resolution(w, h), display_change(w, h, settings.vsync);
    }
}

// Shift+H flips between the game's own graphics (original textures and models, no smoothing) and
// the mod's, for comparing. Saved settings are left alone; the menus show the saved values.
void settings_frame(void)
{
    static int was, original, hd_textures, smooth, hd_models;
    int down = (GetAsyncKeyState('H') & 0x8000) && (GetAsyncKeyState(VK_SHIFT) & 0x8000)
               && GetForegroundWindow() == *(HWND *)0x753724; // the game's window
    if (down && !was) {
        if ((original = !original)) {
            hd_textures = settings.hd_textures, smooth = settings.smooth, hd_models = settings.hd_models;
            settings.hd_textures = settings.smooth = settings.hd_models = 0;
        } else {
            settings.hd_textures = hd_textures, settings.smooth = smooth, settings.hd_models = hd_models;
        }
        textures_apply();
        overlay_toast(original ? "Original graphics (Shift+H)" : "HD graphics (Shift+H)");
        log_line("graphics: %s", original ? "original" : "hd");
    }
    was = down;
}
