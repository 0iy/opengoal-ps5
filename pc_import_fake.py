#!/usr/bin/env python3
"""Fake engine for GUI tests: same CLI and JSON-lines contract as pc_import.py, no real work.
Env: FAKE_FAIL=1 fails in the compile phase, FAKE_SLEEP=seconds per step (default 0.08)."""
import argparse, json, os, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--game", default="auto"); ap.add_argument("--iso", required=True); ap.add_argument("--ps5", required=True)
ap.add_argument("--port", type=int, default=8080); ap.add_argument("--tools-dir"); ap.add_argument("--jobs", type=int)
ap.add_argument("--json-progress", action="store_true")
a = ap.parse_args()
name = os.path.basename(a.iso).lower()
game = a.game if a.game != "auto" else next((g for g in ("jak3", "jak2", "jak1") if g in name), "jak1")
serial = {"jak1": "SCUS-97124", "jak2": "SCUS-97265", "jak3": "SCUS-97330"}[game]
steps = [("detect", 1), ("tools", 1), ("extract", 6), ("decompile", 8), ("compile", 6), ("pack", 3), ("upload", 8), ("install", 2)]
total = sum(n for _, n in steps); done = 0; delay = float(os.environ.get("FAKE_SLEEP", "0.08"))

def emit(phase, pct, overall, msg, speed=0, eta=0):
    print(json.dumps({"phase": phase, "percent": pct, "overall": overall, "speed_bps": speed, "eta_s": eta,
                      "message": msg, "game": game, "serial": serial}), flush=True)

for phase, n in steps:
    for i in range(n):
        if os.environ.get("FAKE_FAIL") == "1" and phase == "compile" and i == 2:
            emit("failed", 40, int(100 * done / total), "Could not reach the PS5 app on port %d (connection refused)" % a.port)
            sys.exit(2)
        time.sleep(delay); done += 1
        emit(phase, int(100 * (i + 1) / n), int(100 * done / total), "%s %d/%d" % (phase, i + 1, n),
             speed=(35_000_000 if phase == "upload" else 0), eta=int((total - done) * delay))
emit("done", 100, 100, "Ready")
