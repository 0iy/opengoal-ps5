# Installing OpenGOAL-PS5

Deutsch: siehe unten.

## What you need

- A jailbroken PS5 (firmware 13.60) and a PC (Windows, Linux or macOS) on the same network.
- Python 3 on the PC (Windows: python.org, tick "Add to PATH"; Linux/macOS: usually installed).
- Your own Jak games. The release contains no game files.

## Get the console ready (in this order)

1. Exploit + ELF loader (port 9021). Nothing else yet.
2. `kstuff-lite` (send to 9021, wait about 20 s).
3. `ftpsrv-ps5.elf` (FTP, port 2121) and ShadowMountPlus. `shsrv` (port 2323) is optional.
4. Do NOT load OnionHEN before launching the app: the app is then refused (error `0x80020008`).
5. Do not restart the console and do not change kernel flags; the `0xffff` flag value is normal on 13.60.

## Install

1. Download and unzip the release. Optional: check files against `SHA256SUMS`
   (`sha256sum -c SHA256SUMS`, or `Get-FileHash` on Windows).
2. Windows: double-click `install.bat`. Linux/macOS: `sh install.sh`.
3. Enter the PS5 IP (or press Enter to search the network). The installer:
   - checks that the loader (9021) and FTP (2121) answer, and says in plain words what is missing;
   - uploads the app to `/data/homebrew/LAPY77001` with progress, skipping files already there;
   - creates `/data/opengoal/config/ps5.cfg` (resolution=0, refresh=60, language) only if it does not exist;
   - verifies the sizes of every file on the console;
   - optionally sends payload ELFs you provide (`--payload file.elf`, or type paths when asked). OnionHEN is refused.
4. Start **OpenGOAL-PS5** from the PS5 home screen (ShadowMountPlus must be running).
5. The app shows a QR code. Open `http://<PS5 IP>:8080` on your phone or PC and send your own `.iso` images.
   Faster: import from the PC with a one-liner, see [`ONE_LINERS.md`](ONE_LINERS.md).

Running the installer again is safe (resumes, re-sends only `eboot.bin`, `param.json` and changed files).

## Options

| Option | Meaning |
|---|---|
| `--ip 192.168.x.y` | skip the question / network search |
| `--lang de` or `en` | text language (default: system language) |
| `--dry-run` | connect and compare, but write nothing |
| `--app DIR` | app folder (default `app/LAPY77001` next to the script) |
| `--payload FILE` | send an ELF to port 9021 after the upload (repeatable) |
| `--ftp-port`, `--loader-port` | if your payloads use other ports |

## Troubleshooting

- "[MISSING] ELF loader": the exploit is not running; start it, then run the installer again.
- "[MISSING] FTP": send `ftpsrv-ps5.elf` to port 9021 after kstuff-lite.
- Verify fails: run the installer again; it only re-sends what differs.
- Launcher language/resolution: `ps5.cfg` can be edited in `/data/opengoal/config`.

## Deutsch

**Voraussetzungen:** gejailbreakte PS5 (FW 13.60), PC im selben Netzwerk, Python 3, deine eigenen Jak-Spiele.

**Konsole vorbereiten (Reihenfolge):** Exploit + ELF-Loader (Port 9021), dann `kstuff-lite`, dann `ftpsrv-ps5.elf` (2121) und
ShadowMountPlus. OnionHEN NICHT vor dem Start der App laden. Konsole nicht neu starten, keine Kernel-Flags schreiben.

**Installieren:** Release entpacken, unter Windows `install.bat` doppelklicken, unter Linux/macOS `sh install.sh`
(Sprache mit `--lang de`). IP eingeben oder Enter fuer die Netzwerksuche. Der Installer prueft Loader und FTP, laedt die App
nach `/data/homebrew/LAPY77001`, legt `ps5.cfg` nur an, wenn sie fehlt, und prueft alle Dateigroessen. Mit `--dry-run` wird
nichts geschrieben. Danach `OpenGOAL-PS5` im Startbildschirm starten, am Handy oder PC `http://<PS5-IP>:8080` oeffnen und die
eigenen `.iso`-Images senden. Erneutes Ausfuehren ist gefahrlos.
