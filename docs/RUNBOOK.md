# Runbook: operating the console

For developers. Users follow [`INSTALL.md`](INSTALL.md). Tested console: PS5, firmware 13.60. The console address is `PS5_IP` or the git-ignored `.ps5_ip`.

## Boot order that works (after every console restart)

Steps 2 and 3 are automated: after the loader (step 1) is up, run `tools/ps5 setup` (or `python installer/ps5_setup.py`). It maps what answers on the console, loads kstuff-lite
(only with `--with-kstuff`) and ShadowMountPlus in this order when the live state shows them missing, uploads and starts the app, and waits for evidence (a port, a process) after
every step. It never loads OnionHEN, never writes kernel flags and never restarts the console. `--dry-run` shows the plan. Details and options: [`INSTALL.md`](INSTALL.md).
The list below is what it implements, and what to do by hand:

1. Browser exploit and ELF loader (port 9021 open). Nothing else yet.
2. `kstuff-lite` (send to 9021), wait about 20 s.
3. `ftpsrv-ps5.elf` (FTP 2121), ShadowMountPlus (mounts `/data/homebrew/LAPY77001` when the app launches), optionally `shsrv-ps5.elf` (plain TCP shell on 2323:
   `ps`, `cat`, `ls`, `cp`, `launch`, `kill`).
4. Do not load OnionHEN before the app: with its built-in kstuff the fake-signed eboot is refused (`0x80020008`, kernel log
   `sceSblAuthMgrAuthHeader returned unexpected error 46`).
5. A ps5debug payload on port 744 is optional; `python tools/ps5dbg_maps.py list` is read-only.

Payloads come from their upstream releases (`EchoStretch/kstuff-lite`, `ps5-payload-dev/ftpsrv`, `ps5-payload-dev/shsrv`, ShadowMountPlus): verify them
against the release digests. `ps5_setup.py` pins size and SHA-256 (kstuff-lite v1.11, ShadowMountPlus 1.7beta7, ftpsrv v0.21.1, shsrv v0.20) in its `PAYLOADS` table; update
the pins there when you move to a newer release (hash the file you downloaded, compare with the `digest` of the GitHub release API). Never write kernel flags from payloads. Never restart the console from scripts.

## Daily loop

```
tools/ps5 doctor           # toolchain files, and the console ports when an address is set
tools/ps5 go jak3 60       # build, kill, deploy, run for 60 s
tools/ps5 log "fps|CRASH"  # grep the console log of the last start
```

After rest mode the loader (9021) and FTP (2121) usually survive but the shell payload can accept connections and stay silent; `tools/ps5` then launches and kills
the app through `payloads/launchapp.elf` and `payloads/killapp.elf` via the loader. If every port is closed the jailbreak is gone: run the exploit again.

## Logs

| Source | How |
|---|---|
| App log | UDP broadcast on port 9999 (one listener at a time); `tools/ps5 run` prints it and saves `out/last_run.log` |
| Full log on the console | `/data/opengoal/log/ps5.log` (200+ MB, read with FTP REST): `tools/ps5 log` |
| Kernel log | `payloads/klog_dump.c` (build with `-DALL` for the full stream), crash reports contain `# fault address` and `# rip` |
| Crash addresses | `tools/ps5 sym <runtime address of ps5_log> <address> ...` resolves them against the app ELF in WSL |
| Debug channel | `tools/ps5 dbg ping`; the app dials out to the PC on TCP 9998 when `/data/opengoal/config/debughost.txt` holds the PC address |

## Payloads

`payloads/` holds sources and prebuilt ELFs for `killapp`, `launchapp`, `scan` (used by the installer) and `keepalive` (resets the auto power-down timer every
20 s while you work). `klog_dump.c` and `kstuff_state.c` are diagnostics (read the kernel log, read kstuff's enable flag; `0xffff` is normal on 13.60) and
are built on demand. Rebuild with `bash payloads/build.sh <file.c> <out.elf>` (needs `PS5_SDK`, the ps5-payload-sdk install, and clang with lld).

### Setup agent

`payloads/ogagent.elf` (TCP 9099, header `X-OG-Token`) is what the one-command setup talks to instead of ftpsrv and shsrv. The PC script patches a token into the
ELF before sending it to 9021; it stops by itself after 60 minutes, or 10 minutes after the last request once the app was launched. If a send failed, send it
again: a second copy exits when the port is busy. `GET /v1/status` shows kernel, processes, mounts and whether the app runs; `GET /v1/log?tail=50` shows its own
request log. Endpoints and the token layout are in `payloads/README.md`.

## Stray settings

Stray controller presses in the launcher change `ps5.cfg` (resolution to 4K, for example). `tools/rplay.py` resets it; check `resolution=0` before measuring.
