# Performance journal, 2026-10-23 session

Everything measured and changed in the session that rebuilt the toolchain and started the 60 fps work. Numbers come from `perf_runs/*`
(UDP log, console log, summary, tracer binaries). "Measured" means it is in those files; "assumed" means it is not.
Read `RUNBOOK.md` for how to operate the console and `PLAN_60FPS.md` for the plan.

## 1. Where things stand

| Game, scene (1080p) | Start of session | Now (default flags) | Best seen with test flags |
| --- | --- | --- | --- |
| Jak 1 intro | 58 to 60 fps | not re-measured | |
| Jak 2 city | 21 to 22 fps (this included the cost of the GPU trace) | 30 to 32 fps | 38 to 42 fps (`nomipcpu`+`nomultidraw`, pre mip fix) |
| Jak 3 gameplay | 39 to 43 fps | 43 to 46 fps | 51 to 52 fps (`nomultidraw`) |

Not yet 60 in either game. The user reports: menus are fine, in-game there are frame-time issues and many visual glitches (not catalogued yet).
Jak 3 was "reasonably playable" on the 43 to 52 fps builds. Nothing is committed to git.

## 2. Corrections to earlier statements (read these first)

1. `gputrace.txt` costs about 10 fps by itself (poller thread). Jak 2 measured 22 fps with it and 31 without. All "12 to 16 ms batch-retire
   waits" in the first rounds were largely produced by it. Never use it for fps numbers.
2. The sampling profiler (`profile.txt`) is unreliable: return addresses are guessed and samples bias towards syscall return points. The
   "cache flush 60 %" and "nanosleep 48 %" attributions were wrong. Use the tracer.
3. The kstuff flag at `sysentvec+14` reading `0xffff` does NOT mean kstuff is off on 13.60 (int3 hook, fake sysent tables). Writing `0xdeb7`
   corrupted the state and hung the console userland. Do not write it.
4. The rebuilt driver in this session had lost two compile flags of the original project: `-DPS5_GPU_BLIT_MIN_PIXELS=1` (small mip levels
   on the GPU) and the shader cache build id. Without the first, every small animated texture took the CPU mip path with a full GPU wait.
   `drv_cc_cache.sh` now carries both. Plain `drv_cc.sh` builds without them: do not use it for deployable objects.
5. The first Jak 3 "gameplay" traces were the launcher process (232 draws, 16.8 ms frames). The tracer arms per process; for Jak 3 use
   `trace.txt` = `100 7`.
