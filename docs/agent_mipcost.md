# Agent mipcost: where glGenerateMipmap time goes (Jak 3, 4K output) and what can be cut

Files: `drv_patch59.py` (driver, env `PS5_MIPFAST`), `trace_mip.py` (analysis of a trace). Nothing was run on the console.
Compile-checked: `PS5_SRC=~/tmp_mipcost_src python3 drv_patch59.py` on a private copy of the live tree (second run prints
"already patched"), then the `drv_cc_cache.sh` clang line with the private path and output `~/tmp_mipcost_out/ps5_screen.o`:
no errors, no new warnings. (The copy lives in `~/tmp_mipcost_src`, not `/tmp`: WSL wipes `/tmp` between `wsl -e` calls.)

## 1. Main finding (measured, `trace_mip.py` on 4 traces)

The 2.9 ms of `jak3_r4k` is **2.2 ms backpressure wait and only 0.68 ms CPU**. The wait is the 8-slot in-flight batch queue
being full when the mip burst arrives (batch flush -> `ps5_draw_batch_retire_one_locked(true)`, `ps5_screen.c:12337-12342`, event 112).

| trace (all 9 calls and 15.1 blit draws per frame) | glGenerateMipmap ms/frame | backpressure inside | CPU inside | frame total backpressure (trace2json) |
| --- | --- | --- | --- | --- |
| jak3_r4k | 2.92 | 2.23 | 0.68 | 2.72 |
| jak3_r1440 | 1.76 | 1.11 | 0.65 | 2.30 |
| jak3_q16x128 | 1.90 | 1.29 | 0.61 | 2.25 |
| jak3_q1 | 0.76 | 0.17 | 0.59 | 3.44 |

The CPU part is constant (0.6 to 0.7 ms); the wait part moves between runs, while the frame-wide backpressure stays 2.2 to 3.4 ms.
Assumption (inferred from these four traces, not proven): the wait is not caused by the mips, it lands on the first burst of
submits after the CPU got ahead of the GPU; remove the mip submits and the same wait shows up at the next submit. So CPU savings in
glGenerateMipmap do not turn into fps one to one; only fewer batches or less GPU work in flight can.

Call distribution in r4k (1805 calls): 1498 single-level calls cost 54 us each (no wait), 7-level chains 178 us (q16x128, no wait),
the 306 calls that include a backpressure wait cost 1.5 to 1.8 ms each. `jak3_r4k` per frame: 7.5 single-level calls plus about 1 chain.

## 2. Ranked cost table (CPU, per single-level call of 52 us; from the nested events of a typical call in q16x128)

Timeline of one call (us from call start; events 116/111/103/122/121 are existing):

| # | step | us | where |
| --- | --- | --- | --- |
| 1 | final submit at the framebuffer restore, includes waiting for the prep worker to finish the blit draw (async-collect 17 us) | 20 | `ps5_set_framebuffer_state` -> `ps5_draw_batch_submit()` (`ps5_screen.c:13650`), runtime `runtime_async_collect_one` |
| 2 | submit of the game's pending batch at the first framebuffer switch (async-collect 7 us) | 11 | same site; this batch would otherwise have continued, so the mip call cuts it |
| 3 | checks, `create_sampler_view`, 19 `util_blitter_save_*`, blitter set-up before the framebuffer switch | 8 | `ps5_blit_gpu_color` (`:8100`) |
| 4 | `ps5_draw_vbo` for the blit draw (state build 4 us, descriptor copy 1 us) | 7 | event 122 |
| 5 | blitter state between submit and draw (2 us) and restore (about 1 us), rest | 6 | |

56 % of the CPU time is batch cut plus worker round trip (rows 1 and 2); that is structural: every mip level renders into a
different framebuffer, and a framebuffer change closes the fixed-framebuffer batch.
In a 7-level chain each level costs only 25 us (the first submit happens once).

## 3. Ideas from the task and why most are not worth it (read in the source)

- **Cache pipe_surface per (resource, level):** nothing to cache. In Mesa 26.2 `pipe_framebuffer_state.cbufs[]` embeds
  `struct pipe_surface`; `util_blitter_default_dst_texture` fills a stack struct, `ps5_blit_gpu_color` never calls `create_surface`.
