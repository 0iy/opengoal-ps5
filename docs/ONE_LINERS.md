# One-liners: import your games from the PC

Faster than the web page on the console: the PC unpacks, analyses and builds the game, then sends the result to the PS5.
Needs the app already installed and running on the console ([`INSTALL.md`](INSTALL.md)) and the PC on the same network.

> The addresses below contain a placeholder. Replace `<owner>/<repo>` with the real GitHub repository once the release exists.

| System | Paste into | One-liner |
|---|---|---|
| Windows | PowerShell | `irm https://github.com/<owner>/<repo>/releases/latest/download/bootstrap.ps1 \| iex` |
| macOS / Linux | Terminal | `curl -fsSL https://github.com/<owner>/<repo>/releases/latest/download/bootstrap.sh \| bash` |

A window opens: choose or drop your `.iso` files (Jak 1, 2, 3 are recognised by the disc serial), the PS5 is found automatically
(or type its IP, then **Test connection**), press **Start**. You see phase, percent, speed and time left per game; the end message is
"Ready: start the game on your PS5." German or English follows the system language.

## What runs

1. `bootstrap.ps1` / `bootstrap.sh` (about 30 lines, read them first) prints what it will do, then downloads `SHA256SUMS` and
   `OpenGOAL-PS5-gui.zip` from the same release, and stops if the SHA-256 of the zip does not match.
2. The zip goes to `~/.opengoal-ps5/app` (Windows: `%USERPROFILE%\.opengoal-ps5\app`). Contents: `gui/windows/OpenGOAL-PS5.ps1`,
   `gui/macos/OpenGOAL-PS5.command`, `gui/OpenGOAL-PS5-gui.py`, `pc_import.py`.
3. Windows starts the PowerShell window (WinForms, nothing to install). macOS/Linux start the Python window.
4. No admin rights or sudo, no system settings, no PATH changes. Settings: `~/.opengoal-ps5/config.json` (last PS5 IP). The import engine caches
   its tools in `~/.opengoal-ps5/tools`. Delete the folder to remove everything.
5. The GUI talks only to the PS5 (port 8080 for discovery, whatever `pc_import.py` uses for the transfer) and to the downloads the engine
   needs. It scans only your own /24 network for port 8080.

## Python

`pc_import.py` needs Python 3.
- macOS: `xcode-select --install` (free) or python.org. Without tkinter the program falls back to AppleScript dialogs
  (file chooser, notifications per phase, final dialog); without osascript or on a headless Linux to a text mode.
- Linux: `python3` (and `python3-tk` for the window).
- Windows: if Python 3 is not found the window offers (a) `winget install Python.Python.3.12 --scope user` or (b) a portable
  embeddable zip into `~\.opengoal-ps5\python`, no admin. (b) is checked against a pinned SHA-256; **the pin in
  `gui/windows/OpenGOAL-PS5.ps1` (`$PyEmbedSha256`) is still a placeholder, so (b) refuses to run until the maintainer fills it**:
  download `python-3.12.8-embed-amd64.zip`, verify it with the signature on python.org, put `Get-FileHash -Algorithm SHA256` into the script.

## Trust model (honest version)

- The one-liner runs a script fetched over HTTPS from GitHub. Nobody can verify it for you before it runs. If you do not want to trust
  that, use the two-step form: download `bootstrap.ps1` (or `.sh`), read it, then run it; or download `OpenGOAL-PS5.zip` and use
  `gui/` from there.
- The checksum protects against a damaged or half-uploaded download and against a mixed-up release. It does **not** protect against
  someone who controls the GitHub release: they can replace the zip and `SHA256SUMS` together. To pin harder, compare the hash of
  `OpenGOAL-PS5-gui.zip` with the one printed in the release notes or the README (published through a different channel).
- `irm | iex` / `curl | bash` hide what is executed from antivirus and from you. That is the price of a one-liner.
- The Windows window starts with `-ExecutionPolicy Bypass` for that one process only; the system policy is not changed.
- Your game images never leave your network.

## For maintainers

`make_release.sh` / `.ps1` build `release/OpenGOAL-PS5-gui.zip`, copy `bootstrap.*` and write `release/SHA256SUMS` (gui zip, both bootstrap
scripts, full bundle zip) via `gui/make_gui_zip.py`; upload those files as assets of the GitHub release (the `latest/download/<file>` URL
needs exactly these names). The bundle zip itself also contains `gui/`, `pc_import.py` (if present) and the bootstrap scripts.
Engine contract: `pc_import.py --game auto|jak1|jak2|jak3 --iso PATH --ps5 IP [--port N] [--tools-dir DIR] [--jobs N] --json-progress`,
one JSON object per line `{"phase","percent","overall","speed_bps","eta_s","message","game","serial"}`, exit 0 = ok.

Tests (no console is contacted): `python tests/gui/test_core.py`; the Windows window against the fake engine:
`python tests/gui/fake_ps5.py 18080`, then with `OGPS5_ENGINE=pc_import_fake.py OGPS5_PORT=18080 OGPS5_SCAN_PREFIX=127.0.0.`
run `& gui\windows\OpenGOAL-PS5.ps1 -Iso a.iso,b.iso -AutoStart -ScreenshotTo shot.png`. `tests/gui/make_fake_iso.py OUT SCUS_971.24` writes a tiny test image.
