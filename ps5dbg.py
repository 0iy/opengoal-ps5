#!/usr/bin/env python3
"""Minimal ps5debug(-NG) client (port 744): list processes, attach, dump thread registers, detach.

usage: ps5dbg.py list
       ps5dbg.py regs <pid>      attach, print registers of every thread, detach
       ps5dbg.py detach
Protocol as in ps4debug: header {magic 0xFFAABBCC, cmd, length} + data; replies start with a u32 status.
"""
from ps5cfg import PS5_IP
import socket
import struct
import sys

HOST = PS5_IP
MAGIC = 0xFFAABBCC
CMD_PROC_LIST = 0xBDAA0001
CMD_DEBUG_ATTACH = 0xBDBB0001
CMD_DEBUG_DETACH = 0xBDBB0002
CMD_DEBUG_THREADS = 0xBDBB0005
CMD_DEBUG_GETREGS = 0xBDBB0008
CMD_PROC_MAPS = 0xBDAA0004
CMD_CONSOLE_NOTIFY = 0xBDDD0004

REG_NAMES = ["r15", "r14", "r13", "r12", "r11", "r10", "r9", "r8", "rdi", "rsi", "rbp", "rbx", "rdx", "rcx", "rax"]


def recv_all(s, n):
    data = b""
    while len(data) < n:
        chunk = s.recv(n - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return data


def call(cmd, payload=b""):
    s = socket.create_connection((HOST, 744), timeout=8)
    s.sendall(struct.pack("<III", MAGIC, cmd, len(payload)) + payload)
    status = struct.unpack("<I", recv_all(s, 4))[0]
    return s, status


def main():
    action = sys.argv[1]
    if action == "list":
        s, st = call(CMD_PROC_LIST)
        print(f"status=0x{st:08x}")
        count = struct.unpack("<I", recv_all(s, 4))[0]
        for _ in range(count):
            name, pid = struct.unpack("<32sI", recv_all(s, 36))
            print(pid, name.split(b"\0")[0].decode(errors="replace"))
    elif action == "regs":
        pid = int(sys.argv[2])
        s, st = call(CMD_DEBUG_ATTACH, struct.pack("<I", pid))
        print(f"attach status=0x{st:08x}")
        s.close()
        s, st = call(CMD_DEBUG_THREADS)
        print(f"threads status=0x{st:08x}")
        count = struct.unpack("<I", recv_all(s, 4))[0]
        tids = list(struct.unpack(f"<{count}I", recv_all(s, 4 * count))) if count else []
        print("threads:", tids)
        s.close()
        for tid in tids:
            s, st = call(CMD_DEBUG_GETREGS, struct.pack("<I", tid))
            if st != 0x80000000:
                print(f"tid {tid}: getregs status=0x{st:08x}")
                s.close()
                continue
            raw = recv_all(s, 15 * 8 + 4 + 2 + 2 + 4 + 2 + 2 + 8 * 5)
            vals = struct.unpack("<15QIHHIHH5Q", raw)
            regs = dict(zip(REG_NAMES, vals[:15]))
            trapno, fs, gs, err, es, ds, rip, cs, rflags, rsp, ss = vals[15:]
            print(f"tid {tid}: rip=0x{rip:x} rsp=0x{rsp:x} trapno={trapno} err=0x{err:x} " +
                  " ".join(f"{k}=0x{v:x}" for k, v in regs.items()))
            s.close()
        s, st = call(CMD_DEBUG_DETACH)
        print(f"detach status=0x{st:08x}")
    elif action == "detach":
        s, st = call(CMD_DEBUG_DETACH)
        print(f"detach status=0x{st:08x}")


main()
