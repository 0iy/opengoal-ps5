# agent merge: fewer driver draws for Jak 2 (multi-draw gather)

Files: `shim_patch_merge.py` (applies to `ps5shim/glfix.cpp`, or to the file named by env `GLFIX_SRC`). Nothing else touched; no console use.
Verified: the patch applied twice to a private copy (`/tmp/merge_glfix.cpp` in WSL, second run prints "already patched"), and the patched file
compiles with `g++ -std=c++17 -fsyntax-only -Wall -Wextra` with zero warnings (same as the unpatched file). Not linked, not run.

## 1. Key finding: the existing "adjacent range" merge can never fire

`w_MultiDrawElements` already merges sub-draws whose converted ranges touch (glfix.cpp, "adjacent ranges of the converted list draw as
one"). Every `glfix: multidraw ranges in=... out=...` line in `perf_runs/*` has **in == out** (e.g. in=219441 out=219441). The OpenGOAL
data layout explains why:

* `make_multidraws_from_vis_string` (`background_common.cpp:568`) walks the vis groups of one StripDraw and emits one run per maximal
  sequence of *visible* groups (`counts_out[md_idx] = iidx - run_start`). A new sub-draw starts only after at least one invisible group.
  So by construction two neighbouring sub-draws of one call are separated by culled index data in the source buffer, and in the
  converted buffer too (a culled group converts to its own triangles). Contiguous neighbours do not exist unless the culled group has
  no triangles. Same function for tfrag (`TFragment.cpp:451`), tie (`Tie3.cpp:458-469`, also the `_and_proto_` variant), shrub (`Shrub.cpp:323`).
* Therefore "merge contiguous sub-draws" has an expected gain of about 0. Real merging must either **bridge the gaps** (draws culled
  geometry: extra GPU triangles, and for tie the proto-visibility gaps would draw protos the game chose to hide: unsafe) or **gather**
  (copy the visible ranges into one new contiguous range: exactly the same triangles in the same order). I implemented gather.

## 2. How OpenGOAL issues draws (read in `~/jak/game/graphics/opengl_renderer`)

* Draw call sites: tfrag `TFragment.cpp:487-510`, tie `Tie3.cpp:601-624, 694-697, 977-992`, shrub `Shrub.cpp:364-389`, merc `Merc2.cpp:1333-1350`
  (single `glDrawElements`, one per draw), generic `Generic2_OpenGL.cpp:276,292`, direct `DirectRenderer.cpp:292-314` (`glDrawArrays`), others.
* Per tree, per StripDraw (= one texture + one DrawMode): `glBindTexture`, `setup_tfrag_shader` (blend/depth/alpha state, uniforms), one
  `glUniform1i(decal)`, then **one glMultiDrawElements whose sub-draws are the visible runs of that StripDraw**. So texture or state
  changes between every pair of multi-draw calls: calls cannot be merged with each other, only their sub-draws.
* Shaders: no use of `gl_DrawID`, `gl_BaseVertex`, `gl_BaseInstance`; `gl_InstanceID` does not occur; `gl_VertexID` only in
  `sprite_distort_instanced.vert` and `splash.vert` (not tfrag/tie/shrub; those use `glDrawArrays` anyway). Verified by grep over
  `shaders/`. Nothing forbids merging sub-draws of a multi-draw call. All sub-draws of one call share every piece of GL state by API definition.
* Index data is 32 bit, triangle strips with restart `0xFFFFFFFF` (`glPrimitiveRestartIndex(UINT32_MAX)`); glfix converts them to lists.

## 3. What the patch does

`PS5_MERGE_DRAWS=1` (default off, current behaviour): in `w_MultiDrawElements`, after the ranges are resolved to the converted buffer
and the existing adjacent merge ran, if there are 2 or more ranges: copy them (in call order) into a staging vector (computing min and
max index on the way), append them with `glBufferSubData` to a private dynamic element buffer, and issue **one** `glDrawRangeElements(GL_TRIANGLES, lo, hi, total, UINT, offset)`.
Triangles and order are identical to the sub-draws, so the image must be bit-identical (provoking vertex preserved too: converted lists
are already per-triangle). Driver draws per multi call: N sub-draws -> 1. The lo/hi also removes the driver's own min/max scan for those draws.

Safety and fallbacks (`merge_gather`): any misaligned or out-of-range offset, a count <= 0, total over 4M indices or not a multiple of 3 -> returns
false and the original multi-draw runs (counted in the stats as `fallback`). Single sub-draw calls stay untouched.

Buffer lifetime: the gather buffer is append-only within a frame; at every swap (`ps5_glfix_end_frame`) the flag `orphan` is set and the
next gather re-specifies the storage with `glBufferData(cap, NULL)` (also when it would overflow mid-frame; capacity starts at 1M indices = 4 MB, doubles).
Draws already queued for the driver keep referring to the old storage (that is what buffer orphaning means in GL; Mesa renames the resource;
the driver has `PS5_NO_BUFFER_RENAME`, so renaming exists). **This is the main assumption to test**: if the async prep workers read the
buffer after it was orphaned and the driver does not retain the old resource, geometry would flicker or vanish. Test with
`PS5_ASYNC_MULTIDRAW=1` (they are the case that matters) and with default flags.

The GL bindings go through `bind_hw_ebo` / `restore_ebo` exactly like the existing converted buffers, so the VAO's own element buffer is restored by the next non-draw call.

Static data added: exactly one function-local `static MergeState* p` (guard variable plus pointer) in `mg()`. `MergeState` and the statistics are
heap allocated, and only when `PS5_MERGE_DRAWS` or `PS5_MERGE_STATS` is set. No namespace-scope variables, no static arrays.
Also adds `#include <cstdlib>`. Hooks: 3 lines in single-draw/array paths (statistics only), 2 in the multi path, 1 in `ps5_glfix_end_frame`.

## 4. Instrumentation: `PS5_MERGE_STATS=1`

Every 3 s, `ps5_log` lines (UDP and console log):

```
merge: 3.0s 135 frames; per frame: multi=.. single=.. other=.. subs=.. nonempty-calls=..
merge: subs/call 1:.. 2:.. 3-4:.. 5-8:.. 9-16:.. 17-32:.. 33-64:.. 65+:..
merge: neighbour sub-draws=.. src-contiguous=..; gap(conv idx) <0:.. 0:.. 1-12:.. 13-48:.. 49-192:.. >192:..
merge: indices drawn=.., lying in 1..192 gaps=..; consecutive calls=.. same-program=.. same-state=.. same-state+contiguous=..
merge: gather calls=.. indices=.. fallback=..
```

* `subs` per frame minus `nonempty-calls` per frame = driver draws removed by gather (upper bound; calls with 1 sub-draw are unchanged).
* The gap histogram quantifies bridging as an alternative (gap = converted indices lying between two sub-draws; 12 indices = 4 triangles).
* Consecutive-call state: signature = program, bound 2D texture of the active unit, draw FBO, VAO, blend enable, depth mask, depth func,
  blend src (via `glGetIntegerv`; costs a few us per draw, so use the stats only for measuring, not for fps comparisons). Uniform values
  (e.g. `decal`, `alpha_min`) are NOT in the signature, so `same-state` is an **upper bound** of what could be merged across calls.
  `same-state+contiguous` additionally requires that the next call starts exactly where the previous one ended in the same converted buffer.

## 5. Merging consecutive separate draw calls: not implemented, and why

A deferred "hold one pending draw" scheme needs to flush on: every `glBindTexture`/`glActiveTexture`, `glUseProgram`, every `glUniform*`
(and any `glBufferSubData`/`glBufferData`/`glMapBuffer*` on a bound buffer, `glBindBuffer`/`glBindVertexArray`/vertex attribute calls, `glBindFramebuffer`/`glFramebuffer*`,
every `glEnable/Disable/BlendFunc/DepthMask/DepthFunc/...`, `glClear`, blit, readback, `glTex*Image`, `glGenerateMipmap`, `glFlush/Finish`, swap), i.e. effectively all
GL entry points, and glfix interposes only ~30 of them. Missing one gives wrong output, not a crash. By the layout in section 2 the engine
changes texture and `decal`/alpha uniforms between nearly every pair of draws, so the expected gain is small, and the chain statistic
(`same-state+contiguous`) will show it on the first run. Recommendation: implement it only if that number is above roughly 10 percent of calls; the cheap safe
variant would then be a wrapper for the handful of state calls the renderer uses, which is a separate change. Merc (`Merc2.cpp:1333`) uses a different
texture/bone-uniform set per draw, so it cannot merge at all.

## 6. Expected draw reduction

Facts (measured, from the brief and journal): Jak 2 city has about 1220 engine draw calls and about 1970 driver draws per frame, 14.6 us per driver draw.

Derived (assumption-based):
* Almost all 1970 - 1220 = about 750 extra driver draws come from multi-draw calls (tfrag/tie/shrub), because single-draw callers (merc, direct, sprite) create exactly one each.
  Gather turns each multi call into one draw, so the driver draws drop to **about 1220 minus empty calls**: -38 percent at most.
* If frame time scales with driver draws (it is CPU bound there), 45 fps -> up to about 70 fps. Not the real expectation: copy and
  `glBufferSubData` cost (about 12 bytes per triangle; a few MB per frame, perhaps 0.3 to 1 ms) and a possibly size-dependent part of the 14.6 us (descriptor and
  constant preparation are per draw, but the min/max scan and vertex fetch are per index) reduce it. Realistic guess 55 to 65 fps. 60 fps needs about 1000 draws at the current cost, so gather
  alone gets close but may need one more step (cutting per-draw cost).
* Not derivable offline: how many sub-draws per call there actually are. The statistics line `subs/call` gives it on the first run.
  Many large tfrag draws probably have only a few runs, while far trees/tie protos with scattered visibility may have dozens.

## 7. Apply, enable, test

Apply (WSL, repo root): `GLFIX_SRC=ps5shim/glfix.cpp python3 shim_patch_merge.py` (default target is `ps5shim/glfix.cpp`; the main session decides).
Proposed `appmain.cpp` lines next to the others (about line 115):

```cpp
{ struct stat nf; if (stat("/data/opengoal/config/mergedraws.txt", &nf) == 0) setenv("PS5_MERGE_DRAWS", "1", 1); }
{ struct stat nf; if (stat("/data/opengoal/config/mergestats.txt", &nf) == 0) setenv("PS5_MERGE_STATS", "1", 1); }
```

Test sequence (one console run each, Jak 2 Haven city, same spot, `asyncmultidraw.txt` on):

1. Build with the patch, no flags: confirm boots and fps equal to before (hooks are one pointer check).
2. `mergestats.txt` only: read the five `merge:` lines; check `subs - nonempty-calls` per frame is about 700 and read `same-state+contiguous`.
3. `mergedraws.txt` only: `perfround.py` with the tracer; `python trace2json.py <trace.bin> out.json` (not the other order), compare draws per frame
   (event 11 count per frame, expect about 1970 -> about 1250) and driver ms per frame (sum of event 11 and event 10 minus 11 for glfix time; the copy shows up in event 10).
   Check `gather ... fallback=0`.
4. Screenshots: `shotseries.py` at a fixed camera position with and without the flag (the title/idle camera in Haven is static), then
   `python shotdiff.py a.png b.png --thresh 0` and `--thresh 4`. The expected result is 0 differing pixels (identical triangles and order); anything else is a bug in the patch or in orphaning.
   Repeat once with `syncdebug.txt` if a diff appears, to separate buffer-lifetime races from logic errors.
5. Soak: 5 minutes of driving (level streaming changes the buffers, `invalidate` paths) and a Jak 3 run (`asyncmultidraw`, it already sits at 59 fps; check no regression).

## 8. Risks and open questions

* Buffer orphaning with the driver's async prep (section 3). If it fails visually, fallback is a bump allocator without per-frame orphan (grow only), at the cost of memory; not implemented.
* `glBufferSubData` into a freshly orphaned dynamic buffer on the PS5 driver: cost unmeasured (the existing `upload()` does the same for converted lists).
* Gather costs memory bandwidth for the whole visible index set once per frame; for tfrag-heavy scenes this is the part to watch in `glfix` time (event 10 minus 11).
* Not checked: whether `lo/hi` via `glDrawRangeElements` changes driver behaviour for vertex fetch (the single-draw path already uses it).
* Skipped: gap bridging (section 1) and deferred merging of separate calls (section 5).
