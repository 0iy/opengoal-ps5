# In-game settings on the PS5

OpenGOAL's own options menus offer things the console cannot do (window size, monitor, vsync, frame rate) and lack the PS5 upscaling options. The patch
`engine/patch_ps5_ingame_settings.py` (manifest step `ingame-settings`, optional, requires `core`) locks the former and adds the latter. Details of the settings:
[`FSR.md`](FSR.md), [`USER_GUIDE.md`](USER_GUIDE.md).

Status: the patched `goal_src` compiles with goalc for all three games, the C++ part compiles, and the script is idempotent. The menus have not been exercised in a running game on
the console; check the list at the end.

## What reaches the console

The console compiles `goal_src` on the device. The project directory is unpacked from the toolchain pack that `engine/make_skeleton.py` builds from the patched jak-project tree
(`goal_src`, `decompiler/config`, `decompiler/data`, `game/assets`, `custom_assets`, `common/goos`), and `app/rebuild_all.sh` puts it into the app. So the patch must be applied
before the pack is built. The unpack runs only when `goal_src/<game>` is missing: a console that already imported a game keeps its old `goal_src`; re-import (or delete the project's
`goal_src`) for the menu change to appear. The decompiler never overwrites `goal_src`, so the edits survive an import.

## What changes

**All games** (`goal_src/jak1/pc/pckernel-common.gc`, also built for Jak 2 and 3): after `load-settings` the frame rate is forced to 60 and vsync on; saved `fps` and `vsync` values are read
and ignored; `update-to-os` re-forces both every frame. `window-size`, `game-size` and `msaa` are untouched (the app overrides `game-size`; MSAA stays, see below).

**C++** (engine build, `#if defined(__ps5__)`): `pc_set_vsync` is always true, `pc_set_frame_rate` always 60, `pc_set_display_mode` a no-op; `display_manager.cpp` forces fullscreen and
display 0 after loading settings. New kernel functions `pc-ps5-get-setting` and `pc-ps5-set-setting!` call the weak symbols `ps5_ingame_get(int)` and `ps5_ingame_set(int, int)`, which
`app/shim/launcher.cpp` implements on top of `ps5.cfg` (id 0 = upscale, 1 = sharpness). Without the shim the weak symbols are null: entries show Off or 0 and nothing crashes.

**Menus:**

| Entry | Jak 1 (`progress-pc.gc`) | Jak 2 and 3 (`progress/progress-static-pc.gc`) |
|---|---|---|
| Resolution / window size, display, display mode | disabled, current value still shown | disabled |
| V-Sync | disabled (On) | disabled (On) |
| Frame rate | disabled (60) | disabled (60) |
| Aspect ratio, MSAA, PS2 graphics | untouched | untouched |
| Upscaling | new slider 0..4 (off, quality, balanced, performance, auto) | new carousel (Off, Quality 83 %, Balanced 67 %, Performance 50 %, Auto) |
| Sharpness | new slider 0..10 | new carousel 0..10, disabled while upscaling is Off |

Disabled entries are drawn locked and ignore confirm. Cursor skipping was added so the menu does not open on, or stop at, a disabled entry (at most one lap, so a page of only
disabled entries cannot hang). Side effect: other disabled entries (controller pages without a controller, mouse options) are skipped too. New text ids `#x1f10` and `#x1f11` are added
to every `game_custom_text_*.json` in English. The Jak 2 and 3 value labels are string literals in the lambda (English only).

An in-game change is stored in `ps5.cfg` and applies at the next game start, exactly like the launcher: the renderer reads its environment once at engine start. The render scale is the
upscale preset; a free percentage would need a new `ps5.cfg` key.

## Extending

Add an edit to `EDITS` in the script (`edit(id, file, old, new)`): `old` must match exactly once, and `new` must not be a substring of text that already exists in the file (the idempotency check
would skip it). To disable another option use `:should-disable? (lambda () #t)` in Jak 2 and 3 and `:option-disabled-func (lambda () #t)` in Jak 1. `python3 engine/patch_ps5_ingame_settings.py --emit-manifest`
prints the manifest step with all anchors. The script refuses to write a `.gc` file that is no longer parenthesis balanced.

Syntax check after every change (about 15 s per file, needs goalc built from the same tree): `goalc -g <game> --user-auto --proj-path <tree> -c '(make "out/<game>/obj/<file>.o")'`. With the patch,
`progress-pc`, `pckernel-common`, `pckernel` (Jak 1), and `progress-static-pc`, `progress-generic-pc`, `progress-pc`, `pckernel` (Jak 2 and 3) compile.

## Not verified

- Behaviour in a game: cursor skipping and wrap, the Jak 1 slider callbacks and the carousel labels have never run.
- Jak 1 sliders repeat every frame while left or right is held (like the volume sliders): a tap moves one step.
- MSAA is left in; the FSR code forces 100 percent while MSAA is on and the driver's MSAA support is unverified. Disable it the same way as the other entries if it misbehaves.
- The debug menu (`pc/debug/default-menu-pc.gc`) can still change `target-fps` in debug builds; the C++ side clamps vsync and 60 fps.
- Jak X (`goal_src/jakx`) is not touched.

## Console test

1. Build with the patch (`tools/ps5 build`), rebuild the toolchain pack, push it, re-import or recompile one game.
2. For each game: Options > Graphics. The page must not open on a locked entry. Resolution, display, display mode, V-Sync and frame rate are greyed and read Fullscreen, On, 60.
3. Set Upscaling to Quality, leave the menu: `/data/opengoal/config/ps5.cfg` has `upscale=1`, the launcher shows the same value after quitting to it, and the log shows the render scale after the next start.
4. Copy a PC `pc-settings.gc` with `(vsync #f)` and `(fps 144)` and a `display-settings.json` with windowed mode into the config directory: the menu must still read On, 60 and Fullscreen.
5. The other menus (controller, subtitles, language, aspect ratio, PS2 graphics page) still work, and a controller page without a controller is navigable.
