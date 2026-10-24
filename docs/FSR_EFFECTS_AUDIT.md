# FSR and screen-space effects: audit and the "dark JAK II logo"

Status 2026-10-24. Source: a copy of the live `~/jak/game/graphics` (patch_fsr.py v2 applied) in `~/fsr_audit`. Line numbers refer to that copy
(`OpenGLRenderer.cpp` = patched file, so its numbers are not the upstream ones). Nothing here was run on the console. Read `docs/FSR.md` first.

## 1. The dark logo is not a render-size bug (most likely: different moment of the intro)

Evidence from the screenshots already in `perf_runs/shots/` and the console logs:

| Run (all Jak 2, same build family) | scale | shot taken at (position of `captured` in the console log / run length) | what the picture shows |
| --- | --- | --- | --- |
| `fsr_0` -> `fsr0_0.png` | 100 | line 1525 of 1887 = about 61 s of 75 s | bright orange logo, "Press the Start Button", camera pulled back |
| `fsr_67b` -> `fsr67b_0.png` (v1 patch, image in the corner) | 67 | line 1477 of 1822 = about 61 s of 75 s | bright orange logo with the two faces, "Press the Start Button" |
| `fsr_v2b`, `fsr_v2c` -> `fsrv2_0.png`, `fsrscr_0.png` | 67 | line 936 of 1346 / 1031 of 1426 = about 38 to 40 s of 55 s | brown "JAK", black "II", no "Press the Start Button", camera closer |

So (a) the same 67 percent render with the v1 shaders shows the correct logo, and (b) the dark shots were taken about 20 s earlier in the run than
the bright ones. The title is the scene `title-disk-intro` (`goal_src/jak2/levels/title/title-obs.gc:139`: `(send-event "jak-logo" 'color-mult 0 0 0 1)`;
the lightning sequence at lines 173-343 then raises the colour; `:post` at line 703 copies `color-mult x` into the brightness of the light spheres
"big-title1/2"). The logo is a merc model (`skel-jak-logo`, line 59) lit only by those light spheres, so before the sequence has run it is exactly what the
dark shots show: ambient light only, "JAK" brown and "II" black, with the lilac rim light. The "Press the Start Button" text appears when the sequence is done.

What a render-size problem would have to do, and why nothing in the code can: the logo path is Merc2 (`foreground/Merc2.cpp`, `shaders/merc2.*`,
`emerc.*`) and `Generic2`. None of them reads the framebuffer, the viewport or any size (grep result in section 3). The only code that changes
colours based on the frame is `BlitDisplays` (copy, zoom blur, slow time, colour filter), `DepthCue` and the final pass, and those are either not active in the title
or were correct in the v1 shot. The v2 changes touched only the final pass; they cannot darken one model.

Not proven: I did not see the game clock of the two runs. The test that settles it costs one run: shots at 3 times in the same run (see section 5, test 1) at 67 percent
and at 100 percent. If the logo is dark at 61 s at 67 percent but bright at 61 s at 100 percent, this analysis is wrong and the next suspect is the pooled FBO itself
(`fsr_slot` / `make_fbo`), compare `perf_runs/fsr_v2c` pixel values of the `px src@1/4` line in `fsrdbg.txt`.

## 2. What is a render pixel, what is an output pixel

| name | unit | where set |
| --- | --- | --- |
| `settings.game_res_w/h` | game resolution (output pixels of the window in practice) | `pipelines/opengl.cpp:667-689` |
| `settings.window_framebuffer_w/h`, `draw_region_w/h` (RenderOptions), `m_fsr.win_*` | window pixels | `opengl.cpp:519-524`, `OpenGLRenderer.cpp:1879-1882` |
| `render_state->render_fb_w/h`, GL viewport during the frame, `render_fbo->width/height` | render pixels (smaller when scaled) | `OpenGLRenderer.cpp:1891-1895` |
| `render_state->draw_region_w/h`, `draw_offset_x/y` | render pixels (rescaled by patch_fsr v2) | `OpenGLRenderer.cpp:1883-1889` |

## 3. Audit of every use

Verdicts: OK = correct at any render size; BREAKS = wrong below 100 percent (fixed in `patch_fsr_effects.py`, "fx"); CHECK = reading cannot decide.
A grep over all of `game/graphics` for `game_res|render_fb_|draw_region|draw_offset|window_framebuffer|glViewport|glScissor|GL_VIEWPORT|glBlitFramebuffer|glReadPixels|glCopyTexSubImage2D|gl_FragCoord|dFdx|glPointSize|glLineWidth|LOD_BIAS`
lists every site below; `glScissor`, `GL_SCISSOR_TEST`, `glCopyTexSubImage2D`, `glPointSize`, `glLineWidth`, `dFdx/dFdy/fwidth`, `textureLod` and `TEXTURE_LOD_BIAS` do not occur at all.

