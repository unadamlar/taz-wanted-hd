// Compiles one HLSL entry point with d3dcompiler_47 (run under Wine) and prints the bytecode as a C array.
// usage: hlslc <file> <entry> <profile> <array name> [DEFINE=VALUE...]
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { const char *name, *def; } macro;
typedef struct { void **vt; } blob;
typedef HRESULT (WINAPI *compile_fn)(const void *, SIZE_T, const char *, const macro *, void *, const char *, const char *, UINT, UINT, blob **, blob **);
#define BLOB_PTR(b) ((void *(WINAPI *)(blob *))(b)->vt[3])(b)
#define BLOB_SIZE(b) ((SIZE_T (WINAPI *)(blob *))(b)->vt[4])(b)

int main(int argc, char **argv)
{
    if (argc < 5) return fprintf(stderr, "usage: hlslc file entry profile name [DEF=V...]\n"), 2;
    HMODULE m = LoadLibraryA("d3dcompiler_47.dll");
    compile_fn compile = m ? (compile_fn)GetProcAddress(m, "D3DCompile") : NULL;
    if (!compile) return fprintf(stderr, "no d3dcompiler_47\n"), 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return fprintf(stderr, "cannot read %s\n", argv[1]), 2;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *src = malloc(n);
    fread(src, 1, n, f);
    fclose(f);
    macro defs[16] = { { 0 } };
    int nd = 0;
    for (int i = 5; i < argc && nd < 15; i++, nd++) {
        char *eq = strchr(argv[i], '=');
        if (eq) *eq = 0;
        defs[nd].name = argv[i], defs[nd].def = eq ? eq + 1 : "1";
    }
    blob *code = NULL, *err = NULL;
    HRESULT hr = compile(src, n, argv[1], defs, NULL, argv[2], argv[3], 0, 0, &code, &err);
    if (err) fprintf(stderr, "%s: %.*s\n", argv[4], (int)BLOB_SIZE(err), (char *)BLOB_PTR(err));
    if (FAILED(hr) || !code) return fprintf(stderr, "%s failed: %08lx\n", argv[4], hr), 1;
    const DWORD *p = BLOB_PTR(code);
    SIZE_T words = BLOB_SIZE(code) / 4;
    printf("static const DWORD %s[%u] = {", argv[4], (unsigned)words);
    for (SIZE_T i = 0; i < words; i++) printf("%s0x%08lx,", i % 10 ? " " : "\n    ", p[i]);
    printf("\n};\n");
    return 0;
}
