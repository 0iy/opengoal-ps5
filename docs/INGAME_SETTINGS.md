# PS5 in-game settings (OpenGOAL's own options menus)

Status 2026-10-24. Patch script `patch_ps5_ingame_settings.py` (manifest step `ingame-settings`, `required: false`).
Applied only to a private copy (`~/ingame_src`, `~/ingame_full`); not applied to `~/jak`, not built into the app, not run on the console.

## Where the console gets goal_src (the patch must reach it)

- The console compiles `goal_src` on the device: `ps5shim/importer.cpp:173-175` runs the extractor with `--extract --decompile --compile`
  against the project dir `/data/opengoal/proj_<game>/`.
- That project dir is unpacked from the toolchain pack (`unpack_skeleton`, `importer.cpp:180-181`), and the pack is built by
  `make_skeleton.py <jak-project dir> skeleton.tar.zst` from `goal_src`, `decompiler/config`, `decompiler/data`, `game/assets`,
  `custom_assets`, `common/goos` of the jak-project tree. So the patch must be applied to that tree (the patched `~/jak`, or the
  `sync_upstream.py` private copy) BEFORE `make_skeleton.py` / `push_skeleton.py`. The patch touches `goal_src/**` and
  `game/assets/<game>/text/game_custom_text_*.json` (both are in the pack), plus two C++ files for the engine build (`rebuild_all.sh`).
- `unpack_skeleton` runs only when `goal_src/<game>` is missing. A console that already imported keeps its old `goal_src`; push the new pack
  (`push_skeleton.py`) and recompile (re-import, or delete `goal_src` of that project) for the menu change to appear.
- The decompiler does not overwrite `goal_src` (it writes reference code to `decompiler_out/`), so the edits survive an import.
  Nothing the extractor emits sets pc-settings: the settings file is `pc-settings.gc` in the user config dir (`/data/opengoal/config/...`,
  `FileUtil.cpp` patch), created by the game at first run (`load-settings`) or copied by a user. That is why settings are also forced at load (below).

## What changes per game

### Shared (all three games): `goal_src/jak1/pc/pckernel-common.gc` (Jak 2 and 3 build this file from the jak1 folder, `jak2/lib/project-lib.gp:221`)

| Site (original line) | Change |
|---|---|
| `load-settings` end (`:642`, after the `cond`) | `(set-frame-rate! obj 60 #t)` then `(true! (-> obj vsync?))`: whatever a copied `pc-settings.gc` said |
| `handle-input-settings` `("fps")` (`:449`) and `("vsync")` (`:492`) | the saved value is read (the parser needs it consumed) and ignored |
| `update-to-os` (`:114-123`, runs every frame) | `pc-set-vsync #t`, `pc-set-frame-rate 60`, `vsync?` forced `#t` |

`window-size`/`game-size`/`msaa` keys are not touched (game-size is overwritten by `appmain.cpp`; MSAA is kept, see below).

### C++ (engine build)

- `game/kernel/common/kmachine.cpp`: `pc_set_vsync` (`:975`) always true, `pc_set_frame_rate` (`:983`) always 60, `pc_set_display_mode`
  (`:577`) a no-op, all under `#if defined(__ps5__)`. New kernel functions `pc-ps5-get-setting` (`int -> int`) and
  `pc-ps5-set-setting!` (`int int -> none`), registered next to `pc-set-vsync`. They call weak `ps5_ingame_get(int)` / `ps5_ingame_set(int,int)`.
- `game/system/hid/display_manager.cpp:27`: after `load_settings()` the display mode is forced to Fullscreen and `display_id` to 0
  (a copied PC `display-settings.json` cannot select windowed/borderless/another monitor). `SDL_SetWindowFullscreen` is a stub in
  `ps5shim/ps5sdl.cpp:358`, so this only sets the state the menu reads (`pc-get-display-mode` returns `fullscreen`).
- `define-extern` of the two functions in `goal_src/jak{1,2,3}/kernel-defs.gc` after `pc-set-vsync`.

### Jak 1: `goal_src/jak1/pc/progress-pc.gc` (old `game-option` system)

`*graphic-options-pc*` (`:250-290`). Disabled = existing `:option-disabled-func`: drawn locked (`:3018-3023`, locked colour, value still shown, so the
fixed value is visible read-only) and confirm is ignored (`:2443-2447`).

| Entry | Original line | Now |
|---|---|---|
| Game resolution (menu `resolution`) | 258-262 | disabled |
| Display mode | 263 | disabled (shows Fullscreen) |
| Display (monitor menu) | 264-270 | disabled (was: only when windowed) |
| V-Sync | 271 | disabled (shows On) |
| Aspect ratio, MSAA | 272-278 | untouched |
| Frame rate | 279-285 | disabled (shows 60) |
| NEW slider `ps5-upscale` 0..4, NEW slider `ps5-sharpness` 0..10 | inserted before PS2 options | entries 7 and 8; values in `*ps5-fsr*`, loaded from `pc-ps5-get-setting` when the menu is built (`:2136-2140`), written by `:on-change` |

