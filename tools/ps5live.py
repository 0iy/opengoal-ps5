#!/usr/bin/env python3
"""Compact live view of the console log, for debugging without flooding the reader.

  ps5live.py sum [KB]        one screen: fps, frame time, slow frames, hot buckets, waits, blits, clears, crash
  ps5live.py slow [KB]       the slowest frames: what each one did (draws, uploads, flush callers)
  ps5live.py ptree [KB]      profiler dumps: buckets in slow dumps (root over 25 ms) against normal ones
  ps5live.py grep RE [N] [KB] last N distinct matching lines (tail KB, default 1024), numbers masked, with counts
  ps5live.py cfg             console config flags and the Jak settings that matter
  ps5live.py size            log size and age

Reads the tail of /data/opengoal/log/ps5.log over FTP (never the whole file; it can be hundreds of MB).
Console address: PS5_IP or .ps5_ip in the repository root."""
import ftplib, os, re, sys, collections, io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = "/data/opengoal/log/ps5.log"
CFG = "/data/opengoal/config"
SETTINGS = "/data/opengoal/config/OpenGOAL/%s/settings/pc-settings.gc"


def ip():
    v = os.environ.get("PS5_IP")
    if v:
        return v
    with open(os.path.join(ROOT, ".ps5_ip")) as f:
        return f.read().strip()


def ftp():
    f = ftplib.FTP()
    f.connect(ip(), 2121, timeout=15)
    f.login()
    return f


def tail(kb):
    f = ftp()
    try:
        size = f.size(LOG)
        buf = io.BytesIO()
        f.retrbinary("RETR " + LOG, buf.write, rest=max(0, size - kb * 1024))
        txt = buf.getvalue().decode("utf-8", "replace")
        return size, txt[txt.find("\n") + 1:]
    finally:
        f.close()


def num(m, default=0.0):
    return float(m.group(1)) if m else default


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else 0.0


def summary(kb):
    size, txt = tail(kb)
    print("\n".join(summary_lines(size, txt, kb)))


def log_size():
    f = ftp()
    try:
        return f.size(LOG)
    finally:
        f.close()


def since(start):
    """Log text written after byte offset `start` (after a rotation: the whole new file)."""
    f = ftp()
    try:
        size = f.size(LOG)
        buf = io.BytesIO()
        f.retrbinary("RETR " + LOG, buf.write, rest=start if size >= start else 0)
        return size, buf.getvalue().decode("utf-8", "replace")
    finally:
        f.close()


