# QA pipeline (`qa_pipeline.py`)

Automatic gate to run after every upstream sync or patch change. Written and tested offline only (fake logs and images); never run against the console by its author.

## Usage

```
python qa_pipeline.py --quick                           # jak1/jak2 30 s, jak3 60 s (rplay fixed cost is about 2 min extra), compare with baseline
python qa_pipeline.py --full --build --deploy           # WSL build, kill + deploy, 90/90/190 s with the tracer (flag `trace` added)
python qa_pipeline.py --full --update-baseline          # collects twice (A, A2), writes baseline + golden + noise masks; --runs 1 skips the noise run
python qa_pipeline.py --analyze qa/runs/<stamp>_full    # offline re-analysis of a collected run (no console access)
python qa_pipeline.py --dry-run --full                  # print the plan
```
Options: `--games jak2,jak3`, `--flags asyncmultidraw` (shipping config, passed to perfround; perfround deletes every other flag file), `--no-trace`,
`--tol key=value` (see `TOL` in the script), `--klog-file path` (kernel log text, e.g. from `m1/klog_dump.elf`, scanned for crash patterns),
`--force-deploy`. Exit code 0 PASS, 1 WARN, 2 FAIL, 3 pipeline error. Run the console steps one at a time; do not run two pipelines at once (one UDP listener).

## What it does

Collect (per game, `qa/runs/<stamp>_<mode>/run1/<game>/`): `shotseries.request_shots` (shot.txt) -> `perfround.py` (udp.log, console.log, trace) -> `ps5.py kill` (always, in a `finally`)
-> fetch `shot_<i>.png` -> `trace2json.py` statistics. Each subprocess has a timeout; output goes to `collect.out` / `pipeline.out`. At the end `shot.txt` and `trace.txt` are removed from the console.
It never writes kernel flags, never restarts the console, never loads payloads other than what `ps5.py kill/deploy` already does.

Analyse (pure python, `analyze_game`):
- Crash: patterns `CRASH`, `fault address`, `# rip`, `sceSblAuthMgr`, `0x80020008`, `SIGSEGV/BUS/ILL/ABRT`, `ucontext`, `unexpected error N` in udp.log, console.log, optional klog. Silent return to the launcher: too few `fps:` samples
  (below 50 % of secs/3) or, for timestamped logs, fps lines ending more than 15 s before the log end. Any hit is FAIL.
- Frame stats over the steady part (first `warm` fraction of 3 s samples skipped): avg fps, min, p1 low (of the 3 s fps samples), frames >20 ms and >33 ms per 3 s window (`frametime:` lines), worst frame ms.
  Trace (full mode): driver draw_vbo ms/frame, calls/frame, us per draw.
- Compare with `qa/baseline.json` (per mode): fps drop warn 5 % / fail 10 % (raised to 3x / 4.5x the A-vs-A2 fps noise), p1 15 / 30 %, frames >33 ms +1 / +3 per 3 s, >20 ms +2 / +6, driver +10 / +25 %.
- Screenshots (shot times fixed per scenario): diff vs `qa/golden/<mode>/<game>_<i>.png` with threshold 16, outside the learned mask `*.mask.png` (pixels that differ between A and A2, dilated 6 px).
  Warn above 0.5 % pixels or a region over 300 px, fail above 8 % or a region over 6000 px. If A vs A2 already differed over 5 % (non-deterministic scene) the result is capped at WARN. Heatmaps go to the report folder.
- Glitch heuristics (`glitch_checks`): FAIL for black frame, one colour over 97 %, over 50 % saturated white, magenta fill (NaN/missing texture look). With a golden: WARN if uniform tiles grow by 15 points,
  high-frequency garbage tiles by 10 points, or the HUD bands (top/bottom 10 %) lose edge energy below 40 % of golden. Without golden: WARN if over 80 % of tiles are uniform.
- Verdict = worst finding. Reports: `qa/reports/<date>/report_<mode>_<time>.{md,json}` plus heatmaps. No baseline for a game = WARN. `--update-baseline` refuses a run that has any FAIL (crash, short run).

Scenarios (`SCENARIOS` in the script, overridable per mode/game in `qa/scenarios.json`, e.g. `{"full": {"jak3": {"shots": [{"name": "spawn", "t": 70}]}}}`):
quick = boot/title/play at 6/14/26 s (jak3 10/30/50 s); full jak1/jak2 = boot 8, title 20, spawn/city 40-45, play 60, play2 80 (secs 90); jak3 = 10/30/60/100/130 (secs 190).

## Tests

`python -m unittest tests/test_qa_pipeline.py` (9 tests, fake logs and synthetic 480x270 images): log stats, silent return, crash patterns, trace parse, absolute and relative glitch checks, mask learning (animated patch ignored, new glitch region found at the right place),
end-to-end update-baseline -> PASS rerun -> FAIL regression -> WARN without baseline -> refuse crashed baseline, dry run.

## Unverified (needs the console)

- The collect phase has never been run: `perfround.py` for `jak1` (assumed to work through `ps5.py run jak1`), the interplay of `shot.txt` with the jak3 launcher -> game process restart (shot times may be relative to the launcher, adjust `qa/scenarios.json`),
  whether `shot.txt` is honoured by the launcher process of jak1/jak2, and that `ps5.py kill` after perfround leaves nothing running.
- Real thresholds: the defaults are guesses; measure the A-vs-A2 noise (`--update-baseline`) and tune with `--tol`. Real 1080p screenshots were not tested (synthetic 480x270 only; masks and compare scale with size, region pixel limits do not).
- `perfround.py` deletes `asyncmultidraw.txt` unless it is in `--flags` (default is). `perfround.py` has a hard-coded IP; `shotseries` uses `PS5_IP`.
- klog is not fetched automatically (needs a payload); pass `--klog-file`. Crash detection otherwise relies on UDP `CRASH` lines and the tail of `ps5.log`.
- Shots taken at wall-clock seconds can land in a different game state (cutscenes) run to run; that shows up as an unstable scene (capped at WARN) only if the baseline A/A2 pair differed.
