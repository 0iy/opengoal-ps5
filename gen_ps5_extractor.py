#!/usr/bin/env python3
"""Generate a Ninja build for the jak-project `extractor` (ISO -> game data) sources for the PS5.

Same method as gen_ps5_ninja.py: take the host CMake compile commands for the target, rebuild each TU with the PS5
clang wrapper. Translation units already in libgk.a are skipped; the rest go to libextractor.a.
`decompiler/extractor/main.cpp` is built with -Dmain=extractor_main so the app can call it.
"""
import json
import os
import shlex
import sys

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, "jak_cfg")
JAK = os.path.join(HOME, "jak")
APP = os.path.join(HOME, "ps5app")
OUT = os.path.join(HOME, "ps5build_ext")
WRAP = os.path.join(APP, "tooling", "prospero-clang18")
SDK = os.path.join(APP, ".deps", "native", "ps5-payload-sdk")
HERE = os.path.dirname(os.path.abspath(__file__))

EXCLUDE = (
    "third-party/SDL/", "third-party/curl/", "third-party/discord-rpc/", "third-party/tree-sitter/",
    "third-party/libtinyfiledialogs/", "third-party/cubeb/", "third-party/googletest/",
)
EXTRA_DEFS = ["-D__ps5__", "-D__forceinline=inline", "-DMAP_POPULATE=0", "-DOS_POSIX"]
EXTRA_INCLUDES = [os.path.join(HERE, "ps5shim", "include")]
FILE_FLAGS = {"decompiler/extractor/main.cpp": ["-Dmain=extractor_main"],
              "goalc/listener/Listener.cpp": ["-DTCP_SOCKET_LEVEL=IPPROTO_TCP"]}


# Libraries that CMake builds as separate shared targets (not part of the extractor TU list): replxx and tree-sitter.
_REPLXX = ["ConvertUTF.cpp", "conversion.cxx", "escape.cxx", "history.cxx", "prompt.cxx", "replxx.cxx", "replxx_impl.cxx", "terminal.cxx", "util.cxx"]
EXTRA_SOURCES = []  # replxx is stubbed in ps5shim/ps5stubs.cpp (no terminal on the console)
EXTRA_SOURCES += [
    ("third-party/tree-sitter/tree-sitter/lib/src/lib.c", ["-I" + os.path.join(JAK, "third-party/tree-sitter/tree-sitter/lib/include"), "-I" + os.path.join(JAK, "third-party/tree-sitter/tree-sitter/lib/src")]),
    ("third-party/tree-sitter/tree-sitter-opengoal/parser.c", ["-I" + os.path.join(JAK, "third-party/tree-sitter/tree-sitter-opengoal")]),
]


def keep_flag(tokens):
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
        elif t == "-isystem":
            path = tokens[i + 1]
            i += 1
            if not path.startswith("/usr"):
                yield "-isystem"
                yield path
        i += 1


def rel_of(entry):
    src = entry["file"]
    if not os.path.isabs(src):
        src = os.path.normpath(os.path.join(entry["directory"], src))
    rel = os.path.relpath(src, JAK)
    if rel.startswith(".."):
        rel = os.path.relpath(src, CFG)
    return src, rel


def objs_of(cmd_file):
    out = set()
    for line in open(cmd_file):
        if " -c " in line and " -o " in line:
            t = shlex.split(line)
            if "-o" in t:
                out.add(t[t.index("-o") + 1])
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    commands = json.load(open(os.path.join(CFG, "compile_commands.json")))
    need = objs_of(os.path.join(HOME, "ext_cmds.txt"))
    have = objs_of(os.path.join(HOME, "gk_cmds.txt"))
    rules, objects, seen = [], [], set()
    for entry in commands:
        tokens = shlex.split(entry["command"])
        if "-o" not in tokens:
            continue
        o = tokens[tokens.index("-o") + 1]
        if o not in need:
            continue
        src, rel = rel_of(entry)
        if rel in seen or any(rel.startswith(e) for e in EXCLUDE):
            continue
        if o in have and rel != "decompiler/extractor/main.cpp":
            continue  # already part of libgk.a
        seen.add(rel)
        is_c = src.endswith(".c")
        flags = [f for f in keep_flag(tokens) if not f.startswith("-std=")]
        obj = os.path.join(OUT, "obj", rel.replace("/", "__") + ".o")
        cmd_flags = " ".join(shlex.quote(f) for f in flags + EXTRA_DEFS + ["-I" + p for p in EXTRA_INCLUDES] + FILE_FLAGS.get(rel, []))
        rules.append((obj, src, "-std=gnu11" if is_c else "-std=c++20", cmd_flags, "cc" if is_c else "cxx"))
        objects.append(obj)
    for rel, flags in EXTRA_SOURCES:
        src = os.path.join(JAK, rel)
        is_c = src.endswith(".c")
        obj = os.path.join(OUT, "obj", rel.replace("/", "__") + ".o")
        rules.append((obj, src, "-std=gnu11" if is_c else "-std=c++20", " ".join(shlex.quote(f) for f in flags + EXTRA_DEFS), "cc" if is_c else "cxx"))
        objects.append(obj)
    with open(os.path.join(OUT, "build.ninja"), "w") as n:
        n.write("ninja_required_version = 1.5\n")
        n.write(f"wrap = {WRAP}\nsdk = {SDK}\n")
        n.write("rule cxx\n  command = env PS5_PAYLOAD_SDK=$sdk sh $wrap $std -O2 -w -fexceptions -frtti -ffunction-sections -fdata-sections $flags -MD -MF $out.d -c $in -o $out\n  depfile = $out.d\n  deps = gcc\n  description = CXX $out\n")
        n.write("rule cc\n  command = env PS5_PAYLOAD_SDK=$sdk sh $wrap $std -O2 -w -ffunction-sections -fdata-sections $flags -MD -MF $out.d -c $in -o $out\n  depfile = $out.d\n  deps = gcc\n  description = CC $out\n")
        for obj, src, std, flags, lang in rules:
            n.write(f"build {obj}: {lang} {src}\n  std = {std}\n  flags = {flags}\n")
        n.write("rule ar\n  command = rm -f $out && llvm-ar-18 rcs $out $in\n  description = AR $out\n")
        lib = os.path.join(OUT, "libextractor.a")
        n.write(f"build {lib}: ar " + " ".join(objects) + "\n")
        n.write(f"build all: phony {lib}\ndefault all\n")
    print(f"{len(objects)} objects -> {OUT}/build.ninja")


main()
