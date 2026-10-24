# Performance

What was measured, what changed in the driver and the shim, how to measure, and what to avoid. All numbers: 1080p, vsync 60 Hz, tracer window
only, unless noted. Raw output of a run is in `out/perf_runs/` (git-ignored).

## Current state

| Game, scene | Default before the work | Now (shipped defaults) | Limit |
|---|---|---|---|
| Jak 1 intro | 58 to 60 fps | not re-measured since the driver work | vsync |
| Jak 2 city (about 1970 driver draws per frame) | 21 to 32 fps | 50 to 58 fps | CPU: 8 to 15 us per draw in the driver |
| Jak 3 gameplay (about 530 draws) | 39 to 43 fps | 59 to 60 fps, about 3 frames per 3 s over 20 ms | vsync |

Jak 3 sits at the display limit. Jak 2 is CPU bound; resolution changes do not help it (1440p and 4K output measured the same on Jak 3, so the GPU pixel cost is
not the limit either). 4K output is slower than 1080p on the GPU side.

## What made the difference

| Change | Switch (config flag file) | Effect |
|---|---|---|
| Async multi-draw: `glMultiDrawElements` batches are queued instead of submitted synchronously | default on, `noasyncmultidraw` turns off | Jak 3 43 -> 58.7 fps (`submit_lock` waits 1.7 ms -> 0, driver 21-28 -> 9 us per draw); Jak 2 32 -> 44 |
| Draw merging in the shim (`glfix.cpp`): compatible draws are gathered with a fresh `glBufferData` per gather | default on, `nomerge` turns off | Jak 2 45 -> 55 to 58 fps; Jak 3 stays 59 to 60. An orphan plus `glBufferSubData` variant ran at 14 fps: keep the fresh upload |
| Deferred draws may sample other mip levels of a render target texture (level-range test instead of whole-texture alias) | default on | removes about 15 refused triangle-fan draws per frame in Jak 3 (the GPU mip blits) |
| Small mip levels generated on the GPU (`PS5_GPU_BLIT_MIN_PIXELS=1`) | compile-time, in `drv_cc_cache.sh` | without it every small animated texture took the CPU path with a full GPU wait |
| Glow depth fix: `w_glTexImage2D` turns `GL_DEPTH_COMPONENT` into D24S8 for the probe texture | `PS5_NO_DEPTH_FMT_FIX` env turns off | glow sprites no longer show through solid objects (the driver rejected the format-changing depth blit, so the probe stayed cleared) |
| Queue 16 batches of 128 draws (compile time) | `PS5_INFLIGHT_BATCH_CAPACITY` | fewer frames over 33 ms in Jak 3 (0 against 0 to 2 per 3 s) |
| Lazy mips (`mipfast3`) | off by default, launcher option "Lazy mipmaps" | about +2 fps in Jak 2 (driver 8.6 -> 7.7 ms per frame); distant surfaces may flicker |

No effect, left off: `clflushopt` fast flush, wait granularity 100 us, worker diagnostics, async swap, triple buffering, per-draw cost reductions
(`drawcost`, `rtfastflush`) without async multi-draw. Details of every switch: [`driver/README.md`](../driver/README.md).

Where the time goes (Jak 2 city, 1970 draws, tracer on): `ps5_draw_vbo_locked` 10.2 ms (constant preparation 2.3, descriptor table flush 2.1,
texture preparation 0.7, state and variants about 2), glfix 3.3, descriptor copy 0.7, batch submit 1.8. Getting below about 8 us per draw is the way to
60 fps in Jak 2.

## Measuring

```
tools/ps5 perf round jak2_x jak2 90 trace            # one run: saves out/perf_runs/jak2_x.{udp.log,console.log,summary.txt,trace_*.bin}
tools/ps5 perf round jak3_x jak3 190 trace nomerge   # more flags after "trace"; all other flag files are removed first
tools/ps5 perf suite jak3 190 base "" nomerge nomerge # several labelled flag sets in a row
tools/ps5 perf trace stats out/perf_runs/jak2_x.trace_1.bin -   # per-frame breakdown ("-" = statistics only)
tools/ps5 perf trace stages|mip|multidraw <trace.bin>          # per-draw driver stages, mipmap cost, queue behaviour
```

The second argument of `perf trace stats` is an output file for Perfetto JSON; pass `-` for statistics only, never a trace path.
Flags known to `perf round`: `nomipcpu nomultidraw gputrace profile spinwait trace syncdebug asyncmultidraw asyncswap triplebuffer presentlog drawcost
rtfastflush diag nomerge noasyncmultidraw shotscreen mergestats mipfast mipfast3 waitus100 workerdiag`, plus `res1440` and `res4k`.

Rules for numbers that hold up:

- Use the tracer (`trace.txt` = `start duration` in seconds; Jak 3 needs `100 7`: the first process is the launcher). Not `gputrace` (costs about 10 fps by
  itself, and produced the early "12 to 16 ms retire waits"), not the sampling profiler (return addresses are guessed; it blamed cache flushes and
  `nanosleep` wrongly).
- Compare the same scene: Jak 2 starts in the intro and reaches the city after about 40 s; Jak 3 is driven into the new game by `rplay.py`, gameplay after about 100 s.
- The first run after a deploy has hitches (shader cache rebuild): do a warm-up run. A driver rebuild invalidates the cache.
- Stale flag files made baseline runs invalid more than once: `perf round` clears every flag it knows before setting yours.
- The shim forces the game size to the output size, so a 900p "internal resolution" test is invalid without the FSR patch ([`FSR.md`](FSR.md)).
- The kstuff flag reading `0xffff` is normal on 13.60. Never write `0xdeb7`: it corrupted the state and hung the console userland.

## Pitfalls

- Extra static arrays in `ps5_screen.c` plus a shim block once made the app crash at start (SIGSEGV in libc++ iostream init writing to `.init_array` in the
  RELRO region), probably a layout fragility in `ps5-pie.ld`. Function-local `static int` scalars were fine. Change array sizes and pools one at a time and boot-test.
- The app build does not notice a changed driver object or `libgk.a`: `tools/ps5 build` and `app/rebuild_all.sh` touch the app entry for you.
- `deploy` fails with "Text file busy" while the app runs: kill first (`tools/ps5 go` does).
- The console's FTP server has no `NLST`; use `LIST`.
- In heredocs through some tool layers `\n` becomes a real newline: write scripts with an editor.
- `drv_cc.sh` (plain) builds without the shader cache id and GPU mip blits: do not deploy those objects.

## Open

- Jak 2 city is CPU bound at about 14 us per draw in the driver; the target is under 8 us.
- Remaining slow frames in Jak 3 (2 percent): `glGenerateMipmap` 2 to 7 ms, async-collect and batch submit up to 10 ms when prep workers are descheduled,
  backpressure 6 ms.
- A near-constant 7.7 to 8.0 ms GPU group per frame in Jak 3 is unexplained.
- Visual glitches in places: classify with `syncdebug` and screenshot comparison (`tools/ps5 shots`, `tools/shotdiff.py`).
- Hover music (`snd0.at9`) stutters on the console with the encoder in `tools/at9enc/`; the leading hypothesis is that the hardware decoder expects fixed
  128-byte frames while the encoder emits variable-length ones (126 to 334 bytes). Not tested. The file is derived from a copyrighted track and is never shipped.
- Remote Play without PSN was tried (pairing works, every session request is answered with an application error); not pursued.
