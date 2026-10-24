# agent multidraw: async multi-draw and in-flight queue depth

Files: `drv_patch53.py` (async multi-draw + flush-cause trace event), `drv_patch54.py` (queue sizes as compile-time defines),
`multidraw_report.py` (read-only trace report). Nothing here touched the console, the live driver tree or existing repo files.
Both patches were applied twice (idempotent) to a private copy (`~/multidraw_work/src` in WSL) and both objects compiled
(`ps5_screen.o`, `ps5_agc_runtime_backend.o`) in four size configurations without errors. Nothing was run on the console.

## Incident to know about first

I ran `python trace2json.py jak3_t7.trace.bin jak3_t6.trace.bin` by mistake (second argument = output path). **That overwrote
`perf_runs/jak3_t6.trace_14804_0.bin` with a 140 MB Chrome-JSON of the t7 trace.** The t6 binary trace is gone (untracked file,
no backup). t6 console/udp/summary files are intact, and the t6 per-frame numbers I read before it happened are quoted below.
If t6 raw events are needed again, re-run the t6 config. Do not use that file; `multidraw_report.py` refuses it (bad magic).

## 1. What the traces say (verified, from jak3_t7 = nomultidraw, 362 frames)

`python multidraw_report.py perf_runs/jak3_t7.trace_15093_0.bin`:

| metric | value |
|---|---|
| batch submits per frame | 128.8 |
| draws per batch (glfix wrapper draws / submits) | 4.1; 50% of submits have 0 draws since the previous submit, 96% have <= 16 |
| submits caused by the multi-draw refusal (event 114, flags 0x40401 = multi, triangles, 32-bit index) | **70.8 per frame = 55%** |
| other submits (framebuffer change, pipe flush, barrier, full batch) | 57 per frame (cause not yet traced, see patch 53 event 116) |
| backpressure waits | 0.94/frame, mean 5.9 ms, **max single wait 8.0 ms** |

Correction to the brief: the "single events up to 14.8 ms" are two waits (about 7 ms each) in one frame. Per-frame
aggregation in `trace2json.py` sums them; no single backpressure wait in t7 exceeds 8.0 ms (282 of 362 frames have one,
55 have two). The waits cluster at 6.6 to 8.0 ms.

### Why the refusal flush matters

`ps5_try_deferred_draw` (ps5_screen.c, `num_draws != 1` branch, about line 12580) calls `ps5_draw_batch_flush_locked()` and
returns false for every multi-draw. With `PS5_NO_MULTIDRAW` the call then goes to `util_draw_multi`, whose sub-draws are
deferred normally. So `nomultidraw` removes the full wait but **still closes the open batch at every glMultiDrawElements**
(72 per frame in Jak 3). That is the 129 instead of about 57 batches per frame, and it is the "four times as many flushes" seen in
Jak 2. The flush is not needed for correctness: every sub-draw either joins the batch or is refused by the same function, which
flushes itself (or goes the immediate path, which flushes in `ps5_screen_submit_lock`).

### Is the GPU really 15 ms behind in bursts?

No, not for a single wait. What the data supports:
* Single waits are 6.6 to 8.0 ms. The gputrace run `jak3_fix` (flags gputrace, nomipcpu, nomultidraw, close to t7) shows per 3 s
  window about 128 command groups of >= 3 ms (813 ms of 1295 ms total GPU-attributed time, mean 6.3 ms, top values 7.8 to 8.0 ms)
  and about 17.7k groups under 3 ms (about 3 ms per frame in sum, mean about 27 us). So the GPU load per frame is: roughly one heavy
  group of 6 to 8 ms plus about 118 tiny groups. GPU busy time is about 8.6 ms per frame (gputrace excludes idle gaps), far below
  the 19.4 ms frame. The GPU is not saturated; the CPU waits for one slow group.
* Why the CPU waits for it: the queue is 8 batches. At 129 batches per frame the CPU produces a batch every about 93 us
  (12 ms thread CPU / 129), so 8 batches hold only about 0.75 ms of CPU lead. A 7 ms group at the head of the queue blocks the CPU
  after 0.75 ms. With the multi-draw refusal flush gone (about 57 batches, about 210 us each) 8 batches cover about 1.7 ms; 16 about
  3.4 ms; 32 about 6.7 ms.
