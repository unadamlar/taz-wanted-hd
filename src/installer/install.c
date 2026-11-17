// Player installer: finds Taz: Wanted folders and writes d3d8.dll and taz-hd\ into one. The mod's files are
// packed onto the end of the exe by tools/pack-installer.py.
// Command line (for tests and the elevated relaunch): --list [--all], --install <dir>, --uninstall <dir>, --quiet.
#define COBJMACROS
#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <tlhelp32.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#define RETAIL_TIMESTAMP 0x3d3bc9b0 // taz.exe linked 2002-07-22
#define GAME_KEY L"Software\\Infogrames\\TazWanted\\Release"
#define UNINSTALL_KEY L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
#define WINE_KEY L"Software\\Wine\\DllOverrides"
#define WINE_VALUE L"native,builtin"
#define MARK ".\\taz-hd.ini" // in every build of our d3d8.dll
#define PACK_MAGIC "TAZHDPK1"
#define DAMAGED L"This installer file is damaged or incomplete. Download it again."
#define CLOSE_GAME L"Taz: Wanted is running. Close the game first, then try again."
#define PATH 1024
#define MAX_GAMES 32
#define FOREVER (~0ULL)

enum { DLL_NONE, DLL_OURS, DLL_OTHER, DLL_LINK };
enum { OK, FAILED, NEED_ADMIN };
enum { OP_INSTALL = 1, OP_UNINSTALL };
enum { ID_LIST = 100, ID_BROWSE, ID_PLAY, ID_INSTALL, ID_UNINSTALL, ID_CLOSE };
enum { WM_PROGRESS = WM_APP, WM_TASK_DONE, WM_ELEVATED_DONE, WM_FOUND, WM_SEARCH_DONE };

typedef struct { WCHAR dir[PATH]; int dll, retail, hd; } Game;

static Game games[MAX_GAMES];
static int ngames, src_ok, wine, searching, plain_header;
static WCHAR src[PATH];
static ULONGLONG copied, total;
static HANDLE pack; // this exe
static DWORD pack_start, pack_count;
static int last_permille = -1;
static HWND wnd, list, text, bar, btn[5];
static int dpi = 96, busy, done_index = -1, task_mode, exit_code;
static struct { int op, index; DWORD res; WCHAR dir[PATH], msg[3 * PATH]; } task;

static int S(int x) { return MulDiv(x, dpi, 96); }
static DWORD attrs(const WCHAR *p) { return GetFileAttributesW(p); }
static int exists(const WCHAR *p) { return attrs(p) != INVALID_FILE_ATTRIBUTES; }
static int is_dir(const WCHAR *p) { DWORD a = attrs(p); return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY); }

static void join(WCHAR *out, const WCHAR *dir, const WCHAR *name)
{
    size_t n = wcslen(dir);
    _snwprintf(out, PATH, n && dir[n - 1] == '\\' ? L"%ls%ls" : L"%ls\\%ls", dir, name);
    out[PATH - 1] = 0;
}

// \\?\ form, so texture paths deep inside a long game path still work.
static void long_form(WCHAR *out, const WCHAR *p)
{
    if (p[0] == '\\' && p[1] == '\\') _snwprintf(out, PATH, L"\\\\?\\UNC\\%ls", p + 2);
    else _snwprintf(out, PATH, L"\\\\?\\%ls", p);
    out[PATH - 1] = 0;
}

static void say(const WCHAR *fmt, ...)
{
    static HANDLE h;
    WCHAR b[4 * PATH];
    va_list ap;
    va_start(ap, fmt);
    _vsnwprintf(b, 4 * PATH - 2, fmt, ap);
    va_end(ap);
    b[4 * PATH - 2] = 0;
    wcscat(b, L"\n");
    if (!h) {
        h = GetStdHandle(STD_OUTPUT_HANDLE);
        if ((!h || h == INVALID_HANDLE_VALUE) && AttachConsole(ATTACH_PARENT_PROCESS))
            h = CreateFileW(L"CONOUT$", GENERIC_WRITE, FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    }
    DWORD n, mode;
    if (GetConsoleMode(h, &mode)) {
        WriteConsoleW(h, b, wcslen(b), &n, NULL);
        return;
    }
    char u[16 * PATH];
    int len = WideCharToMultiByte(CP_UTF8, 0, b, -1, u, sizeof u, NULL, NULL);
    if (len > 1) WriteFile(h, u, len - 1, &n, NULL);
}

// ---- detection

static int add_game(const WCHAR *dir)
{
    WCHAR full[PATH], lng[PATH], exe[PATH];
    if (!dir[0]) return -1;
    DWORD n = GetFullPathNameW(dir, PATH, full, NULL);
    if (!n || n >= PATH) return -1;
    n = GetLongPathNameW(full, lng, PATH);
    if (n && n < PATH) wcscpy(full, lng);
    n = wcslen(full);
    while (n > 3 && full[n - 1] == '\\') full[--n] = 0;
    join(exe, full, L"taz.exe");
    if (!exists(exe) || is_dir(exe)) return -1;
    for (int i = 0; i < ngames; i++)
        if (!lstrcmpiW(games[i].dir, full)) return i;
    if (ngames == MAX_GAMES) return -1;
    wcscpy(games[ngames].dir, full);
    return ngames++;
}

// until FOREVER: the whole-computer search on its own thread, which hands what it finds to the window.
static void scan(const WCHAR *dir, int depth, ULONGLONG until)
{
    WCHAR p[PATH];
    WIN32_FIND_DATAW fd;
    if (GetTickCount64() > until) return;
    join(p, dir, L"taz.exe");
    if (exists(p)) {
        if (until == FOREVER && wnd) PostMessageW(wnd, WM_FOUND, 0, (LPARAM)_wcsdup(dir));
        else add_game(dir);
    }
    if (!depth) return;
    join(p, dir, L"*");
    HANDLE h = FindFirstFileExW(p, FindExInfoBasic, &fd, FindExSearchLimitToDirectories, NULL, FIND_FIRST_EX_LARGE_FETCH);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        // reparse points: Windows' compatibility junctions and links that loop back
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) || fd.cFileName[0] == '.' || fd.cFileName[0] == '$') continue;
        join(p, dir, fd.cFileName);
        scan(p, depth - 1, until);
    } while (FindNextFileW(h, &fd) && GetTickCount64() <= until);
    FindClose(h);
}

