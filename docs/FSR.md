# Dynamic internal resolution and FSR 1.0 upscaling

Status 2026-10-24. Implemented as `patch_fsr.py` (engine patch) plus `fsr/` (GLSL and offline tests). Not applied to any live tree,
not run on the console. Everything in "Verified offline" below was run; everything in "Not verified" was not.

## What it does

The engine renders the world into one offscreen FBO (`render_buffer`, size `game_res`) and `do_pcrtc_effects` draws it to the window
region (`draw_region`, letterbox) with the `post_processing` shader (brightness/contrast) and a bilinear filter. The patch:

1. Chooses a percent per frame (`fsr_frame_begin`, first thing in `OpenGLRenderer::render`).
2. If the percent is below 100, `setup_frame` renders into a pooled FBO of `game_res * percent / 100` (even sizes, at least 64) instead
   of `render_buffer`. `render_fb_w/h` and the viewport follow, so every user of `render_fb_w/h` (BlitDisplays, glow probe, distort,
   Warp, FramebufferCopier) sees the smaller size, no other renderer is edited.
3. `draw_region`/`draw_offset` in `SharedRenderState` are rescaled to render-target pixels (DepthCue reads the render FBO with them);
   the window-pixel values are kept in `m_fsr.win_*` and used for the final viewport.
4. The final pass (`fsr_present`, replaces the `glDrawArrays` of the plain blit) runs EASU into an RGBA8 intermediate of the draw
   region size, then RCAS into the window with the same brightness/contrast math as `post_processing.frag`. `PS5_FSR_SHARP=0` skips
   RCAS (EASU draws straight to the window). If shader build fails the code falls back to the old bilinear blit.
5. At 100 percent nothing changes (same code path as before; one extra branch per frame).

Screenshots, MSAA (`msaa_samples != 1`) and tiny sizes force 100 percent for that frame.

### Settings (environment, all optional)

