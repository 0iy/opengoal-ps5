#!/usr/bin/env python3
"""Host end-to-end test of the PC install path: pc_import.upload() -> app/shim/webserver.cpp (real code, stubbed importer).
Run through tests/host/install_host.sh (it builds and starts the server and sets WS_PORT / WS_ROOT / RX_BIN)."""
import io, json, os, socket, struct, subprocess, sys, tempfile, time, zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "installer"))
import pc_import as pc

PORT = int(os.environ["WS_PORT"])
ROOT = os.environ["WS_ROOT"]  # replaces /data/opengoal
RX = os.environ["RX_BIN"]
rep = pc.Reporter(False, pc.WEIGHTS)
rep.emit = lambda *a, **k: None


def entries(tag, big=6 << 20):
    rnd = os.urandom(big)
    txt = (b"jak and daxter " * 200000)
    return [pc.DirEntry("goal_src/user"), pc.BytesEntry("out/jak1/fr3/beach.fr3", rnd), pc.BytesEntry("out/jak1/iso/GAME.CGO", txt),
            pc.BytesEntry("out/jak1/iso/ABC.TXT", tag.encode() * 300), pc.BytesEntry("game/assets/empty.txt", b"")], {
        "out/jak1/fr3/beach.fr3": rnd, "out/jak1/iso/GAME.CGO": txt, "out/jak1/iso/ABC.TXT": tag.encode() * 300, "game/assets/empty.txt": b""}


def status(game="jak1"):
    code, body = pc.http_json("127.0.0.1", PORT, "GET", "/api/status")
    return json.loads(body)["games"][game]


def check_tree(root, want):
    for rel, data in want.items():
        got = open(os.path.join(root, *rel.split("/")), "rb").read()
        assert got == data, rel
    assert os.path.isdir(os.path.join(root, "goal_src", "user"))


def raw_put(stream_bytes, total, query="game=jak1&mode=replace"):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    s.sendall(("PUT /api/install?%s&total=%d HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n" % (query, total)).encode())
    try:
        s.sendall(stream_bytes)
        s.shutdown(socket.SHUT_WR)
    except OSError:
        pass
    d = b""
    try:
        while True:
            b = s.recv(65536)
            if not b:
                break
            d += b
    except OSError:
        pass
    head, _, body = d.partition(b"\r\n\r\n")
    try:
        return int(head.split()[1]), json.loads(body or b"{}")
    except ValueError:
        return int(head.split()[1]), {}


# 1. capabilities
code, body = pc.http_json("127.0.0.1", PORT, "GET", "/api/info")
assert code == 200 and json.loads(body)["install_api"] == 1

# 2. normal install, replace mode; progress visible in status while sending is not asserted (too fast), the final state is
ents, want = entries("A")
total = pc.tar_total(ents)
j = pc.upload(rep, "127.0.0.1", PORT, "jak1", ents, total, 2, "replace", {"serial": "SCES-50361", "region": "PAL"})
assert j["ok"] and j["files"] == 4, j
data = os.path.join(ROOT, "jak1", "data")
check_tree(data, want)
assert os.path.isfile(os.path.join(data, ".ps5ready")) and not os.path.exists(os.path.join(ROOT, "jak1", "data.new"))
st = status()
assert st["phase"] == "done" and st["serial"] == "SCES-50361" and st["percent"] == 100, st
print("install replace ok")

# 3. second install replaces the first atomically; old tree is gone afterwards
ents, want2 = entries("B", 2 << 20)
pc.upload(rep, "127.0.0.1", PORT, "jak1", ents, pc.tar_total(ents), 2, "replace", {})
check_tree(data, want2)
time.sleep(1.0)
assert not os.path.exists(os.path.join(ROOT, "jak1", "data.old"))
print("install replace twice ok")

# 4. add mode merges into the existing tree, no .part left
ents = [pc.BytesEntry("out/jak1/iso/VAGWAD.FRE", os.urandom(3 << 20))]
extra = ents[0].data
pc.upload(rep, "127.0.0.1", PORT, "jak1", ents, pc.tar_total(ents), 2, "add", {})
assert open(os.path.join(data, "out", "jak1", "iso", "VAGWAD.FRE"), "rb").read() == extra
check_tree(data, want2)
assert not [f for f in os.listdir(os.path.join(data, "out", "jak1", "iso")) if f.endswith(".part")]
print("install add ok")

