Taz: Wanted HD  (version VERSION)
=================================

A free fan remaster for the PC version of Taz: Wanted (2002). It is a mod: you need the game
itself, installed. Nothing from the original game is included except upscaled textures and videos.

What it does
- Runs at your desktop resolution and your screen's shape (16:9, 16:10, ultrawide), without the 2002
  launcher.
- Replaces the game's textures, fonts and loading screens with 4x upscaled versions.
- Plays the intro videos upscaled and full screen.
- Faster menu text (lands in about a quarter of the time; the camera and characters keep their pace).
  Menu text speed, frame cap and vsync are set from an in-game panel (press F1).
- Quicksave (F5) and quickload (F9) anywhere in a level. The quicksave lasts until you leave the
  level or quit the game; the game's own save slots work as before.

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
Press F1 in game. Changes apply at once (a resolution or vsync change takes about a second) and
are saved in taz-hd.ini in the game folder. Changing the resolution or vsync discards the quicksave.
The game's own "Widescreen" option does nothing now: the picture always matches your screen.
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
