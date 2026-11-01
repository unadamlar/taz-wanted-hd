#!/bin/sh
# Launches the dev install with umu-run, mounting the disc image first. Paths come from dev.env.
# --headless runs it inside an invisible gamescope screen, which keeps working while the desktop is
# locked; send input to gamescope's X display.
root=$(dirname "$0")/..
[ -f "$root/dev.env" ] && . "$root/dev.env"
: "${TAZ_GAME:?set TAZ_GAME in dev.env}" "${WINEPREFIX:?set WINEPREFIX in dev.env}"
export WINEPREFIX PROTONPATH GAMEID=umu-default WINEDLLOVERRIDES="d3d8=n,b"

"$root/tools/mount-cd.sh" || exit 1
cd "$TAZ_GAME" || exit 1
if [ "$1" = --headless ]; then
    # Test runs play into a silent sink.
    pactl list short sinks | grep -q taz-hd-silent ||
        pactl load-module module-null-sink sink_name=taz-hd-silent >/dev/null
    export PULSE_SINK=taz-hd-silent
    exec gamescope --backend headless -W 2880 -H 1800 -w 2880 -h 1800 -- umu-run "$TAZ_GAME/taz.exe" Launched
fi
exec umu-run "$TAZ_GAME/taz.exe" Launched
