#!/usr/bin/env bash
# Installs or removes the Taz: Wanted HD mod. Run it from the unzipped mod folder:
#   ./install.sh [--uninstall] [/path/to/game/folder]
set -u

here=$(dirname "$(readlink -f "$0")")
data=${XDG_DATA_HOME:-$HOME/.local/share}
conf=${XDG_CONFIG_HOME:-$HOME/.config}
override='"d3d8"="native,builtin"'
hits=    # game folders found, one per line
lutris=  # "game folder<TAB>prefix" lines from Lutris configs
report=

# ---- talking to the player: terminal, or zenity/kdialog when started from a file manager

ui=${TAZ_UI:-}
if [ -z "$ui" ]; then
    if [ -t 0 ] && [ -t 1 ]; then
        ui='tty'
    else
        ui='none'
        case ${XDG_CURRENT_DESKTOP:-} in *KDE*) tools="kdialog zenity" ;; *) tools="zenity kdialog" ;; esac
        for t in $tools; do command -v "$t" >/dev/null && { ui=$t; break; }; done
    fi
fi
if [ "$ui" = none ]; then
    echo "Please run this from a terminal: open one in this folder and type  ./install.sh" >&2
    exit 1
fi

info() {
    case $ui in
        tty) printf '%s\n' "$1" ;;
        zenity) zenity --info --no-markup --title "Taz: Wanted HD" --text "$1" 2>/dev/null ;;
        kdialog) kdialog --title "Taz: Wanted HD" --msgbox "$1" ;;
    esac
}
say() { report+="$*"$'\n'; [ "$ui" != tty ] || printf '%s\n' "$*"; return 0; }
finish() {
    [ "$ui" = tty ] && { read -r -p "Press Enter to close. " _; return 0; }
    info "$report"
}
die() { say "$@"; finish; exit 1; }

confirm() {
    case $ui in
        tty) local a; read -r -p "$1 [y/N] " a; [ "${a:0:1}" = y ] || [ "${a:0:1}" = Y ] ;;
        zenity) zenity --question --no-markup --text "$1" 2>/dev/null ;;
        kdialog) kdialog --yesno "$1" ;;
    esac
}

progress_start() {
    case $ui in
        zenity) exec 3> >(zenity --progress --auto-close --no-cancel --title "Taz: Wanted HD" --text "Copying files, this takes a minute or two..." 2>/dev/null) ;;
        kdialog) kdialog --passivepopup "Copying files, this takes a minute or two..." 10 >/dev/null 2>&1 & ;;
    esac
}
progress() { # percent
    case $ui in
        tty) printf '\r  Copying files... %d%%' "$1" ;;
        zenity) echo "$1" >&3 ;;
    esac
}
progress_end() {
    case $ui in
        tty) echo ;;
        zenity) echo 100 >&3; exec 3>&- ;;
    esac
}

# ---- finding the game

has_exe() { [ -n "$(find -H "$1" -maxdepth 1 -iname taz.exe -type f 2>/dev/null)" ]; }

add_hit() {
    local d
    d=$(readlink -f "$1")
    case $'\n'$hits in *$'\n'"$d"$'\n'*) ;; *) hits+="$d"$'\n' ;; esac
}

scan() { # depth, start folders...: add every folder holding a taz.exe
    local depth=$1 d; shift
    while IFS= read -r d; do add_hit "$d"; done < <(find -H "$@" -maxdepth "$depth" -iname taz.exe -type f -printf '%h\n' 2>/dev/null)
}

scan_prefix() { # a Wine prefix, or a Proton one with the real prefix in pfx/
    local q c
    for q in "$1" "$1/pfx"; do
        c=$q/drive_c
        [ -d "$c" ] && scan 4 "$c"/Program\ Files* "$c/Games"
    done
}

yml_get() { sed -n "s/^ *$1: *//p" "$2" | head -1 | sed "s/^['\"]//; s/['\"] *\$//"; }

