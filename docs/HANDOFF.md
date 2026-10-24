# HANDOFF: state of the OpenGOAL-PS5 port (2026-10-22)

Everything needed to continue on another machine. Read this first, then `SETUP_NEW_MACHINE.md`, then `../PERF_ANALYSIS.md`.

## Update 2026-10-23 (read first)

The session of 2026-10-23 rebuilt the toolchain on a new machine, added a tracer, wait accounting and patches 42 to 57, and measured both
games. Current state, corrections of older statements, patch table, tools and pitfalls: `PERF_JOURNAL.md`. Console boot order and the
build/measure loops: `RUNBOOK.md`. Plan: `PLAN_60FPS.md`. Sub-agent reports: `agent_syncdbg.md`, `agent_multidraw.md`, `agent_present.md`,
`agent_drawcost.md` (brief: `AGENT_BRIEF.md`). The driver must be built with `drv_cc_cache.sh` (plain `drv_cc.sh` loses two flags).

## Goal

Native OpenGOAL (jak-project v0.3.x) on a jailbroken PS5 (fw 13.60), Jak 1 / 2 / 3 at 60 fps minimum, no loss of quality,
controller-driven launcher, on-console ISO import, packaged as one app "OpenGOAL-PS5" (title id `LAPY77001`, GPL-3.0-or-later,
no game data in the repo).

## Architecture (one paragraph)

`jak-project` (patched, `apply_ps5_patches.py` + `patch_gfxprof.py` + `patch_proftree.py`) is compiled by `gen_ps5_ninja.py` /
`ps5.py build` into `libgk.a`; the PS5 shim (`ps5shim/*.cpp`: SDL replacement over EGL, launcher UI, importer, web import page,
GL interposition `glfix.cpp`, debug channel) and the "ogapp" packaging (`setup_ogapp.sh`, based on ps5-native-app-boilerplate)
link it into `eboot.bin`. OpenGL goes through the **ps5-opengl SDK** (Mesa 26.2 -> gallium driver `ps5` -> AGC command buffers);
we compile the driver ourselves (`drv_cc.sh`, `drv_cc_backend.sh`) and link it first (`libog_group.a` GROUP) so our patched
`ps5_screen.c` / `ps5_agc_native_runtime.c` / `ps5_agc_runtime_backend.c` / `ps5_egl.c` win over the SDK's. One game per
process: the launcher relaunches the app for each game (`next.txt`, `sceSystemServiceLoadExec`).

## What works

- Launcher (controller driven), Jak 1/2/3 boot and play, import of ISOs on the console (web page :8080, QR), keep-awake
  (`sceSystemServicePowerTick` every 5 s), Quit -> launcher flow.
- Rendering fixes done earlier: merc, logo, crates, Jak, TM purple (shader), UI.
- Performance work of 2026-10-19/20 (details in `PERF_ANALYSIS.md`): Jak 3 spawn scene 27-30 -> ~40 fps (CPU 18.4 -> 15.9 ms).

## Open work, in order of value

1. **60 fps in Jak 2/3.** Remaining: one ~7-9 ms hiccup per frame in a random render bucket (render thread preempted? GPU trace
   shows 7.8 ms outliers); ~50 GPU blits/frame from `glGenerateMipmap` cost ~5 ms CPU; final window blit waits for a flip.
   Ideas: fewer/cheaper blits for mip generation, triple buffering (two flips in flight), reduce per-draw driver CPU
   (`ps5_draw_vbo_locked` state building, descriptor flush calls, batch drains per FBO pass), glthread (`PS5_GLTHREAD=1`, untested after fixes),
   cache `glGetUniformLocation` in OpenGOAL. Research notes (OpenGOAL issues/PRs, driver knobs) are summarised in `PERF_ANALYSIS.md`.
2. **Jak 2 vehicle lights visible through buildings** (not investigated; needs the scene).
3. **Jak 1 import re-test** (jak1 is installed; `POST :8080/api/start?game=jak1` was cancelled to free the app).
4. Release: README/NOTICE, private -> public repo, release zip, shader-cache pre-warm, remove dev files from the console.
5. XMB: tile name still reads "OpenGOAL" (system database cache; needs re-registration via etaHEN or DB rebuild, not changed by us).
   Hover music: `at9enc/` is a from-scratch ATRAC9 encoder; the 15 s file built from the user's MP3 is **not** in this repo (copyright);
   whether the console accepts it is unconfirmed (first 45 s file was silent).

## Console facts