# 5. corrupt stream: refused, the installed game stays untouched, no staging dir
ents, want3 = entries("C", 1 << 20)
stream = bytearray(b"".join(pc.stream_frames(ents, 2)))
stream[len(stream) // 2] ^= 0xFF
code, j = raw_put(bytes(stream), pc.tar_total(ents))
assert code == 422 and j["error"] == "bad_contents", (code, j)
check_tree(data, want2)
assert not os.path.exists(os.path.join(ROOT, "jak1", "data.new"))
assert status()["phase"] == "failed" and status()["reason"] == "bad_contents"
print("corrupt stream rejected ok")

# 6. truncated stream (connection closed in the middle)
good = b"".join(pc.stream_frames(ents, 2))
code, j = raw_put(good[: len(good) // 2], pc.tar_total(ents))
assert code == 500 or j.get("error") in ("net", "bad_contents"), (code, j)
check_tree(data, want2)
assert not os.path.exists(os.path.join(ROOT, "jak1", "data.new"))
print("truncated stream rejected ok")

# 7. path traversal / absolute path inside the tar
for evil in ("../evil", "/abs/evil", "a/../../evil"):
    class E(pc.BytesEntry):
        pass
    e = pc.BytesEntry("x", b"1234")
    e.dest = evil
    code, j = raw_put(b"".join(pc.stream_frames([e], 1)), pc.tar_total([e]))
    assert code == 422, (evil, code, j)
assert not os.path.exists(os.path.join(ROOT, "evil")) and not os.path.exists("/evil")
print("unsafe paths rejected ok")

# 8. wrong total (declared size does not match the stream)
code, j = raw_put(good, pc.tar_total(ents) + 4096)
assert code == 422, (code, j)
check_tree(data, want2)
print("size mismatch rejected ok")

# 9. unknown game
code, j = raw_put(good, 4096, "game=jak9&mode=replace")
assert code == 404, code
print("unknown game ok")


# 11. cancel while the stream is arriving (the receiver notices at the next received bytes)
ents, _ = entries("E", 2 << 20)
good = b"".join(pc.stream_frames(ents, 2))
c = socket.create_connection(("127.0.0.1", PORT), timeout=10)
c.sendall((("PUT /api/install?game=jak1&mode=replace&total=%d HTTP/1.1" + chr(13) + chr(10) + "Host: x" + chr(13) + chr(10) + "Connection: close" + chr(13) + chr(10) + chr(13) + chr(10)) % pc.tar_total(ents)).encode())
c.sendall(good[:300000])
time.sleep(0.5)
assert status()["phase"] == "importing" and status()["stage"] == "install", status()
pc.http_json("127.0.0.1", PORT, "POST", "/api/cancel?game=jak1")
c.sendall(good[300000:600000])
d = b""
try:
    while True:
        b = c.recv(65536)
        if not b:
            break
        d += b
except OSError:
    pass
assert b" 422 " in d[:20] and b"cancelled" in d, d[:200]
check_tree(data, want2)
assert not os.path.exists(os.path.join(ROOT, "jak1", "data.new"))
print("cancel ok")

# 10. receiver (same header as the server) against Python generated streams, odd chunk sizes
ents, want4 = entries("D", 3 << 20)
sf = os.path.join(tempfile.gettempdir(), "ps5_stream_test.bin")
open(sf, "wb").write(b"".join(pc.stream_frames(ents, 2)))
for chunk in ("1", "7", "4093", "0", "1048576"):
    out = subprocess.run([RX, sf, chunk], capture_output=True, text=True).stdout.splitlines()
    assert out[0].startswith("OK 4 "), (chunk, out[:2])
    got = {l.split()[0]: (int(l.split()[1]), l.split()[2]) for l in out[1:] if not l.startswith("dir ")}
    for rel, d in want4.items():
        assert got[rel] == (len(d), "%08x" % (zlib.crc32(d) & 0xFFFFFFFF)), (chunk, rel)
    assert "dir goal_src/user" in out
    if chunk == "1048576":
        print("receiver speed (host, MB/s raw):", out[0].split()[3])
bad = bytearray(open(sf, "rb").read())
bad[2000000] ^= 1
open(sf, "wb").write(bytes(bad))
assert subprocess.run([RX, sf, "4093"], capture_output=True, text=True).stdout.startswith("FAIL")
os.remove(sf)
print("receiver unit ok")
print("ALL OK")