### OpenGLRenderer.cpp / BucketRenderer.h (patched file)

| site | what | verdict |
| --- | --- | --- |
| `BucketRenderer.h:72-82` | fields `render_fb_x/y/w/h`, `draw_region_w/h`, `draw_offset_x/y` | OK (they carry render pixels after v2) |
| `OpenGLRenderer.cpp:1776-1782` | `rw/rh` from `game_res * pct / 100`, even, at least 64 | OK |
| `:1784-1830` | render FBO choice (pooled target / `render_buffer`), prewarm | OK |
| `:1838-1855` | Jak 1: clear of the window FBO with window size, then clear of the render FBO | OK (window clear uses window size, render clear is size independent) |
| `:1859-1889` | draw region/offset in window px, then scaled by `rw/game_res_w` (`lround`) | OK. `offset + region` cannot exceed `rw`: with letterbox the offset sum is `W - o` scaled, without it `o = 0` and `W * sx = rw` exactly. |
| `:1891-1895` | `render_fb_*` and `glViewport(0,0,rw,rh)` | OK |
| `:1608-1623` | screenshot source and region (`render_fbo->width`, `draw_offset`) | OK: `fsr_scaled` is false when `save_screenshot`, the frame renders at full size |
| `:2195` | `glReadPixels` in `finish_screenshot` | OK, same reason |
| `:2227-2250` | MSAA resolve blit uses `render_fbo->width/height` | OK (MSAA forces 100) |
| `:2251` | final viewport `win_*` | OK (window pixels, intended) |

### DepthCue (Jak 2 only; `DepthCue.cpp`)

| site | what | verdict |
| --- | --- | --- |
| `:295-307` | setup cache keyed on `draw_region_w/h` | OK (render px, so a percent change re-runs setup) |
| `:369-376` | sample texture sized `draw_region` | OK |
| `:388-408` | depth-cue FBO sized `draw_region * res_scale` | OK |
| `:540-551` | `glBlitFramebuffer` from `render_fb` at `draw_offset/draw_region`, 1:1 | OK (both in render px). Like upstream it assumes `game_res == window size`; not a scale issue |
| `:574`, `:611-612` | viewports of the two passes; the second one is left set to the region after the effect | OK (same as upstream; DirectRenderer reads the viewport, see below, and the region equals the full target when there is no letterbox) |

### Glow (`sprite/GlowRenderer.cpp`)

| site | what | verdict |
| --- | --- | --- |
| `:527-541` | probe FBO textures re-allocated when `render_fb_w/h` differ (colour RGBA8, depth `GL_DEPTH_COMPONENT`) | OK for a fixed scale: the same re-allocation already happens on the first frame of stock (`GlowRenderer.h:108-109` starts at 640x480). CHECK in AUTO: one re-allocation per percent change (hitch) |
| `:547-557` | depth blit `0..render_fb_w/h` into the probe FBO, 1:1 | OK |
| `:591`, `:626`, `:669`, `:748` (+ restores `:598 :634 :674 :771`) | viewports of its own FBOs, old viewport restored | OK |
| `shaders/glow_probe*.vert/frag` | probe quads in NDC, result is a ratio after a fixed-size downsample grid | OK (at 67 percent a probe covers fewer pixels, so the visibility fraction is quantised more coarsely; CHECK visually for flickering flares) |

### Sprite distort (`sprite/Sprite3_Distort.cpp`, shaders `sprite_distort*`)

| site | what | verdict |
| --- | --- | --- |
| `:598-611` | copy of the whole render FBO into the distort texture, 1:1 | OK |
| `:626-641` | texture re-allocated to `render_fb_w/h`, called from `:480` and `:534` before use | OK |
| `shaders/sprite_distort.frag` | normalised texture coordinates | OK |

### BlitDisplays (Jak 2/3), `FramebufferCopier`, Warp

