# Contributing

Bug reports, test reports and patches are welcome. This is an experimental hobby project that has been tested on one console model and firmware (13.60), so reports from other setups are especially useful, including "it worked".

## Test reports

Open a test report (issue template) with your console model, firmware, what you did and what happened. Run `python ps5_setup.py --debug` and attach `ps5_setup_debug.log`
(tokens are masked; remove your addresses and account names first).

## Reporting a bug

Open an issue with: firmware, game and scene, launcher settings, what you expected, and the last lines of `/data/opengoal/log/ps5.log`.
Remove your console address and account names from logs before posting. Do not attach game files, ISOs, dumps or keys.

## Pull requests

- Keep changes small and say what you measured (fps, tracer numbers, screenshots) and on which firmware.
- Engine changes: an idempotent patch script in `engine/` with a marker and asserted replacements (`assert s.count(old) == 1`), added to `engine/ports/manifest.json`.
  Driver changes: edit the SDK sources and regenerate `driver/ps5-opengl.patch` (see `driver/README.md`).
  Either way the new behaviour is switchable at runtime by a flag file and the default is unchanged.
- Run `python tests/run_all.py` before you push; it needs no console and must end without FAIL.
- Commit subjects are short sentences without prefixes.
- No game data, copyrighted media, firmware, keys, console dumps, personal addresses or tokens. Write `PS5_ADDRESS` instead of an address in docs and logs.
- New files need a licence compatible with GPL-3.0-or-later; list third-party code in `THIRD_PARTY_NOTICES.md`.
- No code that writes kernel flags, bypasses game protection or supports piracy.

Layout, `tools/ps5` commands and build: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
