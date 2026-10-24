# Installing OpenGOAL-PS5

Deutsch: siehe unten.

## What you need

- A jailbroken PS5 (firmware 13.60) and a PC (Windows, Linux or macOS) on the same network.
- Python 3 on the PC (Windows: python.org, tick "Add to PATH"; Linux and macOS: usually installed). The import window on Windows can fetch a portable Python itself.
- The ELF loader (port 9021) running on the console. kstuff-lite and ShadowMountPlus are loaded for you.
- Your own Jak games as unmodified `.iso` images. The release contains no game files.

## Set up the console and install the app (automatic)

Start the exploit on the PS5 until the ELF loader listens on port 9021, then run in the unzipped release folder:

```
python ps5_setup.py
```

(`python3` on Linux and macOS; from a repository checkout `tools/ps5 setup --app <LAPY77001 folder>`; the one-line bootstrap further down runs it first.)
It needs nothing else on the console and does everything in this order, re-probing the console every 1 to 2 seconds and showing what changed:

1. **Discover.** Finds the console without configuration: your own /24 networks are scanned for the homebrew ports (9021, 9020, 2121, 2323, 744, 8080, 9099 and the
   etaHEN, ShadowMountPlus and ps5debug ports), candidates are fingerprinted by banner (ftpsrv, shell prompt, our app, our agent), by Sony MAC prefix and by the read-only
   Remote Play discovery request (UDP 9302). One candidate is taken automatically, several are listed. The address is remembered in `~/.opengoal-ps5/config.json`.
2. **Map.** A live table shows what answers: loader, FTP, shell, ps5debug, agent, app. kstuff cannot be read, so it is shown as "inferred" (ShadowMountPlus or the app runs)
   or "unknown". OnionHEN is reported (red) when its process is visible.
3. **Plan.** Only missing steps: send the agent, load kstuff-lite, load ShadowMountPlus, upload the app, start it. Nothing to do when the app already answers on port 8080.
4. **Install.** The agent (`ogagent.elf`, port 9099, random token per run) is sent to the loader first, because it makes the process list visible. kstuff-lite and
   ShadowMountPlus are downloaded from their own GitHub releases (pinned size and SHA-256, refused on mismatch, cached in `~/.opengoal-ps5/payloads`) and sent in the
   documented order. Each step waits for evidence (a port, a process) instead of a fixed sleep; kstuff has no visible trace and gets the documented 20 s settle time. If a step does
   not show up, one sentence tells you what to do on the console and the setup keeps probing, continuing the moment the console is ready.
5. **App.** The app folder is uploaded in parallel, `eboot.bin` last; files whose size and SHA-256 already match (`.og-manifest.json` on the console) are skipped,
   `/data/opengoal/config/ps5.cfg` is created only when missing, the app is started and the setup waits for `http://<PS5 address>:8080/api/info`. Then the agent is shut down.

It never writes kernel flags, never restarts the console and never loads OnionHEN. kstuff-lite has no license file, so it is fetched from the author's release and only
with your consent (`--with-kstuff`, or the question it asks when kstuff looks missing). Running it again is safe: it resumes and only does what the live state still needs.

| Option | Meaning |
|---|---|
| `--ip ADDRESS`, `--no-scan` | skip the network search (`--no-scan` alone uses the remembered address) |
| `--with-kstuff` | allow loading kstuff-lite when it is needed |
| `--update` | re-check and re-send app files even when the app already runs |
| `--yes` | never ask a question |
| `--dry-run` | probe and print the plan, send nothing |
| `--lang de` or `en` | text language and the `ps5.cfg` language (default: system language) |
| `--json` | one JSON event per line on stdout (for the import window), implies `--yes` |
| `--app DIR` | the `LAPY77001` folder (default: next to the script, else fetched from the release and checked against `SHA256SUMS`) |
| `--agent-elf FILE` | agent payload (default: the `ogagent.elf` in the `payloads` folder next to the script) |
| `--no-agent` | fallback without the agent: `ftpsrv` is loaded and `install.py` uploads over FTP; load ShadowMountPlus and kstuff yourself |
| `--max-wait SECONDS` | give up one waiting step after this long (default 900, exit code 3) |

