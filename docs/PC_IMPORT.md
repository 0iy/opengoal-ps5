# PC import: do the heavy work on the PC, send only the finished game

`pc_import.py` (Python 3.8+, standard library only, Windows / macOS / Linux) extracts the user's ISO and decompiles the game data with the
**official OpenGOAL tools** on the PC, assembles the minimal runtime data (the "play set") and streams it to the console with
`PUT /api/install`, where it is unpacked while it arrives. The on-console importer (ISO upload, extractor, decompiler, goalc) stays as the
fallback and is untouched.

"MB" below means MiB (1,048,576 bytes) for sizes. Everything here was measured on one machine with one disc (Jak and Daxter, PAL, SCES-50361, 1,460,305,920 bytes). Nothing was run on the
console. Numbers are labelled **measured** or **estimate**. The "playable within about one minute" target is **not** claimed: it is plausible
from the measured PC side and the estimated network side, and has to be measured on the console (section 9).

## 1. Result in one table

All times are wall seconds, warm file cache, ISO and project on the system SSD.

| Machine | Stage | Old way: official tools, `extractor --extract --decompile --compile` | New way: `pc_import.py`, precompiled game code |
|---|---|---|---|
| Windows 11, Ryzen 5 5600G, 6 cores / 12 threads, official `extractor.exe` v0.3.6 (**measured**) | extract | 2.9 | about 5 (incl. 1.4 GB written, project check) |
| | decompile (data, levels, textures) | 7.7 | about 5.6 |
| | compile (goalc `(mi)`, 1318 targets) | 29.0 | about 0.5 (only the text/subtitle targets, 46 files) |
| | assemble the play set + compress (8 threads) | - | 2.6 |
| | **total until the stream is ready (no network)** | **39.6** | **14.1 to 16.2** (3 runs; 20.2 with the one-time project setup) |
| WSL2 Ubuntu limited to 2 vCPU, ext4, official Linux tools (**measured**) | extract / decompile / compile | 7.2 / 11.4 / 25.9 = 44.5 | |
| | whole run to a loopback test server (real receiver code, no network limit) | | playable at 25.7, voice extras done at 33.2 |
| | same run without a codepack (full goalc build, the fallback) | | 51.1 (dry run) |
| Console, on-console import (the reason for this work) (**measured earlier by the main session**) | extract about 1 MB/s => 30+ min, decompile + compile longer | | |

Network part (**estimate**, not measured): the core play set is 729 MB raw and 553 MB on the wire. Gigabit Ethernet at about 100 MB/s: about 6 s.
Wi-Fi at about 30 MB/s: about 18 s. Compression and sending overlap with the PC work after the decompile. Rough end-to-end *estimate* for the
playable state: PC preparation 11 s (12 threads) to 20 s (2 cores) + sending 6 to 18 s = about 17 to 40 s, plus whatever the console needs to
write and verify (unknown, receiver measured at 278 to 415 MB/s without disk writes on a PC core). The other voice languages (829 MB for this PAL
disc, 0 extra for discs with one language) follow after the game is playable.

## 2. Where the time goes and what was done about it

Critical path of the old way (Windows, measured): extract 2.9, decompile 7.7, compile 29.0. Inside the compile: 518 game source files by goalc
16.8 s (single threaded, cannot be split), 765 file copies 6.5 s (about 1.4 GB of disc files copied into `out/<game>/iso`), custom test level
3.0 s, subtitles 0.55 s, 28 DGO packs 0.46 s.