static int reg_string(HKEY k, const WCHAR *name, WCHAR *out)
{
    DWORD type, size = (PATH - 1) * sizeof(WCHAR);
    if (RegQueryValueExW(k, name, NULL, &type, (BYTE *)out, &size) || (type != REG_SZ && type != REG_EXPAND_SZ)) return 0;
    out[size / sizeof(WCHAR)] = 0;
    if (out[0] == '"') {
        memmove(out, out + 1, wcslen(out) * sizeof(WCHAR));
        WCHAR *q = wcschr(out, '"');
        if (q) *q = 0;
    }
    return 1;
}

static void detect_registry(HKEY root, REGSAM view)
{
    HKEY k, e;
    WCHAR v[PATH], name[256];
    if (!RegOpenKeyExW(root, GAME_KEY, 0, KEY_READ | view, &k)) {
        if (reg_string(k, L"Location", v)) add_game(v);
        RegCloseKey(k);
    }
    if (RegOpenKeyExW(root, UNINSTALL_KEY, 0, KEY_READ | view, &k)) return;
    for (DWORD i = 0;; i++) {
        DWORD n = 256;
        if (RegEnumKeyExW(k, i, name, &n, NULL, NULL, NULL, NULL)) break;
        if (RegOpenKeyExW(k, name, 0, KEY_READ | view, &e)) continue;
        if (reg_string(e, L"DisplayName", v)) {
            CharLowerW(v);
            if (wcsstr(v, L"taz") && wcsstr(v, L"wanted") && reg_string(e, L"InstallLocation", v)) add_game(v);
        }
        RegCloseKey(e);
    }
    RegCloseKey(k);
}

static void detect(void)
{
    static const HKEY roots[] = { HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER };
    static const REGSAM views[] = { KEY_WOW64_32KEY, KEY_WOW64_64KEY };
    static const WCHAR *known[] = { L"Program Files (x86)\\Infogrames\\Taz Wanted", L"Program Files\\Infogrames\\Taz Wanted",
        L"Program Files (x86)\\Atari\\Taz Wanted", L"Program Files\\Atari\\Taz Wanted", L"Games\\Taz Wanted", L"Taz Wanted" };
    static const WCHAR *deep[] = { L"Games", L"Program Files (x86)", L"Program Files" };
    static const KNOWNFOLDERID *user[] = { &FOLDERID_Desktop, &FOLDERID_Documents, &FOLDERID_Downloads };
    WCHAR drives[256], p[PATH];
    ULONGLONG deadline = GetTickCount64() + 2000;

    for (int r = 0; r < 2; r++)
        for (int v = 0; v < 2; v++) detect_registry(roots[r], views[v]);
    add_game(src); // downloaded into the game folder, or a folder inside it
    join(p, src, L"..");
    add_game(p);
    GetLogicalDriveStringsW(255, drives);
    for (WCHAR *d = drives; *d; d += wcslen(d) + 1)
        if (GetDriveTypeW(d) == DRIVE_FIXED)
            for (int i = 0; i < 6; i++) {
                join(p, d, known[i]);
                add_game(p);
            }
    for (int i = 0; i < 3; i++) {
        PWSTR f;
        if (SUCCEEDED(SHGetKnownFolderPath(user[i], 0, NULL, &f))) {
            scan(f, 3, deadline);
            CoTaskMemFree(f);
        }
    }
    for (WCHAR *d = drives; *d; d += wcslen(d) + 1) {
        if (GetDriveTypeW(d) != DRIVE_FIXED) continue;
        scan(d, 1, deadline);
        for (int i = 0; i < 3; i++) {
            join(p, d, deep[i]);
            scan(p, 2, deadline);
        }
    }
}

