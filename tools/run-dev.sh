#!/bin/sh
# Launches the dev install the way Lutris does. Unpatched, taz.exe on its own starts
# TazLauncher.exe, whose Play button runs "taz.exe Launched", so we pass that directly.
# --headless runs it inside an invisible gamescope screen, which keeps working while the desktop is
# locked; send input to gamescope's X display.
GAME=$HOME/Games/taz-wanted
export WINEPREFIX=$HOME/.local/share/wineprefixes/tazwanted
export PROTONPATH=$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-11-x86_64
export GAMEID=umu-default WINEDLLOVERRIDES="d3d8=n,b"

"$(dirname "$0")/mount-cd.sh" || exit 1
cd "$GAME" || exit 1
if [ "$1" = --headless ]; then
    exec gamescope --backend headless -W 2880 -H 1800 -w 2880 -h 1800 -- umu-run "$GAME/taz.exe" Launched
fi
exec umu-run "$GAME/taz.exe" Launched
