# Setting up the build/test environment on a new machine

The previous machine was Windows 11 + WSL2 Ubuntu. Paths below are the ones the scripts hard-code
(`/mnt/c/Users/<you>/dev/projects/opengoal-ps5` = this repo, `~/jak`, `~/gl`, `~/drv`, `~/ps5app`, `~/ogapp`, `~/ps5build`);
on another user name, search-and-replace `milos` / `a1` in the scripts (`ps5.py` has `WSL_HERE`, the `*.sh` files have `HERE=`).

## 0. Clone this repo

```
git clone https://github.com/0iy/opengoal-ps5.git C:\Users\<you>\Desktop\ps5-homebrew
```

Open the folder in your editor and read `docs/HANDOFF.md` first.

## 1. Third-party sources (pinned)

| What | URL | Revision | Where |
| --- | --- | --- | --- |
| jak-project (OpenGOAL) | https://github.com/open-goal/jak-project | `553a713aed3794f454fa7b45a1f1ef443bbb914a` | `~/jak` (WSL) |
| ps5-opengl SDK (Mesa -> AGC) | https://github.com/blackbearreloaded/ps5-opengl/releases/latest | file `sdk.tgz`, sha256 `f93643c0...77c5` (see `wsl_snapshot/sdk_tgz.sha256`) | `~/gl/ps5-opengl-sdk-1.0.0`, sources `~/gl/src/ps5-opengl` |
| ps5-native-app-boilerplate | https://github.com/blackbearreloaded/ps5-native-app-boilerplate | `b8dc4a3fe2e05e826b037bd68824751c7468a6d7` | `~/ps5app` |
| ps5-payload-sdk (clang wrapper, loader) | https://github.com/ps5-payload-dev/sdk | v0.44 `f5d40f02770e9b0001dd9e18056eca70b3da8b40` | inside `~/ps5app/.deps` |
| ps5debug-NG, playden-ps5 (reference only) | https://github.com/Pharaoh2k/ps5debug-NG , https://github.com/leolobato/playden-ps5 | see `.gitmodules`-less notes in HANDOFF | optional |
| Mesa (inside the SDK) | https://archive.mesa3d.org/mesa-26.2.0.tar.xz | sha256 `efd4bb08...a4ef` | `~/drv/tp/mesa-26.2.0` |
| opengnm-psbc | https://github.com/PS4-OpenGNM/opengnm-psbc | `a92a1228ea3a64e4be9f0e61c2a65a5aa7ffed92` | `~/drv/tp/opengnm-psbc` |

The full dependency list of the SDK is in `wsl_snapshot/ps5-opengl_dependencies_head.json` and in the SDK's own `dependencies.json`.

## 2. WSL packages

```
sudo apt install build-essential cmake ninja-build clang-18 lld-18 llvm-18 llvm-18-tools python3 python3-pip python3-numpy python3-pil git curl zstd unzip
pip install pillow numpy
```

`llvm-symbolizer-18` / `llvm-nm-18` are used to turn runtime addresses into names (image base offset is `0x400000`, see `addr2sym.sh`).
Windows side: Python 3.13 with `pillow`; Git; `gh` (GitHub CLI) for the repo.

## 3. Reproduce the WSL trees

```
# jak-project: pinned base + our patched working tree
git clone https://github.com/open-goal/jak-project ~/jak && cd ~/jak && git checkout 553a713aed3794f454fa7b45a1f1ef443bbb914a
git submodule update --init --recursive
git apply /mnt/c/Users/<you>/Desktop/ps5-homebrew/wsl_snapshot/jak-project_vs_553a713.patch
# (equivalently: python3 apply_ps5_patches.py; patch_gfxprof.py; patch_proftree.py — the diff already contains them)

# ps5-opengl SDK: unpack the release, then overwrite the sources we patched with the snapshot copies
mkdir -p ~/gl && tar xzf sdk.tgz -C ~/gl          # produces ps5-opengl-sdk-1.0.0 and src/ps5-opengl
S=/mnt/c/Users/<you>/Desktop/ps5-homebrew/wsl_snapshot/ps5-opengl
cp $S/gallium_ps5/*     ~/gl/src/ps5-opengl/src/gallium/ps5/
cp $S/platform/*        ~/gl/src/ps5-opengl/src/platform/
cp $S/egl/ps5_egl.c     ~/gl/src/ps5-opengl/src/egl/
cp $S/*.mk              ~/gl/src/ps5-opengl/toolchain/   # if present
```