// Every folder of every fixed drive, for a game copied somewhere detect() doesn't look.
static DWORD WINAPI search(void *arg)
{
    static char *(CDECL *unix_name)(const WCHAR *);
    WCHAR drives[256], p[PATH];
    WIN32_FIND_DATAW fd;
    if (wine) unix_name = (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "wine_get_unix_file_name");
    GetLogicalDriveStringsW(255, drives);
    for (WCHAR *d = drives; *d; d += wcslen(d) + 1) {
        if (GetDriveTypeW(d) != DRIVE_FIXED) continue;
        char *u = unix_name ? unix_name(d) : NULL;
        int unix_root = u && !strcmp(u, "/"); // Wine's Z: is all of Linux, /proc included
        HeapFree(GetProcessHeap(), 0, u);
        if (unix_root) continue;
        join(p, d, L"*");
        HANDLE h = FindFirstFileExW(p, FindExInfoBasic, &fd, FindExSearchLimitToDirectories, NULL, FIND_FIRST_EX_LARGE_FETCH);
        if (h == INVALID_HANDLE_VALUE) continue;
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
                || fd.cFileName[0] == '.' || fd.cFileName[0] == '$' || !lstrcmpiW(fd.cFileName, L"Windows")) continue;
            join(p, d, fd.cFileName);
            scan(p, 16, FOREVER);
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    if (wnd) PostMessageW(wnd, WM_SEARCH_DONE, 0, 0);
    return 0;
}

// ---- game folder state

static DWORD pe_stamp(const WCHAR *exe)
{
    BYTE b[4096];
    DWORD n = 0, stamp = 0;
    HANDLE h = CreateFileW(exe, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    if (ReadFile(h, b, sizeof b, &n, NULL) && n >= 64 && b[0] == 'M' && b[1] == 'Z') {
        DWORD pe = *(DWORD *)(b + 0x3c);
        if (pe + 12 <= n && !memcmp(b + pe, "PE\0\0", 4)) stamp = *(DWORD *)(b + pe + 8);
    }
    CloseHandle(h);
    return stamp;
}

static int has_mark(const WCHAR *path)
{
    int found = 0;
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    DWORD size = GetFileSize(h, NULL), n;
    char *b = size < (64u << 20) ? HeapAlloc(GetProcessHeap(), 0, size) : NULL;
    if (b && ReadFile(h, b, size, &n, NULL))
        for (DWORD i = 0; !found && i + sizeof MARK - 1 <= n; i++) found = !memcmp(b + i, MARK, sizeof MARK - 1);
    if (b) HeapFree(GetProcessHeap(), 0, b);
    CloseHandle(h);
    return found;
}

// Wine shows symlinks to files as plain files; its Unix name for them is the target's.
static int is_link(const WCHAR *path)
{
    static char *(CDECL *unix_name)(const WCHAR *);
    WCHAR parent[PATH];
    char name[PATH];
    DWORD at = attrs(path);
    if (at == INVALID_FILE_ATTRIBUTES) return 0;
    if (at & FILE_ATTRIBUTE_REPARSE_POINT) return 1;
    if (!wine) return 0;
    if (!unix_name) unix_name = (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "wine_get_unix_file_name");
    wcscpy(parent, path);
    WCHAR *slash = wcsrchr(parent, '\\');
    if (!slash || !unix_name) return 1; // can't tell: the safe side
    *slash = 0;
    WideCharToMultiByte(CP_UTF8, 0, slash + 1, -1, name, PATH, NULL, NULL);
    char *a = unix_name(parent), *b = unix_name(path);
    size_t n = a ? strlen(a) : 0;
    int link = !a || !b || strncmp(a, b, n) || b[n] != '/' || _stricmp(b + n + 1, name);
    HeapFree(GetProcessHeap(), 0, a);
    HeapFree(GetProcessHeap(), 0, b);
    return link;
}

static int dll_state(const WCHAR *dir)
{
    WCHAR p[PATH];
    join(p, dir, L"d3d8.dll");
    if (!exists(p)) return DLL_NONE;
    if (is_link(p)) return DLL_LINK;
    return has_mark(p) ? DLL_OURS : DLL_OTHER;
}

static void update_game(Game *g)
{
    WCHAR p[PATH];
    join(p, g->dir, L"taz.exe");
    g->retail = pe_stamp(p) == RETAIL_TIMESTAMP;
    g->dll = dll_state(g->dir);
    join(p, g->dir, L"taz-hd");
    g->hd = is_dir(p);
}

static void status_text(const Game *g, WCHAR *out)
{
    const WCHAR *s = g->dll == DLL_LINK ? L"Developer setup (d3d8.dll is a link)" : g->dll == DLL_OURS ? L"Installed"
        : g->dll == DLL_OTHER ? L"Not installed (has another d3d8.dll)" : L"Not installed";
    _snwprintf(out, 128, L"%ls%ls", s, g->retail ? L"" : L"; other game version");
    out[127] = 0;
}

// ---- install and uninstall (worker thread)

static DWORD fail(WCHAR *msg, const WCHAR *what, DWORD err, const WCHAR *path)
{
    WCHAR sys[512] = L"";
    if (err == ERROR_SHARING_VIOLATION || err == ERROR_LOCK_VIOLATION || err == ERROR_USER_MAPPED_FILE) what = CLOSE_GAME;
    else if (err == ERROR_DISK_FULL || err == ERROR_HANDLE_DISK_FULL) what = L"The disk is full. The HD mod needs about 700 MB of free space.";
    else if (err) FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, NULL, err, 0, sys, 512, NULL);
    if (path && !wcsncmp(path, L"\\\\?\\", 4)) path += 4;
    _snwprintf(msg, 3 * PATH, L"%ls%ls%ls%ls%ls", what, sys[0] ? L"\n\n" : L"", sys, path ? L"\n\n" : L"", path ? path : L"");
    msg[3 * PATH - 1] = 0;
    return FAILED;
}

