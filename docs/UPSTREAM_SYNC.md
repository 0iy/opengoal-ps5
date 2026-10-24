# Syncing with upstream OpenGOAL (jak-project)

`engine/sync_upstream.py` (stdlib only, run it in WSL as `tools/ps5 sync --work ~/sync_work <cmd>`) pulls
https://github.com/open-goal/jak-project and ports it to the PS5 build with the patches listed in `engine/ports/manifest.json`.
It works only in `--work` (default `$SYNC_WORK` or `~/sync_work`) and refuses a work dir that overlaps `~/jak`, `~/gl`,
`~/ogapp`, `~/drv`, `~/ps5app`, `~/ps5build*`. It never touches the PS5.

## Files

| File | Role |
|---|---|
| `engine/ports/upstream.lock` | pinned upstream commit (base of our tree) + sha256 of the resulting patched diff (determinism check) |
| `engine/ports/manifest.json` | ordered steps (script or `.patch`), description, required/optional, `requires`, `touches`, `markers`, `anchors` |
| `engine/ports/patches/*.patch` | edits of the live tree that had no script; captured as patches (see below) |
| `engine/apply_ps5_patches.py`, `patch_gfxprof.py`, `patch_proftree.py`, `patch_ps5_ingame_settings.py`, `patch_fsr.py`, `patch_fsr_effects.py`, `patch_import_progress.py` | the patch scripts. They honour `JAK_ROOT`/`HOME` (private copy) and `SYNC_FILE_MAP` (relocation) |
| `engine/gen_manifest_anchors.py` | one-off: generated the `anchors` of the `core` step from the tables inside `apply_ps5_patches.py` (`patch_fsr.py` and `patch_fsr_effects.py` print their own step with `--emit-manifest`) |

## Commands

```
tools/ps5 sync status                 # pinned vs upstream HEAD / latest tag, commits ahead, patched files that changed
tools/ps5 sync fetch [--ref R]        # R = pinned (default) | head | latest-tag | tag | branch | sha ; submodules included
tools/ps5 sync preflight              # anchor check of every step against the fetched upstream (no writes besides the report)
tools/ps5 sync port                   # preflight, then copy + apply all steps on a fresh copy
tools/ps5 sync verify [--compile]     # static checks of the ported tree
tools/ps5 sync snapshot [--out DIR] [--compare FILE] [--update-lock]
tools/ps5 sync all [--ref R]          # fetch + port + verify + snapshot
```

Layout of the work dir: `upstream/` (clean checkout, never patched), `fetch.json`, `preflight.json`,
`port/home/jak` (the patched copy; `HOME` of the scripts is `port/home`, so their `~/jak` resolves to it), `port/state.json`,
`snapshot/` (`jak-project_vs_<sha7>.patch`, `jak-project_BASE_COMMIT.txt`, `jak-project_status.txt`); `snapshot --out DIR` writes elsewhere.

Exit codes: `0` ok (also AUTO-RELOCATED), `3` NEEDS-REVIEW or BROKEN somewhere, `1` hard error / failed apply, `2` only with
`--strict` when an optional step failed.

## Normal update

1. `status` - is there something new, and which of our files did upstream touch?
2. `fetch --ref latest-tag` (or `head`), then `preflight`. Read the summary and the changelog digest.
3. If the result is OK or AUTO-RELOCATED: `all --ref latest-tag`. Review the diff in `snapshot/`, then
   `snapshot --update-lock` (this moves the pin and the expected diff hash) and commit `engine/ports/`.
4. Copy the ported tree to the live `~/jak` and run the real build (`tools/ps5 build`) yourself. The tool does not.

## Pre-flight: how failures are detected before anything is written

Every step declares `anchors` in the manifest: `{id, file, kind: "text"|"function", text, count (int or "any"), name?}`.
`text` is the exact text the patch relies on (for scripts: the `old` strings/regex targets, line endings normalised to LF
as the scripts read files in text mode). `kind: "function"` anchors are the signature lines of functions we patch; they carry `name`
so `git log -L:name:file` can show the history. Each anchor is evaluated on the **pinned** commit first (an anchor that is
not there is a manifest error and makes the step BROKEN) and then on the new upstream:

| Anchor status | Meaning | Evidence in the report |
|---|---|---|
| found | expected number of matches in the same file | line shift vs pinned is shown, not escalated (scripts match text, not lines) |
| moved | same text, unique, in another file (rename seen by `git diff -M`, or found by `git grep` + full-text check) | old and new file |
| changed | text gone or count differs; best difflib window in the file is >= 0.60 similar (or several files match) | ratio, old/new side by side, suggested new anchor text, upstream commits (`git log -S<first line>`, `-L` for functions, else file history) |
| gone | file deleted or nothing similar left | best ratio, upstream commits |

Step classification (worst anchor wins, plus its `requires` steps):

