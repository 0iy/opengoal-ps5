# Runbook: operating the console and the build loop

Console: PS5 CFI-2016 B01Y, firmware 13.60, IP `192.168.x.y` (LAN since 2026-10-23, MAC `xx:xx:xx:xx:xx:xx`). PC: `192.168.x.y`.
The debug channel host is `/data/opengoal/config/debughost.txt` (must match the PC address).

## Boot order that works (after every console restart; the user runs the browser exploit and the ELF loader)

1. Exploit and ELF loader (port 9021 open). Nothing else.
2. `kstuff-lite_v1.11.elf` (send to 9021). Wait about 20 s.
3. `ftpsrv-ps5.elf` (FTP 2121), `smp_1.7beta7.elf` (ShadowMountPlus, mounts `/data/homebrew/LAPY77001` on launch),
   optionally `shsrv-ps5.elf` (plain TCP shell on 2323, not SSH; `ps`, `cat`, `ls`, `cp`, `launch`, `kill`).
4. Do NOT load OnionHEN before: with OnionHEN's built-in kstuff the fake-signed eboot is refused (`0x80020008`,
   klog `sceSblAuthMgrAuthHeader returned unexpected error 46`).
   Payload files used so far were verified against release digests; they live in the session scratchpad, re-download from
   `EchoStretch/kstuff-lite`, `ps5-payload-dev/ftpsrv`, `ps5-payload-dev/shsrv`, ShadowMountPlus releases.
5. `ps5dbg_maps.py list` (port 744) works when a ps5debug payload runs; it is read-only.

Never write kernel flags from payloads. Do not restart the console from scripts.

## Build loop (WSL, Ubuntu; repo path `/mnt/c/Users/<you>/dev/projects/opengoal-ps5`)

```
bash drv_cc_cache.sh        # ps5_screen.o with GPU mip blits and shader cache id (the only correct driver build)
bash drv_cc_backend.sh      # ps5_agc_runtime_backend.o (runtime, 2 prep workers)
touch ~/ogapp/src/ogmain.cpp && bash rebuild_all.sh    # engine, shim, link, eboot.bin in ~/ogapp/dist/LAPY77001
python ps5.py kill; python ps5.py deploy --force      # app must not run during deploy
```
Driver patches: `python3 drv_patchNN.py` (idempotent). Shim patches: `python shim_patch_*.py`. The driver source tree is
`~/gl/src/ps5-opengl/src` (not in git). Tools expect `PYTHONIOENCODING=utf-8` on Windows.

## Measurement loop

```
python perfround.py jak2_x jak2 90 trace [flag ...]     # jak3: 190 s, tracer window 100 s start
python trace2json.py perf_runs/jak2_x.trace_<n>.bin -     # statistics; give a second argument only to write JSON (it overwrites!)
bash perf_suite.sh jak3 190 label1 "" label2 asyncmultidraw ...
```
Rules: never use `gputrace` for fps; compare runs of the same scene (Jak 2 starts in the intro, the city is reached at about 40 s;
Jak 3 is driven by `rplay.py` into the new game, gameplay after about 100 s); a driver rebuild invalidates the shader cache, the first
run after a deploy has hitches (do a warm-up run).

## Logs

UDP broadcast on port 9999 (all `ps5_log` lines, one listener at a time), `last_run.log` (written by `ps5.py run`),
`/data/opengoal/log/ps5.log` on the console (200+ MB, read with FTP REST), kernel log via `m1/klog_dump.elf`
(`-DALL` build `klog_all.elf` for the full stream), crash reports in klog (`# fault address`, `# rip`).

## Backups and safety

`backup/`: original console eboot, `param.json.orig`, `snd0_console_2026-10-23.at9`, `jak2_pc-settings.gc`, Slot 1 registry values before the
ActRemoteLink fake sign-in (`slot1_registry_before.json`), `arl_agent_noguard.elf`. On the console: `/data/arl_backup/{config.dat,auth.dat}`.
