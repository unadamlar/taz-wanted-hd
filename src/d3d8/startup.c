// Lets taz.exe start on its own: without the "Launched" argument it opens the 2002 launcher and
// quits, and it finds its folder (and taz.dat) through a registry value only the installer writes.
#include <string.h>
#include "proxy.h"

#define LAUNCHER_JUMP ((BYTE *)0x4aa0dc) // je past the launcher call when the argument is "Launched"
#define GAME_KEY "Software\\Infogrames\\TazWanted\\Release"
#define FAKE_KEY ((HKEY)(ULONG_PTR)0x7a2d0001)

static LSTATUS (WINAPI *real_RegOpenKeyExA)(HKEY, LPCSTR, DWORD, REGSAM, PHKEY);
static LSTATUS (WINAPI *real_RegQueryValueExA)(HKEY, LPCSTR, LPDWORD, LPDWORD, LPBYTE, LPDWORD);
static LSTATUS (WINAPI *real_RegCloseKey)(HKEY);

static LSTATUS WINAPI hook_RegOpenKeyExA(HKEY key, LPCSTR sub, DWORD opts, REGSAM sam, PHKEY out)
{
    if (key != HKEY_LOCAL_MACHINE || !sub || _stricmp(sub, GAME_KEY)) return real_RegOpenKeyExA(key, sub, opts, sam, out);
    *out = FAKE_KEY;
    return ERROR_SUCCESS;
}

// The game's only value there is Location, its folder, which it copies into 80 bytes; answer "." since
// DllMain already made the game folder current.
static LSTATUS WINAPI hook_RegQueryValueExA(HKEY key, LPCSTR name, LPDWORD res, LPDWORD type, LPBYTE data, LPDWORD size)
{
    if (key != FAKE_KEY) return real_RegQueryValueExA(key, name, res, type, data, size);
    const char *dir = ".";
    if (!name || _stricmp(name, "Location")) return ERROR_FILE_NOT_FOUND;
    if (!size) return ERROR_INVALID_PARAMETER;
    if (!data || *size <= strlen(dir)) {
        *size = strlen(dir) + 1;
        return data ? ERROR_MORE_DATA : ERROR_SUCCESS;
    }
    if (type) *type = REG_SZ;
    strcpy((char *)data, dir);
    *size = strlen(dir) + 1;
    return ERROR_SUCCESS;
}

static LSTATUS WINAPI hook_RegCloseKey(HKEY key)
{
    return key == FAKE_KEY ? ERROR_SUCCESS : real_RegCloseKey(key);
}

void startup_patch(void)
{
    real_RegOpenKeyExA = patch_import("ADVAPI32.dll", "RegOpenKeyExA", hook_RegOpenKeyExA);
    real_RegQueryValueExA = patch_import("ADVAPI32.dll", "RegQueryValueExA", hook_RegQueryValueExA);
    real_RegCloseKey = patch_import("ADVAPI32.dll", "RegCloseKey", hook_RegCloseKey);
    if (!real_RegOpenKeyExA || !real_RegQueryValueExA || !real_RegCloseKey) log_line("startup: registry imports not found");

    static const BYTE orig[] = { 0x74, 0x13 };
    if (memcmp(LAUNCHER_JUMP, orig, sizeof orig)) {
        log_line("startup: unexpected code at %p, the launcher still opens without \"Launched\"", LAUNCHER_JUMP);
        return;
    }
    DWORD old;
    VirtualProtect(LAUNCHER_JUMP, 1, PAGE_EXECUTE_READWRITE, &old);
    *LAUNCHER_JUMP = 0xeb; // always jump, as if "Launched" was given
    VirtualProtect(LAUNCHER_JUMP, 1, old, &old);
    FlushInstructionCache(GetCurrentProcess(), LAUNCHER_JUMP, 1);
}
