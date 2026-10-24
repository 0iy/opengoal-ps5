# Third-party notices

OpenGOAL-PS5 is licensed GPL-3.0-or-later (see `LICENSE`). It builds on and links the projects below. "Evidence" says how the licence was
established; entries marked *upstream* take the licence from the project itself, whose repository carries the text.
The release bundle includes the repository licence; the licence texts of the linked components stay in their projects.

## Linked into the app or derived from in this repository

| Component | Use | Licence | Evidence |
|---|---|---|---|
| [OpenGOAL / jak-project](https://github.com/open-goal/jak-project) (pinned `553a713`) | game engine, compiler, decompiler; patched by the scripts in `engine/` | ISC (their third-party code keeps its own licences, e.g. Dear ImGui MIT) | *upstream* |
| [ps5-opengl](https://github.com/blackbearreloaded/ps5-opengl) (Mesa gallium driver and AGC runtime for PS5) | `driver/ps5-opengl.patch` patches it | GPL-3.0-or-later | SPDX headers in the patched `ps5_*.c` files |
| [Mesa](https://www.mesa3d.org) 26.2 | OpenGL state tracker inside the SDK | MIT (parts differ) | `docs/DEVELOPMENT.md` lists the version; licence *upstream* |
| [ps5-native-app-boilerplate](https://github.com/blackbearreloaded/ps5-native-app-boilerplate) | app packaging tooling (copied into `~/ogapp` by `app/setup_ogapp.sh`), `app/glue/` | GPL-3.0-or-later | SPDX headers in `tooling/native/*.cpp` of the boilerplate |
| [ps5-payload-sdk](https://github.com/ps5-payload-dev/sdk) v0.44 | toolchain wrapper, crt/runtime objects linked into the app and the `payloads/` | GPL-3.0 | *upstream* |
| OpenProspero/AGC | AGC command-buffer reference used by the driver | GPL-3.0 | *upstream* |
| [opengnm-psbc](https://github.com/PS4-OpenGNM/opengnm-psbc), [opengnm](https://github.com/PS4-OpenGNM/opengnm) | shader compiler pieces inside the SDK | *upstream* | pinned in the SDK's `dependencies.json` |
| SDK dependencies: SPIRV-Headers, Vulkan-Headers (Khronos), imgui, nanovg, sokol | inside the ps5-opengl SDK build | *upstream* (permissive) | the SDK's `dependencies.json` |
| [FFmpeg](https://ffmpeg.org) `libavcodec/atrac9dec.c` tables | `tools/at9enc/atrac9tab.h` (data tables) | LGPL-2.1-or-later | header note in `tools/at9enc/README.md` |
| Noto Sans JP | font `assets/NotoSansJP-Medium.ttf` shipped in the app folder, not in git | SIL OFL 1.1 | `art/fonts/OFL.txt` |
| OpenGOAL logo (`art/og_icon.png`, `art/og_logo_text.png`) and `art/sce_sys/icon0.png` derived from it | app icon | OpenGOAL project artwork, see jak-project / launcher repository | *upstream* |

## Used at runtime or install time, not distributed here

These run on the console beside the app. You download them yourself from their projects; check their licences.

| Component | Role |
|---|---|
| etaHEN | jailbreak environment / HEN (not required for the app itself) |
| kstuff / kstuff-lite (EchoStretch) | kernel patches so the app starts; load before the app |
| ShadowMountPlus (release `smp_1.7beta7`) | mounts the app folder at launch |
| [ps5-payload-dev/ftpsrv, shsrv](https://github.com/ps5-payload-dev) | FTP (2121) and shell (2323) used by the installer and dev tools |
| Chiaki-ng, ActRemoteLink, OnionHEN | Remote Play experiments; not part of the app |
| [ps5debug-NG](https://github.com/Pharaoh2k/ps5debug-NG), [playden-ps5](https://github.com/leolobato/playden-ps5), [SharpProspero](https://github.com/SvenGDK/SharpProspero) | reference only (git-ignored checkouts); no code copied into this repository was verified |

## Not included, never distributed

Game data of Jak and Daxter: The Precursor Legacy, Jak II, Jak 3 (c) Sony Interactive Entertainment / Naughty Dog. Users supply their own
discs. No firmware, keys, console dumps or game music are part of the repository (`.gitignore` blocks `*.iso`, `*.at9`, `backup/`).

"PlayStation" and "PS5" are trademarks of Sony Interactive Entertainment Inc. "Jak and Daxter" is a trademark of its owner. This project is
not affiliated with, endorsed by or sponsored by Sony, Naughty Dog, or the OpenGOAL team.