static int game_running(void)
{
    PROCESSENTRY32W pe = { sizeof pe };
    int found = 0;
    HANDLE h = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (h == INVALID_HANDLE_VALUE) return 0;
    for (BOOL ok = Process32FirstW(h, &pe); ok && !found; ok = Process32NextW(h, &pe)) found = !lstrcmpiW(pe.szExeFile, L"taz.exe");
    CloseHandle(h);
    return found;
}

static int elevated(void)
{
    HANDLE t;
    TOKEN_ELEVATION e = { 0 };
    DWORD n;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &t)) return 0;
    GetTokenInformation(t, TokenElevation, &e, sizeof e, &n);
    CloseHandle(t);
    return e.TokenIsElevated;
}

// Common checks; OK when the folder can be changed.
static DWORD check_folder(const WCHAR *dir, const WCHAR *ldir, WCHAR *msg)
{
    WCHAR p[PATH];
    if (dll_state(dir) == DLL_LINK)
        return fail(msg, L"d3d8.dll in this folder is a link to another file (a developer setup). The installer leaves this folder alone.", 0, NULL);
    if (game_running()) return fail(msg, CLOSE_GAME, 0, NULL);
    join(p, ldir, L"taz-hd-write-test.tmp");
    HANDLE h = CreateFileW(p, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        CloseHandle(h);
        return OK;
    }
    DWORD e = GetLastError();
    if (e == ERROR_ACCESS_DENIED && !elevated()) return NEED_ADMIN;
    return fail(msg, L"The installer can't write to this folder.", e, dir);
}

static void progress(ULONGLONG bytes)
{
    copied += bytes;
    int pm = total ? (int)(copied * 1000 / total) : 0;
    if (pm != last_permille && wnd) PostMessageW(wnd, WM_PROGRESS, pm, 0);
    last_permille = pm;
}

// The packed files follow the exe's last section: magic, file count, total bytes, then per file
// name length (u16), UTF-8 name, size (u32), data.
static int open_pack(void)
{
    WCHAR exe[PATH];
    BYTE b[4096];
    DWORD n, end = 0;
    GetModuleFileNameW(NULL, exe, PATH);
    pack = CreateFileW(exe, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (pack == INVALID_HANDLE_VALUE || !ReadFile(pack, b, sizeof b, &n, NULL) || n != sizeof b) return 0;
    IMAGE_NT_HEADERS32 *nt = (void *)(b + ((IMAGE_DOS_HEADER *)b)->e_lfanew);
    IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; i++)
        if (sec[i].PointerToRawData + sec[i].SizeOfRawData > end) end = sec[i].PointerToRawData + sec[i].SizeOfRawData;
    if (SetFilePointer(pack, end, NULL, FILE_BEGIN) != end || !ReadFile(pack, b, 20, &n, NULL) || n != 20 || memcmp(b, PACK_MAGIC, 8)) return 0;
    pack_count = *(DWORD *)(b + 8);
    total = *(ULONGLONG *)(b + 12);
    pack_start = end + 20;
    return pack_count > 0;
}

static int read_pack(void *out, DWORD size)
{
    DWORD n;
    return ReadFile(pack, out, size, &n, NULL) && n == size;
}

static DWORD write_file(const WCHAR *path, DWORD size, WCHAR *msg)
{
    static BYTE buf[1 << 20];
    WCHAR dir[PATH];
    DWORD res = OK, n;
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE && GetLastError() == ERROR_PATH_NOT_FOUND) {
        wcscpy(dir, path);
        for (WCHAR *s = wcschr(dir + 4, '\\'); s; s = wcschr(s + 1, '\\')) {
            *s = 0;
            CreateDirectoryW(dir, NULL);
            *s = '\\';
        }
        h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    }
    if (h == INVALID_HANDLE_VALUE) return fail(msg, L"Couldn't copy a file.", GetLastError(), path);
    for (; size && res == OK; size -= n) {
        n = size < sizeof buf ? size : sizeof buf;
        if (!read_pack(buf, n)) res = fail(msg, DAMAGED, 0, NULL);
        else if (!WriteFile(h, buf, n, &n, NULL)) res = fail(msg, L"Couldn't copy a file.", GetLastError(), path);
        else progress(n);
    }
    CloseHandle(h);
    return res;
}

// Never follows links. Wine applies deletes to a link's target, so there links are refused instead.
static DWORD delete_tree(const WCHAR *dir, WCHAR *msg)
{
    WCHAR p[PATH];
    WIN32_FIND_DATAW fd;
    DWORD res = OK;
    if (!exists(dir)) return OK;
    if (is_link(dir)) {
        if (wine) return fail(msg, L"A folder here is a link to another folder; the installer leaves it alone. Remove the link yourself, then try again.", 0, dir);
        return RemoveDirectoryW(dir) ? OK : fail(msg, L"Couldn't remove a folder link.", GetLastError(), dir);
    }
    join(p, dir, L"*");
    HANDLE h = FindFirstFileExW(p, FindExInfoBasic, &fd, FindExSearchNameMatch, NULL, FIND_FIRST_EX_LARGE_FETCH);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
            join(p, dir, fd.cFileName);
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) res = delete_tree(p, msg);
            else if (wine && is_link(p)) res = fail(msg, L"A file here is a link to another file; the installer leaves it alone. Remove the link yourself, then try again.", 0, p);
            else if (!DeleteFileW(p) && !(GetLastError() == ERROR_ACCESS_DENIED && SetFileAttributesW(p, FILE_ATTRIBUTE_NORMAL) && DeleteFileW(p)))
                res = fail(msg, L"Couldn't delete a file.", GetLastError(), p);
        } while (res == OK && FindNextFileW(h, &fd));
        FindClose(h);
    }
    if (res == OK && !RemoveDirectoryW(dir)) res = fail(msg, L"Couldn't delete a folder.", GetLastError(), dir);
    return res;
}