| Variable | Values | Meaning |
| --- | --- | --- |
| `PS5_RENDER_SCALE` | unset or 100 = off; `0` or `auto`; 33..99 | fixed percent (typically 83, 77, 67, 50) or AUTO |
| `PS5_FSR` | default 1; `0` | `0` = scaled render + plain bilinear blit (A/B against FSR) |
| `PS5_FSR_SHARP` | 0..10, default 7 | 0 = no RCAS; N = RCAS at `2 - 0.18 N` stops (10 = 0.2 stops, AMD's default) |
| `PS5_FSR_TARGET_MS` | default 16.0 | controller target for time inside `render()` |
| `PS5_FSR_REFRESH` | default 60 | for the vsync miss test (period over 1.08 x refresh interval) |
| `PS5_FSR_MIN` | default 50 | lowest AUTO step |
| `PS5_FSR_PREWARM` | default 1 | allocate all AUTO render targets at the first frame (shaders still build at the first scaled present) |
| `PS5_FSR_LOG` | default 1 | log every scale change, and a status line every 300 frames |

### AUTO controller (`fsr_frame_begin`)

Ladder 100, 83, 67, 50 (cut at `PS5_FSR_MIN`). Per frame it records the frame period P (start of `render` to start of the next) and
R (time inside `render`). Windows of 30 frames, the 2 worst frames dropped, frames over 100 ms ignored, 6 frames after every change
ignored.

- Miss: `R > target` or `P > 1.08 x refresh interval` (a missed vsync shows as P = 33 ms).
- Down: two consecutive missing windows (about 1 s), or one window with P over 1.5 x interval. One step at a time, applied at the
  next frame.
- Down step verification: if after one window R fell by less than 7 percent and frames still miss, the load is CPU or driver bound,
  the step is undone and further down steps are blocked for 1800 frames (doubling each time, max 21600). Resolution scaling cannot
  fix the 17 to 28 us per draw driver cost that dominates today, so this guard matters.
- Up: window good (`R < 0.8 x target` and `P < 1.04 x interval`) for `backoff` consecutive windows (6, about 3 s), then one step up at a
  safe point: a fade/blackout frame (`pmode_alp_register < 1`) or after 300 frames of waiting. A step up that fails within 4 windows
  doubles the wait for that step (6, 12, ... 96 windows). Hysteresis comes from the asymmetric thresholds (0.8 versus 1.0) plus backoff.
- FBO resize cost is avoided with a pool: every AUTO target is allocated once (prewarm, at the first frame, typically a loading
  screen), switching only rebinds. The `FramebufferCopier`s used by BlitDisplays/Warp/glow do reallocate their textures on a size change;
  that hitch is paid once per switch, which the 6-frame settle and the backoff keep rare.

Simulation (`fsr/test/ctrl_sim.py`, synthetic frame times, GPU cost proportional to percent squared, 8 ms hitch right after a change,
vsync quantised period, 120 s at 60 fps): light scene stays at 100 with 0 changes; GPU bound heavy scene settles at 67 percent
(10 changes in 120 s, five of them failed probes with growing backoff); CPU bound scene returns to 100 and blocks (6 changes);
heavy then light returns to 100; borderline load settles at 83. The real R/P relation of this port is unmeasured (see risks), the
thresholds are the first thing to tune on the console.

## Files

- `patch_fsr.py` patches `game/graphics/opengl_renderer/OpenGLRenderer.h/.cpp` (11 asserted replacements, idempotent, marker `ps5_fsr`).
  `FSR_SRC` is required (jak-project root). Embeds `fsr/fsr.vert` and `fsr/fsr.frag` as raw string literals; no shader files on the
  console, no `Shader`/`ShaderId` changes.
- `fsr/fsr.vert`, `fsr/fsr.frag`: `#version 410 core` like `post_processing`. One source, two programs (`#define FSR_EASU` or
  `FSR_RCAS` spliced behind the `#version` line). EASU: 12 `texelFetch` taps (the algorithm's `b c / e f g h / i j k l / n o`
  footprint), luma-gradient direction, anisotropic Lanczos2 approximation, de-ring against the 4 center texels. RCAS: 5 taps,
  noise attenuation, per-channel limiter, lobe limit 0.1875.
- `fsr/test/gl_harness.c`, `fsr/test/fsr_ref.py`, `fsr/test/ctrl_sim.py`: offline tests.
- Written from the public description of AMD FidelityFX FSR 1.0 (MIT) from memory, not copied from the SDK header. Differences from the
  reference: exact reciprocal/rsqrt instead of the `APrx*` approximations, fp32 everywhere, divide guards in RCAS (`1/65536`) instead
  of relying on inf/NaN behaviour, `texelFetch` instead of `textureGather`. Output will match AMD's within rounding but is not
  bit-identical; I had no copy of the AMD header to compare against.

Static data added: none (all state is in `OpenGLRenderer::m_fsr`; two `const char*` string literal constants in an anonymous
namespace are read-only data). This avoids the patch-45 RELRO pitfall.

## Apply and build

```
wsl -e bash -c 'FSR_SRC=~/jak python3 /mnt/c/Users/<you>/dev/projects/opengoal-ps5/patch_fsr.py'   # live tree: main session only
wsl -e bash -c 'bash /mnt/c/Users/<you>/dev/projects/opengoal-ps5/rebuild_all.sh'
```

`rebuild_all.sh` runs `apply_ps5_patches.py` first; if that script rewrites `OpenGLRenderer.cpp`/`.h` from scratch, run
`patch_fsr.py` after it (or add it to the chain). The anchors are strings of the current live file (it already contains other ps5
patches), so a changed `setup_frame`/`do_pcrtc_effects` makes an assertion fail loudly instead of patching wrongly.

## Integration (lines for the two files another session owns; not applied)

Values in `ps5.cfg`: `upscale=0..4` (0 off, 1 quality 83, 2 balanced 67, 3 performance 50, 4 auto) and `sharpness=0..10`.
Line numbers refer to the working tree on 2026-10-24.

### `ps5shim/include/ps5launcher.h`, `struct Ps5Settings`

```cpp
  int upscale = 0;     // 0 = off, 1 = quality (83 %), 2 = balanced (67 %), 3 = performance (50 %), 4 = auto
  int sharpness = 7;   // FSR RCAS strength 0 (off) .. 10
```

### `ps5shim/launcher.cpp`

In `ps5_settings_load()` (next to `lazymips=`):

```cpp
    else if (std::sscanf(line, "upscale=%d", &v) == 1) g_settings.upscale = std::clamp(v, 0, 4);
    else if (std::sscanf(line, "sharpness=%d", &v) == 1) g_settings.sharpness = std::clamp(v, 0, 10);
```

In `ps5_settings_save()`, extend the written text (the existing `fprintf` writes only four keys; if the other session writes
merge/async/lazymips elsewhere keep that and just add these two):

```cpp
  std::fprintf(f, "upscale=%d\nsharpness=%d\n", g_settings.upscale, g_settings.sharpness);
```

Enum and rows: replace `SET_FSR` entry in the enum by `SET_FSR, SET_SHARP`, and replace the `r[SET_FSR] = {...}` block by:

```cpp
  static const char* const kUpEn[] = {"Off", "Quality (83%)", "Balanced (67%)", "Performance (50%)", "Auto"};
  static const char* const kUpDe[] = {"Aus", "Qualit\xc3\xa4t (83%)", "Ausgewogen (67%)", "Leistung (50%)", "Auto"};
  r[SET_FSR] = {L("Upscaling (FSR)", "Hochskalierung (FSR)"), g_settings.lang ? kUpDe[g_settings.upscale] : kUpEn[g_settings.upscale], true,
                L("Renders below the output size and upscales with FSR 1.0. Auto lowers the size when the frame rate drops.",
                  "Rendert unter der Ausgabegr\xc3\xb6\xc3\x9f\x65 und skaliert mit FSR 1.0 hoch. Auto verkleinert bei niedriger Bildrate.")};
  r[SET_SHARP] = {L("Sharpness", "Sch\xc3\xa4rfe"), std::to_string(g_settings.sharpness), g_settings.upscale > 0,
                  L("FSR sharpening, 0 = off.", "FSR-Sch\xc3\xa4rfung, 0 = aus.")};
```

In the settings input `switch (settings_sel)` (next to `case SET_LAZYMIPS`):

```cpp
          case SET_FSR: g_settings.upscale = (g_settings.upscale + 5 + dir) % 5; break;
          case SET_SHARP: g_settings.sharpness = std::clamp(g_settings.sharpness + dir, 0, 10); break;
```

(`SET_FSR` was disabled, so also drop the "not available" strings. The greyed-row skip logic already handles `SET_SHARP` while
`upscale == 0`. Both changes apply at the next engine start, which the existing toast says.)

### `ps5shim/appmain.cpp`

Directly after `const Ps5Settings& cfg = ps5_settings();` (line 147), before the display mode is set; the engine reads the variables
at its first rendered frame, which is after this point:

```cpp
  {  // dynamic resolution + FSR (docs/FSR.md). Developer flag files win over ps5.cfg.
    static const char* const kScale[] = {nullptr, "83", "67", "50", "auto"};
    if (cfg.upscale > 0 && cfg.upscale <= 4) {
      setenv("PS5_RENDER_SCALE", kScale[cfg.upscale], 1);
      setenv("PS5_FSR_SHARP", std::to_string(cfg.sharpness).c_str(), 1);
      setenv("PS5_FSR_REFRESH", std::to_string(cfg.refresh).c_str(), 1);
    }
    int rs = 0;
    if (FILE* rf = std::fopen("/data/opengoal/config/renderscale.txt", "r")) {  // content: 33..100 or 0 (= auto)
      if (std::fscanf(rf, "%d", &rs) == 1 && rs >= 0) setenv("PS5_RENDER_SCALE", rs >= 100 ? "100" : (rs == 0 ? "auto" : std::to_string(rs).c_str()), 1);
      std::fclose(rf);
    }
    struct stat nf;
    if (stat("/data/opengoal/config/nofsr.txt", &nf) == 0) setenv("PS5_FSR", "0", 1);  // scaled render, plain bilinear blit
    if (FILE* sf = std::fopen("/data/opengoal/config/fsrsharp.txt", "r")) {            // content: 0..10
      int v = 0;
      if (std::fscanf(sf, "%d", &v) == 1 && v >= 0 && v <= 10) setenv("PS5_FSR_SHARP", std::to_string(v).c_str(), 1);
      std::fclose(sf);
    }
  }
```

(`std::to_string(rs).c_str()` inside the ternary is a temporary that lives until the end of the full expression, which includes the
`setenv` call, so it is valid.) The refresh value is 60 (locked). No other file changes. The relaunch flow (`relaunch_self`) re-runs
`main`, so a changed setting is picked up at the next game start.

## Driver (ps5-opengl, Mesa 26.2 gallium ps5) feature list and risk

Used GL, all plain: `glCreateShader/CompileShader/LinkProgram/BindAttribLocation/GetUniformLocation/Uniform*`, `#version 410 core`
fragment shaders with `sampler2D`, `texelFetch` (LOD 0), `textureSize`, `gl_FragCoord`, `floor/clamp/min/max/inversesqrt`,
RGBA8 `glTexImage2D` render targets (`glFramebufferTexture2D`, `glCheckFramebufferStatus`), pooled `make_fbo` targets with
`GL_DEPTH24_STENCIL8` renderbuffers (the existing code path), `glTexParameteri` NEAREST/CLAMP. No compute, no image load/store, no
`textureGather`, no UBO/SSBO, no MRT, no `glBlitFramebuffer` with scaling (the old msaa resolve blit is untouched).

Risks, in the order I would check them:

1. Sampling a texture that was just a render target in the same frame with `texelFetch`: the old blit already samples
   `render_buffer`; the new second sampling is of the RGBA8 intermediate right after rendering to it (EASU then RCAS). The driver's
   render-to-sampler hazard handling (barrier/cache flush between the two passes, patch 51 touched alias checks in the multi-draw
   path) must cover it. Symptom: RCAS output stale or half-updated tiles. Workaround: `PS5_FSR_SHARP=0` (no second pass).
2. Rendering to an FBO without depth (the intermediate) after FBOs with depth: existing code already does this (`framebuffer_sample_fbo`).
3. First-use shader compile of two fragment shaders on the console (hitch of some ms). With AUTO it happens at the first present at
   scale below 100, not at prewarm (prewarm allocates targets only). The Mesa shader cache (`PS5_SHADER_CACHE_DIR`) should remove it
   from the second run on; a possible improvement is to call `fsr_build()` in the prewarm block.
4. `gl_FragCoord` origin/convention: shaders assume lower-left origin with pixel centers at +0.5 (GL default). If the ps5 driver
   flips Y for window FBO 0 only, the final pass would be upside down or shifted by one pixel in the RCAS-to-window pass; the
   harness cannot show that. The engine's own screen blits do not depend on `gl_FragCoord`, so this is a new assumption. Check in the
   first screenshot.
5. Memory: 4K output with AUTO holds the native 4K target (66 MB with depth/stencil) plus 83/67/50 percent targets (about 93 MB) plus the
   33 MB RGBA8 intermediate. 1440p is 0.44 of that, 1080p 0.25. If the driver's pool is tight, set `PS5_FSR_PREWARM=0` (targets
   appear lazily at the first switch) or `PS5_FSR_MIN=67`.
