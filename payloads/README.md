# Payloads

Small ELFs that are sent to the console's ELF loader (port 9021). The prebuilt `.elf` files are what the tools use; the `.c` files are their sources.

| Payload | Used by | What it does |
|---|---|---|
| `killapp` | `tools/ps5 kill`, `run` | closes the app (title `LAPY77001`) |
| `launchapp` | `tools/ps5 run`, `rplay.py` | launches the app when the shell payload is silent after rest mode |
| `scan` | installer (`scan.elf` in the release bundle) | asks ShadowMountPlus for an immediate scan so a newly installed app registers |
| `keepalive` | developers | resets the auto power-down timer and the screen saver every 20 s, heartbeat on UDP 9999 |
| `klog_dump.c` | developers | copies the kernel log to UDP 9999 (`-DALL` for everything, otherwise remote-play and network lines); no prebuilt ELF |
| `kstuff_state.c` | developers | reads kstuff's enable flag (read-only); no prebuilt ELF |

## Origin and licence

Every `.elf` here is built from the `.c` file of the same name with `build.sh` and the PS5 payload SDK v0.42. The ELFs contain our code plus the SDK's runtime objects, so they are
GPL-3.0-or-later like the sources (`THIRD_PARTY_NOTICES.md`, section 4, lists the sha256 of each). No third-party binary is stored in this directory; the loader, kstuff, FTP and shell
servers you send them to come from their own projects.

## Rebuild

```
export PS5_SDK=<install directory of ps5-payload-sdk>
bash payloads/build.sh payloads/killapp.c payloads/killapp.elf
```

`build.sh` needs `clang` and `ld.lld` in the path (on Windows it also adds `C:\Program Files\LLVM\bin`) and links against the SDK's libc, `libSceNet` and
`libkernel_web`. Send a payload with `nc <console address> 9021 < payloads/killapp.elf`. Some payloads read a request file from `/data` first
(`/data/kill_app.txt`, `/data/launch_app.txt` containing the title id); `tools/ps5` writes it for you.
