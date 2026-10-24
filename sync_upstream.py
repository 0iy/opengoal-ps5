#!/usr/bin/env python3
"""Pull the official OpenGOAL (open-goal/jak-project) and port it to the PS5 build, deterministically.

  status    pinned commit (ports/upstream.lock) vs upstream latest tag / HEAD, and which files we patch changed upstream
  preflight anchor check of every patch against the fetched upstream: OK / AUTO-RELOCATED / NEEDS-REVIEW / BROKEN (+JSON, changelog digest)
  fetch     clone/fetch upstream into <work>/upstream and check out --ref (default: the pinned commit), with submodules
  port      copy that checkout to <work>/port/home/jak and apply ports/manifest.json step by step; precise failure report
  verify    static checks of the ported tree (steps applied, markers, no leftovers, idempotent re-run); --compile optional
  snapshot  write the diff vs upstream in wsl_snapshot/ style (BASE_COMMIT, status, patch)
  all       fetch + port + verify + snapshot

Stdlib only. Never touches ~/jak, ~/gl, ~/ogapp (the work dir is refused if it overlaps them). See docs/UPSTREAM_SYNC.md.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "ports" / "upstream.lock"
MANIFEST = Path(os.environ.get("SYNC_MANIFEST") or ROOT / "ports" / "manifest.json")  # override only for tests
PROTECTED = ["jak", "gl", "ogapp", "drv", "ps5app", "ps5build", "ps5build_ext"]
GIT = ["git", "-c", "core.autocrlf=false", "-c", "advice.detachedHead=false", "-c", "protocol.file.allow=always"]


class Fail(Exception):
    pass


def run(cmd, cwd=None, env=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise Fail(f"command failed ({p.returncode}): {' '.join(map(str, cmd))}\n{p.stdout}{p.stderr}")
    return p


def git(args, cwd, check=True):
    return run(GIT + list(args), cwd=cwd, check=check)


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def work_dir(args):
    w = Path(args.work or os.environ.get("SYNC_WORK") or "~/sync_work").expanduser().resolve()
    home = Path.home().resolve()
    for name in PROTECTED:  # the live trees: refuse to work in, under or around them
        live = home / name
        if w == live or live in w.parents or w in live.parents:
            raise Fail(f"refusing work dir {w}: overlaps the live tree {live}")
    w.mkdir(parents=True, exist_ok=True)
    return w


def sha256(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------------------------- status
def remote_info(repo):
    out = run(["git", "ls-remote", repo, "HEAD", "refs/tags/*"]).stdout.splitlines()
    head, tags = None, {}
    for ln in out:
        sha, ref = ln.split("\t")
        if ref == "HEAD":
            head = sha
        elif ref.startswith("refs/tags/"):
            name = ref[len("refs/tags/"):]
            peeled = name.endswith("^{}")
            name = name[:-3] if peeled else name
            if peeled or name not in tags:  # peeled entry = the commit an annotated tag points to
                tags[name] = sha
    return head, tags


def tag_key(t):
    return [int(x) for x in re.findall(r"\d+", t)]


def latest_tag(tags):
    vt = [t for t in tags if re.fullmatch(r"v?\d+(\.\d+)+", t)]
    return max(vt, key=tag_key) if vt else None


def cmd_status(args):
    lock, man = load_json(LOCK), load_json(MANIFEST)
    pinned = lock["commit"]
    head, tags = remote_info(lock["repo"])
    lt = latest_tag(tags)
    pinned_tags = [t for t, s in tags.items() if s == pinned]
    print(f"repo            {lock['repo']}")
    print(f"pinned          {pinned}  tags: {', '.join(pinned_tags) or 'none (between releases)'}")
    print(f"upstream HEAD   {head}  {'== pinned' if head == pinned else 'differs'}")
    print(f"latest tag      {lt}  {tags.get(lt)}  {'== pinned' if tags.get(lt) == pinned else ''}")
    up = work_dir(args) / "upstream"
    if not (up / ".git").exists():
        print("no local clone yet: run `fetch` for ahead counts and the list of patched files that changed upstream")
        return 0
    if not args.offline:
        git(["fetch", "--tags", "--prune", "-q", "origin"], up)
    have = lambda s: git(["cat-file", "-e", f"{s}^{{commit}}"], up, check=False).returncode == 0
    for label, sha in (("HEAD", head), (f"tag {lt}", tags.get(lt))):
        if not sha or not have(sha):
            print(f"{label}: not in local clone (fetch first)")
            continue
        n = git(["rev-list", "--count", f"{pinned}..{sha}"], up).stdout.strip()
        anc = git(["merge-base", "--is-ancestor", pinned, sha], up, check=False).returncode == 0
        files = sorted({f for s in man["steps"] for f in s.get("touches", [])})
        ch = git(["diff", "--name-only", pinned, sha, "--"] + files, up).stdout.split()
        print(f"{label}: {n} commit(s) ahead of pinned{'' if anc else ' (pinned is NOT an ancestor)'}; "
              f"{len(ch)} of {len(files)} files we patch changed upstream" + (":" if ch else ""))
        for f in ch:
            print(f"    {f}")
    return 0


# --------------------------------------------------------------------------------------------- fetch
def resolve_ref(up, ref, lock, repo_tags):
    if ref in (None, "pinned"):
        ref = lock["commit"]
    elif ref == "head":
        ref = "origin/HEAD"
    elif ref == "latest-tag":
        ref = latest_tag(repo_tags)
        if not ref:
            raise Fail("no version tag found upstream")
        ref = f"refs/tags/{ref}"
    for cand in (ref, f"origin/{ref}", f"refs/tags/{ref}"):
        p = git(["rev-parse", "--verify", "-q", f"{cand}^{{commit}}"], up, check=False)
        if p.returncode == 0:
            return p.stdout.strip()
    raise Fail(f"cannot resolve ref {ref!r} in {up}")


def cmd_fetch(args):
    lock = load_json(LOCK)
    w = work_dir(args)
    up = w / "upstream"
    if not (up / ".git").exists():
        print(f"cloning {lock['repo']} -> {up} (blobless)")
        run(GIT + ["clone", "--filter=blob:none", "--no-checkout", lock["repo"], str(up)])
    else:
        print("fetching")
        git(["fetch", "--tags", "--prune", "-q", "origin"], up)
    _, tags = remote_info(lock["repo"]) if args.ref == "latest-tag" else (None, {})
    sha = resolve_ref(up, args.ref, lock, tags)
    print(f"checkout {sha} (ref {args.ref or 'pinned'})")
    git(["checkout", "--force", "--detach", sha], up)
    git(["clean", "-fdq"], up)
    sub = not args.no_submodules
    if sub:
        git(["submodule", "sync", "--recursive", "-q"], up)
        git(["submodule", "update", "--init", "--recursive", "--force", "-q"], up)
    (w / "fetch.json").write_text(json.dumps({"ref": args.ref or "pinned", "commit": sha, "submodules": sub,
                                              "time": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    print(f"fetched {sha}" + ("" if sub else " (no submodules)"))
    return 0


# --------------------------------------------------------------------------------------------- preflight
RANK = {"OK": 0, "AUTO-RELOCATED": 1, "NEEDS-REVIEW": 2, "BROKEN": 3}


def nl(b):
    return b.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")  # scripts read in text mode: CRLF -> LF


def read_rev(up, rev, rel):
    p = subprocess.run(GIT + ["show", f"{rev}:{rel}"], cwd=up, capture_output=True)
    return nl(p.stdout) if p.returncode == 0 else None


def positions(text, needle):
    out, i = [], text.find(needle)
    while i >= 0:
        out.append(text.count("\n", 0, i) + 1)
        i = text.find(needle, i + 1)
    return out


def fuzzy_window(text, anchor):
    """Best-matching window of `text` for a (multi-line) anchor: (ratio, start_line, window_text) or None."""
    import difflib
    L, A = text.split("\n"), anchor.rstrip("\n").split("\n")
    n = len(A)
    stripped = {}
    for i, l in enumerate(L):
        stripped.setdefault(l.strip(), []).append(i)
    keys = list(stripped)
    cand = set()
    for off, a in enumerate(A):
        a = a.strip()
        if len(a) < 5:
            continue
        for m in difflib.get_close_matches(a, keys, n=4, cutoff=0.72):
            for i in stripped[m]:
                for d in (-1, 0, 1):
                    cand.add(max(0, i - off + d))
        if len(cand) > 400:
            break
    best = None
    for s in sorted(cand):
        for size in range(max(1, n - 2), n + 3):
            w = "\n".join(L[s:s + size])
            if not w:
                continue
            sm = difflib.SequenceMatcher(None, w, anchor.rstrip("\n"), autojunk=False)
            if sm.real_quick_ratio() < 0.5 or sm.quick_ratio() < 0.5:
                continue
            r = sm.ratio()
            if best is None or r > best[0]:
                best = (r, s + 1, w)
    return best


def side_by_side(old, new, width=54):
    import difflib
    a, b = old.rstrip("\n").split("\n"), new.rstrip("\n").split("\n")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        for k in range(max(i2 - i1, j2 - j1)):
            l = a[i1 + k] if i1 + k < i2 else ""
            r = b[j1 + k] if j1 + k < j2 else ""
            out.append(f"{'  ' if tag == 'equal' else '!='} {l[:width]:<{width}} | {r[:width]}")
    return out


def first_line(a):
    return next((l.strip() for l in a["text"].split("\n") if len(l.strip()) > 6), a["text"].strip())


def pickaxe(up, base, target, rel, a):
    """Upstream commits that touched the anchor: -S on its first line, -L on the function, else the file log."""
    fmt = ["--format=@@C %h %ad %an: %s", "--date=short"]
    pull = lambda p: [l[4:] for l in p.stdout.splitlines() if l.startswith("@@C ")]
    res = pull(git(["log"] + fmt + [f"-S{first_line(a)}", f"{base}..{target}", "--", rel], up, check=False))
    if a.get("name"):
        res += pull(git(["log"] + fmt + [f"-L:{a['name']}:{rel}", f"{base}..{target}", "-s"], up, check=False))
    if not res:
        res = [c + "  (file history; no commit changed this exact text)"
               for c in pull(git(["log"] + fmt + [f"{base}..{target}", "--", rel], up, check=False))]
    return list(dict.fromkeys(res))[:8]


def eval_anchor(up, base, target, a, renames):
    """Status of one anchor on the new upstream: found | moved | changed | gone | inactive (+ detail)."""
    want = a.get("count", 1)
    ok_count = (lambda n: n >= 1) if want == "any" else (lambda n: n == want)
    rel = a["file"]
    res = {"id": a["id"], "file": rel, "kind": a["kind"], "expected": want, "text": a["text"]}
    old_txt = read_rev(up, base, rel)
    base_pos = positions(old_txt, a["text"]) if old_txt is not None else []
    res["pinned_lines"] = base_pos[:5]
    if not base_pos:
        res.update(status="inactive", manifest_error=want != "any",
                   detail="anchor is not present at the pinned commit (manifest error, or an 'any' anchor that never applied)")
        return res
    new_rel = renames.get(rel, rel)
    new_txt = read_rev(up, target, new_rel)
    if new_txt is not None:
        pos = positions(new_txt, a["text"])
        if ok_count(len(pos)):
            res.update(status="found" if new_rel == rel else "moved", file_new=new_rel, lines=pos[:5],
                       detail=f"renamed upstream {rel} -> {new_rel}" if new_rel != rel else
                       ("line shift %+d" % (pos[0] - base_pos[0]) if pos[0] != base_pos[0] else "same place"))
            return res
    # not in the expected file. A near-identical window in the same file means "edited in place"; otherwise look for the
    # whole text in other files (moved); only then fall back to a weaker fuzzy match (changed) or give up (gone).
    best = fuzzy_window(new_txt, a["text"]) if new_txt is not None else None
    n_now = len(positions(new_txt, a["text"])) if new_txt is not None else 0

    def changed(why):
        r = dict(status="changed", detail=why, upstream_commits=pickaxe(up, base, target, new_rel, a))
        if best and best[0] >= 0.6:
            r.update(ratio=round(best[0], 3), lines=[best[1]], old_snippet=a["text"], new_snippet=best[2],
                     suggested_anchor=best[2], side_by_side=side_by_side(a["text"], best[2]),
                     detail=f"{why}; fuzzy match, difflib ratio {best[0]:.2f}, at line {best[1]}")
        return r

    if n_now:
        res.update(changed(f"text still present but {n_now} match(es) instead of {want}"))
        return res
    if best and best[0] >= 0.9:
        res.update(changed("edited in place"))
        return res
    cands = []
    if len(a["text"].strip()) >= 30 or chr(10) in a["text"].strip():  # a short one-liner is not a usable move signature
        for hit in git(["grep", "-l", "-F", "-e", first_line(a), target], up, check=False).stdout.split():
            path = hit.split(":", 1)[1]
            t = read_rev(up, target, path) if path != new_rel else None
            if t is not None and ok_count(len(positions(t, a["text"]))):
                cands.append((path, positions(t, a["text"])[:5]))
    if len(cands) == 1:
        res.update(status="moved", file_new=cands[0][0], lines=cands[0][1], detail=f"same text now in {cands[0][0]}")
        return res
    if len(cands) > 1:
        res.update(changed("text now appears in several files (ambiguous): " + ", ".join(c[0] for c in cands[:6])))
        return res
    if best and best[0] >= 0.6:
        res.update(changed("edited"))
        return res
    res.update(status="gone", ratio=round(best[0], 3) if best else 0.0, upstream_commits=pickaxe(up, base, target, new_rel, a),
               detail=(f"file {rel} no longer exists upstream" if new_txt is None else "no similar text left in the file")
               + (f" (best ratio {best[0]:.2f})" if best else ""))
    return res


def classify(anchors):
    """OK / AUTO-RELOCATED / NEEDS-REVIEW / BROKEN for one step, plus the file map to apply it with.
    A line shift inside the same file is OK: the scripts match on text, not on line numbers."""
    cls, fmap = "OK", {}
    for r in anchors:
        s, c = r["status"], "OK"
        if r.get("manifest_error"):
            c = "BROKEN"
        elif s == "moved" and r["file_new"] != r["file"]:
            c = "AUTO-RELOCATED"
            if fmap.get(r["file"], r["file_new"]) != r["file_new"]:
                c = "NEEDS-REVIEW"  # anchors of one file landed in different files
                r["detail"] += " (conflicts with another anchor of the same file)"
            fmap[r["file"]] = r["file_new"]
        elif s == "changed":
            c = "NEEDS-REVIEW"
        elif s == "gone":
            c = "BROKEN"
        r["class"] = c
        if RANK[c] > RANK[cls]:
            cls = c
    return cls, fmap


def digest(up, base, target, files):
    p = git(["log", "--format=@@C %h|%ad|%an|%s", "--date=short", "--name-only", f"{base}..{target}", "--"] + sorted(files), up, check=False)
    out, cur = [], None
    for l in p.stdout.splitlines():
        if l.startswith("@@C "):
            h, d, an, s = l[4:].split("|", 3)
            cur = {"commit": h, "date": d, "author": an, "subject": s, "files": []}
            out.append(cur)
        elif l.strip() and cur is not None and l in files:
            cur["files"].append(l)
    return out


def run_preflight(w, man, lock, fj):
    up = w / "upstream"
    base, target = lock["commit"], fj["commit"]
    renames = {}
    for l in git(["diff", "-M", "--name-status", base, target], up, check=False).stdout.splitlines():
        parts = l.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            renames[parts[1]] = parts[2]
    steps = []
    for st in man["steps"]:
        anchors = [eval_anchor(up, base, target, a, renames) for a in st.get("anchors", [])]
        cls, fmap = classify(anchors)
        if st["kind"] == "patch" and fmap:  # a .patch has its paths baked in: relocation needs a human
            cls = max(cls, "NEEDS-REVIEW", key=RANK.get)
        steps.append({"id": st["id"], "required": st.get("required", True), "class": cls, "file_map": fmap, "anchors": anchors})
    byid = {x["id"]: x for x in steps}
    for st in man["steps"]:  # a step is only as good as the steps it builds on
        for dep in st.get("requires", []):
            if RANK[byid[dep]["class"]] > RANK[byid[st["id"]]["class"]]:
                byid[st["id"]]["class"] = byid[dep]["class"]
                byid[st["id"]]["note"] = f"depends on {dep} ({byid[dep]['class']})"
    files = {a["file"] for st in man["steps"] for a in st.get("anchors", [])} | {f for st in man["steps"] for f in st.get("touches", [])}
    return {"pinned": base, "target": target, "steps": steps, "digest": digest(up, base, target, files),
            "overall": max((s["class"] for s in steps), key=RANK.get, default="OK")}


def print_preflight(rep):
    print(f"PRE-FLIGHT pinned {rep['pinned'][:7]} -> upstream {rep['target'][:7]}")
    for s in rep["steps"]:
        n = {}
        for a in s["anchors"]:
            n[a["status"]] = n.get(a["status"], 0) + 1
        print(f"  {s['class']:15} {s['id']:9} {'required' if s['required'] else 'optional'}  anchors: " + ", ".join(f"{v} {k}" for k, v in sorted(n.items())))
        if s["file_map"]:
            print(f"      relocated files: {s['file_map']}")
        for a in s["anchors"]:
            if a["status"] == "inactive" and not a.get("manifest_error"):
                continue
            if a["status"] == "found" or (a["status"] == "moved" and a["file_new"] == a["file"]):
                continue
            print(f"    - [{a['status'].upper()}] {a['id']} {a['file']}: {a.get('detail', '')}")
            for l in a.get("side_by_side", [])[:30]:
                print("        " + l)
            if a.get("suggested_anchor"):
                print("        suggested updated anchor: the right-hand column above")
            for c in a.get("upstream_commits", [])[:5]:
                print(f"        upstream: {c}")
    d = rep["digest"]
    print(f"CHANGELOG DIGEST: {len(d)} upstream commit(s) since the pinned commit touch files we patch" + (":" if d else ""))
    for c in d[:20]:
        print(f"  {c['commit']} {c['date']} {c['subject'][:80]}  [{', '.join(Path(f).name for f in c['files'])}]")
    if len(d) > 20:
        print(f"  ... {len(d) - 20} more (see the JSON report)")
    print(f"PRE-FLIGHT RESULT: {rep['overall']}")


def cmd_preflight(args):
    w = work_dir(args)
    if not (w / "fetch.json").exists():
        raise Fail("run `fetch` first")
    rep = run_preflight(w, load_json(MANIFEST), load_json(LOCK), load_json(w / "fetch.json"))
    jp = Path(args.json) if args.json else w / "preflight.json"
    jp.write_text(json.dumps(rep, indent=1))
    print_preflight(rep)
    print(f"JSON report: {jp}")
    return 3 if RANK[rep["overall"]] >= RANK["NEEDS-REVIEW"] else 0


# --------------------------------------------------------------------------------------------- port
def fake_env(home, tree):
    env = dict(os.environ)
    env.update(HOME=str(home), USERPROFILE=str(home), JAK_ROOT=str(tree), PYTHONDONTWRITEBYTECODE="1")
    return env


def commit_all(tree, msg):
    git(["add", "-A"], tree)
    git(["-c", "user.name=sync_upstream", "-c", "user.email=sync@localhost", "commit", "-q", "--no-verify", "-m", msg], tree)


def revert(tree):
    git(["reset", "--hard", "-q"], tree)
    git(["clean", "-fdq"], tree)


def explain_failure(step, out, tree, base, target, up):
    """Say which patch failed against which upstream file and lines, and what changed upstream there."""
    lines = []
    files = []
    for m in re.finditer(r"PATCH FAILED (\S+?):\s*(.*)", out):
        files.append(m.group(1))
        lines.append(f"  anchor not found in {m.group(1)}: {m.group(2)}")
    for m in re.finditer(r"error: patch failed: (\S+?):(\d+)", out):
        files.append(m.group(1))
        lines.append(f"  hunk does not apply: {m.group(1)} near line {m.group(2)}")
    for m in re.finditer(r"error: (\S+?): patch does not apply", out):
        files.append(m.group(1))
    tb = re.findall(r'File "([^"]+)", line (\d+), in (\S+)\n\s*(.*)', out)
    if tb:
        f, n, fn, src = tb[-1]
        err = out.strip().splitlines()[-1]
        lines.append(f"  script {Path(f).name} line {n} ({fn}): {src}   -> {err}")
        sp = ROOT / step["path"]
        if sp.exists() and Path(f).name == sp.name:  # show the anchor definition just above the assert
            src_lines = sp.read_text(encoding="utf-8", errors="replace").splitlines()
            for k in range(max(0, int(n) - 12), int(n)):
                if re.match(r"\s*(old|new|inc)\s*=", src_lines[k]):
                    lines.append(f"    script line {k + 1}: {src_lines[k].strip()[:160]}")
    if not files:
        files = list(step.get("touches", []))
    files = list(dict.fromkeys(files))
    for f in files:
        lines.append(f"  upstream history of {f}  ({base[:7]}..{target[:7]}):")
        log = git(["log", "--format=    %h %ad %s", "--date=short", f"{base}..{target}", "--", f], up, check=False).stdout
        lines.append(log.rstrip() or "    (no upstream commit touched this file: the anchor was already different at the pinned base, or the script is stale)")
        hunks = [h for h in git(["diff", "-U0", base, target, "--", f], up, check=False).stdout.splitlines() if h.startswith("@@")]
        if hunks:
            lines.append(f"    changed upstream line ranges (old->new): " + "  ".join(h.split("@@")[1].strip() for h in hunks[:12]) + (" ..." if len(hunks) > 12 else ""))
    lines.append(f"  fix: edit {step['path']} (anchor text) against upstream {target[:7]}, then re-run `port`; see docs/UPSTREAM_SYNC.md")
    return "\n".join(lines)


def cmd_port(args):
    w = work_dir(args)
    man, lock = load_json(MANIFEST), load_json(LOCK)
    if not (w / "fetch.json").exists():
        raise Fail("run `fetch` first")
    fj = load_json(w / "fetch.json")
    up = w / "upstream"
    base = fj["commit"]
    if git(["rev-parse", "HEAD"], up).stdout.strip() != base:
        raise Fail("upstream checkout moved since fetch; run `fetch` again")
    pdir = w / "port"
    if pdir.exists():
        shutil.rmtree(pdir)
    rep = run_preflight(w, man, lock, fj)  # decide everything BEFORE a single byte is written
    pdir.mkdir(parents=True)
    (pdir / "preflight.json").write_text(json.dumps(rep, indent=1))
    print_preflight(rep)
    pf = {s["id"]: s for s in rep["steps"]}
    blocked = [s["id"] for s in rep["steps"] if RANK[s["class"]] >= RANK["NEEDS-REVIEW"] and s["required"]]
    if blocked:
        print(f"{chr(10)}PORT ABORTED before applying anything: required step(s) {', '.join(blocked)} need review (report: {pdir / 'preflight.json'})")
        (pdir / "state.json").write_text(json.dumps({"complete": False, "base": fj["commit"], "preflight": rep["overall"]}, indent=1))
        return 3
    home = pdir / "home"
    tree = home / "jak"
    home.mkdir(parents=True)
    print(f"copying upstream {base[:7]} -> {tree}")
    shutil.copytree(up, tree, symlinks=True)
    if git(["status", "--porcelain", "--ignore-submodules"], tree).stdout.strip():
        raise Fail("fresh copy is not clean")
    only = set(args.only.split(",")) if args.only else None
    skip = set(args.skip.split(",")) if args.skip else set()
    env = fake_env(home, tree)
    state = {"base": base, "ref": fj["ref"], "pinned": lock["commit"], "steps": [], "complete": False,
             "preflight": rep["overall"], "file_map": {}, "relocations": []}
    failed_required = None
    for step in man["steps"]:
        sid = step["id"]
        if (only and sid not in only) or sid in skip or step.get("enabled", True) is False:
            state["steps"].append({"id": sid, "status": "skipped"})
            continue
        if RANK[pf[sid]["class"]] >= RANK["NEEDS-REVIEW"]:  # optional step that needs review: not applied, tree stays consistent
            print(f"[REVIEW   ] {sid}: optional step NOT applied ({pf[sid]['class']}), see report")
            state["steps"].append({"id": sid, "status": "needs-review", "required": False, "class": pf[sid]["class"]})
            continue
        bad_dep = [d for d in step.get("requires", []) if next((x["status"] for x in state["steps"] if x["id"] == d), "") != "ok"]
        if bad_dep:
            print(f"[SKIPPED  ] {sid}: requires {', '.join(bad_dep)} which was not applied")
            state["steps"].append({"id": sid, "status": "skipped", "required": step.get("required", True), "reason": "requires " + ",".join(bad_dep)})
            continue
        fmap = pf[sid]["file_map"]
        if fmap:
            state["file_map"].update(fmap)
            state["relocations"].append({"step": sid, "map": fmap})
            print(f"[RELOCATE ] {sid}: applying with file map {fmap}")
        env["SYNC_FILE_MAP"] = json.dumps(fmap)
        src = ROOT / step["path"]
        if not src.exists():
            raise Fail(f"manifest step {sid}: {src} missing")
        if step["kind"] == "script":
            p = run([sys.executable, str(src)] + step.get("args", []), cwd=tree, env=env, check=False)
        elif step["kind"] == "patch":
            p = run(GIT + ["apply", "--check", "-p1", str(src)], cwd=tree, check=False)
            if p.returncode == 0:
                p = run(GIT + ["apply", "-p1", "--whitespace=nowarn", str(src)], cwd=tree, check=False)
        else:
            raise Fail(f"step {sid}: unknown kind {step['kind']}")
        out = (p.stdout or "") + (p.stderr or "")
        changed = git(["status", "--porcelain", "--ignore-submodules"], tree).stdout.strip()
        status = "ok" if p.returncode == 0 and changed else ("no-change" if p.returncode == 0 else "failed")
        req = step.get("required", True)
        entry = {"id": sid, "status": status, "required": req, "rc": p.returncode, "files": len(changed.splitlines())}
        print(f"[{status.upper():9}] {sid}: {step['path']}  ({'required' if req else 'optional'})")
        if status == "ok":
            commit_all(tree, f"ps5-port: {sid}")
        else:
            revert(tree)
            why = explain_failure(step, out, tree, lock["commit"], base, up) if status == "failed" else \
                "  the step ran but changed nothing (already patched upstream, or the script found no work)"
            print(f"  --- {sid} {'FAILED' if status == 'failed' else 'changed nothing'} against upstream {base[:7]}\n{why}")
            print("  script output:\n" + "\n".join("    " + x for x in out.strip().splitlines()[-15:]))
            entry["report"] = why
            if req:
                failed_required = sid
                state["steps"].append(entry)
                break
        state["steps"].append(entry)
    if failed_required:
        shutil.rmtree(tree)  # never leave a half-patched tree
        (pdir / "state.json").write_text(json.dumps(state, indent=1))
        print(f"\nPORT FAILED at required step {failed_required}; no tree kept (state: {pdir / 'state.json'})")
        return 1
    diff = git(["diff", "--full-index", base, "HEAD"], tree).stdout
    state.update(complete=True, tree=str(tree), diff_sha256=sha256(diff),
                 changed=git(["diff", "--name-only", base, "HEAD"], tree).stdout.split())
    (pdir / "state.json").write_text(json.dumps(state, indent=1))
    warn = [s["id"] for s in state["steps"] if s["status"] in ("failed", "no-change")]
    print(f"\nPORT OK: {len(state['changed'])} files changed, diff sha256 {state['diff_sha256'][:16]}"
          + (f", WARNINGS in optional steps: {', '.join(warn)}" if warn else ""))
    print(f"tree: {tree}")
    review = [s["id"] for s in state["steps"] if s["status"] == "needs-review"]
    if review:
        print(f"NEEDS REVIEW (optional steps not applied): {', '.join(review)}")
    return 3 if review else (2 if (warn and args.strict) else 0)


# --------------------------------------------------------------------------------------------- verify
def port_state(w):
    sp = w / "port" / "state.json"
    if not sp.exists():
        raise Fail("run `port` first")
    st = load_json(sp)
    if not st.get("complete"):
        raise Fail("last port did not complete; there is no tree (see port/state.json)")
    return st, Path(st["tree"])


def cmd_verify(args):
    w = work_dir(args)
    man = load_json(MANIFEST)
    st, tree = port_state(w)
    base = st["base"]
    res = []

    def check(name, ok, detail=""):
        res.append((ok, name, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))

    by_id = {s["id"]: s for s in st["steps"]}
    fm = st.get("file_map", {})
    mp = lambda f: fm.get(f, f)
    for step in man["steps"]:
        s = by_id.get(step["id"], {"status": "missing"})
        req = step.get("required", True)
        check(f"step {step['id']} applied" + ("" if req else " (optional)"), s["status"] == "ok" or not req, s["status"])
    changed = set(st["changed"])
    known = {mp(f) for s in man["steps"] if by_id.get(s["id"], {}).get("status") == "ok" for f in s.get("touches", [])}
    check("no unexpected changed files", changed <= known, ", ".join(sorted(changed - known)))
    check("every file a step touches changed", known <= changed, ", ".join(sorted(known - changed)))
    miss = []
    for step in man["steps"]:
        if by_id.get(step["id"], {}).get("status") != "ok":
            continue
        for m in step.get("markers", []):
            if m["text"] not in (tree / mp(m["file"])).read_text(encoding="utf-8", errors="replace"):
                miss.append(f"{step['id']}:{m['file']}:{m['text']!r}")
        for f in map(mp, step.get("touches", [])):
            if "__ps5__" not in (tree / f).read_text(encoding="utf-8", errors="replace"):
                miss.append(f"{step['id']}:{f}: no __ps5__ marker")
    check("markers present", not miss, "; ".join(miss))
    stray = [str(p.relative_to(tree)) for pat in ("*.rej", "*.orig") for p in tree.rglob(pat) if ".git" not in p.parts]
    check("no .rej/.orig leftovers", not stray, ", ".join(stray))
    added = [l[1:] for l in git(["diff", "-U0", base, "HEAD"], tree).stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]
    bad = sorted({pat for pat in man.get("forbidden_in_added_lines", []) for l in added if pat in l})
    check("no leftover debug/conflict markers in added lines", not bad, ", ".join(bad))
    check("tree clean (everything committed by port)", not git(["status", "--porcelain", "--ignore-submodules"], tree).stdout.strip())
    # idempotence: re-running every applied script on the patched tree must change nothing
    env = fake_env(tree.parent, tree)
    dirty = []
    for step in man["steps"]:
        if step["kind"] != "script" or by_id.get(step["id"], {}).get("status") != "ok":
            continue
        env["SYNC_FILE_MAP"] = json.dumps(fm)
        p = run([sys.executable, str(ROOT / step["path"])] + step.get("args", []), cwd=tree, env=env, check=False)
        if git(["status", "--porcelain", "--ignore-submodules"], tree).stdout.strip() or p.returncode != 0:
            dirty.append(step["id"])
        revert(tree)
    check("scripts idempotent on the patched tree", not dirty, ", ".join(dirty))
    if args.compile:
        cc = ROOT / "compile_check.sh"
        real = Path(os.environ.get("REAL_HOME", Path.home()))
        for name in ("ps5app",):  # read-only SDK wrapper; compile_check.sh writes only to <fake home>/jak_check2
            link = tree.parent / name
            if not link.exists() and (real / name).exists():
                link.symlink_to(real / name)
        files = [f for f in sorted(changed) if f.endswith(".cpp")]
        p = run(["bash", str(cc)] + files, cwd=tree, env=env, check=False)
        check("syntax-only compile of changed .cpp files (compile_check.sh)", "bad=0" in p.stdout, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:])
    ok = all(r[0] for r in res)
    print("VERIFY " + ("OK" if ok else "FAILED") + ("" if args.compile else "  (static checks only; --compile not run)"))
    return 0 if ok else 1


# --------------------------------------------------------------------------------------------- snapshot
def norm_patch(text):
    return "\n".join(l for l in text.splitlines() if not l.startswith("index "))


def cmd_snapshot(args):
    w = work_dir(args)
    st, tree = port_state(w)
    base = st["base"]
    out = Path(args.out).expanduser() if args.out else (ROOT / "wsl_snapshot" if args.to_repo else w / "snapshot")
    out.mkdir(parents=True, exist_ok=True)
    patch = git(["diff", "--abbrev=8", base, "HEAD"], tree).stdout
    (out / f"jak-project_vs_{base[:7]}.patch").write_text(patch, encoding="utf-8", newline="\n")
    (out / "jak-project_BASE_COMMIT.txt").write_text(base + "\n")
    stat = "".join(f" M {f}\n" for f in sorted(st["changed"]))
    (out / "jak-project_status.txt").write_text(stat)
    print(f"wrote {out}/jak-project_vs_{base[:7]}.patch ({len(st['changed'])} files), BASE_COMMIT, status")
    if args.compare:
        a, b = norm_patch(Path(args.compare).read_text(encoding="utf-8", errors="replace")), norm_patch(patch)
        if a == b:
            print(f"COMPARE {args.compare}: IDENTICAL (ignoring 'index' lines)")
        else:
            import difflib
            d = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "committed", "ported", lineterm="", n=0))
            print(f"COMPARE {args.compare}: DIFFERENT, {len(d)} diff lines (first 40):\n" + "\n".join(d[:40]))
            return 1
    if args.update_lock:
        lock = load_json(LOCK)
        if st["ref"] != "pinned":
            lock["commit"] = base
        lock["patched_diff_sha256"] = st["diff_sha256"]
        LOCK.write_text(json.dumps(lock, indent=2) + "\n")
        print(f"updated {LOCK.name}: commit {lock['commit'][:7]}, patched_diff_sha256 {st['diff_sha256'][:16]}")
    else:
        lock = load_json(LOCK)
        exp = lock.get("patched_diff_sha256")
        if exp and base == lock["commit"]:
            ok = exp == st["diff_sha256"]
            print(f"determinism vs lock: {'MATCH' if ok else 'MISMATCH'} ({st['diff_sha256'][:16]} vs {exp[:16]})")
            return 0 if ok else 1
    return 0


def cmd_all(args):
    for fn in (cmd_fetch, cmd_port, cmd_verify, cmd_snapshot):  # port runs the pre-flight itself
        rc = fn(args)
        if rc:
            return rc
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", help="work dir (default $SYNC_WORK or ~/sync_work)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ref", help="pinned (default) | head | latest-tag | tag | branch | sha")
    common.add_argument("--no-submodules", action="store_true")
    common.add_argument("--only", help="comma list of step ids")
    common.add_argument("--skip", help="comma list of step ids")
    common.add_argument("--strict", action="store_true", help="exit 2 when an optional step failed")
    common.add_argument("--compile", action="store_true", help="verify: also syntax-compile changed files (needs ~/ps5app)")
    common.add_argument("--out"); common.add_argument("--to-repo", action="store_true", help="snapshot: write into wsl_snapshot/")
    common.add_argument("--compare", help="snapshot: compare with this patch file")
    common.add_argument("--update-lock", action="store_true")
    common.add_argument("--json", help="preflight: path of the JSON report (default <work>/preflight.json)")
    common.add_argument("--offline", action="store_true", help="status: do not fetch the local clone")
    for n, f in (("status", cmd_status), ("fetch", cmd_fetch), ("preflight", cmd_preflight), ("port", cmd_port), ("verify", cmd_verify),
                 ("snapshot", cmd_snapshot), ("all", cmd_all)):
        sp = sub.add_parser(n, parents=[common])
        sp.set_defaults(fn=f)
    a = ap.parse_args()
    try:
        return a.fn(a)
    except Fail as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