* Open: the ceiling around 7.8 to 8.0 ms on many different draw indices in gputrace is suspiciously constant. It may be one fixed
  latency (e.g. a group that waits for a flip/label, or the glGenerateMipmap compute) rather than load. The traces cannot tell.
  `gputrace` distorts timing (about 10 fps), so use it only to identify the group, not for the fps comparison.

## 2. Part 1: PS5_ASYNC_MULTIDRAW (drv_patch53.py)

Design: in `ps5_draw_vbo`, before `ps5_try_deferred_draw`, if env `PS5_ASYNC_MULTIDRAW` is set and the call is a multi-draw
(num_draws > 1, not indirect, no legacy primitive conversion), loop over the sub-draws and call
`ps5_try_deferred_draw(base, info, drawid_offset + (increment_draw_id ? i : 0), NULL, &draws[i], 1)`. That reuses everything:
one descriptor snapshot per sub-draw (`ps5_batch_copy_descriptors`), batch retention (`ps5_batch_retain_resources`), the same
`ps5_multidraw_eligible`, the `PS5_MULTIDRAW_BATCH_CAPACITY` flush, the occlusion-query handling, owner change flush. Count-0
sub-draws are accepted as no-ops (existing behaviour). If a sub-draw is refused (it has already flushed, as for a refused single
draw) the remaining sub-draws go to `util_draw_multi`, which is the pre-patch path. A non-zero `last_draw_status` stops the loop.
`ps5_try_multi_draw_batch` is never reached when the flag is set (so `nomultidraw` is irrelevant then). Flag unset: byte-identical
behaviour. New static data: one function-local `static int` (cached getenv). No new arrays.

Also in patch 53: trace event **116** in `ps5_draw_batch_submit` (framebuffer-change, pipe flush, barriers), arg = return
address of its caller, so flush causes can be counted (`multidraw_report.py`). `ps5_draw_batch_submit` became `noinline`.
Event 116 is emitted only when the tracer hook is installed.

### Async multi-draw versus nomultidraw fallback

Same sub-draw semantics and the same per-draw cost (snapshot + retain + `ps5_draw_vbo_locked`, about 17 us driver per draw).
The difference is only the flush at the multi-draw boundary:

| | sync multi-draw (default) | nomultidraw | PS5_ASYNC_MULTIDRAW |
|---|---|---|---|
| full GPU wait per multi-draw | yes (113: 2.05 ms/frame, 75 per frame in t6) | no | no |
| batch flush per multi-draw | yes, plus retire | yes (70.8 per frame in t7) | no |
| batches per frame (Jak 3) | 72.5 (t6) | 128.8 (t7) | expected about 58 |
| backpressure per frame | 2.99 ms (t6) | 5.54 ms (t7) | expected lower (more CPU lead per slot) |
| batch submit per frame | 1.07 ms (t6) | 2.33 ms (t7) | expected about 1 ms |

Verdict: the async version is better than the nomultidraw fallback on every axis except that its benefit is an estimate until
measured: it keeps the full-wait removal and removes the flush that nomultidraw adds. The nomultidraw gain (+8 fps) is
real, and the async version should keep it and reduce the 2.3 ms submit and part of the backpressure. Risk: batches become larger, so
the first draws of a batch reach the GPU later (the GPU idles at the start of a pass). I do not expect this to matter because
framebuffer changes still flush.

## 3. Part 2: batch size and queue depth (drv_patch54.py)

### What limits batch size (read in ps5_screen.c)

`ps5_draw_batch_flush_locked` is reached from:
1. the multi-draw/ineligible refusal in `ps5_try_deferred_draw` (about 12580 to 12612): 70.8 per frame in Jak 3 (above);
2. `ps5_draw_batch_submit` (about 320): `ps5_set_framebuffer_state` when the state changes (13526), `ps5_flush` (9398, 9404),
   `ps5_memory_barrier` (9436, only when not compute-only), `ps5_texture_barrier` (9449). Jak 3 renders many small offscreen
   targets (about 6 clears of 128x128 and 8 blitter colour ops per frame in the t7 summary), so framebuffer changes are many;
3. batch full: `ps5_deferred.count == PS5_MULTIDRAW_BATCH_CAPACITY` (12663, 16638). Rare: only 516 of 46.6k batches in t7 had
   more than 64 draws. The 256 limit is not what limits the batch size;
4. `ps5_screen_submit_lock` (every immediate-path draw, query begin/end, timestamp, drain): flush plus full retire. 1 per frame in
   t7 (caller 0xb7077f), so nothing to gain there;
