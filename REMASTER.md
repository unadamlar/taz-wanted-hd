# Remaster look: plan and state

The running plan for the `look-test` branch. Update it as work lands: it is how the next session picks up.
AGENTS.md holds the engine facts and test rig; read it first.

## Goal

Make the game look like a modern stylized remake while staying a mod of the player's own copy. The game's
code, levels, collision and animation stay. The direction is `extracted/look/target.jpg` (an AI image of the
zoo hub). It is loose reference: do what looks best for this game, never chase a pixel match.

## Where it stands

- Blender look test, zoo hub, three art passes: `extracted/look/pass3/` is the current best
  (`final-B-pass2-vs-pass3.jpg`, `final-A-pass2-vs-pass3.jpg`, `final-C-strip.jpg`). The user likes the direction.
- In game (`src/d3d8/look.c`, `hd.c`, off unless `tests=1` and `look=N`): `look=0` is off and any other value is the
  Remaster look. Live: a `taz-hd\look` file holding N. F11 cycles Remaster, HD and Original 2002.
- Step 1 is done (2026-11-21): the whole mod runs on Direct3D 9 through a built-in d3d8to9, and the hub's 5,353 static
  world pieces draw as 832 merged draws. Checked in game: `extracted/look/reports/step1/`.
- Step 2 is done (2026-11-22): the zoo hub draws pass 3's materials, foliage, grass, sky, water, soft shadows, AO, bloom
  and tone mapping in game, with the HUD ungraded. `master`'s camera, level ending and grass fixes are merged in.
  Checked in game: `extracted/look/reports/step2.md`.
- Step 3 is done (2026-11-22): 12 routes across the hub, with fixes for glows burning to white, shadows while walking,
  grass under the player, scenery at the camera, and the game's own screens. Report: `extracted/look/reports/step3.md`.
- Step 4 is done (2026-11-22): the city hub (scene 8) is a moonlit night city through the same pipeline, with street
  lamps, lit windows and signs. Report: `extracted/look/reports/step4.md`.
- Step 5 is done (2026-11-22): the zoo has hard-edged cliffs, finished buildings, a creased elephant, real 3D barbed wire, a stone moat bank
  and a proper water bed. On-screen messages no longer drop the picture to the flat look, and the moat no longer breaks
  up when the camera skims it. Report: `extracted/look/reports/step5.md`.
- Planet X, the room behind the doors between hubs, has its own Remaster look (2026-11-22). It is not a scene: the same model
  sits far below each of the four hubs' levels, so `look.c` swaps to shared look data (`scene30`) while the camera is down there.
  It works from all four hubs, including the west and Taz hubs, which have no Remaster data of their own. Images:
  `extracted/look/reports/step6/planet/`.

Measured on the desktop (RTX 4070, 2880x1800, 4x MSAA, vsync off, 3 runs of 600 frames, fixed view). Zoo hub: Remaster
7.18-7.44 ms per frame, HD 1.63-1.64. City hub: Remaster 5.58-5.67, HD 1.56-1.61.

Memory, measured under Proton: Proton lifts the game's 2 GB limit by default, so normal test runs show about 3,500 MB free.
With the real limit on (`STEAM_COMPAT_CONFIG=noforcelgadd`), 23 level loads across 8 levels never went below 1,435 MB free,
so the game uses about 600 MB. With the 4 GB flag set in the exe, the same walk kept at least 3,485 MB free. Only the two
hubs have Remaster data so far, and real Windows is not measured.

## Step 6 in progress (2026-11-23)

The user's first play-through fix list is merged: floating logs, fence height, Taz's fur and face, a 3D zoo boat, rings, blue
fences, chains and gates, trunks inside their railings, the city's tree, supermarket lights, background buildings, railing and
crane chains, and Planet X (`scene30`) with grass, rock, a round dome, a smooth hull and redrawn space.

- Current dressed scenes: zoo `extracted/look/pass7/zoohub-dressed.blend`, city `extracted/look/city/pass3/cityhub-dressed.blend`,
  Planet X `extracted/look/planet/pass2/planetx-dressed.blend`. Export each with `tools/look/export.py -- --level <level> --runtime <dir> --cpu`:
  a busy GPU can bake black, and the export then stops with an error.
