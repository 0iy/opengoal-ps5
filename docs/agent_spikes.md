# Agent spikes: the 2 % of Jak 3 frames over 20 ms

Scope: Jak 3, `asyncmultidraw`, traces `perf_runs/jak3_{q0,q1,q2,q16x128,r1440,r4k,s1_amd}.trace_*.bin` (1606 frames, 27.4 s in total, about 3.4 s each,
s1_amd 7 s). Nothing was run on the console. Everything below marked **measured** comes from those traces, **read** from the sources
(`~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c`, `ps5shim/*.cpp`), **assumed** is a hypothesis.

## 1. Short answer

1. The premise "the prep workers stall" explains only a small part. Of the 43 frames over 20 ms in the traces, **27 (68 % of the lost milliseconds)
   are GPU waits** (retire / backpressure wait, and `glGenerateMipmap` which contains the same wait), **8 (21 %) are a gap of 10 to 27 ms in which
   the render thread issues no GL call at all** (game code on the other side or the render thread not running), **4 (7 %) are real prep-worker
   stalls**, 4 are mixed. All numbers: measured.
2. Events 103 (async-collect) and 111 (batch submit) do not "co-occur", **103 is nested inside 111**: batch flush -> `runtime_async_drain` ->
   `runtime_async_collect_one` spin. The 7 spikes are 7 events, not 14. Likewise **112 is nested inside 100** (identical values in all 1472 cases).
3. No clustering at multiples of 7.87 ms exists in these traces (section 3). The waits are quantised at about **1.2 ms** instead: that is the
   `sceKernelUsleep(1000)` polling loop of the GPU completion wait (`runtime_completion_pause`, line 1012), not the scheduler tick.
4. Cheapest real gain: finer GPU wait polling (`PS5_WAIT_US`). Biggest unknown: what stalls a worker 3.6 to 15 ms (preemption of a pinned,
   100 % busy thread, or a slow first-use job). Patch 60 adds the event that answers it (`PS5_WORKER_DIAG`, event 140) before anyone tunes priorities.

## 2. Analysis tables (reproduce: `python spikes_analyze.py`, `python spikes_gaps.py`; both read only)

Frames over 20 ms per run, from the traces (tracer window only):

| run | frames | fps | over 20 ms | over 33 ms |
| --- | --- | --- | --- | --- |
| q0 | 199 | 58.5 | 7 | 0 |
| q1 (asyncswap) | 199 | 58.6 | 5 | 1 |
| q2 (triplebuffer) | 199 | 59.0 | 4 | 0 |
| q16x128 | 199 | 58.7 | 6 | 1 |
| r1440 | 199 | 58.2 | 8 | 0 |
| r4k | 200 | 59.0 | 5 | 0 |
| s1_amd | 411 | 58.8 | 8 | 2 |
| total | 1606 | | 43 (2.7 %, 4.7 per 3 s) | 4 |

Whole-run `frametime:` lines (about 75 windows of 3 s per run, a much better statistic than the 3.4 s trace window), frames over 20 ms per 3 s:
q0 4.19, q1 4.07, q2 4.41, **q16x128 2.96**, r1440 4.09, r4k 7.41 (over 33 ms: 2.0), s1_amd 4.11. Run to run noise is about +-0.2, so a change of
0.5 per 3 s is detectable in one 190 s run.

Exclusive classification of the 43 slow frames (`spikes_gaps.py`, last block):

| class | frames | ms lost against 16.7 ms | share |
| --- | --- | --- | --- |
| GPU wait (retire/backpressure >= 2 ms; includes the glGenerateMipmap cases) | 27 | 322 | 68 % |
| render-thread gap >= 10 ms with no GL call and no wait | 8 | 98 | 21 % |
| prep-worker stall (collect >= 3 ms, always together with submit) | 4 | 33 | 7 % |
| other | 4 | 22 | 5 % |

Which events are in the slow frames (frames where the event totals >= 3 ms): retire 22 (mean 6.0 ms), backpressure 22 (6.1 ms, same waits),
glGenerateMipmap 10 (7.5 ms, contains the wait), collect 4 (12.3 ms), submit 4 (12.7 ms, contains collect), `submit_lock`/drain/flip 0. 17 of 43 slow
frames have no single event >= 3 ms.