static void wine_override(int set)
{
    HKEY k;
    WCHAR v[64];
    if (RegCreateKeyExW(HKEY_CURRENT_USER, WINE_KEY, 0, NULL, 0, KEY_READ | KEY_WRITE, NULL, &k, NULL)) return;
    if (set) RegSetValueExW(k, L"d3d8", 0, REG_SZ, (const BYTE *)WINE_VALUE, sizeof WINE_VALUE);
    else if (reg_string(k, L"d3d8", v) && !wcscmp(v, WINE_VALUE)) RegDeleteValueW(k, L"d3d8");
    RegCloseKey(k);
}

static DWORD do_install(const WCHAR *dir, WCHAR *msg)
{
    WCHAR d[PATH], bak[PATH], p[PATH], name[PATH], cleared[PATH] = L"";
    char name8[PATH];
    WORD len;
    DWORD size;
    long_form(d, dir);
    DWORD res = check_folder(dir, d, msg);
    if (res) return res;
    int other = dll_state(dir) == DLL_OTHER;
    join(bak, d, L"d3d8.dll.bak");
    if (other && exists(bak))
        return fail(msg, L"This folder has another mod's d3d8.dll and already a d3d8.dll.bak. Move one of them somewhere else, then try again.", 0, NULL);
    SetFilePointer(pack, pack_start, NULL, FILE_BEGIN);
    copied = 0;
    for (DWORD i = 0; i < pack_count; i++) {
        if (!read_pack(&len, 2) || len >= PATH || !read_pack(name8, len) || !read_pack(&size, 4)) return fail(msg, DAMAGED, 0, NULL);
        name8[len] = 0;
        MultiByteToWideChar(CP_UTF8, 0, name8, -1, name, PATH);
        // An older copy of each of the mod's folders goes first, so files a newer version dropped don't
        // linger; anything else in taz-hd (screenshots) stays.
        WCHAR *sub = !wcsncmp(name, L"taz-hd\\", 7) ? wcschr(name + 7, '\\') : NULL;
        if (sub && (wcsncmp(name, cleared, sub - name) || cleared[sub - name])) {
            wcsncpy(cleared, name, sub - name);
            cleared[sub - name] = 0;
            join(p, d, cleared);
            if ((res = delete_tree(p, msg))) return res;
        }
        join(p, d, name);
        if (!wcscmp(name, L"d3d8.dll")) { // packed last, so a failed copy never leaves the mod half installed and active
            if (other && !MoveFileW(p, bak)) return fail(msg, L"Couldn't keep the other d3d8.dll as d3d8.dll.bak.", GetLastError(), p);
            SetFileAttributesW(p, FILE_ATTRIBUTE_NORMAL);
        } else if (wine && exists(p) && is_link(p))
            return fail(msg, L"A file here is a link to another file; the installer leaves it alone.", 0, p);
        if ((res = write_file(p, size, msg))) return res;
    }
    if (wine) wine_override(1);
    return OK;
}

static DWORD do_uninstall(const WCHAR *dir, WCHAR *msg)
{
    WCHAR d[PATH], a[PATH], b[PATH];
    long_form(d, dir);
    DWORD res = check_folder(dir, d, msg);
    if (res) return res;
    join(a, d, L"d3d8.dll");
    join(b, d, L"d3d8.dll.bak");
    if (dll_state(dir) == DLL_OURS) {
        if (!DeleteFileW(a)) return fail(msg, L"Couldn't remove d3d8.dll.", GetLastError(), a);
        if (exists(b) && !MoveFileW(b, a)) return fail(msg, L"Couldn't put the other mod's d3d8.dll back.", GetLastError(), b);
    }
    join(a, d, L"taz-hd");
    if ((res = delete_tree(a, msg))) return res;
    join(a, d, L"taz-hd.ini");
    DeleteFileW(a);
    join(a, d, L"taz-hd.log");
    DeleteFileW(a);
    if (wine) {
        int others = 0;
        for (int i = 0; i < ngames; i++) others |= lstrcmpiW(games[i].dir, dir) && dll_state(games[i].dir) == DLL_OURS;
        if (!others) wine_override(0);
    }
    return OK;
}

static DWORD WINAPI worker(void *arg)
{
    task.res = task.op == OP_INSTALL ? do_install(task.dir, task.msg) : do_uninstall(task.dir, task.msg);
    PostMessageW(wnd, WM_TASK_DONE, 0, 0);
    return 0;
}

static DWORD WINAPI wait_elevated(void *process)
{
    DWORD code = 1;
    WaitForSingleObject(process, INFINITE);
    GetExitCodeProcess(process, &code);
    CloseHandle(process);
    PostMessageW(wnd, WM_ELEVATED_DONE, code, 0);
    return 0;
}

// ---- window

static int selected(void) { return (int)SendMessageW(list, LVM_GETNEXTITEM, -1, LVNI_SELECTED); }

static void header(const WCHAR *fmt, ...)
{
    WCHAR b[2 * PATH];
    va_list ap;
    va_start(ap, fmt);
    _vsnwprintf(b, 2 * PATH - 1, fmt, ap);
    va_end(ap);
    b[2 * PATH - 1] = 0;
    SetWindowTextW(text, b);
    plain_header = 0;
}