| Class | Action by `port` |
|---|---|
| OK | applied |
| AUTO-RELOCATED | a moved anchor is unique: the step is applied with `SYNC_FILE_MAP={old path: new path}`; recorded in `port/state.json` `relocations` |
| NEEDS-REVIEW | changed/ambiguous anchor (or relocation of a `.patch`, whose paths are fixed): **required step: whole port aborts before writing anything; optional step: not applied**, exit 3 |
| BROKEN | gone / manifest error: same handling as NEEDS-REVIEW |

Output: human summary on stdout and `preflight.json` (`pinned`, `target`, `overall`, `steps[].class`, `steps[].file_map`,
`steps[].anchors[]` with `status`, `detail`, `lines`, `pinned_lines`, `ratio`, `old_snippet`, `new_snippet`, `suggested_anchor`,
`side_by_side`, `upstream_commits`; and `digest[]` = upstream commits since the pin that touch any file we patch or anchor).

If a script still fails at apply time (an assert the anchors do not mirror), the step is rolled back and the report names the
script line of the assert with the nearby `old = ...` definition, the file and the first anchor line's position (`apply_ps5_patches.py`
now reports every failing anchor, not only the first), or, for `.patch` steps, the hunk and line from `git apply`; plus the upstream
history and changed line ranges of the file. A required failure deletes the copy: **no half-patched tree is ever left**
(each successful step is committed inside the private copy, a failed one is `reset --hard`).

## Fixing a NEEDS-REVIEW / BROKEN step

1. Open `preflight.json` (or the console output) for the step; read the side-by-side and the upstream commits.
2. Edit the anchor text in the script (`old = ...` / `patch(...)`) to the new upstream wording and adjust the replacement the way
   upstream's change requires. Update the matching `anchors[].text` in `engine/ports/manifest.json` (the manifest is the source of truth for
   pre-flight; a stale anchor shows up as a manifest error when the pinned commit is checked).
3. `tools/ps5 sync --work W fetch` at the **pinned** ref and run `port` -> `snapshot --compare` must still reproduce the
   committed patch for scripts you only re-anchored. Then re-run `preflight` on the new ref.
4. Optional steps that are not worth the effort can be dropped for one run with `port --skip id`.
5. After the first successful `all` on the new ref: `snapshot --update-lock`.

## Determinism

* Upstream input is a commit sha from `engine/ports/upstream.lock`, never a branch.
* Steps run in manifest order on a fresh copy; scripts are idempotent, use no clock/random; git runs with `core.autocrlf=false`;
  Python text mode normalises CRLF to LF exactly as before (so FileUtil.cpp etc. show as whole-file diffs, as in the old snapshot).
* `diff --full-index base HEAD` is hashed (`diff_sha256` in `state.json`); `snapshot` compares it with `patched_diff_sha256` in the
  lock when the base is the pinned commit (`MATCH`/`MISMATCH`, exit 1 on mismatch).
* `verify` re-runs every script on the patched tree and requires no change (idempotence).

## Verify

Static: all required steps applied; only expected files changed and each expected file changed; markers present (`__ps5__`, step
markers); no `.rej/.orig`, no conflict markers or `__ps5__ TEST|diag` debris in added lines; tree clean; scripts idempotent.
`--compile` additionally runs `engine/compile_check.sh` (clang `-fsyntax-only` with the PS5 SDK libc++ headers) on the changed `.cpp`
files, with `HOME` = the private copy and a read-only symlink to `~/ps5app`; it needs the SDK and is not part of the default run.
A full link/ninja build is deliberately **not** run (the build scripts write to `~/ps5build`, `~/drv`, `~/ogapp`).

## What is not handled by this tool

| Part | Why |
|---|---|
| `driver/ps5-opengl.patch` | different upstream (ps5-opengl and Mesa); see [`driver/README.md`](../driver/README.md) |
| `app/shim/`, `app/glue/` | our own sources, not patches |
| `engine/ports/patches/0010-*.patch`, `0020-*.patch` | in the manifest; capture two edits that had no script (a `ps5_log` forward declaration in `opengl.cpp`; the slow-frame trigger and 28-line cap of the proftree dump) |

## Known limits

* Only jak-project is handled; the driver and the shim have their own upstream/lifecycle.
* Anchors are only as good as their declaration: a script edit that is not mirrored in the manifest is caught at apply time (runtime
  report), not in pre-flight. `apply_ps5_patches.py`'s global `#ifdef __linux__` replacement and the RGB texture regex are
  declared with `count: "any"`.
* Relocation is per file (`SYNC_FILE_MAP`); moving text between files inside one script step is NEEDS-REVIEW, and so is relocating a `.patch`.
* Newer upstream (v0.3.9) currently needs review in `core`: the Apple-Silicon commit (#4390) rewrote the `__linux__` branches in kscheme/mips2c,
  `runtime.cpp` main-memory mmap and the extractor `compile()` signature (#4420). Not ported yet.