Render-thread gaps (time between instrumented top-level calls): normal frames median 1.4 ms, p90 4.0, max 6.4; slow frames median 6.8, p90 15.7,
max 26.9. The large gaps sit at the start of the frame (0 to 4 ms after the frame tick) in 25 of the 34 gaps listed by `spikes_gaps.py` (gaps over 5 ms): the render thread waits
for the next frame's draw data or is not running. Several frames show two gaps of 12 to 16 ms (for example 29.6 ms = 13.0 + 12.6).
This looks like the game thread (EE) being late, **assumed**, not provable from this tracer (only the render thread is traced).

Single-wait duration histograms (events >= 0.5 ms; all runs):

| event | n | distribution |
| --- | --- | --- |
| retire (100) = backpressure (112) | 1472 (0.92 per frame) | 0.25 ms bins: 1.25 ms: 452, 2.25: 20, 2.5: 107, 3.5: 415, 4.5: 190, 4.75: 183, 5.75: 74, 6.75: 21, 8.0: 4 |
| collect (103) | 14 (>= 0.5 ms), 7 (>= 3 ms) | 3.6, 5.5, 6.5, 9.0, 9.8, 12.9, 15.3 ms |
| submit (111) | 14, 7 | the same 7 spikes (submit = collect + 0.0 to 0.4 ms) |
| glGenerateMipmap (206) | 549 | 1.5 ms: 263 (normal cost), then 2.5, 3.5, 3.75, 4.75, 5.75, 6.75, 8.5 (= the retire quantisation) |

Spikes of 103/111 per 3 s: 0.8. All 7 occurred at random times, 3 of them in the first 1.1 s of a trace window. Residue test against 7.87 ms
(events >= 3 ms, tolerance 1 ms): collect 1 of 7, retire 5 of 893, genmip 8 of 209; chance level 25 %. **No tick clustering.** The retire values
form a ladder 1.25, 2.5, 3.5, 4.75, 5.75, 6.75, 8.0 ms: steps of about 1.1 to 1.25 ms = one `sceKernelUsleep(1000)` iteration including the
200 us spin and wake-up. A wait whose GPU work ends 0.05 ms after a sleep started still costs 1.2 ms; mean overshoot about 0.6 ms per wait.

## 3. How the async workers wait and why one can stall (read)

* Job ring: `runtime_async_jobs[RUNTIME_ASYNC_JOBS]`, `RUNTIME_ASYNC_JOBS = PS5_MULTIDRAW_BATCH_CAPACITY` (native_runtime.c:1485). The producer
  (render thread) copies the draw state into a slot, bumps `runtime_async_produced` (1664-1678); when the ring is full it collects one job first.
* Workers (`runtime_async_main`, 1532): claim with a CAS on `runtime_async_consumed` (1565), prepare, store `job->ready` (1588). **Idle policy: unbounded
  `pause` spin** (1543-1563). The only alternative is `PS5_WORKER_YIELD` (`workeryield.txt`): `sched_yield` after N spins; no blocking primitive exists.
  Workers never sleep, so each occupies its CPU at 100 %.
* Pinning (`runtime_async_pin`, 1512): one CPU each, `PS5_PREP_BASE + worker * PS5_PREP_STEP`, default 10 and 2; the deployed `prepcpu.txt` is `2 4`
  = **cpus 2 and 6** (log: `prep workers: cpu base=2 step=4`). A single-CPU mask means a descheduled worker cannot migrate. Process mask `0x1fff`.
* Collect (`runtime_async_collect_one`, 1599): strictly in order, `pause` spin until `ready` of the oldest job (1605). A batch flush
  (`runtime_async_drain`, 1681) collects everything; the render thread therefore waits for the **slowest outstanding job**. Head of line blocking: if the
  worker holding the oldest unfinished job loses its CPU or is slow, the whole flush waits and nothing else can overtake it.
* GPU completion wait (`runtime_completion_pause`, 1012): 200 us spin, then `sceKernelUsleep(1000)` per iteration (`PS5_SPIN_WAIT` switches to spinning).
  `waits < 2000` is the timeout (about 2 s) and also the success criterion at 5387/5409/5660.
