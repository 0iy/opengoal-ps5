# Dynamic resolution and FSR 1.0 upscaling

Experimental. Optional engine patches `engine/patch_fsr.py` and `engine/patch_fsr_effects.py` plus the shaders in `engine/fsr/`. In the launcher: **Upscaling**
(Off, Quality 83 %, Balanced 67 %, Performance 50 %, Auto) and **Sharpness**.

Status: verified offline (shader output against a reference, controller simulation, compile with the console toolchain). Run on a console in Jak 2 at 67 %: the image
fills the window and the title is correct, with no fps gain because Jak 2 is CPU bound. Not verified on a console: the Auto controller, the other games and scales,
and the screen-space effects listed below at reduced size.

## How it works

The engine renders the world into one offscreen target and draws it to the window with a bilinear filter. The patch:

1. picks a render percent per frame (`fsr_frame_begin`, the first thing in `OpenGLRenderer::render`);
2. below 100 percent, renders into a pooled target of `game_res * percent / 100` (even sizes, at least 64). `render_fb_w/h` and the viewport follow, so every user
   of those sizes (BlitDisplays, glow probe, distort, Warp, FramebufferCopier) sees the smaller size;
3. rescales `draw_region`/`draw_offset` to render pixels and keeps the window values for the final viewport;
4. replaces the final blit by EASU into an RGBA8 intermediate of the draw-region size, then RCAS into the window with the same brightness and contrast math as
   `post_processing.frag` (`PS5_FSR_SHARP=0` skips RCAS). If the shaders fail to build it falls back to the bilinear blit;
5. at 100 percent nothing changes. Screenshots, MSAA and tiny sizes force 100 percent for that frame.

The shaders (`engine/fsr/fsr.vert`, `fsr.frag`, `#version 410 core`, one source and two programs selected by `FSR_EASU` or `FSR_RCAS`) are embedded in the C++ as
string literals; no shader files are needed on the console. They follow the public description of AMD FidelityFX FSR 1.0 (MIT): exact reciprocals instead of
the approximations, fp32 throughout, `texelFetch` instead of `textureGather`. The output matches within rounding, not bit for bit.

## Settings

The launcher writes `upscale=0..4` (off, 83, 67, 50, auto) and `sharpness=0..10` to `ps5.cfg`; `app/shim/appmain.cpp` turns them into environment variables.
Developer files in `/data/opengoal/config/`: `renderscale.txt` (33..100, 0 = auto), `nofsr.txt` (scaled render with the plain bilinear blit, for A/B), `fsrsharp.txt` (0..10).