- Character models use a new six-bone format, 138 MB instead of 53 MB. The new DLL skips the old files. The built ones are in the test
  copies' `taz-hd/meshes`; `extracted/meshes/out` is still old, so run `tools/models.sh` for the 20 models before packaging.
- The user's playable copy is `~/Games/taz-agents/play` (Lutris: "Taz: Wanted Remaster"). Its DLL and data are its own copies, so
  update it after each reviewed batch. Tests must not touch it.
- Sound distortion: measured as the game's own files and mix, not the mod. No fix is chosen. Evidence and options:
  `extracted/look/reports/step6/sound/`.
- Checked on the merged build (2026-11-24). Planet X: Taz walked through the real zoo door 6 times and back 5 times, and the look
  switched each way. Costumes: 11 draw in all three looks, but only the zoo's reindeer ran on real Remaster level data, and the ninja
  was not compared on his floor polisher. Lowest free address space with the real 2 GB limit: 1,331 MB over 27 loads of 12 levels.
  Uncapped at 2880x1800, 4x MSAA: zoo 7.56-7.57 ms, city 6.00-6.30 ms. Report: `extracted/look/reports/step7/rig/`.
- Not checked on the merged build: level-complete cutscenes (they could leave static 3D chains or fences behind).

## Step 7 in progress (2026-11-24)

Rolling out the look, two tracks at a time. Track state and resume steps: `extracted/look/reports/step7/RESUME.md`.

- Main menu, loading screens and pause menu have a Remaster version (`extracted/look/reports/step7/screens/`). Copy `scene01` and `screens`
  from `extracted/look/screens/runtime/` into `<game>/taz-hd/look/`. Not yet in the user's playable copy.
