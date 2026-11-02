// Our settings as rows in the game's own option menus: on the frontend Game Options page in place of the
// game's Widescreen row (it does nothing now), and in the pause menu's options above Exit Game. Each row
// reads "Label: value"; Select changes it, and the line under the rows describes it. Rows are the game's
// text items; their text comes from its string table, so for a moment we point one entry at ours.
#include <stdio.h>
#include <string.h>
#include "proxy.h"

typedef void *(__attribute__((thiscall)) *add_text_fn)(void *page, int string_id, int new_row);
typedef void *(__attribute__((thiscall)) *add_item_fn)(void *page, void *item, int new_row);
#define ADD_TEXT ((add_text_fn)0x544640) // new text item from a string number, added to page
#define ADD_ITEM ((add_item_fn)0x5445d0)
#define SET_TEXT ((void *(*)(void *, unsigned, ...))0x540350) // item text from a string number (printf-style)
#define STRINGS (*(BYTE **)0x6c8c08)                    // +0x20 entries of 16 bytes, first the wide text
#define LENT_STRING 0x58e                                 // "Widescreen": lends its entry while we set a text
#define WIDESCREEN_ROW ((BYTE *)0x525156)                 // Game Options: call ADD_TEXT(page, 0x58e, 1)
#define EXIT_ROW ((BYTE *)0x4c5bb7)                       // pause options: call ADD_ITEM(page, exit_game, 1)
#define FRONT_BLANK ((BYTE *)0x5254f2)                    // Game Options: ADD_ITEM(info "NULL" page, its text, 1)
#define PAUSE_VIBRATION ((BYTE *)0x4c5cdc)                // pause: ADD_TEXT(info "VIBRATION" page, 0x90, 1), unused on PC
#define FRONT_POPUP (*(void **)0x739b74)                  // a yes/no or slider popup is open
#define PAUSE_POPUP (*(void **)0x702310)
#define FRONT_INFO (*(BYTE **)(*(BYTE **)0x739b50 + 0x30)) // the line under the rows: a book of named pages
#define PAUSE_INFO (*(BYTE **)(*(BYTE **)0x70230c + 0x20))
typedef void *(__attribute__((thiscall)) *add_page_fn)(void *book, const char *name, int, int, int);
typedef void (__attribute__((thiscall)) *show_page_fn)(void *book, const char *name, int);
#define ADD_PAGE ((add_page_fn)0x548ed0)
#define SHOW_PAGE ((show_page_fn)0x549370)
#define BUILD_OPTIONS ((void (*)(BYTE *))0x524db0) // builds the frontend's Game Options pages
#define BUILD_OPTIONS_CALL ((BYTE *)0x521249)
#define FRONTEND ((BYTE *)0x739b08)
#define FRONT_BOOK (*(BYTE **)(FRONTEND + 0x68))   // its pages; +0x148 the current one's node, page at +0x20
#define OPTIONS_PAGE (*(const char **)0x650258)    // "options"
#define OPTIONS_STATE (*(int **)0x739b50)          // 7 or 8: the Game Options update leaves Back alone
#define KEYS_PAGE "TAZHD_KEYS"
#define SELECT_ITEM ((void *(__attribute__((thiscall)) *)(void *page, void *item))0x5449c0)
// A page title as Game Options builds its own (FUN_00524db0 at 0x524e70..0x524f36).
#define GAME_ALLOC ((BYTE *(*)(int size, const char *file, int line, int flags))0x559610)
#define TEXT_BOX ((void (__attribute__((thiscall)) *)(void *))0x4500a0)
#define COLOUR ((void (__attribute__((thiscall)) *)(void *, int, int, int, int))0x41f5c0)
#define TITLE_VTABLE ((void *)0x5f749c)
#define TEXT_INIT ((void (__attribute__((thiscall)) *)(void *, int string_id))0x53f690)
#define TEXT_STYLE ((void *(__attribute__((thiscall)) *)(void *, void *style))0x540610)
#define TITLE_STYLE ((void *)0x73e550)
#define TEXT_FLAGS ((void (__attribute__((thiscall)) *)(void *, int, int))0x541cf0)

struct menu {
    void *items[16]; // per setting; NULL where the page has no row for it
    void (*game_callback)(int *event);
    void *about;            // a text item on an info page the game never shows otherwise
    const char *about_page; // that page's name
};
static struct menu front = { .about_page = "NULL" }, pause_menu = { .about_page = "VIBRATION" };

static void set_text(void *item, const char *s)
{
    wchar_t text[64];
    for (int i = 0; i < 64; i++)
        if (!(text[i] = (BYTE)s[i])) break;
    text[63] = 0;
    void **entry = (void **)(*(BYTE **)(STRINGS + 0x20) + LENT_STRING * 16);
    void *lent = *entry;
    *entry = text;
    SET_TEXT(item, LENT_STRING);
    *entry = lent;
}