scan_lutris() {
    local f exe pre d
    for f in "$conf"/lutris/games/*.yml "$HOME"/.var/app/net.lutris.Lutris/config/lutris/games/*.yml; do
        [ -f "$f" ] || continue
        exe=$(yml_get exe "$f"); pre=$(yml_get prefix "$f")
        [ -n "$exe" ] || continue
        d=$(dirname "$exe")
        { [ -d "$d" ] && has_exe "$d"; } || continue
        add_hit "$d"
        [ -n "$pre" ] && lutris+="$(readlink -f "$d")"$'\t'"$(readlink -f "$pre")"$'\n'
    done
}

scan_all() {
    local p lib m
    scan_lutris
    for p in "$HOME/.wine" "$data"/wineprefixes/* "$data"/bottles/bottles/* "$HOME"/.var/app/com.usebottles.bottles/data/bottles/bottles/* \
             "$HOME"/Games/* "$HOME"/Games/Heroic/Prefixes/default/*; do
        [ -d "$p" ] && scan_prefix "$p"
    done
    for p in "$data/Steam" "$HOME/.steam/steam" "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" "$HOME/.var/app/com.valvesoftware.Steam/data/Steam"; do
        [ -d "$p/steamapps" ] || continue
        while IFS= read -r lib; do
            for q in "$lib"/steamapps/compatdata/*; do [ -d "$q" ] && scan_prefix "$q"; done
        done < <(echo "$p"; sed -n 's/^[[:space:]]*"path"[[:space:]]*"\(.*\)"/\1/p' "$p/steamapps/libraryfolders.vdf" 2>/dev/null)
    done
    scan 3 "$HOME/Games" "$HOME/games" "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" "$data/games"
    scan 2 "$HOME"
    for m in ${TAZ_MEDIA:-/run/media /media /mnt}; do [ -d "$m" ] && scan 5 "$m"; done
}

prefix_of() { # the Wine prefix a game folder lives in, if known
    case $1 in */drive_c/*) echo "${1%%/drive_c/*}"; return ;; esac
    printf '%s' "$lutris" | awk -F'\t' -v d="$1" '$1 == d { print $2; exit }'
}

ours() { grep -aq 'taz-hd.log' "$1"; }

status_of() { if [ -d "$1/taz-hd" ] && [ -f "$1/d3d8.dll" ] && ours "$1/d3d8.dll"; then echo "mod installed"; else echo "mod not installed"; fi; }

ask_folder() {
    local p
    info "I could not find your game by myself. Pick the folder that contains taz.exe (Steam: right-click the game > Manage > Browse local files; Lutris: right-click it > Browse files)."
    while :; do
        case $ui in
            tty) read -r -p "Folder (you can drag it into this window): " p || exit 1 ;;
            zenity) p=$(zenity --file-selection --directory --title "Choose the folder that contains taz.exe" 2>/dev/null) || exit 1 ;;
            kdialog) p=$(kdialog --getexistingdirectory "$HOME") || exit 1 ;;
        esac
        p=${p#\'}; p=${p%\'}; p=${p/#\~/$HOME}
        [ -d "$p" ] && has_exe "$p" && { game=$(readlink -f "$p"); return; }
        say "There is no taz.exe in that folder."
    done
}

choose_game() {
    local dirs=() d i n=
    while IFS= read -r d; do [ -n "$d" ] && dirs+=("$d"); done <<<"$hits"
    [ ${#dirs[@]} -gt 0 ] || { ask_folder; return; }
    while :; do
        case $ui in
            tty)
                echo "Found Taz: Wanted here:"
                for i in "${!dirs[@]}"; do printf '  %2d) %s   [%s]\n' $((i + 1)) "${dirs[i]}" "$(status_of "${dirs[i]}")"; done
                echo "  0) Another folder"
                read -r -p "Which one? [1] " n || exit 1
                [ -n "$n" ] || n=1 ;;
            *)
                local args=()
                for i in "${!dirs[@]}"; do args+=("$((i + 1))" "${dirs[i]}" "$(status_of "${dirs[i]}")"); done
                args+=(0 "Another folder..." "")
                if [ "$ui" = zenity ]; then
                    n=$(zenity --list --title "Taz: Wanted HD" --text "Where is your Taz: Wanted?" --column "" --column "Folder" --column "" "${args[@]}" 2>/dev/null) || exit 1
                else
                    local m=()
                    for ((i = 0; i < ${#args[@]}; i += 3)); do m+=("${args[i]}" "${args[i + 1]}  [${args[i + 2]}]"); done
                    n=$(kdialog --title "Taz: Wanted HD" --menu "Where is your Taz: Wanted?" "${m[@]}") || exit 1
                fi ;;
        esac
        if [ "$n" = 0 ]; then ask_folder; return; fi
        if [[ $n =~ ^[0-9]+$ ]] && [ "$n" -le ${#dirs[@]} ]; then game=${dirs[n - 1]}; return; fi
    done
}

# ---- Wine setting (user.reg)

wine_running() { # is a wineserver running for this prefix? (its environment names the prefix)
    local d c e p
    for d in /proc/[0-9]*; do
        read -r c <"$d/comm" 2>/dev/null && [ "$c" = wineserver ] || continue
        e=$(tr '\0' '\n' <"$d/environ" 2>/dev/null)
        p=$(sed -n 's/^WINEPREFIX=//p' <<<"$e")
        [ -n "$p" ] || p=$(sed -n 's/^HOME=\(.*\)/\1\/.wine/p' <<<"$e")
        [ "$(readlink -f "$p")" = "$1" ] && return 0
    done
    return 1
}

# Rewrites the d3d8 line under [Software\\Wine\\DllOverrides] to $2 (empty: remove it); creates the section if needed.
# With $3 = get, only prints the current d3d8 line.
edit_reg() { # user.reg, line, [get]
    local ft
    ft=$(printf '%x' $(( ($(date +%s) + 11644473600) * 10000000 )))
    awk -v line="$2" -v get="${3:-}" -v now="$(date +%s)" -v ft="$ft" '
        function flush() { if (insec && !done && line != "") { print line; done = 1 } }
        substr($0, 1, 1) == "[" { flush(); insec = index(tolower($0), "[software\\\\wine\\\\dlloverrides]") == 1; seen = seen || insec }
        insec && $0 == "" { flush() }
        insec && index(tolower($0), "\"d3d8\"=") == 1 { if (get) { print; exit } flush(); next }
        get { next }
        { print }
        END {
            if (get) exit
            flush()
            if (!seen && line != "") { print ""; print "[Software\\\\Wine\\\\DllOverrides] " now; print "#time=" ft; print line }
        }' "$1"
}

set_override() { # prefix, line ("" removes); keeps one backup of the original user.reg
    local reg=$1/user.reg tmp
    tmp=$(mktemp "$reg.XXXXXX") || return 1
    chmod --reference="$reg" "$tmp"
    if edit_reg "$reg" "$2" >"$tmp" && [ -s "$tmp" ]; then
        if cmp -s "$reg" "$tmp"; then rm -f "$tmp"; return 0; fi
        [ -e "$reg.taz-hd.bak" ] || cp -p "$reg" "$reg.taz-hd.bak"
        mv "$tmp" "$reg"
    else
        rm -f "$tmp"; return 1
    fi
}

launcher_help() {
    say "One more step: Wine needs to be told to use the mod's d3d8.dll (a \"DLL override\": name d3d8, value n,b). Set it where you start the game:"
    say "  Steam / Steam Deck: game Properties > General > Launch Options:  WINEDLLOVERRIDES=\"d3d8=n,b\" %command%"
    say "  Lutris: right-click the game > Configure > Runner options > DLL overrides > Add, key d3d8, value n,b"
    say "  Heroic or Bottles: add the environment variable WINEDLLOVERRIDES with the value d3d8=n,b"
    say "  Plain Wine: WINEDLLOVERRIDES=\"d3d8=n,b\" wine taz.exe"
    say "If the old 2002 launcher window opens when you start the game, this step is missing."
}

# ---- install / uninstall

refuse_links() {
    local f
    for f in d3d8.dll taz-hd; do
        [ -L "$1/$f" ] && die "$f in $1 is a link to $(readlink "$1/$f") (a developer setup), so changing it would change that file too. I did nothing in this folder."
    done
}

install_to() {
    local g=$1 dll=$1/d3d8.dll total n=0 st prefix ending="Done. Start"
    [ -f "$here/d3d8.dll" ] && [ -d "$here/taz-hd" ] || die "d3d8.dll and taz-hd are missing next to install.sh. Unzip the whole download first, then run install.sh from the unzipped folder."
    refuse_links "$g"
    [ -w "$g" ] || die "I am not allowed to write to $g."
    if [ -e "$dll" ] && ! ours "$dll"; then
        [ -e "$dll.bak" ] && die "$g already has a d3d8.dll that is not from this mod, and a d3d8.dll.bak. I changed nothing; move d3d8.dll.bak away and run me again."
        mv "$dll" "$dll.bak" && say "Your own d3d8.dll was kept as d3d8.dll.bak."
    fi
    cp --reflink=auto "$here/d3d8.dll" "$dll" || die "Could not copy d3d8.dll into $g."
    mkdir -p "$g/taz-hd" || die "Could not create $g/taz-hd."
    total=$(find "$here/taz-hd" | wc -l)
    progress_start
    cp -rv --reflink=auto "$here/taz-hd/." "$g/taz-hd/" | while IFS= read -r _; do
        n=$((n + 1)); [ $((n % 50)) -eq 0 ] && progress $((n * 100 / total))
    done
    st=${PIPESTATUS[0]}
    progress_end
    [ "$st" -eq 0 ] || die "Copying stopped early (is the disk full? the mod needs about 700 MB). Free some space and run me again."
    say "Copied the mod into $g."

    prefix=$(prefix_of "$g")
    if [ -z "$prefix" ] || [ ! -f "$prefix/user.reg" ]; then
        launcher_help; ending="Almost done: finish the step above, then start"
    elif wine_running "$prefix"; then
        say "The game or its launcher is still running for this Wine prefix, so I left its settings alone. Close everything, run me again, or:"
        launcher_help; ending="Almost done: finish the step above, then start"
    elif set_override "$prefix" "$override"; then
        say "Told Wine to use the mod (d3d8 = native,builtin in $prefix; a copy of the original is user.reg.taz-hd.bak)."
    else
        launcher_help; ending="Almost done: finish the step above, then start"
    fi
    say ""
    say "$ending the game as usual: you should land directly at your screen resolution and see a Graphics page under Game Options."
}

uninstall_from() {
    local g=$1 dll=$1/d3d8.dll prefix old
    refuse_links "$g"
    confirm "Remove the HD mod from $g? Your game saves stay; the mod's settings file (taz-hd.ini) is removed too." || die "Nothing was changed."
    if [ ! -e "$dll" ] || ours "$dll"; then
        rm -f "$dll"
        [ -e "$dll.bak" ] && mv "$dll.bak" "$dll" && say "Your own d3d8.dll is back."
    else
        say "d3d8.dll in this folder is not from this mod, so I left it."
    fi
    rm -rf "$g/taz-hd"; rm -f "$g/taz-hd.ini"
    say "Removed the mod's files from $g."

    prefix=$(prefix_of "$g")
    if [ -n "$prefix" ] && [ -f "$prefix/user.reg.taz-hd.bak" ]; then
        old=$(edit_reg "$prefix/user.reg.taz-hd.bak" "" get)
        if wine_running "$prefix"; then
            say "Wine is still running for this prefix, so I left its d3d8 setting in place. Close everything and run me again to remove it."
        elif set_override "$prefix" "$old"; then
            rm -f "$prefix/user.reg.taz-hd.bak"; say "Removed the Wine setting I added."
        fi
    else
        say "If you set a d3d8 override yourself (launch option or runner setting), you can remove it now."
    fi
}

# ---- main

mode=install
game=
for a in "$@"; do
    case $a in
        --uninstall) mode=uninstall ;;
        -h|--help) echo "Usage: $0 [--uninstall] [/path/to/game/folder]"; exit 0 ;;
        *) game=$a ;;
    esac
done

if [ -n "$game" ]; then
    has_exe "$game" || die "There is no taz.exe in $game."
    game=$(readlink -f "$game")
    scan_lutris
else
    scan_all
    choose_game
fi

if [ "$mode" = uninstall ]; then uninstall_from "$game"; else install_to "$game"; fi
finish
