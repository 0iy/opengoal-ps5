# OpenGOAL-PS5 (Deutsch)

**Jak and Daxter** 1, 2 und 3 nativ auf einer gejailbreakten PlayStation 5. Port der [OpenGOAL](https://github.com/open-goal/jak-project)-Engine
mit Controller-Launcher, Spielimport direkt auf der Konsole und angepasstem OpenGL-AGC-Treiber. Keine Emulation.

> **Keine Spieledateien enthalten.** Du brauchst deine eigenen, legal erworbenen Discs als `.iso`-Abbild. Piraterie wird nicht unterstuetzt.

## Stand (v0.1.0, frueher Release)

| Spiel | Bildrate (1080p, mit Draw-Zusammenfassung und asynchronem GPU-Senden) |
|---|---|
| Jak 1 | 58 bis 60 fps (Intro, aelterer Messwert) |
| Jak 2 | etwa 50 bis 58 fps in der Stadt (32 fps ohne) |
| Jak 3 | 59 bis 60 fps im Spiel (43 fps ohne) |

Bekannt: einzelne Grafikfehler, gelegentliche Ruckler. FSR-Hochskalierung ist experimentell. Details: [`docs/PERF_JOURNAL.md`](docs/PERF_JOURNAL.md).

## Voraussetzungen

- PS5 mit Firmware **13.60** (einzige getestete Version): ELF-Loader (9021), kstuff, FTP (2121), ShadowMountPlus
- PC im selben Netzwerk mit Python 3
- eigene Spiele als unveraenderte `.iso`-Abbilder

## Installation

1. Release-Zip entpacken.
2. `install.bat` (Windows) oder `sh install.sh --lang de` (Linux/macOS) starten, PS5-Adresse eingeben oder Enter fuer die Suche.
3. **OpenGOAL-PS5** auf der Konsole starten, die angezeigte Adresse (QR-Code) am Handy oder PC oeffnen und die `.iso`-Dateien senden.

Mehr: [`docs/INSTALL.md`](docs/INSTALL.md) (Abschnitt Deutsch), [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

## Rechtliches

Unabhaengiges Fanprojekt, **nicht verbunden mit** Sony Interactive Entertainment, Naughty Dog oder dem OpenGOAL-Team. Marken gehoeren ihren
Inhabern. Das Repository enthaelt keine Spieldaten, Firmware, Schluessel oder Konsolen-Dumps. Nur mit eigenen Spielen und eigener Konsole nutzen.

Lizenz: GPL-3.0-or-later ([`LICENSE`](LICENSE)). Drittkomponenten: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
