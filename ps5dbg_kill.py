#!/usr/bin/env python3
"""Kill (or stop/resume) a process through ps5debug-NG: CMD_DEBUG_PROCESS_STOP 0xBDBB0500.

usage: ps5dbg_kill.py <pid> [state]     state: 0 resume (SIGCONT), 1 stop, 2 kill (default)
Status words on the wire: success 0x80000000, error 0xF0000001, no data 0xF0000003.
"""
from ps5cfg import PS5_IP
import socket
import struct
import sys

HOST = PS5_IP
pid = int(sys.argv[1])
state = int(sys.argv[2]) if len(sys.argv) > 2 else 2
payload = struct.pack("<IB", pid, state)
s = socket.create_connection((HOST, 744), timeout=8)
s.sendall(struct.pack("<III", 0xFFAABBCC, 0xBDBB0500, len(payload)) + payload)
status = struct.unpack("<I", s.recv(4))[0]
print(f"pid {pid} state {state}: status=0x{status:08x}")
