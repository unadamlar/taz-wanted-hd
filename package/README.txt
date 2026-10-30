Taz: Wanted HD  (version VERSION)
=================================

A free fan remaster for the PC version of Taz: Wanted (2002). It is a mod: you need the game
itself, installed. Nothing from the original game is included except upscaled textures and videos.

What it does
- Runs at your desktop resolution, in widescreen, without the 2002 launcher.
- Replaces the game's textures, fonts and loading screens with 4x upscaled versions.
- Plays the intro videos upscaled and full screen.
- Optional faster menus, frame cap and vsync, set from an in-game panel (press F1).

Install (Windows 10 or 11)
1. Copy everything in this folder into the game folder, next to taz.exe.
2. The game checks for its CD. Insert the disc, or double-click the disc image (.iso) to mount it.
3. Run taz.exe.

Install (Linux / Steam Deck)
Same files, plus tell Wine to use the mod's d3d8.dll:
- Steam (taz.exe added as a non-Steam game with Proton): set the launch options to
    WINEDLLOVERRIDES="d3d8=n,b" %command%
- Lutris: Configure > Runner options > DLL overrides, add d3d8 with the value n,b
The disc or disc image must be visible to Wine as a CD drive.

Settings
Press F1 in game. Resolution, widescreen, HD textures and vsync apply after restarting the game;
menu speed and the frame cap apply at once. They are saved in taz-hd.ini in the game folder.
Leave the game's own "Widescreen" option off: the mod already uses your screen's real shape.
F12 saves a screenshot to taz-hd\shots.

Supported game version
The retail PC release, taz.exe dated 2002-07-22
(SHA-256 357536c0e3a94525cb3960e1aac1733ee5dd1ed743f5a1114ffca988cbe84cfe).
With another taz.exe you get a one-time warning; HD textures and videos still work.

Uninstall
Delete d3d8.dll, taz-hd.ini and the taz-hd folder from the game folder.

Problems
taz-hd.log in the game folder records what the mod did, including crashes. Attach it when reporting.

Credits
Upscaling: Real-ESRGAN (Xintao Wang et al., BSD 3-Clause).
Taz: Wanted is (c) Warner Bros. Entertainment, developed by Blitz Games and published by
Infogrames. This is an unofficial fan project, not affiliated with or endorsed by them.
The mod's own code is under the MIT license (LICENSE.txt).
