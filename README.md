# OpenGOAL-PS5

Play **Jak and Daxter** 1, 2 and 3 natively on a jailbroken PlayStation 5. A port of the [OpenGOAL](https://github.com/open-goal/jak-project)
engine with a controller-driven launcher, on-console game import and a patched OpenGL-to-AGC graphics driver. No emulation.

[Deutsch](README.de.md) | [Install](docs/INSTALL.md) | [User guide](docs/USER_GUIDE.md) | [Docs index](docs/README.md)

> **No game files are included.** You need your own legally owned discs and import them from `.iso` images. This project does not
> support piracy.

<!-- screenshots: add docs/img/launcher.png, docs/img/jak2.png, docs/img/jak3.png -->
| Launcher | Jak 2 | Jak 3 |
|---|---|---|
| *(screenshot placeholder)* | *(screenshot placeholder)* | *(screenshot placeholder)* |

## Status (v0.1.0, early release)

Measured at 1080p, vsync 60 Hz, with draw merging and async GPU submit on (details: [`docs/PERF_JOURNAL.md`](docs/PERF_JOURNAL.md) section 10).

| Game | Playable | Frame rate | Notes |
|---|---|---|---|
| Jak and Daxter: The Precursor Legacy | boots and plays | 58 to 60 fps (intro, measured before the latest driver work, not re-measured) | import re-test pending |
| Jak II | playable | about 50 to 58 fps in the city (32 fps without merging and async submit) | some visual glitches remain |
| Jak 3 | playable | 59 to 60 fps in gameplay (43 fps without them), about 3 frames per 3 s over 20 ms | some visual glitches remain |

Known issues: visual glitches in places, occasional frame-time spikes, 4K output is much slower than 1080p on the GPU side. FSR upscaling
and dynamic resolution are experimental and have not been verified on a console yet ([`docs/FSR.md`](docs/FSR.md)).

## Requirements

- A jailbroken PS5 on **firmware 13.60** (the only version tested), with the ELF loader (port 9021), kstuff, an FTP service (port 2121) and
  ShadowMountPlus running. Setup order: [`docs/INSTALL.md`](docs/INSTALL.md).
- A PC on the same network with Python 3 for the one-time install.
- Your own copies of the games as unmodified `.iso` dumps.

## Install

1. Download the release zip and unzip it.
2. Run `install.bat` (Windows) or `sh install.sh` (Linux/macOS); enter the PS5 address or press Enter to search ([`release_template/install.py`](release_template/install.py)).
3. Start **OpenGOAL-PS5** on the console and add your games, either fast from the PC (paste the one-liner from [`docs/ONE_LINERS.md`](docs/ONE_LINERS.md) into PowerShell or Terminal, pick your `.iso` files) or through the QR-code web page on the console (slower).

Details and options: [`docs/INSTALL.md`](docs/INSTALL.md).

## Features

- Controller launcher for Jak 1/2/3, English and German
- On-console ISO import through a web page on port 8080 (checks the image, converts and compiles the game on the PS5)
- Draw merging and asynchronous GPU submit (about +10 fps in Jak 2, Jak 3 reaches vsync)
- Experimental: FSR 1.0 upscaling with dynamic resolution, lazy mipmaps
- Upstream sync tooling and an automated QA pipeline to follow new OpenGOAL versions ([`docs/UPSTREAM_SYNC.md`](docs/UPSTREAM_SYNC.md), [`docs/QA_PIPELINE.md`](docs/QA_PIPELINE.md))

## FAQ

**Which firmware works?** 13.60 is the only one tested. Others are unknown.
**Can I use my disc directly?** No. Create an `.iso` image of your own disc first; `.bin/.cue` must be converted.
**Does it write to my console permanently?** It installs one app folder under `/data/homebrew` and data under `/data/opengoal`. It never changes kernel flags or system settings.
**Why does the game ask for kstuff first, not OnionHEN?** With OnionHEN's built-in kstuff the app is refused (error `0x80020008`). Load OnionHEN only after the app is running.
**Can I get 60 fps everywhere?** Jak 3 is at the limit; Jak 2 city is about 50 to 58. Work continues, see [`docs/PLAN_60FPS.md`](docs/PLAN_60FPS.md).

## Troubleshooting

| Symptom | Try |
|---|---|
| Installer: "[MISSING] ELF loader / FTP" | start the exploit / `ftpsrv-ps5.elf`, run the installer again |
| App refused at start (`0x80020008`) | OnionHEN was loaded first; restart the jailbreak chain without it |
| Black screen or crash in game | turn off draw merging or async submit in the launcher settings, restart the app |
| Import stops | keep the console awake, check the free disk space, see `docs/ONBOARDING_WEB.md` |
| Everything silent after rest mode | re-run the exploit and loader; ports 2121/9021 may survive, the app may not |

More: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

## Building and contributing

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md). Security issues: [`SECURITY.md`](SECURITY.md).

## Legal

OpenGOAL-PS5 is an independent fan project. It is **not affiliated with or endorsed by** Sony Interactive Entertainment, Naughty Dog or the
OpenGOAL team. "PlayStation", "PS5", "Jak and Daxter" and related names are trademarks of their owners and are used only to describe
compatibility. The repository contains no game data, firmware, keys or console dumps. Use it only with games you own and on a console you own.

## Credits

[OpenGOAL / jak-project](https://github.com/open-goal/jak-project) (ISC), [ps5-opengl](https://github.com/blackbearreloaded/ps5-opengl) and
[ps5-native-app-boilerplate](https://github.com/blackbearreloaded/ps5-native-app-boilerplate) (GPL-3.0-or-later), [Mesa](https://www.mesa3d.org),
[ps5-payload-dev](https://github.com/ps5-payload-dev) (SDK, ftpsrv, shsrv), kstuff, ShadowMountPlus, etaHEN, FFmpeg (ATRAC9 tables),
Noto Sans JP (OFL). Full list: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## License

GPL-3.0-or-later, see [`LICENSE`](LICENSE).