5. `ps5_draw_batch_drain_buffer` when a CPU access overlaps the open batch: 0 per frame in t7 ("0 forced submit+GPU wait").

Backpressure occurs when `ps5_inflight_count == PS5_INFLIGHT_BATCH_CAPACITY` inside the flush (12237): the CPU blocks on the oldest
batch (`ps5_draw_batch_retire_one_locked(true)`); the runtime has the same limit in `ps5_agc_gate2_batch_submit` (returns -1 if
full) so the two arrays must have the same size. Slot arrays in the runtime are indexed by the same two constants.

### Options, least risky first

A. **PS5_ASYNC_MULTIDRAW (patch 53), no size change**: removes 55% of the batches. Runtime switch, no static data. Do this first.

B. **16 batches x 128 draws (static-neutral)**: `-DPS5_INFLIGHT_BATCH_CAPACITY=16u -DPS5_MULTIDRAW_BATCH_CAPACITY=128u`.
   Doubles queue depth, halves the draw capacity per batch; every array sized by the product stays the same size. Measured with
   `nm -S`/`size` on the compiled objects:

   | config | ps5_inflight | ps5_deferred | runtime_pending | runtime_work_free | async jobs | total bss screen+backend |
   |---|---|---|---|---|---|---|
   | 8 x 256 (today) | 1,858,112 | 232,264 | 131,200 | 49,152 | 503,808 (0x7b000) | 3,349,955 |
   | 16 x 128 | 1,864,832 | 116,552 | 131,328 | 49,152 | 251,904 (0x3d800) | 2,980,995 (-369 KB) |
   | 32 x 128 | 3,729,664 | 116,552 | 262,656 | 98,304 | 251,904 | 5,026,307 (+1.68 MB) |
   | 16 x 256 | 3,716,224 | 232,264 | 262,400 | 98,304 | 503,808 | about +2.0 MB |

   Draw capacity 128: 516 of 46.6k batches exceeded 64 draws in Jak 3; Jak 2 (about 1250 draws per frame) would hit the 128 limit
   about 10 times per frame instead of 5, and each of those is a cheap non-waiting flush. Risk: `RUNTIME_ASYNC_JOBS` (the
   producer-to-worker job ring in the runtime) is tied to the same constant, so its depth halves from 256 to 128; if the render
   thread produces faster than the 2 workers consume it may stall on the ring (watch "wait async-collect", currently 1.8 to 2.5 ms
   per frame). If that regresses, use option C.

