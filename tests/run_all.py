#!/usr/bin/env python3
"""All-in-one offline test suite. Never contacts the console.

  python tests/run_all.py            run everything, print one PASS/FAIL/SKIP table, exit 1 on any FAIL
  python tests/run_all.py -k lint    only checks whose name contains "lint" (repeat -k to add more)
  python tests/run_all.py --list     list the checks

Checks that need a tool which is not installed (PowerShell, node, WSL or g++, numpy/Pillow) are reported as SKIP with the reason.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CHECKS = []
SKIP_DIRS = {".git", "out", "release", "archive", "backup", "node_modules", "__pycache__", "shots_all", "perf_runs"}


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


class Skip(Exception):
    pass


# ----------------------------------------------------------------------------------------------- helpers
def repo_files():
    """Tracked files plus untracked files that are not ignored (what a commit would contain)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            names = [n.decode("utf-8", "replace") for n in out.stdout.split(b"\0") if n]
            return sorted(n for n in set(names) if os.path.isfile(os.path.join(ROOT, n)))
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        found += [os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/") for f in files]
    return sorted(found)


FILES = None


def files(*suffixes):
    global FILES
    if FILES is None:
        FILES = repo_files()
    return [f for f in FILES if f.endswith(suffixes)] if suffixes else FILES


def read_text(rel):
    data = open(os.path.join(ROOT, rel), "rb").read()
    return None if b"\0" in data else data.decode("utf-8", "replace")


def run(cmd, timeout=300, cwd=ROOT, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)


def tail(p, n=12):
    return "\n".join((p.stdout + p.stderr).strip().splitlines()[-n:])


def wsl_path(p):
    p = os.path.abspath(p)
    return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/") if os.name == "nt" else p


def linux_shell():
    """Return a function running a bash script on Linux (WSL on Windows), or raise Skip."""
    if os.name == "nt":
        if not shutil.which("wsl"):
            raise Skip("WSL not installed")
        base = ["wsl", "-e", "bash", "-c"]
    else:
        base = ["bash", "-c"]
    probe = run(base + ["command -v g++ >/dev/null && command -v curl >/dev/null && echo ok"], timeout=120)
    if "ok" not in probe.stdout:
        raise Skip("g++ and curl are needed (WSL or Linux)")

    def go(script, timeout=300):
        return run(base + ["cd '%s' && %s" % (wsl_path(ROOT), script)], timeout=timeout)
    return go


# ----------------------------------------------------------------------------------------------- static checks
@check("repository layout")
def t_layout():
    allowed = {"README.md", "README.de.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "LICENSES", ".gitignore", ".github",
               "app", "driver", "engine", "payloads", "tools", "installer", "tests", "art", "docs"}
    extra = sorted({f.split("/")[0] for f in files()} - allowed)
    assert not extra, "unexpected entries in the repository root: " + ", ".join(extra)
    return "%d files" % len(files())


@check("python compile")
def t_pycompile():
    bad = []
    for f in files(".py"):
        try:
            compile(read_text(f), f, "exec")
        except SyntaxError as e:
            bad.append("%s:%s %s" % (f, e.lineno, e.msg))
    assert not bad, "\n".join(bad)
    return "%d files" % len(files(".py"))


@check("shell syntax")
def t_shell():
    bash = shutil.which("bash")
    if not bash:
        raise Skip("bash not found")
    scripts = files(".sh", ".command") + [f for f in files() if f == "tools/ps5"]
    bad = []
    for f in scripts:
        p = subprocess.run([bash, "-n"], input=open(os.path.join(ROOT, f), "rb").read(), capture_output=True)
        if p.returncode:
            bad.append(f + ": " + p.stderr.decode("utf-8", "replace").strip()[:200])
    assert not bad, "\n".join(bad)
    return "%d scripts" % len(scripts)


@check("powershell parse")
def t_powershell():
    ps = shutil.which("pwsh") or shutil.which("powershell")
    if not ps:
        raise Skip("no PowerShell found")
    scripts = files(".ps1")
    code = ("$bad = 0; foreach ($f in ($env:OG_FILES -split '\\|')) { $t = $null; $e = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e); "
            "foreach ($x in $e) { $bad++; Write-Output ($f + ':' + $x.Extent.StartLineNumber + ' ' + $x.Message) } }; exit $bad")
    env = dict(os.environ, OG_FILES="|".join(os.path.join(ROOT, f) for f in scripts))
    p = run([ps, "-NoProfile", "-NonInteractive", "-Command", code], env=env, timeout=120)
    assert p.returncode == 0, tail(p)
    return "%d scripts (%s)" % (len(scripts), os.path.basename(ps))


@check("json files")
def t_json():
    n = 0
    for f in files(".json", ".lock"):
        json.loads(read_text(f))
        n += 1
    return "%d files" % n


MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE_PATH = re.compile(r"`((?:app|driver|engine|payloads|tools|installer|tests|art|docs)/[A-Za-z0-9_./-]+)`")


@check("docs links and paths")
def t_docs():
    bad = []
    for f in files(".md"):
        text = read_text(f) or ""
        here = os.path.dirname(f)
        for m in MD_LINK.finditer(text):
            target = m.group(1).split("#")[0]
            if not target or re.match(r"[a-z]+:", target):
                continue
            if not os.path.exists(os.path.join(ROOT, here, target)):
                bad.append("%s: broken link %s" % (f, target))
        for m in CODE_PATH.finditer(text):
            p = m.group(1)
            if "*" in p or "<" in p:
                continue
            if not os.path.exists(os.path.join(ROOT, p)) and not os.path.exists(os.path.join(ROOT, p.rstrip("/"))):
                bad.append("%s: path does not exist: %s" % (f, p))
    assert not bad, "\n".join(bad[:25])
    return "%d documents" % len(files(".md"))


# ----------------------------------------------------------------------------------------------- privacy lint
def lint_rules():
    j = "".join
    return [
        ("name", re.compile(j(["cla", "ude"]) + "|" + j(["anthro", "pic"]), re.I), None),
        ("private IP", re.compile(r"\b(?:192\.168|10\.(?!255\.255\.255\b)\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), None),
        ("MAC address", re.compile(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b"), None),
        ("user path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/Users/[A-Za-z]|/mnt/[a-z]/Users|(?<![\w/.])/home/(?!runner\b)[A-Za-z]"), None),
        ("e-mail", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}"), {"tools/at9enc/atrac9tab.h"}),
        ("open item", re.compile(j([r"\bTO", r"DO\b|\bFIX", r"ME\b|placehol", r"der|<own", r"er>|<re", r"po>|x", r"xxx"])),
         {"LICENSES/BSD-2-Clause.txt", "LICENSES/BSD-3-Clause.txt", "LICENSES/ISC.txt"}),  # SPDX texts keep their owner field
    ]


@check("privacy lint")
def t_lint():
    rules = lint_rules()
    hits = []
    for f in files():
        if f.endswith((".png", ".jpg", ".elf", ".ttf", ".bin")):
            continue
        text = read_text(f)
        if text is None:
            continue
        for label, rx, allow in rules:
            if allow and f in allow:
                continue
            for m in rx.finditer(text):
                hits.append("%s:%d %s: %s" % (f, text.count("\n", 0, m.start()) + 1, label, m.group(0)))
    assert not hits, "%d findings\n%s" % (len(hits), "\n".join(hits[:25]))
    return "%d files clean" % len(files())


# ----------------------------------------------------------------------------------------------- unit and host tests
@check("pc_import selftest")
def t_pc_import():
    p = run([PY, "installer/pc_import.py", "--selftest"], timeout=300)
    assert p.returncode == 0, tail(p)
    return tail(p, 1)


@check("gui unit tests")
def t_gui():
    p = run([PY, "tests/gui/test_core.py"], timeout=300)
    assert p.returncode == 0, tail(p)
    return tail(p, 1)


@check("qa pipeline unit tests")
def t_qa():
    for mod in ("numpy", "PIL"):
        try:
            __import__(mod)
        except ImportError:
            raise Skip("python module %s not installed" % mod)
    p = run([PY, "-m", "unittest", "discover", "-s", "tests", "-p", "test_qa_pipeline.py"], timeout=300)
    assert p.returncode == 0, tail(p)
    return tail(p, 1)


@check("onboarding page script")
def t_node():
    node = shutil.which("node")
    if not node:
        raise Skip("node not installed")
    p = run([node, "tests/test_onboarding_web.js"], timeout=120)
    assert p.returncode == 0 and "ok" in p.stdout, tail(p)
    return "node " + (run([node, "-v"]).stdout.strip() or "?")


@check("sync manifest offline")
def t_sync():
    man = json.loads(read_text("engine/ports/manifest.json"))
    lock = json.loads(read_text("engine/ports/upstream.lock"))
    assert re.fullmatch(r"[0-9a-f]{40}", lock["commit"]), "upstream.lock commit is not a sha"
    assert re.fullmatch(r"[0-9a-f]{64}", lock["patched_diff_sha256"]), "upstream.lock diff hash is not a sha256"
    ids, anchors = set(), set()
    for s in man["steps"]:
        assert s["id"] not in ids, "duplicate step " + s["id"]
        for r in s.get("requires", []):
            assert r in ids, "step %s requires %s, which does not come before it" % (s["id"], r)
        ids.add(s["id"])
        assert os.path.isfile(os.path.join(ROOT, "engine", s["path"])), "missing " + s["path"]
        touches = set(s.get("touches", []))
        for a in s.get("anchors", []):
            assert a["id"] not in anchors, "duplicate anchor " + a["id"]
            anchors.add(a["id"])
            assert a["kind"] in ("text", "function") and a["text"] and a["file"], "bad anchor %s in step %s" % (a["id"], s["id"])
            assert a["count"] == "any" or isinstance(a["count"], int), "bad count in anchor " + a["id"]
        for m in s.get("markers", []):
            assert m["file"] in touches, "marker file %s not in touches of %s" % (m["file"], s["id"])
    scripts = {f for f in os.listdir(os.path.join(ROOT, "engine")) if f.startswith("patch_") and f.endswith(".py") or f == "apply_ps5_patches.py"}
    assert scripts <= {s["path"] for s in man["steps"]}, "patch script without a manifest step: " + ", ".join(sorted(scripts - {s["path"] for s in man["steps"]}))
    p = run([PY, "engine/sync_upstream.py", "--help"], timeout=60)
    assert p.returncode == 0, tail(p)
    return "%d steps, %d anchors" % (len(man["steps"]), len(anchors))


@check("driver patch structure")
def t_driver():
    text = read_text("driver/ps5-opengl.patch")
    lines = text.split("\n")
    i, hunks, names = 0, 0, []
    while i < len(lines):
        l = lines[i]
        if l.startswith("+++ "):
            names.append(l.split()[1][2:])
        m = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", l)
        if m:
            old, new = int(m.group(1) or 1), int(m.group(2) or 1)
            hunks += 1
            i += 1
            while old > 0 or new > 0:
                c = lines[i][:1]
                if c == " " or lines[i] == "":
                    old, new = old - 1, new - 1
                elif c == "-":
                    old -= 1
                elif c == "+":
                    new -= 1
                elif c == "\\":
                    pass
                else:
                    raise AssertionError("hunk %d malformed at line %d" % (hunks, i + 1))
                i += 1
            continue
        i += 1
    assert len(names) == 6 and "src/gallium/ps5/ps5_screen.c" in names, names
    for s in ("drv_cc.sh", "drv_cc_cache.sh", "drv_cc_backend.sh", "drv_cc_egl.sh", "rc.txt", "setup.sh"):
        assert os.path.isfile(os.path.join(ROOT, "driver", "build", s)), "driver/build/" + s
    return "%d files, %d hunks" % (len(names), hunks)


def host_cpp(script, timeout=300):
    return linux_shell()(script, timeout)


@check("host c++: import progress")
def t_h_progress():
    p = host_cpp('T=$(mktemp -d) && g++ -std=c++17 -Wall -Iapp/shim tests/host/import_progress_test.cpp -o $T/t && $T/t; r=$?; rm -rf $T; exit $r')
    assert p.returncode == 0, tail(p)


@check("host c++: glfix conversion")
def t_h_glfix():
    p = host_cpp('T=$(mktemp -d) && g++ -std=c++17 -O1 tests/host/glfix_conv_test.cpp -o $T/t && $T/t; r=$?; rm -rf $T; exit $r')
    assert p.returncode == 0, tail(p)
    return tail(p, 1)


@check("host c++: QR encoder")
def t_h_qr():
    p = host_cpp('T=$(mktemp -d) && g++ -std=c++17 -O1 -Iapp/shim tests/host/qr_main.cpp app/shim/qr.cpp -o $T/t && $T/t "http://PS5_ADDRESS:8080"; r=$?; rm -rf $T; exit $r')
    assert p.returncode == 0, tail(p)
    rows = p.stdout.split()
    n = int(rows[0])
    m = rows[1:]
    assert len(m) == n and all(len(r) == n for r in m), "matrix is not square"
    finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
    for x, y in ((0, 0), (n - 7, 0), (0, n - 7)):
        assert [r[x:x + 7] for r in m[y:y + 7]] == finder, "finder pattern missing at %d,%d" % (x, y)
    return "%dx%d modules" % (n, n)


@check("host c++: web server")
def t_h_web():
    p = host_cpp("bash tests/host/webserver_host.sh", 300)
    assert p.returncode == 0, tail(p)
    for want in ("chunk0 204", "chunk1 204", "chunk2 204", "start 200"):
        assert want in p.stdout, "missing '%s' in the server dialogue\n%s" % (want, tail(p))


@check("host c++: install stream end to end")
def t_h_install():
    p = host_cpp("bash tests/host/install_host.sh", 600)
    assert p.returncode == 0, tail(p)
    return tail(p, 1)


# ----------------------------------------------------------------------------------------------- driver
def main(argv):
    if "--list" in argv:
        print("\n".join(n for n, _ in CHECKS))
        return 0
    keys = [argv[i + 1] for i, a in enumerate(argv) if a == "-k" and i + 1 < len(argv)]
    rows = []
    for name, fn in CHECKS:
        if keys and not any(k in name for k in keys):
            continue
        t0 = time.time()
        try:
            note = fn() or ""
            status = "PASS"
        except Skip as e:
            status, note = "SKIP", str(e)
        except subprocess.TimeoutExpired:
            status, note = "FAIL", "timed out"
        except Exception as e:  # a failing check must not stop the others
            status, note = "FAIL", str(e) or type(e).__name__
        rows.append((name, status, time.time() - t0, note))
        print("%-4s %-36s %6.1fs" % (status, name, rows[-1][2]), flush=True)
    print()
    print("%-38s %-5s %8s  %s" % ("check", "state", "time", "note"))
    print("-" * 100)
    for name, status, secs, note in rows:
        first, *more = (note.splitlines() or [""])
        print("%-38s %-5s %7.1fs  %s" % (name, status, secs, first[:120]))
        if status == "FAIL":
            for extra in more[:24]:
                print(" " * 54 + extra[:140])
    n = {s: sum(1 for r in rows if r[1] == s) for s in ("PASS", "FAIL", "SKIP")}
    print("-" * 100)
    print("%d passed, %d failed, %d skipped, %.1fs" % (n["PASS"], n["FAIL"], n["SKIP"], sum(r[2] for r in rows)))
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
