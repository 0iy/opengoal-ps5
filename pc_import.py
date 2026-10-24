#!/usr/bin/env python3
"""pc_import.py - PC side of the OpenGOAL-PS5 game import (Python 3.8+, standard library only, Windows/macOS/Linux).

Does the heavy work on the PC with the official OpenGOAL tools (ISO extract, data decompile) and sends only the finished
"play set" to the console as ONE streamed, adaptively compressed tar (PUT /api/install). See docs/PC_IMPORT.md.

  pc_import.py --game auto --iso game.iso --ps5 192.168.1.50 [--port 8080] [--tools-dir DIR] [--jobs N] [--json-progress]
               [--pack PACK|--proj-dir DIR] [--codepack FILE] [--voices all|en|none] [--dry-run] [--out DIR]
  pc_import.py --make-codepack OUT.tar --from-build PROJ_DIR        (maintainer: harvest precompiled game code from a full build)
  pc_import.py --selftest                                         (offline tests of the stream format)
"""
import argparse, collections, hashlib, io, json, os, platform, re, shutil, socket, struct, subprocess, sys, tarfile, tempfile
import threading, time, urllib.request, zipfile, zlib
from concurrent.futures import ThreadPoolExecutor

MAGIC = b"PS5IMP01"
FRAME = 4 << 20            # raw bytes per frame
C_RAW, C_DEFLATE, C_END = 0, 1, 255
RELEASE = "v0.3.6"         # == ports/upstream.lock commit 553a713 (verified: git tag v0.3.6 is that commit)
BASE = "https://github.com/open-goal/jak-project/releases/download/" + RELEASE + "/"
TOOLS = {  # sizes/sha256 from the GitHub release API digests
    "windows": ("opengoal-windows-v0.3.6.zip", 42097216, "98aa727f10414faa0d60c233827f472d057150f56baf85506858592d39656cb0"),
    "linux": ("opengoal-linux-v0.3.6.tar.gz", 43037303, "580005f837ecb151c26bb42af5281150721eae45e92206cbab5fb13dbd83e6e4"),
    "macos-arm": ("opengoal-macos-arm-v0.3.6.tar.gz", 42001033, "49515bd0bfd0e584aa54ce111dd895c0e9d52c71c951b4ea0f6b7751c480746e"),
    "macos-intel": ("opengoal-macos-intel-v0.3.6.tar.gz", 42000808, "3cd85e3bb3d2d6dd113a61f0e3a4e059cf579230a85d0ea8407cc2d19d4cf011"),
}
# serial -> (game, region, territory). Same list as ps5shim/importer.cpp + webpage.cpp + the upstream extractor database.
DISCS = {
    "SCUS-97124": ("jak1", "NTSC-U", "SCEA"), "SCES-50361": ("jak1", "PAL", "SCEE"), "SCPS-15021": ("jak1", "NTSC-J", "SCEI"),
    "SCPS-56003": ("jak1", "NTSC-K", "SCEA"), "SCUS-97265": ("jak2", "NTSC-U", "SCEA"), "SCES-51608": ("jak2", "PAL", "SCEE"),
    "SCPS-15057": ("jak2", "NTSC-J", "SCEI"), "SCKA-20010": ("jak2", "NTSC-K", "SCEI"), "SCUS-97330": ("jak3", "NTSC-U", "SCEA"),
    "SCUS-97516": ("jak3", "NTSC-U", "SCEA"), "SCES-52460": ("jak3", "PAL", "SCEE"), "SCKA-20040": ("jak3", "NTSC-K", "SCEI"),
}
BLACK_LABEL_ELF = 7280758013604870207  # jak1 SCUS-97124 black label: *jak1-full-game* is #f (changes compiled code)
# overall percent bands (ESTIMATES from the timings measured in docs/PC_IMPORT.md); "compile" is 0 on the fast path
WEIGHTS = {"detect": 1, "tools": 4, "extract": 10, "decompile": 22, "compile": 0, "pack": 3, "upload": 58, "install": 2}


class Fail(Exception):
    def __init__(self, reason, msg):
        Exception.__init__(self, msg)
        self.reason = reason


# ---------------------------------------------------------------------------------------------------------- progress
class Reporter:
    def __init__(self, json_mode, weights):
        self.json, self.w, self.cur, self.t0, self.last = json_mode, dict(weights), None, time.time(), 0.0
        self.game, self.serial, self.done = "", "", 0.0
        self.order = ["detect", "tools", "extract", "decompile", "compile", "pack", "upload", "install"]
        self.speed, self.eta = 0, -1

    def overall(self, phase, pct):
        tot = float(sum(self.w.values())) or 1.0
        before = sum(self.w[p] for p in self.order[:self.order.index(phase)]) if phase in self.order else tot
        w = self.w.get(phase, 0)
        return int(min(100, 100.0 * (before + w * max(0, min(100, pct)) / 100.0) / tot))

    def emit(self, phase, pct=0, msg="", force=False, **kw):
        now = time.time()
        if not force and phase == self.cur and now - self.last < 0.2 and pct < 100:
            return
        self.cur, self.last = phase, now
        ov = 100 if phase == "done" else self.overall(phase, pct)
        rec = {"phase": phase, "percent": int(pct), "overall": ov, "speed_bps": int(kw.get("speed_bps", self.speed)),
               "eta_s": int(kw.get("eta_s", self.eta)), "elapsed_s": round(now - self.t0, 1), "message": msg, "game": self.game, "serial": self.serial}
        for k, v in kw.items():
            if k not in rec:
                rec[k] = v
        if self.json:
            sys.stdout.write(json.dumps(rec) + "\n")
            sys.stdout.flush()
        elif phase in ("done", "failed") or force or pct in (0, 100) or now - self.last > 1:
            sys.stdout.write("[%3d%%] %-9s %3d%% %s\n" % (ov, phase, pct, msg))
            sys.stdout.flush()


