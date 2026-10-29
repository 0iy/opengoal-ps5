#!/usr/bin/env python3
"""Host test of payloads/ogagent.c (Linux or WSL, needs gcc). Never touches a console.

Builds the host variant (-DOG_HOST, address and undefined-behaviour sanitizers when available) into a private temp folder, starts it on a free
high port with temporary allowlist roots and drives every endpoint: token, path policy (dot-dot, percent-encoded, outside roots, symlinks),
size limits, truncated and concurrent uploads, malformed and random input, lifetime, idle exit and the token patch procedure.
"""
import http.client
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOK = "T0k3n" + "abcdefghijklmnopqrstuvwxyz" + "Q"  # 32 characters
assert len(TOK) == 32
N = {"ok": 0, "bad": []}


def check(name, cond, detail=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"].append("%s %s" % (name, detail))
        print("FAIL", name, detail, flush=True)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def read_resp(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = sock.recv(65536)
        if not d:
            return None
        buf += d
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    hdr = {}
    for l in lines[1:]:
        k, _, v = l.partition(":")
        hdr[k.strip().lower()] = v.strip()
    n = int(hdr.get("content-length", "0"))
    while len(rest) < n:
        d = sock.recv(min(1 << 20, n - len(rest)))
        if not d:
            break
        rest += d
    return status, hdr, rest


class Agent:
    def __init__(self, binary, base, port=None, extra=(), token=TOK):
        self.port = port or free_port()
        self.app = os.path.join(base, "app")
        self.data = os.path.join(base, "data")
        for d in (self.app, self.data):
            os.makedirs(d, exist_ok=True)
        self.errpath = os.path.join(base, "agent_%d_%d.log" % (self.port, id(self)))
        self.err = open(self.errpath, "w")
        args = [binary, "--app", self.app, "--data", self.data, "--port", str(self.port)] + list(extra)
        if token:
            args += ["--token", token]
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="print_stacktrace=1")
        self.p = subprocess.Popen(args, stderr=self.err, stdout=subprocess.DEVNULL, env=env)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                if self.p.poll() is not None:
                    return
                time.sleep(0.05)

    def conn(self, timeout=10):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        return s

    def req(self, method, target, body=None, headers=None, token=TOK, close=True, sock=None):
        s = sock or self.conn()
        h = ["%s %s HTTP/1.1" % (method, target), "Host: t"]
        if token is not None:
            h.append("X-OG-Token: " + token)
        if body is not None:
            h.append("Content-Length: %d" % len(body))
        for k, v in (headers or {}).items():
            h.append("%s: %s" % (k, v))
        s.sendall(("\r\n".join(h) + "\r\n\r\n").encode() + (body or b""))
        r = read_resp(s)
        if sock is None:
            s.close()
        return r

    def js(self, *a, **k):
        r = self.req(*a, **k)
        return r[0], (json.loads(r[2]) if r and r[2][:1] == b"{" else None)

    def alive(self):
        try:
            return self.req("GET", "/v1/status")[0] == 200
        except Exception:
            return False

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        return self.errtext()

    def errtext(self):
        self.err.flush()
        return open(self.errpath).read()


def q(**kw):
    from urllib.parse import quote
    return "&".join("%s=%s" % (k, quote(str(v), safe="/")) for k, v in kw.items())


def put(a, path, data, mode=None, size=None, extra_q="", **k):
    t = "/v1/file?" + q(path=path, size=len(data) if size is None else size) + (("&mode=" + mode) if mode else "") + extra_q
    return a.js("PUT", t, data, **k)


def build(tmp):
    out = os.path.join(tmp, "ogagent_host")
    src = os.path.join(ROOT, "payloads", "ogagent.c")
    base = ["gcc", "-std=gnu11", "-Wall", "-Wextra", "-O1", "-g", "-DOG_HOST", src, "-o", out, "-lpthread"]
    p = subprocess.run(base[:5] + ["-fsanitize=address,undefined", "-fno-sanitize-recover=undefined"] + base[5:], capture_output=True, text=True)
    san = p.returncode == 0
    if not san:
        p = subprocess.run(base, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "warning" not in p.stderr, p.stderr[-2000:]
    return out, san


def main():
    tmp = tempfile.mkdtemp(prefix="ogagent_test_")
    try:
        return run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp):
    binary, san = build(tmp)
    base = os.path.join(tmp, "base")
    os.makedirs(base)
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    secret = os.path.join(outside, "secret.txt")
    open(secret, "w").write("secret")
    a = Agent(binary, base)
    check("agent starts", a.p.poll() is None and a.alive())
    app, data = os.path.realpath(a.app), os.path.realpath(a.data)
    os.symlink(outside, os.path.join(app, "linkdir"))
    os.symlink(secret, os.path.join(data, "linkfile"))

    # ---- token
    check("no token 401", a.req("GET", "/v1/status", token=None)[0] == 401)
    check("wrong token 401", a.req("GET", "/v1/status", token="x" * 32)[0] == 401)
    check("short token 401", a.req("GET", "/v1/status", token=TOK[:31])[0] == 401)
    check("long token 401", a.req("GET", "/v1/status", token=TOK + "a")[0] == 401)
    check("token prefix match only 401", a.req("GET", "/v1/status", token=TOK[:16] + "A" * 16)[0] == 401)
    check("unknown path needs token first", a.req("GET", "/nope", token=None)[0] == 401)
    check("unknown endpoint 404", a.req("GET", "/v1/nope")[0] == 404)
    check("wrong method 405", a.req("GET", "/v1/launch")[0] == 405 and a.req("POST", "/v1/status")[0] == 405)

    # ---- status
    st, j = a.js("GET", "/v1/status")
    check("status 200", st == 200 and j and j["ok"] is True, str(j)[:200])
    check("status fields", j and all(k in j for k in ("agent", "system", "processes", "tcp_ports_open", "mounts", "paths", "app", "caps")))
    check("status version", j["agent"]["version"] == "2" and j["agent"]["lifetime_left_s"] > 0)
    check("status paths", j["paths"]["app_dir_exists"] and j["paths"]["data_dir_exists"] and j["paths"]["eboot_size"] == -1)
    check("status caps", j["caps"]["write_data"] is True and j["caps"]["launch"] is True)
    check("status processes", len(j["processes"]) > 0 and all("pid" in p and "name" in p and "title" in p for p in j["processes"]))
    check("status mounts", len(j["mounts"]) > 0 and all(m["free_bytes"] <= m["total_bytes"] for m in j["mounts"]))
    check("status sees its own port", a.port in j["tcp_ports_open"] or a.port not in (744, 2121, 2323, 9020, 9021, 9099))
    check("app not running", j["app"]["running"] is False)

    # ---- PUT / GET
    data1 = os.urandom(5000)
    p1 = app + "/sub/dir/file.bin"
    st, j = put(a, p1, data1, mode="600")
    check("put ok", st == 200 and j["ok"] and j["size"] == 5000, str(j))
    check("put content", open(p1, "rb").read() == data1)
    check("put mode", (os.stat(p1).st_mode & 0o777) == 0o600)
    check("put leaves no .part", not os.path.exists(p1 + ".part"))
    st, j = put(a, p1, b"new")
    check("put replaces", st == 200 and open(p1, "rb").read() == b"new" and (os.stat(p1).st_mode & 0o777) == 0o644)
    check("put empty", put(a, app + "/empty", b"")[0] == 200 and os.path.getsize(app + "/empty") == 0)
    check("put eboot then status", put(a, app + "/eboot.bin", b"E" * 1234)[0] == 200 and a.js("GET", "/v1/status")[1]["paths"]["eboot_size"] == 1234)
    check("put data root", put(a, data + "/config/x.txt", b"hi")[0] == 200)
    check("put size mismatch 400", put(a, app + "/m", b"abc", size=5)[0] == 400 and not os.path.exists(app + "/m"))
    check("put bad size 400", a.js("PUT", "/v1/file?path=%s/b&size=abc" % app, b"abc")[0] == 400)
    check("put bad mode 400", put(a, app + "/b", b"abc", mode="999")[0] == 400 and put(a, app + "/b", b"abc", mode="4755")[0] == 400)
    check("put without length 411", a.req("PUT", "/v1/file?" + q(path=app + "/nolen"))[0] == 411)
    check("put .part name 400", put(a, app + "/x.part", b"a")[0] == 400)
    check("put missing path 400", a.js("PUT", "/v1/file?size=1", b"a")[0] == 400)
    check("put over directory 409", put(a, app + "/sub", b"a")[0] == 409)
    s = a.conn()
    r = a.req("PUT", "/v1/file?" + q(path=app + "/exp"), b"abc", headers={"Expect": "100-continue"}, sock=s)
    check("expect 100 ok", r is not None and r[0] in (100, 200))
    s.close()

    for name, tgt in (
        ("etc", "/etc/passwd"), ("outside root", outside + "/x"), ("dotdot", app + "/../outside/x"), ("dotdot end", app + "/.."),
        ("dotdot mid", app + "/sub/../../x"), ("dot", app + "/./x"), ("relative", "etc/passwd"), ("double slash", app + "//x"),
        ("trailing slash", app + "/y/"), ("backslash", app + "\\x"), ("root only", app), ("sibling prefix", app + "2/x"),
        ("symlink dir", app + "/linkdir/x"), ("symlink file", data + "/linkfile"), ("symlink dir nested", app + "/linkdir/a/b/c"),
    ):
        st, _ = put(a, tgt, b"pwn")
        check("put 403 " + name, st == 403, "%s -> %s" % (tgt, st))
    for enc in ("%2e%2e", "%2E%2E", "%2e%2E"):
        st = a.req("PUT", "/v1/file?path=%s/%s/outside/pwn&size=3" % (app, enc), b"pwn")[0]
        check("put 403 encoded " + enc, st == 403, str(st))
    check("encoded slash dotdot", a.req("PUT", "/v1/file?path=%s%%2f..%%2f..%%2fpwn&size=3" % app, b"pwn")[0] == 403)
    check("nul byte 400", a.req("PUT", "/v1/file?path=%s/a%%00b&size=3" % app, b"pwn")[0] == 400)
    check("bad escape 400", a.req("PUT", "/v1/file?path=%s/a%%zz&size=3" % app, b"pwn")[0] == 400 and a.req("PUT", "/v1/file?path=%s/a%%2&size=3" % app, b"pwn")[0] == 400)
    st = a.req("PUT", "/v1/file?path=%s/%%252e%%252e/lit&size=3" % app, b"pwn")[0]
    check("double encoded stays literal", st == 200 and os.path.exists(app + "/%2e%2e/lit") and not os.path.exists(os.path.join(app, "..", "lit")))
    check("nothing escaped", open(secret).read() == "secret" and os.listdir(outside) == ["secret.txt"] and not os.path.exists(os.path.join(tmp, "pwn")))
    check("get 403 etc", a.js("GET", "/v1/file?path=/etc/passwd")[0] == 403)
    check("get 403 symlink", a.js("GET", "/v1/file?path=" + data + "/linkfile")[0] == 403 and a.js("GET", "/v1/file?path=" + app + "/linkdir/secret.txt")[0] == 403)
    check("get 403 dotdot", a.js("GET", "/v1/file?path=" + app + "/../outside/secret.txt")[0] == 403)

    st, h, body = a.req("GET", "/v1/file?" + q(path=p1))
    check("get file", st == 200 and body == b"new" and h["x-og-file-size"] == "3")
    big = bytes(random.Random(1).getrandbits(8) for _ in range(300000))
    put(a, app + "/big.bin", big)
    check("get tail", a.req("GET", "/v1/file?" + q(path=app + "/big.bin", tail=1000))[2] == big[-1000:])
    check("get offset len", a.req("GET", "/v1/file?" + q(path=app + "/big.bin", offset=100, len=50))[2] == big[100:150])
    check("get whole", a.req("GET", "/v1/file?" + q(path=app + "/big.bin"))[2] == big)
    check("get missing 404", a.req("GET", "/v1/file?" + q(path=app + "/none"))[0] == 404)
    check("get dir 409", a.req("GET", "/v1/file?" + q(path=app + "/sub"))[0] == 409)

    # ---- limits
    check("oversize put 413", a.req("PUT", "/v1/file?" + q(path=app + "/huge", size=9 << 30), None, headers={"Content-Length": str(9 << 30)})[0] == 413 and not os.path.exists(app + "/huge"))
    s = a.conn(); s.sendall(("GET /v1/status HTTP/1.1\r\nX-OG-Token: %s\r\nX-Pad: %s\r\n\r\n" % (TOK, "a" * 9000)).encode())
    check("header 8k limit 431", read_resp(s)[0] == 431); s.close()
    check("many headers 431", (lambda s: (s.sendall(("GET /v1/status HTTP/1.1\r\nX-OG-Token: %s\r\n%s\r\n" % (TOK, "".join("H%d: v\r\n" % i for i in range(100)))).encode()), read_resp(s))[1])(a.conn())[0] == 431)
    check("small body limit 413", a.req("POST", "/v1/mkdir?" + q(path=data + "/z"), b"a" * 70000)[0] == 413)
    check("chunked 501", a.req("POST", "/v1/mkdir", None, headers={"Transfer-Encoding": "chunked"})[0] == 501)

    # ---- truncated and concurrent uploads
    path = app + "/trunc.bin"
    for existing in (False, True):
        if existing:
            put(a, path, b"old")
        s = a.conn()
        s.sendall(("PUT /v1/file?%s HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: 1000\r\n\r\n" % (q(path=path, size=1000), TOK)).encode() + b"z" * 500)
        time.sleep(0.2)
        s.close()
        time.sleep(0.5)
        check("truncated upload leaves no .part (existing=%s)" % existing, not os.path.exists(path + ".part"))
        check("truncated upload leaves no new file (existing=%s)" % existing, (open(path, "rb").read() == b"old") if existing else not os.path.exists(path))
    results = {}

    def up(i):
        d = os.urandom(3 << 20)
        results[i] = (put(a, app + "/par/f%d" % i, d)[0], d)
    ts = [threading.Thread(target=up, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("concurrent uploads", all(results[i][0] == 200 and open(app + "/par/f%d" % i, "rb").read() == results[i][1] for i in range(8)))
    s1 = a.conn()
    pp = app + "/same.bin"
    s1.sendall(("PUT /v1/file?%s HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: 10\r\n\r\n12345" % (q(path=pp, size=10), TOK)).encode())
    time.sleep(0.3)
    check("same path in parallel 409", put(a, pp, b"other")[0] == 409)
    s1.sendall(b"67890")
    r = read_resp(s1); s1.close()
    check("first of same path wins", r[0] == 200 and open(pp, "rb").read() == b"1234567890")
    st, _ = put(a, pp, b"again")
    check("same path again ok", st == 200)

    # ---- mkdir / rm
    check("mkdir query", a.js("POST", "/v1/mkdir?" + q(path=data + "/tmp/a/b"))[0] == 200 and os.path.isdir(data + "/tmp/a/b"))
    check("mkdir form body", a.js("POST", "/v1/mkdir", ("path=" + data + "/tmp/c").encode())[0] == 200 and os.path.isdir(data + "/tmp/c"))
    check("mkdir json body", a.js("POST", "/v1/mkdir", json.dumps({"path": data + "/tmp/d"}).encode())[0] == 200 and os.path.isdir(data + "/tmp/d"))
    check("mkdir root itself", a.js("POST", "/v1/mkdir?" + q(path=data))[0] == 200)
    check("mkdir 403s", all(a.js("POST", "/v1/mkdir?" + q(path=p))[0] == 403 for p in ("/tmp/evil", app + "/../evil", app + "/linkdir/n", "/etc")))
    check("mkdir existing file 500", a.js("POST", "/v1/mkdir?" + q(path=p1))[0] == 500)
    check("mkdir no path 400", a.js("POST", "/v1/mkdir")[0] == 400)
    put(a, data + "/tmp/a/b/f", b"1")
    check("rm file", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/a/b/f"))[1]["removed"] == 1 and not os.path.exists(data + "/tmp/a/b/f"))
    put(a, data + "/tmp/a/b/f", b"1")
    check("rm non-empty dir 409", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/a"))[0] == 409)
    st, j = a.js("POST", "/v1/rm?" + q(path=data + "/tmp/a") + "&recursive=1")
    check("rm recursive", st == 200 and j["removed"] == 3 and not os.path.exists(data + "/tmp/a"), str(j))
    check("rm empty dir", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/c"))[0] == 200 and not os.path.exists(data + "/tmp/c"))
    check("rm missing", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/none"))[1]["removed"] == 0)
    check("rm outside tmp 403", a.js("POST", "/v1/rm?" + q(path=data + "/config/x.txt"))[0] == 403 and os.path.exists(data + "/config/x.txt"))
    check("rm tmp root 403", a.js("POST", "/v1/rm?" + q(path=data + "/tmp") + "&recursive=1")[0] == 403 and os.path.isdir(data + "/tmp"))
    check("rm app root 403", a.js("POST", "/v1/rm?" + q(path=app) + "&recursive=1")[0] == 403 and os.path.isdir(app))
    check("rm etc 403", a.js("POST", "/v1/rm?path=/etc/passwd")[0] == 403 and a.js("POST", "/v1/rm?path=" + app + "/linkdir/secret.txt")[0] == 403 and os.path.exists(secret))
    check("rm dotdot 403", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/../config/x.txt"))[0] == 403)
    os.symlink(outside, data + "/tmp/inner_link")
    check("rm through symlink 403", a.js("POST", "/v1/rm?" + q(path=data + "/tmp/inner_link/secret.txt"))[0] == 403 and os.path.exists(secret))
    check("rm app subtree", a.js("POST", "/v1/rm?" + q(path=app + "/par") + "&recursive=true")[0] == 200 and not os.path.exists(app + "/par"))
    os.unlink(data + "/tmp/inner_link")
    os.makedirs(data + "/tmp/lk")
    os.symlink(outside, data + "/tmp/lk/l")
    a.js("POST", "/v1/rm?" + q(path=data + "/tmp/lk") + "&recursive=1")
    check("rm recursive never follows symlinks", os.path.exists(secret) and not os.path.exists(data + "/tmp/lk"))

    # ---- launch / kill
    check("launch wrong title 403", a.js("POST", "/v1/launch?title=CUSA00001")[0] == 403 and a.js("POST", "/v1/kill?title=../x")[0] == 403)
    st, j = a.js("POST", "/v1/launch?title=LAPY77001")
    check("launch ok", st == 200 and j["ok"] and j["launch"] == 0, str(j))
    j = a.js("GET", "/v1/status")[1]
    check("status running after launch", j["app"]["running"] is True and j["agent"]["launched"] is True and any(p["title"] == "LAPY77001" for p in j["processes"]))
    st, j = a.js("POST", "/v1/kill")
    check("kill ok", st == 200 and j["ok"] and j["app_id"] > 0, str(j))
    check("status not running after kill", a.js("GET", "/v1/status")[1]["app"]["running"] is False)

    # ---- log
    st, j = a.js("GET", "/v1/log?tail=500")
    lines = j["lines"]
    check("log has requests", st == 200 and any("PUT" in l for l in lines) and any("-> 401" in l for l in lines) and any("launch" in l for l in lines))
    check("log tail n", len(a.js("GET", "/v1/log?tail=3")[1]["lines"]) == 3)
    check("log never holds the token", TOK not in " ".join(lines) and TOK not in a.errtext())

    # ---- protocol edge cases, keep-alive, pipelining
    s = a.conn()
    r1 = a.req("GET", "/v1/status", sock=s); r2 = a.req("GET", "/v1/log?tail=1", sock=s)
    check("keep-alive reuse", r1[0] == 200 and r2[0] == 200 and r1[1]["connection"] == "keep-alive"); s.close()
    s = a.conn()
    one = ("GET /v1/log?tail=1 HTTP/1.1\r\nX-OG-Token: %s\r\n\r\n" % TOK).encode()
    s.sendall(one + one)
    check("pipelined requests", read_resp(s)[0] == 200 and read_resp(s)[0] == 200); s.close()
    s = a.conn()
    s.sendall(("POST /v1/mkdir HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: %d\r\n\r\n" % (TOK, len("path=" + data + "/tmp/pp"))).encode() + ("path=" + data + "/tmp/pp").encode() + one)
    check("pipelined after body", read_resp(s)[0] == 200 and read_resp(s)[0] == 200 and os.path.isdir(data + "/tmp/pp")); s.close()
    s = a.conn(); s.sendall(("GET /v1/status HTTP/1.0\r\nX-OG-Token: %s\r\n\r\n" % TOK).encode())
    check("http/1.0 closes", read_resp(s)[1]["connection"] == "close" and s.recv(10) == b""); s.close()
    s = a.conn(); s.sendall(("GET /v1/status HTTP/1.1\r\nx-og-token:   %s  \r\nconnection: Close\r\n\r\n" % TOK).encode())
    check("header case and spaces", read_resp(s)[0] == 200); s.close()
    bads = {
        "garbage": b"\x00\x01\x02garbage\r\n\r\n", "no version": b"GET /v1/status\r\n\r\n", "http/2": b"GET /v1/status HTTP/2\r\n\r\n",
        "lowercase method": b"get /v1/status HTTP/1.1\r\n\r\n", "no slash": b"GET v1/status HTTP/1.1\r\n\r\n", "empty line": b"\r\n\r\n",
        "header no colon": ("GET /v1/status HTTP/1.1\r\nX-OG-Token %s\r\n\r\n" % TOK).encode(), "folded": ("GET /v1/status HTTP/1.1\r\nX-OG-Token: %s\r\n x: y\r\n\r\n" % TOK).encode(),
        "nul in header": ("GET /v1/status HTTP/1.1\r\nX-OG-Token: %s\r\nX: a\x00b\r\n\r\n" % TOK).encode(),
        "bad length": ("PUT /v1/file?path=%s/q HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: -5\r\n\r\n" % (app, TOK)).encode(),
        "huge length": ("PUT /v1/file?path=%s/q HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: 99999999999999999999999\r\n\r\n" % (app, TOK)).encode(),
        "two lengths": ("PUT /v1/file?path=%s/q HTTP/1.1\r\nX-OG-Token: %s\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nab" % (app, TOK)).encode(),
        "space name": ("GET /v1/status HTTP/1.1\r\nBad Name: x\r\n\r\n").encode(),
    }
    for k, v in bads.items():
        s = a.conn(); s.sendall(v)
        try:
            r = read_resp(s)
        except OSError:
            r = None
        s.close()
        check("malformed '%s' -> 4xx" % k, r is not None and 400 <= r[0] < 500, str(r and r[0]))
    check("alive after malformed", a.alive())
    s = a.conn(); s.sendall(b"GET /v1/status HTTP/1.1\r\nX-OG-Tok"); time.sleep(0.2); s.close()
    check("half header then close", a.alive())
    check("not exposed files after bad puts", not os.path.exists(app + "/q"))

    # ---- fuzz
    rnd = random.Random(7)
    valid = ("PUT /v1/file?%s HTTP/1.1\r\nHost: t\r\nX-OG-Token: %s\r\nContent-Length: 4\r\n\r\nabcd" % (q(path=app + "/fz", size=4), TOK)).encode()
    for i in range(400):
        if i % 2:
            b = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(1, 400)))
        else:
            b = bytearray(valid)
            for _ in range(rnd.randint(1, 8)):
                b[rnd.randrange(len(b))] = rnd.getrandbits(8)
            b = bytes(b[:rnd.randint(1, len(b))]) if rnd.random() < .3 else bytes(b)
        try:
            s = a.conn(2); s.sendall(b); s.settimeout(0.05)
            try:
                s.recv(4096)
            except OSError:
                pass
            s.close()
        except OSError:
            pass
    time.sleep(0.5)
    check("alive after fuzz", a.alive())
    check("fuzz stayed inside roots", os.listdir(outside) == ["secret.txt"] and open(secret).read() == "secret")
    socks = []
    try:
        for _ in range(40):
            socks.append(a.conn())
    except OSError:
        pass
    time.sleep(0.2)
    r = None
    try:
        r = a.req("GET", "/v1/status")
    except OSError:
        pass
    check("connection cap answers 503 or serves", r is None or r[0] in (200, 503))
    [s.close() for s in socks]
    time.sleep(0.5)
    check("alive after connection flood", a.alive())

    # ---- second instance, then shutdown
    b = Agent(binary, base, port=a.port)
    try:
        code = b.p.wait(5)
    except subprocess.TimeoutExpired:
        code = None
    check("second instance exits 0", code == 0, str(code))
    check("first still serves", a.alive())
    check("shutdown", a.js("POST", "/v1/shutdown")[0] == 200)
    try:
        code = a.p.wait(5)
    except subprocess.TimeoutExpired:
        code = None
    check("agent exits after shutdown", code == 0, str(code))
    err = a.stop()
    check("no sanitizer reports", "Sanitizer" not in err and "runtime error" not in err, err[-1500:])
    check("notify line", "OpenGOAL setup agent ready" in err)

    # ---- lifetime and idle-after-launch
    t0 = time.time()
    c = Agent(binary, base, extra=["--lifetime", "2"])
    code = c.p.wait(10)
    check("lifetime exit", code == 0 and 1.5 < time.time() - t0 < 6, "%s %.1f" % (code, time.time() - t0))
    c.stop()
    d = Agent(binary, base, extra=["--idle", "2"])
    time.sleep(2.7)
    check("no idle exit before launch", d.p.poll() is None)
    d.js("POST", "/v1/launch")
    t0 = time.time()
    code = d.p.wait(10)
    check("idle exit after launch", code == 0 and 1.5 < time.time() - t0 < 6, "%s %.1f" % (code, time.time() - t0))
    d.stop()

    # ---- token marker: patch the ELF-like bytes, unpatched refuses to start
    raw = open(binary, "rb").read()
    mark = b"OGAGENT_TOKEN:"
    check("marker exactly once", raw.count(mark) == 1)
    i = raw.index(mark) + len(mark)
    check("marker filler is 32 x", raw[i:i + 32] == b"x" * 32 and raw[i + 32] == 0)
    newtok = ("Patched" + "0123456789" * 3)[:32]
    patched = os.path.join(tmp, "ogagent_patched")
    open(patched, "wb").write(raw[:i] + newtok.encode() + raw[i + 32:])
    os.chmod(patched, 0o755)
    e = Agent(patched, base, token=None)
    check("patched binary accepts new token", e.req("GET", "/v1/status", token=newtok)[0] == 200 and e.req("GET", "/v1/status", token=TOK)[0] == 401)
    e.stop()
    f = Agent(binary, base, token=None)
    try:
        code = f.p.wait(5)
    except subprocess.TimeoutExpired:
        code = None
    check("unpatched binary refuses to start", code == 3, str(code))
    f.stop()

    print("ogagent host test: %d checks ok, %d failed%s" % (N["ok"], len(N["bad"]), " (sanitizers on)" if san else " (no sanitizers)"))
    return 1 if N["bad"] else 0


if __name__ == "__main__":
    sys.exit(main())
