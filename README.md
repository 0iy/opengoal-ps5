# OpenGOAL-PS5

Play Jak and Daxter 1, 2 and 3 natively on a jailbroken PlayStation 5. A port of the [OpenGOAL](https://github.com/open-goal/jak-project) engine with a
controller launcher, on-console game import and a patched OpenGL-to-AGC graphics driver. No emulation.

[Deutsch](README.de.md) | [Install](docs/INSTALL.md) | [User guide](docs/USER_GUIDE.md) | [Docs](docs/README.md)

No game files are included. You need your own legally owned discs, imported from `.iso` images. This project does not support piracy.

| Launcher | Settings | Onboarding page |
|---|---|---|
| ![Launcher](docs/img/launcher.png) | ![Settings](docs/img/settings.png) | ![Onboarding page](docs/img/onboarding.png) |

| Jak and Daxter | Jak II | Jak 3 |
|---|---|---|
| ![Jak 1](docs/img/jak1.png) | ![Jak 2](docs/img/jak2.png) | ![Jak 3](docs/img/jak3.png) |

The onboarding screenshot shows simulated values (no import was running); the others are from a console.

## Start

You need a PS5 on firmware 13.60 (the only version tested) with the ELF loader (9021), kstuff, an FTP service (2121) and ShadowMountPlus running, and a PC on the same network
with Python 3.

1. Download the release zip and unzip it.
2. Run `install.bat` (Windows) or `sh install.sh` (Linux, macOS), enter the PS5 address or press Enter to search.
3. Start OpenGOAL-PS5 on the console and add your games. Fast, from the PC:

```
irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex                  # Windows, PowerShell
curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash           # macOS, Linux
```

Or open the address and QR code the app shows on a phone or PC and upload the `.iso` files there (slower). Details: [`docs/INSTALL.md`](docs/INSTALL.md).

## Status (v0.1.0, early release)

Measured at 1080p, vsync 60 Hz, draw merging and async GPU submit on ([`docs/PERFORMANCE.md`](docs/PERFORMANCE.md)).

| Game | State | Frame rate |
|---|---|---|
| Jak and Daxter: The Precursor Legacy | boots and plays | 58 to 60 fps in the intro (measured before the latest driver work) |
| Jak II | playable, some visual glitches | about 50 to 58 fps in the city (32 fps without merging and async submit) |
| Jak 3 | playable, some visual glitches | 59 to 60 fps in gameplay (43 fps without), about 3 frames per 3 s over 20 ms |

Known issues: visual glitches in places, occasional frame-time spikes, 4K output is much slower than 1080p on the GPU side. FSR upscaling and dynamic resolution are experimental
([`docs/FSR.md`](docs/FSR.md)). Only firmware 13.60 is tested.

## Features

- Controller launcher for Jak 1, 2 and 3, English and German
- Game import on the console (web page on port 8080: checks the image, converts and compiles on the PS5) or from the PC (faster)
- Draw merging and asynchronous GPU submit: about +10 fps in Jak 2, Jak 3 reaches vsync
- Experimental: FSR 1.0 upscaling with dynamic resolution, lazy mipmaps
- Upstream sync tool and a QA pipeline to follow new OpenGOAL versions ([`docs/UPSTREAM_SYNC.md`](docs/UPSTREAM_SYNC.md), [`docs/QA.md`](docs/QA.md))

## FAQ

- **Which firmware works?** 13.60. Others are unknown.
- **Can I use my disc directly?** No. Make an `.iso` image of your own disc first; `.bin/.cue` must be converted.
- **Does it write to my console permanently?** It installs one app folder under `/data/homebrew` and data under `/data/opengoal`. It never changes kernel flags or system settings.
- **Why must kstuff be loaded before OnionHEN?** With OnionHEN's built-in kstuff the app is refused (error `0x80020008`). Load OnionHEN only after the app is running.
- **Can I get 60 fps everywhere?** Jak 3 is at the limit; Jak 2 in the city is about 50 to 58. The remaining cost is CPU time per draw in the driver.

## Troubleshooting

| Symptom | Try |
|---|---|
| Installer: "[MISSING] ELF loader" or "FTP" | start the exploit, or `ftpsrv-ps5.elf`, and run the installer again |
| App refused at start (`0x80020008`) | OnionHEN was loaded first; restart the jailbreak chain without it |
| Black screen or crash in game | turn off draw merging or async submit in the launcher settings, restart the app |
| Import stops | keep the console awake, check the free disk space, see [`docs/ONBOARDING_WEB.md`](docs/ONBOARDING_WEB.md) |
| Everything silent after rest mode | run the exploit and the loader again; ports 2121 and 9021 may survive, the app may not |

More: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

## Repository

| Folder | Content |
|---|---|
| `app/` | the PS5 app: shim (SDL replacement, launcher, importer, web server, GL fixes) and build scripts |
| `driver/` | patched ps5-opengl graphics driver, build scripts and run-time switches |
| `engine/` | patches for the OpenGOAL engine, upstream sync tool, FSR shaders |
| `payloads/` | small console payloads (kill and launch the app, rescan, keep awake) |
| `tools/` | the `ps5` command line: build, deploy, run, measure, QA, test |
| `installer/` | what the release contains: installer, PC import engine and window, bootstrap scripts |
| `tests/` | offline test suite (`python tests/run_all.py`) |
| `art/`, `docs/` | artwork, documentation |

Build and contribute: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md), [`CONTRIBUTING.md`](CONTRIBUTING.md). Security issues: [`SECURITY.md`](SECURITY.md).

## Legal

OpenGOAL-PS5 is an independent fan project. It is not affiliated with or endorsed by Sony Interactive Entertainment, Naughty Dog or the OpenGOAL team. "PlayStation", "PS5",
"Jak and Daxter" and related names are trademarks of their owners and are used only to describe compatibility. The repository contains no game data, firmware, keys or console dumps.
Use it only with games you own and on a console you own.

## Credits

[OpenGOAL / jak-project](https://github.com/open-goal/jak-project) (ISC), [ps5-opengl](https://github.com/blackbearreloaded/ps5-opengl) and
[ps5-native-app-boilerplate](https://github.com/blackbearreloaded/ps5-native-app-boilerplate) (GPL-3.0-or-later), [Mesa](https://www.mesa3d.org),
[ps5-payload-dev](https://github.com/ps5-payload-dev) (SDK, ftpsrv, shsrv), kstuff, ShadowMountPlus, etaHEN, FFmpeg (ATRAC9 tables), Noto Sans JP (OFL).
Full list: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## License

GPL-3.0-or-later, see [`LICENSE`](LICENSE).
