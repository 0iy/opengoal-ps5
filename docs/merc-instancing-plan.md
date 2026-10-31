# Merc instancing plan

Status: plan only, nothing built. Measured 2026-10-30 (Jak 2, `city_traffic`): 60 593 merc draws, 56 % duplicates inside one `do_draws` call
(same `first_index`, `index_count`, `texture`, `mode`), only 1.6 % consecutive and mergeable. Driver cost is about 7 us per draw.

## What the engine does now (Merc2.cpp `do_draws`)

Per draw: uniforms (`ignore_alpha`, `decal`, `gfx_hack_no_tex`, fog), `glBindTexture` when changed, light uniforms when `light_idx` changed,
`setup_opengl_from_draw_mode`, `glBindBufferRange(UBO 1, m_bones_buffer, first_bone, 128 mats)`, `glDrawElements`.
Per instance (model in the world) only two values differ: `first_bone` (offset into the 512 KB `m_bones_buffer`) and `light_idx` (light set).
Bone data is already one shared buffer, so the instances do not need new bone storage, only a way to index it.

## Design

1. **Group:** in `do_draws`, build runs of draws with equal key `(first_index, index_count, texture, mode, flags, no_strip, hash)` for the
   plain path only. Skip `MOD_VTX`, `set_fade` (envmap) and the `w1` fade two-pass path (they draw twice with changed uniforms).
2. **Order:** blended draws (`alpha_blend != off`) keep the original order, so group only draws that are adjacent after a stable sort limited to
   opaque modes first. Opaque and alpha-test draws are order-independent (depth test), so they may be pulled together. Blended draws stay as now.
3. **Per-instance data:** vertex attributes with `glVertexAttribDivisor(…, 1)` (location 6 = `first_bone`, location 7 = `light_idx`), filled
   from a per-frame instance buffer. No `gl_InstanceID` and no SSBO needed.
4. **Bones in the shader:** the `ub_bones` UBO window is only 128 mats. Replace by a buffer texture (`GL_TEXTURE_BUFFER`, `GL_RGBA32F`) over the same
   `m_bones_buffer`, read with `texelFetch(bones_tbo, first_bone + mat*8 + k)`. `#version 410` supports samplerBuffer.
5. **Lights:** same idea, `m_lights_buffer` into a second buffer texture (or a UBO array of 1024 light sets), index by the `light_idx` attribute.
6. **Issue:** one `glDrawElementsInstanced(mode, index_count, GL_UNSIGNED_INT, off, n)` per run. Runs of 1 use the old path (no change).
7. **Shader variant:** new `merc2_inst.vert` plus the existing fragment shader, so the old shader stays as fallback.
8. **Switch:** `/data/opengoal/config/noinstance.txt` turns it off (same style as `nodrawcache.txt`).

## Step 0 is a go/no-go test (about half a day)

Before any engine change, write a small test in the shim or a patch that draws the same mesh 50 times with `glDrawElementsInstanced`,
divisor attributes and `texelFetch` on a buffer texture, on the console. Check:
- the driver accepts it (no `unsupported` log, no CPU fallback; look at the `glfix` and driver log),
- GPU time per instance is about equal to a normal draw (buffer texture fetch in the vertex shader can be slow on some GPUs),
- `glfix` multidraw and draw front cache do not break instanced calls (`glDrawElementsInstanced` must be forwarded or wrapped).

If step 0 fails, stop. Fallback plan: leave merc as is.

## Steps after step 0

1. Engine patch `0050-merc-instancing.patch` + manifest step (marker `__ps5__ merc-instancing`), shader `merc2_inst.vert`.
2. Run `ps5scene run city_traffic city_idle city_tour --label inst-on`, then with `noinstance.txt` for the baseline, `ps5scene compare`.
3. Pixel check: `ps5.py shot` on the same teleport point with and without the flag; compare images (must be identical).
4. Check Jak 1 (merc2 is shared) and Jak 3 for a normal frame.
5. Tests: unit test for the grouping function (pure C++ or a Python port), `run_all.py` stays green.

## Expected gain and risk

- Gain: up to 56 % fewer merc draw calls. At 7 us per draw and about 5 to 10 ms merc time, roughly 2 to 4 ms per frame in the city, more in bad frames.
  Estimate only, not measured.
- Risks: wrong picture when blended draws reorder (handled by step 2 of the design); vertex-stage texture fetch cost; driver instancing
  support unknown (step 0); per-run bookkeeping CPU cost could eat part of the gain. Effort after a passing step 0: 1 to 2 days.

## Step 0 result (2026-10-30): GO

`app/shim/insttest.cpp` (flag file `config/insttest.txt`, runs once about 15 s after start, logs `insttest: ...`). 200 instances of a 1922-triangle
mesh, 3 bone fetches per vertex, offscreen FBO:

| Variant | total | CPU submit |
|---|---|---|
| UBO + glBindBufferRange + glDrawElements per instance (old path) | 1.70 ms | 1.46 ms |
| buffer-texture shader, one draw per instance | 16.3 ms | 12.2 ms (per-draw `glVertexAttribIPointer` is slow, do not use) |
| buffer-texture shader, ONE `glDrawElementsInstanced` | 0.17 ms | 0.06 ms |

All three images are byte-identical (38 912 lit pixels). Driver accepts buffer textures (`GL_RGBA32F`, max 1 048 576 texels), instanced `VertexAttribIPointer`
with divisor, `texelFetch` in the vertex shader. Caveat: the time includes `glFinish`, but GPU-side cost of a real merc scene (textures, blending) is not covered.

## Built and verified (2026-10-30)

Patch `engine/ports/patches/0050-merc-instancing.patch` (manifest step `merc-instancing`), glfix wrapper `w_DrawElementsInstanced`.
`config/noinstance.txt` is polled about every 10 frames (works while the game runs). Log line `merc-inst: per 600 flushes ...` shows the grouping.

- Grouping (Jak 2 city): 322 054 draws to 110 758 runs (-66 %), none left on the old path; Jak 3 cutscene about -20 %, Jak 1 about -19 %.
- Pixel check: frozen city (`(set-master-mode 'pause)`), 1920x1080 screenshots with instancing and without: byte-identical.
- Scenes, merc-l2-pris ms (before to after): city_idle 8.7 to 6.9, city_tour 8.6 to 6.9 (min fps 46 to 59, over 33 ms 0.9 % to 0 %), city_traffic 11-12 to 6-8.
- zoomer_fly paired runs: merc 7.2 (off) vs 6.0-6.5 (on), fps 51 vs 45-48: no gain, run-to-run noise is larger. Its remaining cost is not merc (unknown 5 ms, particles 3 ms, 2d 2 ms).
- Jak 1 (title) and Jak 3 (cutscene) start, render correctly, 59 fps, no shader errors.
