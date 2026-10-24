"""Console address for all tools: env PS5_IP, else the first line of ./.ps5_ip (git-ignored), else an error with the fix."""
import os

_root = os.path.dirname(os.path.abspath(__file__))


def _read():
    ip = os.environ.get("PS5_IP", "").strip()
    if ip:
        return ip
    for d in (os.getcwd(), _root):
        p = os.path.join(d, ".ps5_ip")
        if os.path.isfile(p):
            return open(p).read().strip().splitlines()[0].strip()
    raise SystemExit("Set the console address: export PS5_IP=<ip> (or put it in a file named .ps5_ip next to the scripts).")


PS5_IP = _read()