static void normal_header(void)
{
    if (!src_ok) header(DAMAGED);
    else if (!ngames && searching) header(L"Looking for Taz: Wanted on this computer... If you know where it is, click Browse... "
        L"and choose the folder with taz.exe in it.");
    else if (!ngames) header(L"Taz: Wanted wasn't found on this computer. Click Browse... and choose the folder where "
        L"the game is installed (the one with taz.exe in it).");
    else header(L"Choose your Taz: Wanted folder and click Install. Your saved games are not touched. %ls",
        searching ? L"Still looking through the rest of this computer..." : L"If your game is not in the list, click Browse...");
    plain_header = 1;
}

static void update_buttons(void)
{
    int i = selected();
    Game *g = i >= 0 ? &games[i] : NULL;
    EnableWindow(btn[0], !busy);
    EnableWindow(btn[2], !busy && src_ok && g && g->dll != DLL_LINK);
    EnableWindow(btn[3], !busy && g && g->dll != DLL_LINK && (g->dll == DLL_OURS || g->hd));
    EnableWindow(btn[4], !busy);
    SetWindowTextW(btn[2], g && g->dll == DLL_OURS ? L"&Reinstall" : L"&Install");
    ShowWindow(btn[1], !busy && i >= 0 && i == done_index ? SW_SHOW : SW_HIDE);
}

static void fill_list(int sel)
{
    WCHAR st[128];
    SendMessageW(list, LVM_DELETEALLITEMS, 0, 0);
    for (int i = 0; i < ngames; i++) {
        update_game(&games[i]);
        status_text(&games[i], st);
        LVITEMW it = { LVIF_TEXT, i, 0 };
        it.pszText = games[i].dir;
        SendMessageW(list, LVM_INSERTITEMW, 0, (LPARAM)&it);
        it.iSubItem = 1;
        it.pszText = st;
        SendMessageW(list, LVM_SETITEMTEXTW, i, (LPARAM)&it);
    }
    SendMessageW(list, LVM_SETCOLUMNWIDTH, 1, LVSCW_AUTOSIZE_USEHEADER);
    if (sel < 0 && ngames) sel = 0;
    if (sel >= 0) {
        LVITEMW it = { LVIF_STATE };
        it.state = it.stateMask = LVIS_SELECTED | LVIS_FOCUSED;
        SendMessageW(list, LVM_SETITEMSTATE, sel, (LPARAM)&it);
        SendMessageW(list, LVM_ENSUREVISIBLE, sel, FALSE);
        SetFocus(list);
    }
    update_buttons();
}

static void set_busy(int b)
{
    busy = b;
    ShowWindow(bar, b ? SW_SHOW : SW_HIDE);
    SendMessageW(bar, PBM_SETPOS, 0, 0);
    last_permille = -1;
    update_buttons();
}

static void start_task(int op, int i)
{
    if (!task_mode) {
        if (op == OP_INSTALL && !games[i].retail && MessageBoxW(wnd, L"This taz.exe is a different version from the 2002 PC release "
                L"the mod was made for. HD textures should still work, but other parts of the mod may not.\n\nInstall anyway?",
                L"Different game version", MB_YESNO | MB_ICONWARNING) != IDYES) return;
        if (op == OP_UNINSTALL && MessageBoxW(wnd, L"Remove the HD mod from this folder?\n\nThis deletes d3d8.dll, the taz-hd folder "
                L"(including HD screenshots in it) and the mod's settings. The game itself and your saved games stay.",
                L"Uninstall", MB_YESNO | MB_ICONQUESTION) != IDYES) return;
    }
    task.op = op;
    task.index = i;
    wcscpy(task.dir, games[i].dir);
    done_index = -1;
    set_busy(1);
    header(op == OP_INSTALL ? L"Copying the HD mod into %ls ...\nThis can take a minute." : L"Removing the HD mod from %ls ...", task.dir);
    CloseHandle(CreateThread(NULL, 0, worker, NULL, 0, NULL));
}

static void elevate(void)
{
    WCHAR exe[PATH], args[PATH + 32];
    size_t n = wcslen(task.dir);
    GetModuleFileNameW(NULL, exe, PATH);
    _snwprintf(args, PATH + 32, L"%ls \"%ls%ls\"", task.op == OP_INSTALL ? L"--install" : L"--uninstall", task.dir, task.dir[n - 1] == '\\' ? L"." : L"");
    args[PATH + 31] = 0;
    SHELLEXECUTEINFOW sei = { sizeof sei, SEE_MASK_NOCLOSEPROCESS, wnd, L"runas", exe, args, NULL, SW_SHOWNORMAL };
    if (!ShellExecuteExW(&sei) || !sei.hProcess) {
        MessageBoxW(wnd, L"This folder can only be changed with administrator permission, which was not given.", L"Taz: Wanted HD", MB_ICONWARNING);
        normal_header();
        return;
    }
    set_busy(1);
    ShowWindow(bar, SW_HIDE);
    header(L"Continuing in the administrator window...");
    CloseHandle(CreateThread(NULL, 0, wait_elevated, sei.hProcess, 0, NULL));
}

