#!/usr/bin/env python3
"""qa_pipeline.py: deterministic quality gate for OpenGOAL-PS5 (run after every upstream sync or patch change). See docs/QA_PIPELINE.md.

  python qa_pipeline.py --quick                      # 30 s per game (jak3: rplay fixed cost), compare against qa/baseline.json
  python qa_pipeline.py --full --build --deploy      # build (WSL), kill + deploy, then 90/190 s scenarios with the driver trace
  python qa_pipeline.py --full --update-baseline     # collect twice (A, A2), write baseline, golden shots and the learned noise masks
  python qa_pipeline.py --analyze qa/runs/<stamp>    # offline: analyse an existing run directory (no console access at all)

Collect phase = subprocesses (ps5.py, perfround.py, shotseries, trace2json.py), each with a timeout; the app is killed in a finally.
Analyse phase = pure python on the files in a run directory. Exit code: 0 PASS, 1 WARN, 2 FAIL, 3 pipeline error."""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shotdiff  # noqa: E402  (regions, diff_image)

LEVELS = {"PASS": 0, "WARN": 1, "FAIL": 2}
GAMES = ["jak1", "jak2", "jak3"]


def _s(name, t):
    return {"name": name, "t": t}


# secs = wall seconds of the run; shots = fixed seconds after (game) process start; warm = fraction of 3 s samples skipped as warm-up.
# jak3 is driven by rplay.py (new process on Play), so its shot times are relative to the game process: adjust in qa/scenarios.json.
SCENARIOS = {
    "quick": {
        "jak1": {"secs": 30, "warm": 0.4, "shots": [_s("boot", 6), _s("title", 14), _s("play", 26)]},
        "jak2": {"secs": 30, "warm": 0.4, "shots": [_s("boot", 6), _s("title", 14), _s("play", 26)]},
        "jak3": {"secs": 60, "warm": 0.4, "shots": [_s("boot", 10), _s("menu", 30), _s("late", 50)]},
    },
    "full": {
        "jak1": {"secs": 90, "warm": 0.45, "shots": [_s("boot", 8), _s("title", 20), _s("spawn", 40), _s("play", 60), _s("play2", 80)]},
        "jak2": {"secs": 90, "warm": 0.45, "shots": [_s("boot", 8), _s("title", 20), _s("city", 45), _s("play", 60), _s("play2", 80)]},
        "jak3": {"secs": 190, "warm": 0.55, "shots": [_s("boot", 10), _s("menu", 30), _s("spawn", 60), _s("play", 100), _s("play2", 130)]},
    },
}

# fractions are relative (0.05 = 5 %); *_warn/_fail pairs. Raised automatically by the learned noise (fps_noise_k * measured A-vs-A2).
TOL = {
    "fps_warn": 0.05, "fps_fail": 0.10, "fps_noise_k": 3.0,
    "p1_warn": 0.15, "p1_fail": 0.30,
    "over33_warn": 1.0, "over33_fail": 3.0,      # absolute increase of frames >33 ms per 3 s window
    "over20_warn": 2.0, "over20_fail": 6.0,
    "drv_warn": 0.10, "drv_fail": 0.25,          # driver ms/frame and us/draw from the trace
    "min_fps_samples": 0.5,                      # fraction of the expected secs/3 samples; below = silent exit
    "shot_thresh": 16,                           # max channel difference counted as differing
    "shot_pct_warn": 0.5, "shot_pct_fail": 8.0,  # percent of pixels outside the noise mask
    "region_warn_px": 300, "region_fail_px": 6000,
    "unstable_pct": 5.0,                         # A-vs-A2 raw difference above this: scene is not deterministic, shot diffs are capped at WARN
    "uniform_grow": 0.15, "garbage_grow": 0.10, "ui_ratio": 0.4, "mask_dilate": 6,
}