- For the user to judge: the deep blue loading screens, and the menu's brown dirt path where the original is flat orange.
- The continue screen (also the game over) has a Remaster version; rules pages (the book before boss levels and bonus races) keep the HD art
  (`extracted/look/reports/step7/screens2/`; data `scene31` and `screens` from `extracted/look/screens2/runtime/`). The rules backdrop goes soft and
  amber behind the unchanged book; the continue room (its own look, number 31, chosen by camera position) is a dark cave with a lamp on the cage.
  Map screens kept: full-screen posters whose colour-coded routes a regrade would fight. Normal levels have no rules page. All in the playable copy.
  User 2026-11-25: keep the continue room; the soft amber rules backdrop was reverted (its stars went blurry).
  Character pale paint is shaded in every level (user's pick, 5277d15): the hold at HD's bright cream read like the flat original.
  AO and bloom run at quarter size only (user saw no difference; about -0.3 ms in the zoo and city hubs). Paused-frame blur slightly softer.
  Saguaros are ribbed and domed, a muted olive with soft grooves (striped like the paint they read as a watermelon); museum, west hub, Grand Canyon,
  canyon race; data `extracted/look/saguaro2/<level>/runtime` (department store's flowers: `extracted/look/saguaro/deptstr/runtime`).
- Not checked: bonus-level loading art, a gamepad in these menus, where `boss.png` and `guide.png` splash images appear, continue screens outside westboss.
- City world done: department store, museum, construction site and city boss (`extracted/look/reports/step7/city-levels/`). Data is in
  `extracted/look/city-levels/<level>/runtime/sceneNN`. Not in the user's playable copy. Not checked: finishing a level, win and lose
  screens, the museum's real entry, the 2 GB limit, uncapped frame time. Museum jumps drop Taz into a fall and city boss jumps crash,
  so test them through the routes in that folder's `notes.md`.
- Zoo world done: ice dome, safari, aquarium and zoo boss (`extracted/look/reports/step7/zoo-levels/`). Data is in `extracted/look/runtime-step7/`.
  Not in the user's playable copy. Safari and the aquarium were mostly seen from fixed cameras, because Taz got stuck early on the test walks.
  Known leftovers: safari's flat tree canopies and palm leaves, painted green edges, a flat cyan water area in one view; faint straight
  lines across the aquarium's sea; slightly hazy ice dome snow.
- Zoo boss F5/F9 across the end-of-match replay: fixed by 084d699 (the replay's end frees the goal-effect texture; freeing a game texture now voids the
  quicksave, so F9 is refused). `master` still crashes 9 of 9 and needs that commit for a release (`extracted/look/reports/step7/crashes/notes.md`).
- Cutscenes use the level's Remaster look and keep their own props (`extracted/look/reports/step7/cutscenes/`). The mod tells a cutscene's textures
  from a level's by the pak they loaded from, so this needs nothing per level. Watched 14 of the 29 cutscenes plus two level endings. Open: the
  Tasmania intro's sky can flash flat lavender (in HD and Original too), and a bark strip crosses the zoo boss pitch in its intro.
- West hub done (`extracted/look/reports/step7/westhub/`, data in `extracted/look/westhub/runtime/scene13`): sunlit desert, 6.56-6.85 ms uncapped. Planet X
  worked through its real door from this hub. Not checked: popping in motion, a full walk on foot, the moving train's new chains, its cutscenes, the 2 GB limit.
  Known leftovers: Taz's cream face and belly are paler than HD, canyon walls keep big flat faces up close, and the arch's green prop is low-poly.
- Taz hub done (`extracted/look/reports/step7/tazhub/`, data in `extracted/look/tazhub/runtime/scene18`): turf, dirt paths, clear ponds with fish, the game's
  sky. 6.25M scattered triangles, 7.93-8.06 ms uncapped. Planet X unchanged from this hub (3 real door trips). Not checked: the intro flyover frame by frame, the
  boss doors, a walk on foot, resize, the 2 GB limit. Leftovers: the palest pink cliffs read slightly like veined marble, pool banks follow low-poly sides.
- West levels done: ghost town (night), goldmine (keeps its magenta), Grand Canyon, westboss; hub walls raised in relief, Taz's cream fixed by a
  per-level fill. Grand Canyon is the heaviest level so far (11.7 ms uncapped under load, 7,715 world draws). Westboss starts on its rules page: press Jump.
- Taz bosses done: tazboss1 (Disco Volcano; `glow_add` draws its additive flames as the game does) and tazboss2 (Sam's zeppelin). Taz's cream reads cooler
  than HD in tazboss1, and the zeppelin's force field is clear glass where HD shows near-solid cyan.
- Bonus levels done (21-29): eight reuse their story level's block through `_bonus()` in `levels.py`; detasmania has its own on the Taz hub's surfaces.
  rcgoldmine, rcicedome and deconstruct drop Taz into an endless fall from every entry; tests place him with the scripts in `extracted/look/westhub/bonus/`.
  Deconstruct is dark and Taz reads as a dark shape there; deaqua's flat deep-blue sea is now clear turquoise water over sand.
- Every scene now has Remaster data, and the user's playable copy has all of it (2026-11-24, e1852b5).
- Real 3D objects in place of painted cards so far: safari, Taz hub, west hub, museum (cloth banners, saguaro), department store (one 3D flower per
  painted flower in the beds), safari race, Grand Canyon and its race (saguaros, barrel cacti, signs on boards), zoo boss (leafy bushes), museum race (cloth
  banners), ice dome and its race (real bulbs on a sagging wire), ghost town (round rails with turned balusters, an iron fence of real
  bars), Taz boss 1 (a real red tube truss), goldmine (real sawn plank fences), construction site and deconstruct (real chain links on the crane). The rollout is complete (2026-11-25). The construction site's lit signs and tyres, westboss, goldmine, city boss, aquarium, Taz boss 2, main menu and detasmania were surveyed and left
  alone: their flat art is lit signs, gameplay signs, posters, crates, effects, floor panels or models. The playable copy has these (2026-11-24).
  Candle flames stay the game's animated cards (3D would lose the flicker); burning crates and campfires are 2D sprites the look data can't reach.
  3D train smoke was built and reverted: the puffs are hidden in tunnels and cuttings, and the test camera could never show one to judge.
- For the user to judge in the west: the game's painted canyon stripes are kept on its own shapes. The zoo's rebuilt 3D rock would add depth but replace them,
  and the choice carries to ghost town, goldmine, Grand Canyon and westboss.
- For the user to judge in the city levels: real paint replaces baked colour (store's blue, museum's pink floor, construction huts teal to yellow).
- Crashes track (2026-11-25, `extracted/look/reports/step7/crashes/`): Taz boss 1 closed a few seconds after the test win when a non-player touched a
  player-only object (taz.exe+0x23537, also on `master`); `asserts.c` now skips that touch (0 of 5 after, was 1 of 2). A real fight win was not tried.
  Not reproduced in about 60 Continues and 34 level changes: the d3d9.dll +0x1222a6 crash (freed DXVK memory written earlier; seen once on a zoo boss
  Continue and once on an rcsafari retry after about 30 loads and 300 screenshots), and one Continue-room crash in `merge.c` `add_piece` on a freed vertex buffer.
- Playthrough QA (2026-11-25, `extracted/look/reports/step7/playthru/notes.md`): every level and hub on foot, 60 fps throughout. Open: goldmine sweet sign
  draws black, Taz pale peach in the goldmine, flat green lawn on the main menu (all with the flatscan track). Gamepad not covered.
- Optimization pass (2026-11-25): most levels run 1.3-2x faster uncapped at 2880x1800 with 4x MSAA, look code 0.5-2.5 ms a frame (was 3-7), no intended
  look change. The zoo and city hubs are now limited by the GPU (grass is about 1.75 ms there); most other levels by the game's thread. Tables and the
  profiling patch: `extracted/look/reports/step7/optim/`. Not measured: main menu, Planet X, zoo boss and ice dome (their state changed between runs).
  For the user to decide: lower-resolution AO or bloom (0.3-0.5 ms GPU, changes the picture); drawing the sky after the world (most of 0.34 ms GPU,
  changes draw order against the game's own backdrops).

## How the pieces fit

1. `taz-hd\world` trigger records the level (`capture.c`).
2. `tools/worldview.py` rebuilds it in Blender. Check: it matched the game's frame to 0.18 px on average.
3. `tools/look/dress.py` dresses it through `tools/look/kit.py`. Each level is a block in `tools/look/levels.py`: a table
   of texture-name patterns -> roles, sun, grade, sky, and hand items. Keep those few, since how this scales to 27 levels
   is the main question.
4. `tools/look/export.py` writes the additions to `taz-hd\look\sceneNN\`; `look.c` draws them.

Rerun commands: see the usage lines at the top of `dress.py`. Look data: `blender -b extracted/look/pass5/zoohub-dressed.blend
--factory-startup --python-exit-code 1 -P tools/look/export.py -- --level zoohub` (or `cityhub`; Planet X: `extracted/look/planet/pass2/planetx-dressed.blend`, `--level planetx`). Shaders: `src/d3d8/shaders/build.sh`
regenerates the checked-in `look_shaders.h`. In-game: `qa/lookhero.sh`. `blender` here means
`~/.local/share/devtools/blender/blender`.

## Decisions

- Renderer route: translate the game's D3D8 calls to D3D9 in-process (d3d8to9 by crosire, BSD-2,
  github.com/crosire/d3d8to9, approved by the user), and draw the static world as merged buffers. D3D8 blocks
  real instancing, soft shadows, float targets for bloom and proper materials; a separate 64-bit renderer process
  is not worth it unless memory becomes the wall. Compress the HD textures to free address space.
- d3d8to9 is compiled into our DLL under the existing hooks, so the mod's D3D8 code keeps working. Its shader path
  through d3dx9_43.dll is replaced by direct bytecode conversion, since stock Windows doesn't ship that DLL.
- The merge only takes opaque or alpha-tested static world draws. The game still decides each frame which pieces are
  drawn, so a piece it stops issuing disappears as it would have.
- F11 cycles three looks (user, 2026-11-21): Remaster, HD (the `master` look: HD textures and models, no look
  additions or post) and Original 2002. Swaps are instant, with nothing reloaded. Scenes without look data cycle HD
  and Original only.
- Stay on D3D9 through step 5 (user, 2026-11-21). Newer APIs would add GPU-simulated grass, BC7, cheaper AO and ray
  tracing, but need a new renderer for everything the game draws. Revisit at step 6 from in-game results; if we jump,
  the candidate is Vulkan in a separate 64-bit process, which also removes the memory limit.
- Step 2 grade, judged in game against pass 3: the art's saturation x1.17, contrast x1.26, bloom x0.3; character albedo
  x0.7 and partly desaturated. Levels 1-3 and the debug views are deleted, so there is one Remaster path.
- Two upscaled game textures (`game_metaledges`, `game_tazcage3`) sit in the look data's `tex/`. Treat that folder as
  game-derived in any packaging.
- Second level is the city hub, not Grand Canyon: a night scene with lamps, pavement and buildings is the harder test of
  what carries over.
- Night levels keep the brightness of the game's baked vertex colours and drop their blue tint. Street lamps come from a
  rule and the baked warm pools, at most 64 per level, looked up through a grid so cost doesn't grow with their number.
- Hand work for the city: 14 texture rules, 12 glow rules, 3 material roles, 2 new CC0 texture sets, 1 hand exception,
  about 25 tuned numbers, nothing placed by hand. Estimate, not measured: 1 to 2 hours of agent time per further level of
  this size plus about 15 minutes of review, and 30 to 60 minutes more for a new surface type.
- Frame rate is a later pass. Don't let it block the look, but don't build anything that can't be made fast.
- The remaster targets modern hardware (user, 2026-11-22). Older PCs are not a reason to avoid a feature or graphics API.
- The Windows installer sets the 4 GB flag on the player's own retail `taz.exe` and uninstalling restores it. We never ship
  a `taz.exe`: it is the game's copyrighted program, and the mod only works on the player's own copy.
- Stay on D3D9 unless a measurement shows a newer API would make the game meaningfully faster after D3D9's own fixes, or
  gives an effect we want (user, 2026-11-22).
- Measured after step 5: frame time is the same from 1920x1200 to 2880x1800 (zoo 7.19-7.21 vs 7.18-7.44 ms, city 5.63-5.96
  vs 5.58-5.67), so the CPU sets the frame rate. The Remaster code on the game's thread is 60-70% of the frame. In the city
  at 2880x1800 with 4x MSAA the GPU also reaches 94-97%. No case to switch API yet: cut that CPU work on D3D9 in step 6, then
  measure again. How much of it is the API's own cost is not separated, and real Windows is not measured.
- Hand work for the zoo art: 21 texture rules, 1 path change, no new assets, no hand exceptions, about 19 tuned numbers.
- Hand work for Planet X: 1 hide rule, 2 dome rules, 1 ground rule, 9 gameplay rules, 4 relief rules, 5 material roles from existing
  CC0 sets, a table of the 10 painted planets, nothing placed by hand, about 50 tuned numbers (estimate). The round dome (a superellipse
  containing every vertex of the game's), its ribs and the smooth hull ring are generated from the game's own rings. The hull ring is laid
  just over the game's faceted one, so collision and everything else stays. Space is the game's three panels redrawn by `tools/look/space.py`
  (original procedural work) at 4096 px: same layout, lit planets, more stars, still turning with the game's own transform.
  Painted surfaces there keep their HD colour through the tone curve (`hold`), and light only shades them.
- Sun is per level and placed for looks; baked vertex shadows are dropped.
- User, 2026-11-24: the goal is a reimagined look, so flat 2D objects (painted cards, bushes, flowers, signs, low-poly props) become real 3D
  objects. Rounded or thickened copies of the painted cards were tried and rejected ("don't look great"). Gameplay objects stay readable.
- User, 2026-11-24: keep the deep blue loading screens and the menu's dirt path. West levels keep the game's painted canyon stripes on its
  own shapes, with depth added only on the biggest flat walls. City store and museum keep their real paint; the construction site gets some of
  its night blue back. The playable copy now has everything merged up to f52df7b (backup: `~/Games/taz-agents/play-backup-2026-11-24`).
- Never move a game surface. Walkable tops keep their height; replacements must contain the collision shape.
- Gameplay objects (books, signs, crates, trampolines, pickups) stay readable and clear of grass.

## Roadmap

1. (Done 2026-11-21) Renderer: move to D3D9 and merge the static world in one go. Everything the mod already does must still work:
   HD textures and models, Taz styles, MSAA, resolution change, F5/F9, F11, menus, map previews, paper books, video,
   screenshots, gamepad. Handle device reset for the new targets.
2. (Done 2026-11-22) Bring pass 3 in game: materials on ground, brick and cliffs, foliage cards, sky and clouds, water, soft shadows,
   AO, bloom, tone mapping, character lighting that fits the world (Taz's outline look clashes with it now), a grade
   that leaves the HUD alone, and grass that fades instead of popping.
3. (Done 2026-11-22) Walk the whole zoo hub and fix what shows in motion: popping, sorting against particles and blended draws, feet in
   grass, hidden pickups, the camera passing through trees and fences, level transitions, quickload.
4. (Done 2026-11-22) Second level (city hub, scene 8) to prove what carries over; measure hand work per level.
5. (Done 2026-11-22) More zoo hub art: sharper cliffs, buildings, the elephant, painted leftovers (zigzag moat bank, barbed wire).
6. (Done 2026-11-25) Rollout to all levels, screens and cutscenes; optimization pass. The Remaster stays in this repo (user, 2026-11-25).

## Known problems

- Fixed 2026-11-25 (`extracted/look/reports/step7/fixes/`): rules pages lost their HD and Remaster art after a resolution change (textures that
  survive a Reset now keep their replacements), and the map's Video preview now gets the Remaster pass. Not checked: the preview without MSAA, in
  maps other than Ghost Town's, or through a resolution change while it plays (it should fall back to HD).
- The middle of Taz's back is still dark in the zoo when the sun is behind him.
- The tutorial book's ribbon is thinner and less bright than in HD, and a soft yellow glow remains around the book.
- The fade for scenery by the camera is not checked in motion, and the water only along one run beside the moat. A sprite
  closer to the camera than fading scenery may draw behind it.
- With the camera pressed against the end of the moat, a few frames show a flat green patch and the moat wall. Cause unknown.
- City hub: the big yellow shop door glares, grass right beside a lamp looks like daylight, searchlight beams are flat
  pale triangles, close-up walls are flat and very dark, bright painted green shows at lawn edges, and the painted
  pavement lines don't follow the slab joints. The intro flyover ran without a crash but its frames were not reviewed.
- The zoo's Planet X door opens only once levels 4, 5, 6 and 7 are won, and `qa/save.city` has only 5 and 6. Mark them with
  `taz-hd\complete`, reload the hub and approach the door from the front. Doors into ordinary levels were not tested deliberately.
- The walking-shadow fix is in but not measured. Jumping scenes with the test trigger during the boss intro closes the
  game, with the look off too; plain `master` was not tried.
- Looningdale's level ending still shows 0.9 s of black, on plain `master` too (measured 0.87 s there, 0.92 s here).
- One crash on returning from an alt-tab (2026-11-22, 3840x2160, level 11, Proton CachyOS, NVIDIA 620.73), cause unknown and
  not reproduced. A graphics thread aborted on a double free while the main thread destroyed DXVK semaphores, and Wine ended
  the game with exit code 3, past our crash log. About 1.18 GB of address space was free, so it was not the memory limit.
  130 real alt-tabs in that level at that size under a private KWin did not crash. The device never reported lost, so the
  game's reset path did not run. Test builds now log focus, device state and exits the game did not ask for.
- Not tested on the D3D9 build: real Windows, Wine without DXVK, a physical gamepad, an alt-tab on a real monitor, `config.exe`,
  a full `tools/package.sh` run, a world piece first seen after the merge is built, a world buffer rewritten mid-scene.
- At level 0, 3.9% of pixels differ from the D3D8 build by more than 16 levels, on thin edges and foliage. It looks
  the same side by side; the cause is not isolated.
- Zoo art: rock colour is flat up close and the moss on its ledges looks like green shards. Buildings keep their low-poly
  shapes and the ice detail is subtle. The elephant keeps its low-poly blob shape under its new hide. The water bed barely
  reads.
- Planet X: the red planet under the dome keeps its low-poly shape, craters and white crosses. Door shadows don't follow a door while it
  swings open. Coming back from it reloads the hub's look, a pause of about 0.5 s in the zoo.
- The elephant's hide goes on any untextured character's mid-grey parts. An 18-leg walk found only the elephant, but did
  not cover the whole hub.
- One test visit to the city drew no grass, trees or other added scenery (`extracted/look/checks/screens-ab1`), in a session using live
  shader reloads. It did not repeat in about 16 later checks or 25 clean zoo-to-city visits. Cause unknown.
- Requesting screenshots about every 90 ms through level changes crashes the game after 4-5 changes, on the build before the screens too.
- The pause menu's Exit Game prompt draws over the Exit Game row. Not compared with the build before the screens.
- Main menu: the shore's orange looks salmon, the water is duller than the original, and the alarm clock and fridge are very bright.
- Tazboss2: one Remaster frame showed Taz's helmeted head and claws without his body (2026-11-24, 4 s after entering). Not reproduced in ~80 same-moment
  pairs and three bursts; a probe saw the HD model drawn every frame. Cause unknown.
- Tazboss2: one crash on entry through the test trigger (jump to 0x01000006). The game's set-texture function (0x5737d0) called the callback of a texture
  record whose memory had been freed and reused, from its flat 2D quad drawer (FUN_004dd8f0, used by the map screen and map preview). Not repeated in 21
  entries; the mod's code paths don't touch the game's texture records (read from code, not tested). Likely the known boss-intro test-trigger crash.
- Costume pieces the game attaches to characters (helmets, hats, the skateboard) now take the character paint (2026-11-25): tazboss2 helmet 204,32,34
  against HD 221,33,33 (was 216,56,45). Only Taz's four costumes and the canyon cowboy hat were looked at; other characters' attached pieces were not.
- Boss levels set themselves up on the first frame of play, and their cleanup assumes that ran. Leaving with the QA scene trigger from a rules page
  before pressing Jump therefore crashes: westboss at taz.exe+0x15f785 (null marker arrow), zoo boss after a Continue at taz.exe+0x9abae (stale freed
  camera case at 0x736374). A second entry after such an exit crashes on a freed texture in the 2D quad drawer, probably the same family. Players can't
  reach it: Escape does nothing on rules pages, setup runs within 0.25 s of Jump, and a quicksave from a rules page is refused once play starts.
  Clean: 11 zoo boss F5/F9-then-exit runs over 3 processes, 2 Taz boss 1, 2 city boss, 15 westboss real exits. The QA trigger now waits until the level is in play (`qa/s4.sh scene` presses Jump while it waits); 5 westboss and 6 zoo boss trigger exits from rules pages were clean after it.
  The city boss trigger entry crashes at taz.exe+0x1140a6; enter it the game's way. One d3d9.dll crash during a zoo boss Continue reload (5th visit
  in one process) did not repeat. Notes: `extracted/look/reports/step7/cutscenes/notes.md`.
- A 240-frame full-size screenshot burst crashed in d3d9.dll after 156 frames (`extracted/look/reports/step7/tazhub/burst-crash-taz-hd.log`). Smaller bursts are fine.
- Test-camera shots differ between runs where the game places sprites on screen from its real camera (the safari waterfall's splash, a pink sprite in zoo-b).
- Test runs load any shader files left in `taz-hd\shaders` over the built-in ones. `qa/fast.sh start` now clears them.

## Working rules for this branch

- All work stays on `look-test`. Commit often, in plain English. Don't push, merge to master, tag or release.
- Test only in `~/Games/taz-agents/<name>` copies. Never launch or change `~/Games/taz-wanted` or
  `~/Games/taz-wanted-prefix`: on Lebus that is the user's own Lutris install, with their save.
- Game-derived files stay in ignored folders (`extracted/`, `qa/`, `re/`). Downloads: CC0 assets into
  `../asset-library/` with licence recorded; d3d8to9 is the only approved outside code.
- After each milestone, save a before/after image and a short note to `extracted/look/reports/`.
- The NVIDIA driver hung and froze the whole desktop on 2026-11-23 with five tracks running, cause unproven. Run at most two test
  games at once, keep Blender off the GPU (`dress.py` without `--camera`, `export.py --cpu`), and keep scatter under `dress.py`'s 8M triangle limit.
