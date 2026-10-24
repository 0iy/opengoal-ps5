# Performance analysis: view-dependent frame drops (Jak 2 / Jak 3)

Symptom: in some viewing directions the game runs at 60 fps, in others at ~30 fps and in slow motion. Slow motion is the
game logic running one tick per rendered frame, so every frame that takes longer than 16.7 ms slows the game down.

## What was measured (Jak 3, new-game spawn scene, 1080p, ~530 draw calls per frame)

| Test | Result |
| --- | --- |
| Baseline | 30 fps, render thread CPU 17.4 ms, frame 33.3 ms |
| Output / internal resolution 1080p -> 720p -> dynamic 0.64x | no change (an early "60 fps at 720p" reading was a loading scene) |
| tfrag3 fragment shader without texture fetch / without discard | 34-36 fps (small) |
| tfrag3 vertex shader without time-of-day texelFetch | no change |
| tfrag3 geometry pushed outside the clip volume | 36 fps |
| Skip draws 39-127 (89 terrain multi-draws, 224 sub-draws) | 56 fps (CPU 11.8 ms) |
| Skip any quarter of those draws | no change (cost is spread, quantised by vsync) |
| Render thread pinned to cpu 0/8/10/12 | no change |
| Prep workers (profile) | 75 % idle, not the limit |
| Descriptor-table flush cut from 233 MB to 110 MB per interval | no change |
| Memory type 3 (WC) instead of 12 | slower (20 fps) |
| Engine thread CPU (EE / IOP / DMP) | EE 6 %, IOP 1 %, DMP 0 %: game logic is not the limit |
| vsync off + adaptive (hsync) flip | 32-34 fps (from 27), tearing possible |

## Findings

1. The frame is limited by the render thread: ~18 ms CPU per frame at ~530 draws (about 32 us per draw call, ~24 us of it
   inside the GL entry points, ~10 % spinning for the async prepare workers at every batch drain, ~12 % cache-flush loops).
   Every extra draw adds to that, which is why the view direction matters: terrain/foreground that is in view adds draws,
   behind you it does not. Draw counts: ~400 draws -> 58 fps, ~530 draws -> 30 fps.
2. The scanout path is double buffered with one flip in flight and vsync flips. A frame that needs more than 16.7 ms is
   quantised to 33.3 ms (30 fps) instead of ~55 fps. Slow motion follows from that.
3. Not the cause: resolution, fragment/vertex shading, texture fetch, descriptor flush volume, thread placement, game thread.

## Open work (in order of expected gain)

- Triple-buffered scanout with two flips in flight (driver: pool bytes, register_buffers2 count, EGL buffer index,
  display alias offsets, present synchronisation) so 17-20 ms frames do not fall to 33 ms.
- Cut the per-draw driver cost (state building in ps5_draw_vbo_locked, batch drains per FBO pass, flush call count).
- GPU-side timing (AGC timestamps) to separate GPU time per pass from CPU time; the numbers above only show that GPU
  time is not dominated by pixels.

## Tools (this repository)

`jak3_play.py` (launcher -> new game), `fpsnow.py`, `pin_trial.py`, `ab_trial.py`, `dbg.py skiprange|trace|dumpprog|limit`,
profile.txt ("render" / "w0") sampling profiler, `threads:` log line (per-thread CPU), config flags in
/data/opengoal/config: noflush.txt, fulldescflush.txt, adaptiveflip.txt, nodescflush.txt (breaks rendering, diagnostic only).

## Update 2026-10-19 (GPU trace, flip experiments, worker counts)

New instruments: `gpu:` log line (poller thread timestamps every command-group completion marker, driver patch 23/24/25,
enable with gputrace.txt), `present-wait:` line (draws that waited for the pending flip), `threads:` line.

| Test (Jak 3 spawn scene) | Result |
| --- | --- |
| GPU completion trace | ~20 000 groups per 3 s, 88 % of them < 20 us; real GPU work ~5 ms per frame. ~1.5-2 stalls of ~7.7 ms per frame are not GPU work: they are the poller thread being descheduled (random group index, constant length) |
| Vertex/index buffers in memory type 3 instead of 12 | no change (26 fps, 18.4 ms CPU) |
| Always-immediate flips (mode 2) | 32-35 fps (from 27), still 28-31 ms per frame with 18.3 ms CPU |
| 1 prep worker | 24 fps, CPU 21.7 ms (worse) |
| 3 prep workers | 24-26 fps (no gain) |
| Draws that waited for the pending flip | ~1.9 per frame, ~6 ms per frame total |
| Render thread preemption | ~2500 involuntary context switches per second |

Conclusion so far: the GPU needs only ~5 ms per frame. The frame is limited by the render thread (about 10 ms of real
work plus ~8 ms of spin-waits on prep workers and flips, with heavy preemption by the other busy threads), and the
two-buffer present path turns anything above 16.7 ms into 33 ms. Next steps: make the prep workers sleep instead of
spinning (fewer preemptions), take the final-blit wait off the render thread (triple buffer / deferred present), and
reduce draw count per frame in glfix (merge consecutive draws with identical state).

## Update 2026-10-20: the real cause (CPU-visible GPU syncs) and what was fixed

Instruments added: engine profiler tree (`ptree:`), per-GL-call timing (`glcalls`), draw timeline (`slowdraws`), per-phase loop timing
(`gfxprof`), driver counters: forced buffer drains by call site, buffer renames, blit/clear/mipmap paths, back-pressure, scanout writer checks.

Findings (Jak 3 spawn scene, 1080p):
1. ~135 times per frame a CPU write to a buffer still used by queued draws (glBufferSubData/BufferData on index/vertex buffers)
   submitted the batch and waited for the GPU (13 ms of a 35 ms frame). Fix: buffer renaming (driver patch 31/32): the buffer gets
   fresh arena slots, the old ones are freed after the batch retires.
2. glGenerateMipmap on ~10 animated textures per frame drained the GPU each time (1 ms each) and printed a log line per call.
   Fix: GPU blit chain without drains, small levels on the GPU as well, no log line (patch 33, PS5_GPU_BLIT_MIN_PIXELS=1).
3. The software depth blit of the sun-glow probe (different formats, rejected anyway) drained the GPU every frame (5-6 ms).
   Fix: reject before draining (patch 41).
4. glClear of the window framebuffer (a scanout buffer) twice per frame had to wait for the previous flip, i.e. for a vblank, which
   aligned every frame start to the display (up to 16 ms stall per clear). Fix: skip window clears after the first frames
   (shim_patch_noclear.py; keepwindowclear.txt restores them). Present waits dropped from ~5 ms/frame to ~0.
5. Diagnostics themselves can stall the game: ps5_log writes block (UDP + file); a per-frame tree dump of thousands of lines
   collapsed the frame rate. Keep log volume low.

Result: Jak 3 spawn scene 27-30 fps -> 38-43 fps, CPU 18.4 -> 15.9 ms, forced syncs 135 -> ~7 per frame.

Not helping: 1/3 prep workers (3 workers: slightly worse), worker yield (worse), spinning instead of 1 ms sleeps (starves the loader
threads), buffer memory type 3, core pinning, dynamic resolution, adaptive flips.

Still open: one 7-9 ms hiccup per frame in a random render bucket (also visible as 7.8 ms outliers in the GPU trace): looks like the
render thread being descheduled; ~50 blits/frame from mip generation cost ~5 ms CPU; the final window blit still waits for a flip.
