#pragma once
#include <windows.h>

int png_write(const char *path, UINT w, UINT h, const BYTE *bgra);
BYTE *png_read(const char *path, UINT *w, UINT *h); // caller frees; NULL if missing or unreadable
