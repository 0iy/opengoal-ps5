# Plan: Jak 2 and Jak 3 at a 60 fps minimum

Status 2026-10-23. Evidence comes from `PERF_ANALYSIS.md` and the measurements of this date (details below).

## Goal and what "at any resolution" can mean

- Hard requirement: frame time never above 16.6 ms in normal play, in Jak 2 and Jak 3, at output 1080p, 1440p and 4K.
- Internal render resolution is the one lever that scales GPU cost. The plan therefore ships a dynamic resolution
  controller (internal resolution drops before a frame misses 16.6 ms; output stays at the chosen resolution). With it,
  60 fps is guaranteed at every output resolution. Native 4K internal at 60 fps is a stretch goal that the GPU budget
  decides; Phase 3 measures it, nobody can promise it today.

## Baseline (Jak 2 Haven city, 1080p output, ~1900 draws/frame)

| Item | Measured |
| --- | --- |
| Frame wall time | 44 ms (22 fps) |
| Render thread CPU | 18 to 30 ms (about 16 us per draw) |
| Render thread asleep in `nanosleep` | ~48 % of samples; replacing sleep by spin does not change the frame time |
| Waiting for prep workers (`runtime_async_collect_one`) | ~10 % of samples |
| GPU busy | ~18 ms per frame, one pass type about 7.5 ms per occurrence |
| Waiting for the pending flip | up to 11 ms per frame (`present-wait`) |
| Jak 3 spawn scene | GPU about 5 ms, CPU-bound (see `PERF_ANALYSIS.md`) |

CPU recording, GPU execution and the flip wait run one after the other instead of overlapping. Frame time is roughly the
sum of the three. Target: frame time = max(CPU, GPU), both below 16.6 ms.

Correction of an earlier reading: the sampling profiler guesses return addresses and is biased towards syscall return
points, so its "cache flush 60 %" and "nanosleep 48 %" attributions are not reliable; patch 42 (`drv_patch42.py`) changed
nothing measurable. Use the counters below instead.

Counters from the same run at 1080p internal (`last_run.log`, 66 frames per 3 s):