def summary_lines(size, txt, kb):
    lines = txt.split("\n")
    fps, render, cpu = [], [], []
    for ln in lines:
        m = re.match(r"(?:\d\d:\d\d:\d\d )?fps: ([\d.]+)\s+\(swap [\d.]+ ms, render ([\d.]+) ms per frame, thread cpu ([\d.]+)", ln)
        if m:
            fps.append(float(m.group(1))); render.append(float(m.group(2))); cpu.append(float(m.group(3)))
    out = ["log %.0f MB, tail %d KB, %d fps samples" % (size / 1048576, kb, len(fps))]
    if fps:
        out.append("fps  min %.0f  p5 %.0f  median %.0f  max %.0f | render ms median %.1f p95 %.1f | cpu ms median %.1f" % (
            min(fps), pct(fps, .05), pct(fps, .5), max(fps), pct(render, .5), pct(render, .95), pct(cpu, .5)))
        low = [x for x in fps if x < 40]
        out.append("samples under 40 fps: %d of %d (last 12: %s)" % (len(low), len(fps), " ".join("%.0f" % x for x in fps[-12:])))
    ft = [(int(a), int(b), int(c)) for a, b, c in re.findall(r"frametime: max [\d.]+ ms, frames over 20 ms: (\d+), over 33 ms: (\d+) \(of (\d+)\)", txt)]
    if ft:
        o20, o33, n = map(sum, zip(*ft))
        out.append("frames over 20 ms %.1f%%, over 33 ms %.1f%% (of %d)" % (100. * o20 / max(n, 1), 100. * o33 / max(n, 1), n))
    slow = re.findall(r"slowframe: ([\d.]+) ms, draws=(\d+)", txt)
    if slow:
        ms = [float(a) for a, _ in slow]
        out.append("slowframe lines %d, worst %.0f ms, median %.0f ms" % (len(slow), max(ms), pct(ms, .5)))
    # profiler tree: average ms per bucket over the dumps in the tail
    acc, cnt = collections.defaultdict(float), 0
    for blk in re.split(r"(?=ptree:\s+[\d.]+ ms root)", txt)[1:]:
        cnt += 1
        for ms, name in re.findall(r"ptree:\s+([\d.]+) ms (\[\s*\d+\] [\w-]+|[\w-]+)\s*$", blk, re.M):
            if name != "root" and name != "buckets":
                acc[name] = max(acc[name], 0) + float(ms)
    if cnt:
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:7]
        out.append("hot buckets (avg ms of %d dumps): %s" % (cnt, ", ".join("%s %.1f" % (n.split("] ")[-1], v / cnt) for n, v in top)))
    for key, label in (("waits per frame", "waits"), ("backpressure", "backpressure"), ("drain-buffer", "drain")):
        m = [l for l in lines if l.startswith(key + ":")]
        if m:
            out.append("%s: %s" % (label, re.sub(r"\s+", " ", m[-1])[:150]))
    sw = [l for l in lines if l.startswith("blit: software")]
    if sw:
        n = [int(re.search(r"blits=(\d+)", l).group(1)) for l in sw if re.search(r"blits=(\d+)", l)]
        ms = [num(re.search(r"blits=\d+ ([\d.]+) ms", l)) for l in sw]
        kinds = collections.Counter(re.findall(r"\[(mask\w+ fmt\d+>\d+ \d+x\d+>\d+x\d+ s\d)", " ".join(sw)))
        out.append("software blits per sample %s ms %.1f | %s" % (pct(n, .5), pct(ms, .5), "; ".join("%s x%d" % kv for kv in kinds.most_common(3))))
    cl = [l for l in lines if l.startswith("clear:")]
    if cl:
        paths = collections.Counter(re.findall(r"(buf\d+ \d+x\d+ cb\d+ path\d)", " ".join(cl)))
        big = [(k, v) for k, v in paths.items() if "1920x1080" in k]
        out.append("clear paths (path1 CPU depth, 2 GPU colour, 4 CPU colour): " + "; ".join("%s x%d" % kv for kv in big[:3]))
    md = [l for l in lines if l.startswith("glfix: multidraw") or l.startswith("glfix: draw calls") or l.startswith("glfix: merge2")]
    for l in md[-3:]:
        out.append(re.sub(r"\s+", " ", l)[:140])
    cr = [l for l in lines if "CRASH" in l]
    if cr:
        out.append("CRASH: " + cr[-1][:120])
    return out


def slow(kb):
    size, txt = tail(kb)
    recs = []
    for m in re.finditer(r"slowframe: ([\d.]+) ms, draws=(\d+), render-since-swap=[\d.]+ ms, BufferData \+(\d+) calls \+(\d+) KB, SubData \+(\d+) calls \+(\d+) KB.*?cache flush \+(\d+) calls \+(\d+) KB\n((?:  .*\n)*)", txt):
        ms, draws, bd, bdkb, sd, sdkb, fl, flkb, rest = m.groups()
        # counters that wrapped around (unsigned subtraction) are noise
        wrap = lambda x: int(x) if int(x) < 10**12 else -1
        callers = re.findall(r"flush caller (\w+): \+(\d+) calls \+(\d+) KB", rest)
        recs.append((float(ms), int(draws), wrap(bd), wrap(bdkb), wrap(fl), wrap(flkb), callers))
    recs.sort(key=lambda r: -r[0])
    print("%d slow frames in tail; worst 8:" % len(recs))
    for ms, d, bd, bdkb, fl, flkb, callers in recs[:8]:
        big = sorted(callers, key=lambda c: -int(c[2]))[:2]
        print("%6.0f ms draws %4d BufferData %s calls/%s KB flush %s calls/%s KB top callers %s" % (
            ms, d, bd, bdkb, fl, flkb, " ".join("%s:%sKB" % (a, c) for a, _, c in big)))