| Idea | Verdict (measured unless noted) |
|---|---|
| (a) skip the compile with precompiled game code | **Done.** The compiled `.o` of `goal_src` do not depend on the disc except through two build constants (`*default-territory*` = disc region and `*jak1-full-game*` = black label), so one **codepack per variant** (`jak1-SCEE`, `jak1-SCEA`, `jak1-SCEI`, `jak1-SCEA-bl`, ...) covers all discs of that variant. 517 objects + a recipe = 2.7 MB. Rebuilding the 27 DGO/CGO files from codepack objects + the decompiler's `raw_obj/*.go` with a 20-line Python builder is **byte identical** to goalc's output (checked for all 27 by `--make-codepack`, it refuses to write a codepack otherwise). Not skippable: the 46 TXT files (game text + subtitles) contain the disc's own text; they are built with `goalc -c '(make-group "text")'`, 0.4 s, byte identical to the full build. |
| (b) incremental compile | **Not possible with goalc.** `CompilerTool::needs_run` returns true for every object the *running* compiler does not know (`goalc/make/Tools.cpp`), so a fresh process recompiles all 518 files; measured: a second `--compile` run still takes 15.7 s (13.3 s goalc) although all outputs are up to date. |
| (c) decompiler threads | Level extraction already runs one thread per level (upstream). The rest (config, object DB, link data, text) is single threaded and about 3 s. No thread option exists. 12 threads: 7.7 s, 2 vCPU: 11.4 s. |
| (d) skip decompile passes | Nothing left to skip: all three game configs already have `decompile_code: false`, no dumps, `rip_levels`, `save_texture_pngs`, `rip_streamed_audio` false. `dump_objs: true` is required (`raw_obj/*.go` are DGO members). Level extraction (`levels_extract`, about 3 s) produces the `fr3` files the renderer needs. |
| (e) extract straight from the ISO | Not done. The extractor writes about 1.4 GB (2.9 s Windows, 7.2 s WSL) and everything after it needs part of that data anyway (decompiler: DGO/CGO; play set: STR/MUS/VAG/...). A pure Python ISO9660 streamer could save at most those seconds. Cleaning the work directory afterwards is deferred until after the `done` event (deleting 2 GB took about 8 s on NTFS when it happened at the start of a run). |
| Skip the other 5 voice banks in the first pass | **Done** (`--voices all` sends them afterwards, `--voices en` never). They are 5 x 166 MB of the 1.35 GB in `out/iso`. |
| Skip `out/<game>/obj` | **Done.** 204 MB, only used by the development tools (`load-object`, goalc `ml`). See 4. |

Compression (measured, 4 MiB blocks, single thread, Windows, this data):

| Data | Size | zlib-1 ratio / speed | zlib-6 | lzma-0 |
|---|---|---|---|---|
| `fr3` levels | 200 MB | 97.9 % / 35 MB/s | 98.0 % | 96.2 % / 8 MB/s |
| `*.DGO` | 203 MB | 52.3 % / 52 MB/s | 49.3 % | 43.0 % / 15 MB/s |
| `*.CGO` | 13.5 MB | 34.6 % | 31.4 % | 25.7 % |
| `*.STR` | 103 MB | 50.4 % / 54 MB/s | 48.8 % | 38.6 % / 18 MB/s |
| `VAGWAD.ENG` | 166 MB | 73.3 % / 30 MB/s | 72.4 % | 72.3 % |
| `*.MUS *.SBK *.VIS` | 26 MB | 75-82 % | | |
| `*.TXT` | 4.4 MB | 33.1 % | 28.2 % | 25.7 % |

Choice: **raw deflate level 1 per 4 MiB frame, decided per frame by sampling 64 KiB** (use deflate only if the sample shrinks below 70 % and the
frame below 90 %), big files get their own frames. Level 1 because levels 3/6 gain 1 to 2 percentage points for 10 to 50 % more CPU; lzma is 3 to 5 times
slower. `fr3` (already zstd inside) and voice banks go raw. Result: 729 MB raw -> 553 MB wire, 2.6 s with 8 threads (4.9 s with 2). A faster codec (zstd) is
not in the Python standard library before 3.14; the console already links zstd, so a codec 2 can be added later without changing the format.

## 3. Flow

```
detect ISO (serial -> game/region/variant)     reads ~100 KB, same rules as importer.cpp
tools   official release v0.3.6 (= ports/upstream.lock commit 553a713, git tag checked) -> ~/.opengoal-ps5/tools, size + sha256 verified
extract extractor --extract --validate         ISO -> <proj>/iso_data/<game>
decompile extractor --decompile                -> <proj>/decompiler_out/<game> (raw_obj/*.go ...) and <proj>/out/<game>/fr3
text    goalc -c '(make-group "text")'         -> out/<game>/iso/*.TXT          (fallback without codepack: extractor --compile, slow)
pack    plan the play set (sizes only), build DGO/CGO lazily from codepack .o + raw_obj .go
upload  tar -> 4 MiB frames -> thread pool (deflate-1 / raw) -> ONE TCP connection -> PUT /api/install   (compress + send overlap)
install console verifies CRC32 + size, renames data.new -> data, answers; then the optional extras (mode=add)
```