C. **32 x 128 or 16 x 256**: about +1.7 / +2.0 MB .bss (zero pages, only touched when used; `ps5_inflight` copies only the live bytes
   of a batch). Largest effect on backpressure (about 6.7 ms of CPU lead at 32 with 57 batches per frame), costs more
   in-flight resources (descriptor snapshots and retained textures are held longer, more latency between input and picture, up to
   32 batches' worth; the rename/reclaim spare table `PS5_SPARE_MAX` 4096 is unchanged and could fill earlier).

All of this is compile-time (`EXTRA=`) and is a no-op by default. Both `ps5_screen.o` and `ps5_agc_runtime_backend.o` must be
built with identical values; a mismatch only compiles but corrupts indexing.

### Pitfall 5 (new statics)

Patch 53: no new arrays (one function-local int). Patch 54: no new statics; with option B the total .bss goes down by 369 KB; with
C it goes up by 1.7 to 2.0 MB, which is the exact kind of change that moved the RELRO/iostream layout in patch 45. Apply and test
in this order: (1) patch 53 alone, (2) patch 54 + B, (3) patch 54 + C. Never both at once.

### Build note I hit

`ps5_agc_runtime_backend.c` includes `ps5_screen.h` through `-I~/gl/src/ps5-opengl/src/gallium/ps5` from `~/drv/rc.txt`
(and `~` is a symlink to the live tree). A private-copy compile of the backend silently uses the **live** header unless
`rc.txt` is also redirected. I redirected a copy of rc.txt to verify the sizes above. On the live tree this is correct as is.

## 4. Apply and test (main session)

```
wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && python3 drv_patch53.py && python3 drv_patch54.py"
wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && bash drv_cc_cache.sh && bash drv_cc_backend.sh && bash rebuild_all.sh"
# option B build instead:  EXTRA='-DPS5_INFLIGHT_BATCH_CAPACITY=16u -DPS5_MULTIDRAW_BATCH_CAPACITY=128u' bash drv_cc_cache.sh
#   (drv_cc_cache.sh overwrites EXTRA; edit its export line to append, or call drv_cc.sh with the full EXTRA, and same for drv_cc_backend.sh)
```
Note `drv_cc_cache.sh` sets `export EXTRA=...` itself, so for the size variants append to that string or run `drv_cc.sh` directly.

Shim (proposed line, not edited): in `ps5shim/appmain.cpp` next to nomultidraw:
`{ struct stat nf; if (stat("/data/opengoal/config/asyncmultidraw.txt", &nf) == 0) setenv("PS5_ASYNC_MULTIDRAW", "1", 1); }`
and add `"asyncmultidraw"` to `FLAGS` in `perfround.py` (line 20).

Runs (Jak 3 gameplay, same scene as jak3_t6/t7, always with `trace`, 190 s as in t7), one per build:

| run | flags | build |
|---|---|---|
| a | (none) | patched build, default behaviour; must reproduce t6: 43 fps, submit_lock 2.05 ms |
| b | nomultidraw | patched build; must reproduce t7: 51.5 fps |
| c | asyncmultidraw | patched build, option A |
| d | asyncmultidraw | build with 16 x 128 |
| e | asyncmultidraw | build with 32 x 128 (only if d is stable) |
| f | asyncmultidraw gputrace | patched build, only to identify the 7 to 8 ms group, not for fps |

Then repeat c on Jak 2 city (compare with its nomultidraw run: 3 to 5 ms backpressure, 4 ms submit).

For each: `python trace2json.py <trace> -` and `python multidraw_report.py <trace>`.

### Numbers that must move (c versus b, the expected direction and size)

| number | b (t7) | c expected | how to read |
|---|---|---|---|
| submit_lock (full wait), ms/frame | 0.00 (1 call) | 0.00, must stay 0 | trace2json row 113 |
| batch submit, ms/frame (calls) | 2.33 (129) | about 1.0 (about 58) | row 111 |
| submits caused by event 114 | 70.8/frame | 0 | multidraw_report "submit causes" |
| draws per batch | 4.1 | about 9 | multidraw_report |
| backpressure wait, ms/frame (events) | 5.54 (0.94) | lower; if unchanged the queue depth (d, e) is the lever | row 112 |
| wait batch-retire | 5.53 | follows backpressure | row 100 |
| draw / driver draw_vbo, us per draw | 20.2 / 17.7 | unchanged (+- 1 us), if it rises the per-sub-draw snapshot is more expensive than in nomultidraw (it should not be, same code) | trace2json "per draw" |
| fps | 51.5 | > 51.5 | summary |
| `[ps5-inflight] peak=` in the console log | 8 | 8 (still reaches capacity) | console log |

d versus c: backpressure ms/frame should fall roughly in proportion to the added CPU lead (expectation: 16 x 128 about 1.7 ms to
3.4 ms of lead covers part of a 7 ms group, 32 x 128 most of it); `wait async-collect` must not rise (job ring is 128 in d and e);
`[ps5-inflight] peak` should exceed 8. If fps does not rise but the backpressure time moves to `wait flip` / `wait frame-complete`,
the GPU (or the vblank) is the real limit and depth is exhausted.

### Image check (picture must not change)

Compare screenshots (`shot.py`) at fixed spots in Jak 3 and Jak 2 city with run a (frame-pacing and order are unchanged; draw
order within a multi-draw is identical to `util_draw_multi`, which nomultidraw already exercises). Look specifically at things drawn
with glMultiDrawElements (72 per frame in Jak 3: probably foreground/foliage/particles) and for flicker (resource retention
bug) and gl_DrawID-dependent shading. A mismatch only in c but not in b would point to my loop (drawid offset or status handling).

## 5. Risks and unverified points

* Not run anywhere (no console). Compile-only verification, four configurations.
* Retention memory: the async path holds more descriptor snapshots in flight (`ps5_descriptor_take` pool) because multi-draws no
  longer retire synchronously; the pool class is the same as for single deferred draws.
* `ps5_try_deferred_draw` is called per sub-draw: its `ps5_my_report()` and trace overhead repeats; negligible.
* Event 116 relies on `__builtin_return_address`; the address must be mapped to a function with the link map of the build.
* The explanation for the constant 7.8 to 8.0 ms group is a hypothesis (open question above).
* t6 raw trace destroyed by me (see top). t6 numbers in this document are from the stdout I captured before it happened.
