# drawcost: CPU cost per draw (agent report)

Files: `drv_patch56.py` (ps5_screen.c), `drv_patch57.py` (ps5_agc_native_runtime.c), `trace_stages.py`. Nothing here touched the console or
the live driver tree. Both patches were applied to a private copy of the live tree (`PS5_SRC`), applied twice (second run prints
"already patched"), and compiled with the project flags (`ps5_screen.o`, `ps5_agc_runtime_backend.o`, no errors, only the old Mesa
header warnings). They were **not run** on the console. Every gain figure below is an estimate unless it says "measured".

Line numbers refer to the live tree as read on 2026-10-23 (`ps5_screen.c` 18796 lines, `ps5_agc_native_runtime.c` 5736 lines).

## 1. What is measured

From `trace2json.py` on `perf_runs/jak2_t3.trace_13236_0.bin` (Jak 2) and `jak3_t3.trace_13336_0.bin` (Jak 3). The file `jak3_t6.trace_14804_0.bin`
is JSON, not a tracer binary, so `jak3_t3` was used instead.

| | Jak 2 city | Jak 3 |
|---|---|---|
| draws per frame | 1255 | 529 |
| glfix wrapper (pre/post) | 2.5 us/draw | 2.0 us/draw |
| Mesa state tracker | about 0 | about 0 (the -7.6 printed for Jak 3 is distorted by glGenerateMipmap time) |
| driver `draw_vbo`, all inclusive | 17.1 us/draw | 25 to 30 us/draw |
| job hand-over (`ps5_agc_gate2_run` on the render thread) | 0.7 us/draw | 3.4 us/draw (includes the spin) |
| async-collect spin | 4.63 ms/frame = **3.7 us/draw**, 627 waits/frame of 7.4 us | 2.19 ms/frame = **4.1 us/draw**, 296 waits |
| batch submit | 0.97 ms/frame, 52 batches | 0.87 ms/frame |

So of the 17 us in the driver for Jak 2, 3.7 us are the spin and 0.7 us the hand-over; about 12.7 us are state building on the render
thread. There is no per-function measurement of that 12.7 us in any log: the existing `[ps5-driver-sec]`/`[ps5-driver-my]` printf lines
go to stdout and are not in `perf_runs/*`. Patch 56 adds a tracer event that closes this gap (section 4).

## 2. Ranked costs per draw (static analysis plus the numbers above)

Only rank 1 is measured. Ranks 2 to 5 are estimates from counting calls, memory traffic and fences in the source; their order among
themselves is uncertain by design and `trace_stages.py` on a patched build will settle it.

| # | Cost | Where | Est. us/draw (Jak 2) | Why |
|---|---|---|---|---|
| 1 | Waiting for prep workers at the batch edge | `runtime_async_collect_one` `ps5_agc_native_runtime.c:1565-1580`, called by `runtime_async_drain` from `ps5_agc_gate2_batch_submit` `:1928`, `batch_present` `:2292`, and the compute path `ps5_agc_runtime_backend.c:903` | **3.7 measured** | 627 waits per frame for 52 drains: at each drain about half of the batch's jobs are not ready yet. The 2 workers run at about the producer's speed, so every batch edge waits for the lag (about 88 us per drain). Cause is worker-side, see 2a |
| 2 | Descriptor snapshot and flushes | `ps5_batch_copy_descriptors` `ps5_screen.c:11806` (3 pool takes `:11764`, 2 `memcpy`, 3 `struct pipe_resource` copies), `ps5_flush_descriptor_table` `:2673` called twice per draw (`:10743`, `:10805`, each 2 flush calls), vertex table flush `:10715`, `ps5_prepare_constant` `:3603` (memset of the bank, descriptor writes), `ps5_flush_gpu_data` `:2609` | 2.5 to 3.5 | about 6 flush calls per draw, each ends in `mfence` (`ps5_clflushopt_loop` `:2588`) and updates 4 atomics plus a 48-entry caller table. An `mfence` after clflushopt of dirty lines waits for the write-back, about 0.2 to 0.4 us on this memory system (assumption) |
| 3 | Texture descriptor preparation | `ps5_prepare_texture` `:4050-4600`, the big validity condition `:4262-4350`, descriptor encode, `ps5_flush_texture_backing` check `:2918` | 2 to 3 | per bound texture and stage, every draw: about 60 field compares, format/swizzle table lookups, 48-byte descriptor memset and encode. Jak 2 binds about 2 textures per draw (assumption) |
| 4 | gate2 setters and TLS | `:10824-10990` (about 25 setter calls) and `:11238-11262`, each into `ps5_agc_native_runtime.c`/`ps5_agc_runtime_backend.c` writing `runtime_draw_state` / `ps5_agc_draw_state`, which are `_Thread_local` and the backend is built with `-femulated-tls` (`drv_cc_backend.sh:7`, default `TLSFLAG`) | 1.5 to 2.5 | with emulated TLS every access to a `_Thread_local` is a call to `__emutls_get_address`; about 60 to 100 such calls per draw (hypothesis, not measured). Render-target loop `:10986-11111` and depth block `:11112-11225` add about 0.5 us |
| 5 | Vertex input and variants | `ps5_vertex_layout_from_state` `:14742` (memset about 450 bytes), two `ps5_select_shader_variant` `:15200` (linked list walk, 14 field compares and a 450-byte `memcmp` per variant), vertex descriptor loop `:10577-10717` (per element validation, `ps5_vertex_buffer_descriptor`), `ps5_encode_graphics_state` `:2290` (loops over all 16 viewports and scissors, `:2419-2459`) | 1.5 to 2.5 | the viewport loop alone is about 0.3 us because `PS5_ENABLE_VIEWPORT_ARRAY_CANDIDATE` is 0 and only slot 0 is ever read (`:10943`, `:10949`) |
| 6 | Batch bookkeeping | `ps5_multidraw_eligible` `:11641` (2 stages x 16 units), `ps5_batch_retain_resources` `:11862` (about 12 `pipe_resource_reference` = atomic inc now and dec at retire), `ps5_deferred_mutex` lock/unlock, `ps5_try_deferred_draw` `:12556` | 1 to 2 | |
| 7 | Struct copies into the job | `ps5_agc_gate2_run` `ps5_agc_native_runtime.c:1637-1638` (`runtime_draw_inputs` about 1.4 KB, backend state about 0.4 KB) and again in the worker `:1537-1538` | **0.1** | not worth touching: about 2 KB at cache speed is under 0.1 us, and the worker copy is not on the render thread |