The log is `~/.opengoal-ps5/setup.log` (the token is masked). Exit codes: 0 done, 1 failed, 2 console not found, 3 gave up waiting, 130 interrupted.
If port 9099 answers with a token this computer does not know (an agent of an unknown run), restart the exploit; the agent also ends by itself after an hour.

### Manual way (what the setup automates)

Boot order on the console: exploit and ELF loader (9021); `kstuff-lite` (wait about 20 s); ShadowMountPlus and, for the old FTP installer, `ftpsrv-ps5.elf` (2121).
Do not load OnionHEN before launching the app (error `0x80020008`), do not restart the console and do not change kernel flags; the flag value `0xffff` is normal on 13.60.
Then `install.bat` (Windows) or `sh install.sh` uploads the app over FTP (`--ip`, `--lang`, `--dry-run`, `--app`, `--payload FILE`, `--ftp-port`, `--loader-port`);
it checks the loader and FTP, skips files already there, creates `ps5.cfg` only if missing and verifies every size. Without Python (Windows):
`.\Install-OpenGOAL.ps1 -Ps5 <your PS5 address>`. Start **OpenGOAL-PS5** from the home screen afterwards (ShadowMountPlus must be running).

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
   After unpacking it runs the console setup (`ps5_setup.py`) first; `OGPS5_SKIP_SETUP=1` skips that. If the app folder is not next to the script, the setup downloads
   `OpenGOAL-PS5.zip` from the same release and checks it against `SHA256SUMS` the same way.
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

- The setup waits at "ELF loader": the exploit is not running; start it and the setup continues by itself.
- The app does not start (`0x80020008`): kstuff-lite is missing or OnionHEN was loaded first; restart the jailbreak chain without OnionHEN, run `python ps5_setup.py --with-kstuff`.
- Upload fails or differs: run the setup again; it only re-sends what differs.
- Language and resolution: edit `ps5.cfg` in `/data/opengoal/config`.
- More: [`USER_GUIDE.md`](USER_GUIDE.md).

## Deutsch

**Voraussetzungen:** gejailbreakte PS5 (FW 13.60), PC im selben Netzwerk, Python 3, deine eigenen Jak-Spiele als `.iso`.

**Konsole einrichten:** Exploit starten, bis der ELF-Loader auf Port 9021 lauscht, dann im entpackten Release `python ps5_setup.py` (Linux, macOS: `python3`). Das Skript findet
die PS5 selbst, zeigt live was laeuft, laedt fehlende Teile (kstuff-lite nur mit `--with-kstuff` oder nach Rueckfrage, ShadowMountPlus) von den Releases der Autoren (Groesse und
SHA-256 fest hinterlegt), laedt die App hoch, startet sie und wartet auf `http://<PS5-Adresse>:8080`. Es wartet bei jedem Schritt auf ein Lebenszeichen (Port, Prozess) und sagt in
einem Satz, was auf der Konsole zu tun ist, wenn etwas fehlt. OnionHEN niemals vor dem Start der App laden. Es schreibt keine Kernel-Flags und startet die Konsole nicht neu.
Optionen: `--ip`, `--no-scan`, `--with-kstuff`, `--update`, `--yes`, `--dry-run` (nichts senden), `--lang de`, `--json`. Erneutes Ausfuehren ist gefahrlos. Ohne Agent geht der
alte Weg: `install.bat` oder `sh install.sh --lang de` (FTP).

**Spiele hinzufuegen:** Am schnellsten vom PC: die Zeile fuer dein System aus der Tabelle oben in PowerShell oder das Terminal einfuegen, `.iso`-Dateien waehlen,
**Start** druecken. Langsamer ueber die Konsole: am Handy oder PC `http://<PS5-Adresse>:8080` oeffnen (QR-Code in der App) und die `.iso`-Images senden.
