#pragma once
#include <windows.h>

int png_write(const char *path, UINT w, UINT h, const BYTE *bgra);
BYTE *image_read(const char *path, UINT *w, UINT *h); // PNG or JPEG; caller frees; NULL if missing or unreadable
