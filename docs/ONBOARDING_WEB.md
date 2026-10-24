# ISO onboarding web page

Served by the app on port 8080. Files: `app/shim/webpage.cpp` (page), `webserver.cpp` (HTTP, SSE, upload, queue, status), `importer.cpp`
(extractor wrapper, ISO pre-check, progress hooks), `import_progress.h` (pure percent/ETA logic, host-tested), `include/ps5import.h`
(C API for the launcher), `engine/patch_import_progress.py` (optional upstream patch). No external requests, no dependencies, no images
(game cards are CSS gradients with a numeral). Language follows the browser (de/en), toggle top right. Honours `prefers-reduced-motion`.

## Flow

1. Drop one or many `.iso` files (or click). Browser pre-check (about 100 KB read, no hashing): extension, size >= 64 MB, ISO9660 PVD,
   raw `.bin` detection, file size >= PVD volume size, `SYSTEM.CNF;1`, ELF name -> serial -> game + region. A second file for the same game is rejected.
2. Upload one game at a time, 4 parallel 32 MB chunks, written with `pwrite()` straight into `<game>.part` (preallocated sparse, renamed to
   `<game>.iso`, never copied). The next game uploads while the previous one imports.
3. `POST /api/start` checks that all chunks are in, runs the authoritative pre-check on the console and queues the game.
4. `queue_loop` runs the imports one after another. The queue lives on the console, closing the browser does not stop it.
5. After the import the `.iso` is deleted (setting `delete_iso`, default on; also deleted when the import fails or is cancelled).

## Live updates

The page opens `GET /api/events` (server-sent events, one JSON per 250 ms). If the stream is silent for 1.5 s it falls back to polling
`/api/status` every 250 ms. DOM writes are keyed and skip unchanged values, so bars animate smoothly with a 0.25 s CSS transition.
Per game: a main bar (overall percent, whole game including upload), a thin stage bar (percent of the current stage), speed, ETA, elapsed,
step strip (Upload, Check, Unpack, Analyse, Build). When two or more games are in the session a combined "All games" bar appears.

## Resumable upload, reload, cancel

- `POST /api/begin?game=&total=&chunk=&fp=`: `fp` is `size-lastModified-name`. If `<game>.meta` + `.part` match (same fp, size, chunk size) the
  upload resumes and the answer is `{"resume":[finished chunk offsets],"chunk":N,"status":{...}}`; the page sends only the missing chunks.
  Otherwise the upload restarts (space check: ISO size + 512 MB).
- Finished chunks are recorded in `<game>.done` (one offset per line) and survive page reloads and app restarts (`restore_uploads()` at start).
  After a reload the card shows "Upload interrupted, drop the same file again" (status `idle` >= 4 s); dropping the same file continues.
- `POST /api/start` returns 409 when chunks are missing; the page retries `begin` once (resume) automatically, then shows `incomplete`.
- `POST /api/cancel?game=`: uploading -> files removed, idle; queued -> removed from the queue, ISO deleted; importing -> the importer is told
  to stop, it ends as `failed` with reason `cancelled`; done/failed -> card dismissed (idle).
  Cancelling a running import: `ps5_import_log`/`ps5_import_progress` throw `ImportCancel` on the import thread only (other extractor threads are never
  interrupted). Needs the upstream patch; without it the cancel takes effect only at the next stage boundary (`ps5_import_stage_set`).

## HTTP API

| Request | Meaning |
|---|---|
| `GET /` | the page |
| `GET /api/status` | status JSON v3 |
| `GET /api/events` | same JSON as `text/event-stream` |
| `POST /api/begin?game=jakN&total=BYTES&chunk=BYTES&fp=STR` | start/resume upload. 200, 409 `{"error":"busy"\|"no_space"\|"io"}`, 400 `{"error":"total"}` |
| `PUT /api/chunk?game=&off=&total=` | raw body at offset; 409 if no upload in progress |
| `POST /api/start?game=` | verify + queue. 200 queued, 422 rejected (`reason` in status), 409 not complete / not uploading |
| `POST /api/cancel?game=` | see above |
| `GET|POST /api/settings?delete_iso=0\|1` | read / set (POST writes `/data/opengoal/config/delete_iso.txt`) |
| `GET /api/info` | `{"install_api":1,...}`: the console can receive a PC import stream |
| `PUT /api/install?game=&total=&mode=replace\|add&serial=&region=` | PC import: self-delimiting stream, unpacked while it arrives (see `docs/PC_IMPORT.md`). Shows as phase `importing`, stage `install` (C API: phase 4, stage 0) |

