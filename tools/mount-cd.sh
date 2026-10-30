#!/bin/sh
# Mounts the Taz disc image (the game checks for its CD) and points the prefix's D: at it.
# Paths come from the environment or dev.env. Works as a Lutris pre-launch command.
root=$(dirname "$0")/..
[ -f "$root/dev.env" ] && . "$root/dev.env"
: "${ISO:?set ISO in dev.env}" "${WINEPREFIX:?set WINEPREFIX in dev.env}"

dev=$(losetup -j "$ISO" -O NAME -n | head -n1)
[ -n "$dev" ] || dev=$(udisksctl loop-setup -r --no-user-interaction -f "$ISO" | sed -n 's/.* as \(\/dev\/loop[0-9]*\)\..*/\1/p')
[ -n "$dev" ] || { echo "could not attach $ISO" >&2; exit 1; }

mnt=$(findmnt -n -o TARGET "$dev")
[ -n "$mnt" ] || mnt=$(udisksctl mount --no-user-interaction -b "$dev" | sed -n 's/.* at \(.*\)$/\1/p')
[ -n "$mnt" ] || { echo "could not mount $dev" >&2; exit 1; }

ln -sfn "$mnt" "$WINEPREFIX/dosdevices/d:"
ln -sfn "$dev" "$WINEPREFIX/dosdevices/d::"
echo "D: -> $mnt ($dev)"