6. Earlier I called the OpenAGC project Apache-2.0. `OpenProspero/AGC` is GPL-3.0 (compatible with this repo's GPL-3.0-or-later).

## 3. Findings (all measured unless marked)

### Jak 2 city, about 1250 draws per frame, default flags (perf_runs/jak2_t3)
- Frame 32 ms. Render thread: draw wrapper 25.5 ms (glfix 2.5 us per draw, Mesa 0.2 us, driver 17 us), async-collect spin 4.6 ms,
  batch-retire 1.7 ms, batch submit 1 ms.
- GPU full waits are small in this scene once the GPU trace is off. The bottleneck is CPU in the driver per draw.

### Jak 3 gameplay, about 530 draws per frame (perf_runs/jak3_t3 to t7, perf_suite results)
- Default: 43 fps (23.2 ms). Waits per frame: batch-retire 7.2 ms (1.2 events), backpressure 2.8 ms, async-collect 2.4 ms, `submit_lock`
  full waits 1.7 ms (74 per frame: the synchronous multi-draw path), batch submit 1.05 ms.
- Per draw: driver about 21 to 28 us.
- `submit_lock` callers (tracer event 113, symbolised): `ps5_draw_vbo` non-deferred path (draws refused by `ps5_try_deferred_draw`),
  `ps5_try_multi_draw_batch`, `eglSwapBuffers` (about 0 ms).
- Refusal reasons (events 114/115): 72 multi-draws per frame (`glMultiDrawElements`, triangles, 4-byte index) and about 15 triangle-fan
  draws per frame refused for TEXTURE. The fans were the GPU mip blits: sampling level N and rendering level N+1 of the same texture
  was rejected as an alias hazard. Fixed by patch 51 (level-range test).
- `nomultidraw` alone: 51.5 fps (19.4 ms). Remaining: backpressure 5.5 ms per frame (queue of 8 batches full), batch submit 2.3 ms
  (129 submits per frame), batch-retire 5.5 ms.
- Spin instead of sleep (`spinwait.txt`): no change. The waits are real GPU latency, not scheduler granularity.
- From the multidraw agent (assumed, from the traces): batches average 4.1 draws, 55 % of submits come from the flush at every multi-draw
  boundary, GPU busy about 8.6 ms of 19.4 ms, one 6 to 8 ms GPU group per frame whose near-constant length is unexplained.

### Mips
- With the restored flags all small mip levels run on the GPU (`mip: ... gpu=N cpu=0`), forced drains are 0. Jak 3 `glGenerateMipmap`
  still costs about 5 ms per frame on the render thread (before patch 51); the blit chain was synchronous.

### Console, network, tools
- Console on LAN since 18:5x: FTP deploy of the 41 MB eboot takes 1 s (was 40 s on Wi-Fi with 33 to 75 % packet loss; deploys timed out).
- Jak 2 `game-size` was 3840x2160 in `pc-settings.gc` (Jak 1 and 3: 1920x1080). Set to 1920x1080, backup `backup/jak2_pc-settings.gc`.
  The effect on fps was not isolated (the frame cost is CPU bound).

## 4. Driver and shim patches (repo root; apply order matters)

Applied to the live tree `~/gl/src/ps5-opengl` unless noted. All new behaviour is off by default unless stated.

| Patch | What | Status |
| --- | --- | --- |
| 42 | `ps5_fast_flush`: clflushopt loop and one `mfence` (CPUID detection) | applied, no measurable gain, keep |
| 43 | wait-site accounting (`ps5_driver_wait_sites`), `waits per frame:` log line | applied, on |
| 44 | `PS5_MIP_SKIP_CPU` (`nomipcpu.txt`): skip CPU mip level (stale mips) | applied, diagnostic only, obsolete after the flag fix |
| 45 | submit_lock caller table (several statics) | REVERTED: app crashed at start (see 6) |
| 46 | `PS5_NO_MULTIDRAW` (`nomultidraw.txt`) | applied, test flag, +8 fps in Jak 3 |
| 47 | trace hook `ps5_driver_trace_hook` and events 100 to 112 | applied |
| 48 | events 121 (gate2_run) and 122 (driver draw_vbo) | applied |
| 49 | event 113 submit_lock with caller address | applied |
| 50 | events 114/115 (deferred refused, reject bits) | applied |
| 51 | allow deferred draws that sample other mip levels of the render target texture | applied, on by default |
| 52 | `PS5_SYNC_DEBUG` sync mode for glitch classification (agent syncdbg) | applied, off |
| 53 | `PS5_ASYNC_MULTIDRAW` (agent multidraw; needs `fix53.py` after 52) | applied, off, under test |
| 54 | compile-time `PS5_INFLIGHT_BATCH_CAPACITY` / `PS5_MULTIDRAW_BATCH_CAPACITY` | NOT applied (layout change, test alone) |
| 55 | `PS5_ASYNC_SWAP`, `PS5_TRIPLE_BUFFER` (agent present) | NOT applied (changes pool layout, +32 MiB; test alone; `ps5_egl.c` is built by the SDK build, see agent doc) |
| 56 | `PS5_DRAWCOST` bit mask: viewport slot 0 only, descriptor flush with one fence, event 130 stage times (agent drawcost) | applied, off, under test |
| 57 | `PS5_RT_FAST_FLUSH`: workers flush with clflushopt and one fence | applied, off, under test |
| shim | `shim_patch_trace.py`, `shim_patch_trace2.py`: tracer core in `glfix.cpp`, frame tick in `ps5sdl.cpp`, event 11 around the real GL draw | applied |

Test flags (file in `/data/opengoal/config`, created and removed by `perfround.py`): `nomipcpu`, `nomultidraw`, `gputrace`, `profile`,
`spinwait`, `trace` (content `start dur` seconds), `syncdebug`, `asyncmultidraw`, `asyncswap`, `triplebuffer`, `presentlog`, `drawcost`,
`rtfastflush`. The mapping to environment variables is in `ps5shim/appmain.cpp`.

## 5. Tools added

| Tool | Purpose |
| --- | --- |
| `perfround.py label game secs [flags]` | one measured run, saves `perf_runs/<label>.{udp.log,console.log,summary.txt,trace_*.bin}` |
| `perf_suite.sh game secs label flags ...` | several flag sets in a row, prints a trace summary each |
| `trace2json.py trace.bin [out.json or -]` | per-frame breakdown, draw decomposition, full waits by caller; JSON for Perfetto. The second argument is the OUTPUT file: an agent overwrote a trace by passing a binary there |
| `ps5dbg_maps.py` | read-only client for the ps5debug protocol (port 744): process list, memory map, memory read |
| `m1/klog_dump.c` / `klog_all` | read `/dev/klog` live and broadcast lines over UDP 9999 (filtered or `-DALL`) |
| `arl.py` | client for the ActRemoteLink agent (Remote Play experiments, see 7) |
| `ps5.py` | `run` now writes `last_run.log` with every UDP line; works without the shell payload |
| agent tools | `shotseries.py`, `shotdiff.py` (screenshots and image diff), `trace_stages.py`, `multidraw_report.py`; docs in `agent_*.md` |

## 6. Pitfalls

- Patch 45 (extra static arrays in `ps5_screen.c` plus a shim block) made the app crash at start: SIGSEGV in libc++ iostream init
  (`_GLOBAL__I_000100`) writing to the `.init_array` start in the RELRO region. Probably a data layout fragility in `ps5-pie.ld`.
  Add new static data one change at a time and boot-test after each. Patches 43, 47 to 57 added only function-local `static int` scalars and
  one function pointer and booted fine; 54 and 55 change array sizes or pools: test them alone.
- `rebuild_all.sh` does not relink when only the driver object changed: `touch ~/ogapp/src/ogmain.cpp` first.
- `ps5.py deploy` fails with "Text file busy" while the app runs: kill first.
- In heredocs through the tool layer `\n` is turned into a real newline: write scripts with the editor tool.
- Do not run `ftplib` `NLST` on the console's ftpsrv (not supported); use `LIST`.

## 7. Unresolved

- Remote Play without PSN: pairing works (OnionHEN Toolbox PIN, Chiaki-ng 1.9.9 and 1.10.0, account id base64 `(redacted)`, ActRemoteLink
  fake-signin on slot 1 done, backups in `backup/` and `/data/arl_backup`), but every session request is answered with
  `RP-Application-Reason 80108b12` (wrong key gives `80108b26`). Cause unknown. `perf_runs`-style in-app streaming is the fallback idea.
- Hover music (`sce_sys/snd0.at9`): reference decoder LibAtrac9 (`at9enc/refdec.c`) decodes it without errors and identically to ffmpeg
  (opposite polarity); header and loop points valid. The user hears stutter ("15 fps"). Hypothesis: the hardware decoder expects fixed 128
  byte frames while the encoder packs variable-length frames (126 to 334 bytes). Not tested. A copy of the file is in `backup/`.
- Visual glitches in game: not catalogued. Plan: sync-debug mode plus screenshot diff, see `agent_syncdbg.md`.
- The 7.7 to 8.0 ms near-constant GPU group length: unexplained.

## 8. Next steps

1. Finish the patch suite on Jak 3 and Jak 2 (53, 56, 57 individually), then 55 (async swap, then triple buffer) and 54 (queue 16x128).
2. Bring per-draw CPU from about 17 to 25 us to under 8 us (agent drawcost: spin in the workers, descriptor flushes, state caches).
3. Dynamic internal resolution, then an FSR 1.0 final pass (MIT) for upscaling; DLSS is NVIDIA only, PSSR is PS5 Pro only.
4. Glitch triage with `syncdebug` and `shotdiff`; GL record and replay harness; a PC reference render if game data is available.
5. Commit the work (repo has many uncommitted files).

## 9. Results after patches 51 to 58 (evening of 2026-10-23, all 1080p unless noted, tracer window only)

| Run | fps | Notes |
| --- | --- | --- |
| Jak 3 default flags | 43.1 | 72 synchronous multi-draws per frame, `submit_lock` 1.7 ms |
| Jak 3 `asyncmultidraw` | 58.7 to 59.0 | `submit_lock` 0, driver 8.7 to 9.7 us per draw, backpressure 2.2 to 2.9 ms, retire 2.3 to 3.5 ms |
| Jak 3 `asyncmultidraw` + `asyncswap` / `triplebuffer` | 58.6 / 59.0 | no gain (patch 55) |
| Jak 3 `asyncmultidraw`, queue 16x128 (patch 54) | 58.7 | fewer frames over 33 ms (0 against 0 to 2 per 3 s) |
| Jak 3 `drawcost` / `rtfastflush` | 44.4 / 44.0 | no effect without `asyncmultidraw` |
| Jak 3 `asyncmultidraw` at 1440p / 4K output (framebuffer follows the output) | 58.2 / 59.0 | resolution independent: the GPU pixel cost is not the limit |
| Jak 2 default flags | 31.9 | |
| Jak 2 `asyncmultidraw` | 44.0 to 45.0 | CPU bound: about 1970 driver draws per frame, 14 to 15 us per draw |
| Jak 2 + `asyncswap` / `triplebuffer` | 42.1 / 40.5 | worse (scene draw counts differ slightly between runs) |

Jak 3 conclusion: with `asyncmultidraw` the game sits at the vsync limit; the average 58.7 comes from about 2 % of frames (3 to 6 per 3 s)
that exceed 20 ms. Worst-frame contributors in the trace: `glGenerateMipmap` 2 to 7 ms, async-collect and batch submit 10 ms
(prep workers descheduled), backpressure 6 ms. The 1600x900 test was invalid: the shim forces the game size to the output size
(`appmain.cpp kW/kH`), so there is no lower internal resolution yet.

Jak 2 per-frame cost (1970 driver draws, tracer on): `ps5_draw_vbo_locked` 10.2 ms (`prepare_constant` 2.3, `flush_descriptor_table` 2.1,
`prepare_texture` 0.7, state and variants about 2), glfix 3.3, descriptor copy 0.7, retain 0.3, eligibility 0.2, batch submit 1.8.

State left on the console: `asyncmultidraw.txt` on, all other test flags removed, `ps5.cfg` resolution 0 (1080p), queue 16x128 build deployed
(`drv_cc_cache.sh` with `PS5_EXTRA_DEFS` and `EXTRA` for the backend must use identical values). `drv_cc_egl.sh` builds the EGL layer that is linked before the SDK
library (needed only by patch 55; plain SDK EGL also works).

## 10. Session 2026-10-24: merge gather, glow depth fix

- **Merge gather (shim, `shim_patch_merge.py`)**: default ON (`nomerge.txt` disables). Only works fast with a fresh `glBufferData(total, data)` per gather;
  the agent's orphan + `glBufferSubData` variant ran at 14 fps. Jak 2 (asyncmultidraw, 1080p): 45 -> 55-58 fps. Jak 3 with merge: 59-60 steady,
  about 3 frames over 20 ms per 3 s. Screenshot compare: geometry identical, only animated parts differ.
- **perfround.py** removes every flag file in `FLAGS`; new flags (`nomerge`, `mergestats`, `mipfast`, `mipfast3`, `waitus100`, `workerdiag`) were added. Before
  that, stale flag files made some "baseline" runs invalid (jak2_m0, jak2_mg: no asyncmultidraw / stale merge).
- **Glitch: glow sprites visible through solid objects** (Jak 2 title: fireflies over the logo). Present with syncdebug, nomultidraw, nomerge -> translation bug.
  Cause: `GlowRenderer::blit_depth` re-specifies the probe depth texture as `GL_DEPTH_COMPONENT`/`GL_UNSIGNED_INT`, the render buffer is D24S8;
  `ps5_blit` rejects ZS blits with different formats (`ps5_blit_early_reject`), so the probe depth stayed cleared (0) and every probe passed.
  Fix in `glfix.cpp` `w_glTexImage2D`: data==NULL, internalformat 0x1902 -> D24S8 (`PS5_NO_DEPTH_FMT_FIX` env disables). Verified by screenshot.
  Open: other game paths may hit the same early reject; driver printf is not visible, consider a counter event.
- Pending tests: patch 59 (mipfast), patch 60 (waitus100, workerdiag); appmain maps `mipfast.txt`, `mipfast3.txt`, `waitus100.txt`, `workerdiag.txt`.

### 10.1 Patches 59/60 measured (2026-10-24, tracer on, merge on, asyncmultidraw)
Jak 3 (190 s): b0 59.1 fps (4.35 frames >20 ms per 3 s), waitus100 59.3 (4.0), mipfast 59.2 (3.6), mipfast3 59.8 (3.1), workerdiag 59.2 (3.6): all within noise, vsync limit. Keep defaults.
Jak 2 (90 s): b0 50.1, waitus100 51.0, mipfast 51.9, mipfast3 52.2 (driver ms/frame 8.6 -> 7.7). mipfast3 gives about +2 fps; stale 2x2/1x1 mips untested, not default.

### 10.2 FSR / dynamic resolution (2026-10-24)
`patch_fsr.py` v2 + `patch_fsr_effects.py` applied; `renderscale.txt` (33..100, 0 = auto) or ps5.cfg `upscale=` select the scale. Verified on Jak 2 at 67 %:
the final image fills the window, title logo correct (the dark logo seen earlier was the intro lightning sequence, not a render bug). No fps gain in Jak 2 (CPU bound, ~52 fps).
Timed screenshots read the render buffer unless `shotscreen.txt` exists (then the real window image). `shotseries.py request` no longer fails when stale shots exist.