| site | what | verdict |
| --- | --- | --- |
| `BlitDisplays.cpp:49-52` | screen copy to the PC-BLIT texture, texture record gets `render_fb_w/h` | OK. I found no consumer of the record's size (`TextureAnimator.cpp:2300-2347` sizes only its own textures); CHECK for Jak 3 animation layers that source tbp 0x3300 |
| `:70`, `:81`, `:159`, `:185`, `:218` | copies for zoom blur, slow time, colour filter, all taken and used in the same frame | OK |
| `:94-107` | clears of window FBO 0 and render FBO | OK (size independent) |
| `:113-116` | **copy-back of the stored screen copy only if its size equals the render size** | **BREAKS in AUTO.** The copy is taken when the pause/progress menu opens (`pc-port 0x10`) and copied back every frame while the menu is open (`0x11`). A menu frame is cheap, so AUTO steps up while the menu is open; the sizes then differ, the copy-back is skipped and the background is black (the FB was just cleared at `:106`). Fixed scale and 100 percent are not affected. Fix: copy back with scaling |
| `opengl_utils.cpp:224-253` `copy_now` | re-allocates its texture when the size changes, blit 1:1 | OK (hitch on a percent change, CHECK) |
| `opengl_utils.cpp:255-269` `copy_back_now` | blits `m_fbo_width x m_fbo_height` to `render_fb_w x render_fb_h` with `GL_NEAREST` | OK at equal size; a scaled blit is what the fix uses (`GL_LINEAR`), see "unverified" |
| `Warp.cpp:11` | copy of the render FBO every warp bucket | OK; `Generic2_OpenGL.cpp:255-262`, `generic.vert:64-67` use normalised coordinates |

### Viewport consumers and own-FBO effects

| site | what | verdict |
| --- | --- | --- |
| `DirectRenderer.cpp:266-272` + `shaders/direct_basic*.frag` (`gl_FragCoord`) | GS scissor emulated with `game_sizes = (512, game_height, viewport w, viewport h)`, `w = vp_w / 512` | OK while the viewport is `(0,0,rw,rh)`. Scale independent. With a letterbox the viewport left behind by DepthCue (`:611`) is smaller than the FBO and the test is off; that is an upstream property, not a scale one |
| `Shader.cpp:11-23`, `shaders/*.vert SCISSOR_HEIGHT/SCISSOR_ADJUST/HEIGHT_SCALE` | GS to NDC mapping | OK (no pixel sizes) |
| `opengl_utils.cpp:84-101` `FramebufferTexturePairContext` | saves and restores viewport and FBO | OK. Users: `OceanEnvmap.cpp:198-199,259`, `OceanTexture.cpp:90,249,432`, `EyeRenderer.cpp:518`, `background/Hfrag.cpp:455`, `ProgressRenderer` minimap (offscreen mode), `TextureAnimator` |
| `SkyBlendGPU.cpp:131-132,203-204` | own FBOs, viewport and FBO restored | OK |
| `sprite/Sprite3.h:126` `fbo_width = 640` | initial value, overwritten by `distort_setup_framebuffer_dims` | OK |

### Pipeline, shim

| site | what | verdict |
| --- | --- | --- |
| `pipelines/opengl.cpp:448` | splash screen at window size | OK |
| `:519-553` | `RenderOptions`, screenshot overrides (`game_res = screenshot size`) | OK (a screenshot frame renders unscaled) |
| `:667-689`, `gfx.h:69-70` | `game_res` from settings | OK |
| `ps5shim/ps5sdl.cpp:477-521`, `glfix.cpp:832,1144` | timed shots read the FBO that `glfix` saw as the frame's main FBO with the window width and height | CHECK: with a scaled render the FBO is smaller than the window, so the read is out of range; that is what `shotscreen.txt` avoids (reads window FBO 0). Not changed here |

### No size use at all (read, grep clean)

`foreground/Merc2.cpp`, `Merc2BucketRenderer`, `Generic2*.cpp` (only the normalised warp mapping above), `Shadow2.cpp`, `ShadowRenderer.cpp` (stencil + full-screen quad in NDC),
`EyeRenderer.cpp` (own 32x32 FBOs), `background/Tie3, Shrub, TFragment, Hfrag`, `ocean/*`, `SkyRenderer.cpp`, `SlowTimeEffect.cpp` (NDC), `DirectRenderer2.cpp`,
`ProgressRenderer.cpp`, `TextureAnimator.cpp` (own FBOs; no read of the render FBO), `CollideMeshRenderer`, `Sprite3.cpp` (3D sprites in NDC), `Sprite3_Glow.cpp`.
Jak 1 uses none of BlitDisplays/Warp/DepthCue/glow-probe FBO sizes except Glow and the distort copy listed above; its only extra path is the window clear at `:1838-1855`.
Jak 3 adds Hfrag montage, darkjak/ocean/clouds texture animations, the minimap in `ProgressRenderer`; all render into their own fixed-size FBOs.
GOAL side (not C++): `sprite-distort.gc:135` and `warp.gc:27` / `sky-tng.gc:875` use fixed 512x512 tbp texture descriptors, i.e. normalised coordinates, so a smaller copy only needs the texture to hold the whole frame.