- **Cache the sampler view:** `ps5_create_sampler_view` (`:17693`) is a validation plus `calloc` plus a resource reference;
  `ps5_sampler_view_destroy` a `free`. Well under 1 us. A cache would need invalidation for no gain.
- **One state save/restore per chain:** not possible with `u_blitter`: every `util_blitter_blit_generic` restores the saved state
  and drops the saved framebuffer at its end. The restore measured about 1 us, and the framebuffer restore is what cuts the batch.
- **Skip re-validation per level:** about 40 comparisons, a few hundred cycles.
- **Cheaper alternative for the 7-level chain:** each level needs its own framebuffer, so 7 batches. Not implemented, three options:
  (a) tail skip (below, implemented); (b) one compute dispatch that writes all levels (the driver has `launch_grid`; needs a new
  shader, unknown cost, would turn 8 batches into 1); (c) MRT with differently sized targets is not valid in one pass.
- **Skip generation for unchanged textures:** there is no write epoch. `texture_publication_epoch` (`:280`, `:2995`) is the CPU cache
  publication counter (clflush bookkeeping), not a GPU-write counter, and `gpu_written` is only set for compute writes (`:16760`,
  `:17018`). A real "written since last mip generation" counter would need a bump in every write path (draw to a bound colour
  target, clear, blit, copy, transfer unmap, texture_subdata). The textures here are rendered every frame (the `mip:` log shows
  n equal to the frame count for the 1-level textures), so "unchanged" would almost never be true. The useful signal is the opposite
  one: **"nobody sampled the texture since the request"**, which needs only a flag set at request time. That is bit 1 below.

## 4. What drv_patch59.py does (env `PS5_MIPFAST`, bit mask, default 0 = unchanged behaviour)

Always on, free while the tracer is off: events **137** `ps5_generate_mipmap` (arg 1 = ok), **138** `ps5_blit_gpu_color` (arg 1 =
GPU path), **139** `util_blitter_blit_generic` only, **140** lazy flush (arg = levels). `trace2json.py` prints them as `evNNN`
(add names if wanted); `trace_mip.py` prints their ms/frame.

**Bit 1, lazy mips (`PS5_MIPFAST=1`).** `glGenerateMipmap` on an eligible texture only stores `mip_lazy, mip_lazy_base, mip_lazy_last`
in the resource and returns true. Eligible: 2D, single layer, colour render-target texture without display bind, one of the four
GPU-blit formats (RGBA8, R8, RG8, RGBA16F), linear sampled layout, every level an exact halving or 1 (the same cases the GPU blit chain
handles today). Everything else takes the old path. The chain runs (`ps5_mip_lazy_flush`, clears the flag first, then the old code)
at exactly these points, all conservative:

| Trigger | Site | Why |
| --- | --- | --- |
| texture bound in a fragment or vertex sampler slot at a draw | `ps5_draw_vbo_traced`, before the draw | the draw may sample any level (geometry/tess slots 2 to 4 and compute are NOT scanned: Jak does not use them) |
| `transfer_map` with read, or level > 0 | `ps5_transfer_map` | readback needs the mips; a write to level > 0 must not be overwritten later. Level-0 writes do not flush (the later generation reads the newer level 0, which is what GL would give after the next request anyway) |
| blit source or destination | `ps5_blit` (skipped while the blitter runs) | levels read or written |
| `resource_copy_region` source, and destination at level > 0 | `ps5_resource_copy_region` | same |
| framebuffer attachment at level > 0 (colour or depth) | `ps5_set_framebuffer_state` (skipped while the blitter runs) | rendering into a mip must not be overwritten |
| a second `glGenerateMipmap` with a different base level, or an ineligible request on the same resource | wrapper | merging could overwrite levels set explicitly |

