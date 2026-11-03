# Status page of the app

Served by the app on port 8080 (`http://<PS5 address>:8080`, also as a QR code in the launcher under **Settings > Add games**).
Files: `app/shim/webpage.cpp` (page), `app/shim/webserver.cpp` (HTTP, SSE, PC install stream), `include/ps5import.h` (C API for the launcher).
No external requests, no dependencies, no images (game cards are CSS gradients with a numeral). Language follows the browser (de/en), toggle top right.

Games are installed from the PC only ([`PC_IMPORT.md`](PC_IMPORT.md)). Building a game on the console needs more memory than the app has
(Jak 3: 5.6 GB measured, the app heap is 1 GB), so the ISO upload and console import of 0.3.1 and earlier were removed in 0.3.3.

## What the page shows

- The one-liners for PowerShell (Windows) and the Terminal (macOS, Linux) with a Copy button. The page is plain http on the LAN, where
  `navigator.clipboard` is not available; the button selects the text and uses `document.execCommand("copy")`.
- One card per game: installed or not, region and serial of the installed disc, and during a PC import: percent, speed, elapsed time and time left.
  A finished or failed install can be dismissed (OK).
- A summary bar when more than one game installs in this session.

## API

```
GET  /api/status   {"version":3,"ip":"...","busy":false,"games":{"jak1":{"installed":true,"phase":"importing","stage":"install","percent":37,
                    "stage_percent":37,"bytes":...,"total":...,"speed":...,"eta":30,"elapsed":20,"idle":0,"serial":"SCUS-97124","region":"NTSC-U",
                    "reason":""},...},"overall":{"games":1,"percent":37,"eta":30}}
GET  /api/events   the same JSON as server-sent events, 4 per second
POST /api/cancel?game=jak1   stops a running install (the PC sees the connection close) or dismisses a done/failed card
GET  /api/info     install API version, app version, data format per installed game, folders the app cannot write
GET  /api/log      tail of the app log (?kb=N)
PUT  /api/install  the PC import stream, see PC_IMPORT.md
```

`phase` is `idle`, `importing`, `done` or `failed`; `reason` is one of `io no_space bad_contents cancelled net`. The launcher reads the same state
through `ps5_game_status()` and shows "Installing 37%".

## Tests

`node tests/test_onboarding_web.js` runs the page script against a stubbed DOM and a mock of the API. `tests/host/webserver_host.sh` builds
`webserver.cpp` on Linux and checks the endpoints (the removed upload endpoints answer 404). `tests/host/install_host.sh` drives the install
stream with the real `pc_import.py` code.
