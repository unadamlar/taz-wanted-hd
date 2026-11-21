Taz: Wanted HD  (version VERSION)
=================================

A free fan remaster for the PC version of Taz: Wanted (2002). It is a mod: you need the game
itself, installed. Nothing from the original game is included except upscaled textures and videos.

What it does
- Runs at your desktop resolution and your screen's shape (16:9, 16:10, ultrawide), without the 2002
  launcher.
- Replaces the game's textures, fonts and loading screens with 4x upscaled versions.
- Smooths jagged edges with anti-aliasing (multisampling).
- Plays the intro videos upscaled and full screen.
- Faster menu text (lands in about a quarter of the time; the camera and characters keep their pace).
- Its settings live in the game's own menus (Game Options, and Options in the pause menu), with
  keyboard or controller.
- Rounder, smoother characters with cleaner cartoon shading; Taz gets new hands and his ears, fur
  and tail bounce as he moves.
- Taz Style: try newer looks for Taz (Detailed Cartoon, Soft Shading, Fur Detail) or keep the
  current one.
- Sees further: scenery and objects in the distance stay visible instead of popping in (Draw
  Distance: Original, Far or Very Far).
- F11 switches between the original graphics and the new ones, for comparing.
- Quicksave (F5) and quickload (F9) anywhere in a level. The quicksave lasts until you leave the
  level or quit the game; the game's own save slots work as before.

Install (Windows 10 or 11)
The easy way is the one-file installer from the same download page (taz-wanted-hd-VERSION-setup.exe):
run it and it finds your game and copies the mod in. From this zip, by hand:
1. Copy d3d8.dll and the taz-hd folder into the game folder, next to taz.exe.
2. Run taz.exe.

Install (Linux / Steam Deck)
Windows games run on Linux through Wine or Proton (also inside Steam, Lutris, Heroic, Bottles).
Any of them works.

1. Unzip the whole download anywhere.
2. Run install.sh: open a terminal in the unzipped folder and type  ./install.sh
   It finds your Taz: Wanted folder, copies the mod into it and, when the game lives in a Wine
   prefix it can see, tells Wine to use the mod. If it can't, it prints the one setting to add in
   your launcher (below).
3. Start the game as usual.

By hand instead:
1. Copy d3d8.dll and the taz-hd folder into the game folder, next to taz.exe.

2. Tell Wine/Proton to use the mod's d3d8.dll. Wine has its own d3d8.dll and uses it unless told
   otherwise. The setting is a "DLL override": name d3d8, value n,b (native, then builtin).
   Set it wherever you start the game:
   - Steam, Steam Deck (taz.exe added with "Add a Non-Steam Game", Proton chosen under
     Properties > Compatibility): Properties > General > Launch Options:
         WINEDLLOVERRIDES="d3d8=n,b" %command%
   - Lutris: right-click the game > Configure > Runner options > DLL overrides > Add,
     key d3d8, value n,b
   - Heroic, Bottles or anything else that lets you set environment variables: add
     WINEDLLOVERRIDES with the value d3d8=n,b
   - Plain Wine: run winecfg in the game's prefix > Libraries, type d3d8, Add, Edit, choose
     "Native then Builtin". Or start the game with: WINEDLLOVERRIDES="d3d8=n,b" wine taz.exe

   To check: the game should start straight at your screen's resolution, and Game Options should
   have a Graphics page. If the old 2002 launcher window opens instead, the override isn't set.

Settings
Game Options (main menu) has Graphics (a page with Resolution, HD Textures, Vsync, Anti-Aliasing
(Off, 2x, 4x or 8x; 4x by default), Smooth Characters, Taz Style, Draw Distance and Frame Cap),
Controls (a page with Controls, Mouse Look and the keys) and Menu Text Speed. Options in the pause
menu has HD Textures, Taz Style, Draw Distance, Controls and Mouse Look. Press Select to change one. Changes apply at once
(a resolution, vsync or anti-aliasing change takes about a second) and are saved in taz-hd.ini in
the game folder. Changing the resolution, vsync or anti-aliasing discards the quicksave.
The game's Widescreen option is gone: the picture always matches your screen's shape.
F12 saves a screenshot to taz-hd\shots.

Controls
WASD moves (arrows still work) and the mouse turns and tilts the camera while you play, running,
spinning or standing, and stays pointed where you leave it; walls move it closer instead of turning it. Mouse
Look sets its speed (Off turns it off). Space jumps, Shift or right click spins, left click bites, middle click
looks around, Q rants, Ctrl tiptoes and Tab opens the map (in levels;
the zoo hub has none). Original keys the layout
doesn't use (C, F, R, X, V, E, T, arrows) still work. Set Controls to Classic for the original keys
only (D rants, Space opens the map, no mouse look).

Gamepad
An Xbox-style gamepad (or anything Steam Input shows the game as one) works without setting it up
in the 2002 config tool, and can be plugged in while the game runs. Left stick moves, right stick turns
and tilts the camera, A jumps, B spins, Y bites, X rants, LB and RB swing the camera, either
trigger tiptoes, pressing the right stick looks around, Start pauses, Back opens the map. In menus
A selects and B goes back. Other pads, and pads you already set up in the config tool, work as
before. Player two still needs the config tool.

On a laptop touchpad the camera won't turn while you hold W, A, S or D if the system ignores the
touchpad while typing. Turn that off: Linux, the touchpad's "Disable while typing" setting (KDE,
GNOME); Windows, Touchpad sensitivity "Most sensitive". A USB mouse is not affected.

To change keys, open Game Options > Controls, pick an action and press the new key or mouse button
(Esc keeps the old one); Reset to Defaults puts them all back. They can also be set in taz-hd.ini
under [taz-hd], one or two inputs each, for example:
    key_jump=Space
    key_spin=LShift MouseRight
Actions: key_forward, key_back, key_left, key_right (one key each), key_jump, key_spin, key_bite,
key_rant, key_tiptoe, key_look, key_map. Names: letters, digits, F1-F4, F6-F8, F10, Space, Tab,
Enter, Backspace, LShift, RShift, LCtrl, RCtrl, LAlt, RAlt, CapsLock, Up, Down, Left, Right, Home,
End, PgUp, PgDn, Insert, Delete, Num0-Num9, NumPlus, NumMinus, NumEnter, Minus, Equals, LBracket,
RBracket, Semicolon, Apostrophe, Grave, Backslash, Comma, Period, Slash, MouseLeft, MouseRight,
MouseMiddle. A key you give an action stops doing its old job.

Supported game version
The retail PC release, taz.exe dated 2002-07-22
(SHA-256 357536c0e3a94525cb3960e1aac1733ee5dd1ed743f5a1114ffca988cbe84cfe).
With another taz.exe you get a one-time warning; HD textures and videos still work.

Uninstall
Windows installer: run it again and click Uninstall. Linux: ./install.sh --uninstall. Or delete
d3d8.dll, taz-hd.ini and the taz-hd folder from the game folder.

Problems
taz-hd.log in the game folder records what the mod did, including crashes. Attach it when reporting.

Credits
Upscaling: Real-ESRGAN (Xintao Wang et al., BSD 3-Clause).
Taz: Wanted is (c) Warner Bros. Entertainment, developed by Blitz Games and published by
Infogrames. This is an unofficial fan project, not affiliated with or endorsed by them.
The mod's own code is under the MIT license (LICENSE.txt).