Cursor skipping: Jak 1 never skipped. New `ps5-opt-disabled?`, `ps5-nav-step!`, `ps5-nav-skip!` (before `respond-common`, `:2182`); the up/down
branches (`:2210-2234`) call `ps5-nav-skip!`, and a snap at the top of the nav block moves the cursor off a disabled option (the page opens on index 0 = disabled).
At most one lap, so a list with only disabled entries (e.g. "no other resolution") cannot hang. Side effect: every other disabled entry in the Jak 1 menu
(controller, speedrun, "message" options) is now skipped too.

### Jak 2: `goal_src/jak2/pc/progress/` and Jak 3: `goal_src/jak3/pc/progress/` (generic menu, same text in both games)

`*graphic-options-pc*` in `progress-static-pc.gc` (Jak 2 `:578-700`, Jak 3 `:689-811`). Disabled = `:should-disable? (lambda () #t)`, drawn with
`progress-option-off` (`progress-generic-draw-pc.gc:259,298,332,385,477`); confirm is blocked (`progress-generic-pc.gc`, `should-disable?` check in the scrolling page).

| Entry | Jak 2 / Jak 3 line | Now |
|---|---|---|
| Window size (`menu-generic-to-resolutions-option`) | 584 / 695 | disabled |
| Display (monitor carousel) | 588 / 699 | disabled |
| Display mode carousel | 601 / 712 | disabled (shows Fullscreen) |
| Aspect ratio, MSAA, PS2 graphics page | 617, 683, 700 / 794, 811 | untouched |
| Frame rate carousel (+ its disclaimer page) | 651 / 762 | disabled (shows 60) |
| V-Sync boolean | 675 / 786 | disabled (shows On) |
| NEW carousel `progress-ps5-upscale` (Off / Quality 83% / Balanced 67% / Performance 50% / Auto) | before `progress-graphics-ps2` | `get-item-index-fn` = `pc-ps5-get-setting 0`, `on-confirm` = `pc-ps5-set-setting! 0` |
| NEW carousel `progress-ps5-sharpness` 0..10 | same | disabled while upscale = Off |

Cursor skipping (`progress-generic-pc.gc`, `respond-progress` of `menu-generic-scrolling-page`, Jak 2 `:271`, Jak 3 `:272`): new `ps5-menu-option-disabled?` and
`ps5-menu-skip-disabled!`; called after the up and down moves (wrapping) and once per frame while no item is selected (so the page does not open on the disabled index 0).
Side effect: other `should-disable?` entries (controller pages without a controller, mouse options) are skipped too.

### Text

New text ids `#x1f10`/`#x1f11` (Jak 1 `ps5-upscale`/`ps5-sharpness` in `engine/ui/text-h.gc`; Jak 2/3 `progress-ps5-upscale`/`progress-ps5-sharpness`
in `text-id-h.gc` / `text-h.gc`), added to every `game_custom_text_*.json` of the game in English. The Jak 2/3 value labels ("Quality (83%)" ...)
are string literals in the lambda (English only; Jak 1 shows plain numbers on its sliders: upscale 0 off, 1 quality, 2 balanced, 3 performance, 4 auto).

## FSR / render scale: how the menu and the launcher agree

Single source of truth is `ps5.cfg` (`upscale=0..4`, `sharpness=0..10`, `docs/FSR.md`). The launcher reads/writes it through `Ps5Settings`. The renderer
reads `PS5_RENDER_SCALE`/`PS5_FSR_SHARP` from the environment once at engine start (`appmain.cpp`, docs/FSR.md), so an in-game change applies at the next game start,
exactly like the launcher. There is no separate "Render scale" field: the render scale IS the upscale preset (83/67/50 %/auto, shown in the label); a free percentage
would need a new `ps5.cfg` key and is not in docs/FSR.md. Sharpness is the second entry.

The GOAL side asks C++ via `pc-ps5-get-setting` / `pc-ps5-set-setting!`; C++ forwards to the weak symbols below. **The shim side is not written** (files owned by others, so
not edited). Proposed code for `ps5shim/launcher.cpp` (ids: 0 = upscale, 1 = sharpness):

```cpp
extern "C" int ps5_ingame_get(int id) {
  const Ps5Settings& s = ps5_settings();
  return id == 0 ? s.upscale : id == 1 ? s.sharpness : -1;
}
extern "C" void ps5_ingame_set(int id, int v) {
  Ps5Settings& s = ps5_settings();
  if (id == 0) s.upscale = std::clamp(v, 0, 4);
  else if (id == 1) s.sharpness = std::clamp(v, 0, 10);
  ps5_settings_save();
}
```

Without it the weak symbols are null: the entries show "Off"/0, changes do nothing, nothing crashes.