## `/api/status` (version 3)

```
{"version":3,"ip":"...","busy":true,"current":"jak2","queue":["jak3"],
 "games":{"jak2":{"installed":false,"phase":"importing","stage":"decompile","percent":47,"stage_percent":50,
                  "bytes":0,"total":0,"speed":0,"eta":140,"elapsed":125,"idle":-1,"serial":"SCUS-97265","region":"NTSC-U","reason":""}, ...},
 "overall":{"games":2,"percent":30,"eta":400},          // games of this session (uploading..done); eta -1 if unknown
 "settings":{"delete_iso":true},
 "upload":{...legacy}, "import":{...legacy}}
```

`phase`: `idle uploading verifying queued importing done failed`. `stage` (importing): `prepare extract decompile compile`.
`percent` overall 0..99 (100 when done, -1 idle), `stage_percent` -1 unknown, `speed` upload bytes/s, `eta` seconds or -1, `idle` seconds since the last
chunk byte (-1 never). `reason`: pre-check `notiso tiny raw truncated nosys unknown wrong_game`; import `toolchain unknown_disc bad_contents bad_iso extract decompile compile cancelled`;
transient `cancelling` while a running import is being stopped; page-only `ext dup busy no_space io net incomplete`.

## C API for the launcher (`app/shim/include/ps5import.h`)

```c
struct Ps5GameStatus { int installed; int phase /*0 idle,1 uploading,2 verifying,3 queued,4 importing,5 done,6 failed*/;
  int stage /*0 none,1 prepare,2 extract,3 decompile,4 compile*/; int percent /*-1..100*/; int stage_percent /*-1..100*/;
  unsigned long long bytes, total; unsigned speed_bps; int eta_s; int elapsed_s; char serial[16]; char region[8]; char reason[24]; };
int ps5_game_status(const char* game /*jak1|jak2|jak3*/, Ps5GameStatus* out);   // 0 ok, -1 unknown game
const char* ps5_import_queue_text(void);   // "Jak II: decompiling 50% (+1 waiting)", "" when idle; valid until the next call on that thread
```
Implemented in `webserver.cpp` (same data as the JSON). Thread safe (one mutex). Old entry points (`ps5_web_progress`, `ps5_import_state/rc/stage/percent`) are kept.

## How the percent is obtained

| Stage | Source | Notes |
|---|---|---|
| prepare | tar entries processed / tar size (importer.cpp) | only when the toolchain pack must be unpacked |
| extract | `Extracting X, size 0x..` log line of `unpack_entry`, bytes done / ISO size | measured design, needs the upstream log hook |
| decompile | `[Mem] After ...` milestone lines (weights in `import_progress.h`) and one `stats for <level>` line per extracted level between "textures" (52%) and "extraction" (96%) | milestone weights and expected level counts (22/30/30) are estimates |
| compile | goalc `MakeSystem::make` loop: `ps5_import_progress(4, done, total)` per build target | exact count of targets |

All of this needs `engine/patch_import_progress.py` (manifest step `import-progress`, required=false, requires `core`). It adds weak hooks to
`common/log/log.cpp` (`ps5_import_log`) and `goalc/make/MakeSystem.cpp` (`ps5_import_progress`), implemented in `importer.cpp`. Without the patch the
page still works: stage names, elapsed, indeterminate stage bar, overall percent only moves at stage boundaries.

Overall percent bands (`import_progress.h`, ESTIMATES, no timing logs exist on this machine): upload 10, verify 2, then per game
prepare/extract/decompile/compile = 1/10/24/53 (jak1), 1/11/25/51 (jak2, jak3). ETA: upload = bytes left / smoothed speed; import = linear
extrapolation of the import's own progress (not before 3 percentage points and 5 s). Re-measure from the `import: stage ...` lines in the console log and edit `kStageW`.

## Speed: what was found and changed

Read in `~/jak` (decompiler/extractor/main.cpp, common/util/read_iso_file.cpp, decompiler/decompilation_process.cpp, level_extractor, goalc/make):

