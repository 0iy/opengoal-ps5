#!/usr/bin/env python3
"""Generate a Ninja build that compiles the jak-project `gk` sources for the PS5.

Reads the host CMake compile_commands.json (exact sources, -D and -I per translation unit),
drops the desktop-only third-party libraries, and rebuilds each TU with the PS5 clang wrapper.
Writes build.ninja and objects.txt into the output directory.
"""
import json
import os
import shlex
import subprocess
import sys

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, "jak_cfg")
JAK = os.path.join(HOME, "jak")
APP = os.path.join(HOME, "ps5app")
OUT = os.path.join(HOME, "ps5build")
WRAP = os.path.join(APP, "tooling", "prospero-clang18")
SDK = os.path.join(APP, ".deps", "native", "ps5-payload-sdk")

# Directories (relative to the jak source root) that are not built for the PS5.
EXCLUDE = (
    "third-party/SDL/",
    "third-party/curl/",
    "third-party/discord-rpc/",
    "third-party/replxx/",
    "third-party/tree-sitter/",
    "third-party/libtinyfiledialogs/",
    "third-party/cubeb/",
    "third-party/googletest/",
)
# Individual files excluded (relative to source root).
EXCLUDE_FILES = set()

COMPAT_FILES = {
    "common/cross_sockets/XSocket.cpp",
    "common/cross_sockets/XSocketServer.cpp",
}

# Per-file extra flags (relative source path -> flags).
FILE_FLAGS = {
    "game/main.cpp": ["-Dmain=gk_main"],  # the PS5 app owns main(); it calls gk_main()
}

# Our own PS5 sources compiled with the engine (path relative to app/shim).
GL_SDK = os.path.join(HOME, "gl", "ps5-opengl-sdk-1.0.0", "sdk", "include")
SHIM_SOURCES = [
    "ps5sdl.cpp",
    "ps5platform.cpp",
    "ps5stubs.cpp",
    "ps5locale.c",
    "ps5posix.c",
    "ps5dirs.c",
    "ps5diag.cpp",
    "gl_table.c",
    "glfix.cpp",
    "launcher.cpp",
    "launcher_assets.cpp",
    "importer.cpp",
    "webserver.cpp",
    "webpage.cpp",
    "qr.cpp",
    "appmain.cpp",
]
SHIM_FLAGS = [
    "-I" + JAK,
    "-I" + os.path.join(JAK, "third-party/SDL/include"),
    "-I" + os.path.join(JAK, "third-party/cubeb/cubeb/include"),
    "-I" + GL_SDK,
]

EXTRA_DEFS = ["-D__ps5__", "-D__forceinline=inline", "-DMAP_POPULATE=0", "-DOS_POSIX"]
SHIM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "shim")
EXTRA_INCLUDES = [os.path.join(SHIM_DIR, "include")]


