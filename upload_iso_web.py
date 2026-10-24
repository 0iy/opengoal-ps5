#!/usr/bin/env python3
"""Upload an ISO to the console's onboarding web server like the web page does (begin / chunk / start) and follow /api/status.

usage: upload_iso_web.py <game jak1|jak2|jak3> <iso> [--host IP] [--port 8080] [--chunk MiB] [--threads N] [--log file]
Env: PS5_IP (default host). Prints one line per second with the status of the game; writes the raw status JSON lines to --log.
"""
from ps5cfg import PS5_IP
import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(url, method="GET", data=None, timeout=60):
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("iso")
    ap.add_argument("--host", default=PS5_IP)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--chunk", type=int, default=8, help="chunk size in MiB")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--log", default="")
    a = ap.parse_args()
    base = f"http://{a.host}:{a.port}"
    size = os.path.getsize(a.iso)
    chunk = a.chunk << 20
    fp = f"{size}-{int(os.path.getmtime(a.iso))}-{os.path.basename(a.iso)}"
    st, body = call(f"{base}/api/begin?game={a.game}&total={size}&chunk={chunk}&fp={fp}", "POST", b"")
    print("begin", st, body[:200])
    if st != 200:
        return 1
    resume = set(json.loads(body).get("resume", []))
    offsets = [o for o in range(0, size, chunk) if o not in resume]
    log = open(a.log, "a") if a.log else None
    done = {"n": 0, "bytes": 0, "stop": False}
    t0 = time.time()

    def poll():
        while not done["stop"]:
            st, b = call(f"{base}/api/status")
            if log:
                log.write(f"{time.time() - t0:.1f} {b.decode(errors='replace')}\n")
                log.flush()
            try:
                g = json.loads(b)["games"][a.game]
                print(f"{time.time() - t0:6.1f}s phase={g.get('phase')} stage={g.get('stage')} pct={g.get('percent')} stage_pct={g.get('stage_percent')} "
                      f"bytes={g.get('bytes')}/{g.get('total')} speed={g.get('speed')} eta={g.get('eta')} reason={g.get('reason', '')}", flush=True)
            except Exception as e:  # noqa: BLE001
                print("status?", e, b[:80], flush=True)
            time.sleep(1.0)

    th = threading.Thread(target=poll, daemon=True)
    th.start()

    f_lock = threading.Lock()
    fh = open(a.iso, "rb")

    def send(off):
        with f_lock:
            fh.seek(off)
            data = fh.read(chunk)
        for attempt in range(5):
            st, b = call(f"{base}/api/chunk?game={a.game}&off={off}&total={size}", "PUT", data, timeout=120)
            if st in (200, 204):
                done["n"] += 1
                done["bytes"] += len(data)
                return
            time.sleep(1 + attempt)
        raise RuntimeError(f"chunk {off} failed: {st} {b[:100]}")

    with ThreadPoolExecutor(a.threads) as ex:
        list(ex.map(send, offsets))
    print(f"upload done in {time.time() - t0:.1f}s ({size / (time.time() - t0) / 1e6:.1f} MB/s)", flush=True)
    st, b = call(f"{base}/api/start?game={a.game}", "POST", b"")
    print("start", st, b[:200], flush=True)
    # follow until the game is done or failed
    while True:
        st, b = call(f"{base}/api/status")
        try:
            g = json.loads(b)["games"][a.game]
        except Exception:  # noqa: BLE001
            time.sleep(2)
            continue
        if g.get("phase") in ("done", "failed") or (g.get("installed") and g.get("phase") == "idle"):
            break
        time.sleep(2)
    done["stop"] = True
    print(f"finished after {time.time() - t0:.1f}s: {g}", flush=True)
    return 0 if g.get("phase") != "failed" else 2


if __name__ == "__main__":
    sys.exit(main())
