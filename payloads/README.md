# Payloads

Small ELFs that are sent to the console's ELF loader (port 9021). The prebuilt `.elf` files are what the tools use; the `.c` files are their sources.

| Payload | Used by | What it does |
|---|---|---|
| `killapp` | `tools/ps5 kill`, `run` | closes the app (title `LAPY77001`) |
| `launchapp` | `tools/ps5 run`, `rplay.py` | launches the app when the shell payload is silent after rest mode |
| `scan` | installer (`scan.elf` in the release bundle) | asks ShadowMountPlus for an immediate scan so a newly installed app registers |
| `keepalive` | developers | resets the auto power-down timer and the screen saver every 20 s, heartbeat on UDP 9999 |
| `ogagent` | installer (one-command setup) | HTTP agent on TCP 9099: copies files into `/data/homebrew/LAPY77001/` and `/data/opengoal/`, reads logs, launches and kills the app; needs a patched token (see below) |
| `klog_dump.c` | developers | copies the kernel log to UDP 9999 (`-DALL` for everything, otherwise remote-play and network lines); no prebuilt ELF |
| `kstuff_state.c` | developers | reads kstuff's enable flag (read-only); no prebuilt ELF |

## ogagent: the setup agent

`ogagent.elf` is the console-side half of the automatic setup, so ftpsrv and shsrv are not needed for it. The PC script patches a token into the ELF, sends it to
the loader (9021) and then talks HTTP to the console on **TCP 9099**. A notification "OpenGOAL setup agent ready" appears on the TV. Sending it a second
time while one runs is harmless: the new copy finds the port in use and exits.

**Token marker.** `og_token_blob` in `ogagent.c` is a writable, exported `char` array in `.data`, read through a `volatile` pointer so the compiler can neither
drop nor fold it. In the ELF it is the 14 bytes `OGAGENT_TOKEN:` followed by 32 lowercase `x` characters and a NUL. The marker text occurs exactly once in the file.
Patch the 32 bytes after the marker with the token (32 printable ASCII characters without space; letters and digits are the safe choice), keep the file length:

```python
MARK = b"OGAGENT_TOKEN:"
data = bytearray(open("ogagent.elf", "rb").read())
assert data.count(MARK) == 1 and len(token) == 32
i = data.index(MARK) + len(MARK)
assert data[i:i + 32] == b"x" * 32      # still the filler
data[i:i + 32] = token.encode("ascii")
```

An unpatched agent (token still the filler) shows a notification and exits instead of listening.

**Requests.** Every request needs `X-OG-Token: <token>` (constant-time compare; a wrong token gets 401 after a 100 ms delay and the connection is closed).
Minimal HTTP/1.1, one thread per connection (16 at most, then 503), keep-alive and pipelining work, no chunked bodies (501), `Expect: 100-continue` is honoured.
Headers are limited to 8 KiB (431), bodies of everything except `PUT /v1/file` to 64 KiB (413), a file to 8 GiB (413). Answers are JSON (`{"ok":true,...}` or
`{"ok":false,"error":"..."}`), except the body of `GET /v1/file`. Query values are percent-decoded once; `+` stays `+`.

| Endpoint | Parameters | Result |
|---|---|---|
| `GET /v1/status` | none | `agent` (version, uptime_s, lifetime_left_s, launched), `system` (kernel, firmware, sdk_version, uptime_s), `processes` ([pid, name, title]), `tcp_ports_open` (loopback probe of 744, 2121, 2323, 9020, 9021, 9099), `mounts` ([path, type, free_bytes, total_bytes]), `paths` (app_dir_exists, data_dir_exists, eboot_size or -1), `app` (title, running, app_id), `caps` (write_data, launch) |
| `PUT /v1/file` | `path` (absolute), `size` (must equal Content-Length), `mode` (octal, default 644, at most 777) | streams the body into `<path>.part`, checks the byte count, renames; creates parent folders. A connection that ends early removes the `.part` and leaves the old file. 409 when another upload of the same path runs or the target is a folder; names ending in `.part` are refused (400) |
| `GET /v1/file` | `path`; optional `tail=<bytes>`, or `offset=<n>` and `len=<n>` | the bytes, header `X-OG-File-Size` holds the whole size; one answer is cut at 64 MiB |
| `POST /v1/mkdir` | `path` (query, or a form or JSON body) | creates the folder and its parents; the allowed root itself is accepted |
| `POST /v1/rm` | `path`; `recursive=1` for non-empty folders | removes a file, an empty folder or a tree below `/data/opengoal/tmp/` or the app folder (not those folders themselves; symlinks are never followed); a missing path answers `removed:0` |
| `POST /v1/launch` | `title` (only `LAPY77001`, the default) | same calls as `launchapp.c`; `launch` holds the raw result, HTTP 500 when it is not 0 |
| `POST /v1/kill` | `title` (only `LAPY77001`) | same calls as `killapp.c` (KillApp, 1.5 s, ForceKillApp); raw results in `kill` and `force_kill` |
| `GET /v1/log` | `tail=<n>` (default 100, at most 256) | `lines`: the agent's own ring buffer, one line per request (peer, request line, status code), never the token |
| `POST /v1/shutdown` | none | answers and ends the agent |

Path policy for `path`: absolute, no empty, `.` or `..` component, no backslash or control character, no trailing slash, and below `/data/homebrew/LAPY77001/` or
`/data/opengoal/`; any existing component below the root that is a symlink is refused. Everything else answers 403 (a missing `path` is 400). The agent never
changes kernel flags, system settings or other processes; the only process it touches is the allowed title through the launcher service.

**Lifetime.** The agent ends 60 minutes after it started (`OG_LIFETIME_SEC`) or 10 minutes after the last request once a `launch` succeeded
(`OG_IDLE_AFTER_LAUNCH_SEC`, a running request does not count as idle). Both are compile-time constants.

**Build and test.** `bash payloads/build.sh payloads/ogagent.c payloads/ogagent.elf -lkernel_sys -lSceSystemService -lSceUserService`
(`getfsstat` lives in `libkernel_sys`; the file avoids `statvfs`, `thread_local` and static objects with destructors). The same source builds for the host
with `-DOG_HOST` and `python tests/test_ogagent_host.py` (in WSL or Linux) drives every endpoint against temporary folders; `tests/run_all.py` runs it.

**Read, not run.** The host test cannot cover the console calls: `sysctl` KERN_PROC and `sysctlbyname` (`kern.version`, `kern.sdk_version`),
`sceKernelGetSystemSwVersion` and `sceKernelGetAppInfo` (struct layouts assumed: a title id is only reported when it has the shape `XXXX00000`),
`getfsstat`, the `sceLncUtil*` and `sceUserService*` calls, `sceKernelSendNotificationRequest`, and `app.running` (title match, else the launcher's app id above 0).

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
