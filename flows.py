#!/usr/bin/env python3
"""Preset controller flows via the debug channel ("press <hexmask> <ms>").

usage: python flows.py <flow> [shot_name]
flows:
  to_gameplay   launcher -> title -> NEW GAME -> slot 2 (empty) -> skip intro (needs slot 2 empty)
  intro_skip    skip logo/intro with triangle x2
  pause         START (pauses or opens menu in game)
  shot_only     capture screen only
Masks follow libpad layout: X=0x4000 TRIANGLE=0x1000 START=0x0008 DOWN=0x0040 CIRCLE=0x2000.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
X, TRI, START, DOWN = 0x4000, 0x1000, 0x0008, 0x0040

FLOWS = {
    "to_gameplay": [
        (X, 150, 8),       # launcher: start (title loads slowly)
        (START, 150, 3),   # title: PRESS START (title ignores early input, so repeat)
        (START, 150, 3),
        (START, 150, 3),
        (X, 150, 4),       # main menu: NEW GAME
        (DOWN, 120, 1),    # save select: slot 2
        (DOWN, 120, 1),    # slot 3 (slots 1-2 hold saves from earlier tests)
        (X, 150, 5),       # slot 3 -> intro
        (TRI, 150, 3),     # intro skip
        (TRI, 150, 4),
    ],
    "intro_skip": [(TRI, 150, 3), (TRI, 150, 3)],
    "pause": [(START, 150, 2)],
    "shot_only": [],
}


def dbg(*args):
    return subprocess.run([sys.executable, os.path.join(HERE, "dbg.py"), *args],
                          capture_output=True, text=True, timeout=60).stdout.strip()


def main():
    flow = sys.argv[1] if len(sys.argv) > 1 else "shot_only"
    shot = sys.argv[2] if len(sys.argv) > 2 else None
    if flow not in FLOWS:
        print("unknown flow:", flow, "| known:", ", ".join(FLOWS))
        return 2
    for mask, ms, wait in FLOWS[flow]:
        dbg("press", format(mask, "x"), str(ms))
        time.sleep(wait)
    if shot:
        subprocess.run([sys.executable, os.path.join(HERE, "ps5.py"), "snap", shot],
                       capture_output=True, text=True, timeout=60)
        print("shot:", shot)
    print("flow done:", flow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