static void finished(DWORD res)
{
    fill_list(task.index);
    if (res) {
        normal_header();
        return;
    }
    if (task.op == OP_UNINSTALL) {
        header(L"The HD mod was removed from %ls.", task.dir);
        return;
    }
    done_index = task.index;
    header(L"Done! Taz: Wanted HD is installed. Click Play now, or start the game the way you usually do.%ls",
        wine ? L"\nWine was set to load the mod's d3d8.dll (DllOverrides: d3d8 = native,builtin)." : L"");
    update_buttons();
}

static void browse(void)
{
    IFileOpenDialog *d;
    IShellItem *item;
    PWSTR p;
    if (FAILED(CoCreateInstance(&CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER, &IID_IFileOpenDialog, (void **)&d))) return;
    IFileOpenDialog_SetOptions(d, FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
    IFileOpenDialog_SetTitle(d, L"Choose the Taz: Wanted folder (the one with taz.exe in it)");
    if (SUCCEEDED(IFileOpenDialog_Show(d, wnd)) && SUCCEEDED(IFileOpenDialog_GetResult(d, &item))) {
        if (SUCCEEDED(IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &p))) {
            int n = ngames, i = add_game(p);
            if (i < 0) { // maybe a folder above the game's
                scan(p, 2, GetTickCount64() + 2000);
                if (ngames > n) i = n;
            }
            if (i < 0) MessageBoxW(wnd, L"There is no taz.exe in that folder. Choose the folder where Taz: Wanted is installed.", L"Taz: Wanted HD", MB_ICONINFORMATION);
            else {
                fill_list(i);
                normal_header();
            }
            CoTaskMemFree(p);
        }
        IShellItem_Release(item);
    }
    IFileOpenDialog_Release(d);
}

static HWND control(const WCHAR *cls, const WCHAR *label, DWORD style, int id, HFONT font)
{
    HWND h = CreateWindowExW(0, cls, label, WS_CHILD | WS_VISIBLE | style, 0, 0, 0, 0, wnd, (HMENU)(INT_PTR)id, NULL, NULL);
    SendMessageW(h, WM_SETFONT, (WPARAM)font, FALSE);
    return h;
}

// Layout in 96-dpi units: 640 x 380 client area.
static void layout(void)
{
    int w = 640, bw = 104, bh = 30, gap = 8, by = 380 - 16 - bh;
    MoveWindow(text, S(16), S(14), S(w - 32), S(52), FALSE);
    MoveWindow(list, S(16), S(72), S(w - 32), S(222), FALSE);
    MoveWindow(bar, S(16), S(306), S(w - 32), S(18), FALSE);
    MoveWindow(btn[0], S(16), S(by), S(bw), S(bh), FALSE);
    MoveWindow(btn[1], S(16 + bw + gap), S(by), S(bw), S(bh), FALSE);
    for (int i = 2; i < 5; i++) MoveWindow(btn[i], S(w - 16 - (5 - i) * bw - (4 - i) * gap), S(by), S(bw), S(bh), FALSE);
}

static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM wp, LPARAM lp)
{
    switch (m) {
    case WM_CREATE: {
        static const WCHAR *labels[] = { L"&Browse...", L"&Play now", L"&Install", L"&Uninstall", L"&Close" };
        NONCLIENTMETRICSW ncm = { sizeof ncm };
        SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof ncm, &ncm, 0);
        HFONT font = CreateFontIndirectW(&ncm.lfMessageFont);
        wnd = h;
        text = control(L"STATIC", L"Looking for Taz: Wanted on this computer...", SS_LEFT, 0, font);
        list = control(WC_LISTVIEWW, L"", WS_BORDER | WS_TABSTOP | LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS | LVS_NOSORTHEADER, ID_LIST, font);
        bar = control(PROGRESS_CLASSW, L"", 0, 0, font);
        SendMessageW(bar, PBM_SETRANGE32, 0, 1000);
        ShowWindow(bar, SW_HIDE);
        for (int i = 0; i < 5; i++) btn[i] = control(L"BUTTON", labels[i], WS_TABSTOP | (i == 2 ? BS_DEFPUSHBUTTON : 0), ID_BROWSE + i, font);
        SendMessageW(list, LVM_SETEXTENDEDLISTVIEWSTYLE, 0, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER);
        LVCOLUMNW c = { LVCF_TEXT | LVCF_WIDTH, 0, S(340), L"Game folder" };
        SendMessageW(list, LVM_INSERTCOLUMNW, 0, (LPARAM)&c);
        c.cx = S(244);
        c.pszText = L"Status";
        SendMessageW(list, LVM_INSERTCOLUMNW, 1, (LPARAM)&c);
        layout();
        return 0;
    }
    case WM_CTLCOLORSTATIC:
        SetBkColor((HDC)wp, GetSysColor(COLOR_WINDOW));
        return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
    case WM_NOTIFY:
        if (((NMHDR *)lp)->idFrom == ID_LIST && ((NMHDR *)lp)->code == LVN_ITEMCHANGED) update_buttons();
        return 0;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_BROWSE: browse(); break;
        case ID_INSTALL: if (selected() >= 0) start_task(OP_INSTALL, selected()); break;
        case ID_UNINSTALL: if (selected() >= 0) start_task(OP_UNINSTALL, selected()); break;
        case ID_PLAY: {
            WCHAR exe[PATH];
            join(exe, games[done_index].dir, L"taz.exe");
            if ((INT_PTR)ShellExecuteW(h, NULL, exe, NULL, games[done_index].dir, SW_SHOWNORMAL) > 32) DestroyWindow(h);
            break;
        }
        case ID_CLOSE: case IDCANCEL: PostMessageW(h, WM_CLOSE, 0, 0); break;
        }
        return 0;
    case WM_PROGRESS:
        SendMessageW(bar, PBM_SETPOS, wp, 0);
        return 0;
    case WM_TASK_DONE:
        set_busy(0);
        if (task_mode) {
            if (task.res) MessageBoxW(h, task.msg, L"Taz: Wanted HD", MB_ICONERROR);
            exit_code = task.res != OK;
            DestroyWindow(h);
        } else if (task.res == NEED_ADMIN) elevate();
        else {
            if (task.res) MessageBoxW(h, task.msg, L"Taz: Wanted HD", MB_ICONERROR);
            finished(task.res);
        }
        return 0;
    case WM_ELEVATED_DONE:
        set_busy(0);
        finished(wp);
        return 0;
    case WM_FOUND: {
        int n = ngames, sel = selected();
        add_game((WCHAR *)lp);
        free((void *)lp);
        if (ngames > n) {
            fill_list(sel);
            if (plain_header) normal_header();
        }
        return 0;
    }
    case WM_SEARCH_DONE:
        searching = 0;
        if (plain_header) normal_header();
        return 0;
    case WM_CLOSE:
        if (!busy) DestroyWindow(h);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(exit_code);
        return 0;
    }
    return DefWindowProcW(h, m, wp, lp);
}