def keep_flag(tokens):
    """Yield only the flags worth carrying over from the host compile command."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("-D"):
            if t == "-D" and i + 1 < len(tokens):
                yield "-D" + tokens[i + 1]
                i += 1
            else:
                yield t
        elif t.startswith("-I"):
            path = t[2:] if t != "-I" else tokens[i + 1]
            if t == "-I":
                i += 1
            if not path.startswith("/usr"):
                yield "-I" + path
        elif t in ("-isystem", "-I"):
            path = tokens[i + 1]
            i += 1
            if not path.startswith("/usr"):
                yield "-isystem"
                yield path
        elif t.startswith("-std="):
            yield t
        i += 1


def main():
    os.makedirs(OUT, exist_ok=True)
    commands = json.load(open(os.path.join(CFG, "compile_commands.json")))
    gk_cmds = os.path.join(HOME, "gk_cmds.txt")
    if not os.path.exists(gk_cmds):  # the host build's command list for the gk target (needs the CMake configuration in ~/jak_cfg)
        with open(gk_cmds, "w") as f:
            subprocess.run(["ninja", "-t", "commands", "gk"], cwd=CFG, stdout=f, check=True)
    # Restrict to what `gk` needs: read the object list produced by `ninja -t commands gk`.
    needed = set()
    for line in open(gk_cmds):
        if " -c " in line and " -o " in line:
            tokens = shlex.split(line)
            if "-o" in tokens:
                needed.add(tokens[tokens.index("-o") + 1])
    rules = []
    objects = []
    seen = set()
    for entry in commands:
        tokens = shlex.split(entry["command"])
        if "-o" not in tokens:
            continue
        obj_rel = tokens[tokens.index("-o") + 1]
        if obj_rel not in needed:
            continue
        src = entry["file"]
        if not os.path.isabs(src):
            src = os.path.normpath(os.path.join(entry["directory"], src))
        rel = os.path.relpath(src, JAK)
        if rel.startswith(".."):
            rel = os.path.relpath(src, CFG)
        if any(rel.startswith(e) for e in EXCLUDE) or rel in EXCLUDE_FILES:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        is_c = src.endswith(".c")
        flags = list(keep_flag(tokens))
        obj = os.path.join(OUT, "obj", rel.replace("/", "__") + ".o")
        std = "-std=gnu11" if is_c else "-std=c++20"
        flags = [f for f in flags if not f.startswith("-std=")]
        # ps5_compat.h is force-included only where a TU needs it (keeps other objects cached).
        need_compat = rel in COMPAT_FILES
        compat = ["-include", os.path.join(EXTRA_INCLUDES[0], "ps5_compat.h")] if need_compat and not is_c else []
        cmd_flags = " ".join(shlex.quote(f) for f in flags + EXTRA_DEFS + ["-I" + p for p in EXTRA_INCLUDES] + compat + FILE_FLAGS.get(rel, []))
        lang = "cc" if is_c else "cxx"
        rules.append((obj, src, std, cmd_flags, lang))
        objects.append(obj)

    with open(os.path.join(OUT, "build.ninja"), "w") as n:
        n.write("ninja_required_version = 1.5\n")
        n.write(f"wrap = {WRAP}\n")
        n.write(f"sdk = {SDK}\n")
        n.write("rule cxx\n  command = env PS5_PAYLOAD_SDK=$sdk sh $wrap $std -O2 -w -fexceptions -frtti -ffunction-sections -fdata-sections $flags -MD -MF $out.d -c $in -o $out\n  depfile = $out.d\n  deps = gcc\n  description = CXX $out\n")
        n.write("rule cc\n  command = env PS5_PAYLOAD_SDK=$sdk sh $wrap $std -O2 -w -ffunction-sections -fdata-sections $flags -MD -MF $out.d -c $in -o $out\n  depfile = $out.d\n  deps = gcc\n  description = CC $out\n")
        n.write("rule nasm\n  command = nasm -f elf64 -o $out $in\n  description = NASM $out\n")
        for obj, src, std, flags, lang in rules:
            n.write(f"build {obj}: {lang} {src}\n  std = {std}\n  flags = {flags}\n")
        for shim in SHIM_SOURCES:
            obj = os.path.join(OUT, "obj", "shim__" + os.path.basename(shim) + ".o")
            sflags = " ".join(shlex.quote(f) for f in SHIM_FLAGS + EXTRA_DEFS + ["-I" + p for p in EXTRA_INCLUDES])
            is_c_shim = shim.endswith(".c")
            n.write(f"build {obj}: {'cc' if is_c_shim else 'cxx'} {os.path.join(SHIM_DIR, shim)}\n"
                    f"  std = {'-std=gnu11' if is_c_shim else '-std=c++20'}\n  flags = {sflags}\n")
            objects.append(obj)
        asm_obj = os.path.join(OUT, "obj", "asm_funcs_x86_64.o")
        n.write(f"build {asm_obj}: nasm {os.path.join(JAK, 'game/kernel/asm_funcs_x86_64.asm')}\n")
        objects.append(asm_obj)
        n.write("rule ar\n  command = rm -f $out && llvm-ar-18 rcs $out $in\n  description = AR $out\n")
        lib = os.path.join(OUT, "libgk.a")
        n.write(f"build {lib}: ar " + " ".join(objects) + "\n")
        n.write(f"build all: phony {lib}\n")
        n.write("default all\n")
    with open(os.path.join(OUT, "objects.txt"), "w") as f:
        f.write("\n".join(objects) + "\n")
    print(f"{len(objects)} objects ({len(rules)} compile units) -> {OUT}/build.ninja")


if __name__ == "__main__":
    main()