* Nobody sets a thread priority anywhere (grep over `ps5shim/`, `m0/`, `m1/`: no `rtprio`, `setprio`, `pthread_setschedparam`). Affinity is only set
  by `runtime_async_pin` and the optional `renderpin.txt` block in `SDL_GL_SwapWindow` (ps5sdl.cpp:611). Engine threads (IOP, DMP, EE-Worker, EE) are
  registered by name through `ps5_thread_register` (ps5sdl.cpp:552, called from `bootstrap_thread_func`) and keep the full mask `0x1fff` at the default
  priority. The render thread is unpinned.

Candidate causes of a 3.6 to 15 ms worker stall (the traces cannot separate them):

1. **Preemption of the pinned spinner** (assumed). A thread that never blocks gets the worst interactivity score in a ULE-like scheduler and loses every
   contest on its core; any other runnable thread placed on cpu 2 or 6 (IOP 1 to 30 %, EE, DMP, EE-Worker, system threads, the unpinned render thread
   after a wake-up) runs for a full time slice. The earlier 120 involuntary switches per frame on the render thread show that the machine is
   not quiet. But the stall lengths are not multiples of 7.87 ms (3.6, 5.5, 6.5, 9.0, 9.8, 12.9, 15.3), so a plain one-tick slice is not the pattern.
2. **A slow job** (assumed): first use of a shader pair runs `create_shader` / `link_shaders` under `runtime_shader_mutex` and allocates direct
   memory (native_runtime.c:1239, 1282, 4303). Rare, random, 3 to 15 ms and independent of the tick: fits the observed pattern at least as well as (1).
3. A page fault or kernel lock in the first touch of command memory (no evidence).

Patch 60 event 140 separates 1 from 2 in one run (section 4).

## 4. Patches (new files only; nothing applied)

### 4.1 `drv_patch60.py` (driver, only `platform/ps5_agc_native_runtime.c`; root `PS5_SRC`, default `~/gl/src/ps5-opengl/src`)

Verified: applies twice (second run prints "already patched") on a private copy and compiles with the `drv_cc_backend.sh` clang line
(private output `~/spikes_out/backend.o`, `U rtprio_thread` resolved from libkernel, which exports it: checked with `strings` on the SDK's
`libkernel.so`, also `pthread_setschedparam`, `scePthreadSetprio`, `scePthreadSetaffinity`, `cpuset_setaffinity`). Not run on the console.

| env | what | default |
| --- | --- | --- |
| `PS5_WAIT_US=50..1000` | GPU completion wait sleeps this long instead of 1000 us. One wait is still counted per elapsed ms, so timeout and the `waits < 2000` success tests keep their meaning | 1000 (unchanged) |
| `PS5_WORKER_SLEEP_SPINS=n`, `PS5_WORKER_SLEEP_US` | worker: after n idle spins, `sceKernelUsleep(us)` per iteration instead of spinning forever | 0 = never, us 50 |
| `PS5_WORKER_RT="type prio"` | worker scheduling class through `rtprio_thread(RTP_SET, 0, ...)`: type 2 realtime RR, 10 realtime FIFO, 3 timeshare, 4 idle; prio 0 (best) to 31; logs `[ps5-async-prep] rt ... rc=` | off |
| `PS5_WORKER_DIAG=us` | worker emits trace event 140 for every job slower than us: `dur` = job time, `arg` = worker \| nivcsw delta << 8 \| nvcsw delta << 24 \| (shader pair created) << 40, from `getrusage(RUSAGE_THREAD)` | off |

New static data: **none at file scope**. One function-local `static int us` in `ps5_wait_us()` (same pattern as the existing `static int mode` in
`ps5_sleep_wait_mode()`); everything else is on the stack. No new arrays.

### 4.2 `shim_patch_spikes.py` (shim, `ps5shim/ps5sdl.cpp`; root `PS5_SHIM_DIR`, default `<repo>/ps5shim`)