6. Precision: Mesa on the console compiles `float` as fp32 by default; no `mediump` is used.
7. Game side assumptions about the render size. Jak 2/3 `BlitDisplays` copies the render FBO into a game-usable texture and records
   `render_fb_w/h` as the texture size. Effects that use pixel coordinates of that texture (blur, screen distortion, glow
   probes) should scale with it, but I did not audit the GOAL code that uses the texture. Look for wrongly sized or offset
   fullscreen effects (water refraction, blur on pause, fades) at 67 and 50 percent.
8. `DepthCue` (Jak 2) uses `draw_offset/draw_region` against the render FBO; the patch rescales them to render pixels. Only
   meaningful if `game_res` equals the window size, which is the intent today.
9. CPU bound frames do not get faster. `PERF_JOURNAL.md` shows 17 to 28 us per draw in the driver; the verification step of the
   controller exists for this. Expect AUTO to help only after the CPU cost is below the budget (Phase 2 of `PLAN_60FPS.md`), or in
   GPU heavy scenes (Jak 2 with a one pass type of 7.5 ms, 4K output).

## Verified offline (2026-10-24, WSL Ubuntu, Mesa 25.2 llvmpipe, GL 4.5 core)

- `glslangValidator`: `fsr.vert` and both `fsr.frag` variants compile.
- `fsr/test/fsr_ref.py`: the shaders run on llvmpipe (EGL surfaceless context, same define splicing as the C++, EASU into RGBA8 then
  RCAS from that texture) against a numpy implementation written in a separate vectorised form. Three cases (160x90 to 192x108,
  128x72 to 256x144, 333x187 to 640x360, sharpness 0.2/1.0/0.5 stops, with edges, circle, thin lines, noise): maximum difference
  1 level of 255, no pixel above 2, `PASS worst error 1`. This checks the GLSL against my reference, not against AMD's code (same
  author, same memory). The shader's `out_origin` is only tested with 0.
