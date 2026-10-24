# Third-party notices

OpenGOAL-PS5 is licensed GPL-3.0-or-later (`LICENSE`). Everything below is either linked into the app (`eboot.bin`), copied or patched in this
repository, shipped in the release bundle, or only referenced. Every licence of a component that is stored or shipped here is compatible with
GPL-3.0-or-later for the way it is used. The only components without any licence grant (kstuff) are not distributed (section 5).

The licence texts are in [`LICENSES/`](LICENSES/) (one file per licence, SPDX names, texts from the SPDX licence list). `MIT`, `ISC` and `BSD` texts
there are the generic forms; the copyright holders of each component are named in the tables below and in the component's own files. The release
bundle contains `LICENSE`, this file and `LICENSES/`.

How it was verified (2026-10-24): *GitHub* = `gh api repos/OWNER/REPO/license` (read only); *on disk* = licence file or SPDX headers in the
pinned checkout used for the build (`~/jak`, `~/gl`, `~/ps5app`, SDK archive); *header* = notice at the top of the file in this repository.

## 1. In this repository

| Path | What | Licence | Source / version | Verified |
|---|---|---|---|---|
| everything not listed below | own code (app/shim, app/glue, engine patch scripts, tools, installer, tests, docs, `payloads/*.c`) | GPL-3.0-or-later | this repository | `LICENSE` |
| `engine/*.py`, `engine/ports/patches/*` | patches that edit [OpenGOAL / jak-project](https://github.com/open-goal/jak-project); the patched files stay under the upstream licence, our edits are GPL-3.0-or-later | ISC (upstream) | commit `553a713aed3794f454fa7b45a1f1ef443bbb914a` (tag v0.3.6), `engine/ports/upstream.lock` | GitHub: ISC; on disk `~/jak/LICENSE` identical (`LICENSES/ISC-OpenGOAL-jak-project.txt`) |
| `engine/fsr/fsr.vert`, `fsr.frag` | written from the public description of AMD FidelityFX FSR 1.0 (EASU, RCAS); no AMD source copied | GPL-3.0-or-later (own); the FSR algorithm description is MIT | see `docs/FSR.md` | header of `fsr.frag` |
| `driver/ps5-opengl.patch` | diff against the `ps5-opengl` source (6 files: `ps5_egl.c`, `ps5_screen.c/.h`, `ps5_agc_native_runtime.c`, `ps5_agc_runtime_backend.c`, `ps5_scanout.h`); the patched files carry `Copyright (C) 2026 BlackBearReloaded`, `SPDX-License-Identifier: GPL-3.0-or-later` | GPL-3.0-or-later | ps5-opengl SDK 1.0.0 (see 3.) | on disk: SPDX headers of the patched files |
| `driver/build/*.sh` | build scripts that compile the patched files with the SDK's flags (`rc.txt`) | GPL-3.0-or-later | own, flags taken from the SDK build | - |
| `app/glue/*`, `app/setup_ogapp.sh` | own `main()`/heap setting; the script copies files from the boilerplate and ps5-opengl `native-app/` trees into `~/ogapp` at build time (nothing of them is stored here) | GPL-3.0-or-later | - | - |
| `tools/at9enc/atrac9tab.h` | data tables, byte-identical to FFmpeg `libavcodec/atrac9tab.h` (Copyright 2018 Rostislav Pehlivanov), used by the offline ATRAC9 encoder only; not in the app or the release | LGPL-2.1-or-later (combinable with GPL-3.0-or-later) | FFmpeg blob `a4a63bcaa19921e6bc881888efab20cc0db32ec7` (first commit 755e61839, 2018-07-03) | header; GitHub contents of FFmpeg master compared byte for byte |
| `tools/at9enc/refdec.c` | test wrapper that includes the header of the LibAtrac9 reference decoder (MIT, github.com/Thealexbarney/LibAtrac9); the decoder itself is not included | GPL-3.0-or-later (wrapper) | - | GitHub: MIT |
| `art/fonts/NotoSansJP-Medium.ttf`, `OFL.txt` | Noto Sans JP Medium, Copyright 2014-2021 Adobe (Reserved Font Name "Source"); used by `art/make_art.py` and copied into the app folder | SIL OFL 1.1 (`LICENSES/OFL-1.1.txt` is this same notice file) | file identical to `jak-project/game/assets/fonts/` at the pin | on disk: `cmp` of font and `diff` of the licence text |
| `art/launcher/*.jpg`, `*.png` | converted from the artwork of the official OpenGOAL launcher (backgrounds and logos); see `art/launcher/SOURCE.md` | launcher repository: ISC, Copyright (c) 2022-2026 OpenGOAL Team (`art/launcher/LICENSE-open-goal-launcher.txt`). The pictures themselves show Jak and Daxter artwork owned by Sony Interactive Entertainment / Naughty Dog, used only to identify the games, as the launcher does | open-goal/launcher commit `8c5883300bad4dc29513dd6dbeffb0b3a86d2dad` | GitHub: ISC; the licence file is identical to the launcher's `LICENSE` |
| `art/og_icon.png`, `art/og_logo_text.png`, `art/sce_sys/icon0.png` (derived) | OpenGOAL logo (mask and wordmark) and the app icon built from it | ISC, Copyright (c) OpenGOAL Team (the repositories they come from); the OpenGOAL name and mark stay the project's | `og_icon.png` is `src-tauri/icons/icon.png` of open-goal/launcher, `og_logo_text.png` is `logo-text-colored-new.png` in the `docs/img` folder of open-goal/jak-project | GitHub git blob hashes equal (`9b3d14f1...`, `66e53df9...`); both repositories ISC |
| `docs/img/jak1.png`, `jak2.png`, `jak3.png` | screenshots of the three games running on the console (title screens) | not ours: game artwork (c) Sony Interactive Entertainment / Naughty Dog, shown to document compatibility; no open licence applies | own screenshots | - |
| `app/shim/inflate_lite.h` | raw-deflate (RFC 1951) decoder, written for this repository; no code from zlib, puff or miniz (checked: no third-party notice in the file, own table-driven design) | GPL-3.0-or-later | own | header read |
| `app/shim/qr.cpp` | QR code encoder (byte mode, level L, versions 1-6) written from ISO/IEC 18004; no Nayuki, ZXing or libqrencode code | GPL-3.0-or-later | own | header read |
| `app/shim/ps5sdl.cpp` | the SDL3 replacement. It implements the used subset of the SDL3 API itself on top of the console's pad, video and timer calls and includes the real SDL3 headers (3.4.10, from `jak-project/third-party/SDL/include`) for types, enums and macros only; no SDL source file is compiled or linked | GPL-3.0-or-later (shim); SDL3 headers: zlib (Copyright (C) 1997-2026 Sam Lantinga) | SDL 3.4.10 | on disk `~/jak/third-party/SDL/LICENSE.txt`; GitHub libsdl-org/SDL: Zlib |
| `app/shim/gl_table.c` | generated name table of `gl*` functions of `libPS5OpenGL.a` | GPL-3.0-or-later | `app/gen_gl_table.py` | - |
| `payloads/*.c`, `payloads/build.sh` | see 4. | GPL-3.0-or-later | own | - |
| `.gitignore` blocks | game data (`*.iso`, `*.at9`, `*.dds`, QA golden screenshots), dumps and local output | - | - | - |

## 2. Linked into the app (`eboot.bin`)

`eboot.bin` links the engine, the PS5 OpenGL runtime and the payload SDK runtime into one binary; the combination is distributed under
GPL-3.0-or-later. All of these allow that.

### OpenGOAL / jak-project 553a713 (v0.3.6) and what it vendors

ISC, Copyright (c) 2020-2026 OpenGOAL Team. The third-party code inside the tree keeps its own licence (on disk under `~/jak/third-party/`, listing
libraries that the PS5 targets, `gk` and the on-console extractor/compiler, compile or include):

| Library | Licence | Verified |
|---|---|---|
| fmt | MIT (with the fmt binary-form exception) | on disk `fmt/LICENSE`; GitHub MIT |
| Dear ImGui (+ SDL3/OpenGL3 backends compiled against the SDL shim) | MIT | on disk `imgui/LICENSE.txt`; GitHub MIT |
| glad 0.1.34 (generated GL loader), `KHR/khrplatform.h` | glad output (generator MIT); `khrplatform.h` MIT, Copyright (c) 2008-2018 The Khronos Group | header of `khrplatform.h` |
| stb_image, stb_image_write | MIT (alternative B: public domain) | header of `stb_image.h` (Sean Barrett) |
| zstd (`lib/common`, `compress`, `decompress`) | BSD-3-Clause (alternative: GPL-2.0, not used) | header of `zstd.h` (Yann Collet, Facebook) |
| lzokay | MIT, Copyright (c) 2018 Jack Andersen | on disk `lzokay/LICENSE` |
| libco | ISC, Copyright (c) 2004-2025 ares team, Near et al | on disk `libco/LICENSE` |
| SQLite (amalgamation) | public domain | header of `sqlite3.c` |
| tinygltf | MIT | header of `tiny_gltf.h` |
| draco | Apache-2.0 | on disk `draco/LICENSE` |
| nlohmann/json (`json.hpp`) | MIT | SPDX line in the header |
| inja | MIT (Copyright (c) Pantor) | header; GitHub pantor/inja: MIT |
| magic_enum | MIT | SPDX line in the header |
| CLI11 2.2.0 | BSD-3-Clause | header |
| BS::thread_pool | MIT | header |
| ghc::filesystem (`filesystem.hpp`) | MIT | header |
| dragonbox (part of fmt's number formatting) | Apache-2.0 WITH LLVM-exception OR BSL-1.0 | header |
| xdelta3 (extractor) | Apache-2.0 | on disk `xdelta3/README.md` |
| capstone 6.0.0-Alpha10 (extractor) | BSD-3-Clause; some files LLVM Apache-2.0 WITH LLVM-exception | on disk `capstone/LICENSES/` |
| zydis (extractor) | MIT, Copyright (c) 2014-2024 Florian Bernd | on disk `zydis/LICENSE` |
| tree-sitter and tree-sitter-opengoal grammar (extractor) | MIT | on disk `tree-sitter/tree-sitter/LICENSE`; GitHub open-goal/tree-sitter-opengoal: MIT |
| SDL_GameControllerDB (`game/assets/sdl_controller_db.txt`, packed into `skeleton.tar.zst`) | zlib | file header; GitHub mdqinc/SDL_GameControllerDB: Zlib |
| Noto Sans JP | SIL OFL 1.1 | see 1. |

Not built for the PS5 (excluded by `engine/gen_ps5_ninja.py`): SDL itself, curl, discord-rpc, replxx, libtinyfiledialogs, cubeb, googletest. `fpng`,
`sse2neon`, `mman` are not part of the PS5 build either.

### PS5 OpenGL runtime (`libPS5OpenGL.a`, driver objects)

| Component | Licence | Source / version | Verified |
|---|---|---|---|
| ps5-opengl runtime (gallium PS5 screen, AGC runtime, EGL layer, scanout, shader glue) with our patch (`driver/ps5-opengl.patch`) | GPL-3.0-or-later, Copyright (C) 2026 BlackBearReloaded | SDK release 1.0.0, archive `sdk.tgz`, sha256 `f93643c04c843d56143b00951df1f8042ea7706ae9f19e4e9abf158e1ead77c5`, runtime source commit `dce74910af7f4274c48d05e0ae001b3038462588` | on disk: `LICENSE` (GPL-3.0) and 455 SPDX GPL-3.0-or-later headers in `~/gl/src/ps5-opengl`; GitHub: the mirror `JVK3R/ps5-opengl` release v1.0.0 carries an asset with exactly that sha256, repository licence GPL-3.0 |
| Mesa 26.2.0: GLSL, NIR, Gallium and GL dispatch/state tracker, ACO/RADV parts, AMD AddressLib, util | MIT for the large majority; per file also Apache-2.0, BSL-1.0, SGI-B-2.0 (texts in `LICENSES/`); Linux uapi headers carry GPL-2.0 WITH Linux-syscall-note | `archive.mesa3d.org/mesa-26.2.0.tar.xz`, sha256 `efd4bb08cdb7c365a812cd4e6c9202ab55b2f22cdcd13c7d6c4f9647b799a4ef` | on disk: SDK `LICENSES/Mesa/` (Apache-2.0, BSL-1.0, GPL-1.0-or-later, GPL-2.0-only, MIT, SGI-B-2.0, LLVM exceptions) and SPDX headers; a grep of the SPDX identifiers in the SDK source tree finds GPL-2.0-only and GPL-1.0-or-later only in the licence text files themselves, no source file under them |
| OpenGNM PSBC (PS5 shader compiler, patched by the SDK) and OpenGNM declarations | MIT | PSBC base `a92a1228ea3a64e4be9f0e61c2a65a5aa7ffed92`, OpenGNM `4b295ca54c82c83acf308d1c646a2dfa9ae57350` | on disk SDK `LICENSES/OpenGNM-PSBC.txt`, `OpenGNM.txt` |
| SPIRV-Headers, Vulkan-Headers (compiler inputs) | Apache-2.0 / MIT per file | `0d25db97...`, `b51f6b86...` (SDK `dependencies.json`) | on disk SDK `LICENSES/SPIRV-Headers.txt`, `Vulkan-Headers.txt` |
| `libSceAgc.so`, `libSceAgcDriver.so` link stubs | GPL-3.0-or-later (built from `native-app/agc_*_link_stub.c` of ps5-opengl); contain no Sony code, only import names | same SDK | on disk |

The SDK also contains Dear ImGui, NanoVG, Sokol, VK-GL-CTS examples and the SDL2 PS5 fork. None of them is linked into the app (the link group is
`ps5_screen.o`, `ps5_agc_runtime_backend.o`, `ps5_egl.o`, `libgk.a`, `libPS5OpenGL.a`, `libextractor.a`, libunwind, libc++abi, libc++, compiler-rt builtins).

The original `github.com/blackbearreloaded` account no longer exists (HTTP 404, checked 2026-10-24), so the original repository links are gone. The SDK is
the archive with the sha256 above; verified mirrors with identical release assets: `JVK3R/ps5-opengl` (v1.0.0). The licence travels inside the archive
(`LICENSE`, `LICENSES/`, per-file SPDX headers) and its source archives (`sources/`) are the corresponding source of the runtime.

### Application packaging and runtime

| Component | Licence | Source / version | Verified |
|---|---|---|---|
| [ps5-native-app-boilerplate](https://github.com/drakmor/ps5-native-app-boilerplate): packaging tools (`tooling/native/*`, `tools/*`), `Makefile`, `sce_sys` template, `assets/banner.txt`; copied to `~/ogapp` by `app/setup_ogapp.sh`, not stored here | GPL-3.0-or-later | commit `b8dc4a3fe2e05e826b037bd68824751c7468a6d7` (the commit exists in the GitHub repository) | on disk SPDX headers of `tooling/native/*.cpp`; GitHub: GPL-3.0 |
| `sce_module/libc.prx` in the app folder: clean-room runtime shim generated by the boilerplate's `libc_builder.cpp` | GPL-3.0-or-later, contains no Sony code | sha256 `e6ff45d16adf687855cc3b33b0c8a4132b6504360b221e0a34c7e99fb3ba0036` (same file in the release bundle) | on disk `runtime/README.md` of the boilerplate; hash compared |
| `app_heap.c`, `runtime_shims.c` from ps5-opengl `native-app/` | GPL-3.0-or-later | SDK 1.0.0 | on disk SPDX headers |
| [PS5 payload SDK](https://github.com/ps5-payload-dev/sdk) v0.42: clang/lld wrapper, `crt*.o`, libc, headers; `libc++`, `libc++abi`, `libunwind` built by it | SDK files: GPL-3.0-or-later; `include/freebsd`: BSD; libc++, libc++abi, libunwind: Apache-2.0 WITH LLVM-exception | release v0.42, `ps5-payload-sdk.zip` sha256 `8cfbc7cd5811e719eb4f0c47eea668d3dc7b40bc8ab11c4a5031d40c23ec02da` (GitHub release digest, equals the file used by the boilerplate's `setup-native-dependencies.sh`) | GitHub: GPL-3.0; SDK README states "Files in the folder include/freebsd are licenced under BSD licences. Unless otherwhise explicitly stated inside a file, the rest are licensed under the GPLv3+" |
| compiler-rt builtins (`libclang_rt.builtins-x86_64.a`, clang-18 of the build host) | Apache-2.0 WITH LLVM-exception | LLVM 18 | - |
| zlib (static, build-time compression of the boilerplate tool, not in the app) | zlib | fetched by the boilerplate | - |

## 3. Release bundle (`OpenGOAL-PS5.zip`) contents

Paths starting with `LAPY77001` are inside the bundle's `app` folder.

| File | What it is | Licence |
|---|---|---|
| `LAPY77001/eboot.bin` | the app, see 2. | GPL-3.0-or-later (combined), parts per 2. |
| `LAPY77001/sce_module/libc.prx` | clean-room runtime shim | GPL-3.0-or-later |
| `LAPY77001/sce_sys/icon0.png`, `pic0.dds`, `pic1.dds`, `param.json` | icon and backgrounds built by `art/make_art.py` from the OpenGOAL logo and Noto Sans JP; `pic*.dds` are generated at build time, not stored in git | OpenGOAL artwork (ISC repo) and OFL font output; own composition |
| `LAPY77001/assets/NotoSansJP-Medium.ttf` | launcher font | SIL OFL 1.1 (notice in `LICENSES/OFL-1.1.txt`) |
| `LAPY77001/assets/skeleton.tar.zst` | `goal_src`, decompiler configs, `game/assets` (fonts, shaders, text tables, controller database), `custom_assets`, `common/goos` of the patched jak-project tree; no game data | ISC and the library licences in 2. |
| `LAPY77001/assets/banner.txt` | boilerplate stub text | GPL-3.0-or-later |
| `scan.elf` (bundle folders `tools` and `payloads`), `ogagent.elf` (bundle folder `payloads`) | payloads, see 4. | GPL-3.0-or-later |
| `install.py`, `install.sh`, `install.bat`, `Install-OpenGOAL.ps1`, `README.txt`, `gui/*`, `pc_import.py`, `ps5_setup.py`, `bootstrap.*`, `SHA256SUMS` | own | GPL-3.0-or-later |
| `LICENSE`, `THIRD_PARTY_NOTICES.md`, `LICENSES/` | this notice and the licence texts | - |

Never shipped: `sce_sys/snd0.at9` (derived from a copyrighted track; removed by `installer/make_release.*`), game images, keys, firmware.
Downloaded by the user's machine at run time, not part of the bundle: the OpenGOAL tools release v0.3.6 (`installer/pc_import.py`, sha256 pinned
there; ISC plus the third-party licences of that archive) and, only on Windows without Python, the official Python 3.12.10 embeddable zip
(`installer/gui/windows/OpenGOAL-PS5.ps1`, sha256 pinned there; PSF-2.0, its licence file is inside that zip, we do not redistribute it).

Corresponding source of the release: this repository (the tag of the release) together with jak-project at `553a713` and the ps5-opengl SDK archive
named above.

## 4. Payloads in `payloads/`

All ELFs are built from the `.c` file of the same name in this directory with `payloads/build.sh` (clang 18, `ld.lld`) against the PS5 payload SDK v0.42
(GPL-3.0-or-later with BSD headers). They contain our code plus the SDK's `crt*.o` and libc, hence they are GPL-3.0-or-later; the sources are in this
repository. No third-party binary is stored here.

| ELF | Source | sha256 | In the release |
|---|---|---|---|
| `killapp.elf` | `killapp.c` | `8a6f989555ae242dd56d9c04014d4f60e9267b01452038836549fe2095c585b6` | no |
| `launchapp.elf` | `launchapp.c` | `7fcaa354f8b98b0d78002081ef879d5c86ad1536a604e7a70a295728a11ec8d4` | no |
| `scan.elf` | `scan.c` | `07fa18dd2c63b9865a1f367236dde9a3c7e995005b05321e159b7dc2a1c0fb1d` | yes (bundle folder `tools`) |
| `keepalive.elf` | `keepalive.c` | `460cbd5584644d756f6e18ac413a7c2347943b3238809d0403b19dd8e6010309` | no |
| `ogagent.elf` | `ogagent.c` (own work, GPL-3.0-or-later) | `f910068d95be4a25de3c616e8dad49d611b6d69b5647875a5bb328d0635d7a1e` | yes (bundle folder `payloads`; `ps5_setup.py` patches a copy) |

`ogagent.elf` is stored with its token unpatched (32 filler bytes after the marker `OGAGENT_TOKEN:`); the hash above is of that file, the setup script patches a copy.

`klog_dump.c` and `kstuff_state.c` have no prebuilt ELF. The ELF loader that receives the payloads (port 9021) is the console-side one of your
jailbreak setup, see below.

## 5. Console-side software, not distributed here

You download these yourself from their projects. This repository neither contains nor bundles them; `docs/INSTALL.md` names them and the order to
load them. Licences were read from the GitHub repositories on 2026-10-24.

| Component | Use | Licence | Source |
|---|---|---|---|
| kstuff / kstuff-lite 1.11 | kernel patches so the fake-signed app starts | **no licence file in either repository** (checked `EchoStretch/kstuff-lite`, `ps5-payload-dev/kstuff`), so no right to redistribute is granted; ask the authors before bundling | EchoStretch/kstuff-lite release v1.11 |
| ShadowMountPlus 1.7beta7 (release tag `1.7beta7`) | mounts the app folder | GPL-3.0 | github.com/drakmor/ShadowMountPlus (assets `shadowmountplus.elf`, `ShadowMountPlus_1.7beta7.zip`) |
| ftpsrv (v0.21.1), shsrv (v0.20), elfldr (latest releases at check time) | FTP on 2121, shell on 2323, ELF loader on 9021 | GPL-3.0 | github.com/ps5-payload-dev/{ftpsrv,shsrv,elfldr} |
| etaHEN | jailbreak environment, optional | GPL-3.0 | github.com/LightningMods/etaHEN |
| ps5debug-NG, playden-ps5, SharpProspero | reference only (git-ignored checkouts); nothing copied | GPL-3.0 each | Pharaoh2k/ps5debug-NG, leolobato/playden-ps5, SvenGDK/SharpProspero |
| Chiaki-ng | Remote Play experiments, not part of the app | AGPL-3.0 | chiaki-ng/chiaki-ng |
| OnionHEN, ActRemoteLink | named in the docs as things to avoid or try; no single upstream repository was found whose licence could be read | unknown | - |

`installer/ps5_setup.py` downloads some of these on the user's machine at run time, never bundles them, and refuses any file whose size or SHA-256 differs from the pin in its
`PAYLOADS` table (sizes and digests read from the GitHub release API on 2026-10-24 and re-computed on the downloaded files):

| Asset | Size | sha256 |
|---|---|---|
| EchoStretch/kstuff-lite v1.11 `kstuff.elf` | 1737080 | `ab9a6cb4d3b1daf139d4d646e402b1cf569071acd64599c936d7a3a6164dc779` |
| drakmor/ShadowMountPlus 1.7beta7 `shadowmountplus.elf` | 2517288 | `a8f9d7f76e8749912508ade0cd5c78076b5bbf1271813c78c80c3d3d9d4777ee` |
| ps5-payload-dev/ftpsrv v0.21.1 `ftpsrv-ps5.elf` (fallback only) | 191864 | `7d4b31c83eae4e056580482a3a074e1db25922efc74ac1e439473b45d71a5938` |
| ps5-payload-dev/shsrv v0.20 `shsrv-ps5.elf` (optional) | 986184 | `fa4ccb2587bb61be317df0d001f668b17ebf9b4aafad87acf691b1fb8da0bd2d` |

The script shows each source and licence before it sends the file; kstuff-lite is sent only with the user's consent because its authors published no licence. The Sony Interactive
Entertainment MAC prefixes used for ranking candidates come from the public IEEE OUI list; the Remote Play discovery request follows the format used by chiaki-ng
(`lib/src/discovery.c`, AGPL-3.0; only the message format was taken, no code).

## 6. Build and test tools (not distributed)

clang/LLVM 18 (Apache-2.0 WITH LLVM-exception), ninja, CMake, NASM, Python 3 with `numpy` (BSD-3-Clause), `Pillow` (MIT-CMU) and `zstandard`
(BSD-3-Clause), Node.js (tests), `ffmpeg` (offline ATRAC9 checks). They are installed by the developer and are not part of any download here.

## 7. Not included

Game data of Jak and Daxter: The Precursor Legacy, Jak II and Jak 3 (c) Sony Interactive Entertainment / Naughty Dog. Users supply their own discs.
No firmware, keys, console dumps or game music are part of the repository or the release (`.gitignore` blocks `*.iso`, `*.at9`, `backup/`).

"PlayStation" and "PS5" are trademarks of Sony Interactive Entertainment Inc. "Jak and Daxter" is a trademark of its owner. This project is not
affiliated with, endorsed by or sponsored by Sony, Naughty Dog, or the OpenGOAL team.
