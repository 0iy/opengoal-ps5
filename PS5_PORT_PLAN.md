# OpenGOAL (jak-project) on jailbroken PS5 - port plan

Status date: 2026-10-16. Console: CFI-2016, firmware 13.60, etaHEN + kstuff + ShadowMountPlus.

## Proven on the console (in a Home-tile app, title PPSA99999)
- VideoOut + CPU framebuffer: works (boilerplate hello scene).
- Pad via scePad: works, button mask changes on every press.
- RW mmap at 0x2123000000 (128 MB, OpenGOAL EE_MAIN_MEM_MAP) then mprotect RWX: works, x86 code runs.
  - Mapping RWX directly in mmap does NOT work (SEGV_ACCERR) - map RW, then mprotect.
- Payload (elfldr 9021) cannot open VideoOut (0x80290009 busy). Engine must ship as an app title.
- Remote logging: app sends UDP to PC port 9999.

## Compile feasibility (PS5 SDK libc++ headers, -fsyntax-only, -fexceptions -frtti)
- common/: 65/72 (7 fail: tree_sitter formatter, generated revision.h, 3 small)
- game/: 369/373 (4 fail: cubeb_export.h x3 generated, SystemThread.cpp Windows #ifdef)
- Needed defines: -D__forceinline=inline -DMAP_POPULATE=0 -DOS_POSIX
- Not yet done: real compile + link, third-party libs (fmt, zstd, sqlite3, libco, stb, imgui, lzokay, xdelta3).

## Platform surface to replace (small and bounded)
| Area | Current | PS5 replacement | Size |
|---|---|---|---|
| Window/GL context | SDL3 (graphics/pipelines/opengl.cpp) | EGL via ps5-opengl SDK | 1 file |
| Input | SDL3 (system/hid/*, 19 files) | scePad (+ keyboard/mouse dropped) | ~10 files |
| Audio | cubeb (game/sound, ~10 calls) | sceAudioOut shim | 1 file |
| Renderer | OpenGL 4.3 core, ~105 gl* calls, ~39k lines | ps5-opengl (OpenGL 4.6 core on PS5, GPL-3.0) | no rewrite expected |
| Memory | mmap RWX (runtime.cpp:170) | mmap RW + mprotect RWX | few lines |
| Threads/misc | pthread, SystemThread.cpp | SDK pthread, drop Win32 branch | small |

## Key external pieces
- leolobato/ps5-opengl (OpenGL 4.6 Core on Mesa/Gallium, EGL, compute, SSBO) - the renderer path.
- blackbearreloaded/ps5-native-app-boilerplate - app packaging, FSELF, libc.prx shim, `make deploy`.
- PS5 payload SDK in boilerplate .deps (libc++.a, libc++abi.a, libunwind.a, libc.a, libpthread.a).

## Stages
1. Build `common` + `game` objects with the SDK (CMake or direct), link a console binary that boots to a log line.
2. Replace SDL window/GL with EGL (ps5-opengl), render the OpenGOAL title/debug screen.
3. scePad input backend; sceAudioOut sound backend.
4. Game data: extract from the user's own discs on PC (decompiler/extractor), copy to /data, mount via /app0 or /data path.
5. Menu/launcher replacement (Tauri launcher not portable): in-engine menu or config file.
6. Performance/stability pass, Jak 2/3/X.

## Risks / unknowns
- ps5-opengl is experimental; OpenGOAL's exact GL feature use vs. its 24k NotSupported results is unchecked.
- Memory budget of the app (heap size patched to 256 MiB in Playden's build; OpenGOAL needs 128 MB EE + GPU buffers).
- Large static link (libc++ exceptions/RTTI) with the boilerplate's libc.prx shim vs. SDK libc.a: unresolved which runtime to use.
- Firmware 13.60 only tested for this probe.
- Game data must come from the user's own legally owned discs.

## Product goal (user request, 2026-10-16)
One standalone all-in-one PS5 app, fully controller-driven:
- Built-in menu (replaces the Tauri launcher): choose Jak 1 / 2 / 3 / X, settings, launch - all with the pad.
- In-game controls mapped to the DualSense (scePad): sticks, face buttons, triggers, d-pad, rumble later.
- Game data folder picked/validated in the menu; no PC needed after setup.
- Exit/back to Home with the PS button.
