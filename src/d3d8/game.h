// Things in the 2002 retail taz.exe that more than one file uses. They mean nothing in another build:
// code that runs every frame checks settings.exe_known before touching them.
#pragma once
#define SCENE (*(const BYTE *)0x704cf0)          // 0, 1: menus; from 2: in play
#define PLAYER (*(BYTE **)0x6c8c80)              // player one's actor
#define GAME ((void *)0x6c8c18)                  // the game object its scene change takes
#define GAME_WINDOW (*(HWND *)0x753724)
#define SCREEN_W (*(UINT *)0x6c6b78)
#define SCREEN_H (*(UINT *)0x6c6b7c)
#define FPS (*(const float *)0x642cdc)
#define CREATE_TARGET ((BYTE *)0x56c500)         // FUN_0056c500(w, h, colour bits, depth bits, flags) -> render target