- Quality sanity check (synthetic checker/disc/line scene, 67 percent): PSNR to the full resolution image nearest 24.6 dB, bilinear
  26.1, EASU 26.2, EASU+RCAS 26.0 (RCAS adds contrast, which PSNR punishes). So on this scene EASU is only slightly above bilinear;
  FSR's gain is mostly on edges and fine detail in real images and is not demonstrated by this test.
- `patch_fsr.py` applies to a copy (`~/fsr_src`) of the live tree, applying twice prints "already patched", the patched
  `OpenGLRenderer.cpp` compiles with the real console toolchain command from `build.ninja` (`prospero-clang18`, private output
  `~/fsr_out/OpenGLRenderer.o`, no errors) and with host `g++ -fsyntax-only`.
- `fsr/test/ctrl_sim.py`: controller scenarios listed above, using the controller code extracted from the patched file.

## Not verified

- Nothing was linked or run on the console; no fps or image measurement exists.
- The ps5 driver behaviour for the items in the risk list; EASU cost on the PS5 GPU (12 fetches and about 150 ALU per output pixel at
  4K; RCAS another 5 fetches; both are bandwidth light but not free: expect roughly 0.5 to 1.5 ms at 4K, a guess).
- That the real `R` and `P` of this port behave as the simulation assumes (render duration includes GPU back pressure, the flip wait
  happens after `render()` returns). If the flip wait were inside `render()`, `R` would sit near 16.7 ms permanently and AUTO would
  step down in every scene; then raise `PS5_FSR_TARGET_MS` to 17.5 or look at `P` only.
