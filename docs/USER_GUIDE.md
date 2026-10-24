# User guide

## Launcher controls

| Button | Action |
|---|---|
| Left / Right or L1 / R1 | choose game |
| Cross | play / select |
| Triangle or Options | settings |
| Square | controls help |
| Circle | back |

In game the original Jak controls apply. One game runs per start: choosing another game restarts the app.

## Adding games (first start)

1. The launcher shows a QR code and an address (`http://<PS5 address>:8080`). Open it on a phone or PC in the same network.
2. Drop your `.iso` files (one or several). The page checks each file before upload: it must be an unmodified ISO of Jak 1, 2 or 3;
   `.bin/.cue` and truncated copies are rejected with a reason.
3. The console converts and compiles each game. Keep it on; this takes a few minutes per game. Closing the browser does not stop it.
4. The game becomes playable in the launcher. Use **Settings > Add games** to open the page again.

More detail: [`ONBOARDING_WEB.md`](ONBOARDING_WEB.md).

## Settings

| Setting | Meaning |
|---|---|
| Output resolution | 1080p, 1440p or 4K. The game renders at this size; 4K needs far more GPU time. Applies at the next start |
| Draw merging | fewer GPU draw calls (about +10 fps in Jak 2). Turn off if geometry looks broken |
| Async GPU submit | prepares draws on worker threads. Turn off to look for glitches |
| Lazy mipmaps (experimental) | skips unused mipmap work (about +2 fps in Jak 2); distant surfaces may flicker |
| Upscaling (FSR) | Off, Quality 83 %, Balanced 67 %, Performance 50 %, Auto (lowers size when fps drops). Experimental |
| Sharpness | FSR sharpening, 0 = off |
| Language | English or Deutsch |

Settings are stored in `/data/opengoal/config/ps5.cfg`. The output is locked to 60 Hz.

## Files on the console

| Path | Content |
|---|---|
| `/data/homebrew/LAPY77001` | the app |
| `/data/opengoal/<game>/data` | converted game data |
| `/data/opengoal/config` | settings and saves |
| `/data/opengoal/log/ps5.log` | log (can grow large) |

## Troubleshooting

| Problem | Fix |
|---|---|
| App refused at launch (`0x80020008`) | OnionHEN was loaded before the app; start without it |
| Installer reports missing loader or FTP | start the exploit, then `ftpsrv-ps5.elf` after kstuff-lite; run the installer again (safe to repeat) |
| Import rejected | read the reason shown on the page (wrong game, truncated image, not an ISO) |
| Crash or black screen in game | switch off Draw merging, Async GPU submit, Lazy mipmaps, Upscaling one by one; restart the app |
| Nothing works after rest mode | re-run the exploit and the ELF loader; do not restart from scripts |
| Low frame rate in Jak 2 city | keep Draw merging and Async submit on; use 1080p |

Never write kernel flags: the flag value `0xffff` on 13.60 is normal. Report problems with the log and your firmware version (see
[`CONTRIBUTING.md`](../CONTRIBUTING.md)).
