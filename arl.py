#!/usr/bin/env python3
"""ActRemoteLink agent client: python arl.py send | cmd <COMMAND...> | backup"""
from ps5cfg import PS5_IP
import socket, sys, time, json, os
IP = PS5_IP
HERE = os.path.dirname(os.path.abspath(__file__))
def cmd(c, t=6):
    s = socket.create_connection((IP, 31337), 5); s.settimeout(t)
    s.sendall(c.encode() + b"\n"); b = b""
    try:
        while not b.endswith(b"END\n"):
            d = s.recv(8192)
            if not d: break
            b += d
    except Exception: pass
    s.close(); return b.decode(errors="replace")
STR = [125830656,125874188,125874183,125874190,125874191,125874192,125874189,125874193,125874195]
INT = [125830144,125831424,125831168,125832960,125874194,125874185,125874186,125830912,125831936,125832704,125882625,125854723,125833216]
if sys.argv[1] == "send":
    s = socket.create_connection((IP, 9021), 10); s.sendall(open(os.path.join(HERE, "backup", "arl_agent_noguard.elf"), "rb").read()); s.close(); print("sent")
elif sys.argv[1] == "cmd":
    print(cmd(" ".join(sys.argv[2:])))
elif sys.argv[1] == "backup":
    out = {}
    for k in STR: out[f"str:{k}"] = cmd(f"GETKEY str {k}")
    for k in INT: out[f"int:{k}"] = cmd(f"GETKEY int {k}")
    json.dump(out, open(os.path.join(HERE, "backup", "slot1_registry_before.json"), "w"), indent=1)
    for k, v in out.items(): print(k, v.replace("\nEND\n", "").replace("\n", " "))
