# Documentation map

## For users

| Doc | Content |
|---|---|
| [`INSTALL.md`](INSTALL.md) | prepare the console, run the installer, options (English and German) |
| [`ONE_LINERS.md`](ONE_LINERS.md) | import games from the PC with a one-liner and a small window (Windows, macOS, Linux) |
| [`USER_GUIDE.md`](USER_GUIDE.md) | launcher controls, adding games, settings explained, troubleshooting |
| [`ONBOARDING_WEB.md`](ONBOARDING_WEB.md) | how the ISO import page and its checks work |

## For developers

| Doc | Content |
|---|---|
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | repo layout, build loop, how the pieces fit |
| [`SETUP_NEW_MACHINE.md`](SETUP_NEW_MACHINE.md) | reproduce the WSL build tree, pinned third-party revisions |
| [`RUNBOOK.md`](RUNBOOK.md) | console boot order, build and measurement loops, logs, safety |
| [`UPSTREAM_SYNC.md`](UPSTREAM_SYNC.md) | port new OpenGOAL versions (`sync_upstream.py`, `ports/`) |
| [`QA_PIPELINE.md`](QA_PIPELINE.md) | automatic regression gate (`qa_pipeline.py`) |
| [`FSR.md`](FSR.md) | dynamic resolution and FSR 1.0 (experimental) |
| [`INGAME_SETTINGS.md`](INGAME_SETTINGS.md) | PS5 defaults for OpenGOAL's in-game menus |

## Performance work (history and measurements)

| Doc | Content |
|---|---|
| [`PERF_JOURNAL.md`](PERF_JOURNAL.md) | measured state, corrections, patch list, results (start here) |
| [`PERF_ANALYSIS.md`](PERF_ANALYSIS.md), [`PLAN_60FPS.md`](PLAN_60FPS.md) | root-cause analysis and the 60 fps plan |
| `agent_*.md` | design notes per topic: draw cost, merge, mip cost, multi-draw, present, spikes, sync debug |
| [`HANDOFF.md`](HANDOFF.md) | state snapshot for a new maintainer |

## Release

[`RELEASE_AUDIT.md`](RELEASE_AUDIT.md) (privacy and legal scan) and [`RELEASE_CLEANUP.md`](RELEASE_CLEANUP.md) (pending cleanup).
Top level: [`README`](../README.md), [`CHANGELOG`](../CHANGELOG.md), [`CONTRIBUTING`](../CONTRIBUTING.md), [`SECURITY`](../SECURITY.md),
[`THIRD_PARTY_NOTICES`](../THIRD_PARTY_NOTICES.md).
