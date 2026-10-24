# Contributing

Bug reports and patches are welcome. This is a hobby project for one console model and firmware (13.60).

## Reporting a bug

Open an issue with: firmware, game and scene, launcher settings, what you expected, and the last lines of `/data/opengoal/log/ps5.log`.
Remove your console address and account names from logs before posting. Do not attach game files, ISOs, dumps or keys.

## Pull requests

- Keep changes small and say what you measured (fps, tracer numbers, screenshots) and on which firmware.
- Driver and engine changes: idempotent patch script with a marker and asserted replacements (style of `drv_patch47.py`), switchable at runtime
  by a flag file, default unchanged.
- Run what applies: `python -m unittest tests/test_qa_pipeline.py`, `node tests_onboarding_web.js`, `python3 sync_upstream.py preflight`.
- No game data, copyrighted media, firmware, keys, console dumps, personal addresses or tokens. Use `192.168.x.y` in docs.
- New files need a licence compatible with GPL-3.0-or-later; list third-party code in `THIRD_PARTY_NOTICES.md`.
- No code that writes kernel flags, bypasses game protection or supports piracy.

Layout and build: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