1. Upload: already streamed straight to the final file, 4 parallel connections, 32 MB chunks. Changed: sparse preallocation (`ftruncate`), 2 MB socket reads (was 1 MB),
   `MSG_NOSIGNAL`; no copy and no re-read (the ISO is read once by the extractor, the pre-check reads about 100 KB).
2. Extractor copied the whole extracted disc (`fs::copy` recursive `iso_data/_temp` -> `iso_data/<game>`, GBs of writes and then `remove_all`). Patch: `fs::rename`, copy only as fallback. Biggest I/O saving.
3. Log volume: with the patch the importer hook keeps all info lines and `lg::print` compile lines off stdout (and off the log file for print lines);
   only warn/error/die and lines with "rror"/"ailed" reach `ps5_log`. This removes one `fmt::print` + `fflush` per extracted file and per build target.
4. Already optimal / not changed: the decompiler config of all three games has `decompile_code:false` (no function decompilation, the "decompile" stage is data/level/texture extraction),
   `rip_levels`, `rip_collision`, `save_texture_pngs`, `rip_streamed_audio`, `process_art_groups`, `dump_*` are all false. `dump_objs:true` looks like debug output but is
   **required**: `goal_src/jak1/game.gp` and `lib/project-lib.gp` read `decompiler_out/<game>/raw_obj/*.go`. Do not turn it off.
5. Threads: level extraction (`SimpleThreadGroup`) already starts one thread per level (`num_workers = dgo_names.size()`), so all cores are used there (peak memory is the risk,
   not speed; capping to the core count would give a static partition and could be slower). `unpack_iso_files`, `process_tpages`, `find_code`, and the goalc build (`(mi)`,
   one compiler instance, sequential targets) are single-threaded in upstream; the goalc build is expected to be the longest part and cannot be parallelised without
   an upstream rewrite. Not done.
6. Keep awake: `queue_loop` calls `sceSystemServicePowerTick()` (weak symbol) every 10 s while busy.

Expected times, ESTIMATES only (nothing was timed on the console; no import logs exist in this repo): the I/O saving of the rename (one full copy of the extracted disc,
roughly 1 to 4 GB depending on the game) is worth about tens of seconds up to a few minutes on console flash; log reduction a few percent of the extract/compile stages.
Do not quote a before/after number until `import: stage` timestamps from a real run exist. Measure: the console log has `import: stage <name>` lines with timestamps; compare runs with the patch step on/off.

## Tests

- `tests/test_onboarding_web.js` (node): page script with stubbed DOM and mocked API (serial detection, rejections, sequential upload, duplicate, resume skips chunks, speed/ETA/percent text,
  stalled upload, overall bar, failure text, cancel call, German and English). Passes.
- `tests/host/import_progress_test.cpp`: percent bands sum to 100, monotonic overall, ETA, log-line parser. Passes.
- `tests/host/webserver_host.sh` (WSL): compiles `webserver.cpp` with a stubbed importer and a temp data dir; begin / chunk / resume / start-incomplete (409) / start / status / SSE / cancel / settings. Passes.

## Not verified

- Nothing ran on the console or in a real browser; CSS/layout and the animations are checked by reading only. SSE in the PS5 browser/phone not tested. Real 4-way upload speed unknown.
- The upstream patch compiles in theory only (weak extern "C" declarations, `std::error_code` overload of `fs::rename`); the log hook runs on whatever thread logs, throwing `ImportCancel` only on the import thread.
  If goalc/the decompiler catch `(...)` around a log call, the cancel is swallowed and retried on the next log line.
- `sceSystemServicePowerTick` may not be exported/linked in this SDK (weak, so harmless if absent). Cancel leaves partial `iso_data/_temp` and `decompiler_out` behind.
- The `stats for` lines come from both `extract_common` and each level; the level counts per game and all stage weights are estimates.
- Free space: still only ISO + 512 MB at upload start; extraction needs roughly the ISO size again plus outputs (the `.iso` is deleted afterwards).
- Serial table is duplicated in `importer.cpp` and `webpage.cpp`; update both when upstream adds discs.

## PC import (alternative to the ISO upload)

`installer/pc_import.py` does the extract/decompile on the PC and sends the finished game with `PUT /api/install`; the status JSON, the C API and the launcher card use the existing fields (stage `install`). `installed()` now needs `out/<id>/fr3`, `out/<id>/iso` and `game/assets` (no longer `obj`). Details, measurements and the console test plan: `docs/PC_IMPORT.md`.