def ptree(kb):
    size, txt = tail(kb)
    slow, fast = [], []
    for blk in re.split(r"(?=ptree:\s+[\d.]+ ms root)", txt)[1:]:
        root = float(re.match(r"ptree:\s+([\d.]+)", blk).group(1))
        b = {n.split("] ")[-1]: float(ms) for ms, n in re.findall(r"^ptree:\s{1,3}([\d.]+) ms (\[\s*\d+\] [\w-]+)\s*$", blk, re.M)}
        (slow if root > 25 else fast).append((root, b))
    print("dumps: %d normal (avg root %.1f ms), %d slow (avg root %.1f ms)" % (
        len(fast), sum(r for r, _ in fast) / max(len(fast), 1), len(slow), sum(r for r, _ in slow) / max(len(slow), 1)))
    names = collections.Counter()
    for _, b in slow + fast:
        names.update(b.keys())
    rows = []
    for n in names:
        f = sum(b.get(n, 0) for _, b in fast) / max(len(fast), 1)
        sl = sum(b.get(n, 0) for _, b in slow) / max(len(slow), 1)
        rows.append((sl - f, n, f, sl))
    for d, n, f, sl in sorted(rows, reverse=True)[:8]:
        print("%-22s normal %5.1f ms  slow %5.1f ms  (%+.1f)" % (n, f, sl, d))


def grep(rx, n, kb=1024):
    size, txt = tail(kb)
    seen = collections.OrderedDict()
    r = re.compile(rx)
    for ln in txt.split("\n"):
        if r.search(ln):
            key = re.sub(r"\d+(\.\d+)?", "#", ln)[:160]
            seen[key] = (seen.get(key, (0, ln))[0] + 1, ln[:160])
    for c, ln in list(seen.values())[-n:]:
        print("%5dx %s" % (c, ln))


def cfg():
    f = ftp()
    try:
        names = [l.split()[-1] for l in (lambda b: (f.retrlines("LIST " + CFG, b.append), b)[1])([])]
        print("flags:", " ".join(sorted(n for n in names if n.endswith(".txt"))))
        for name in ("ps5.cfg",):
            buf = io.BytesIO(); f.retrbinary("RETR %s/%s" % (CFG, name), buf.write)
            print(name + ":", " ".join(buf.getvalue().decode().split()))
        for g in ("jak2", "jak3", "jak1"):
            buf = io.BytesIO()
            try:
                f.retrbinary("RETR " + SETTINGS % g, buf.write)
            except ftplib.all_errors:
                continue
            t = buf.getvalue().decode()
            vals = re.findall(r"\((msaa|fps|vsync|lod-force-\w+|ps2-\w+\??|game-res\w*|display-mode)\s+([^)]*)\)", t)
            print("%s: %s" % (g, " ".join("%s=%s" % (k, v.strip()) for k, v in vals)))
    finally:
        f.close()


def size_():
    f = ftp()
    try:
        m = f.sendcmd("MDTM " + LOG)[4:]
        print("log %.1f MB, modified %s UTC" % (f.size(LOG) / 1048576, m))
    finally:
        f.close()


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    c = a[0]
    if c == "sum": summary(int(a[1]) if len(a) > 1 else 400)
    elif c == "slow": slow(int(a[1]) if len(a) > 1 else 1500)
    elif c == "ptree": ptree(int(a[1]) if len(a) > 1 else 1500)
    elif c == "grep": grep(a[1], int(a[2]) if len(a) > 2 else 12, int(a[3]) if len(a) > 3 else 1024)
    elif c == "cfg": cfg()
    elif c == "size": size_()
    else: print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
