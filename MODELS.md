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
| Surfer | 6 aqua | yes | yes | yes | in the HD look the outline shows through along the fold where the belly meets the shorts, as a broken line (seen 2026-11-27; the Remaster look draws no outline). Not the paint: the black swatch rows sit at brow height |
| Snowboarder (goggles) | 4 icedome | yes | yes | yes | camera starts behind a wall; checked running about |
| Skater (cap, board) | 5 safari | yes | yes | yes | |
| Jersey 23 and cap | 9 deptstr | yes | yes | yes | |
| SWAT | 11 contruct | yes | yes | yes | |
| Werewolf | 14 ghost | yes | yes | yes | built with NOHANDS=1 to keep its claws |
| Cowboy | 16 grandc | yes | yes | yes | |
| Tarzan | 18 tazhub | yes | yes | yes | checked running about |
| Ninja | 10 museum | yes | yes | yes | checked from the front in the museum hall (2026-11-27): face, teeth, hands and belt clean. Built from frames recorded during the old endless fall (see Test jumps below) |
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
| SWAT | 25 deconstruct | yes | yes | yes | 9643dd672d591eaa; checked at the start (2026-11-27): backpack, gloves with the new fingers and face whole |
| Werewolf | 26 detasmania | yes | yes | yes | NOHANDS=1 |
| Snowboarder | 27 rcicedome | yes | yes | yes | |
| Explorer | 28 rcgoldmine | n/a | n/a | | hat and whip on Taz's own model; jumping there also falls |
| Skater | 29 rcsafari | yes | yes | yes | |

### Cutscenes

