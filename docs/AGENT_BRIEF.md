# Brief for sub-agents (OpenGOAL-PS5 performance and correctness work)

Read this file fully first. You work for the main session; it owns the console and decides what gets applied.

## Project

Native OpenGOAL (Jak 1/2/3) on a jailbroken PS5 (fw 13.60). Rendering goes: engine OpenGL calls -> our GL interposition `ps5shim/glfix.cpp`
-> Mesa 26.2 state tracker -> our patched gallium driver `ps5_screen.c` -> async prep workers and AGC runtime
(`ps5_agc_native_runtime.c`, `ps5_agc_runtime_backend.c`) -> PS5 AGC command buffers. Read `docs/PERF_ANALYSIS.md`, `docs/PLAN_60FPS.md`,
`docs/HANDOFF.md` (repo root `<repo>`, WSL path `<repo-in-wsl>`).

Driver sources live in WSL (not in the repo): `~/gl/src/ps5-opengl/src/` (`gallium/ps5/ps5_screen.c` about 18.5k lines,
`platform/ps5_agc_native_runtime.c`, `platform/ps5_agc_runtime_backend.c` which includes the runtime, `egl/ps5_egl.c`,
`platform/ps5_scanout.h`). Changes are idempotent Python patch scripts in the repo root named `drv_patchNN.py` (see `drv_patch43.py`,
`drv_patch47.py`, `drv_patch51.py` for the style: a marker string makes a second run print "already patched"; every replacement is
asserted with `assert s.count(old) == 1`). Shim changes are `shim_patch_*.py` against `ps5shim/*.cpp`.
Build the driver with `bash drv_cc_cache.sh` (screen) and `bash drv_cc_backend.sh` (runtime), then `bash rebuild_all.sh` in WSL
(`wsl -e bash -c "cd <repo-in-wsl> && ..."`).

## Hard rules

1. Do NOT touch the console: no `ps5.py`, `perfround.py`, `rplay.py`, no FTP, no payloads, no ports 9021/2121/2323/744/9999. The main session
   runs every console test, one at a time. You may read `perf_runs/*` (logs, summaries, `*.trace*.bin`) and run `trace2json.py` on them.
2. Do NOT edit or run patch scripts against the live driver tree `~/gl/src/ps5-opengl` and do not edit existing repo files. Work in a
   private copy: `cp -r ~/gl/src/ps5-opengl/src /tmp/<yourname>_src` (copy only what you need) and make your patch script take the root from
   the environment variable `PS5_SRC` (default `~/gl/src/ps5-opengl/src`). Verify with `PS5_SRC=/tmp/<yourname>_src python3 drv_patchNN.py` and
   compile-check your changed file by running the clang line of `drv_cc.sh` / `drv_cc_backend.sh` with your private path and your private output
   file (never overwrite `~/drv/out/*.o`).
3. New files only, in the repo root or `docs/`: your patch script(s), tools, and one design/results document `docs/agent_<yourname>.md`.
4. Every behaviour change must be switchable at runtime by an environment variable (the shim maps `/data/opengoal/config/<name>.txt` files to
   env vars in `ps5shim/appmain.cpp`; you may propose that line, do not edit the file) and default to the current behaviour.
5. Known pitfall: driver patch 45 added several new static arrays and the app crashed at start (SIGSEGV in libc++ iostream init writing into
   the RELRO page). Avoid new static data where you can (use existing structures, stack, or one pointer); say in your document exactly which
   statics you add so the main session can test them one at a time.
6. Be honest: separate what you verified (compiled, read in the source, measured in the traces) from what you assume. Quote file:line.

## Deliverable format (your final message)

Short report: what you found, which files you created, how to apply and test (exact commands), what the expected effect is and how to
measure it (the tracer events and `perfround.py` flags are described in `trace2json.py`), risks, and open questions.

## Measured facts you can rely on

- Jak 2 city (1080p): about 31 fps, render thread 24 to 26 ms per frame for about 1250 draws (about 17 us per draw in the driver),
  async-collect spin 4.6 ms, batch retire 1.7 ms. Jak 3 gameplay: about 43 fps, 530 draws, 25 us per draw, batch-retire waits 7 ms,
  backpressure 3 ms (8 in-flight batches, `PS5_INFLIGHT_BATCH_CAPACITY` in `ps5_scanout.h`), 72 synchronous `glMultiDrawElements` per
  frame (`ps5_try_multi_draw_batch` takes `ps5_screen_submit_lock` = flush plus wait for everything in flight).
- The sampling profiler is unreliable. The GPU trace (`gputrace.txt`) itself costs about 10 fps. Use the tracer (`trace.txt`).
- Test flags that exist today: `nomultidraw.txt` (sub-draws take the deferred path, about +8 fps in Jak 3), `nomipcpu.txt` (obsolete
  after the GPU mip fix), `spinwait.txt` (no effect).
- In-game the user sees many visual glitches and frame-time issues; menus are fine.
