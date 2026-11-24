// Diagnostics for silent quits. The game's assert handler (0x48eb10) prints to a debug log the
// release never opens, then exits; we log the failure first. The save written on each scene change
// (FUN_004b8de0) calls FUN_004a1de0 first, which is a no-op unless the label check below says the
// game is missing something; wrapping it logs the scene request.
#include <string.h>
#include "proxy.h"

#define ASSERT_HANDLER ((BYTE *)0x48eb10)

static void __cdecl on_assert(const char *file, int line, const char *msg)
{
    log_line("game assert: %s line %d: %s", file ? file : "?", line, msg ? msg : "");
    if (*(int *)0x6f4af0) return; // already exiting
    *(int *)0x6f4af0 = 1;
    ((void(__cdecl *)(int))0x5dbfd4)(1); // the game's own exit()
}

int scene_requests;

__attribute__((used)) static void __cdecl log_scene_request(int scene)
{
    scene_requests++;
    log_line("saving on the way to scene %d", scene);
}

// Replaces "call 0x4a1de0" at 0x4b8de4; the scene argument sits 0x60 above our return address.
// FUN_004a1de0 does nothing when the label check reports the game's media present, so log and return.
__attribute__((naked)) static void cd_check(void)
{
    __asm__("pushl 0x60(%esp)\n\t"
            "call _log_scene_request\n\t"
            "addl $4, %esp\n\t"
            "ret");
}

static void (WINAPI *real_PostQuitMessage)(int);
static void (WINAPI *real_ExitProcess)(UINT);

static void WINAPI hook_PostQuitMessage(int code)
{
    log_line("game quits: PostQuitMessage(%d) from %p", code, __builtin_return_address(0));
    real_PostQuitMessage(code);
}

int game_quit;

static void WINAPI hook_ExitProcess(UINT code)
{
    game_quit = 1;
    log_line("game quits: ExitProcess(%u) from %p", code, __builtin_return_address(0));
    real_ExitProcess(code);
}

// Logs crashes (the game's runtime turns them into a silent ExitProcess with the exception code).
static LONG WINAPI on_exception(EXCEPTION_POINTERS *e)
{
    static int logged;
    DWORD code = e->ExceptionRecord->ExceptionCode;
    if (code != EXCEPTION_ACCESS_VIOLATION || logged++ > 4) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT *c = e->ContextRecord;
    log_line("crash: access violation at %p (%s %p), eax=%08lx ebx=%08lx ecx=%08lx edx=%08lx esi=%08lx edi=%08lx esp=%08lx",
             e->ExceptionRecord->ExceptionAddress, e->ExceptionRecord->ExceptionInformation[0] ? "writing" : "reading",
             (void *)e->ExceptionRecord->ExceptionInformation[1], c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Esp);
    HMODULE m = NULL;
    char name[MAX_PATH] = "?";
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)e->ExceptionRecord->ExceptionAddress, &m))
        GetModuleFileNameA(m, name, sizeof name);
    log_line("crash: in %s +%#lx", name, (DWORD)((BYTE *)e->ExceptionRecord->ExceptionAddress - (BYTE *)m));
    DWORD *obj = (DWORD *)c->Ecx;
    if (!IsBadReadPtr(obj, 32))
        log_line("crash: ecx object %08lx %08lx %08lx %08lx %08lx %08lx %08lx %08lx", obj[0], obj[1], obj[2], obj[3], obj[4],
                 obj[5], obj[6], obj[7]);
    DWORD *stack = (DWORD *)c->Esp;
    for (int i = 0; i < 24; i += 8)
        log_line("crash: stack %08lx %08lx %08lx %08lx %08lx %08lx %08lx %08lx", stack[i], stack[i + 1], stack[i + 2],
                 stack[i + 3], stack[i + 4], stack[i + 5], stack[i + 6], stack[i + 7]);
    textures_dump_recent();
    return EXCEPTION_CONTINUE_SEARCH;
}

void asserts_patch(void)
{
    AddVectoredExceptionHandler(1, on_exception);
    real_PostQuitMessage = patch_import("USER32.dll", "PostQuitMessage", hook_PostQuitMessage);
    real_ExitProcess = patch_import("KERNEL32.dll", "ExitProcess", hook_ExitProcess);

    redirect_call((BYTE *)0x4b8de4, (void *)0x4a1de0, cd_check);

    // FUN_004a1f10 (asked by FUN_004a1de0 on the way into a scene) looks for the game's volume label
    // and reports it missing otherwise; we answer yes, so the game never stops there.
    static const BYTE label_check[] = { 0x81, 0xec, 0x38, 0x01, 0x00, 0x00 }; // sub esp, 0x138
    static const BYTE label_ok[] = { 0xb8, 0x01, 0x00, 0x00, 0x00, 0xc3 };    // mov eax, 1; ret
    write_code((BYTE *)0x4a1f10, label_check, label_ok, sizeof label_ok);

    static const BYTE orig[] = { 0xa1, 0xf0, 0x4a, 0x6f, 0x00 }; // mov eax, [0x6f4af0]
    write_jump(ASSERT_HANDLER, orig, sizeof orig, 0xe9, on_assert);
}
