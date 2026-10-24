# Development

Build host: Windows 11 with WSL2 Ubuntu (Linux works the same without the WSL wrapper). The console is only touched by `tools/ps5`
(deploy, run, measure) and the tools in [`RUNBOOK.md`](RUNBOOK.md). How the parts fit: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Layout

```
app/        the PS5 app: shim (SDL replacement, launcher, importer, web server, GL fixes), glue (main), build scripts
driver/     patched ps5-opengl graphics driver: one patch, build scripts, run-time switches
engine/     patches for the jak-project engine, upstream sync tool and manifest, FSR shaders, build file generators
payloads/   small console payloads (kill/launch app, scan, keep awake, kernel log) with their prebuilt ELFs
tools/      the `ps5` command line and the modules behind it (console, perf, QA, trace analysis, ATRAC9 encoder)
installer/  release bundle: installer, PC import engine, import GUI, bootstrap scripts, release scripts
tests/      all-in-one offline test suite, host C++ tests, QA baseline
art/        app icon and launcher artwork, generator
docs/       documentation
```

## `tools/ps5`

Run it as `tools/ps5 <command>` (Linux, macOS, Git Bash), `tools\ps5 <command>` (Windows) or `python tools/ps5.py <command>`.
The console address comes from `PS5_IP` or a git-ignored `.ps5_ip` file in the repository root.

| Command | What it does |
|---|---|
| `build` | incremental engine and app build in WSL, prints errors only |
| `deploy [--force]` | uploads `eboot.bin` (skipped when unchanged) |
| `run [game] [seconds]` | restarts the app, optionally straight into `jak1`/`jak2`/`jak3`, prints the log lines that matter |
| `go [game] [seconds]` | build, kill, deploy, run |
| `start`, `kill`, `log [regex]` | start and leave running, close the app, grep the console log of the last start |
| `shot <game> [seconds ...]` | run a game and fetch screenshots to `out/` |
| `perf round`, `perf suite`, `perf trace` | measurements and trace analysis, see [`PERFORMANCE.md`](PERFORMANCE.md) |
| `qa [options]` | regression gate, see [`QA.md`](QA.md) |
| `import [options]` | game import from the PC, see [`PC_IMPORT.md`](PC_IMPORT.md) |
| `sync [command]` | upstream sync, see [`UPSTREAM_SYNC.md`](UPSTREAM_SYNC.md) |
| `test [-k name]` | the offline test suite |
| `doctor` | checks the toolchain files and (when an address is set) the console ports |
| `dbg`, `shots`, `upload`, `sym` | debug channel client, screenshot requests, ISO upload through the web page, crash address lookup |

## Build loop

```
tools/ps5 build            # engine + shim + link -> ~/ogapp/dist/LAPY77001/eboot.bin
tools/ps5 kill && tools/ps5 deploy
tools/ps5 run jak3 60      # restart into a game and watch the log
tools/ps5 test             # before every commit
```

Driver change: edit the sources in `~/gl/src/ps5-opengl`, rebuild the objects (`driver/build/drv_cc_cache.sh`, `drv_cc_backend.sh`, `drv_cc_egl.sh`),
run `tools/ps5 build`, then regenerate the patch (`diff -ruN` against the pristine `ps5-opengl.tar` from the SDK, see [`driver/README.md`](../driver/README.md)).
Engine change: edit the patch scripts in `engine/` (idempotent, `assert s.count(old) == 1`); `apply_ps5_patches.py` runs as part of the build.
Every behaviour change must be switchable by a flag file `/data/opengoal/config/<name>.txt` (mapped to an environment variable in
`app/shim/appmain.cpp`) and default to the old behaviour.

## Set up a new machine

1. **Packages (WSL Ubuntu):**
   `sudo apt install build-essential cmake ninja-build clang-18 lld-18 llvm-18 llvm-18-tools nasm python3 python3-pip python3-numpy python3-pil git curl zstd unzip`
   and `pip install zstandard`. Windows side: Python 3.9+ with `pillow` and `numpy` (for QA and screenshots), Git.
2. **Third-party sources (pinned):**

   | What | Source | Revision | Where |
   |---|---|---|---|
   | jak-project | https://github.com/open-goal/jak-project | `553a713aed3794f454fa7b45a1f1ef443bbb914a` (v0.3.6), submodules | `~/jak` |
   | ps5-opengl SDK | https://github.com/JVK3R/ps5-opengl/releases (mirror, release v1.0.0, asset `ps5-opengl-sdk-1.0.0.tar.gz` saved as `sdk.tgz`; the original blackbearreloaded repository is gone) | sha256 `f93643c04c843d56143b00951df1f8042ea7706ae9f19e4e9abf158e1ead77c5` | `~/gl/sdk.tgz` |
   | ps5-native-app-boilerplate | https://github.com/drakmor/ps5-native-app-boilerplate | `b8dc4a3fe2e05e826b037bd68824751c7468a6d7` | `~/ps5app` (run its `make` once, it fetches the payload SDK v0.42 into `.deps`) |
   | Mesa, opengnm-psbc | inside the SDK archive (`sources/`) | Mesa 26.2.0, sha256 `efd4bb08cdb7c365a812cd4e6c9202ab55b2f22cdcd13c7d6c4f9647b799a4ef` | `~/gl/src/ps5-opengl/third_party` |

3. **Link this repository** at a path of your choice; all scripts find their own location. Scripts expect the WSL home layout `~/jak`, `~/jak_cfg`,
   `~/gl`, `~/drv`, `~/ps5app`, `~/ps5build`, `~/ps5build_ext`, `~/ogapp`.
