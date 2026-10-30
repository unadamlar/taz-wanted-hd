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

struct menu {
    void *items[8];
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
    snprintf(s, sizeof s, "%s: %s", setting_label(setting), setting_shown(setting));
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
    if (event[1] == 2) {
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

static int redirect_call(BYTE *at, void *expect, void *to)
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
}