| Variable | Default | Meaning |
|---|---|---|
| `PS5_RENDER_SCALE` | off | 33..99 fixed percent, `0` or `auto`, 100 = off |
| `PS5_FSR` | 1 | `0` = scaled render with bilinear blit |
| `PS5_FSR_SHARP` | 7 | 0 = no RCAS, N = RCAS at `2 - 0.18 N` stops (10 = AMD's default 0.2) |
| `PS5_FSR_TARGET_MS` | 16.0 | Auto: target for the time inside `render()` |
| `PS5_FSR_REFRESH` | 60 | Auto: display refresh for the missed-vsync test |
| `PS5_FSR_MIN` | 50 | Auto: lowest percent |
| `PS5_FSR_PREWARM` | 1 | allocate all Auto targets at the first frame (`0` = lazily) |
| `PS5_FSR_LOG` | 1 | log scale changes and a status line every 300 frames |
| `PS5_FSR_FX` | 1 | `0` = old behaviour of the pause-menu screen copy (see effects) |

## Auto controller

Ladder 100, 83, 67, 50 (cut at `PS5_FSR_MIN`). Per frame it records the frame period P and the time inside `render` R. Windows of 30 frames, the two worst dropped,
frames over 100 ms ignored, six frames after every change ignored.

- Miss: `R > target` or `P > 1.08 x refresh interval`. Down after two missing windows (about 1 s), one step at a time.
- Verification: if a down step lowers R by less than 7 percent and frames still miss, the load is CPU or driver bound; the step is undone and further steps are blocked for
  1800 frames (doubling, at most 21600). Resolution cannot fix per-draw driver cost, so this guard matters.
- Up: good windows (`R < 0.8 x target`, `P < 1.04 x interval`) for six windows (about 3 s), then one step at a safe point (a fade or after 300 frames); a failed step up doubles
  the wait for that step.
- Targets are allocated once (prewarm) so switching only rebinds; the FramebufferCopiers reallocate on a size change, a hitch paid once per switch.

`engine/fsr/test/ctrl_sim.py` simulates it: a light scene stays at 100, a GPU-bound heavy scene settles at 67, a CPU-bound scene returns to 100 and blocks, borderline load settles at 83.
The real R/P relation on the console is unmeasured; if the flip wait turns out to sit inside `render()`, raise `PS5_FSR_TARGET_MS` to 17.5.

## Screen-space effects at reduced size

An audit of every use of the render size found one real problem: the Jak 2 and Jak 3 pause menu copies the screen and copies it back, which failed when the render size changed.
`patch_fsr_effects.py` (apply after `patch_fsr.py`) makes the copy-back scale (`GL_LINEAR` when sizes differ, `PS5_FSR_FX=0` disables). Everything else that reads sizes
(DepthCue, glow, sprite distort, BlitDisplays) uses `render_fb_w/h`, or normalised coordinates, or its own fixed-size targets, and needs no change. The dark "JAK II" title logo
seen once at 67 percent was the intro lightning sequence at an earlier moment, not a render-size bug (the same scale showed the bright logo later in the run).

Not implemented: a negative texture LOD bias (-0.58 at 67 percent) to keep textures sharper; it needs a change in every fragment shader or texture object and cannot be tested offline.

## Apply

```
FSR_SRC=~/jak python3 engine/patch_fsr.py          # anchors are asserted; a changed setup_frame or do_pcrtc_effects fails loudly
JAK_ROOT=~/jak python3 engine/patch_fsr_effects.py
tools/ps5 build
```

Run the FSR patch after `apply_ps5_patches.py` (it touches other files; the anchors in `OpenGLRenderer.cpp/.h` are upstream text). Both scripts take the tree from `FSR_SRC` or `JAK_ROOT`
and refuse to run without one. `patch_fsr.py` also refuses a tree that carries an older FSR patch (start from a clean tree). Both are optional manifest steps (`fsr`, then `fsr-effects`,
which requires `fsr`), so `tools/ps5 sync` applies them in that order; `--emit-manifest` prints the step with its anchors.

## Offline tests (`engine/fsr/test/`)

- `fsr_ref.py` runs both shaders on llvmpipe (EGL surfaceless) against a numpy implementation: worst error 1 of 255 on synthetic edges, circles, thin lines and noise.
- `ctrl_sim.py` runs the controller scenarios above.
- `gl_harness.c` is the GL harness used by `fsr_ref.py`.

## Console test plan

One case at a time, with `shotscreen.txt` present so timed screenshots read the real window image; record fps, a screenshot at the same camera position and the `fsr:` log lines.
Regression (scale unset equals the build without the patch), plumbing at 67 with `nofsr.txt`, FSR on with sharpness 0 then 7, fixed 83/67/50 at 1080p/1440p/4K,
effects at 67 and 50 (water refraction, pause blur, fades, glow), Auto at 4K in the heaviest scene (at most one change per 3 s, no oscillation, memory stable), a 30 minute soak.
If the picture is drawn 1:1 in a corner, compare with `nofsr.txt`: if that fills the screen the fault is in the FSR pass or its uniforms (the shaders read sizes from two `vec4` uniforms
set with `glUniform4f`, and `fsr_present` appends a diagnostic line every 300 calls to `/data/opengoal/log/fsrdbg.txt`).