# ---------------------------------------------------------------------------------------------------------- ISO detect
def detect_iso(path):
    """Structural check like ps5shim/importer.cpp probe_fd (no hashing). Returns (serial, game, region, territory)."""
    size = os.path.getsize(path)
    if size < (64 << 20):
        raise Fail("tiny", "file too small to be a disc")
    with open(path, "rb") as f:
        f.seek(16 * 2048)
        p = f.read(2048)
        if len(p) < 2048 or p[0] != 1 or p[1:6] != b"CD001":
            f.seek(0)
            h = f.read(12)
            raise Fail("raw" if h[:1] == b"\0" and h[1:11] == b"\xff" * 10 else "notiso", "not a plain 2048-byte-sector ISO")
        if size < struct.unpack_from("<I", p, 80)[0] * 2048:
            raise Fail("truncated", "file is smaller than the disc it describes")
        lba, ln = struct.unpack_from("<I", p, 158)[0], struct.unpack_from("<I", p, 166)[0]
        if ln == 0 or ln > (1 << 20):
            raise Fail("notiso", "bad root directory")
        f.seek(lba * 2048)
        d = f.read(ln)
    pos, sysf, serial = 0, False, None
    while pos + 34 <= len(d):
        rl = d[pos]
        if rl == 0:
            pos = (pos // 2048 + 1) * 2048
            continue
        nl = d[pos + 32]
        name = d[pos + 33:pos + 33 + nl].decode("latin1")
        if name == "SYSTEM.CNF;1":
            sysf = True
        if serial is None and len(name) == 13 and name[4] == "_" and name[8] == "." and name[11:13] == ";1":
            serial = "%s-%s%s" % (name[:4], name[5:8], name[9:11])
        pos += rl
    if not sysf:
        raise Fail("nosys", "no SYSTEM.CNF: not a bootable PS2 disc")
    if serial not in DISCS:
        raise Fail("unknown", "unknown serial %s" % serial)
    return (serial,) + DISCS[serial]


# ---------------------------------------------------------------------------------------------------------- tools
def platform_key():
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "macos-arm" if platform.machine().lower() in ("arm64", "aarch64") else "macos-intel"
    return "linux"


def exe(name):
    return name + (".exe" if os.name == "nt" else "")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ensure_tools(cache, tools_dir, rep):
    """Returns the directory that contains extractor/goalc (+ data/). Downloads the official release once, sha256-verified."""
    if tools_dir:
        if not os.path.isfile(os.path.join(tools_dir, exe("extractor"))):
            raise Fail("tools", "no %s in %s" % (exe("extractor"), tools_dir))
        return tools_dir
    key = platform_key()
    name, size, want = TOOLS[key]
    dest = os.path.join(cache, "tools", RELEASE, key)
    if os.path.isfile(os.path.join(dest, exe("extractor"))) and os.path.isfile(os.path.join(dest, ".verified")):
        return dest
    os.makedirs(os.path.join(cache, "dl"), exist_ok=True)
    arc = os.path.join(cache, "dl", name)
    if not (os.path.isfile(arc) and os.path.getsize(arc) == size and sha256_file(arc) == want):
        rep.emit("tools", 0, "downloading %s (%d MB)" % (name, size >> 20), force=True)
        h, got = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(BASE + name, timeout=30) as r, open(arc + ".part", "wb") as o:
                for b in iter(lambda: r.read(1 << 20), b""):
                    o.write(b)
                    h.update(b)
                    got += len(b)
                    rep.emit("tools", 100 * got // size, "downloading %s" % name)
        except OSError as e:
            raise Fail("tools", "download failed: %s" % e)
        if h.hexdigest() != want or got != size:
            os.remove(arc + ".part")
            raise Fail("tools", "sha256/size mismatch for %s (got %s)" % (name, h.hexdigest()))
        os.replace(arc + ".part", arc)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    if name.endswith(".zip"):
        with zipfile.ZipFile(arc) as z:
            for m in z.namelist():
                if m.startswith("/") or ".." in m.split("/"):
                    raise Fail("tools", "unsafe path in archive: " + m)
            z.extractall(dest)
    else:
        with tarfile.open(arc) as t:
            for m in t.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/") or m.issym() or m.islnk():
                    raise Fail("tools", "unsafe member in archive: " + m.name)
            t.extractall(dest)
    for n in ("extractor", "goalc", "gk"):
        p = os.path.join(dest, exe(n))
        if os.path.isfile(p) and os.name != "nt":
            os.chmod(p, 0o755)
    open(os.path.join(dest, ".verified"), "w").write(want)
    return dest


def ensure_project(cache, tools, pack, proj_dir, rep):
    """Project dir = inputs of the extractor/goalc (decompiler/config, goal_src, game/assets). Official release data/ overlaid with
    our patched pack (goal_src, game assets with the PS5 in-game texts, codepacks)."""
    if proj_dir:
        return os.path.abspath(proj_dir), pack
    base = os.path.join(cache, "proj")
    stamp = os.path.join(base, ".stamp")
    want = (RELEASE + "|" + (os.path.abspath(pack) + str(os.path.getmtime(pack)) if pack and os.path.isfile(pack) else "none"))
    if not (os.path.isfile(stamp) and open(stamp).read() == want):
        shutil.rmtree(base, ignore_errors=True)
        shutil.copytree(os.path.join(tools, "data"), base)
        if pack:
            if not os.path.isfile(pack):
                raise Fail("tools", "pack not found: " + pack)
            with tarfile.open(pack) as t:
                for m in t.getmembers():
                    if m.name.startswith("/") or ".." in m.name.split("/") or m.issym() or m.islnk():
                        raise Fail("tools", "unsafe member in pack: " + m.name)
                t.extractall(base)  # pack layout: goal_src/..., game/assets/..., codepacks/<key>.tar
        open(stamp, "w").write(want)
    return base, pack


# ---------------------------------------------------------------------------------------------------------- entries / tar / frames
class FileEntry:
    def __init__(self, dest, path):
        self.dest, self.path, self.size = dest, path, os.path.getsize(path)

    def chunks(self):
        with open(self.path, "rb") as f:
            for b in iter(lambda: f.read(FRAME), b""):
                yield b


class BytesEntry:
    def __init__(self, dest, data):
        self.dest, self.data, self.size = dest, data, len(data)

    def chunks(self):
        yield self.data


class DirEntry:
    def __init__(self, dest):
        self.dest, self.size = dest, -1


class DgoEntry:
    """A DGO/CGO built exactly like common/util/DgoWriter.cpp build_dgo: u32 count, name[60], then per object
    u32 size, name[60], data, zero pad to 16 (alignment relative to the file start)."""

    def __init__(self, dest, name, members):  # members: [(name_in_dgo, loader() -> bytes, size)]
        self.dest, self.name, self.members = dest, name, members
        n = 64
        for nm, _, sz in members:
            n += 64 + sz
            n += (-n) % 16
        self.size = n

    def chunks(self):
        out = bytearray(struct.pack("<I", len(self.members)) + self.name.encode().ljust(60, b"\0"))
        for nm, load, sz in self.members:
            data = load()
            assert len(data) == sz
            out += struct.pack("<I", sz) + nm.encode().ljust(60, b"\0") + data
            out += b"\0" * (-len(out) % 16)
        yield bytes(out)


def tar_header(name, size, is_dir=False):
    nb = name.encode()
    if len(nb) > 99:
        raise Fail("pack", "path too long for the stream format: " + name)
    h = bytearray(512)
    h[0:len(nb)] = nb
    h[100:108] = b"0000755\0" if is_dir else b"0000644\0"
    h[108:116] = h[116:124] = b"0000000\0"
    h[124:136] = ("%011o" % (0 if is_dir else size)).encode() + b"\0"
    h[136:148] = b"00000000000\0"
    h[148:156] = b"        "
    h[156] = ord("5" if is_dir else "0")
    h[257:263] = b"ustar\0"
    h[263:265] = b"00"
    h[148:156] = ("%06o" % sum(h)).encode() + b"\0 "
    return bytes(h)


def tar_chunks(entries):
    for e in entries:
        if isinstance(e, DirEntry):
            yield tar_header(e.dest.rstrip("/") + "/", 0, True)
            continue
        big = e.size >= (1 << 20)
        if big:
            yield None  # frame boundary: a big file gets its own frames, so the raw/deflate choice fits its content
        yield tar_header(e.dest, e.size)
        sent = 0
        for c in e.chunks():
            sent += len(c)
            yield c
        if sent != e.size:
            raise Fail("pack", "%s changed size while reading (%d != %d)" % (e.dest, sent, e.size))
        pad = (-e.size) % 512
        if pad:
            yield b"\0" * pad
        if big:
            yield None
    yield b"\0" * 1024


def tar_total(entries):
    n = 1024
    for e in entries:
        n += 512 if isinstance(e, DirEntry) else 512 + e.size + (-e.size) % 512
    return n


def compress_frame(raw):
    """Adaptive: sample 64 KiB with deflate level 1; incompressible data (fr3 is zstd inside, STR/MUS/VAG) is sent raw."""
    if len(raw) >= 8192:
        s = raw[:65536]
        if len(zlib.compress(s, 1)) < 0.7 * len(s):
            c = zlib.compressobj(1, zlib.DEFLATED, -15)
            z = c.compress(raw) + c.flush()
            if len(z) < 0.9 * len(raw):
                return C_DEFLATE, z
    return C_RAW, raw


def stream_frames(entries, jobs, on_raw=None):
    """Yields the wire bytes: magic, frames, END(crc32, raw total). Compression runs in a thread pool, order is preserved."""
    yield MAGIC
    crc, total = 0, 0
    pend = collections.deque()
    buf = bytearray()
    with ThreadPoolExecutor(max(1, jobs)) as ex:
        def flush(block):
            nonlocal crc, total
            crc = zlib.crc32(block, crc)
            total += len(block)
            pend.append((len(block), ex.submit(compress_frame, block)))

        def drain(limit):
            while len(pend) > limit:
                rl, fut = pend.popleft()
                codec, z = fut.result()
                if on_raw:
                    on_raw(rl)
                yield struct.pack("<III", codec, len(z), rl) + bytes(z)

        for c in tar_chunks(entries):
            if c is None:
                if buf:
                    flush(bytes(buf))
                    buf.clear()
                continue
            buf += c
            while len(buf) >= FRAME:
                flush(bytes(buf[:FRAME]))
                del buf[:FRAME]
                for x in drain(jobs * 2):
                    yield x
        if buf:
            flush(bytes(buf))
        for x in drain(0):
            yield x
    yield struct.pack("<III", C_END, 12, 0) + struct.pack("<IQ", crc & 0xFFFFFFFF, total)


class FrameReader(io.RawIOBase):
    """Reference decoder of the wire format (same rules as ps5shim/install_stream.h). Used by --out and the self test."""

    def __init__(self, f):
        self.f, self.buf, self.crc, self.total, self.end = f, b"", 0, 0, False
        if self._rd(8) != MAGIC:
            raise Fail("format", "bad magic")

    def _rd(self, n):
        out = b""
        while len(out) < n:
            b = self.f.read(n - len(out))
            if not b:
                raise Fail("format", "truncated stream")
            out += b
        return out

    def readable(self):
        return True

    def readinto(self, b):
        while not self.buf and not self.end:
            codec, clen, rlen = struct.unpack("<III", self._rd(12))
            if clen > (16 << 20) or rlen > (16 << 20):
                raise Fail("format", "frame too large")
            z = self._rd(clen)
            if codec == C_END:
                crc, tot = struct.unpack("<IQ", z)
                if crc != self.crc or tot != self.total:
                    raise Fail("crc", "stream checksum mismatch")
                self.end = True
                break
            raw = z if codec == C_RAW else zlib.decompress(z, -15)
            if len(raw) != rlen or (codec == C_RAW and clen != rlen):
                raise Fail("format", "frame length mismatch")
            self.crc, self.total = zlib.crc32(raw, self.crc), self.total + len(raw)
            self.buf = raw
        n = min(len(b), len(self.buf))
        b[:n] = self.buf[:n]
        self.buf = self.buf[n:]
        return n


def unpack_stream(f, outdir):
    """Writes the stream into outdir exactly like the console receiver would (safe paths, files and dirs only)."""
    fr = FrameReader(f)
    n = 0
    with tarfile.open(fileobj=io.BufferedReader(fr, FRAME), mode="r|") as t:
        for m in t:
            parts = m.name.strip("/").split("/")
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                raise Fail("format", "unsafe entry " + m.name)
            p = os.path.join(outdir, *parts)
            if m.isdir():
                os.makedirs(p, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as o:
                    shutil.copyfileobj(t.extractfile(m), o, 1 << 20)
                n += 1
        while fr.readinto(bytearray(1 << 16)):  # drain padding up to the END frame (verifies the checksum)
            pass
    return n


# ---------------------------------------------------------------------------------------------------------- recipe / codepack
GD_STR = re.compile(r'"([^"]*)"')


def parse_gd(text):
    text = re.sub(r";[^\n]*", "", text)
    s = GD_STR.findall(text)
    out = []
    for nm in s[1:]:
        if nm.endswith(".o"):
            out.append((nm, nm[:-2]))
        elif nm.endswith("-ag.go"):
            out.append((nm, nm[:-6]))
        elif nm.endswith(".go"):
            out.append((nm, nm[:-3]))
        else:
            out.append((nm, nm))
    return s[0], out


def variant_key(game, serial, territory, elf_hash):
    return "%s-%s%s" % (game, territory, "-bl" if game == "jak1" and serial == "SCUS-97124" and elf_hash == BLACK_LABEL_ELF else "")


def build_dgo(dest, name, spec, objs, raw_obj):
    members = []
    for fn, nm in spec:
        if fn.endswith(".o"):
            if fn not in objs:
                raise Fail("bad_contents", "codepack lacks " + fn)
            members.append((nm, (lambda d=objs[fn]: d), len(objs[fn])))
        else:
            p = os.path.join(raw_obj, fn)
            if not os.path.isfile(p):
                raise Fail("bad_contents", "decompiler output lacks " + fn)
            members.append((nm, (lambda p=p: open(p, "rb").read()), os.path.getsize(p)))
    return DgoEntry(dest, name, members)


def same_file(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as x, open(b, "rb") as y:
        for _ in range(1 << 30):
            ba, bb = x.read(1 << 22), y.read(1 << 22)
            if ba != bb:
                return False
            if not ba:
                return True


def make_codepack(proj, outfile, rep):
    """Maintainer step. proj = a project dir after a COMPLETE official build of one disc (extract+decompile+compile).
    Stores out/<g>/obj/*.o + a recipe (which out/iso files are copies of iso_data files, how every DGO is composed, which
    files goalc generated). Every DGO is rebuilt with the Python builder and compared byte for byte with goalc's output."""
    isod = [d for d in os.listdir(os.path.join(proj, "iso_data")) if os.path.isfile(os.path.join(proj, "iso_data", d, "buildinfo.json"))]
    if len(isod) != 1:
        raise Fail("pack", "expected exactly one iso_data/<game> with buildinfo.json")
    game = isod[0]
    bi = json.load(open(os.path.join(proj, "iso_data", game, "buildinfo.json")))
    bi = bi[0] if isinstance(bi, list) else bi
    serial = bi["serial"]
    key = variant_key(game, serial, DISCS[serial][2], bi.get("elf_hash"))
    out = os.path.join(proj, "out", game)
    isodir, objdir = os.path.join(out, "iso"), os.path.join(out, "obj")
    raw_obj = os.path.join(proj, "decompiler_out", game, "raw_obj")
    gds = {}
    for dp, _, fs in os.walk(os.path.join(proj, "goal_src", game)):
        for f in fs:
            if f.endswith(".gd"):
                nm, spec = parse_gd(open(os.path.join(dp, f), encoding="utf8").read())
                gds[nm] = spec
    srcmap = collections.defaultdict(list)
    for dp, _, fs in os.walk(os.path.join(proj, "iso_data", game)):
        for f in fs:
            srcmap[f].append(os.path.join(dp, f))
    objs = {}
    for fn in sorted(os.listdir(objdir)):
        if fn.endswith(".o"):
            objs[fn] = open(os.path.join(objdir, fn), "rb").read()
    recipe = {"format": 1, "game": game, "key": key, "serial": serial, "release": RELEASE, "iso_copy": {}, "dgo": {}, "text": []}
    for f in sorted(os.listdir(isodir)):
        ref = os.path.join(isodir, f)
        if f in gds:
            e = build_dgo("x", f, gds[f], objs, raw_obj)
            if b"".join(e.chunks()) != open(ref, "rb").read():
                raise Fail("pack", "Python DGO builder differs from goalc for " + f)
            recipe["dgo"][f] = gds[f]
        elif f.upper().endswith((".DGO", ".CGO")):
            print("skipping %s (no .gd found, custom level?)" % f)
        else:
            src = [p for p in srcmap.get(f, []) if same_file(p, ref)]
            if src:
                recipe["iso_copy"][f] = os.path.relpath(src[0], os.path.join(proj, "iso_data", game)).replace("\\", "/")
            else:
                recipe["text"].append(f)  # generated by goalc (text/subtitle tools) at import time
    used = set(fn for spec in recipe["dgo"].values() for fn, _ in spec if fn.endswith(".o"))
    with tarfile.open(outfile, "w:gz", compresslevel=9) as t:
        data = json.dumps(recipe, indent=1, sort_keys=True).encode()
        ti = tarfile.TarInfo("recipe.json")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
        for fn in sorted(used):
            ti = tarfile.TarInfo("obj/" + fn)
            ti.size = len(objs[fn])
            t.addfile(ti, io.BytesIO(objs[fn]))
    print("codepack %s: %d objects, %d dgo, %d iso copies, %d generated text files -> %s (%d KB)" % (
        key, len(used), len(recipe["dgo"]), len(recipe["iso_copy"]), len(recipe["text"]), outfile, os.path.getsize(outfile) >> 10))


def make_pack(tree, outfile, codepack_dir):
    """Maintainer step: our toolchain pack = patched goal_src + game assets/shaders (+ codepacks) as one tar.gz."""
    with tarfile.open(outfile, "w:gz", compresslevel=6) as t:
        for sub in ("goal_src", "game/assets", "game/graphics/opengl_renderer/shaders"):
            t.add(os.path.join(tree, *sub.split("/")), arcname=sub, filter=lambda ti: (setattr(ti, "uid", 0), setattr(ti, "gid", 0), ti)[2])
        for f in sorted(os.listdir(codepack_dir)) if codepack_dir else []:
            if f.endswith(".tar"):
                t.add(os.path.join(codepack_dir, f), arcname="codepacks/" + f)
    print("pack %s: %d MB sha256 %s" % (outfile, os.path.getsize(outfile) >> 20, sha256_file(outfile)))


def load_codepack(path):
    recipe, objs = None, {}
    with tarfile.open(path) as t:
        for m in t.getmembers():
            d = t.extractfile(m).read()
            if m.name == "recipe.json":
                recipe = json.loads(d)
            elif m.name.startswith("obj/"):
                objs[m.name[4:]] = d
    return recipe, objs


# ---------------------------------------------------------------------------------------------------------- stages
def run_tool(rep, phase, cmd, parse, cwd=None):
    """Runs a tool, feeds its stdout lines to parse(line)->percent|None, returns the tail of the log on failure."""
    tail = collections.deque(maxlen=25)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd)
    except OSError as e:
        raise Fail("tools", "cannot start %s: %s" % (cmd[0], e))
    for raw in p.stdout:
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf8", "replace")).rstrip()
        tail.append(line)
        pc = parse(line)
        if pc is not None:
            rep.emit(phase, pc, phase)
    rc = p.wait()
    if rc != 0:
        raise Fail(phase, "%s failed (exit %d): %s" % (phase, rc, " | ".join(list(tail)[-6:])))


def stage_extract(rep, tools, proj, iso, game):
    size = os.path.getsize(iso)
    rx = re.compile(r"Extracting .*size 0x([0-9a-f]+) offset 0x([0-9a-f]+)")

    def parse(l):
        m = rx.search(l)
        return min(99, int(100 * (int(m.group(2), 16) + int(m.group(1), 16)) / size)) if m else None
    run_tool(rep, "extract", [os.path.join(tools, exe("extractor")), iso, "--proj-path", proj, "--game", game, "--extract",
                              "--validate", "--disable-ansi"], parse)


def stage_decompile(rep, tools, proj, game):
    marks = [("DB setup", 12), ("link data", 30), ("After code", 42), ("After textures", 55), ("After extraction", 99)]

    def parse(l):
        for k, v in marks:
            if "[Mem] After " in l and k.lower() in l.lower():
                return v
        return None
    run_tool(rep, "decompile", [os.path.join(tools, exe("extractor")), os.path.join(proj, "iso_data", game), "--folder", "--proj-path",
                                proj, "--game", game, "--decompile", "--disable-ansi"], parse)


def stage_text(rep, tools, proj, game):
    """goalc builds only the text/subtitle targets (0.4 s); everything else of (mi) is replaced by the recipe."""
    run_tool(rep, "compile", [os.path.join(tools, exe("goalc")), "--user-auto", "-g", game, "--proj-path", proj, "--iso-path",
                              os.path.join(proj, "iso_data", game), "--disable-ansi", "-c", '(make-group "text")'], lambda l: None)


def stage_compile_full(rep, tools, proj, game):
    """Fallback without codepack: official extractor --compile = goalc (mi) of all game code (slow, single threaded)."""
    n = [0]

    def parse(l):
        m = re.search(r"\[\s*(\d+)%\]", l)
        return int(m.group(1)) if m else None
    run_tool(rep, "compile", [os.path.join(tools, exe("extractor")), os.path.join(proj, "iso_data", game), "--folder", "--proj-path", proj,
                              "--game", game, "--compile", "--disable-ansi"], parse)


def static_entries(proj, game):
    ents = [DirEntry("goal_src/user")]
    for sub, sel in (("game/assets", lambda rel: rel.split("/")[0] in (game, "fonts") or "/" not in rel),
                     ("game/graphics/opengl_renderer/shaders", lambda rel: True)):
        top = os.path.join(proj, *sub.split("/"))
        for dp, _, fs in os.walk(top):
            for f in sorted(fs):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, top).replace("\\", "/")
                if sel(rel):
                    ents.append(FileEntry(sub + "/" + rel, full))
    return ents


def play_entries(proj, game, recipe, objs, voices):
    """(core entries, extra entries). Extra = voice banks of the other languages (VAGWAD.*), sent after the game is playable."""
    out = os.path.join(proj, "out", game)
    iso_out = "out/%s/iso/" % game
    core, extra = static_entries(proj, game), []
    raw_obj = os.path.join(proj, "decompiler_out", game, "raw_obj")
    if recipe:
        for dest, src in sorted(recipe["iso_copy"].items()):
            e = FileEntry(iso_out + dest, os.path.join(proj, "iso_data", game, *src.split("/")))
            (extra if dest.startswith("VAGWAD.") and dest != "VAGWAD.ENG" else core).append(e)
        for dest, spec in sorted(recipe["dgo"].items()):
            core.append(build_dgo(iso_out + dest, dest, spec, objs, raw_obj))
        for dest in recipe["text"]:
            p = os.path.join(out, "iso", dest)
            if not os.path.isfile(p):
                raise Fail("bad_contents", "goalc text step did not produce " + dest)
            core.append(FileEntry(iso_out + dest, p))
    else:  # full build output
        for f in sorted(os.listdir(os.path.join(out, "iso"))):
            if f == "TSZ.DGO":
                continue
            e = FileEntry(iso_out + f, os.path.join(out, "iso", f))
            (extra if f.startswith("VAGWAD.") and f != "VAGWAD.ENG" else core).append(e)
    fr3 = os.path.join(out, "fr3")
    if not os.path.isdir(fr3):
        raise Fail("decompile", "no fr3 output (level extraction failed)")
    for f in sorted(os.listdir(fr3)):
        core.append(FileEntry("out/%s/fr3/%s" % (game, f), os.path.join(fr3, f)))
    return core, ([] if voices == "en" else extra)


# ---------------------------------------------------------------------------------------------------------- upload
def http_json(host, port, method, path, timeout=5):
    s = socket.create_connection((host, port), timeout=timeout)
    s.sendall(("%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (method, path, host)).encode())
    d = b""
    while True:
        b = s.recv(65536)
        if not b:
            break
        d += b
    s.close()
    head, _, body = d.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def check_console(host, port):
    """Fail fast (before minutes of work) when the console is unreachable or runs an app without /api/install."""
    try:
        code, body = http_json(host, port, "GET", "/api/info")
    except OSError as e:
        raise Fail("net", "cannot reach the console at %s:%d (%s). Is the app open on the PS5?" % (host, port, e))
    if code != 200 or json.loads(body or b"{}").get("install_api") != 1:
        raise Fail("console_old", "the app on the console is too old for PC import (no /api/install); update it")


def upload(rep, host, port, game, entries, total, jobs, mode, meta, phase="upload"):
    t0 = time.time()
    sent = [0]
    q = "game=%s&total=%d&mode=%s&serial=%s&region=%s" % (game, total, mode, meta.get("serial", ""), meta.get("region", ""))
    try:
        s = socket.create_connection((host, port), timeout=15)
    except OSError as e:
        raise Fail("net", "cannot connect to %s:%d: %s" % (host, port, e))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
    s.settimeout(60)

    def on_raw(n):
        sent[0] += n
        dt = max(1e-3, time.time() - t0)
        sp = sent[0] / dt
        rep.speed, rep.eta = int(sp), int((total - sent[0]) / sp) if sp > 0 else -1
        rep.emit(phase, min(99, 100 * sent[0] // max(1, total)), "%d / %d MB" % (sent[0] >> 20, total >> 20))

    resp, got = bytearray(), threading.Event()

    def reader():  # the answer may come early (refusal): read while sending and stop sending as soon as it starts
        waited = 0
        while waited < 300:
            try:
                b = s.recv(65536)
            except socket.timeout:
                waited += 60
                continue
            except OSError:
                break
            if not b:
                break
            resp.extend(b)
            got.set()

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    try:
        s.sendall(("PUT /api/install?%s HTTP/1.1\r\nHost: %s:%d\r\nContent-Type: application/x-ps5imp\r\nConnection: close\r\n\r\n" % (q, host, port)).encode())
        for b in stream_frames(entries, jobs, on_raw):
            if got.is_set():
                break
            s.sendall(b)
        s.shutdown(socket.SHUT_WR)  # tells a truncated-stream case apart on the console; harmless otherwise
    except OSError:
        pass  # the console may have answered with an error and closed; the reader has it
    rt.join(300)  # the console verifies and renames after the END frame
    s.close()
    head, _, body = bytes(resp).partition(b"\r\n\r\n")
    try:
        code, j = int(head.split()[1]), json.loads(body or b"{}")
    except (ValueError, IndexError):
        raise Fail("net", "no valid answer from the console (connection lost?)")
    if code != 200:
        raise Fail(j.get("error", "install"), "console refused the install: HTTP %d %s" % (code, body[:200]))
    return j


# ---------------------------------------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="PC-side OpenGOAL-PS5 game import")
    ap.add_argument("--game", default="auto", choices=["auto", "jak1", "jak2", "jak3"])
    ap.add_argument("--iso")
    ap.add_argument("--ps5", help="console IP")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tools-dir", help="directory with extractor/goalc (+data/) instead of the cached official download")
    ap.add_argument("--cache-dir", default=os.path.join(os.path.expanduser("~"), ".opengoal-ps5"))
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2), help="compression threads")
    ap.add_argument("--json-progress", action="store_true")
    ap.add_argument("--pack", help="our toolchain pack (tar/tar.gz: goal_src, game/assets, codepacks/<key>.tar) overlaid on the official data/")
    ap.add_argument("--proj-dir", help="use this prepared project dir as is (maintainers; it is written to)")
    ap.add_argument("--codepack", help="precompiled game code (see --make-codepack); default: <proj>/codepacks/<variant>.tar")
    ap.add_argument("--voices", default="all", choices=["all", "en"], help="'all' also sends the other voice languages after the game is playable")
    ap.add_argument("--dry-run", action="store_true", help="do everything except the upload")
    ap.add_argument("--out", help="write the finished play set to DIR/data (through the real stream format); implies --dry-run")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--make-codepack"), ap.add_argument("--from-build"), ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--make-pack"), ap.add_argument("--from-tree"), ap.add_argument("--codepacks")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    rep = Reporter(a.json_progress, WEIGHTS)
    try:
        if a.make_pack:
            make_pack(a.from_tree, a.make_pack, a.codepacks)
            return 0
        if a.make_codepack:
            make_codepack(a.from_build, a.make_codepack, rep)
            return 0
        if not a.iso or not (a.ps5 or a.out or a.dry_run):
            ap.error("--iso and --ps5 (or --dry-run/--out) are required")
        dry = a.dry_run or bool(a.out)
        rep.emit("detect", 0, "reading disc image", force=True)
        serial, game, region, terr = detect_iso(a.iso)
        if a.game not in ("auto", game):
            raise Fail("wrong_game", "the disc is %s (%s), not %s" % (game, serial, a.game))
        rep.game, rep.serial = game, serial
        rep.emit("detect", 100, "%s %s %s" % (game, region, serial), force=True)
        if not dry:
            check_console(a.ps5, a.port)
        tools = ensure_tools(a.cache_dir, a.tools_dir, rep)
        proj, pack = ensure_project(a.cache_dir, tools, a.pack, a.proj_dir, rep)
        for d in ("iso_data", "decompiler_out", "out"):
            shutil.rmtree(os.path.join(proj, d), ignore_errors=True)
        t_x = time.time()
        stage_extract(rep, tools, proj, os.path.abspath(a.iso), game)
        bi = json.load(open(os.path.join(proj, "iso_data", game, "buildinfo.json")))
        elf = (bi[0] if isinstance(bi, list) else bi).get("elf_hash")
        key = variant_key(game, serial, terr, elf)
        rep.emit("extract", 100, "extracted", force=True)
        stage_decompile(rep, tools, proj, game)
        rep.emit("decompile", 100, "analysed", force=True)
        cp = a.codepack or os.path.join(proj, "codepacks", key + ".tar")
        recipe, objs = (load_codepack(cp) if os.path.isfile(cp) else (None, {}))
        if recipe:
            rep.w["compile"] = 1
            stage_text(rep, tools, proj, game)
        else:
            rep.w["compile"] = 45
            rep.emit("compile", 0, "no precompiled game code for %s: full build (slow%s)" % (
                key, ", and objects built on Windows are NOT verified for the console" if os.name == "nt" else ""), force=True)
            stage_compile_full(rep, tools, proj, game)
        rep.emit("compile", 100, "ready", force=True)
        rep.emit("pack", 0, "planning play set", force=True)
        core, extra = play_entries(proj, game, recipe, objs, a.voices)
        total = tar_total(core)
        rep.emit("pack", 100, "%d files, %d MB" % (len(core), total >> 20), force=True, total_bytes=total)
        meta = {"serial": serial, "region": region}
        if dry:
            rep.emit("upload", 0, "dry run", force=True)
            done = [0]

            def prog(n):
                done[0] += n
                rep.emit("upload", min(99, 100 * done[0] // max(1, total)), "writing")
            if a.out:
                shutil.rmtree(a.out, ignore_errors=True)
                os.makedirs(os.path.join(a.out, "data"))
                tmp = os.path.join(a.out, ".stream")
                with open(tmp, "wb") as f:
                    for b in stream_frames(core, a.jobs, prog):
                        f.write(b)
                wire = os.path.getsize(tmp)
                with open(tmp, "rb") as f:
                    nfiles = unpack_stream(f, os.path.join(a.out, "data"))
                os.remove(tmp)
            else:
                wire = sum(len(b) for b in stream_frames(core, a.jobs, prog))
                nfiles = len(core)
            rep.emit("done", 100, "dry run: %d files, %d MB raw, %d MB on the wire, extras %d MB" % (
                nfiles, total >> 20, wire >> 20, sum(e.size for e in extra) >> 20), force=True, raw_bytes=total, wire_bytes=wire)
        else:
            upload(rep, a.ps5, a.port, game, core, total, a.jobs, "replace", meta)
            rep.emit("install", 100, "playable", force=True, playable=True)
            if extra:
                n2 = tar_total(extra)
                rep.emit("upload", 0, "voice languages (game is already playable)", force=True)
                try:
                    upload(rep, a.ps5, a.port, game, extra, n2, a.jobs, "add", meta)
                except Fail as e:  # the game is installed and playable; only the other voice languages are missing
                    rep.emit("install", 100, "voice languages not installed: %s" % e, force=True, playable=True, warning=e.reason)
            rep.emit("done", 100, "installed %s" % game, force=True)
        if not a.keep_work and not a.proj_dir:
            for d in ("iso_data", "decompiler_out", "out"):
                shutil.rmtree(os.path.join(proj, d), ignore_errors=True)
        return 0
    except Fail as e:
        rep.emit("failed", 0, str(e), force=True, reason=e.reason)
        return 1
    except KeyboardInterrupt:
        rep.emit("failed", 0, "interrupted", force=True, reason="cancelled")
        return 1


def selftest():
    """Offline checks of the stream format; the C++ receiver is tested against the same vectors by tests_install_host.sh."""
    tmp = tempfile.mkdtemp()
    try:
        rnd = os.urandom(5 << 20)
        txt = (b"hello jak " * 150000)
        ents = [DirEntry("goal_src/user"), BytesEntry("a/rand.bin", rnd), BytesEntry("a/b/text.txt", txt), BytesEntry("empty", b"")]
        d = io.BytesIO(b"".join(stream_frames(ents, 2)))
        n = unpack_stream(d, os.path.join(tmp, "o"))
        assert n == 3 and open(os.path.join(tmp, "o", "a", "rand.bin"), "rb").read() == rnd
        assert open(os.path.join(tmp, "o", "a", "b", "text.txt"), "rb").read() == txt
        assert os.path.isdir(os.path.join(tmp, "o", "goal_src", "user")) and os.path.getsize(os.path.join(tmp, "o", "empty")) == 0
        assert len(d.getvalue()) < len(rnd) + len(txt) // 4  # text is compressed, random data is not inflated
        assert tar_total(ents) == sum(len(c) for c in tar_chunks(ents) if c)
        bad = bytearray(d.getvalue())
        bad[100] ^= 1
        try:
            unpack_stream(io.BytesIO(bytes(bad)), os.path.join(tmp, "p"))
            raise AssertionError("corruption not detected")
        except (Fail, zlib.error, tarfile.TarError):
            pass
        e = DgoEntry("x", "T.DGO", [("a", lambda: b"12345", 5), ("b", lambda: b"x" * 30, 30)])
        raw = b"".join(e.chunks())
        assert len(raw) == e.size and raw[:4] == b"\2\0\0\0" and len(raw) % 16 == 0
        assert parse_gd('("GAME.CGO"\n ("types-h.o" ; c\n  "x-ag.go" "y.go"))') == ("GAME.CGO", [("types-h.o", "types-h"), ("x-ag.go", "x"), ("y.go", "y")])
        print("selftest ok")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
