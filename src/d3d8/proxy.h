#pragma once
#include <windows.h>
#include <d3d8.h>

void log_line(const char *fmt, ...);
void patch(void **slot, void *hook, void **orig);
void textures_install(IDirect3DDevice8 *dev);
void textures_report(void);