- Jak 1 (the `glClear` path with the window framebuffer) and the Jak 2/3 game side texture effects at reduced size.
- Resolution changes while the game is running (the launcher applies them at start only).

## Console test plan

Run one case at a time on a build with the patch, game scenes as in `PERF_JOURNAL.md` (Jak 2 city, Jak 3 gameplay, Jak 1 intro). For
each case record fps (`last_run.log` / tracer), a screenshot at the same camera position (`shot.py`), and the log lines `fsr:`.

1. Regression: `PS5_RENDER_SCALE` unset. fps and screenshot must equal the build without the patch (the scaled path is not entered).
2. Plumbing at 1080p: `renderscale.txt` = 67 with `nofsr.txt` (scaled render, plain bilinear blit): picture must be a
   blurry but correctly framed and colored copy; check fades/brightness. This isolates the render-size change from the shaders.
3. Same with FSR: remove `nofsr.txt`, `fsrsharp.txt` = 0 (EASU only) then 7 (EASU+RCAS). Compare the screenshots to case 2 and to 100 percent.
   Y orientation, one pixel shifts, border at letterbox edges (risk 4), RCAS tile artifacts (risk 1).
4. Fixed scales 83, 77, 67, 50 at 1080p, 1440p, 4K output (`resolution=0/1/2` in `ps5.cfg`): fps per scene and per scale. Expected
   shape: GPU bound scenes gain roughly with the pixel ratio (67 percent = 0.45 of the pixels), CPU bound scenes (Jak 3 530 draws)
   gain nothing. Record the GPU time of the final pass (the `pcrtc` node of the `ptree` log lines).
5. Game side effects at 67 and 50: Jak 2 water/refraction, pause blur, fades, glow, Jak 3 equivalents (risk 7).
6. AUTO (`renderscale.txt` = 0) at 4K output in the heaviest scene: look at the `fsr:` log lines. Required: no more than one change
   per 3 s in steady play, no oscillation, returns to 100 in light scenes, no visible hitch on a change (frame time trace around the
   change: the 6 settle frames), memory stable after prewarm.
7. Tuning if AUTO behaves badly: `PS5_FSR_TARGET_MS`, `PS5_FSR_MIN`, `PS5_FSR_PREWARM=0`; the constants (window 30, 1.08, 0.8, backoff 6) are
   in `fsr_frame_begin`.
8. Soak: 30 minutes AUTO in each game, check for memory growth (pool is bounded to 4 targets plus the intermediate) and for GL errors in the log.

## Notes for the session that owns the live trees

While preparing this I ran `patch_fsr.py` once by mistake without `FSR_SRC` against the live `~/jak` (the first version defaulted to
it) and reverted it within the same session: the 11 replacements were reversed exactly (re-applying to the reverted copy reproduces
the accident state byte for byte; `OpenGLRenderer.h` is again identical to git HEAD, `OpenGLRenderer.cpp` has no `fsr` text and only
the earlier non-FSR local changes). The only side effect is new modification times on `OpenGLRenderer.h/.cpp`, which makes ninja
rebuild everything that includes the header. The script now refuses to run without `FSR_SRC`. A copy of the state at that moment is
in `~/fsr_backup/`.

## v2 (2026-10-24): console report "image drawn 1:1 in the bottom-left corner" and the diagnostic

