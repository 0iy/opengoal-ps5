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

Games are added from a PC (Windows, macOS or Linux) in the same network.

1. The launcher shows a QR code and an address (`http://<PS5 address>:8080`). Open the address in a browser on the PC.
2. Copy the line shown there for your system into PowerShell (Windows) or the Terminal (macOS, Linux) and press Enter.
3. In the window that opens, choose your `.iso` files (unmodified images of Jak 1, 2 or 3) and press **Start**. The PC builds each game and sends it
   to the PS5; Jak 3 takes about a minute.
4. The game becomes playable in the launcher. **Settings > Add games** shows the address again.

More detail: [`PC_IMPORT.md`](PC_IMPORT.md), the status page: [`ONBOARDING_WEB.md`](ONBOARDING_WEB.md).

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
| Setup waits for the ELF loader | start the exploit on the PS5; it continues by itself, or run `python ps5_setup.py` again (safe to repeat) |
| Import rejected | read the reason shown on the page (wrong game, truncated image, not an ISO) |
| Crash or black screen in game | switch off Draw merging, Async GPU submit, Lazy mipmaps, Upscaling one by one; restart the app |
| Nothing works after rest mode | re-run the exploit and the ELF loader; do not restart from scripts |
| Low frame rate in Jak 2 city | keep Draw merging and Async submit on; use 1080p |

Never write kernel flags: the flag value `0xffff` on 13.60 is normal. Report problems with the log and your firmware version (see
[`CONTRIBUTING.md`](../CONTRIBUTING.md)).
