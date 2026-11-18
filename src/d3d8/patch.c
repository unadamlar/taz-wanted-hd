// Changing code and call targets in taz.exe, Direct3D's method tables and the exe's imports. Code
// patches name the bytes they expect and leave anything else alone, so another build of the game
// stays untouched.
#include <string.h>
#include "proxy.h"

// A method table entry (or any pointer slot): stores hook, hands back what was there.
void patch(void **slot, void *hook, void **orig)
{
    DWORD old;
    VirtualProtect(slot, sizeof *slot, PAGE_EXECUTE_READWRITE, &old);
    if (orig) *orig = *slot;
    *slot = hook;
    VirtualProtect(slot, sizeof *slot, old, &old);
}

// Writes n bytes at at, if what is there is expect (NULL: whatever is there). Returns 1 when written.
int write_code(BYTE *at, const BYTE *expect, const void *bytes, SIZE_T n)
{
    DWORD old;
    if ((expect && memcmp(at, expect, n)) || !VirtualProtect(at, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy(at, bytes, n);
    VirtualProtect(at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), at, n);
    return 1;
}

// Replaces the n bytes of instructions at at (expect) with a call (op 0xe8) or jump (0xe9) to to.
int write_jump(BYTE *at, const BYTE *expect, SIZE_T n, BYTE op, void *to)
{
    BYTE code[16];
    if (n < 5 || n > sizeof code) return 0;
    memset(code, 0x90, sizeof code);
    code[0] = op;
    *(INT32 *)(code + 1) = (INT32)((BYTE *)to - (at + 5));
    return write_code(at, expect, code, n);
}

// Points the call at at, which must be a call to expect, at to instead.
int redirect_call(BYTE *at, void *expect, void *to)
{
    if (at[0] != 0xe8 || at + 5 + *(INT32 *)(at + 1) != expect) return 0;
    INT32 rel = (INT32)((BYTE *)to - (at + 5));
    return write_code(at + 1, NULL, &rel, 4);
}

// Points one import of the exe at hook; returns the previous target.
void *patch_import(const char *dll, const char *func, void *hook)
{
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (IMAGE_IMPORT_DESCRIPTOR *d = (void *)(base + dir.VirtualAddress); dir.VirtualAddress && d->Name; d++) {
        if (_stricmp((char *)base + d->Name, dll)) continue;
        IMAGE_THUNK_DATA *names = (void *)(base + (d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk));
        IMAGE_THUNK_DATA *slots = (void *)(base + d->FirstThunk);
        for (; names->u1.AddressOfData; names++, slots++) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            if (strcmp((char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name, func)) continue;
            void *orig;
            patch((void **)&slots->u1.Function, hook, &orig);
            return orig;
        }
    }
    return NULL;
}