### Quality, not correctness (not implemented)

Textures are sampled with the same mip selection at a lower pixel density, so they look blurrier than "67 percent of the pixels" implies. FSR guidance is a negative LOD bias of
`-log2(output/render)` (-0.58 at 67 percent). The engine sets no LOD bias anywhere, and a bias has to go either into every fragment shader (`texture(t, uv, bias)`) or into every
texture object; both are wide changes with no way to test them offline. Listed as a follow-up.

## 4. `patch_fsr_effects.py`

Applies after `patch_fsr.py` v2, `FSR_SRC=<root>` (or `JAK_ROOT`), idempotent, anchors asserted (closest-line report on failure), `--emit-manifest` prints the manifest step.
Registered in `ports/manifest.json` as `fsr-effects` (required false, no `requires`: `patch_fsr.py` itself is not in the manifest yet and refuses to run under `JAK_ROOT`;
`fsr-effects` checks for the `ps5_fsr_v2` marker itself and stops with a clear message).

Edits (4): `BlitDisplays.h` flag `m_fx_have_copy`; `BlitDisplays.cpp` sets it at `0x10` and `do_copy_back` copies back also when sizes differ (if a copy exists and `PS5_FSR_FX` is not `0`);
`opengl_utils.cpp` `copy_back_now` uses `GL_LINEAR` when the sizes differ, `GL_NEAREST` otherwise (unchanged behaviour at equal size).
Switch: `PS5_FSR_FX=0` gives the old behaviour (the shim does not map a config file for it; propose `/data/opengoal/config/nofsrfx.txt` -> `PS5_FSR_FX=0` in `appmain.cpp` if wanted).
No new static data.

Verified: applied to a copy (`~/fsr_audit/root`) of the live tree, second run prints "already patched", diff reviewed (4 hunks in 3 files), `BlitDisplays.cpp`, `opengl_utils.cpp` and
`OpenGLRenderer.cpp` compile with the console toolchain command of `~/ps5build/build.ninja` (`prospero-clang18`, private objects in `~/fsr_audit/out`, no errors; warnings are off in that command).

Not verified: anything at run time. The one thing that is new for the driver is a `glBlitFramebuffer` with different source and destination size (colour, linear). Nothing else in the port
does that (every other blit is 1:1), and `FSR.md` lists "no `glBlitFramebuffer` with scaling" as a property of the current FSR code. Failure shows as a black or garbled menu background right after a
percent change, which is what happens today, so it cannot be worse; a crash is the unlikely worst case, disable with `PS5_FSR_FX=0`.

## 5. Console test plan (one case at a time, `shotscreen.txt` present so that timed shots read the real window image)

Use Jak 2 at 1080p, `renderscale.txt` as described in `FSR.md`. `shot.txt` takes several times, e.g. `30 45 61`.

1. Settle the logo question: 67 percent with `shot.txt` = `30 45 61`, then 100 percent with the same times. Compare shot 3 of both (must both be the lit logo with "Press the Start Button")
   and shot 1 of both (must both be the dark logo). If the 67 percent shot 3 is dark, the analysis in section 1 is wrong; send `fsrdbg.txt`.
2. Title at 83, 67, 50 (fixed), same three times; look at the menu text, glow of the torches, and the borders of the image.
3. Jak 2 city, same spot each time, 100/83/67/50: heat haze and water refraction (sprite distort), flares near lamps and the sun (glow; flicker at 50?), depth-of-field style blur (DepthCue, if active),
   fade to black and back (blackout renderer), pause menu open and closed (screen copy, black background = fail), zoom blur and slow time (power-ups, `BlitDisplays` 0x13/0x15), colour filter.
4. Jak 3 gameplay at 83/67/50: Dark Jak texture animation, water, minimap and progress menu, glow, distort.
5. AUTO (`renderscale.txt` = 0): open the pause menu in a light scene and wait about 20 s (AUTO steps up inside the menu): the background must stay visible. Repeat with `PS5_FSR_FX=0`
   (`nofsrfx` is not mapped; use a temporary line in `appmain.cpp`) to see the old black background, which also proves the fix is what changed it. Look at `fsr:` log lines for the step times.
6. Jak 1 intro at 67 and 50 (window clear path, glow, distort).
7. Per case record fps, the screenshots (same camera position, same game time), `fsrdbg.txt` line and any GL error line in the log.
