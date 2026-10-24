#!/usr/bin/env python3
"""Restart the app and drive Jak 3 (launcher -> new game) into gameplay for profiling. usage: jak3_play.py [seconds_to_wait_after]"""
from ps5cfg import PS5_IP
import ftplib, io, subprocess, sys, time
def dbg(*a): return subprocess.run([sys.executable, "dbg.py", *a], capture_output=True, text=True).stdout.strip()
def ps5(*a): return subprocess.run([sys.executable, "ps5.py", *a], capture_output=True, text=True).stdout.strip()
if dbg("ping") != "R pong":
    ps5("kill"); time.sleep(3); ps5("start")
for _ in range(40):
    time.sleep(2)
    if dbg("ping") == "R pong": break
def launched():
    f = ftplib.FTP(); f.connect(PS5_IP, 2121, timeout=20); f.login(); f.voidcmd("TYPE I")
    p = "/data/opengoal/log/ps5.log"; n = f.size(p); b = io.BytesIO()
    f.retrbinary("RETR " + p, b.write, rest=max(0, n - 60000))
    t = b.getvalue().decode("utf-8", "replace"); i = t.rfind("opengoal-ps5: start")
    return "launching" in t[i:]
time.sleep(8)
for _ in range(4):  # the first press can get lost while the launcher is still starting
    dbg("press", "4000", "150")   # launcher: Play (Jak 3 is the remembered game)
    time.sleep(6)
    if launched(): break
time.sleep(45)
for _ in range(4):
    dbg("press", "1000", "150"); time.sleep(3); dbg("press", "4000", "150"); time.sleep(4)
dbg("press", "4000", "150"); time.sleep(12)
print("in game?")