The snapshot files are the *final* patched versions (all `drv_patch*.py` already applied). To rebuild the history instead,
run the `drv_patch*.py` scripts in numeric order on an untouched SDK (each one is idempotent and asserts its anchors).

`~/drv` (driver compile directory): `rc.txt` (compiler flags and defines, line 2-5), `flags.txt`, helper `mbuild/` are in
`wsl_snapshot/drv/`. The SDK's generated headers for the gallium driver live under `~/drv/tp/opengnm-psbc` (build them with
`make generated` in that tree, as done on the original machine) and `~/drv/tp/mesa-26.2.0/src/mesa` is the unpacked Mesa 26.2.0 tarball.
**Gap:** the exact one-time commands that created `~/drv/tp` were not scripted; recreate it by unpacking Mesa 26.2.0 and cloning
opengnm-psbc at the pinned revision, then run `bash drv_cc.sh` — if it complains about a missing header, build the `generated` target.

```
# app packaging
git clone https://github.com/blackbearreloaded/ps5-native-app-boilerplate ~/ps5app && cd ~/ps5app && git checkout b8dc4a3f...
(run its `make` once so `.deps/native/ps5-payload-sdk` exists)
bash /mnt/c/.../ps5-homebrew/setup_cxx.sh       # C++ variant of the boilerplate (exceptions + RTTI + libc++)
bash /mnt/c/.../ps5-homebrew/setup_ogapp.sh     # assemble ~/ogapp (copies wsl_snapshot-like sources, link recipe, libog_group.a)
python3 /mnt/c/.../ps5-homebrew/gen_ps5_ninja.py   # ~/ps5build/build.ninja from the jak-project compile_commands.json
bash /mnt/c/.../ps5-homebrew/rebuild_all.sh     # libgk.a + eboot.bin (or: python ps5.py build)
```

`ogapp_src/` and `ps5shim/` in this repo are the app-side sources that `rebuild_all.sh` copies into `~/ogapp/src`.
`wsl_snapshot/ogapp/` is a reference copy of the `~/ogapp` files that were hand-edited.

## 4. Console

- Jailbroken PS5 (fw 13.60) with etaHEN, FTP on 2121, ELF loader on 9021, shell payload on 2323 (optional).
- Install the app once (`release_template/Install-OpenGOAL.ps1` or copy `eboot.bin`, `sce_sys/`, `assets/` to
  `/data/homebrew/LAPY77001` and register it with etaHEN); afterwards `python ps5.py deploy` only uploads `eboot.bin`.
- Games: put your own ISOs on the console (`/data/opengoal/import/<game>.iso`) and import through the launcher or
  `POST http://<ps5>:8080/api/start?game=jak1`. No game data is in this repo.
- Debug channel: run `python dbg.py serve` on the PC (or let `ps5.py snap` start it) and write the PC's LAN IP into
  `/data/opengoal/config/debughost.txt`.

## 5. First checks on the new machine

```
python ps5.py build         # builds eboot.bin in WSL
python ps5.py deploy
python jak3_play.py         # needs the debug channel; or: python rplay.py --deploy   (FTP only)
python fpsnow.py
```
Expected for Jak 3 spawn scene with the 2026-10-20 build: ~38-43 fps, thread cpu ~16 ms (see `PERF_ANALYSIS.md`).
