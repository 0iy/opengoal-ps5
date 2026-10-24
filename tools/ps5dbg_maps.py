#!/usr/bin/env python3
"""Read-only client for the ps4debug/ps5debug protocol (TCP 744): list processes and print the memory map of one of them.

usage: ps5dbg_maps.py [list | maps <name-or-pid>]
Protocol (ps4debug): packet = magic 0xFFAABBCC, cmd, datalen (u32 LE) + data; reply = status u32 (0x80000000 = ok) + payload."""
from ps5cfg import PS5_IP
import socket
import struct
import sys

IP = PS5_IP
MAGIC = 0xFFAABBCC
CMD_PROC_LIST, CMD_PROC_MAPS = 0xBDAA0001, 0xBDAA0004


def recv_exact(s, n):
    b = b""
    while len(b) < n:
        d = s.recv(n - len(b))
        if not d:
            raise ConnectionError("closed")
        b += d
    return b


def call(cmd, data=b""):
    s = socket.create_connection((IP, 744), 5)
    s.settimeout(8)
    s.sendall(struct.pack("<III", MAGIC, cmd, len(data)) + data)
    st = struct.unpack("<I", recv_exact(s, 4))[0]
    return s, st


def proc_list():
    s, st = call(CMD_PROC_LIST)
    if st != 0x80000000:
        raise SystemExit("status %#x" % st)
    n = struct.unpack("<I", recv_exact(s, 4))[0]
    out = []
    for _ in range(n):
        name, pid = struct.unpack("<32sI", recv_exact(s, 36))
        out.append((pid, name.split(b"\0")[0].decode(errors="replace")))
    s.close()
    return out


def maps(pid):
    s, st = call(CMD_PROC_MAPS, struct.pack("<I", pid))
    if st != 0x80000000:
        raise SystemExit("status %#x" % st)
    n = struct.unpack("<I", recv_exact(s, 4))[0]
    out = []
    for _ in range(n):
        name, start, end, off, prot = struct.unpack("<32sQQQH", recv_exact(s, 58))
        out.append((name.split(b"\0")[0].decode(errors="replace"), start, end, off, prot))
    s.close()
    return out


if __name__ == "__main__":
    a = sys.argv[1:] or ["list"]
    if a[0] == "list":
        for pid, name in proc_list():
            print(pid, name)
    else:
        key = a[1]
        pid = int(key) if key.isdigit() else next(p for p, n in proc_list() if key.lower() in n.lower())
        for name, start, end, off, prot in maps(pid):
            print("%016x-%016x %s off=%x prot=%x" % (start, end, name, off, prot))