- PS5 `192.168.x.y` (Wi-Fi, MAC `xx:xx:xx:xx:xx:xx`, weak signal), title `LAPY77001`. Ports: FTP 2121, shell 2323
  (can go silent after rest mode), ELF loader 9021, import web page 8080, debug channel: the app dials the PC on TCP 9998
  (host in `/data/opengoal/config/debughost.txt`, must be updated when the PC's LAN IP changes).
- After rest mode FTP + loader survive but the shell may stay silent: `ps5.py` then launches with `m1/launchapp.elf` and kills with
  `m1/killapp.elf` (via the loader). `wake.py <MAC>` sends Wake-on-LAN. If all ports are closed the jailbreak is gone: re-run the exploit and the ELF loader.
- Do not change the console's system settings from scripts; rest-mode timer / WoL / Remote Play are the user's to set.
- Data layout: `/data/opengoal/{jak1,jak2,jak3}/data`, config `/data/opengoal/config` (ps5.cfg, per-game `OpenGOAL/<game>/settings`),
  shader cache `/data/opengoal/cache/shaders`, log `/data/opengoal/log/ps5.log` (can be 200+ MB: read with FTP `REST`, see `fpsnow.py`).

## Tools (all in this repo)

| Tool | Use |
| --- | --- |
| `ps5.py build / deploy / kill / start / run / snap / log` | main loop (WSL build, FTP upload, ELF-loader kill/launch) |
| `dbg.py` + app channel | `ping, ver, ls, tail, put, get, rm, shot, limit, skip, skiprange, dumpprog, trace, press <hexmask> <ms>, stick, mark, import` |
| `jak3_play.py` | restart app, launcher -> Jak 3 new game -> spawn scene (needs debug channel); retries the first Play press |
| `rplay.py` | same without the debug channel (FTP + `inject.txt` key script); `--deploy`, `--cfg name=value` |
| `fpsnow.py`, `pin_trial.py`, `ab_trial.py`, `memtype_trial.py` | log readers / A-B trials |
| `wake.py` | Wake-on-LAN |
| `autopilot.ps1` | unattended: wait for console, deploy, tour, import |
| `tour.py` | smoke tour of Jak 1 (phases, fps, crashes) |
| `drv_patch*.py` | idempotent patches of the SDK driver sources in WSL (`~/gl/src/ps5-opengl`); already applied in `wsl_snapshot/` |
| `apply_ps5_patches.py`, `patch_*.py` | patches for `~/jak` (also as a ready diff in `wsl_snapshot/`) |
| `shim_patch_*.py` | patches of `ps5shim/` (already applied in this repo's sources) |
| `at9enc/` | ATRAC9 encoder (pure Python+numpy, WSL) |

Test flags (empty file or number in `/data/opengoal/config/`): `noflush.txt` (keep: skips safe CPU flushes), `glthread.txt`, `norename.txt`,
`keepwindowclear.txt`, `adaptiveflip.txt`+`flipmode.txt`, `spinwait.txt`, `workeryield.txt`, `fulldescflush.txt`, `gputrace.txt`,
`nocombine.txt`, `profile.txt` (`render` or `w0`), `buffermem.txt`, `renderpin.txt`, `prepcpu.txt` (keep `2 4`), `autolaunch.txt`.
Never leave `nodescflush.txt` (breaks the game: silent return to the launcher).

## Gotchas learned the hard way

- Log volume kills fps (`ps5_log` blocks). Never dump thousands of lines per frame.
- After every driver rebuild the shader cache is cold: 5-28 s hitches for a few runs.
- Stray controller presses in the launcher change `ps5.cfg` (resolution -> 4K). `rplay.py`/`jak3_play.py` reset it; check `resolution=0`.
- Rebuilding the driver only changes `eboot.bin` if you `touch ~/ogapp/src/ogmain.cpp` (the scripts do).
- 3 prep workers, worker yield, spin-wait instead of 1 ms sleeps, buffer memory type 3, adaptive flips, dynamic resolution: all measured, none helped
  (spin-wait starves the loader threads).
- `ps5.py` treats a silent shell as "maybe running" so `kill` still works.
- Python heredocs through the tool layer mangle `\n` escapes: use real files (editor tool) for scripts with escape sequences.

## Repository

Private GitHub repo: https://github.com/0iy/opengoal-ps5 (branch `main`, account `0iy`). Clone with `gh repo clone 0iy/opengoal-ps5`.
After changes in WSL-side trees (`~/jak`, `~/gl/src/ps5-opengl`, `~/ogapp`), refresh `wsl_snapshot/` (see the commands in git history, commit e624b7a) and push.