Project directory = official release `data/` overlaid with **our pack** (`pack.tgz`: patched `goal_src`, game assets with the PS5 in-game
texts, shaders, `codepacks/<variant>.tar`). Without `--pack` the official unpatched data is used: fine for a dry run, but the text would lack
the PS5 settings entries and no codepack exists (fallback compile).

## 4. The play set (what the console needs at runtime)

Derived from the engine source and checked by booting the official Linux `gk --no-display -- -boot -fakeiso` for 50 to 75 s on the assembled tree
(identical to the full build tree: 435 `link finish` lines in both, same log). **Not tested: rendering, fr3 loading and gameplay** (no display).

| Path under `/data/opengoal/<game>/data` | Why | Jak 1 PAL size |
|---|---|---|
| `out/<game>/iso/*` (DGO, CGO, TXT, STR, MUS, SBK, VIS, VAGWAD.ENG, drivers) | fake-iso: `game/overlord/common/fake_iso.cpp` lists this dir; `kmachine.cpp` reads `SCREEN1.*` | 522 MB with ENG voices only |
| `out/<game>/fr3/*.fr3` | `game/graphics/pipelines/opengl.cpp:117` | 200 MB |
| `game/assets/<game>/**`, `game/assets/fonts/**`, `game/assets/sdl_controller_db.txt` | subtitles, custom text, fonts, controller db (`input_manager.cpp:49`, `debug_gui.cpp:285`) | about 10 MB |
| `game/graphics/opengl_renderer/shaders/**` | shader sources | 0.1 MB |
| `goal_src/user/` (empty directory) | the runtime throws `filesystem_error` at start when it is missing (seen) | 0 |
| `.ps5ready` | marker written by the receiver (JSON: serial, region, time) | |
| **Core total** | 531 files | **729 MB raw, 553 MB wire** |
| extras: `VAGWAD.FRE/GER/ITA/JAP/SPA` | other voice languages, sent after the game is playable; if the user switches to a language whose bank is missing the overlord prints `failed to find VAGWAD` (**behaviour on the console unknown**) | 5 x 166 MB |

Not shipped, with the reason: `out/<game>/obj/*` (204 MB; `load_and_link` of single objects is only reached from `load-object`, no `goal_src` calls it; the DGOs contain every object);
`iso_data`, `decompiler_out` (build time only); `custom_assets/*` (only goalc `build-level`); `game/assets/<other game>` (11 MB); `TSZ.DGO`/`test-zone.fr3` (custom test level); logs and `imgui.ini` (runtime creates them).
`installed()` in `webserver.cpp` therefore now checks `out/<id>/fr3`, `out/<id>/iso` and `game/assets` (it used to require `obj`; old installs still pass).

The assembled tree was compared with the full goalc build: all 316 shipped `iso` files are **byte identical** to the Linux build (DGOs rebuilt in Python, TXT from goalc, copies from the disc).
`fr3` files are **not deterministic**: two runs of the same extractor on the same machine differ in size (11,284,639 vs 11,282,519 for `beach.fr3`), Windows vs Linux differ by 2.5 % (10,997,044).
The decompiler is the same code, so this is assumed harmless, but a Windows-extracted `fr3` has never been loaded by the PS5 renderer (open item).

## 5. Wire format and the console receiver

Stream (`PS5IMP01`): magic, then frames `{u32 codec, u32 clen, u32 rlen, payload}` little endian: codec 0 raw, 1 raw deflate (RFC 1951, no zlib header), 255 END with
`u32 crc32` + `u64 byte count` of the whole raw stream. The raw stream is one ustar archive: regular files and directories only, names up to 99 characters.
Reference encoder/decoder: `pc_import.py` (`stream_frames`, `unpack_stream`); receiver: `ps5shim/install_stream.h` (state machine, bytes in, no sockets), `ps5shim/inflate_lite.h`
(about 200 lines, table driven, no zlib dependency because the console build links zstd but not zlib).

```
GET /api/info                         {"install_api":1,"max_frame":16777216,"codecs":["raw","deflate"],"busy":false}
PUT /api/install?game=jak1&total=RAW_TAR_BYTES&mode=replace|add&serial=SCES-50361&region=PAL
    body = the stream, no Content-Length (self delimiting). 200 {"ok":true,"files":531,"bytes":...,"mode":"replace"}
    409 {"error":"busy"|"nogame"}  400 {"error":"total"}  422 {"error":"bad_contents"|"cancelled"}  500 {"error":"io"|"no_space"}
```

