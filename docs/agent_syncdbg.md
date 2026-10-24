# syncdbg: glitch classification tooling

Files: `drv_patch52.py` (driver), `shotseries.py`, `shotdiff.py` (PC). Nothing here touched the console or the live driver tree.

## 1. Sync-debug mode (driver patch 52)

`PS5_SYNC_DEBUG=1` (verified by reading the source and compiling `ps5_screen.c` from a private copy with the project flags; NOT run on the console).

What it changes (all in `ps5_screen.c`, each switch default-off):

| Effect | Where |
|---|---|
| No `ps5_try_deferred_draw` and no `ps5_try_multi_draw_batch`: every draw (and each sub-draw of a multi draw, via `util_draw_multi`) goes through `ps5_screen_submit_lock` (flush the open batch and retire everything in flight with wait) and `ps5_draw_vbo_locked` | `ps5_draw_vbo`, near the old `#ifdef PS5_DEFERRED_DRAW_BATCH` |
| No async prep workers: with no batch active `ps5_agc_gate2_run` calls `ps5_agc_gate2_run_sync` (`ps5_agc_native_runtime.c:1582-1585`); the queue is never fed | follows from the above, no runtime change |
| Buffer renaming off (same as `PS5_NO_BUFFER_RENAME`) | `ps5_buffer_rename_locked` |
| `PS5_NO_BUFFER_FLUSH` / `PS5_NO_DESC_FLUSH` ignored (flushes always happen); whole-bank descriptor flush forced (`PS5_FULL_DESC_FLUSH`) | the 3 `skip =` sites, `ps5_desc_flush_skipped`, `ps5_flush_descriptor_table` |

Statics added: exactly one function-local `static int ps5_sync_dbg` in `ps5_draw_vbo`. Same pattern as the existing `static int skip = -1`.

Assumptions, not verified on hardware: the synchronous path waits for GPU completion per draw (`agc.wait_rendering` in `main()`/run_sync of the runtime, `ps5_agc_native_runtime.c` about line 4640) and CPU cache flush/invalidate on that path is the pre-batching one (flush after CPU writes at draw time, `ps5_invalidate_gpu_writes` on CPU export). Not covered: runtime-side tweaks (command-group combining, flip pacing), glfix. Reading the code I found no way to prove "invalidate before every CPU read" beyond that, so a glitch that persists could still be a missed invalidate; mention that in the verdict.

### Shim proposal (do not apply blindly; `ps5shim/appmain.cpp` next to line 115)

```cpp
{ struct stat nf; if (stat("/data/opengoal/config/syncdebug.txt", &nf) == 0) { setenv("PS5_SYNC_DEBUG", "1", 1); setenv("PS5_NO_COMBINE", "1", 1); } }  // glitch classification, driver patch 52
```

`PS5_NO_COMBINE` (runtime, line 1875) also disables command-group combining. If you want a pure patch-52 test, set only `PS5_SYNC_DEBUG`. Make sure `noflush.txt` is absent (the patch ignores it anyway). glfix: its strip-to-list index conversion is deterministic CPU work with no GPU race, so I left it on: a glitch caused by it must survive sync-debug and be classed as translation bug. If you want to rule it out separately, that needs a different switch (not written).

### Apply and build

```
wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && python3 drv_patch52.py && bash drv_cc_cache.sh && bash rebuild_all.sh"
```
Rollback: the patch is idempotent and has no inverse; it is inert without the variable, so no rollback needed.

## 2. Test procedure for the main session

Pick a scene where the glitch is reproducible at a fixed time after launch (autolaunch + same save/start, same `times`). Same build for all runs, one run at a time.

1. Baseline A: normal config, no syncdebug.txt. `python shotseries.py request 40 50 60`, launch the game (as `ps5.py shot` does: `autolaunch.txt` + launch), wait until the log shows `captured` 3 times, `python shotseries.py fetch shots A`. Note fps lines.
2. Baseline A2: repeat step 1 as tag `A2`. `python shotdiff.py shots/A_0.png shots/A2_0.png --heat shots/A_A2_0.png`. This is the noise floor (animation, nondeterminism). If A vs A2 already differ strongly in the glitch region, the glitch is non-deterministic (typical of a race).
3. Sync run S: create `/data/opengoal/config/syncdebug.txt` (empty file, after the shim line is applied), repeat as tag `S`. fps will be low (expected, several times slower); use later `times` if the scene needs game time: the clock is wall time, not frames, so the scene may be at a different game state; prefer a paused/static scene or a menu-reachable state.
4. Remove `syncdebug.txt` afterwards (it persists on the console).
5. Compare: `python shotdiff.py shots/A_0.png shots/S_0.png --thresh 16 --heat shots/A_S_0.png`. Look at the percentage and the listed regions, and view the heatmap.

### Reading the result

- Glitch visible in A, absent in S, and A-vs-S regions cover the glitch area while A-vs-A2 does not (or only partly): race / coherency / missing barrier. Next: bisect with `norename.txt`, `nomultidraw.txt`, `nodescflush`/`noflush` individually (those are subsets of what sync-debug turns off).
- Glitch present in both A and S, A-vs-S nearly identical in the glitch region: translation bug (shader, blend, format, sampler, glfix). Compare S to a PC reference (same scene on the PC build) with `shotdiff.py --resize`; the regions give the screen area to debug.
- Glitch in S but different or only partly: mixed; treat the sync run as the cleaner baseline for the translation part.
- Differences between A and S that are not in the glitch region (animation, particles, time) are noise: judge only by regions that overlap the glitch and exceed the A-vs-A2 floor.
- `--thresh` 16 ignores small rounding; lower it to 4 to see dithering/format differences, raise to 48 to see only gross errors. Regions merge within `--block` pixels.

## 3. PC tools

- `shotseries.py request T1 T2 ...` writes `shot.txt` (read at app start, so do it before launch) and deletes stale `shot*.ppm`; `fetch OUTDIR TAG [--n N]` downloads `shot0..` and saves full-resolution lossless PNGs `OUTDIR/TAG_i.png` (existing `ps5.py shot()` downsizes to 960x540; this one does not, to keep per-pixel diffs exact). Host from `PS5_IP` (default 192.168.x.y, port 2121). Functions `ftp`, `request_shots`, `fetch_shots`, `save_series` are importable. Not run against the console.
- `shotdiff.py A B [--thresh N] [--heat out.png] [--block N] [--top N] [--resize]`: accepts PNG/PPM; per-pixel max channel difference, percentage over threshold, mean and max, bounding boxes (x0..x1, y0..y1, pixel count) of the largest 8-connected differing regions, heatmap (black same, red moderate, yellow strong). Exit 2 on size mismatch unless `--resize`.
- Tested on synthetic images (480x270 noise image with a 80x40 inverted patch, a 20x10 +40 patch, and one +3 pixel below threshold): reported 2.623 percent, regions 80x40 (3200 px) and 20x10 (200 px), identical images 0.000 percent. The shotseries FTP parts are untested.

## Risks and open points

- Sync mode is slow and changes timing, so timing-dependent game state differs; it hides races by serialising, which is the point.
- It only turns off what the driver exposes; GPU-side hazards inside a single draw or the async GPU mip generation (patch 44/51 paths) are not serialised more than before.
- Whether the sync path really waits per draw is read from code, not measured; check with the tracer (batch-retire waits should dominate frame time in S).