CRASH_RX = [re.compile(p) for p in (
    r"^CRASH", r"fault address", r"^#\s*rip\b", r"\brip\s*[=:]", r"sceSblAuthMgr", r"0x80020008", r"\bSIG(SEGV|BUS|ILL|ABRT)\b",
    r"^ucontext", r"unexpected error \d+")]
FPS_RX = re.compile(r"fps:\s*([0-9.]+)")
FT_RX = re.compile(r"frametime: max ([0-9.]+) ms, frames over 20 ms: (\d+), over 33 ms: (\d+) \(of (\d+)\)")
TS_RX = re.compile(r"^(\d\d):(\d\d):(\d\d) ")


# ----------------------------------------------------------------------------------------------------------------- log analysis
def find_crash(lines):
    """Lines matching a crash pattern (first 6)."""
    return [l.strip()[:160] for l in lines if any(r.search(l) for r in CRASH_RX)][:6]


def log_stats(lines, warm=0.4, secs=None, min_samples=0.5):
    """fps / frametime statistics of the steady part (after the warm-up fraction) plus 'silent' = frames stopped early."""
    fps = [float(m.group(1)) for l in lines for m in [FPS_RX.search(l)] if m]
    ft = [tuple(float(x) for x in m.groups()) for l in lines for m in [FT_RX.search(l)] if m]
    k, kf = int(len(fps) * warm), int(len(ft) * warm)
    sf, sft = fps[k:], ft[kf:]
    r = {"fps_samples": len(fps), "ft_samples": len(ft), "steady_samples": len(sf)}
    if sf:
        r.update(fps_avg=float(np.mean(sf)), fps_min=float(min(sf)), fps_p1=float(np.percentile(sf, 1)))
    if sft:
        r.update(over20_per3s=float(np.mean([x[1] for x in sft])), over33_per3s=float(np.mean([x[2] for x in sft])),
                 worst_frame_ms=float(max(x[0] for x in sft)))
    silent = []
    if secs is not None and len(fps) < min_samples * max(secs - 10, 0) / 3.0:
        silent.append("only %d fps samples for a %d s run (expected about %d): app stopped or returned to the launcher" % (len(fps), secs, (secs - 10) // 3))
    ts = [(i, int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) for i, l in enumerate(lines) for m in [TS_RX.match(l)] if m]
    last_fps = [t for i, t in ts if FPS_RX.search(lines[i])]
    if ts and last_fps and (ts[-1][1] - last_fps[-1]) % 86400 > 15:
        silent.append("fps lines ended %d s before the end of the log" % ((ts[-1][1] - last_fps[-1]) % 86400))
    r["silent"] = silent
    return r


def parse_trace(txt):
    r = {}
    m = re.search(r"frames (\d+), average frame ([0-9.]+) ms", txt)
    if m:
        r["trace_frames"] = int(m.group(1))
    m = re.search(r"^driver draw_vbo\s+([0-9.]+)\s+([0-9.]+)", txt, re.M)
    if m:
        r["driver_ms_frame"], r["driver_draws_frame"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"per draw \(us\):.*?driver ([0-9.]+)", txt)
    if m:
        r["driver_us_draw"] = float(m.group(1))
    return r


# ---------------------------------------------------------------------------------------------------------------- image analysis
def load_rgb(p):
    return np.asarray(Image.open(p).convert("RGB"))


def dilate(m, r):
    for ax in (0, 1):
        acc = m.copy()
        for s in range(1, r + 1):
            if ax == 0:
                acc[s:] |= m[:-s]
                acc[:-s] |= m[s:]
            else:
                acc[:, s:] |= m[:, :-s]
                acc[:, :-s] |= m[:, s:]
        m = acc
    return m


def learn_mask(a, b, thresh=16, r=6):
    """A vs A2: pixels that differ between two runs of the same build (animation, particles) become the ignore mask."""
    d = shotdiff.diff_image(a.astype(np.int16), b.astype(np.int16)) > thresh
    return dilate(d, r), 100.0 * float(d.mean())


def fit(img, shape):
    if img.shape == shape:
        return img, False
    return np.asarray(Image.fromarray(img).resize((shape[1], shape[0]), Image.BILINEAR)), True


def compare_shot(run, gold, mask=None, thresh=16):
    run, resized = fit(run, gold.shape)
    d = shotdiff.diff_image(run.astype(np.int16), gold.astype(np.int16)) > thresh
    raw = 100.0 * float(d.mean())
    if mask is not None and mask.shape == d.shape:
        d = d & ~mask
    return {"raw_pct": raw, "pct": 100.0 * float(d.mean()), "regions": shotdiff.regions(d, 16, 5), "resized": resized}


def _tiles(img, t=32):
    g = img.mean(axis=2)
    h, w = (g.shape[0] // t) * t, (g.shape[1] // t) * t
    return g[:h, :w].reshape(h // t, t, w // t, t).transpose(0, 2, 1, 3).reshape(-1, t * t)


def stats(img):
    """Scalar descriptors used by the glitch heuristics."""
    g = img.mean(axis=2)
    tl = _tiles(img)
    sd = tl.std(axis=1)
    q = (img >> 4).astype(np.int32)
    key = q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]
    dom = np.bincount(key.ravel()).max() / key.size
    band = max(1, g.shape[0] // 10)
    edge = lambda x: float(np.abs(np.diff(x, axis=0)).mean() + np.abs(np.diff(x, axis=1)).mean())
    return {"dark": float((g < 8).mean()), "white": float((img.min(axis=2) >= 250).mean()),
            "magenta": float(((img[..., 0] > 240) & (img[..., 1] < 20) & (img[..., 2] > 240)).mean()),
            "dominant": float(dom), "uniform": float((sd < 1.5).mean()), "garbage": float((sd > 70).mean()),
            "ui_edge": (edge(g[:band]) + edge(g[-band:])) / 2, "nonfinite": 0.0}


def glitch_checks(img, gold=None, tol=TOL):
    """List of (level, text). Absolute checks always; relative checks need the golden image."""
    s, out = stats(img), []
    if s["dark"] > 0.995:
        out.append(("FAIL", "black frame"))
    elif s["dominant"] > 0.97:
        out.append(("FAIL", "uniform frame (%.0f %% one colour)" % (100 * s["dominant"])))
    if s["white"] > 0.5:
        out.append(("FAIL", "saturated white frame (%.0f %%)" % (100 * s["white"])))
    if s["magenta"] > 0.2:
        out.append(("FAIL", "magenta fill, NaN/missing-texture like (%.0f %%)" % (100 * s["magenta"])))
    if gold is None:
        if s["uniform"] > 0.8 and not any(l == "FAIL" for l, _ in out):
            out.append(("WARN", "large uniform area (%.0f %% of tiles), no golden to compare" % (100 * s["uniform"])))
        return out
    g = stats(gold)
    if s["uniform"] - g["uniform"] > tol["uniform_grow"]:
        out.append(("WARN", "uniform area grew %.0f %% -> %.0f %% of tiles" % (100 * g["uniform"], 100 * s["uniform"])))
    if s["garbage"] - g["garbage"] > tol["garbage_grow"]:
        out.append(("WARN", "high-frequency garbage tiles grew %.0f %% -> %.0f %%" % (100 * g["garbage"], 100 * s["garbage"])))
    if g["ui_edge"] > 2.0 and s["ui_edge"] < tol["ui_ratio"] * g["ui_edge"]:
        out.append(("WARN", "UI/HUD bands lost detail (edge energy %.1f -> %.1f): missing UI?" % (g["ui_edge"], s["ui_edge"])))
    return out


# ------------------------------------------------------------------------------------------------------------------- analyse
def slurp(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(o, p, **kw):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(o, f, indent=1, **kw)


def note(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + chr(10))


def read_lines(p):
    return slurp(p).splitlines() if os.path.exists(p) else None


def analyze_game(rundir, game, cfg, tol, extra_log=None):
    """Everything measurable from one game's run directory (udp.log, console.log, trace.txt|trace.bin, shot_<i>.png)."""
    udp, con = read_lines(os.path.join(rundir, "udp.log")), read_lines(os.path.join(rundir, "console.log"))
    res = {"game": game, "findings": [], "metrics": {}, "crash": [], "shots": []}
    add = lambda lv, area, msg: res["findings"].append({"level": lv, "area": area, "msg": msg})
    if udp is None or not udp:
        add("FAIL", "collect", "no UDP log for %s (launch refused, console unreachable or perfround failed): see perfround.out" % game)
        return res
    res["crash"] = find_crash(udp + (con or []) + (extra_log or []))
    for c in res["crash"][:3]:
        add("FAIL", "crash", c)
    st = log_stats(udp, cfg.get("warm", 0.4), cfg.get("secs"), tol["min_fps_samples"])
    silent = st.pop("silent")
    res["metrics"].update(st)
    for s in silent:
        add("FAIL", "crash", s)
    if "fps_avg" not in st:
        add("FAIL", "fps", "no steady-state fps samples")
    tt, tb = os.path.join(rundir, "trace.txt"), os.path.join(rundir, "trace.bin")
    if not os.path.exists(tt) and os.path.exists(tb):
        r = subprocess.run([sys.executable, os.path.join(HERE, "trace2json.py"), tb, "-"], capture_output=True, text=True, timeout=150,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        with open(tt, "w", encoding="utf-8") as f:
            f.write(r.stdout)
    if os.path.exists(tt):
        res["metrics"].update(parse_trace(slurp(tt)))
    for i, sh in enumerate(cfg.get("shots", [])):
        p = os.path.join(rundir, "shot_%d.png" % i)
        res["shots"].append({"i": i, "name": sh["name"], "t": sh["t"], "path": p if os.path.exists(p) else None})
        if not os.path.exists(p):
            add("WARN", "shot", "shot %d (%s @%ss) missing" % (i, sh["name"], sh["t"]))
    return res


def compare_game(res, base, tol, goldens, shot_dir_out):
    """Adds findings from the baseline comparison and the screenshot checks. base = baseline entry or None; goldens = (dir, mode)."""
    add = lambda lv, area, msg: res["findings"].append({"level": lv, "area": area, "msg": msg})
    m, g = res["metrics"], res["game"]
    noise = (base or {}).get("noise", {})
    if base is None:
        add("WARN", "baseline", "no baseline for %s (run --update-baseline)" % g)
    else:
        b = base["metrics"]
        nz = noise.get("fps_rel", 0.0)

        def rel(key, wk, fk, label, higher_is_worse, k=0.0):
            if key not in m or key not in b or b[key] <= 0:
                return
            d = (m[key] - b[key]) / b[key] * (1 if higher_is_worse else -1)
            wt, ft = max(tol[wk], k * nz), max(tol[fk], k * nz * 1.5)
            if d > ft:
                add("FAIL", "perf", "%s %.2f vs baseline %.2f (%+.1f %%, fail above %.1f %%)" % (label, m[key], b[key], 100 * d * (1 if higher_is_worse else -1), 100 * ft))
            elif d > wt:
                add("WARN", "perf", "%s %.2f vs baseline %.2f (%+.1f %%, warn above %.1f %%)" % (label, m[key], b[key], 100 * d * (1 if higher_is_worse else -1), 100 * wt))

        rel("fps_avg", "fps_warn", "fps_fail", "avg fps", False, tol["fps_noise_k"])
        rel("fps_p1", "p1_warn", "p1_fail", "p1 low fps", False, tol["fps_noise_k"])
        rel("driver_ms_frame", "drv_warn", "drv_fail", "driver ms/frame", True)
        rel("driver_us_draw", "drv_warn", "drv_fail", "driver us/draw", True)
        for key, wk, fk, lab in (("over33_per3s", "over33_warn", "over33_fail", "frames >33 ms per 3 s"), ("over20_per3s", "over20_warn", "over20_fail", "frames >20 ms per 3 s")):
            if key in m and key in b:
                d = m[key] - b[key]
                if d > tol[fk]:
                    add("FAIL", "perf", "%s %.1f vs baseline %.1f" % (lab, m[key], b[key]))
                elif d > tol[wk]:
                    add("WARN", "perf", "%s %.1f vs baseline %.1f" % (lab, m[key], b[key]))
        if base.get("shots") and [s["t"] for s in res["shots"]] != [s["t"] for s in base["shots"]]:
            add("WARN", "baseline", "scenario shot times differ from the baseline: update the baseline")
    gdir, mode = goldens
    for sh in res["shots"]:
        if not sh["path"]:
            continue
        img = load_rgb(sh["path"])
        gp = os.path.join(gdir, mode, "%s_%d.png" % (g, sh["i"]))
        gold = load_rgb(gp) if os.path.exists(gp) else None
        mp = os.path.join(gdir, mode, "%s_%d.mask.png" % (g, sh["i"]))
        mask = (np.asarray(Image.open(mp).convert("L")) > 0) if os.path.exists(mp) else None
        tag = "%s %s@%ss" % (g, sh["name"], sh["t"])
        for lv, msg in glitch_checks(img, gold, tol):
            add(lv, "glitch", "%s: %s" % (tag, msg))
        if gold is None:
            continue
        c = compare_shot(img, gold, mask, tol["shot_thresh"])
        sh["diff"] = {"pct": c["pct"], "raw_pct": c["raw_pct"], "regions": c["regions"], "resized": c["resized"], "masked": mask is not None}
        if c["resized"]:
            add("WARN", "shot", "%s: size differs from golden (resized for compare)" % tag)
        unstable = (noise.get("shot_raw_pct") or [0] * 99)[sh["i"]] > tol["unstable_pct"] if sh["i"] < len(noise.get("shot_raw_pct") or []) else False
        big = max([r[4] for r in c["regions"]] or [0])
        lv = "FAIL" if (c["pct"] > tol["shot_pct_fail"] or big > tol["region_fail_px"]) else "WARN" if (c["pct"] > tol["shot_pct_warn"] or big > tol["region_warn_px"]) else None
        if lv:
            if unstable and lv == "FAIL":
                lv = "WARN"
            heat = os.path.join(shot_dir_out, "%s_%d_heat.png" % (g, sh["i"]))
            os.makedirs(shot_dir_out, exist_ok=True)
            run, _ = fit(img, gold.shape)
            dd = shotdiff.diff_image(run.astype(np.int16), gold.astype(np.int16))
            if mask is not None and mask.shape == dd.shape:
                dd = np.where(mask, 0, dd).astype(np.uint8)
            shotdiff.heatmap(dd, tol["shot_thresh"]).save(heat)
            sh["heat"] = heat
            add(lv, "shot", "%s: %.2f %% pixels differ from golden outside the noise mask%s, largest region %s" % (
                tag, c["pct"], " (scene unstable in A vs A2, capped at WARN)" if unstable else "", tuple(int(x) for x in c["regions"][0][:4]) if c["regions"] else "-"))
    return res


def verdict(results):
    v = 0
    for r in results:
        for f in r["findings"]:
            v = max(v, LEVELS[f["level"]])
    return [k for k, x in LEVELS.items() if x == v][0]


# ------------------------------------------------------------------------------------------------------------------- baseline
def update_baseline(qa, mode, run1, run2, games, cfgs, tol):
    """Write baseline entry + golden shots (run1) and, if run2 exists, the noise masks and fps noise (run1 vs run2)."""
    bp = os.path.join(qa, "baseline.json")
    base = jload(bp) if os.path.exists(bp) else {"version": 1, "modes": {}}
    gdir = os.path.join(qa, "golden", mode)
    os.makedirs(gdir, exist_ok=True)
    out = base["modes"].setdefault(mode, {})
    for g in games:
        d1 = os.path.join(run1, g)
        a = analyze_game(d1, g, cfgs[g], tol)
        bad = [f for f in a["findings"] if f["level"] == "FAIL"]
        if bad:
            raise RuntimeError("refusing to baseline %s: run has failures: %s" % (g, bad[0]["msg"]))
        ent = {"metrics": a["metrics"], "shots": [{"name": s["name"], "t": s["t"]} for s in a["shots"]], "created": datetime.datetime.now().isoformat(timespec="seconds"), "noise": {}}
        for s in a["shots"]:
            if s["path"]:
                shutil.copy(s["path"], os.path.join(gdir, "%s_%d.png" % (g, s["i"])))
        if run2:
            b = analyze_game(os.path.join(run2, g), g, cfgs[g], tol)
            m1, m2 = a["metrics"].get("fps_avg"), b["metrics"].get("fps_avg")
            if m1 and m2:
                ent["noise"]["fps_rel"] = abs(m1 - m2) / ((m1 + m2) / 2)
            raws = []
            for s1, s2 in zip(a["shots"], b["shots"]):
                if s1["path"] and s2["path"]:
                    im1, im2 = load_rgb(s1["path"]), load_rgb(s2["path"])
                    im2, _ = fit(im2, im1.shape)
                    mask, raw = learn_mask(im1, im2, tol["shot_thresh"], tol["mask_dilate"])
                    Image.fromarray((mask * 255).astype(np.uint8)).save(os.path.join(gdir, "%s_%d.mask.png" % (g, s1["i"])))
                    raws.append(raw)
                else:
                    raws.append(0.0)
            ent["noise"]["shot_raw_pct"] = raws
        out[g] = ent
    jdump(base, bp)
    return bp


# --------------------------------------------------------------------------------------------------------------------- collect
def run_cmd(args, timeout, logf=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out, rc = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = "TIMEOUT after %ds\n%s" % (timeout, (e.stdout or b"") if isinstance(e.stdout, str) else ""), -9
    except Exception as e:  # noqa: BLE001  (tool missing etc.: record, do not crash the gate)
        out, rc = "EXC %r" % e, -1
    if logf:
        note(logf, "$ %s\n%s\n(rc %s)\n" % (" ".join(args), out, rc))
    return rc, out


def kill_app(logf):
    return run_cmd([sys.executable, os.path.join(HERE, "ps5.py"), "kill"], 90, logf)


def collect_game(game, cfg, outdir, flags, tag):
    os.makedirs(outdir, exist_ok=True)
    logf = os.path.join(outdir, "collect.out")
    label = "qa_%s_%s" % (tag, game)
    times = [s["t"] for s in cfg["shots"]]
    try:
        import shotseries
        f = shotseries.ftp()
        try:
            shotseries.request_shots(f, times)
        finally:
            f.quit()
        rc, _ = run_cmd([sys.executable, "-u", os.path.join(HERE, "perfround.py"), label, game, str(cfg["secs"])] + flags, cfg["secs"] + 900, logf)
    except Exception as e:  # noqa: BLE001
        note(logf, "collect error: %r\n" % e)
    finally:
        kill_app(logf)  # never leave the app running
    pr = os.path.join(HERE, "perf_runs")
    for src, dst in ((label + ".udp.log", "udp.log"), (label + ".console.log", "console.log")):
        if os.path.exists(os.path.join(pr, src)):
            shutil.copy(os.path.join(pr, src), os.path.join(outdir, dst))
    bins = sorted(glob.glob(os.path.join(pr, label + ".trace_*.bin")))
    if bins:
        shutil.copy(bins[0], os.path.join(outdir, "trace.bin"))
    try:
        import shotseries
        f = shotseries.ftp()
        try:
            for i, im in enumerate(shotseries.fetch_shots(f, len(times))):
                im.save(os.path.join(outdir, "shot_%d.png" % i))
        finally:
            f.quit()
    except Exception as e:  # noqa: BLE001
        note(logf, "shot fetch error: %r\n" % e)


def cleanup_console(logf):
    """Remove the files this pipeline created (shot.txt, trace.txt); other flag files are perfround's business."""
    try:
        import shotseries
        f = shotseries.ftp()
        for n in ("shot.txt", "trace.txt"):
            try:
                f.delete("%s/%s" % (shotseries.CFG, n))
            except Exception:  # noqa: BLE001
                pass
        f.quit()
    except Exception as e:  # noqa: BLE001
        note(logf, "cleanup error: %r\n" % e)


# ------------------------------------------------------------------------------------------------------------------------ report
def write_report(repdir, mode, v, results, meta):
    os.makedirs(repdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%H%M%S")
    js = os.path.join(repdir, "report_%s_%s.json" % (mode, stamp))
    md = js[:-5] + ".md"
    jdump({"verdict": v, "mode": mode, "meta": meta, "games": results}, js, default=str)
    L = ["# QA report: %s (%s)" % (v, mode), "", "meta: " + json.dumps(meta, default=str), ""]
    for r in results:
        m = r["metrics"]
        L += ["## %s" % r["game"], "",
              "| metric | value |", "|---|---|"] + ["| %s | %s |" % (k, ("%.2f" % x) if isinstance(x, float) else x) for k, x in m.items() if k != "silent"]
        L += ["", "| level | area | finding |", "|---|---|---|"] + ["| %s | %s | %s |" % (f["level"], f["area"], f["msg"].replace("|", "/")) for f in r["findings"]]
        if not r["findings"]:
            L.append("| PASS | - | no findings |")
        L += ["", "| shot | diff % (masked) | raw % | heatmap |", "|---|---|---|---|"]
        for s in r["shots"]:
            d = s.get("diff")
            L.append("| %d %s @%ss | %s | %s | %s |" % (s["i"], s["name"], s["t"], "%.3f" % d["pct"] if d else "-", "%.3f" % d["raw_pct"] if d else "-", s.get("heat", "-")))
        L.append("")
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return md, js


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mg = ap.add_mutually_exclusive_group()
    mg.add_argument("--quick", action="store_true")
    mg.add_argument("--full", action="store_true")
    ap.add_argument("--games", default=",".join(GAMES))
    ap.add_argument("--build", action="store_true", help="ps5.py build (WSL only)")
    ap.add_argument("--deploy", action="store_true", help="ps5.py kill + deploy (app must not run during deploy)")
    ap.add_argument("--force-deploy", action="store_true")
    ap.add_argument("--update-baseline", action="store_true", help="collect twice (A, A2) unless --runs 1; write baseline, golden shots and masks")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--analyze", metavar="RUNROOT", help="offline: analyse RUNROOT/run1 (and run2 for --update-baseline); no console access")
    ap.add_argument("--flags", default="asyncmultidraw", help="perfround flags (shipping config); 'trace' is added in --full")
    ap.add_argument("--no-trace", action="store_true")
    ap.add_argument("--qa-dir", default=os.path.join(HERE, "qa"))
    ap.add_argument("--klog-file", help="optional kernel log text to scan for crash patterns")
    ap.add_argument("--tol", action="append", default=[], metavar="KEY=VAL")
    ap.add_argument("--dry-run", action="store_true")
    ar = ap.parse_args(argv)

    mode = "full" if ar.full else "quick"
    tol = dict(TOL)
    for kv in ar.tol:
        k, _, x = kv.partition("=")
        if k not in tol:
            ap.error("unknown tolerance " + k)
        tol[k] = type(tol[k])(float(x))
    scen = {m: {g: dict(c) for g, c in d.items()} for m, d in SCENARIOS.items()}
    sp = os.path.join(ar.qa_dir, "scenarios.json")
    if os.path.exists(sp):
        for m, d in jload(sp).items():
            for g, c in d.items():
                scen[m].setdefault(g, {}).update(c)
    games = [g for g in ar.games.split(",") if g]
    bad = [g for g in games if g not in GAMES]
    if bad:
        ap.error("unknown game %s" % bad)
    cfgs = scen[mode]
    flags = [f for f in ar.flags.split(",") if f] + (["trace"] if mode == "full" and not ar.no_trace else [])
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    extra = read_lines(ar.klog_file) if ar.klog_file else None

    if ar.dry_run:
        print("mode", mode, "games", games, "flags", flags, "update_baseline", ar.update_baseline)
        for g in games:
            print(" ", g, json.dumps(cfgs[g]))
        return 0

    if ar.analyze:
        root = ar.analyze
    else:
        root = os.path.join(ar.qa_dir, "runs", "%s_%s" % (stamp, mode))
        os.makedirs(root, exist_ok=True)
        pl = os.path.join(root, "pipeline.out")
        py = sys.executable
        try:
            if ar.build:
                rc, out = run_cmd([py, os.path.join(HERE, "ps5.py"), "build"], 1800, pl)
                if rc:
                    print("BUILD FAILED\n" + out[-1500:])
                    return 2
            if ar.deploy:
                kill_app(pl)
                rc, out = run_cmd([py, os.path.join(HERE, "ps5.py"), "deploy"] + (["--force"] if ar.force_deploy else []), 600, pl)
                if rc:
                    print("DEPLOY FAILED\n" + out[-1500:])
                    return 2
            for n in range(1, (ar.runs if ar.update_baseline else 1) + 1):
                for g in games:
                    print("collect run%d %s (%ds)" % (n, g, cfgs[g]["secs"]), flush=True)
                    collect_game(g, cfgs[g], os.path.join(root, "run%d" % n, g), flags, "%s_r%d" % (stamp, n))
        finally:
            kill_app(pl)
            cleanup_console(pl)

    run1, run2 = os.path.join(root, "run1"), os.path.join(root, "run2")
    if not os.path.isdir(run1):
        print("no run1 directory in", root)
        return 3
    if ar.update_baseline:
        try:
            print("baseline written:", update_baseline(ar.qa_dir, mode, run1, run2 if os.path.isdir(run2) else None, games, cfgs, tol))
        except RuntimeError as e:
            print("ERROR:", e)
            return 2
        return 0

    bp = os.path.join(ar.qa_dir, "baseline.json")
    base = jload(bp).get("modes", {}).get(mode, {}) if os.path.exists(bp) else {}
    repdir = os.path.join(ar.qa_dir, "reports", datetime.date.today().isoformat())
    results = []
    for g in games:
        r = analyze_game(os.path.join(run1, g), g, cfgs[g], tol, extra)
        if r["metrics"]:
            compare_game(r, base.get(g), tol, (os.path.join(ar.qa_dir, "golden"), mode), os.path.join(repdir, "heat_%s" % stamp))
        results.append(r)
    v = verdict(results)
    md, js = write_report(repdir, mode, v, results, {"mode": mode, "flags": flags, "run": root, "stamp": stamp,
                                                    "eboot_sha1": (slurp(os.path.join(HERE, ".deployed_sha1")).strip() if os.path.exists(os.path.join(HERE, ".deployed_sha1")) else None)})
    for r in results:
        for f in r["findings"]:
            print("%-4s %-8s %s: %s" % (f["level"], f["area"], r["game"], f["msg"]))
    print("VERDICT", v, "->", md)
    return LEVELS[v]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("PIPELINE ERROR: %r" % e)
        sys.exit(3)