Reads `/data/opengoal/config/threadpol.txt` (absent = no change). Line: `<name> <cpu mask hex, 0 = leave> <class, 0 = leave> <prio>`; name is an
engine thread name (`IOP`, `DMP`, `EE-Worker`, `EE`, as in the `threads:` log line) or `RENDER` for the thread that calls `SDL_GL_SwapWindow`
(applied at its first swap, before `renderpin.txt`). Logs `threadpol: <name> mask= rc= class= prio= rc=`. Verified: applies twice on a copy of
`ps5sdl.cpp`, compiles with the ninja command of `ps5sdl.cpp`. No static data (stack only), one added include `<sys/rtprio.h>`. Not run.

### 4.3 Proposed lines for `ps5shim/appmain.cpp` (not edited)

```cpp
auto cfg = [](const char* file, const char* var) {  // first line of a config file -> environment variable
  if (FILE* f = std::fopen(file, "r")) { char b[64] = {0}; std::fgets(b, sizeof b, f); std::fclose(f); b[std::strcspn(b, "\r\n")] = 0; if (b[0]) setenv(var, b, 1); }
};
cfg("/data/opengoal/config/waitus.txt", "PS5_WAIT_US");
cfg("/data/opengoal/config/workersleep.txt", "PS5_WORKER_SLEEP_SPINS");
cfg("/data/opengoal/config/workersleepus.txt", "PS5_WORKER_SLEEP_US");
cfg("/data/opengoal/config/workerrt.txt", "PS5_WORKER_RT");      // content "2 20"
cfg("/data/opengoal/config/workerdiag.txt", "PS5_WORKER_DIAG");  // content "500"
```

### 4.4 Not implemented: producer-side work stealing

