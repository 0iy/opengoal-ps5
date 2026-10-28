OpenGOAL for PlayStation 5
==========================

A native port of the OpenGOAL engine (v0.3.6) with a controller-driven launcher.
Play Jak and Daxter: The Precursor Legacy, Jak II and Jak 3 on a jailbroken PS5.

What you need
-------------
* PS5 with the ELF loader (port 9021) running. kstuff-lite and ShadowMountPlus are loaded for you by ps5_setup.py (or load them yourself).
* Your own Jak and Daxter games as unmodified .iso images (this bundle contains no game files).

Install
-------
1. Unzip this folder on a PC in the same network as the PS5.
2. Run the setup (needs Python 3): python ps5_setup.py   (python3 on Linux/macOS; add --with-kstuff to allow loading kstuff-lite)
   It finds the PS5, loads what is missing, uploads and starts the app. Run it again at any time.
   Old way over FTP (needs ftpsrv on port 2121 and ShadowMountPlus already running):
     Windows:      double-click install.bat
     Linux/macOS:  sh install.sh
   It finds the PS5, checks the services, uploads the app and tells you what to do next.
   Options: --ip <ip>  --lang de|en  --dry-run   (details: docs/INSTALL.md in the repository)
   Without Python (Windows): .\Install-OpenGOAL.ps1 -Ps5 <your PS5 IP>
3. On the PS5 open the "OpenGOAL" tile, then open http://<PS5 IP>:8080 to send your own game images.
Verify the download with SHA256SUMS.
Licences: LICENSE (GPL-3.0-or-later), THIRD_PARTY_NOTICES.md and LICENSES/ (components and their licence texts).

Using the launcher
------------------
  Left / Right ... choose a game      Cross ... play
  Triangle ....... display settings   Square .. controls help

Game data is stored in /data/opengoal/<game>/data. Saves and settings are in /data/opengoal/config.
Logs: /data/opengoal/log/ps5.log (also sent as UDP broadcast on port 9999 for debugging).
Import problems: every PC import writes a full debug log to <your home folder>\.opengoal-ps5\last_import.log (it includes the console's
log tail after a failure). Attach that one file to a bug report. The console log is also readable in a browser: http://PS5-IP:8080/api/log
