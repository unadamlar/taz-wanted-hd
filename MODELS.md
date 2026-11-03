# Character models checklist

Which characters have an upgraded model, and what is left. Every character already gets
smoothing and clean cartoon shadows automatically (`smooth.c`); this list is for the extra work
that needs a model file: new hands, springs (bouncing ears, fur, tail) and anything hand-made.

## How to do one

1. Record it in game (muted, save restored afterwards):
   - Taz costume: `FRAMES=60 qa/costume.sh qa/cos <scene>` jumps to the level, puts the
     level's costume on and records 60 frames into `qa/cos/scene<scene>/`.
   - Other characters: they have to be on screen. `qa/survey.sh` jumps to levels and records one
     frame; the zoo hub, ghost and construction levels caught a few. Characters off screen at a
     level's start need a scripted walk or a cutscene.
2. Build (about a minute each): `tools/models.sh <name> <dir>/capture-001.bin <dir>/capture-020.bin <dir>/capture-040.bin <dir>/capture-060.bin`
   writes `extracted/meshes/out/<fingerprint>.bin`. The hands and springs steps find Taz's bones
   by shape; other characters need their own scripts. `NOHANDS=1` keeps a costume's own hands
   (claws, gloves).
3. Copy the .bin to the game's `taz-hd/meshes/` and look at it in game: hands in claw and fist
   poses, no gaps or spikes, springs not swinging the wrong parts.
4. Tick it off here. `tools/package.sh` ships everything in `extracted/meshes/out`.

## Taz

| Model | Scene | Captured | Built | Checked in game | Notes |
|---|---|---|---|---|---|
| Taz (normal) | all | yes | yes | yes | hands, shading, ear rims, 4 springs |
| Surfer | 6 aqua | yes | yes | yes | belly crease line sometimes draws dashed |
| Snowboarder (goggles) | 4 icedome | yes | yes | partly | camera starts behind a wall; look at it in play |
| Skater (cap, board) | 5 safari | yes | yes | yes | |
| Jersey 23 and cap | 9 deptstr | yes | yes | yes | |
| SWAT | 11 contruct | yes | yes | yes | |
| Werewolf | 14 ghost | yes | yes | yes | built with NOHANDS=1 to keep its claws |
| Cowboy | 16 grandc | yes | yes | yes | |
| Tarzan | 18 tazhub | yes | yes | partly | only partly in shot |
| Ninja | 10 museum | yes | yes | partly | jumping straight to the museum drops Taz into an endless fall; the costume shows for ~24 frames before each respawn takes it off, which was enough to record and to see it drawn |
| Explorer hat and whip | 15 goldmine | n/a | n/a | yes | the goldmine costume only adds a hat and whip; Taz's own model (and file) is used |

### Bonus levels

Each bonus level carries its own copy of its costume, so each is a separate model (and file). Taz already
wears it when the level starts; press Jump to close the level's intro page.

| Model | Scene | Captured | Built | Checked in game | Notes |
|---|---|---|---|---|---|
| Ninja on the floor polisher | 21 vrmuseum | yes | yes | yes | |
| Cowboy | 22 vrgrandc | yes | yes | yes | |
| Jersey 23 and cap | 23 vrdeptstr | yes | yes | yes | |
| Surfer | 24 deaqua | yes | yes | yes | |
| SWAT | 25 deconstruct | | | | jumping there drops Taz into an endless fall, like the museum |
| Werewolf | 26 detasmania | yes | yes | yes | NOHANDS=1 |
| Snowboarder | 27 rcicedome | yes | yes | yes | |
| Explorer | 28 rcgoldmine | n/a | n/a | | hat and whip on Taz's own model; jumping there also falls |
| Skater | 29 rcsafari | yes | yes | yes | |

## Other characters

None have model files yet; all get the automatic smoothing and shading.

| Character | Where seen | Captured | Notes |
|---|---|---|---|
| Tweety | zoo hub | one frame | 885 points |
| Zookeeper | ghost level | one frame | 1,394 points |
| She-Devil, Sylvester, Yosemite Sam, Elmer, Daffy, Wile E. Coyote, Gossamer, bosses | not yet | | each has its own data file in Paks/ |

## Known limits

- Jumping straight into scene 2 (playpen) crashes the game, with or without the mod's models.
- A model file only matches the exact model it was made from; a character whose model the game
  swaps (costumes, cutscene versions) needs one file per version.