## Extending

Add an edit to `EDITS` in the script (`edit(id, file, old, new)`; `old` must match exactly once; `new` must not be a substring of text that already exists
elsewhere in the file, otherwise the idempotency check skips it). To disable another option in Jak 2/3 add `:should-disable? (lambda () #t)`; in Jak 1 `:option-disabled-func (lambda () #t)`.
Then `python3 patch_ps5_ingame_settings.py --emit-manifest` prints the manifest step with all anchors (already merged into `ports/manifest.json`).

## Checks that were run

- `JAK_ROOT=<private copy> python3 patch_ps5_ingame_settings.py`: 121 changes, 0 failed; second run: 0 changes (idempotent). The script refuses to write a `.gc` file that is no longer
  paren balanced (string, `;` comment and `#| |#` aware); every patched file was balanced before and after.
- Net paren delta of every edit is 0; symbols used (`menu-generic-option`, `type?`, `*progress-pc-generic-store*`, `progress-scroll-up!`, `PROGRESS_PC_PAGE_HEIGHT`, `1-!`, `min`, `max`, `string-format`, `true!`) were found in the sources.
- **Real goalc compile.** goalc was built in a private full copy (`~/ingame_full`, cmake + `ninja goalc`, about 40 min on 2 cores). Although the group builds need extracted game
  data, single targets compile from `goal_src` alone: `goalc -g <game> --user-auto --proj-path ~/ingame_full -c '(make "out/<game>/obj/<file>.o")'`. With the patch applied these
  compiled without error: jak1 `progress-pc`, `pckernel-common`, `pckernel`; jak2 `progress-static-pc`, `progress-generic-pc`, `progress-pc`, `pckernel`; jak3 `progress-static-pc`,
  `progress-generic-pc`, `progress-pc`, `pckernel` (each with its whole dependency chain, 260-400 targets, which includes the changed `kernel-defs.gc` and text-id enums).
  Use this command as the syntax check after every change (about 15 s per file).
- C++: `g++ -std=c++20 -fsyntax-only` (with and without `-D__ps5__`) on the patched `kmachine.cpp` and `display_manager.cpp`: no errors. The engine was not linked.

## Risks and not verified

- Compiles, but behaviour is untested: the cursor logic (skip, wrap, snap), the Jak 1 slider callbacks and the carousel labels have never run in a game.
- Jak 1 slider hold-repeat: the slider moves every frame while left/right is held (same as the volume sliders), so 0..4 flies by; a tap moves one step.
- Jak 1 skipping with the scrolling list: `progress-scroll-down!` can be called more than once in one frame when several entries are skipped; with the current 11-entry page the skips
  never cross the scroll threshold, a long list of disabled entries might scroll oddly.
- MSAA was left in. The engine has an MSAA resolve path but `docs/FSR.md` says MSAA forces 100 % scale and the PS5 driver's MSAA support is unverified; if it misbehaves disable it the same way (`:should-disable? (lambda () #t)` plus force `gfx-msaa` to 1 in `load-settings`).
- Debug menu (`pc/debug/default-menu-pc.gc`) can still change `target-fps` / vsync / display mode in debug builds; the C++ side clamps vsync and 60 fps, `target-fps` in GOAL (game speed) is not clamped there.
- Pack and compiled game: an old imported project keeps the old `goal_src` (see top). The C++ changes need `rebuild_all.sh`.
- Jak X (`goal_src/jakx`) is not touched.

## Console test plan (main session; screenshots with `shot.py` / Remote Play)

1. Build: apply the script to `~/jak` (or run `sync_upstream.py port`), `rebuild_all.sh`, rebuild the skeleton (`make_skeleton.py`), push it, re-import or recompile one game.
2. Add the shim functions above; or skip them to test the "no shim" behaviour first (entries show Off, nothing crashes).
3. For each game: Options > Graphics. Screenshot 1: the page as opened (cursor must NOT be on window size/resolution). Check greyed: resolution/window size, display, display mode (Fullscreen), vsync (On), frame rate (60). Press up/down across the whole page, including wrap-around: the cursor must never rest on a greyed entry. Press confirm on neighbours of greyed entries: nothing opens. Screenshot 2: scrolled to the FSR entries.
4. Change Upscaling to Quality, leave the menu, check `/data/opengoal/config/ps5.cfg` has `upscale=1`; quit to the launcher and confirm the launcher shows the same value; restart the game and look for the `PS5_RENDER_SCALE` / `fsr` log lines.
5. Copy a PC `pc-settings.gc` with `(vsync #f)`, `(fps 144)` and a PC `display-settings.json` with windowed mode into the config dir: start, open the menu, the values must read On / 60 / Fullscreen, and the klog must show 60 fps pacing.
6. Check the other menus (controller, subtitles, language, aspect ratio, PS2 graphics page) still work, and that a controller page with no controller (disabled entries) is navigable.
