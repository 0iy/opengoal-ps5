#!/usr/bin/env python3
"""Write a tiny valid ISO9660 image whose SYSTEM.CNF names the given serial: make_fake_iso.py OUT SCUS_971.24"""
import struct, sys


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def rec(name, lba, size, flags=0):
    n = name.encode()
    body = bytes([0]) + both32(lba) + both32(size) + bytes(7) + bytes([flags, 0, 0]) \
        + struct.pack("<H", 1) + struct.pack(">H", 1) + bytes([len(n)]) + n
    if (len(body) + 1) % 2:
        body += bytes(1)
    return bytes([len(body) + 1]) + body


def make(path, boot, sectors=24):
    cnf = ("BOOT2 = cdrom0:\\%s;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n" % boot).encode()
    img = bytearray(sectors * 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[80:88] = both32(24)
    pvd[156:190] = rec(chr(0), 18, 2048, 2)[:34]
    img[16 * 2048:17 * 2048] = pvd
    root = rec(chr(0), 18, 2048, 2) + rec("SYSTEM.CNF;1", 19, len(cnf))
    img[18 * 2048:18 * 2048 + len(root)] = root
    img[19 * 2048:19 * 2048 + len(cnf)] = cnf
    open(path, "wb").write(img)


if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2])