- Render thread user time 31.8 ms per frame, 224 voluntary and 121 involuntary context switches per frame.
- Two single draws per frame block for ~7.9 ms each (`slowdraws`: draw #28 and #173), about 16 ms of the 45 ms. 7.87 ms
  is one 127 Hz scheduler tick; the GPU trace shows the same constant 7.7 to 7.8 ms outlier. Suspect: the render thread
  is descheduled or waits on something that needs a free core while the prep workers and other threads spin.
- Flip wait (`present-wait`) is 0.01 ms per frame at 1080p internal; it was 11 ms per frame at the 4K internal setting.
- Back-pressure 0.08 ms per frame, batch submit 1.15 ms per frame: not the limit.

The first task of Phase 1 is therefore to find what the two ~7.9 ms draws wait for and to stop the render thread from
losing its core (thread oversubscription: prep workers, poller, loaders).

## Phase 0: measurement that can be trusted (1 to 2 days)

1. Wait-site accounting: name and time every sleep/spin/futex site in the driver and shim (GPU completion, flip,
   prep worker, fence, back-pressure). The per-frame report prints ms per site.
2. Frame-pointer stack walker plus a module map at startup, so the existing profiler resolves libkernel/libc frames.
3. GPU time per pass: tag each command group with render bucket and draw count (extend `gpu:` trace).
4. Benchmark harness: fixed scenes (Jak 2 Haven city view set, Jak 3 wasteland view set) from save files, N seconds,
   JSON output (p50/p95/p99 frame time, CPU/GPU/wait split), automatic A/B diff of two runs. Built on `ps5.py run`,
   `last_run.log` and the debug channel.
5. External view: `ps5debug` on port 744 (client `ps5dbg_maps.py`) for module maps and memory reads; test whether thread
   registers can be sampled from outside.

Exit: for both games, a table that splits every frame into CPU record, GPU per pass, waits per site.

## Phase 1: remove the serialization (largest expected gain, about 1 to 2 weeks)

1. Triple-buffered scanout with two flips in flight (driver: pool bytes, `register_buffers2` count, EGL buffer index,
   display alias offsets, present synchronisation). Removes the 11 ms flip wait and the 33 ms quantisation.
2. Remove the remaining forced GPU drains (about 7 per frame): audit each drain call site, replace by fences or
   renaming (patches 31/32 pattern).
3. Record frame N+1 while the GPU runs frame N (command buffer double buffering, deferred submit).
4. Replace the 1 ms sleep waits by fence-driven wakeups where a wait remains.

Exit: Jak 2 Haven wall time close to max(CPU, GPU) (about 25 ms or better).

## Phase 2: cut CPU time per draw (1 to 3 weeks)

Target: 1900 draws in under 8 ms of render thread time (about 4 us per draw).

1. Merge consecutive draws with identical state in `glfix` (tfrag/tie multi-draws, merc), `glMultiDrawElements` path.
2. Hoist per-draw work: cache uniform locations and program/texture state in the engine, skip redundant state in
   `ps5_draw_vbo_locked`, build descriptor tables once per batch and flush each batch once (flush volume was 40 MB/frame).
3. Move driver work to a dedicated thread (`glthread`, untested after the fixes) or pre-bake draw lists for static terrain.
4. Mip generation: replace per-frame `glGenerateMipmap` blit chains (about 50 blits/frame) with fewer or cached mips.
5. Remove the 7 to 9 ms hiccup in a random render bucket (render thread preemption: thread priorities/affinity).

Exit: render thread CPU below 8 ms in both games.

## Phase 3: cut GPU time (2 to 4 weeks, parallel to Phase 2)

1. Per-pass GPU timing from Phase 0 identifies the 7.5 ms pass type and the top passes of Jak 3.
2. Likely levers, each validated by measurement: depth prepass for terrain, cheaper alpha-test/discard shaders, texture
   formats and mip bias, merc and TIE shader cost, overdraw, post-processing at reduced resolution, render target
   formats and compression, sampler/cache settings of the PS5 driver.
3. Dynamic resolution controller (internal scale 100 % to 50 %, bias towards staying above 60 fps), with output upscale.
4. Matrix test: output 1080p/1440p/4K x internal scale. Record the GPU ms per pixel to decide whether native 4K can hold 60.

Exit: GPU below 14 ms at 1080p native in the worst scenes; dynamic resolution holds 60 at 4K output.

## Phase 4: decision gate (only if Phases 1 to 3 miss the target)

A native AGC backend for the hot passes (tfrag, merc) through OpenAGC (Apache-2.0) and openagc-psbc (MIT, SPIR-V to
AGC). Large (months) and not started; the gate is a measured per-draw driver cost that cannot go below the target after
Phase 2. AnyPS5 is GPL-2 only: read, do not copy.

## Phase 5: release quality

- Scenes: Jak 2 Haven city, Port, Kras city; Jak 3 wasteland, Spargus, Mar; boss/vehicle scenes. 30 minute soak per game.
- Regression run of all three games after every driver patch (`tour.py`, benchmark harness).
- 1% low and 0.1% low frame times in the report; shader cache pre-warm so first-time hitches stay below 50 ms.
- Commit and snapshot (`wsl_snapshot/`) after every green phase.

## Order and expected effect

| Step | Expected frame time, Jak 2 Haven | Confidence |
| --- | --- | --- |
| Today | 44 ms | measured |
| After Phase 1 | about 25 to 30 ms | medium (overlap is the design goal, not yet shown) |
| After Phase 2 | CPU below 10 ms, bound by GPU 18 ms | medium |
| After Phase 3 | GPU below 14 ms, 60 fps | low to medium (depends on the heavy pass) |
| Phase 4 | only if needed | n/a |

Risks: driver rework may expose PS5-specific limits (flip depth, memory types); GPU cost of the heavy pass may need
engine-side shader changes; 4K native may stay out of reach without lowering the internal resolution.

## Housekeeping

- Jak 2 had `game-size 3840 2160` (4K internal); changed to 1920x1080 (backup `backup/jak2_pc-settings.gc`); effect on fps
  not yet confirmed.
- Console boot order that works: fresh jailbreak, kstuff 1.11, ftpsrv, ShadowMountPlus 1.7beta7, no OnionHEN.
