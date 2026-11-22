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

Measured on the desktop (RTX 4070, 2880x1800, 4x MSAA, vsync off, 3 runs of 600 frames, view A): Remaster 6.17-6.36 ms
per frame, HD 1.58-1.66, Original 1.52-1.54. Address space free: 1,849 MB at HD, 1,772 MB at Remaster, largest hole
1,315 MB.

## How the pieces fit

1. `taz-hd\world` trigger records the level (`capture.c`).
2. `tools/worldview.py` rebuilds it in Blender. Check: it matched the game's frame to 0.18 px on average.
3. `tools/look/zoohub.py` dresses it through `tools/look/kit.py`: a table of texture-name patterns -> roles, plus a
   per-level `LEVEL` block (sun, grade, sky, cliff settings). Hand items are listed in `HAND`; keep them few, since
   how this scales to 27 levels is the main question.
4. `tools/look/export.py` writes the additions as `taz-hd\look-sceneNN.bin`; `look.c` draws them.

Rerun commands: the `extracted/look/` renders come from
`blender -b --factory-startup --python-exit-code 1 -P tools/look/zoohub.py -- game|lit|dressed --camera ABC`, then
`python3 tools/look/zoohub.py compose pass3`. Look data: `blender -b extracted/look/pass3/zoohub-dressed.blend
--factory-startup --python-exit-code 1 -P tools/look/export.py -- --scene 3`. Shaders: `src/d3d8/shaders/build.sh`
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
- Frame rate is a later pass. Don't let it block the look, but don't build anything that can't be made fast.
- Sun is per level and placed for looks; baked vertex shadows are dropped.
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
4. Second level (city hub, scene 8, or Grand Canyon, 16) to prove what carries over; measure hand work per level.
5. More zoo hub art: sharper cliffs, buildings, the elephant, painted leftovers (zigzag moat bank, barbed wire).
6. Later, with the user: optimization pass, whether to split into its own repo, rollout to all levels.

## Known problems

- Taz looks flat from behind, which is how the player mostly sees him. The three non-Current Taz styles ignore the
  level's sun and shadows.
- The tutorial book's ribbon is pale and faint next to HD, and its yellow haze still covers part of the view up close.
- Bright flat green ground shows around the book stands. Scenery right next to the camera dissolves in visible dots.
  The water has fewer white glints than pass 3.
- Walking through a real level door is not tested: about 21 runs never got through one in this save. Level changes were
  tested through the game's scene change and a real level ending.
- The walking-shadow fix is in but not measured. Jumping scenes with the test trigger during the boss intro closes the
  game, with the look off too; plain `master` was not tried.
- Looningdale's level ending still shows 0.9 s of black, on plain `master` too (measured 0.87 s there, 0.92 s here).
- Not tested on the D3D9 build: real Windows, Wine without DXVK, a physical gamepad, a real alt-tab, `config.exe`,
  a full `tools/package.sh` run, a world piece first seen after the merge is built, a world buffer rewritten mid-scene.
- At level 0, 3.9% of pixels differ from the D3D8 build by more than 16 levels, on thin edges and foliage. It looks
  the same side by side; the cause is not isolated.
- Pass 3: cliffs are rounded like stacked pancakes, the water bed barely reads, the elephant is plain, buildings are
  untouched, a green-and-white fragment sits in camera B's bottom-right corner.

## Working rules for this branch

- All work stays on `look-test`. Commit often, in plain English. Don't push, merge to master, tag or release.
- Test only in `~/Games/taz-agents/<name>` copies. Never launch or change `~/Games/taz-wanted` or
  `~/Games/taz-wanted-prefix`: on Lebus that is the user's own Lutris install, with their save.
- Game-derived files stay in ignored folders (`extracted/`, `qa/`, `re/`). Downloads: CC0 assets into
  `../asset-library/` with licence recorded; d3d8to9 is the only approved outside code.
- After each milestone, save a before/after image and a short note to `extracted/look/reports/`.