Not in the table because it only matters for Jak 3: `ps5_try_multi_draw_batch` does a `printf` per `glMultiDrawElements` call
(`:11990`, 72 per frame) and blocks on `ps5_screen_submit_lock`. Where stdout goes on the console is unknown to me.

### 2a. Why rank 1 is a worker cost (the important finding)

Per draw the worker does (`runtime_prepared_work_clear` about `:1127`, `runtime_prepared_work_publish` `:1132-1143`, call sites `:4141-4146`
and `:5199-5204`):

- `memset(memory + 0x4000, 0, 0x4000)`: 16 KiB zeroed, so all 256 lines are dirty;
- `flush_gpu_data(memory + 0x4000, 0x4000)`: 256 lines flushed, plus the command words, as 3 separate calls with an `mfence` each;
- `flush_gpu_data` is `util_flush_inval_range` (`:3012-3016`). The screen driver already knows that Mesa reports CLFLUSHOPT missing on the
  PS5 (comment at `ps5_screen.c:2599`), so Mesa takes its plain `clflush` path: one serialising `clflush` per line.

1255 jobs x 16 KiB = about 20 MB per frame of zero write-back through `clflush`. This matches the "flush volume 40 MB per frame" in
`PLAN_60FPS.md`. If a `clflush` costs 30 to 50 ns, that is 10 to 16 ms of worker time per frame, 5 to 8 ms per worker, which is the size of
the lag the producer sees at every drain. This is arithmetic from the source plus the flush counters, **not measured per job**.
It would also be consistent with 3 workers not helping (PERF_ANALYSIS) if the flushes contend for the same memory path (a guess).

Consequence for planning: every microsecond the render thread saves is only visible while the workers keep up. After patch 57 the
workers get cheaper; if the spin does not fall, the worker path (16 KiB clear) is the next target.

## 3. What each patch changes

All behaviour is **off by default**. Both patches read an environment variable once.

### drv_patch56.py (ps5_screen.c), env `PS5_DRAWCOST` (bit mask)

| Bit | Change | Estimated gain | Risk |
|---|---|---|---|
| 1 | `ps5_encode_graphics_state` encodes viewport/scissor slot 0 only when `PS5_ENABLE_VIEWPORT_ARRAY_CANDIDATE` is 0 (verified: slots 1..15 are read only under that macro, `:10937`; the other consumers use `[0]`) | 0.3 us/draw | very low; slots 1..15 of the stack struct become uninitialised but unread |
| 2 | descriptor flushes inside `ps5_draw_vbo_locked` (vertex table `:10715`, VS table `:10743`, FS table `:10805`) use CLFLUSHOPT with no `mfence` each; one `mfence` right before the hand-over (before `*submitted = true`). Falls back to the old path when cpuid has no CLFLUSHOPT | 1 to 2 us/draw (5 of about 6 fences removed; assumption on fence cost) | low. The fence is placed before the draw becomes visible to the worker or the GPU; an early error return skips the fence but the draw is then not submitted, and the retry path re-flushes with the old function. Statistics counters are still updated, the `flush caller` table is not (new call site is not recorded) |
| 4 | no `printf` per multi draw | 72 printf per frame in Jak 3 (unknown cost) | none |
| always | trace event 130 per draw, only when the shim tracer is armed (`ps5_driver_trace_hook` set): `dur` = whole call in ns, `a` = 6 stage times, 10 bits each, 100 ns units | measurement only | cost is one clock read and one event per draw while tracing |