Same base level and a still-pending resource: the request is replaced (last level = max); the older chain is never run. This is the
saving. Resource destruction needs no hook (the flag dies with the calloc'd struct; nothing holds a pointer to a pending resource).
Semantic difference to GL: the mips are generated from level 0 at the time of first use, not at the call. For the render-then-generate
pattern of the texture animations this is the same or newer content. A game that changes level 0, calls genmip, changes level 0 again
and then samples the old mips would differ (not seen).
Not covered, because unused here: compute `launch_grid` image/texture bindings, `ps5_clear` with level > 0 outside the framebuffer
path, texture views that alias a pending resource (the driver has none except the display alias, which is not eligible).

How much it saves is unknown until measured: a chain is skipped only when the texture is not bound in any draw before the next
request. Saving per skipped single-level call is about 50 us CPU, per skipped 128x128 chain about 180 us, plus the batch cuts.
Upper bound is the whole 0.6 to 0.7 ms CPU and 15 of about 60 batches per frame. The scan costs 32 pointer loads per draw
(about 0.05 ms per frame). Measure it from the log: `mip:` lines keep `n` = requests; `gpu` = levels really generated, so saved
levels = sum(n * (last - base)) - sum(gpu).

**Bit 2, tail skip (`PS5_MIPFAST=2`, `PS5_MIPFAST_TAIL=N`, default 2).** For textures with both dimensions >= 32 the chain stops when
the next level would be <= N x N in both dimensions (2x2 and 1x1 stay stale; they are only sampled when the surface is below about
2 screen pixels per 128 texels). Saves 2 of 7 batches of a 128x128 chain, about 50 us and 2 batches per frame. Visual risk: stale
or never-written 2x2/1x1 levels; compare with `shotdiff.py`. `PS5_MIPFAST=3` combines both.

Statics added: only two function-local `static int` scalars in `ps5_mipfast_env`. Struct change: 3 bytes in `struct ps5_resource`
(only allocated with `calloc` at `:5158` and in `ps5_display_target_alias`). No new arrays, no shim change required.

## 5. Apply and test

```
wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && python3 drv_patch59.py && bash drv_cc_cache.sh && touch ~/ogapp/src/ogmain.cpp && bash rebuild_all.sh"
```
(use the same `PS5_EXTRA_DEFS` as the deployed build). Env mapping to add to `ps5shim/appmain.cpp` (proposal, not edited):
```
{ struct stat nf; if (stat("/data/opengoal/config/mipfast.txt", &nf) == 0) setenv("PS5_MIPFAST", "1", 1); }   // driver patch 59, lazy mips
{ struct stat nf; if (stat("/data/opengoal/config/mipfast2.txt", &nf) == 0) setenv("PS5_MIPFAST", "2", 1); }  // tail skip
```
Runs (Jak 3, `asyncmultidraw` on, 4K output as in r4k, 3 s trace each, same spot), one flag set at a time:

1. baseline (no flag): confirms the patched build equals jak3_r4k; check `trace_mip.py` shows events 137 to 139 and no behaviour change.
2. `mipfast` (=1): `python3 trace_mip.py perf_runs/<run>.trace_*.bin` and `python3 trace2json.py <bin> -`.

| Metric | Baseline (r4k) | Success for bit 1 |
| --- | --- | --- |
| glGenerateMipmap ms/frame | 2.92 (2.23 wait + 0.68 CPU) | CPU part below 0.3; the wait part may stay or move: judge the sum of glGenerateMipmap + backpressure wait + batch-retire in the frame |
| `batch submit` calls/frame (trace2json) | 60.7 | down by up to 15 |
| draw count (`draw (glfix wrapper)` calls) | 524.2 | unchanged (the blit draws are event 122 only) |
| event 140 calls/frame vs 9 requests | n/a | below 9 means chains were skipped |
| fps and frames over 20 ms per 3 s | 59.0, 3 to 6 | not worse |

3. `mipfast2` (=2) the same table; expect batch submit down by about 2 and glGenerateMipmap CPU down by about 0.05 ms.
4. Visual check for bit 1: screenshot series (`shotseries.py`, `shotdiff.py`) of the same scene with and without the flag at places with
animated textures (fire, water, screens); any difference points at a missing flush trigger. Also run the Jak 3 menus and a
cutscene (many glTexSubImage/readback paths).
5. Boot test alone first (struct layout and statics are tiny, but follow pitfall 6 of the journal).

## 6. Open points

- Whether the animated textures are really unsampled in a large fraction of frames is the unknown that decides the value of bit 1.
- The real lever for the wait is fewer or cheaper GPU batches (one compute dispatch for a chain, or multi-framebuffer batches);
  both are bigger changes in the runtime and were not attempted.
- `ps5_mip_lazy_eligible` repeats the GPU-path preconditions by hand; if `ps5_blit_gpu_color` gains new restrictions the old
  path would still be taken at flush time, so the result stays correct, only the saving shrinks.