static void show_value(void *item, int setting)
{
    char s[64];
    if (setting_is_link(setting)) snprintf(s, sizeof s, "%s", setting_label(setting));
    else snprintf(s, sizeof s, "%s: %s", setting_label(setting), setting_shown(setting));
    set_text(item, s);
}

static int row_of(struct menu *m, void *item)
{
    for (int i = 0; i < setting_count(); i++)
        if (item && m->items[i] == item) return i;
    return -1;
}

// Page callbacks get {item, event}: 0 highlighted, 1 left, 2 Select pressed, 3 back.
static void handle(struct menu *m, int *event, int popup_open)
{
    int i = row_of(m, (void *)event[0]);
    if (i < 0 || popup_open) {
        if (m->game_callback) m->game_callback(event);
        return;
    }
    if (event[1] == 2 && setting_is_link(i)) {
        if (m == &front) menu_open_keys();
    } else if (event[1] == 2) {
        setting_step(i, 1);
        show_value(m->items[i], i);
    } else if (event[1] == 0 && m->about) {
        BYTE *info = m == &front ? FRONT_INFO : PAUSE_INFO;
        set_text(m->about, setting_about(i));
        if (info) ((void (__attribute__((thiscall)) *)(void *, const char *, int))0x549370)(info, m->about_page, 0);
    }
}

static void front_callback(int *event) { handle(&front, event, FRONT_POPUP != NULL); }
static void pause_callback(int *event) { handle(&pause_menu, event, PAUSE_POPUP != NULL); }

static void add_rows(struct menu *m, BYTE *page, void (*callback)(int *))
{
    settings_refresh();
    for (int i = 0; i < setting_count(); i++) {
        m->items[i] = NULL;
        if (!setting_on_page(i, m == &pause_menu)) continue;
        BYTE *item = ADD_TEXT(page, LENT_STRING, 1);
        *(DWORD *)(item + 0x108) &= ~2u; // as the game does for its rows
        snprintf((char *)item + 4, 32, "TAZHD_%d", i);
        show_value(item, i);
        m->items[i] = item;
    }
    BYTE *owner = page; // Game Options' rows sit on an inner page; its parent gets their events
    while (owner && !*(void **)(owner + 0x110)) owner = *(BYTE **)(owner + 0x34);
    if (!owner) {
        log_line("menu: no page callback found, our rows can't change values");
        return;
    }
    log_line("menu: rows on page %p, events via %p (callback %p)", page, owner, *(void **)(owner + 0x110));
    if (*(void **)(owner + 0x110) != (void *)callback) m->game_callback = *(void **)(owner + 0x110);
    *(void **)(owner + 0x110) = callback;
}

static BYTE unused_item[0x400]; // the game names and flags the Widescreen item it gets back; nothing else

static void *__attribute__((thiscall)) options_rows(void *page, int string_id, int new_row)
{
    add_rows(&front, page, front_callback);
    return unused_item;
}

static void *__attribute__((thiscall)) pause_rows(void *page, void *exit_game, int new_row)
{
    add_rows(&pause_menu, page, pause_callback);
    return ADD_ITEM(page, exit_game, new_row);
}

static void *__attribute__((thiscall)) front_blank(void *page, void *text, int new_row)
{
    front.about = text;
    return ADD_ITEM(page, text, new_row);
}

static void *__attribute__((thiscall)) pause_vibration(void *page, int string_id, int new_row)
{
    return pause_menu.about = ADD_TEXT(page, string_id, new_row);
}

// The Controls page: Controls and Mouse Look rows, then one row per action ("Jump: Space"; Select,
// then press the new key) and Reset to Defaults. It is a page of the frontend book, shown from Game
// Options' Controls row while the Game Options update keeps running; Back returns to Game Options.
static const char *KEYS_SETTINGS[] = { "controls", "mouse_sensitivity" };
#define KEYS_FIRST (int)(sizeof KEYS_SETTINGS / sizeof *KEYS_SETTINGS) // rows before the actions
static struct { void *page, *rows[20], *reset; int count, open, closing, saved_state; } keys;

static void keys_show(void)
{
    char s[64];
    for (int r = 0; r < KEYS_FIRST; r++) show_value(keys.rows[r], setting_find(KEYS_SETTINGS[r]));
    for (int r = KEYS_FIRST; r < keys.count; r++) {
        controls_row_text(r - KEYS_FIRST, s, sizeof s);
        set_text(keys.rows[r], s);
    }
}

static int keys_current(void);

