<p align="center">
  <img src="docs/img/banner.png" alt="OpenGOAL-PS5: Jak and Daxter 1, 2 and 3 on PlayStation 5" width="100%">
</p>

<p align="center">
  <a href="https://github.com/0iy/opengoal-ps5/actions/workflows/tests.yml"><img src="https://github.com/0iy/opengoal-ps5/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/0iy/opengoal-ps5/releases/latest"><img src="https://img.shields.io/github/v/release/0iy/opengoal-ps5?color=f97316" alt="latest release"></a>
  <img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0">
  <img src="https://img.shields.io/badge/PS5%20firmware-13.60-1f6feb" alt="firmware 13.60">
  <img src="https://img.shields.io/badge/status-experimental-d97706" alt="experimental">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#status">Status</a> ·
  <a href="#help-test-and-report-bugs">Report a bug</a> ·
  <a href="docs/INSTALL.md">Install guide</a> ·
  <a href="docs/README.md">Docs</a> ·
  <a href="README.de.md">Deutsch</a>
</p>

Play **Jak and Daxter** 1, 2 and 3 natively on a jailbroken PlayStation 5. A port of the [OpenGOAL](https://github.com/open-goal/jak-project) engine with a controller
launcher, fast game import from your PC and a patched OpenGL-to-AGC graphics driver. No emulation. **No game files included**: bring your own legally owned discs as `.iso`.

> [!WARNING]
> **Experimental, in testing.** New software that can be unstable on your console; tested on one console only (CFI-2016, firmware 13.60). Expect bugs and glitches.
> **Testers, feedback, issues and pull requests are very welcome.** Independent fan project, not affiliated with Sony, Naughty Dog or the OpenGOAL team:
> report bugs of this port [here](https://github.com/0iy/opengoal-ps5/issues/new/choose), not to OpenGOAL.

## Quick start

**You need:** a PS5 on firmware 13.60 with a jailbreak that runs the ELF loader on port 9021, a PC on the same network (Windows, macOS or Linux) with Python 3, and your own games as `.iso` images.

1. **Start the jailbreak on the PS5** until the ELF loader listens (port 9021). Do not load OnionHEN before the app runs.
2. **Paste one line on the PC.** It finds the PS5, loads what is missing, installs and starts the app, then opens the import window. Choose or drop your `.iso` files, press **Start**, and launch a game from the PS5 home screen when the import finishes.

**Windows** (PowerShell):

```powershell
irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex
```

**macOS and Linux** (Terminal):

```bash
curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash
```

These commands run a bootstrap script from the latest release. To inspect it before running, use the two-step method in the [install guide](docs/INSTALL.md#trust-model).

**Updating is the same line.** Run it again: it downloads the latest release, compares it with the version on the console and updates only if the console is older
(and tells you "up to date" otherwise). Your games and saves stay. The import window shows "Update available" when a newer release exists. If a release ever changes the
game format, the setup lists the games to import again; they keep working until you do.

Safe to run again: it only does what is still needed. It never restarts the console or writes kernel flags, and it never bundles kstuff-lite (fetched from its author's release, only after asking you).
Prefer to read first? Download `OpenGOAL-PS5.zip` from the [latest release](https://github.com/0iy/opengoal-ps5/releases/latest), unzip it and run `python ps5_setup.py` (add `--debug` for a log you can attach to a report).
Details and the manual route: [`docs/INSTALL.md`](docs/INSTALL.md).

<p align="center">
<img src="docs/img/jak2.png" width="100%" alt="Jak II running on a PS5">
</p>

<p align="center">
<img src="docs/img/launcher.png" width="32%" alt="Launcher"> <img src="docs/img/settings.png" width="32%" alt="Settings"> <img src="docs/img/jak3.png" width="32%" alt="Jak 3">
</p>

## Status

Early release; see the badge above for the latest version. Measured at 1080p, vsync 60 Hz ([`docs/PERFORMANCE.md`](docs/PERFORMANCE.md)).

| Game | State | Frame rate |
|---|---|---|
| Jak and Daxter: The Precursor Legacy | 🟢 playable | 58 to 60 fps (title and intro, PAL disc imported from the PC) |
| Jak II | 🟡 playable, some visual glitches | about 50 to 58 fps in the city |
| Jak 3 | 🟡 playable, some visual glitches | 59 to 60 fps in gameplay |

Known issues: the one-command setup is new and verified on one console only; visual glitches in places; occasional frame-time spikes; 4K is much slower than 1080p. FSR upscaling is experimental ([`docs/FSR.md`](docs/FSR.md)).

## Help test and report bugs

Real feedback is the most useful thing right now, also when everything worked.

- **Tried it?** Open a [test report](https://github.com/0iy/opengoal-ps5/issues/new?template=test-report.yml): console model, firmware, what worked. Attach `ps5_setup_debug.log` (tokens are masked; remove anything private).
- **Found a bug?** Open a [bug report](https://github.com/0iy/opengoal-ps5/issues/new?template=bug.yml).
- **Questions or ideas?** Use [Discussions](https://github.com/0iy/opengoal-ps5/discussions).
- **Want to code?** Pull requests are welcome: [`CONTRIBUTING.md`](CONTRIBUTING.md). Docs, setup script and tests need no console (`python tests/run_all.py`); engine, driver and app changes need a PS5 ([`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)).

<details>
<summary><b>FAQ</b></summary>

- **Which firmware works?** 13.60. Others are unknown.
- **Can I use my disc directly?** No. Make an `.iso` image of your own disc first; `.bin/.cue` must be converted.
- **Does it write to my console permanently?** It installs one app folder under `/data/homebrew` and data under `/data/opengoal`. It never changes kernel flags or system settings.
- **Why must kstuff be loaded before OnionHEN?** With OnionHEN's built-in kstuff the app is refused (error `0x80020008`). Load OnionHEN only after the app is running.
- **Can I get 60 fps everywhere?** Jak 3 is at the limit; Jak 2 in the city is about 50 to 58. The remaining cost is CPU time per draw in the driver.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

| Symptom | Try |
|---|---|
| Setup waits at "ELF loader" | start the exploit on the PS5; the setup continues by itself (or run it again) |
| Setup says a suspended copy blocks the start | close the game on the PS5 (home screen, Options, Close Game); if it stays, restart the jailbreak chain and run the setup again |
| App refused at start (`0x80020008`) | OnionHEN was loaded first; restart the jailbreak chain without it |
| Black screen or crash in game | turn off draw merging or async submit in the launcher settings, restart the app |
| Import stops | keep the console awake, check the free disk space, see [`docs/ONBOARDING_WEB.md`](docs/ONBOARDING_WEB.md) |
| Everything silent after rest mode | run the exploit and the loader again; ports 2121 and 9021 may survive, the app may not |

More: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

</details>

<details>
<summary><b>How it works and what is in this repository</b></summary>

The PC extracts, decompiles and packs the game and streams the finished result to the console. On the PS5 one app holds the controller launcher and web server, the patched OpenGOAL engine
with a small SDL/GL shim, and the driver that translates OpenGL (Mesa) to AGC. Draw merging and asynchronous GPU submit give about +10 fps in Jak 2; Jak 3 reaches vsync.

| Folder | Content |
|---|---|
| `app/` | the PS5 app: shim (SDL replacement, launcher, importer, web server, GL fixes) and build scripts |
| `driver/` | patched ps5-opengl graphics driver |
| `engine/` | patches for the OpenGOAL engine, upstream sync tool, FSR shaders |
| `payloads/` | small console payloads (setup agent, kill and launch the app, rescan, keep awake) |
| `tools/` | the `ps5` command line: build, deploy, run, measure, QA, test |
| `installer/` | what the release contains: setup script, PC import engine and window, bootstrap scripts |
| `tests/`, `docs/`, `art/` | offline test suite, documentation, artwork |

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). All docs: [`docs/README.md`](docs/README.md). Security issues: [`SECURITY.md`](SECURITY.md).

</details>

## Legal

OpenGOAL-PS5 is an independent fan project. It is not affiliated with or endorsed by Sony Interactive Entertainment, Naughty Dog or the OpenGOAL team. "PlayStation", "PS5",
"Jak and Daxter" and related names are trademarks of their owners and are used only to describe compatibility. The repository contains no game data, firmware, keys or console dumps.
Use it only with games you own and on a console you own.

## Credits and license

[OpenGOAL / jak-project](https://github.com/open-goal/jak-project) (ISC), ps5-opengl (BlackBearReloaded; the original repository is gone, see [`driver/README.md`](driver/README.md)),
[ps5-native-app-boilerplate](https://github.com/drakmor/ps5-native-app-boilerplate), [Mesa](https://www.mesa3d.org), [ps5-payload-dev](https://github.com/ps5-payload-dev), kstuff,
ShadowMountPlus, etaHEN, FFmpeg (ATRAC9 tables), Noto Sans JP (OFL). Full list: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

GPL-3.0-or-later, see [`LICENSE`](LICENSE).