`webserver.cpp` `handle_install` (all existing `/api/*` unchanged; `tests_webserver_host.sh` still passes):

* one install at a time, refused (409) while this game is verifying, queued, importing or has an upload that sent bytes in the last 10 s;
* `replace`: unpacks while receiving into `/data/opengoal/<game>/data.new` (files written straight to their final name, no temp copy, no second pass), verifies CRC32 and the declared total,
  writes `.ps5ready`, renames `data` -> `data.old`, `data.new` -> `data`, deletes `data.old` in a background thread; on any error `data.new` is removed and the old install is untouched;
  **a successful replace deletes the previous install of that game** (back it up first, section 9);
* `add`: merges into the existing `data` (used for the voice banks), every file written as `<name>.part` and renamed, so a playable game never sees a half file;
* paths are validated (no `..`, no absolute path, no `\`, `:` or control characters, files and directories only, links refused); a tar entry outside the allowed form fails the whole install;
* after an error the answer is sent and the connection is drained for up to 64 MB / 1 s before closing (otherwise the TCP reset can destroy the answer); the client also reads while it sends;
* `POST /api/cancel?game=` during an install stops it (`reason` `cancelled`, 422);
* no `statvfs` (it crashes on the PS5 SDK, see the existing comment); a full disk shows up as `ENOSPC` -> `no_space`. No `fsync`: a power loss during the final seconds can leave a partial game that still carries `.ps5ready`.

Status integration (no change to `launcher.cpp`, `ps5import.h` unchanged): while installing, `ps5_game_status` reports `phase = 4 (importing)`, `stage = 0` (the launcher labels that
"Installing"/"Einrichten"), `percent` = `stage_percent` = bytes received / total (max 99), `bytes`, `total`, `speed_bps`, `eta_s`, `elapsed_s`, `serial`, `region`; the launcher's detail line
therefore reads "Installing 37%" and the speed line "xx MB/s - n s left". `ps5_import_queue_text()` returns "Jak and Daxter: installing 37%". Afterwards `phase = 5 (done)` (`installed` becomes 1) or
`phase = 6 (failed)` with `reason` in `io no_space bad_contents cancelled` (existing keys of the launcher and the web page). `/api/status` shows `"stage":"install"`; `webpage.cpp` got the
text `install` (EN/DE) and counts it as the last step.

## 6. CLI contract (for the GUI)

```
pc_import.py --game auto|jak1|jak2|jak3 --iso PATH --ps5 IP [--port 8080] [--tools-dir DIR] [--jobs N] [--json-progress]
             [--pack PACK.tgz | --proj-dir DIR] [--codepack FILE] [--voices all|en] [--cache-dir DIR]
             [--dry-run] [--out DIR] [--keep-work]
```

* `--tools-dir DIR` uses `DIR/extractor[.exe]`, `goalc`, `data/` as they are (no download, no hash check). Default: download once to `~/.opengoal-ps5/tools/v0.3.6/<windows|linux|macos-arm|macos-intel>` (urllib, size and sha256 pinned in the script, verified, reused).
* `--dry-run` runs everything except the upload and prints the byte counts; `--out DIR` additionally writes the finished tree to `DIR/data` **through the real wire format and reference decoder** (so it tests the stream too) and implies `--dry-run`.
* `--jobs` = compression threads (default `min(8, cpus)`).
* Exit code 0 ok, 1 failed (the last JSON line says why).
* `--json-progress`: one JSON object per line, flushed:
  `{"phase":"detect|tools|extract|decompile|compile|pack|upload|install|done|failed","percent":0-100,"overall":0-100,"speed_bps":N,"eta_s":N,"elapsed_s":N.N,"message":"...","game":"jak1","serial":"SCES-50361"}`.
  `percent` is the phase, `overall` the whole run (weights are estimates, `compile` is 1 with a codepack and 45 without). `speed_bps`/`eta_s` are only meaningful in `upload` (-1/0 otherwise).
  `pack` adds `total_bytes`. After the core install a line `{"phase":"install","percent":100,"message":"playable","playable":true}` appears (**the game can be started now**), then the optional voice
  upload (`upload` again, mode add), then `done`. A failed voice upload only adds `"warning"` to an `install` line. `failed` carries `"reason"`: `tiny notiso raw truncated nosys unknown wrong_game`
  (disc), `tools`, `net`, `console_old`, `extract`, `decompile`, `compile`, `bad_contents`, `pack`, `busy`, `no_space`, `io`, `cancelled` (console answers).
* Maintainer modes: `--make-codepack OUT.tar --from-build PROJ`, `--make-pack OUT.tgz --from-tree JAK_DIR [--codepacks DIR]`, `--selftest`.

## 7. Portability: do the PC-built objects run on the PS5 engine?

* The precompiled objects are x86-64 GOAL code with link data; the engine links them at load time (`link_and_exec`); by reading only (not audited line by line) they contain no absolute host addresses; the runtime
  provides the symbol table base (r15/r14 convention) and calls C++ functions through its own trampolines (`kscheme.cpp` has `_WIN32` and POSIX variants). The PS5 engine
  is the same code base as the Linux runtime with SysV calling convention, and an install already works with objects built by the console's FreeBSD goalc.
* **Measured, and the reason the codepack must be built on a POSIX goalc and shipped, not rebuilt on the user's PC:** 97 of the 518 `.o` produced by the *Windows* goalc differ from the Linux
  ones (a few bytes each, e.g. `xor r12,r12` vs `xor r10,r10`: different register allocation), so 21 DGO/CGO differ. Two Linux builds are byte identical to each other (518/518). The Windows output
  is probably valid on SysV, but that is **unverified**; the fallback compile therefore warns on Windows. macOS was not tested (no machine): its goalc is expected to behave like Linux.
* **Console-built vs Linux-built objects are not byte identical** (comparison by size with `docs/console_jak1_tree.txt`): 1031 of 1039 `obj` files and 24 of 27 DGO/CGO files have the same size; the 8
  `.o` that differ are `collide-cache`, `collide-edge-grab`, `collide-mesh`, `collide-reaction-target`, `fisher` (not patched by us, 2 to 16 bytes) and the three PS5-patched sources `text-h`, `pckernel-common`, `progress-pc`
  (the console install may predate the current patch set). So the official Linux goalc and the console's goalc do not generate identical code for 5 files; semantics are assumed equal. **Safest codepack
  source: the objects of a working console install** (section 8).
* Legal: the codepack and the pack contain only the open-source `goal_src` (patched by `ports/manifest.json`) compiled, nothing derived from a disc. Everything disc-derived (STR/MUS/VAG/DGO data, raw_obj, TXT, fr3) is produced on the user's PC from the user's own ISO and is not stored anywhere else.
  Codepack/pack are bound to the engine: they must be rebuilt whenever `ports/upstream.lock` or the manifest patches change (they carry `release` and `serial`/key in `recipe.json`; there is no automatic compatibility check yet).

## 8. Maintainer: producing the pack and codepacks

Per disc variant (needs one ISO of that variant; only PAL jak1 was available here):

```
# 1. Linux/WSL, official Linux tools + the patched tree, full build once
EX=~/tools/extractor; P=~/proj          # P = copy of the patched tree with goal_src game/assets decompiler/config (see make_skeleton.py include list)
$EX game.iso --proj-path $P --game jak1 --extract --validate
$EX $P/iso_data/jak1 --folder --proj-path $P --game jak1 --decompile --compile
# 2. harvest (verifies all DGOs byte for byte)
python3 pc_import.py --make-codepack cps/jak1-SCEE.tar --from-build $P
# 3. the pack the PCs download
python3 pc_import.py --make-pack pack.tgz --from-tree ~/jak --codepacks cps        # 21 MB, prints the sha256
```

Recommended instead of step 1's compile, because those objects are proven on the PS5 engine: use a working console install. Copy `out/jak1/obj/*.o` (and the console's `iso/*.DGO,*.CGO,*.TXT`
for the byte comparison) next to a PC extract + decompile into `$P/out/jak1/`, then run step 2; `--make-codepack` fails if the PC-decompiled `raw_obj` or the objects do not rebuild the console's DGOs exactly.
(Needs FTP access to the console; **not done here**.) Variant keys: `jak1-SCEA`, `jak1-SCEA-bl` (SCUS-97124 with ELF hash 7280758013604870207), `jak1-SCEE`, `jak1-SCEI`, `jak2-<territory>`, `jak3-<territory>`.
Only `jak1-SCEE` exists (`~/pcimp/cps/jak1-SCEE.tar` in WSL, 2.7 MB; the pack `~/pcimp/pack.tgz`, 21 MB, sha256 15a18a26157745bc7adf7f2c9f8b6ee476ddbc3016d629858f5a7cfab7048bcc). Jak 2 and Jak 3 were
never run: their `.gd` discovery, recipe and play set are untested (the codepack builder would refuse to write a wrong DGO recipe, the rest is unverified).

## 9. How to verify on the console (the main session)

0. Back up what works. A successful `replace` deletes the old `data`: `mv /data/opengoal/jak1/data /data/opengoal/jak1_bak/data` (or copy) before the test.
1. Build/deploy the app with the new `ps5shim/webserver.cpp`, `install_stream.h`, `inflate_lite.h`, `webpage.cpp` (no build script change: header-only; `webserver.cpp` still compiles with the same flags, host check below).
2. `curl http://<ps5>:8080/api/info` must answer `{"install_api":1,...}`.
3. From the PC (use the PAL pack above for the PAL disc; any other variant falls back to the slow full build, expect about 45 to 50 s more):
   `python pc_import.py --game auto --iso C:\path\jak1.iso --ps5 <ps5-ip> --pack pack.tgz --json-progress`
   The last `install` line with `"playable":true` is the time to quote. Watch `curl http://<ps5>:8080/api/status` (stage `install`, percent, speed) and the launcher card.
4. Check the tree over FTP: `/data/opengoal/jak1/data/{.ps5ready,out/jak1/iso,out/jak1/fr3,game/assets/jak1,game/graphics/opengl_renderer/shaders,goal_src/user}`; compare the `iso` file list and sizes with the old install (`docs/console_jak1_tree.txt`): DGO/CGO/STR/VAG equal, TXT/fr3 may differ.
5. Start the game from the launcher; play through the intro and a level change (fr3 loading, voices, movies). Then switch the in-game language to check the extra voice banks.
6. Negative tests: pull the cable during the upload (expect `data` untouched and no `data.new`), `pc_import.py --ps5 <ip>` while a second install runs (409 busy), cancel from the web page.
7. Host checks (no console): `python3 pc_import.py --selftest`; `bash tests_install_host.sh` (WSL; builds the real `webserver.cpp` with a stubbed importer, drives it with the real `pc_import.py` upload code: replace twice, add, corrupt stream, truncated stream, `..` and absolute paths, wrong total, receiver with 1/7/4093-byte pieces);
   `bash tests_webserver_host.sh` (old API); `g++ -std=c++17 -fsyntax-only -Wall -Wextra -I ps5shim -I ~/jak ps5shim/webserver.cpp ps5shim/importer.cpp ps5shim/webpage.cpp`; `node tests_onboarding_web.js`.

## 10. Risks and open items

* **Not run on the console at all.** Receiver speed on the PS5 (CRC32, inflate, many small file creates, flash write speed) is unknown; the host receiver does 278 to 415 MB/s raw without disk.
* The 1-minute figure depends on the home network; Wi-Fi at 30 MB/s costs about 18 s for the core set. Voice banks of other languages add 829 MB for this disc.
* `fr3` from the Windows/macOS extractor never loaded by the PS5 renderer; `fr3` is nondeterministic and differs from the Linux output in size (assumed fine).
* Windows/macOS-built objects (fallback compile) unverified on the engine; codepack built with the *official Linux* goalc differs in 5 files from the console's own goalc (section 7). Prefer the console-harvested codepack.
* Only `jak1-SCEE` codepack and only PAL Jak 1 were run. Region-dependent code (`*default-territory*`, `*jak1-full-game*`) is why variants exist; an unlisted variant silently takes the slow fallback.
* `obj/` and the other voice banks are assumed unneeded; evidence is source reading plus a headless boot, not a played game. If the engine needs `obj`, add it to `play_entries` (+204 MB).
* `replace` deletes the previous install; no fsync; the swap happens while the app runs (if the game process is running from `data`, do not install).
* `mode=add` is not atomic as a whole (per file only). A second concurrent import for another game is allowed (only CPU contention).
* Python `zlib.crc32` and deflate release the GIL, the producer is one thread: the sender tops out around 300 to 500 MB/s, far above the network, but a slow disk on the PC (HDD) makes extract (1.4 GB) and the reads the bottleneck.
* The pack/codepack have no signature or automatic engine-compatibility check; the tools download is pinned by sha256 but the pack URL/hosting is not decided (use `--pack`).
* macOS: asset names and sha256 are from the release API, never downloaded or run here. Apple Silicon support in upstream arrived after v0.3.6 (UPSTREAM_SYNC.md); the arm64 asset may not extract/decompile.
