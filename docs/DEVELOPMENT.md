# Development

Build host: Windows 11 + WSL2 Ubuntu (see [`SETUP_NEW_MACHINE.md`](SETUP_NEW_MACHINE.md)). Build scripts never touch the console; only
`ps5.py` (deploy/run) and the tools in [`RUNBOOK.md`](RUNBOOK.md) do.

## Data flow

engine OpenGL calls -> `ps5shim/glfix.cpp` (GL interposition, draw merging) -> Mesa 26.2 -> patched gallium driver `ps5_screen.c`
-> async prep workers + AGC runtime -> PS5 command buffers. Launcher, importer and web page live in `ps5shim/`.

## Repository map

| Path / prefix | Content |
|---|---|
| `ps5shim/` | app shim: SDL replacement, launcher UI, importer, web server and page, GL fixes, QR code |
| `ogapp_src/`, `setup_ogapp.sh`, `rebuild_all.sh` | app packaging and the link/eboot build |
| `drv_patchNN.py`, `drv_cc*.sh` | idempotent patches of the ps5-opengl driver source and its build (use `drv_cc_cache.sh`, not `drv_cc.sh`) |
| `apply_ps5_patches.py`, `patch_*.py`, `shim_patch_*.py` | patches for jak-project, shim, FSR, in-game settings |
| `ports/`, `sync_upstream.py` | upstream sync manifest, lock and patches ([`UPSTREAM_SYNC.md`](UPSTREAM_SYNC.md)) |
| `qa_pipeline.py`, `tests/` | QA gate and offline tests ([`QA_PIPELINE.md`](QA_PIPELINE.md)) |
| `fsr/` | FSR shaders and offline reference tests ([`FSR.md`](FSR.md)) |
| `ps5.py`, `perfround.py`, `rplay.py`, `trace2json.py`, `shot*.py`, `ps5*.ps1` | deploy, run, measure, replay, screenshot tools |
| `m0/`, `m1/` | small PS5 payloads (kill/launch app, scan, diagnostics): `*.c` sources and `build.sh` |
| `at9enc/` | ATRAC9 encoder for the hover music |
| `art/`, `og_*.png` | app icon and background generators |
| `release_template/` | installer shipped in the release (`install.py`, `.bat`, `.sh`, `.ps1`) |
| `wsl_snapshot/` | patched driver sources, jak-project diff and build flags of the last machine |
| `docs/` | documentation ([`README.md`](README.md)) |

Root scripts not listed above (`tmp_*`, `find_*`, `prof_*`, trial scripts) are one-off debugging aids scheduled for removal
([`RELEASE_CLEANUP.md`](RELEASE_CLEANUP.md)).

## Build and run loop

```
bash drv_cc_cache.sh && bash drv_cc_backend.sh        # driver objects
bash rebuild_all.sh                                    # engine + shim + link -> eboot.bin
python ps5.py kill; python ps5.py deploy --force      # console address from PS5_IP
```
Driver change: write `drv_patchNN.py` (marker string, `assert s.count(old) == 1`), apply, rebuild. Every behaviour change must be switchable
by a flag file `/data/opengoal/config/<name>.txt` (mapped to an environment variable in `ps5shim/appmain.cpp`) and default to the old behaviour.

## How the parts fit

| Topic | Doc |
|---|---|
| Console boot order, measurement loop, logs | [`RUNBOOK.md`](RUNBOOK.md) |
| New OpenGOAL version | [`UPSTREAM_SYNC.md`](UPSTREAM_SYNC.md): fetch, preflight, port, verify, snapshot |
| Regression gate after every sync or patch | [`QA_PIPELINE.md`](QA_PIPELINE.md) |
| Dynamic resolution, FSR | [`FSR.md`](FSR.md) |
| OpenGOAL in-game menus on PS5 | [`INGAME_SETTINGS.md`](INGAME_SETTINGS.md) |
| ISO import page | [`ONBOARDING_WEB.md`](ONBOARDING_WEB.md) |
| Install flow | [`INSTALL.md`](INSTALL.md) |
| Measurements and history | [`PERF_JOURNAL.md`](PERF_JOURNAL.md) |

## Rules

Use the tracer (`trace.txt`), not `gputrace` or the sampling profiler, for frame times. Never write kernel flags and never restart the console
from scripts. Third-party checkouts (`jak-project/`, `sdk*/`, ...) are git-ignored; revisions are pinned in `SETUP_NEW_MACHINE.md`.
