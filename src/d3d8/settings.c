// taz-hd.ini in the game folder, replacing the 2002 launcher and config tool. Missing file or keys
// mean defaults. resolution=auto uses the desktop size and is written into taz.dat before the game
// reads it.
#include <stdio.h>
#include <stdlib.h>
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

void settings_save(const char *key, const char *value)
{
    WritePrivateProfileStringA("taz-hd", key, value, INI);
}

void settings_load(void)
{
    char res[32];
    settings.hd_textures = GetPrivateProfileIntA("taz-hd", "hd_textures", 1, INI);
    settings.vsync = GetPrivateProfileIntA("taz-hd", "vsync", 1, INI);
    settings.fps_limit = GetPrivateProfileIntA("taz-hd", "fps_limit", 0, INI);
    settings.passthrough = GetPrivateProfileIntA("taz-hd", "passthrough", 0, INI); // testing: no patches at all
    GetPrivateProfileStringA("taz-hd", "menu_text_speed", "3", res, sizeof res, INI);
    settings.menu_speed = (float)atof(res);
    if (settings.menu_speed < 0.25f || settings.menu_speed > 8.0f) settings.menu_speed = 3.0f;
    GetPrivateProfileStringA("taz-hd", "resolution", "auto", res, sizeof res, INI);

    UINT w = 0, h = 0;
    DEVMODEA mode = { .dmSize = sizeof mode };
    if (!_stricmp(res, "auto")) {
        if (EnumDisplaySettingsA(NULL, ENUM_CURRENT_SETTINGS, &mode)) {
            w = mode.dmPelsWidth;
            h = mode.dmPelsHeight;
        }
    } else if (sscanf(res, "%ux%u", &w, &h) != 2) {
        w = h = 0;
    }
    if (w && h) write_resolution(w, h);
    log_line("settings: resolution=%s hd_textures=%d vsync=%d fps_limit=%d menu_text_speed=%.2f%s", res,
             settings.hd_textures, settings.vsync, settings.fps_limit, settings.menu_speed,
             settings.passthrough ? " passthrough" : "");
}