static void keys_close(void)
{
    if (keys_current()) SHOW_PAGE(FRONT_BOOK, OPTIONS_PAGE, 0);
    if (OPTIONS_STATE) *OPTIONS_STATE = keys.saved_state;
    keys.open = keys.closing = 0;
}

static void keys_callback(int *event)
{
    if (controls_capturing()) return;
    if (event[1] == 3) keys.closing = 1; // after this frame's Game Options update, which would see Back too
    if (event[1] != 2) return;
    if ((void *)event[0] == keys.reset) controls_reset_keys();
    for (int r = 0; r < keys.count; r++)
        if ((void *)event[0] == keys.rows[r]) {
            if (r < KEYS_FIRST) setting_step(setting_find(KEYS_SETTINGS[r]), 1);
            else controls_capture(r - KEYS_FIRST, keys_show);
        }
    keys_show();
}

static void __cdecl build_options(BYTE *frontend)
{
    BUILD_OPTIONS(frontend);
    BYTE *page = ADD_PAGE(*(BYTE **)(frontend + 0x68), KEYS_PAGE, 0, 0, 0);
    if (!page) return;
    *(DWORD *)(page + 0x124) |= 1;           // as Game Options sets its page up (FUN_00547220, FUN_005472b0)
    *(DWORD *)(page + 0x124) = (*(DWORD *)(page + 0x124) & ~0x3f00u) | 0x800;
    BYTE *title = GAME_ALLOC(0x38c, "taz-hd", 0, 0x1001);
    if (title) {
        TEXT_BOX(title);
        for (int i = 0; i < 2; i++) COLOUR(title + 0x380 + i * 4, 0xff, 0, 0xff, 0xff);
        *(void **)title = TITLE_VTABLE;
        TEXT_INIT(title, LENT_STRING);
        set_text(title, "Controls");
        ADD_ITEM(page, title, 0);
        TEXT_STYLE(title, TITLE_STYLE);
        ((void *(__attribute__((thiscall)) *)(void *, int))(*(void ***)title)[0x6c / 4])(title, 0x80);
        TEXT_FLAGS(title, 0, 0);
    }
    keys.count = KEYS_FIRST + controls_row_count();
    for (int r = 0; r <= keys.count && r < 20; r++) {
        BYTE *item = ADD_TEXT(page, LENT_STRING, 1);
        *(DWORD *)(item + 0x108) &= ~2u;
        snprintf((char *)item + 4, 32, "TAZHD_K%d", r);
        if (r < keys.count) keys.rows[r] = item;
        else set_text(keys.reset = item, "Reset to Defaults");
    }
    keys_show();
    *(void **)(page + 0x110) = keys_callback;
    keys.page = page;
    log_line("menu: keys page %p", page);
}

void menu_open_keys(void)
{
    if (keys.open || !OPTIONS_STATE) return;
    keys.saved_state = *OPTIONS_STATE;
    *OPTIONS_STATE = 7;
    SHOW_PAGE(FRONT_BOOK, KEYS_PAGE, 0);
    SELECT_ITEM(keys.page, keys.rows[0]);
    keys.open = 1;
    keys_show();
}

static int keys_current(void)
{
    BYTE *node = FRONT_BOOK ? *(BYTE **)(FRONT_BOOK + 0x148) : NULL, *page = node ? *(BYTE **)(node + 0x20) : NULL;
    return page && !strcmp((char *)page + 4, KEYS_PAGE);
}

// Per frame, after the game's update: Back was pressed, or something else changed the page (the idle demo).
void menu_frame(void)
{
    if (keys.open && (keys.closing || !keys_current())) keys_close();
}

int redirect_call(BYTE *at, void *expect, void *to)
{
    if (at[0] != 0xe8 || at + 5 + *(INT32 *)(at + 1) != expect) return 0;
    DWORD old;
    VirtualProtect(at, 5, PAGE_EXECUTE_READWRITE, &old);
    *(INT32 *)(at + 1) = (INT32)((BYTE *)to - (at + 5));
    VirtualProtect(at, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, 5);
    return 1;
}

void menu_patch(void)
{
    if (!redirect_call(WIDESCREEN_ROW, (void *)ADD_TEXT, options_rows) || !redirect_call(EXIT_ROW, (void *)ADD_ITEM, pause_rows))
        log_line("menu: unexpected code, our settings are only in taz-hd.ini");
    else if (!redirect_call(FRONT_BLANK, (void *)ADD_ITEM, front_blank) || !redirect_call(PAUSE_VIBRATION, (void *)ADD_TEXT, pause_vibration))
        log_line("menu: unexpected code, no descriptions under our rows");
    if (!redirect_call(BUILD_OPTIONS_CALL, (void *)BUILD_OPTIONS, build_options))
        log_line("menu: unexpected code, no Keys page");
}
