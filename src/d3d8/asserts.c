// Diagnostics for silent quits. The game's assert handler (0x48eb10) prints to a debug log the
// release never opens, then exits; we log the failure first. Scene loads (FUN_004b8de0) start with
// the CD check (FUN_004a1de0), which quits when the disc is missing; we log both.
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

__attribute__((used)) static void __cdecl log_scene_request(int scene)
{
    log_line("loading scene %d", scene);
}

__attribute__((used)) static void __cdecl log_cd_result(int missing)
{
    if (missing) log_line("CD check failed: the game will quit");
}

// Replaces "call 0x4a1de0" at 0x4b8de4; the scene argument sits 0x60 above our return address.
__attribute__((naked)) static void cd_check(void)
{
    __asm__("pushl 0x60(%esp)\n\t"
            "call _log_scene_request\n\t"
            "addl $4, %esp\n\t"
            "movl $0x4a1de0, %eax\n\t"
            "call *%eax\n\t"
            "pushl 0x6f4af4\n\t"
            "call _log_cd_result\n\t"
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

static void WINAPI hook_ExitProcess(UINT code)
{
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

    static const BYTE cd_call[] = { 0xe8, 0xf7, 0x8f, 0xfe, 0xff }; // call 0x4a1de0 at 0x4b8de4
    if (!memcmp((BYTE *)0x4b8de4, cd_call, sizeof cd_call)) {
        BYTE call[5] = { 0xe8 };
        *(INT32 *)(call + 1) = (INT32)((BYTE *)cd_check - ((BYTE *)0x4b8de4 + 5));
        DWORD old;
        VirtualProtect((BYTE *)0x4b8de4, 5, PAGE_EXECUTE_READWRITE, &old);
        memcpy((BYTE *)0x4b8de4, call, 5);
        VirtualProtect((BYTE *)0x4b8de4, 5, old, &old);
    }

    static const BYTE orig[] = { 0xa1, 0xf0, 0x4a, 0x6f, 0x00 }; // mov eax, [0x6f4af0]
    if (memcmp(ASSERT_HANDLER, orig, sizeof orig)) return;
    BYTE jmp[5] = { 0xe9 };
    *(INT32 *)(jmp + 1) = (INT32)((BYTE *)on_assert - (ASSERT_HANDLER + 5));
    DWORD old;
    VirtualProtect(ASSERT_HANDLER, sizeof jmp, PAGE_EXECUTE_READWRITE, &old);
    memcpy(ASSERT_HANDLER, jmp, sizeof jmp);
    VirtualProtect(ASSERT_HANDLER, sizeof jmp, old, &old);
    FlushInstructionCache(GetCurrentProcess(), ASSERT_HANDLER, sizeof jmp);
}
