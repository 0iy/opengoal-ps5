# Installing OpenGOAL-PS5

Deutsch: siehe unten.

## What you need

- A jailbroken PS5 (firmware 13.60) and a PC (Windows, Linux or macOS) on the same network.
- Python 3 on the PC (Windows: python.org, tick "Add to PATH"; Linux and macOS: usually installed). The import window on Windows can fetch a portable Python itself.
- Your own Jak games as unmodified `.iso` images. The release contains no game files.

## Get the console ready (in this order)

1. Exploit and ELF loader (port 9021). Nothing else yet.
2. `kstuff-lite` (send to 9021, wait about 20 s).
3. `ftpsrv-ps5.elf` (FTP, port 2121) and ShadowMountPlus. `shsrv` (port 2323) is optional.
4. Do not load OnionHEN before launching the app: the app is then refused (error `0x80020008`).
5. Do not restart the console and do not change kernel flags; the flag value `0xffff` is normal on 13.60.

## Install the app

1. Download the release zip from the [releases page](https://github.com/0iy/opengoal-ps5/releases/latest) and unzip it. Optional: check the files against `SHA256SUMS`
   (`sha256sum -c SHA256SUMS`, or `Get-FileHash` on Windows).
2. Windows: double-click `install.bat`. Linux and macOS: `sh install.sh`.
3. Enter the PS5 address (or press Enter to search the network). The installer:
   - checks that the loader (9021) and FTP (2121) answer, and says in plain words what is missing;
   - uploads the app to `/data/homebrew/LAPY77001` with progress, skipping files already there;
   - creates `/data/opengoal/config/ps5.cfg` (resolution, refresh, language) only if it does not exist;
   - verifies the size of every file on the console;
   - optionally sends payload ELFs you provide (`--payload file.elf`). OnionHEN is refused.
4. Start **OpenGOAL-PS5** from the PS5 home screen (ShadowMountPlus must be running).

Running the installer again is safe: it resumes and re-sends only `eboot.bin`, `param.json` and changed files.

| Option | Meaning |
|---|---|
| `--ip ADDRESS` | skip the question and the network search |
| `--lang de` or `en` | text language (default: system language) |
| `--dry-run` | connect and compare, write nothing |
| `--app DIR` | app folder (default: the `LAPY77001` folder inside `app`, next to the script) |
| `--payload FILE` | send an ELF to port 9021 after the upload (repeatable) |
| `--ftp-port`, `--loader-port` | if your payloads use other ports |

Without Python (Windows): `.\Install-OpenGOAL.ps1 -Ps5 <your PS5 address>`.

## Add your games

**Fast, from the PC (recommended).** The PC unpacks, analyses and builds the game and sends the result; the app must be running on the console. Paste one line:

**Windows** (PowerShell):

```powershell
irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex
```

**macOS and Linux** (Terminal):

```bash
curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash
```

A window opens: choose or drop your `.iso` files (Jak 1, 2 and 3 are recognised by the disc serial), the PS5 is found automatically (or type its address and press
**Test connection**), press **Start**. You see phase, percent, speed and time left per game; the end message is "Ready: start the game on your PS5". German or English
follows the system language.

**Slower, on the console.** The app shows a QR code. Open `http://<PS5 address>:8080` on a phone or PC and send the `.iso` files ([`ONBOARDING_WEB.md`](ONBOARDING_WEB.md)).

### What the one-liner runs

1. `bootstrap.ps1` / `bootstrap.sh` (about 30 lines, read them first) prints what it will do, downloads `SHA256SUMS` and `OpenGOAL-PS5-gui.zip` from the same release
   and stops if the SHA-256 of the zip does not match.
2. The zip goes to `~/.opengoal-ps5/app` (Windows: `%USERPROFILE%\.opengoal-ps5\app`): the window (`gui/windows/OpenGOAL-PS5.ps1`, `gui/macos/OpenGOAL-PS5.command`,
   `gui/OpenGOAL-PS5-gui.py`) and `pc_import.py`.
3. No admin rights or sudo, no system settings, no PATH changes. Settings: `~/.opengoal-ps5/config.json` (last PS5 address); the import engine caches its tools in
   `~/.opengoal-ps5/tools`. Delete the folder to remove everything.
4. The window talks only to the PS5 (port 8080) and to the downloads the engine needs. It scans only your own /24 network for port 8080.

Python for the window: macOS `xcode-select --install` or python.org (without tkinter it falls back to AppleScript dialogs, headless to a text mode); Linux `python3`
and `python3-tk`; Windows: if Python 3 is missing the window offers `winget install Python.Python.3.12 --scope user` or a portable embeddable zip
(`python-3.12.10-embed-amd64.zip` from python.org, no admin) into `~\.opengoal-ps5\python`, accepted only if its SHA-256 equals the value pinned in
`installer/gui/windows/OpenGOAL-PS5.ps1`.

### Trust model

- The one-liner runs a script fetched over HTTPS from GitHub; nobody can verify it for you before it runs. If you do not want that, use the two-step form: download
  `bootstrap.ps1` (or `.sh`), read it, then run it; or use `gui/` from `OpenGOAL-PS5.zip`.
- The checksum protects against a damaged download and a mixed-up release. It does not protect against someone who controls the release (they could replace the zip and
  `SHA256SUMS` together). Compare the zip's hash with one published through another channel if you need that.
- The Windows window starts with `-ExecutionPolicy Bypass` for that one process only. Your game images never leave your network.

## Troubleshooting

- "[MISSING] ELF loader": the exploit is not running; start it, then run the installer again.
- "[MISSING] FTP": send `ftpsrv-ps5.elf` to port 9021 after kstuff-lite.
- Verification fails: run the installer again; it only re-sends what differs.
- Language and resolution: edit `ps5.cfg` in `/data/opengoal/config`.
- More: [`USER_GUIDE.md`](USER_GUIDE.md).

## Deutsch

**Voraussetzungen:** gejailbreakte PS5 (FW 13.60), PC im selben Netzwerk, Python 3, deine eigenen Jak-Spiele als `.iso`.

**Konsole vorbereiten (Reihenfolge):** Exploit und ELF-Loader (Port 9021), dann `kstuff-lite`, dann `ftpsrv-ps5.elf` (2121) und ShadowMountPlus. OnionHEN NICHT vor dem
Start der App laden. Konsole nicht neu starten, keine Kernel-Flags schreiben.

**Installieren:** Release entpacken, unter Windows `install.bat` doppelklicken, unter Linux und macOS `sh install.sh` (Sprache mit `--lang de`). Adresse eingeben oder
Enter fuer die Netzwerksuche. Der Installer prueft Loader und FTP, laedt die App nach `/data/homebrew/LAPY77001`, legt `ps5.cfg` nur an, wenn sie fehlt, und prueft alle
Dateigroessen. Mit `--dry-run` wird nichts geschrieben. Erneutes Ausfuehren ist gefahrlos. Danach `OpenGOAL-PS5` im Startbildschirm starten.

**Spiele hinzufuegen:** Am schnellsten vom PC: die Zeile fuer dein System aus der Tabelle oben in PowerShell oder das Terminal einfuegen, `.iso`-Dateien waehlen,
**Start** druecken. Langsamer ueber die Konsole: am Handy oder PC `http://<PS5-Adresse>:8080` oeffnen (QR-Code in der App) und die `.iso`-Images senden.
