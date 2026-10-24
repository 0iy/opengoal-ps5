# OpenGOAL-PS5 (Deutsch)

**Jak and Daxter** 1, 2 und 3 nativ auf einer gejailbreakten PlayStation 5. Port der [OpenGOAL](https://github.com/open-goal/jak-project)-Engine
mit Controller-Launcher, Spielimport direkt auf der Konsole und angepasstem OpenGL-AGC-Treiber. Keine Emulation.

[English](README.md) | [Installation](docs/INSTALL.md) | [Anleitung](docs/USER_GUIDE.md) | [Dokumentation](docs/README.md)

Keine Spieledateien enthalten. Du brauchst deine eigenen, legal erworbenen Discs als `.iso`-Abbild. Piraterie wird nicht unterstuetzt.

<p align="center">
<img src="docs/img/launcher.png" width="49%" alt="Launcher"> <img src="docs/img/settings.png" width="49%" alt="Einstellungen">
<img src="docs/img/onboarding.png" width="49%" alt="Import-Seite"> <img src="docs/img/jak1.png" width="49%" alt="Jak and Daxter">
<img src="docs/img/jak2.png" width="49%" alt="Jak II"> <img src="docs/img/jak3.png" width="49%" alt="Jak 3">
</p>

Der Screenshot der Import-Seite zeigt simulierte Werte (es lief kein Import); die anderen stammen von einer Konsole.

## Start

Du brauchst eine PS5 mit Firmware 13.60 (einzige getestete Version): ELF-Loader (9021), kstuff, FTP (2121) und ShadowMountPlus laufen. Dazu einen PC im selben Netzwerk mit Python 3
und deine Spiele als unveraenderte `.iso`-Abbilder.

1. `OpenGOAL-PS5.zip` vom [neuesten Release](https://github.com/0iy/opengoal-ps5/releases/latest) laden und entpacken.
2. App auf der Konsole installieren: `install.bat` (Windows) oder `sh install.sh --lang de` (Linux, macOS) starten, PS5-Adresse eingeben oder Enter fuer die Suche.
3. **OpenGOAL-PS5** auf der Konsole starten und die Spiele vom PC hinzufuegen: eine Zeile einfuegen, ein kleines Fenster oeffnet sich, `.iso`-Dateien hineinziehen:

**Windows** (PowerShell):

```powershell
irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex
```

**macOS und Linux** (Terminal):

```bash
curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash
```

Oder die in der App angezeigte Adresse (QR-Code) am Handy oder PC oeffnen und die `.iso`-Dateien dort senden (langsamer). Mehr: [`docs/INSTALL.md`](docs/INSTALL.md) (Abschnitt Deutsch).

## Stand (v0.1.0, frueher Release)

Gemessen bei 1080p, vsync 60 Hz, mit Draw-Zusammenfassung und asynchronem GPU-Senden ([`docs/PERFORMANCE.md`](docs/PERFORMANCE.md)).

| Spiel | Zustand | Bildrate |
|---|---|---|
| Jak 1 | startet und laeuft | 58 bis 60 fps im Intro (vor der letzten Treiberarbeit gemessen) |
| Jak 2 | spielbar, einzelne Grafikfehler | etwa 50 bis 58 fps in der Stadt (32 fps ohne) |
| Jak 3 | spielbar, einzelne Grafikfehler | 59 bis 60 fps im Spiel (43 fps ohne) |

Bekannt: einzelne Grafikfehler, gelegentliche Ruckler. FSR-Hochskalierung ist experimentell ([`docs/FSR.md`](docs/FSR.md)).

## Entwicklung

Aufbau und Build: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md), Beitraege: [`CONTRIBUTING.md`](CONTRIBUTING.md), Tests: `python tests/run_all.py`.

## Rechtliches

Unabhaengiges Fanprojekt, **nicht verbunden mit** Sony Interactive Entertainment, Naughty Dog oder dem OpenGOAL-Team. Marken gehoeren ihren
Inhabern. Das Repository enthaelt keine Spieldaten, Firmware, Schluessel oder Konsolen-Dumps. Nur mit eigenen Spielen und eigener Konsole nutzen.

Lizenz: GPL-3.0-or-later ([`LICENSE`](LICENSE)). Drittkomponenten: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
