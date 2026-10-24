<p align="center">
  <img src="docs/img/banner.png" alt="OpenGOAL-PS5: Jak and Daxter 1, 2 und 3 auf der PlayStation 5" width="100%">
</p>

<p align="center">
  <a href="https://github.com/0iy/opengoal-ps5/actions/workflows/tests.yml"><img src="https://github.com/0iy/opengoal-ps5/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <img src="https://img.shields.io/badge/release-v0.1.0-f97316" alt="Release v0.1.0">
  <img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0">
  <img src="https://img.shields.io/badge/PS5%20firmware-13.60-1f6feb" alt="Firmware 13.60">
  <img src="https://img.shields.io/badge/status-experimentell-d97706" alt="Experimentell">
</p>

<p align="center">
  <a href="#start">Start</a> ·
  <a href="#stand">Stand</a> ·
  <a href="#mithelfen-und-fehler-melden">Fehler melden</a> ·
  <a href="docs/INSTALL.md">Installation</a> ·
  <a href="docs/README.md">Doku</a> ·
  <a href="README.md">English</a>
</p>

**Jak and Daxter** 1, 2 und 3 nativ auf einer gejailbreakten PlayStation 5. Port der [OpenGOAL](https://github.com/open-goal/jak-project)-Engine mit Controller-Launcher,
schnellem Spielimport vom PC und einem angepassten OpenGL-zu-AGC-Grafiktreiber. Keine Emulation. **Keine Spieldateien enthalten**: du brauchst deine eigenen, legal erworbenen Discs als `.iso`.

> [!WARNING]
> **Experimentell, in der Testphase.** Neue Software, die auf deiner Konsole instabil sein kann; getestet auf genau einer Konsole (CFI-2016, Firmware 13.60). Rechne mit Fehlern und Grafikfehlern.
> **Tester, Feedback, Issues und Pull Requests sind sehr willkommen.** Unabhaengiges Fanprojekt, nicht verbunden mit Sony, Naughty Dog oder dem OpenGOAL-Team:
> Fehler dieses Ports bitte [hier](https://github.com/0iy/opengoal-ps5/issues/new/choose) melden, nicht bei OpenGOAL.

## Start

**Du brauchst:** eine PS5 mit Firmware 13.60 und einem Jailbreak, der den ELF-Loader auf Port 9021 startet, einen PC im selben Netz (Windows, macOS oder Linux) mit Python 3 und deine Spiele als `.iso`-Abbilder.

1. **Jailbreak auf der PS5 starten**, bis der ELF-Loader lauscht (Port 9021). OnionHEN nicht vor dem Start der App laden.
2. **Eine Zeile am PC einfuegen.** Sie findet die PS5, laedt was fehlt, installiert und startet die App und oeffnet das Import-Fenster. `.iso`-Dateien hineinziehen.
   Etwa eine Minute spaeter ist das Spiel spielbar.

**Windows** (PowerShell):

```powershell
irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex
```

**macOS und Linux** (Terminal):

```bash
curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash
```

Jederzeit wiederholbar: es erledigt nur, was noch fehlt. Es startet die Konsole nie neu, schreibt keine Kernel-Flags und enthaelt kstuff-lite nicht (kommt vom Release des Autors, nur nach Rueckfrage).
Lieber erst lesen? `OpenGOAL-PS5.zip` vom [neuesten Release](https://github.com/0iy/opengoal-ps5/releases/latest) laden, entpacken und `python ps5_setup.py` starten (`--debug` schreibt ein Log fuer Fehlerberichte).
Mehr und der manuelle Weg: [`docs/INSTALL.md`](docs/INSTALL.md) (Abschnitt Deutsch).

<p align="center">
<img src="docs/img/jak2.png" width="100%" alt="Jak II auf einer PS5">
</p>

<p align="center">
<img src="docs/img/launcher.png" width="32%" alt="Launcher"> <img src="docs/img/settings.png" width="32%" alt="Einstellungen"> <img src="docs/img/jak3.png" width="32%" alt="Jak 3">
</p>

## Stand

v0.1.0, frueher Release. Gemessen bei 1080p, vsync 60 Hz ([`docs/PERFORMANCE.md`](docs/PERFORMANCE.md)).

| Spiel | Zustand | Bildrate |
|---|---|---|
| Jak 1 | 🟢 spielbar | 58 bis 60 fps (Titel und Intro, PAL-Disc vom PC importiert) |
| Jak 2 | 🟡 spielbar, einzelne Grafikfehler | etwa 50 bis 58 fps in der Stadt |
| Jak 3 | 🟡 spielbar, einzelne Grafikfehler | 59 bis 60 fps im Spiel |

Bekannt: das Ein-Befehl-Setup ist neu und nur auf einer Konsole geprueft; einzelne Grafikfehler; gelegentliche Ruckler; 4K ist deutlich langsamer als 1080p. FSR-Hochskalierung ist experimentell ([`docs/FSR.md`](docs/FSR.md)).

## Mithelfen und Fehler melden

Echtes Feedback ist gerade das Wichtigste, auch wenn alles lief.

- **Ausprobiert?** [Testbericht](https://github.com/0iy/opengoal-ps5/issues/new?template=test-report.yml) mit Konsolenmodell, Firmware und was ging. `ps5_setup_debug.log` anhaengen (Tokens sind maskiert; Privates entfernen).
- **Fehler gefunden?** [Fehlerbericht](https://github.com/0iy/opengoal-ps5/issues/new?template=bug.yml).
- **Fragen oder Ideen?** [Discussions](https://github.com/0iy/opengoal-ps5/discussions).
- **Mitprogrammieren?** Pull Requests sind willkommen: [`CONTRIBUTING.md`](CONTRIBUTING.md). Doku, Setup-Skript und Tests brauchen keine Konsole (`python tests/run_all.py`); Engine, Treiber und App brauchen eine PS5 ([`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)).

Aufbau, Ordner und Architektur: [`docs/README.md`](docs/README.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Sicherheitsluecken: [`SECURITY.md`](SECURITY.md).

## Rechtliches

Unabhaengiges Fanprojekt, **nicht verbunden mit** Sony Interactive Entertainment, Naughty Dog oder dem OpenGOAL-Team. Marken gehoeren ihren Inhabern. Das Repository enthaelt keine Spieldaten,
Firmware, Schluessel oder Konsolen-Dumps. Nur mit eigenen Spielen und eigener Konsole nutzen.

Lizenz: GPL-3.0-or-later ([`LICENSE`](LICENSE)). Drittkomponenten: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
