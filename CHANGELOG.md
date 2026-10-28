# Changelog

## 0.1.1 (unreleased)

### Added
- Updating: run the one-line install again. The setup compares the console's version (`app` in `/api/info`, from the `VERSION` file uploaded with the app) with the release and updates by itself when it is older, says "up to date" when equal and refuses to downgrade. It never restarts the app while an import runs.
- The import windows show "Update available" when a newer release exists; the setup prints the same notice
- `data_format` check: games record the format they were imported with (`/api/info` `formats`); after an update the setup lists games that need a re-import
- Debug log of every PC import (`~/.opengoal-ps5/last_import.log`, includes the console log after a failure) and `GET /api/log` on the console
- Console install errors now name the failing step, path and errno (`{"error":"io","errno":13,"why":"...","where":"..."}`) with a hint for the usual causes

### Fixed
- "Failed: no extractor.exe" on a fresh install: the import windows pointed at an empty tools folder instead of downloading the official release

## 0.1.0 (first public version)

Based on OpenGOAL (jak-project `553a713`, v0.3.x). Tested on firmware 13.60 only.

### Added
- Native Jak 1/2/3 port: PS5 shim (SDL replacement over EGL), controller launcher (English/German), keep-awake, quit-to-launcher flow
- On-console ISO import with web page on port 8080, QR code, pre-checks and queue ([`docs/ONBOARDING_WEB.md`](docs/ONBOARDING_WEB.md))
- One-command console setup (`installer/ps5_setup.py`, also `tools/ps5 setup`): finds the PS5, shows its state live, loads kstuff-lite and ShadowMountPlus when missing (pinned downloads), installs and starts the app through the `ogagent` payload
- Installer for Windows/Linux/macOS (`installer/release_template/install.py`) and a faster game import from the PC (`installer/pc_import.py`, import window, one-line bootstrap)
- Draw merging (`app/shim/glfix.cpp`) and asynchronous multi-draw submit; patched Mesa-to-AGC driver (`driver/ps5-opengl.patch`)
- Experimental: FSR 1.0 upscaling with dynamic resolution, lazy mipmaps ([`docs/FSR.md`](docs/FSR.md))
- Upstream sync tool (`engine/sync_upstream.py`, `engine/ports/`) and QA pipeline (`tools/qa_pipeline.py`)
- Frame tracer and analysis tools (`tools/ps5 perf`)
- Setup `--debug` log with per-request timings (`ps5_setup_debug.log`), detection of a suspended app copy that blocks the launch, test report issue template
- One command line, `tools/ps5`, for build, deploy, run, measure, QA, import, sync, test and doctor
- All-in-one offline test suite, `python tests/run_all.py`, with a privacy lint

### Changed
- Repository restructure: the 150 files of the root moved into `app/`, `driver/`, `engine/`, `payloads/`, `tools/`, `installer/` and `tests/`; the 60 driver patch scripts and the
  driver snapshot became one patch (`driver/ps5-opengl.patch`) with build scripts; one-shot scripts, experiment payloads and working notes were removed; documentation
  reduced to one page per topic (old to new paths: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md))

### Performance (1080p, from [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md))
- Jak 3 gameplay: 39-43 fps -> 59-60 fps (async multi-draw + merge)
- Jak 2 city: 21-22 fps -> about 50-58 fps (async multi-draw, merge, GPU mip fix)
- Jak 3 spawn scene 27-30 -> about 40 fps in the earlier work of 2026-10-19/20

### Fixed
- Glow sprites visible through solid objects (depth blit format, `glTexImage2D` fix)
- Mip generation falling back to the CPU path (missing `PS5_GPU_BLIT_MIN_PIXELS` build flag)
- Earlier rendering issues: merc, logo, crates, Jak, TM purple (shader), UI

### Known issues
- Visual glitches in places; occasional frame-time spikes; Jak 1 import not re-tested after the latest driver work
