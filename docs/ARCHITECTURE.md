# Architecture

OpenGOAL-PS5 is one native PS5 app (`eboot.bin`, title `LAPY77001`) that contains the OpenGOAL engine, a launcher, an importer and a web
server, and links a patched graphics driver. The PC side only installs the app and, optionally, prepares game data faster.

```
  PC                                      PS5 app (eboot.bin)
  ----------------------------            -----------------------------------------------------------
  installer/release_template  --FTP-->    app/glue/ogmain.cpp   main() -> app/shim/appmain.cpp
  installer/pc_import.py ---HTTP :8080-->   |
  browser (phone or PC) ---HTTP :8080-->    +- launcher.cpp    controller UI, settings, ps5.cfg
                                            +- webserver.cpp   status, ISO upload, install stream  <- webpage.cpp
                                            +- importer.cpp    ISO check, extractor (engine/gen_ps5_extractor.py)
                                            |
                                            +- OpenGOAL engine (jak-project + engine/*.py patches)
                                                 |  OpenGL 4.1 calls
                                                 v
                                            app/shim/glfix.cpp   GL interposition: draw merging, fixes, tracer
                                                 |
                                                 v
                                            Mesa 26.2 gallium driver (driver/ps5-opengl.patch)
                                                 |  prep worker threads, batching
                                                 v
                                            AGC runtime backend -> PS5 GPU command buffers -> display
```

## The parts

| Part | Folder | Role |
|---|---|---|
| App | `app/` | `shim/` replaces SDL and the platform layer (window, input, audio, threads, files under `/data`), hosts the launcher, importer and web server, and intercepts GL calls (`glfix.cpp`). `glue/` is the app's `main`. `rebuild_all.sh` and `setup_ogapp.sh` link everything with the ps5-opengl SDK into the app folder. |
| Driver | `driver/` | The graphics stack. The patch adds asynchronous draw preparation, multi-draw batching, GPU mip generation and the measurement hooks. |
| Engine | `engine/` | jak-project is not forked. Idempotent scripts patch an upstream checkout (`apply_ps5_patches.py` is the core; FSR, in-game settings, import progress and profilers are optional). `ports/manifest.json` lists every step with the text it depends on, which lets `sync_upstream.py` port new OpenGOAL versions and report what broke before anything is written. `gen_ps5_ninja.py` and `gen_ps5_extractor.py` rebuild the engine and the extractor with the PS5 compiler from the host CMake configuration. |
| Payloads | `payloads/` | Tiny ELFs sent to the console's loader port: close/launch the app, ShadowMountPlus rescan, keep-awake, kernel log, kstuff flag read. |
| Tools | `tools/` | `ps5` command line: build, deploy, run, measure, QA, test. |
| Installer | `installer/` | What users get: `install.py` uploads the app over FTP; `pc_import.py` and the GUI prepare games on the PC; `make_release.*` bundles it all. |

## Runtime

- **One game per process.** The launcher runs first; choosing a game writes `next.txt` and restarts the app, which then starts the engine for that game.
  This keeps each game's memory map and driver state clean.
- **Game data** lives under `/data/opengoal/<game>/data`. The importer checks the ISO (serial, size), runs the extractor on the console, and compiles the
  game code; the PC import path does that work on the PC and sends one compressed stream (`PUT /api/install`) that the console unpacks while receiving.
  Nothing from a disc is stored in this repository or in the release.
- **Settings** are `ps5.cfg` (written by the launcher) plus developer flag files in `/data/opengoal/config/`; `appmain.cpp` turns both into environment
  variables before the engine and driver start.
- **Frame path.** The engine submits about 500 to 2000 draws per frame. `glfix.cpp` merges compatible draws, Mesa translates state, the driver hands
  each draw to worker threads that build the AGC packets, and a batch is submitted to the GPU while the next frame is prepared. The 60 Hz display
  flip is the limit; see [`PERFORMANCE.md`](PERFORMANCE.md).
- **Upscaling.** The optional FSR patch renders into a smaller target and a final pass (EASU, RCAS) writes the window ([`FSR.md`](FSR.md)).

## Why it is built this way

- The console's graphics API (AGC) is unlike OpenGL, and the engine needs OpenGL 4.1. Reusing the ps5-opengl SDK keeps the port small; the cost is CPU time
  per draw, which is why most of the performance work is in the driver and in draw merging.
- Patching an upstream checkout by script (instead of carrying a fork) makes new OpenGOAL releases a repeatable job with a pre-flight check.
- Everything that changes behaviour has a switch, so a regression can be isolated in one run without a rebuild.