In `runtime_async_collect_one` the producer could claim the next unclaimed job with the same CAS and run `ps5_agc_gate2_run_sync` itself. It does not
help the observed case: the job being waited for is already claimed by the stalled worker, only later jobs could be stolen, and the stall length does
not change. It also has to save and restore the producer's thread-local draw state (`runtime_draw_state`, `ps5_agc_draw_state`, the `static
_Thread_local` cache at ps5_agc_runtime_backend.c:582), which is risky. Revisit only if event 140 shows many workers idle while one stalls.

## 5. Ranking (expected gain, risk; gains are estimates, **assumed**)

| # | change | targets | expected gain | risk |
| --- | --- | --- | --- | --- |
| 1 | `PS5_WORKER_DIAG` (event 140) | decides between preemption and slow job | none directly; removes the guesswork for 2 to 4 | none (off by default, only worker thread, one `getrusage` per job when on) |
| 2 | `PS5_WAIT_US=100` (try 100 and 250) | the quantised GPU waits, 68 % of the lost time | mean 0.5 ms less CPU time per frame, 15 to 25 % fewer frames over 20 ms (those at 20 to 21.5 ms), fps +0.1 to +0.3 | low: more wakeups while waiting; a very short value costs CPU in the wait only |
| 3 | `PS5_WORKER_SLEEP_SPINS` (try 20000 with 50 us) | worker stalls if cause 1 (preemption); gives the workers a sleep history so the scheduler may favour them | at most the 7 % class (about 0.3 frames per 3 s), more if the gaps are also scheduling | low to medium: wake-up latency adds to collect (0.6 ms/frame today); can lose fps |
| 4 | `threadpol.txt`: render thread `RENDER` pinned on a cpu not used by workers (and not their SMT sibling), IOP/EE-Worker/DMP masks excluding cpus 2, 6 and the render cpu | the 8 gap frames (21 %) and the 120 involuntary switches per frame, if they are scheduling | up to 1 to 1.5 fewer frames over 20 ms per 3 s | medium: wrong topology guess makes things worse (SMT pairs, which cpus the OS reserves, are **unknown**; `renderpin` trials already exist in `pin_trial.py` with no recorded result) |
| 5 | `PS5_WORKER_RT` / `RENDER` realtime class | preemption of workers/render by timeshare threads | possibly the 7 % + part of 21 % | **high**: a spinning realtime thread can starve kernel threads bound to its cpu and hang the console. Only with `PS5_WORKER_SLEEP_SPINS` set, class 2 (round robin), prio 20 or worse; test last |
| 6 | stealing (not implemented) | | ~0 | medium |
| - | queue 16x128 (patch 54, already measured) | GPU class | **2.96 vs 4.2 per 3 s (-30 %)** in the whole-run `frametime:` lines | already tested |

The largest lever for the over-20-ms frames is therefore on the GPU side (deeper in-flight queue, fewer flushes before `glGenerateMipmap`), not the
scheduler: q16x128 alone beats anything expected from items 3 to 6.

## 6. Test plan (main session, one change per run, Jak 3 `asyncmultidraw` + `trace`, 190 s, default 1080p; keep queue 16x128 build as the new baseline)

Build: patch 60 touches only the runtime object. `wsl -e bash -c "cd /mnt/c/Users/<you>/dev/projects/opengoal-ps5 && python3 drv_patch60.py && <drv_cc_backend.sh with the same EXTRA/PS5_EXTRA_DEFS as the deployed build> && python3 shim_patch_spikes.py && touch ~/ogapp/src/ogmain.cpp && bash rebuild_all.sh"`
(add the `cfg` lines of 4.3 to `appmain.cpp` by hand; `perfround.py` has to create the config files for the new flags).

Metric (per run, from `perf_runs/<label>.udp.log`):

```
grep -h "frametime:" perf_runs/<label>.udp.log | tail -n +10 | sed -E 's/.*over 20 ms: ([0-9]+), over 33 ms: ([0-9]+) \(of ([0-9]+)\)/\1 \2 \3/' | awk '{a+=$1;b+=$2;n++} END{print a/n, b/n}'
```

plus fps from `summary.txt`, plus `python trace2json.py <bin> -` (worst 6 frames) and `python spikes_analyze.py <bin>` / `python spikes_gaps.py <bin>` (class table).
Baseline to beat: 4.1 to 4.4 over-20 per 3 s, 0.25 to 0.4 over-33, 58.5 to 59 fps (q16x128: 2.96).

| step | flags (config files) | success |
| --- | --- | --- |
| 0 | baseline repeat (noise) | 4.1 to 4.4 |
| 1 | `workerdiag.txt` = 500 | event 140 present; `spikes_analyze.py` prints "slow prep jobs": preempted (nivcsw > 0) vs shader pair created vs neither. Decides whether steps 4 and 5 make sense. Also read the `[ps5-async-prep] rt` and `prep workers` log lines |
| 2 | `waitus.txt` = 250, then 100 | retire ladder in `spikes_analyze.py` shifts from 1.25 ms steps to smaller ones; over-20 per 3 s down by >= 0.5 |
| 3 | `workersleep.txt` = 20000 (+ `workersleepus.txt` = 50) | over-20 not worse; `async-collect` ms per frame in the `waits per frame:` line not above 0.7 |
| 4 | `threadpol.txt`: `RENDER 0x100 0 0` (cpu 8), `IOP 0x1c33 0 0`, `EE-Worker 0x1c33 0 0`, `DMP 0x1c33 0 0` (masks exclude cpus 2, 3, 6, 7, 8, 9; cpus 3, 7, 9 assumed to be the SMT siblings of 2, 6, 8: **unverified**) | gap-class frames (spikes_gaps.py) and over-20 down; check the `threads:` line for loader/IOP starvation and any loading-time regression |
| 5 | step 4 plus `RENDER 0x100 2 20`; only if 4 helped and with step 3 on | as above; abort on any freeze |

Stop rules: any `rc` other than 0 in the `threadpol:` / `rt` log lines means the call is not permitted on this firmware; drop that item. Keep
`workeryield.txt` unset. Success overall: over-20 per 3 s below 3 (from 4.2) with fps >= 59.

## 7. Open questions

* Whether the PS5 kernel here uses ULE (assumed from the FreeBSD 11 base; `rtprio.h` is the FreeBSD 11.4 one in the SDK) and what the tick-based slice
  length is. The earlier 7.87 ms outliers (PLAN_60FPS.md) do not show up in these 7 traces.
* CPU topology of the 13 usable cpus (SMT pairs, cpu reserved for the system). `cpuset_getaffinity` only returns the mask. A thread-to-cpu sampling
  (the cpu a thread runs on is not exposed) would need `ps5debug`.
* The 8 "gap" frames need a trace of the EE thread; the tracer only records the render thread. Adding the same hook to the `EE` thread's frame
  boundaries would settle whether the stall is game code.