4. **First build:** `bash app/first_build.sh` (host configuration of jak-project, engine patches, engine and extractor archives, driver objects,
   app packaging, `eboot.bin`). Afterwards `tools/ps5 build` is the loop.
5. **Console:** boot order and operations in [`RUNBOOK.md`](RUNBOOK.md). Install the app once with the installer from a release bundle; after that
   `tools/ps5 deploy` only uploads `eboot.bin`.
6. **Check:** `tools/ps5 doctor` and `tools/ps5 test`.

Third-party checkouts are git-ignored. Do not commit game data, firmware, keys or dumps.

## Rules

- Use the tracer (`trace.txt`), not `gputrace` or the sampling profiler, for frame times.
- Never write kernel flags and never restart the console from scripts.
- Add new static data in the driver one change at a time and boot-test after each ([`PERFORMANCE.md`](PERFORMANCE.md), pitfalls).
- Commit subjects are short sentences without prefixes.

## Where the old files went

| Old path | New path |
|---|---|
| `ps5shim/` | `app/shim/` |
| `ogapp_src/` | `app/glue/` |
| `rebuild_all.sh`, `setup_ogapp.sh`, `gen_gl_table.py`, `gen_launcher_assets.py` | `app/` (same names) |
| `wsl_first_build.sh` | `app/first_build.sh` |
| `drv_patch1..60.py`, `fix53.py`, `wsl_snapshot/ps5-opengl/` | `driver/ps5-opengl.patch` |
| `drv_cc*.sh`, `wsl_snapshot/drv/rc.txt` | `driver/build/` |
| `apply_ps5_patches.py`, `patch_gfxprof.py`, `patch_proftree.py`, `patch_eh.sh`, `patch_fsr.py`, `patch_fsr_effects.py`, `patch_ps5_ingame_settings.py`, `patch_import_progress.py` | `engine/` |
| `sync_upstream.py`, `ports/`, `gen_manifest_anchors.py`, `compile_check.sh` | `engine/` |
| `fsr/` | `engine/fsr/` |
| `make_skeleton.py`, `gen_ps5_ninja.py`, `gen_ps5_extractor.py` | `engine/` |
| `wsl_snapshot/jak-project_*` | removed (`tools/ps5 sync snapshot` regenerates it) |
| `m0/`, `m1/` | `payloads/` (experiments and diagnostic ELFs removed) |
| `ps5.py` | `tools/console.py` (used by `tools/ps5`) |
| `ps5cfg.py`, `dbg.py`, `rplay.py`, `perfround.py`, `shotseries.py`, `shotdiff.py`, `qa_pipeline.py`, `upload_iso_web.py`, `symlookup.py`, `ps5dbg_maps.py` | `tools/` |
| `perf_suite.sh` | `tools/perf_suite.py` |
| `trace2json.py`, `trace_stages.py`, `trace_mip.py`, `multidraw_report.py` | `tools/trace/stats.py`, `stages.py`, `mip.py`, `multidraw.py` |
| `at9enc/` | `tools/at9enc/` |
| `pc_import.py`, `ps5_setup.py`, `bootstrap.*`, `make_release.*`, `gui/`, `release_template/` | `installer/` |
| `pc_import_fake.py` | `tests/gui/pc_import_fake.py` |
| `tests_*.cpp`, `tests_*.sh`, `tests_*.py`, `tests_onboarding_web.js` | `tests/host/`, `tests/test_install_e2e.py`, `tests/test_onboarding_web.js` |
| `qa/baseline.json` | `tests/qa/baseline.json` |
| `og_icon.png`, `og_logo_text.png` | `art/` |
| `PERF_JOURNAL.md`, `PERF_ANALYSIS.md`, `PLAN_60FPS.md`, `agent_*.md` | `docs/PERFORMANCE.md` |
| `SETUP_NEW_MACHINE.md`, `HANDOFF.md` | this file and `RUNBOOK.md` |
| `ONE_LINERS.md` | `docs/INSTALL.md` |
| `QA_PIPELINE.md`, `FSR_EFFECTS_AUDIT.md` | `docs/QA.md`, `docs/FSR.md` |
| removed one-shot scripts (`shim_patch_*.py`, `patch_launcher_*.py`, `patch_fsr_v1.py`, `gen_import_probe.py`, `analyze*`, `flows.py`, `startwatch.py`, `spikes_*.py`, `arl.py`, `ps5dbg*.py`, `jak3_play.py`, `conv_assets.py`, ...) | git history |

## Release

1. `python tools/ps5.py build`, then `python tests/run_all.py` (must be green).
2. Rebuild the toolchain pack when `engine/` patches or game assets changed: `python installer/pc_import.py --make-pack installer/opengoal-ps5-pack.tgz ...`
   and put its size and sha256 into `PACK_SIZE` / `PACK_SHA256` in `installer/pc_import.py`.
3. `bash installer/make_release.sh` (WSL; stops with a message when the `ogagent.elf` payload is not built) writes `release/`: `OpenGOAL-PS5.zip`, `OpenGOAL-PS5-gui.zip`, `opengoal-ps5-pack.tgz`, `bootstrap.ps1`, `bootstrap.sh`, `SHA256SUMS`.
4. `gh release create vX.Y.Z release/OpenGOAL-PS5.zip release/OpenGOAL-PS5-gui.zip release/opengoal-ps5-pack.tgz release/bootstrap.ps1 release/bootstrap.sh release/SHA256SUMS`
   (the tag in `PACK_URL` must match).
