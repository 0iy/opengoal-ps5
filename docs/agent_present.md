# Present path: async swap and triple buffering (agent "present")

Patch: `drv_patch55.py` (applies to `PS5_SRC`, default the live tree). Verified: patch applies and is idempotent on a private copy
(`~/present_src`), `ps5_screen.c` and `ps5_agc_runtime_backend.c` compile with the project flags (private outputs in `~/present_out`),
`ps5_egl.c` passes `-fsyntax-only` (its real build is the SDK's, not in this repo). NOT run on the console.

## 1. What the code does today (read in the source)

Config of the shipped build (`~/drv/rc.txt` line 4): `PS5_SCANOUT_HEIGHT=2160 PS5_DYNAMIC_SCANOUT PS5_GPU_PRESENT_BATCH PS5_MULTIDRAW_BATCH
PS5_DEFERRED_DRAW_BATCH`, `PS5_RENDER_ARENA_BYTES=0x10000000`. So a display slot is `PS5_SCANOUT_BYTES = 0x2000000` (32 MiB, the 2160p
capacity, also at 1080p), `PS5_SCANOUT_POOL_BYTES = 0x4000000` (64 MiB), arena offset 64 MiB, whole render pool 320 MiB (`ps5_screen.c:109-120`).

A frame already has more asynchrony than the task text assumes:

1. `eglSwapBuffers` (`ps5_egl.c` ~1140): `st_context_flush(... ST_FLUSH_END_OF_FRAME | ST_FLUSH_WAIT if swap_interval)` with callback
   `ps5_before_swap_flush` -> `ps5_context_queue_present` -> `ps5_agc_gate2_batch_present` (`ps5_agc_native_runtime.c` ~2290). That appends
   `set_flip(handle, buffer_index, mode, marker)` plus a new completion marker to the LAST batch entry: the flip is a GPU-tail flip, the CPU is
   not needed to issue it. `runtime_adaptive_flip_mode()` picks mode 1 (vsync) or 2 (hsync/immediate if the last frame was > 16.9 ms and adaptive is on).
2. `ST_FLUSH_WAIT` makes Mesa call `fence_finish` (`ps5_draw_batch_fence_finish`, ps5_screen.c ~12292): CPU spins until the batch of this frame retired.
   Then `ps5_screen_submit_lock` (ps5_screen.c ~150-170) = flush + `ps5_draw_batch_retire_locked(true)` (trace event 113 "submit_lock (full wait)",
   wait site 0 "batch-retire"). Because the game calls `SDL_GL_SetSwapInterval(1)` (`appmain.cpp:149`) this happens every frame.
3. `ps5_agc_gate2_present` (~2750) refuses to run with `runtime_pending_batches && swap_interval != 0` (so the full wait above is mandatory for
   interval 1). With the pool registered (`framebuffer_size >= FRAMEBUFFER_POOL_BYTES`, always true here) it only sets `runtime_gpu_present_deferred = 1`
   and returns: the flip itself is NOT awaited at swap.
4. The flip is awaited lazily: `runtime_video_prepare_draw` (~2540) calls `ps5_agc_gate2_wait_present()` before any command that writes the scanout pool
   (`ps5_agc_writes_scanout`, backend.c ~776, tests every MRT against the whole pool) -> `runtime_gpu_present_finish`: poll `get_flip_status` /
   `is_flip_pending` until `!pending && status[3] == marker`, sleeping 1 ms (`ps5_wsite_add(2)` = trace event 102 "wait flip"). Same wait in
   `ps5_screen.c:12521` (CPU access to the display target).
5. Only one flip can be in flight: the scalar `runtime_gpu_present_buffer`, `batch_present` fails if it is >= 0 and calls `runtime_video_wait_idle`, buffer index
   is checked `> 1`, EGL toggles `buffer_index ^= 1`, `register_buffers2(... buffers, 2 ...)` (~2635), `ps5_display_target_alias` accepts only index 1,
   `targets[2]`/`scanout[2]`.

Consequence: frame j+1 renders into the buffer that is on screen until flip j-1... precisely with 2 buffers frame j writes buffer j%2, which is displayed
until flip j-1 has executed, so the first scanout write of frame j must wait for flip j-1 (vsync after the GPU finished frame j-1). That is the "wait flip".
Plus the swap-time GPU wait (item 2) which prevents any CPU/GPU overlap across the swap.

## 2. (b) Async swap (cheap step): `PS5_ASYNC_SWAP=1`

Two-buffer layout unchanged. EGL computes `sync_swap = swap_interval && !async` and uses it for the `ST_FLUSH_WAIT` flag, the lock choice
(`ps5_screen_present_lock` = flush + non-blocking retire, which the interval-0 path already used) and the argument to `ps5_agc_gate2_present`.
The flip was already queued in the GPU tail, so nothing else is needed: the CPU returns from swap at once and starts frame j+1; its offscreen passes
overlap GPU frame j; only the final write into the scanout waits for flip j (same invariant as before).
Gain: the swap-time GPU wait (batch-retire + frame-complete tail, ~2-7 ms in the Jak 3 numbers). Works while CPU time per frame >= one vsync interval.
Not a gain when frames are short (< 16.7 ms): then the flip-j wait still quantises to vsync; that is what (a) removes.
Risk: pacing. Today swap blocks on GPU; afterwards the render thread is paced only by the flip wait and the 8 in-flight batch capacity. Input latency is at most
unchanged (still one flip in flight).

## 3. (a) Triple buffering with two flips in flight: `PS5_TRIPLE_BUFFER=1` (implies async swap)

### Numbers
- Slot = 0x2000000 B (32 MiB). Pool 2 slots 0x4000000 (64 MiB) -> **3 slots 0x6000000 (96 MiB)**. Offsets: slot0 0x0, slot1 0x2000000, slot2 0x4000000 (2 MiB aligned).
- Arena offset 0x4000000 -> **0x6000000**; arena size unchanged 0x10000000 (256 MiB); render pool 320 MiB -> **352 MiB** (0x16000000, < 4 GiB window assert).
  The layout change is unconditional (patch always allocates three slots); +32 MiB direct memory is the only cost with the switch off. If memory is
  tight: lower `PS5_RENDER_ARENA_BYTES` by 0x2000000.
- `register_buffers2` count 2 -> 3 (when the env is set): buffer 2 at framebuffer + 0x4000000. At 1080p only ~10 MB of each 32 MiB slot is scanned.
- Required hazard rule: with N buffers and round-robin frames, frame j writes buffer j%N, which stays on screen until flip j-N+1 has executed. A scanout write needs
  "outstanding flips <= N-2": N=2 -> 0 (today), N=3 -> 1. Queueing a flip needs the same (so at most 2 outstanding).

### Code (all in drv_patch55.py)
| Where | Change |
| --- | --- |
| `ps5_scanout.h:39` | `PS5_SCANOUT_BUFFERS 3u`, `PS5_SCANOUT_POOL_BYTES = BUFFERS * BYTES` |
| `ps5_screen.c:116` | `PS5_RENDER_ARENA_OFFSET = PS5_SCANOUT_BUFFERS * PS5_RENDER_TARGET_BYTES` (pool bytes follow from the header) |
| `ps5_screen.c:6013` `ps5_display_target_alias` | accept index 1..2, size check against 3 slots |
| `ps5_egl.c` | `targets[3]`, `scanout[3]` (create/destroy alias 2), `buffer_index = (buffer_index+1) % n` with n from weak `ps5_agc_gate2_scanout_buffers()`, `sync_swap` |
| runtime | new exported `ps5_agc_gate2_scanout_buffers()` (reads `PS5_TRIPLE_BUFFER` once, prints `[ps5-present] scanout buffers=N`), `runtime_present_wait(limit)`, `buffers[3]` + count in `runtime_video_acquire`, index checks `>= N` in `batch_present` and `present`, relaxed wait (limit 1) in `batch_present` and `runtime_video_prepare_draw`, strict wait (limit 0) stays in `ps5_agc_gate2_wait_present` (shutdown, CPU access, CPU-submitted flip), `fresh` flag so `present` does not wait for the flip its own swap just queued |

### Flip completion tracking
State: newest flip marker `runtime_gpu_present_marker`/buffer (existing scalars) and `runtime_flip_prev_marker` (older, 0 = none). `batch_present` waits to <= 1 outstanding, then shifts newest into prev and records the new flip.
`runtime_present_wait(limit)`: newest done when `!pending && status[3] >= marker` (clears everything); prev done when `status[3] >= prev && pending <= 1`; returns when
`limit>=1 && prev==0` or newest done. N=2 path (`runtime_gpu_present_finish`) is untouched and still used when the env is off.
**Assumption not verified:** `status[3]` (flipArg) is the argument of the last COMPLETED flip, flips complete in order, and `is_flip_pending` counts requested-not-yet-processed flips.
The existing code only used equality for the newest flip, so it never needed this. Every test is combined with `pending`, so a wrong reading can only make it wait longer... except the
prev test (`status[3] >= prev && pending <= 1`) if status[3] were "last submitted"; `PS5_PRESENT_LOG=1` prints `limit/pending/count/arg/cur/prev` on the first poll of each wait to check this first.
**Also unverified:** whether VideoOut accepts 2 queued flips from `sceAgcDcbSetFlip` without stalling the GPU command processor (queue-full behaviour).

### Render target choice without stalling
Round robin; no search. The back buffer for frame j is j%3 (EGL `buffer_index`, picked again by `ps5_validate_drawable` after the drawable stamp changes). No stall unless two flips are
still outstanding when the first scanout write arrives.

### Failure modes
- Tearing / use-after-flip: writing a buffer that is displayed or queued. Guards: limit-1 wait before every scanout-writing command (`ps5_agc_writes_scanout`), strict wait for CPU access.
  Wrong status semantics (above) is the main way to get this.
- Flip mode 2 (immediate) with a queued flip behind a vsync flip could reorder visually or tear: see section 5.
- Two outstanding GPU-tail flips and a CPU-submitted flip (explicit flush/readback frames): `present` forces strict wait (limit 0) before `submit_flip`, then uses the old path.
- Latency: CPU may run two flips ahead, +1 frame input latency vs. now.
- Shutdown/mode change: `shutdown_present` and `display_idle` use the strict wait/`buffer>=0` rule; they were not changed.
- Static data added: runtime `runtime_gpu_present_fresh` (int), `runtime_flip_prev_marker` (uint64), two function-local `static int` (buffer count, verbose log); egl one function-local `static int` (async).
  No arrays. If the RELRO crash appears, bisect by these.

## 4. Apply and build
```
wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && python3 drv_patch55.py && bash drv_cc_cache.sh && bash drv_cc_backend.sh && bash rebuild_all.sh"
```
The egl file is built by the SDK build, as for earlier egl edits (copy per `docs/SETUP_NEW_MACHINE.md:54`).
Proposed shim lines for `ps5shim/appmain.cpp` (not edited by me), same style as `flipmode.txt`:
`asyncswap.txt -> PS5_ASYNC_SWAP=1`, `triplebuffer.txt -> PS5_TRIPLE_BUFFER=1`, `presentlog.txt -> PS5_PRESENT_LOG=1`.

## 5. flipmode / adaptiveflip experiments (docs/PERF_ANALYSIS.md)
- Measured there: always-immediate flips (mode 2) or adaptive: 27 -> 32-35 fps, "tearing possible". Mechanism: mode 2 executes the flip at the next hsync instead of waiting for
  the vsync, so flip j completes earlier and the flip-j wait ends earlier. That is exactly the latency that triple buffering removes without tearing. The two are alternatives for the same problem.
- Conflict: mode 2 flips present a new buffer mid-scan; with a second flip queued behind a vsync flip the order/latching is unknown, and the "late frame -> mode 2" heuristic
  (`runtime_adaptive_flip_mode`, `PS5_VSYNC_STRICT` unset only when `adaptiveflip.txt` exists) would make the tear visible in exactly the frames triple buffering is meant to smooth.
  So: test triple buffering with the defaults (no `adaptiveflip.txt`, no `flipmode.txt` = mode 1). Do not combine for the first runs; combining later is a separate experiment.
- They do not conflict in code: the mode is only an argument of `set_flip` in `batch_present`; patch 55 does not touch it.

## 6. Test plan (main session, one run at a time, same scene each, Jak 3 spawn and Jak 2 city)
Order: baseline; `PS5_ASYNC_SWAP=1`; `PS5_TRIPLE_BUFFER=1 PS5_PRESENT_LOG=1` (short run to read the log); `PS5_TRIPLE_BUFFER=1`.
Boot checks: log line `[ps5-present] scanout buffers=3`, `[ps5-agc] present-open ... buffers=3`, `[ps5-gallium] display-alias index=2 offset=67108864`,
`shared-render-pool bytes=369098752 arena-offset=100663296`. No `scanout reuse before confirmed flip completion`, no `queued presentation failed`, no `present failed`.

`trace2json.py` events (names at line 14-15) that must move:
| Event | Baseline | async swap | triple |
| --- | --- | --- | --- |
| 113 submit_lock (full wait) | ~1 per frame, large | gone (0 calls from swap) | gone |
| 101 wait frame-complete | small | small | small |
| 100 wait batch-retire | includes the swap tail | drops by the GPU-tail latency | same as async |
| 102 wait flip | ~6-11 ms/frame, at the final blit | roughly the same or smaller | **near 0** when CPU frame < 33 ms; only when 2 flips outstanding |
| 112 backpressure | 3 ms | may rise a little (CPU runs ahead) | watch it; if it rises, `PS5_INFLIGHT_BATCH_CAPACITY` is next |
| frame time p50/p95 (`perfround.py`) | 31 fps, 24-26 ms | CPU frame time, less 33 ms quantisation | 17-20 ms frames stay 17-20 ms (no 33 ms steps); fps toward 1000/CPU-time up to 60 |
Success: p95 frame time no longer bimodal at 16.7/33.3; fps histogram not clustered at 30. Compare the sum "wait flip + submit_lock + batch-retire" per frame.

Tearing / use-after-flip detection:
1. `PS5_PRESENT_LOG=1`: `count` must advance by exactly 1 per presented frame and `arg` must be monotone; `pending` must never exceed 2; `cur`/`prev` markers must be in increasing order. If `arg`
   already equals `cur` while `pending>0` the status semantics assumption is wrong: stop.
2. Visual: a scene with continuous horizontal pan (Jak 3 spawn, turn the camera at constant speed) on a capture card or phone camera at 1/1000 s: a tear shows as a horizontal split with two time steps;
   a stale-buffer (use-after-flip) bug shows as a frame from 2-3 frames ago flashing (judder back and forth, not a split).
3. Counter check: `[ps5-gpu-present] frames=` at shutdown equals the number of rendered frames (the engine frame counter); flips lost or doubled show as a difference.
4. Run 5 minutes for stability (flip queue stall would show as the GPU `suspend`/hang, black screen, or `submission retirement failed`).
If wait-flip stays high with `PS5_TRIPLE_BUFFER=1` look at the log: `limit=1` waits with `pending=2` mean the game is GPU-queue-bound, not buffer-bound.

## 7. Not done / open
- Nothing is verified on hardware; status[3] semantics and the two-queued-flip behaviour of `sceAgcDcbSetFlip` are assumptions.
- The leaked `pipe_fence_handle` per `eglSwapBuffers` (the `fence` out-parameter is never released) exists today; unchanged.
- Allocation of the extra 32 MiB depends on direct memory availability; not checked.
- Dynamic scanout modes (1440p/2160p/120 Hz) were not considered beyond the 32 MiB slot (fits all modes).
