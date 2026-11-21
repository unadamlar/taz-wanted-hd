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
- In-game prototype (`src/d3d8/look.c`, off unless `tests=1` and `look=N`): draws pass 2's grass, clutter, fences,
  trees and cliff rocks inside the game's 3D pass, with sun shadow maps and tiling dirt. Screenshots:
  `extracted/look/render/`. It has not been given pass 3's art yet.
- Levels: `look=0` off, `1` additions, `2` adds sun and shadows on the world, `3` adds dirt and a colour grade,
  `8`/`9` shadow-map debug views. Live: a `taz-hd\look` file holding N.

Measured on the laptop (RTX 4060, 2880x1800, 4x MSAA, vsync off, mostly 2 runs): 210-240 fps at level 0, 105-130 at
level 1 (GPU-bound on ~2M grass triangles), 46-55 at levels 2-3 (CPU-bound: ~35 D3D calls for each of ~7,500 tiny
world draws). The additions cost ~25 MB of address space, with ~2.6 GB free.

## How the pieces fit

1. `taz-hd\world` trigger records the level (`capture.c`).
2. `tools/worldview.py` rebuilds it in Blender. Check: it matched the game's frame to 0.18 px on average.
3. `tools/look/zoohub.py` dresses it through `tools/look/kit.py`: a table of texture-name patterns -> roles, plus a
   per-level `LEVEL` block (sun, grade, sky, cliff settings). Hand items are listed in `HAND`; keep them few, since
   how this scales to 27 levels is the main question.
4. `tools/look/export.py` writes the additions as `taz-hd\look-sceneNN.bin`; `look.c` draws them.

Rerun commands: the `extracted/look/` renders come from
`blender -b --factory-startup --python-exit-code 1 -P tools/look/zoohub.py -- game|lit|dressed --camera ABC`, then
`python3 tools/look/zoohub.py compose pass3`. In-game: `qa/lookhero.sh`, then
`qa/lookmeasure.sh extracted/look/render "0 1 2 3" 3`. `blender` here means `~/.local/share/devtools/blender/blender`.

## Decisions

- Renderer route: translate the game's D3D8 calls to D3D9 in-process (d3d8to9 by crosire, BSD-2,
  github.com/crosire/d3d8to9, approved by the user), and draw the static world as merged buffers. D3D8 blocks
  real instancing, soft shadows, float targets for bloom and proper materials; a separate 64-bit renderer process
  is not worth it unless memory becomes the wall. Compress the HD textures to free address space.
- Stay on D3D9 through step 5 (user, 2026-11-21). Newer APIs would add GPU-simulated grass, BC7, cheaper AO and ray
  tracing, but need a new renderer for everything the game draws. Revisit at step 6 from in-game results; if we jump,
  the candidate is Vulkan in a separate 64-bit process, which also removes the memory limit.
- Frame rate is a later pass. Don't let it block the look, but don't build anything that can't be made fast.
- Sun is per level and placed for looks; baked vertex shadows are dropped.
- Never move a game surface. Walkable tops keep their height; replacements must contain the collision shape.
- Gameplay objects (books, signs, crates, trampolines, pickups) stay readable and clear of grass.

## Roadmap

1. Renderer: move to D3D9 and merge the static world in one go. Everything the mod already does must still work:
   HD textures and models, Taz styles, MSAA, resolution change, F5/F9, F11, menus, map previews, paper books, video,
   screenshots, gamepad. Handle device reset for the new targets.
2. Bring pass 3 in game: materials on ground, brick and cliffs, foliage cards, sky and clouds, water, soft shadows,
   AO, bloom, tone mapping, character lighting that fits the world (Taz's outline look clashes with it now), a grade
   that leaves the HUD alone, and grass that fades instead of popping.
3. Walk the whole zoo hub and fix what shows in motion: popping, sorting against particles and blended draws, feet in
   grass, hidden pickups, the camera passing through trees and fences, level transitions, quickload.
4. Second level (city hub, scene 8, or Grand Canyon, 16) to prove what carries over; measure hand work per level.
5. More zoo hub art: sharper cliffs, buildings, the elephant, painted leftovers (zigzag moat bank, barbed wire).
6. Later, with the user: optimization pass, whether to split into its own repo, rollout to all levels.

## Known problems

- Taz casts no shadow at levels 2-3; a fix and a state-caching build compile but were never run.
- Grass blades shadow themselves into dark speckle. The grade tints the HUD. Pebbles render darker than in Blender.
- Device reset isn't handled for the shadow textures. `qa/lookwalk.sh` was written but never run.
- Instancing relies on DXVK's 256 vertex constants (real D3D8 hardware may only give 96): another reason for D3D9.
- Pass 3: cliffs are rounded like stacked pancakes, the water bed barely reads, the elephant is plain, buildings are
  untouched, a green-and-white fragment sits in camera B's bottom-right corner.

## Working rules for this branch

- All work stays on `look-test`. Commit often, in plain English. Don't push, merge to master, tag or release.
- Test only in `~/Games/taz-agents/<name>` copies. Never launch or change `~/Games/taz-wanted` or
  `~/Games/taz-wanted-prefix`: on Lebus that is the user's own Lutris install, with their save.
- Game-derived files stay in ignored folders (`extracted/`, `qa/`, `re/`). Downloads: CC0 assets into
  `../asset-library/` with licence recorded; d3d8to9 is the only approved outside code.
- After each milestone, save a before/after image and a short note to `extracted/look/reports/`.