Every cutscene pak carries its own re-export of Taz (3,010-3,254 vertices; the same 1,039-point body except the
first zoo scene's second copy), so each needs its own file. The buffer fingerprint can be read straight from the pak:
the 52-byte vertex block sits whole in the `.obe` (`tools/pak.py unpack`, then FNV-1a over that run). The `taz.obe`
copies (hub endings, level endings, hub "done" scenes) draw most of Taz untextured, coloured by vertex colour; the
build carries vertex colours through to the file. Their textured parts (eyes, inner ears, toes, mouth) use a doubled
texture blend and the untextured body a plain one, so the DLL gives each group of a replacement its own batch's blend;
before that those parts came out half bright, grey. Checked against `hd_models=0` in the construction "done" scene
(2026-11-27): same colours, rounder fingers.

Recording (`qa/cutcap.sh <out> <seconds> <trigger file> <text>` writes the trigger, then one capture a second):
hub intros `scene "<n> intro"`; boss intros play on a plain jump; boss endings and level endings on an empty
`complete`; a hub ending by marking its three levels won, reloading the hub and winning it (`qa/hubwin.sh`, which also
records the boss intro after); hub "done" scenes play when Return closes a level's results page (`qa/cutdone.sh`);
the first zoo scene after a new game in an empty slot. `qa/capfp.py --sum <dir>` lists the buffers seen and
`qa/cutbuild.sh <name> <fingerprint> <dir>` builds from up to seven frames spread over the scene. Files are about
9 MB each.

| Cutscene | Fingerprint | Built | Checked in game |
|---|---|---|---|
| main menu Taz (frontend) | bb8d46fefde74e65 | yes | loads |
| first zoo scene (cs02) | 233e5ac80281f380 | yes | |
| first zoo scene, second copy | be7c13679bcc13c0 | yes, NOHANDS=1 (an extra hand bone) | |
| zoo hub intro (cs03) | 3d1122e6904ff360 | yes | yes: new hands, smooth outline |
| city hub intro (cs07) | 8a2365474c2658fa | yes | |
| west hub intro (cs11) | 8b62364a368ad815 | yes | |
| city boss intro and ending, Taz hub intro (cs09, cs10, cs15) | dccd2445320dff50 | yes | |
| zoo boss intro, westboss ending (cs05, cs14) | 272f4054586c218f | yes | loads, drawn |
| zoo boss ending (cs06) | 4015a2204f32820d | yes | loads, drawn |
| westboss intro (cs13) | 9cadecf172c55d33 | yes | |
| Taz boss 1 intro, ending (cs16, cs17) | c1521e05e8a2a154, 5c1dabe616c7f502 | yes | |
| Taz boss 2 intro, ending (cs18, cs19) | 399cb658aefc58f4, fe37f65685c69c86 | yes | |
| end of game (cs20) | 88dc76337d1df517 | yes | |
| zoo, city, west hub endings | 489e6c57a184a1c4, 07b6647e0087cd0f, 6b832bbc88ffb8f1 | yes | |
| level endings: icedome, safari, aqua | 34bf6e1c2d2f027c, 7acf43e33bb20625, e104b2437b3d6f31 | yes | icedome: drawn (shot before the blend fix below, not since) |
| level endings: deptstr, museum (two copies), contruct | 3dcf74b568e3d9dd, ef75d4b63b1763d1, cc94cb8cd5619e6f, c06fbec7cc2d5b24 | yes | contruct: loads, drawn |
| level endings: ghost, goldmine, grandc | b3a2e9336af3c43e, e4d12b6c9e636f90, 0c20f4ae41cac4be | yes | |
| zoo hub "done": icedome, safari, aqua | ba48771e6282c4cf, 65a30a0f07d3d211, d22f2d9403fe37f4 | yes | |
| city hub "done": deptstr, museum, contruct | 974855e996eba92b, 24294615a0371159, 5f929bdd1c191dd7 | yes | contruct: yes, same colours as the original |
| west hub "done": ghost and goldmine (one file), grandc | a6a50830afbd15fa, 33eea9f78a8d4736 | yes | |
| story intro (maingameintro) | e4bdb8d62945c2de | no | a jump to its scene 35 goes straight on to the zoo; not recorded |
| Taz in the dinghy (zoo hub "aqua done") | cbf1d1be77f60890 | no | a separate 1,450-vertex model; not seen in the recording |

## Other characters

All get the automatic smoothing and shading. A model file only pays off where it adds something visible;
most of these characters already animate their floppy parts with their own bones.

| Character | Where seen in play | Fingerprint | Model file | Notes |
|---|---|---|---|---|
| Elephant | 7 zooboss (Elephant Pong) | 1d44544a0d4eebd7 | yes | ears swing (2 springs); checked drawn whole close up, the swing itself not caught on screen. The ears are thin plates whose rim points serve front and back; `tools/normals.py` (PLATES) gives each side its own normals, so they no longer shade dark or show black outline wedges |
| Yosemite Sam | 7 zooboss (in the stands), 17 westboss | dba92834ff14d74c | no | never close in play: about 40 pixels wide at 2880x1800 in westboss (top edge of the screen) and as far off in the zooboss stands. A dense file was built and drew whole in westboss with no crash (2026-11-15) but shows nothing at that size, so it was dropped |
| Gossamer | 7 zooboss (goalkeeper, close to camera) | 01036cdeaa4e7c03 | yes | dense surface, no springs, built with `PERBONE=1`. Checked in his goal celebrations (2026-11-15): facing the camera and covering his face, smooth outline, clean brows, no black shards (`qa/models-check/pairs/gossamer-fixed.jpg`; `gossamer-face-auto-old-fixed.jpg` shows automatic smoothing, the first dense build and this one). The first build had sawtooth brows: the game drew him with its one-bone shader, which ignores a dense model's blended weights. `qa/gossamer.sh <out>` takes the shots. |
| Tweety | zoo hub (flies around the Tutorial 1 book) | 9ccd72fd73041cc4 | yes | dense surface only. All 12 bones moved in 28 frames. Checked from behind at about 250 pixels tall (2026-11-15): drawn whole, head round, head feathers there. Not seen from the front in game, and not compared with the automatic smoothing in the same view Rebuilt with `PERBONE=1`; the rebuilt file checked 2026-11-27 in the Tutorial 1 scene, where she flies up to the camera: whole, rounded, head feathers there, face clean from the side. Her lopsided head is the original model's shape (same in the Original 2002 look). |
| Zookeeper | 14 ghost (recorded), 4 icedome, 3 zoo hub (seen) | adbdee12889a7268 | yes | dense surface only. Checked once in game, catching Taz in the ghost level (2026-11-15): drawn whole with his net, smooth outline, no gaps. Face hidden under the cap in that shot; not compared with the automatic smoothing in the same view Rebuilt with `PERBONE=1` afterwards and checked again in the zoo hub's Tutorial 4 (2026-11-27): coming out of his hut and swinging the net, face, cap, moustache, hands and net all clean and whole in the Remaster look. |
| She-Devil, Daffy, Elmer, Wile E. Coyote, Sylvester, Mecha-Tweety | cutscenes only (She-Devil also the 2-player levels) | one per cutscene | no | cutscene versions are separate models (`cs05_shedevil.obe` ...); a scene jump skips intros once seen (save flag at 0x6c9860 + slot*0x13d4 + scene*0xa8, bit 1) |

Seen while recording, not built: the ghost level has two more characters (a95143be45888734, 1,652 vertices,
and 996c0e186a82c7d8, 596); the zooboss lose screen draws its caged character (8a4245570492cc82, 3,180
vertices) and three sharks.

## Known limits

- Jumping straight into scene 2 (playpen) crashes the game, with or without the mod's models; 19 (tazboss1)
  crashed once while loading (only tried with the mod). 12 (cityboss) crashes right after loading
  (taz.exe +0x1140a6, also with every mod feature off) unless jumped to from 8 (cityhub), the way play
  reaches it.
- Jumping straight into 10 museum, 25 deconstruct or 28 rcgoldmine used to drop Taz into an endless fall at the map origin: the start point names a door or checkpoint leaves at 0x704ce8/0x704cec were still set, and a level only reads its own STARTPOSITION when they are 0. The test jump clears them now (2026-11-27); all three start on their start point.
- A model file only matches the exact model it was made from; a character whose model the game
  swaps (costumes, cutscene versions) needs one file per version.