Stage boundaries of event 130 (the existing `ps5_ck[]` checkpoints): bounds and index scan; framebuffer sample count; state encode, variants,
vertex descriptors; prepare (constants, textures, flushes); gate2 setters, packages, targets, depth; `ps5_agc_gate2_run`.

Statics added: two function-local `static int` (`ps5_dc_flags`, `ps5_dc_defer_fence`), same pattern as the existing `static int skip = -1`.
No arrays. If the app crashes at start (see the patch 45 pitfall) remove these two first.

Patch 56 touches the head of `ps5_flush_descriptor_table`; it deliberately does not match the `full = getenv(...)` line that
`drv_patch52.py` edits, so the two apply in any order (checked: patch 52 then 56 then 57 applies cleanly on a copy of the live tree, which does not have 52 yet).

### drv_patch57.py (ps5_agc_native_runtime.c), env `PS5_RT_FAST_FLUSH`

- `flush_gpu_data` (the runtime's, used by the workers) uses a CLFLUSHOPT loop plus one `mfence` instead of `util_flush_inval_range`, when cpuid
  reports CLFLUSHOPT (same test as `ps5_fast_flush`).
- `runtime_prepared_work_publish` issues its three flushes without fences and fences once.
- Expected: worker time per job falls (clflushopt lines overlap, clflush lines serialise), the async-collect spin falls from 4.6 ms toward
  the lag of one job. Honest range: 0 to 3 ms per frame. If it is 0, the worker bottleneck is something else (see 5.4).
- Risk: low. Semantics equal (flush then fence). Only the instruction changes. One function-local `static int`.
- Rebuild: `bash drv_cc_backend.sh` (runtime) as well as the screen build. Both patches work separately.

### Proposed shim lines (not applied; `ps5shim/appmain.cpp`, next to the `nomultidraw.txt` line)

```cpp
{ struct stat nf; if (stat("/data/opengoal/config/drawcost.txt", &nf) == 0) setenv("PS5_DRAWCOST", "7", 1); }  // drv_patch56, bit mask 1+2+4
{ struct stat nf; if (stat("/data/opengoal/config/rtfastflush.txt", &nf) == 0) setenv("PS5_RT_FAST_FLUSH", "1", 1); }  // drv_patch57
```

For single-bit tests, edit the number in the first line (1, 2 or 4).

## 4. Test plan

Same scene, same build, one run at a time, `trace.txt` armed (as for `jak2_t3`, `jak3_t3`), at least 10 s of steady state.

1. Build 0: patches 56 and 57 applied, no flags. Run `python trace2json.py <bin> -` and `python trace_stages.py <bin>`. This is the
   baseline and gives the first real per-stage numbers (us per draw and ms per frame for the six stages). Ranks 2 to 5 should be re-sorted from it.
   Compare against `jak2_t3` (17.1 us driver, spin 4.63 ms) to confirm the build with no flags does not change anything.
2. `PS5_RT_FAST_FLUSH=1` only. Watch: `wait async-collect` ms per frame (target below 2), frame time, `driver draw_vbo` us/draw.
3. `PS5_DRAWCOST=1`, then `=2`, then `=7`, each alone on top of step 1's best. Watch `prepare` stage (bit 2 targets it) and the `state+variants` stage (bit 1).
4. Pass criteria per run: per draw us for the driver (trace2json "per draw" line), async-collect spin ms/frame, average frame time, and no
   change in the draw count per frame.
5. Visual check: capture the same scene with `shotseries.py` for baseline and for the best combination, then
   `python shotdiff.py shots/A_0.png shots/B_0.png --thresh 16 --heat shots/A_B_0.png` (tool from `docs/agent_syncdbg.md`; it was not checked
   here). First measure the noise floor with two baseline captures. Expected diff: none beyond noise. A visible
   change with bit 2 or `PS5_RT_FAST_FLUSH` means a missing flush (garbage descriptors or stale command words): then run with `PS5_SYNC_DEBUG` for comparison.
6. Crash at start: remove the new statics (list above) one change at a time.

Expected totals if everything works (estimate): Jak 2 driver 17 us to about 12 to 13 us per draw, frame time down by 4 to 6 ms, so about 31 fps
to 36 to 38 fps; Jak 3 smaller. This is not a promise: the 3.7 us spin may stay if the workers stay slow.

## 5. Not implemented: designs and invalidation conditions

These are the larger gains. I did not write them: without per-stage numbers it is unclear which pays, and a wrong cache is a visual glitch.
Do them after step 1 of the test plan shows which stage dominates.

### 5.1 Graphics state cache (stage "state")
Cache the result of `ps5_encode_graphics_state` (+ the matching gate2 setter arguments) in `struct ps5_context`.
Invalidate (bump a counter) in: `ps5_bind_blend_state`, `ps5_bind_rasterizer_state`, `ps5_bind_depth_stencil_alpha_state`,
`ps5_set_blend_color`, `ps5_set_stencil_ref`, `ps5_set_sample_mask`, `ps5_set_min_samples`, `ps5_set_scissor_states`, `ps5_set_viewport_states`,
`ps5_set_framebuffer_state` (also changes `nr_cbufs`, `width`, `height`, zsbuf), and anything that frees a blend/rasterizer/dsa object
(`ps5_delete_fixed_state`), because the key would be a pointer. Also bound by the draw: `context->framebuffer.nr_cbufs` read at encode time.
Conservative rule: compare a 64-bit generation, never pointers alone.

### 5.2 Vertex layout and variant cache (stage "state+variants")
Key: (`context->vs`, `context->vertex_elements` pointer, vertex-element generation, `primitive_type`, rasterizer `flatshade_first`,
fs->nir inputs) -> (`vs->active`, `fragment variant`). Invalidate on: `ps5_bind_vs_state`, `ps5_bind_fs_state`, `ps5_bind_vertex_elements_state`,
shader delete, `ps5_set_framebuffer_state` (fragment exports depend on formats and sample count), `ps5_bind_blend_state` (alpha_to_one),
`ps5_bind_rasterizer_state` (multisample, smooth), `ps5_set_min_samples`, and geometry/tessellation bind. `shader->active` is written by
`ps5_select_shader_variant`, so the cache must also be invalidated when anything else selects a variant on the same shader (blitter, compute).
Cheaper first step: move the matching variant to the front of `shader->variants` (only a list reorder, no key needed).

### 5.3 Texture descriptor reuse (stage "prepare", rank 3)
Per (stage, unit) remember the last encoded 48-byte descriptor plus the key (sampler view pointer, sampler state pointer, `texture->data`,
`texture->level_stride[0]`, `texture->texture_publication_epoch`, view levels/layers, texture buffer size). Invalidate when: the sampler
view or sampler is rebound or destroyed (`ps5_set_sampler_views`, `ps5_bind_sampler_states`, `ps5_sampler_view_destroy`,
`ps5_sampler_view_release`), the texture is reallocated/renamed or staged (depth staging, packed stencil staging, buffer rename),
mipmaps regenerated (`ps5_generate_mipmap`), `ps5_texture_subdata`, or a framebuffer attachment alias changes. The descriptor must still be written into
the new per-draw snapshot (a 48-byte memcpy), so the saving is the validation and encode, not the flush. High risk of stale descriptors; do last.

### 5.4 Worker side: reduce the 16 KiB per job
After patch 57, if the spin remains: the clear and flush of `memory+0x4000..0x8000` is mostly unused (the prepared path uses about 0x5000..0x5110,
0x6000, 0x6ff0 marker, 0x7000 and 0x7800 register tables plus the user data at 0x4000..0x4900). Flushing only the written extents needs the
exact GPU-read extents of that page, which I did not establish; do not guess. Also try `WORKERS=3` together with patch 57 (it was
neutral/worse before only because every worker was slow on flushes).

### 5.5 Emulated TLS (rank 4 hypothesis)
Build the backend with a native TLS model (`TLSFLAG=` empty in `drv_cc_backend.sh`) only if the platform supports it; the script's default
is `-femulated-tls`, presumably for a reason (linker script `ps5-pie.ld`, the patch 45 crash). Safer code-level alternative: in each
setter fetch `&runtime_draw_state` once, and in `ps5_draw_vbo_locked` build the whole `runtime_draw_inputs` in a stack struct and make one
call that stores it. Not done: it touches about 25 functions.

## 6. Open questions

- Real cost of one `mfence` after dirty clflushopt and of one `clflush` on this CPU: not measured; the estimates assume 0.2 to 0.4 us and 30 to 50 ns.
- Where does the process stdout go on the console (cost of the per-multidraw printf)?
- Is the worker bottleneck really the flush? Patch 57 plus the unchanged `trace_stages.py` answers it in one run.