Report: Jak 2 title, `PS5_RENDER_SCALE=67`, scene shown at 0.67x in the bottom-left of the 1920x1080 window, rest black; render size, `win_*`
and `rw` were right at `setup_frame`.

Root cause: **not proven.** Reading the patched live `OpenGLRenderer.cpp`, `ps5shim/glfix.cpp` and the game sources found no
definite bug. What the symptom means: the output is exactly what EASU produces when its source size equals its destination size
(scale 1) and everything outside the source is fetched as black, or what a plain 1:1 copy of a 1920x1080 texture holds when the scene
was rendered into its corner. Checked and ruled out by reading: game scissor (no `glScissor`/`GL_SCISSOR_TEST` anywhere in
`game/graphics`), viewport at the final pass (`glViewport(win_x, win_y, win_w, win_h)` right before `fsr_present`, then again inside
it), `window_blit_src` (= `m_fbo_state.render_fbo`, the pooled target, `msaa == 1`), `glfix.cpp` (wraps `glDrawArrays` strips into an
indexed draw, `glClear` on the window FBO, `glTexImage2D`, `glFramebufferTexture2D`, none touch viewport or sizes), Y flip (cannot give a
1:1 corner). Not checkable offline: the ps5 driver's handling of `glUniform2f`, `glGetUniformLocation` for these programs, the
size it really allocates for the pooled texture.

v2 changes (`patch_fsr.py`, `fsr/fsr.frag`):
- Shaders take their sizes from two `vec4` uniforms (`dims` = source and destination size, `misc` = origin and RCAS scale) set with
  `glUniform4f`, the call the engine's own post-processing relies on, instead of four `vec2`/`float` uniforms. Source size is passed
  from the CPU, not `textureSize`.
- `glDisable(GL_SCISSOR_TEST)` at the start of the pass.
- `fsr_present` writes one line every 300 calls to `/data/opengoal/log/fsrdbg.txt` (append, via `fopen`).

Reading the line (`fsr frame ... `):
| Field | Meaning, and what it tells |
| --- | --- |
| `src fbo/tex WxH (GL says WxH)` | pooled target size we believe vs the size the driver reports. `GL says 1920x1080` = the driver ignored the allocation size: the scene sits in the corner of a full size texture and the bug is in the render target, not the shader. |
| `win x,y WxH`, `mid WxH (GL WxH)` | draw region and intermediate size; they must be 0,0 1920x1080. |
| `viewport easu`, `rcas` | `glGetIntegerv(GL_VIEWPORT)` taken right before each draw. Anything but the window rectangle = state override (driver or shim). |
| `scissor 0/1 box` | scissor enable and box after the pass. |
| `prog`, `drawfbo` | current program (the RCAS program id when RCAS ran) and draw FBO (0 at the end). |
| `loc easu ... rcas ...` | uniform locations in order src, dims, misc, color_mult, color_add. `-1` for `dims`/`misc` = the driver lost them (then the shader runs with zero sizes). |
| `px window@3/4`, `@1/4` | RGBA of the window at 3/4 and 1/4 of the draw region after both passes. For a correct upscale both are scene colors; for the reported symptom 3/4 is `0,0,0,x` and 1/4 is scene. |
| `px mid@3/4`, `@1/4` | same for the intermediate after EASU only: black at 3/4 means EASU itself ran at scale 1 (check `dims`, `loc`); scene at 3/4 and black in the window means RCAS or the window write is wrong. |
| `px src@1/4` | source texel at a quarter of the render target (should be scene). |
| `glerr` | `glGetError` after the pass. |

Fast discriminator needing no log: create `nofsr.txt` (scaled render, plain bilinear blit of the same target). If that still shows the
corner image the render target / viewport is at fault; if it fills the screen the problem is in the FSR shaders or their uniforms.

Upgrading a tree that already has the v1 patch (and the temporary `FSRDBG` line):
`FSR_SRC=~/jak python3 patch_fsr.py --reset`. It removes the exact v1 edits (list kept in `patch_fsr_v1.py`, which must stay next to the
script; reversal verified byte exact against the saved v1 state apart from the shader text), deletes lines containing `FSRDBG`,
then applies v2. Without `--reset` an old patch makes the script refuse. A v2 tree prints "already patched". Tested on a copy of the live
`OpenGLRenderer.cpp/.h` (v1 + FSRDBG); the result compiles with the console toolchain and `glslangValidator`; `fsr_ref.py` still passes with the new uniforms
(worst error 1).
