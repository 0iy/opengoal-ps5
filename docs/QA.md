# QA pipeline

Regression gate for the app on a real console: run it after every upstream sync, driver change or shim change. It collects fps, frame-time statistics, logs and
screenshots, compares them with a baseline and writes a report. The analysis half is pure Python and also runs offline on a saved run.

## Usage

```
tools/ps5 qa --quick                          # Jak 2 and Jak 1 30 s, Jak 3 60 s (Jak 3 needs about 2 min extra to reach gameplay), compare with the baseline
tools/ps5 qa --full --build --deploy          # build in WSL, kill and deploy, then 90/90/190 s runs with the driver tracer
tools/ps5 qa --full --update-baseline         # collect twice (A, A2), write baseline, golden screenshots and noise masks (--runs 1 skips the noise run)
tools/ps5 qa --analyze tests/qa/runs/<stamp>_full    # offline re-analysis of a collected run, no console access
tools/ps5 qa --dry-run --full                 # print the plan
```

Options: `--games jak2,jak3`, `--flags asyncmultidraw` (shipping config; `perfround` removes every other flag file), `--no-trace`, `--tol key=value`
(see `TOL` in `tools/qa_pipeline.py`), `--klog-file path` (kernel log text from `payloads/klog_dump.c`, scanned for crash patterns), `--force-deploy`.
Exit code: 0 PASS, 1 WARN, 2 FAIL, 3 pipeline error. Do not run two pipelines at once (one UDP listener).

## What it does

Collect, per game, into `tests/qa/runs/<stamp>_<mode>/run1/<game>/`: request screenshots (`shot.txt`), run `perfround.py` (UDP log, console log, trace),
close the app (always, in a `finally`), fetch the screenshots, compute trace statistics. Every subprocess has a timeout. At the end `shot.txt` and `trace.txt` are
removed from the console. It never writes kernel flags and never restarts the console.

Analysis:

- **Crash:** patterns `CRASH`, `fault address`, `# rip`, `sceSblAuthMgr`, `0x80020008`, `SIGSEGV/BUS/ILL/ABRT`, `ucontext` in the logs. A silent return to the launcher
  (too few `fps:` samples, or fps lines ending long before the log) is a failure.
- **Frame statistics** over the steady part: average and minimum fps, p1 low, frames over 20 ms and over 33 ms per 3 s window, worst frame; with the trace also
  driver milliseconds per frame and microseconds per draw.
- **Baseline comparison** (`tests/qa/baseline.json`, per mode): fps drop warn 5 percent and fail 10 percent (raised to 3x and 4.5x the measured A-versus-A2 noise),
  p1 15 and 30 percent, frames over 33 ms +1 and +3 per 3 s, over 20 ms +2 and +6, driver time +10 and +25 percent.
- **Screenshots** at fixed times per scenario: difference to the golden image with threshold 16, outside the learned mask (pixels that already differ between A and A2).
  Warn above 0.5 percent changed pixels or a region over 300 px, fail above 8 percent or a region over 6000 px. A scene that is unstable between A and A2 caps at WARN.
- **Glitch heuristics:** black frame, one colour over 97 percent, mostly saturated white, magenta fill (FAIL); with a golden also growing uniform or garbage tiles
  and lost HUD edge energy (WARN).
- The verdict is the worst finding. Reports go to `tests/qa/reports/<date>/report_<mode>_<time>.{md,json}` with heatmaps. A game without a baseline is a WARN.
  `--update-baseline` refuses a run that contains any FAIL.

Scenarios (`SCENARIOS` in the script, overridable per mode and game in a file `scenarios.json` in `tests/qa`, for example `{"full": {"jak3": {"shots": [{"name": "spawn", "t": 70}]}}}`):
quick = boot, title, play at 6/14/26 s (Jak 3 at 10/30/50 s); full Jak 1 and Jak 2 = 8, 20, 40 to 45, 60, 80 s (90 s run); Jak 3 = 10, 30, 60, 100, 130 s (190 s run).

## Files

| Path | Content | In git |
|---|---|---|
| `tests/qa/baseline.json` | numbers of the quick mode for Jak 2 and Jak 3 from the maintainer's console | yes |
| golden folder next to the baseline (`golden`) | golden screenshots and noise masks | no: they are frames of the games |
| `tests/qa/runs/`, `tests/qa/reports/` | collected runs and reports | no |

The baseline is a starting point: your console, firmware and scenes differ. Run `tools/ps5 qa --full --update-baseline` once to record your own, and the golden
screenshots, before relying on the comparison. There is no baseline for Jak 1 or for full mode yet.

## Tests

`python tests/run_all.py -k qa` runs the unit tests (`tests/test_qa_pipeline.py`) on fake logs and synthetic images: log statistics, silent return, crash patterns,
trace parsing, glitch checks, mask learning, and the whole cycle update-baseline, PASS, regression FAIL, missing baseline WARN, crashed baseline refused.

## Limits

- Thresholds are defaults; tune them with `--tol` after measuring your own A-versus-A2 noise.
- Shots at wall-clock times can land in another game state (cutscenes) from run to run; that is detected only when the baseline pair already differed.
- Crash detection relies on the UDP `CRASH` lines and the tail of `ps5.log`; the kernel log is not fetched automatically.
