# Graphics driver

OpenGOAL-PS5 draws through the ps5-opengl SDK (BlackBearReloaded, GPL-3.0-or-later; the original repository no longer exists, a mirror with the identical release archive is [JVK3R/ps5-opengl](https://github.com/JVK3R/ps5-opengl)) (Mesa 26.2 with a gallium driver for the
PS5 GPU, AGC command buffers). This folder holds our changes to that SDK and the scripts that compile them.

| Path | Content |
|---|---|
| `ps5-opengl.patch` | all driver changes as one unified diff against the pristine SDK source (`-p1`, six files) |
| `build/setup.sh` | unpacks the SDK sources, applies the patch, creates the compile directory `~/drv` |
| `build/drv_cc_cache.sh` | compiles `ps5_screen.o` (gallium driver) the way the app ships it: use this one |
| `build/drv_cc_backend.sh` | compiles `ps5_agc_runtime_backend.o` (includes `ps5_agc_native_runtime.c`): AGC submit, prep workers |
| `build/drv_cc_egl.sh` | compiles `ps5_egl.o`, the EGL layer that is linked before the SDK library |
| `build/drv_cc.sh` | plain driver compile without shader cache and GPU mip blits; only used by the other scripts |
| `build/rc.txt` | compiler flags (lines 2-3) and defines (lines 4-5) taken from the SDK build |

## Why it is patched

The stock SDK is correct but synchronous: every draw waits for CPU-side preparation, and several GL paths drain the GPU. The patch keeps the
SDK behaviour as the default for anything it does not change and adds:

| Area | Change | File |
|---|---|---|
| Draw batching | deferred draws may sample other mip levels of a render target texture; multi-draws are queued asynchronously (`PS5_ASYNC_MULTIDRAW`); batch capacity is a compile-time setting | `ps5_screen.c`, `ps5_agc_native_runtime.c`, `ps5_scanout.h` |
| Async preparation | worker threads prepare draws in parallel (CPU placement, optional realtime priority, idle spin/sleep control) | `ps5_agc_runtime_backend.c`, `ps5_agc_native_runtime.c` |
| Mipmaps | small levels are generated on the GPU (`PS5_GPU_BLIT_MIN_PIXELS`), optional lazy level generation (`PS5_MIPFAST`) | `ps5_screen.c` |
| Cache flushes | `clflushopt` loop with one fence, descriptor flush with one fence | `ps5_screen.c`, `ps5_agc_native_runtime.c` |
| Present | adaptive flip, optional async swap and triple buffering (`ps5_egl.c`) | `ps5_egl.c`, `ps5_screen.c` |
| Shader cache | on-disk cache keyed by a build id that changes with the driver | `ps5_screen.c` |
| Measurement | tracer hook and driver events for the performance tools (`tools/ps5 perf`), wait-site accounting | `ps5_screen.c`, `ps5_agc_native_runtime.c` |

Measured effect and the reasoning behind each change: [`docs/PERFORMANCE.md`](../docs/PERFORMANCE.md).

## Build

Prerequisites: WSL2 Ubuntu with the packages in [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md), the PS5 payload SDK in `~/ps5app/.deps` and the
app packaging tree `~/ogapp` (`app/setup_ogapp.sh`).

1. Download `ps5-opengl-sdk-1.0.0.tar.gz` of the ps5-opengl SDK release v1.0.0 from the mirror above and save it as `~/gl/sdk.tgz` (sha256 `f93643c04c843d56143b00951df1f8042ea7706ae9f19e4e9abf158e1ead77c5`).
2. `bash driver/build/setup.sh` unpacks it to `~/gl`, applies `ps5-opengl.patch` to `~/gl/src/ps5-opengl` and links `~/drv`.
   The compile step needs Mesa headers and the generated shader compiler sources from the SDK's own source tree. Prepare that tree as
   the SDK describes (`fetch-sources.py` in its `tools/`, `toolchain/build-opengnm-psbc.sh`, `toolchain/build-mesa-ps5.sh`); it creates
   `third_party/` and `build/mesa-ps5-probe`, which `~/drv` points to.
3. Compile the three objects:

```
bash driver/build/drv_cc_cache.sh
bash driver/build/drv_cc_backend.sh
bash driver/build/drv_cc_egl.sh
```

The objects land in `~/drv/out` and are linked into the app by `app/setup_ogapp.sh` (group archive). When only a driver object changed, the app
build does not notice: `tools/ps5 build` touches the app entry for you. Use identical `EXTRA`/`PS5_EXTRA_DEFS` values for the backend and the cache
build, otherwise the two objects disagree on struct layout.

Verify that a fresh SDK extraction accepts the patch: `patch -p1 --dry-run < driver/ps5-opengl.patch` inside an unpacked `ps5-opengl` tree.

## Run-time switches

The app maps empty marker files in `/data/opengoal/config/` to environment variables before the driver starts (`app/shim/appmain.cpp`).
Defaults are the shipped behaviour; the rest are for measurement and for narrowing down glitches.

| File in `config/` | Variable | Effect |
|---|---|---|
| `noasyncmultidraw.txt` | `PS5_ASYNC_MULTIDRAW` unset | go back to synchronous multi-draw batches (default is async) |
| `nomultidraw.txt` | `PS5_NO_MULTIDRAW` | no multi-draw batching at all |
| `nocombine.txt` | `PS5_NO_COMBINE` | do not combine command groups |
| `syncdebug.txt` | `PS5_SYNC_DEBUG`, `PS5_NO_COMBINE` | fully synchronous mode to tell sync bugs from translation bugs |
| `nomipcpu.txt` | `PS5_MIP_SKIP_CPU` | skip the CPU mip filter (stale mips, diagnostic) |
| `mipfast.txt`, `mipfast3.txt` | `PS5_MIPFAST` 1 / 3 | lazy mip generation, with tail skip |
| `spinwait.txt` | `PS5_SPIN_WAIT` | spin instead of sleeping in waits |
| `waitus100.txt` | `PS5_WAIT_US` 100 | wait granularity in microseconds |
| `workerdiag.txt` | `PS5_WORKER_DIAG` | log long worker idle/busy times |
| `workeryield.txt` | `PS5_WORKER_YIELD` | idle prep workers yield after N spins |
| `prepcpu.txt` | `PS5_PREP_BASE`, `PS5_PREP_STEP` | CPU placement of the prep workers |
| `asyncswap.txt`, `triplebuffer.txt` | `PS5_ASYNC_SWAP`, `PS5_TRIPLE_BUFFER` | async swap, third display buffer |
| `adaptiveflip.txt` | `PS5_VSYNC_STRICT` unset | adaptive (tearing) flip |
| `flipmode.txt` | `PS5_FLIP_MODE` | force flip mode (1 vsync, 2 immediate) |
| `presentlog.txt` | `PS5_PRESENT_LOG` | log every present |
| `drawcost.txt` | `PS5_DRAWCOST` 7 | draw cost experiments (viewport slot 0, one-fence descriptor flush, stage times) |
| `rtfastflush.txt` | `PS5_RT_FAST_FLUSH` | workers flush with `clflushopt` and one fence |
| `noflush.txt`, `nodescflush.txt`, `fulldescflush.txt` | `PS5_NO_BUFFER_FLUSH`, `PS5_NO_DESC_FLUSH`, `PS5_FULL_DESC_FLUSH` | cache flush experiments |
| `buffermem.txt` | `PS5_BUFFER_MEM_TYPE` | memory type for vertex, index and uniform buffers |
| `norename.txt` | `PS5_NO_BUFFER_RENAME` | disable buffer renaming |
| `gputrace.txt` | `PS5_GPU_TRACE` | GPU completion trace (costs about 10 fps: never use it for fps numbers) |
| `trace.txt` | tracer | content `start duration` in seconds; writes `trace_<n>.bin` into the log directory |

`PS5_MIPMAP_OLD`, `PS5_MIPMAP_GPU_MIN_PIXELS`, `PS5_MIPFAST_TAIL`, `PS5_WORKER_SLEEP_US`, `PS5_WORKER_SLEEP_SPINS` and `PS5_WORKER_RT` exist
but have no flag file; set them from a launcher script if you need them.

Never run with several of these at once when you want numbers: `tools/ps5 perf round` removes all flag files first and sets only the ones you name.