static int run_window(int op, int show)
{
    INITCOMMONCONTROLSEX icc = { sizeof icc, ICC_LISTVIEW_CLASSES | ICC_PROGRESS_CLASS | ICC_STANDARD_CLASSES };
    InitCommonControlsEx(&icc);
    HDC dc = GetDC(NULL);
    dpi = GetDeviceCaps(dc, LOGPIXELSY);
    ReleaseDC(NULL, dc);
    WNDCLASSW wc = { 0, wndproc, 0, 0, GetModuleHandleW(NULL), NULL, LoadCursorW(NULL, (LPCWSTR)IDC_ARROW), (HBRUSH)(COLOR_WINDOW + 1), NULL, L"TazHDInstall" };
    wc.hIcon = LoadIconW(NULL, (LPCWSTR)IDI_APPLICATION);
    RegisterClassW(&wc);
    DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    RECT r = { 0, 0, S(640), S(380) };
    AdjustWindowRect(&r, style, FALSE);
    CreateWindowExW(0, wc.lpszClassName, L"Taz: Wanted HD Setup", style, CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left, r.bottom - r.top, NULL, NULL, wc.hInstance, NULL);
    ShowWindow(wnd, show);
    UpdateWindow(wnd);
    if (op) {
        fill_list(0);
        start_task(op, 0);
    } else {
        detect();
        fill_list(-1);
        searching = 1;
        CloseHandle(CreateThread(NULL, 0, search, NULL, 0, NULL));
        normal_header();
    }
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0)
        if (!IsDialogMessageW(wnd, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    return (int)msg.wParam;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    int argc, op = 0, quiet = 0, list_only = 0, all = 0;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    const WCHAR *dir = NULL;
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    wine = GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "wine_get_version") != NULL;
    GetModuleFileNameW(NULL, src, PATH);
    *wcsrchr(src, '\\') = 0;
    src_ok = open_pack();

    for (int i = 1; i < argc; i++) {
        if (!wcscmp(argv[i], L"--list")) list_only = 1;
        else if (!wcscmp(argv[i], L"--all")) all = 1;
        else if (!wcscmp(argv[i], L"--quiet")) quiet = 1;
        else if (!wcscmp(argv[i], L"--install") && i + 1 < argc) op = OP_INSTALL, dir = argv[++i];
        else if (!wcscmp(argv[i], L"--uninstall") && i + 1 < argc) op = OP_UNINSTALL, dir = argv[++i];
    }
    if (list_only) {
        WCHAR st[128];
        detect();
        if (all) search(NULL);
        for (int i = 0; i < ngames; i++) {
            update_game(&games[i]);
            status_text(&games[i], st);
            say(L"%ls\t%ls", games[i].dir, st);
        }
        say(L"%d found%ls", ngames, src_ok ? L"" : L"; no mod files packed in this exe");
        return 0;
    }
    if (op) {
        if (op == OP_UNINSTALL && quiet) detect(); // keeps the Wine override while another copy has the mod
        int i = add_game(dir);
        if (i < 0 || (op == OP_INSTALL && !src_ok)) {
            const WCHAR *m = i < 0 ? L"There is no taz.exe in that folder." : DAMAGED;
            if (quiet) say(L"%ls", m);
            else MessageBoxW(NULL, m, L"Taz: Wanted HD", MB_ICONERROR);
            return 1;
        }
        update_game(&games[i]);
        if (quiet) {
            DWORD res = op == OP_INSTALL ? do_install(games[i].dir, task.msg) : do_uninstall(games[i].dir, task.msg);
            say(L"%ls", res == NEED_ADMIN ? L"Needs administrator permission." : res ? task.msg : L"Done.");
            if (!res && wine) say(L"Wine override d3d8 = %ls", op == OP_INSTALL ? L"native,builtin (set)" : L"removed unless another copy has the mod");
            return res;
        }
        task_mode = 1;
    }
    return run_window(op, show);
}
