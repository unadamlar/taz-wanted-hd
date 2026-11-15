# Character models checklist

Which characters have an upgraded model, and what is left. Every character already gets
smoothing and clean cartoon shadows automatically (`smooth.c`); this list is for the extra work
that needs a model file: new hands, springs (bouncing ears, fur, tail), a dense smooth surface
(`tools/subdivide.py`, so outlines stay round up close) and anything hand-made.

## How to do one

1. Record it in game (muted, save restored afterwards):
   - Taz costume: `FRAMES=60 qa/costume.sh qa/cos <scene>` jumps to the level, puts the
     level's costume on and records 60 frames into `qa/cos/scene<scene>/`. `COS=1 qa/playrec.sh <out> <scene>...`
     does the same while running and turning, for poses and a look in play.
   - Other characters: they have to be on screen. `PRESS=space qa/levelrec.sh <out> <scene>...` jumps to each
     level, closes a boss or bonus level's intro page and records a few frames every few seconds. Boss
     levels put their boss and helpers on screen (zooboss: Gossamer, the elephant, Yosemite Sam watching).
2. Build (about a minute each): `tools/models.sh <name> <dir>/capture-001.bin <dir>/capture-020.bin <dir>/capture-040.bin <dir>/capture-060.bin`
   writes `extracted/meshes/out/<fingerprint>.bin`. Without captures (`tools/models.sh <name>`) it rebuilds
   from the `springs.blend` already in `extracted/meshes/<name>`, which is how all model files were made
   dense on 2026-11-04. `extracted/textures` must be there (subdivide reads which faces are painted black).
   All captures must come from one run. The hands and
   springs steps find Taz's bones by shape. `NOHANDS=1` keeps a costume's own hands (claws, gloves).
   Other characters: `BUFFER=<fingerprint> NOHANDS=1 PERBONE=1` with `SPRINGS=tools/springs/<name>.json`
   (springs placed by hand in the .blend's coordinates, see `tools/springs.py`) or `NOSPRINGS=1` for only the
   dense surface. `PERBONE` makes the dense surface follow the bones exactly as the original model does (skin a bone
   slides far, like brows, otherwise bunches up). The game lists model files once at startup: restart it after copying one in. If meshview warns that bones stand for
   several, the frames didn't move every bone and the model would bend wrongly in other poses: record more
   varied frames.
3. Copy the .bin to the game's `taz-hd/meshes/` and look at it in game: hands in claw and fist
   poses, no gaps or spikes, springs not swinging the wrong parts.
4. Tick it off here. `tools/package.sh` ships everything in `extracted/meshes/out`.

## Taz

| Model | Scene | Captured | Built | Checked in game | Notes |
|---|---|---|---|---|---|
| Taz (normal) | all | yes | yes | yes | hands, shading, ear rims, 4 springs |
| Surfer | 6 aqua | yes | yes | yes | belly crease line sometimes draws dashed |
| Snowboarder (goggles) | 4 icedome | yes | yes | yes | camera starts behind a wall; checked running about |
| Skater (cap, board) | 5 safari | yes | yes | yes | |
| Jersey 23 and cap | 9 deptstr | yes | yes | yes | |
| SWAT | 11 contruct | yes | yes | yes | |
| Werewolf | 14 ghost | yes | yes | yes | built with NOHANDS=1 to keep its claws |
| Cowboy | 16 grandc | yes | yes | yes | |
| Tarzan | 18 tazhub | yes | yes | yes | checked running about |
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

All get the automatic smoothing and shading. A model file only pays off where it adds something visible;
most of these characters already animate their floppy parts with their own bones.

| Character | Where seen in play | Fingerprint | Model file | Notes |
|---|---|---|---|---|
| Elephant | 7 zooboss (Elephant Pong) | 1d44544a0d4eebd7 | yes | ears swing (2 springs); checked drawn whole close up, the swing itself not caught on screen. The ears are thin plates whose rim points serve front and back; `tools/normals.py` (PLATES) gives each side its own normals, so they no longer shade dark or show black outline wedges |
| Yosemite Sam | 7 zooboss (in the stands), 17 westboss | dba92834ff14d74c | no | never close in play: about 40 pixels wide at 2880x1800 in westboss (top edge of the screen) and as far off in the zooboss stands. A dense file was built and drew whole in westboss with no crash (2026-11-15) but shows nothing at that size, so it was dropped |
| Gossamer | 7 zooboss (goalkeeper, close to camera) | 01036cdeaa4e7c03 | yes | dense surface, no springs, built with `PERBONE=1`. Checked in his goal celebrations (2026-11-15): facing the camera and covering his face, smooth outline, clean brows, no black shards (`qa/models-check/pairs/gossamer-fixed.jpg`; `gossamer-face-auto-old-fixed.jpg` shows automatic smoothing, the first dense build and this one). The first build had sawtooth brows: the game drew him with its one-bone shader, which ignores a dense model's blended weights. `qa/gossamer.sh <out>` takes the shots. |
| Tweety | zoo hub (flies around the Tutorial 1 book) | 9ccd72fd73041cc4 | yes | dense surface only. All 12 bones moved in 28 frames. Checked from behind at about 250 pixels tall (2026-11-15): drawn whole, head round, head feathers there. Not seen from the front in game, and not compared with the automatic smoothing in the same view Rebuilt with `PERBONE=1` after the checks described here; the rebuilt file loads but has not been looked at in game. |
| Zookeeper | 14 ghost (recorded), 4 icedome (seen) | adbdee12889a7268 | yes | dense surface only. Checked once in game, catching Taz in the ghost level (2026-11-15): drawn whole with his net, smooth outline, no gaps. Face hidden under the cap in that shot; not compared with the automatic smoothing in the same view Rebuilt with `PERBONE=1` after the checks described here; the rebuilt file loads but has not been looked at in game. |
| Taz in cutscenes | every cutscene | one per cutscene | no | each cutscene (cs02-cs20 `*_tazdevil.obe`, hub `taz.obe`) carries its own Taz, so his new hands and springs are missing there; the Taz scripts should work on them once recorded |
| She-Devil, Daffy, Elmer, Wile E. Coyote, Sylvester, Mecha-Tweety | cutscenes only (She-Devil also the 2-player levels) | one per cutscene | no | cutscene versions are separate models (`cs05_shedevil.obe` ...); a scene jump skips intros once seen (save flag at 0x6c9860 + slot*0x13d4 + scene*0xa8, bit 1) |

Seen while recording, not built: the ghost level has two more characters (a95143be45888734, 1,652 vertices,
and 996c0e186a82c7d8, 596); the zooboss lose screen draws its caged character (8a4245570492cc82, 3,180
vertices) and three sharks.

## Known limits

- Jumping straight into scene 2 (playpen) crashes the game, with or without the mod's models; 19 (tazboss1)
  crashed once while loading (only tried with the mod). 12 (cityboss) crashes right after loading
  (taz.exe +0x1140a6, also with every mod feature off) unless jumped to from 8 (cityhub), the way play
  reaches it.
- Jumping straight into 10 museum, 25 deconstruct or 28 rcgoldmine drops Taz into an endless fall.
- A model file only matches the exact model it was made from; a character whose model the game
  swaps (costumes, cutscene versions) needs one file per version.
