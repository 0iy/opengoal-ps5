"""Console address for all tools: env PS5_IP, else the first line of .ps5_ip in the repository root (git-ignored), else an error with the fix."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read():
    ip = os.environ.get("PS5_IP", "").strip()
    if ip:
        return ip
    for d in (os.getcwd(), ROOT):
        p = os.path.join(d, ".ps5_ip")
        if os.path.isfile(p):
            return open(p).read().strip().splitlines()[0].strip()
    raise SystemExit("Set the console address: export PS5_IP=<ip> (or put it in a file named .ps5_ip in the repository root).")


def ip():
    """Console address; raises SystemExit with the fix when it is not configured."""
    return _read()


def __getattr__(name):  # `from ps5cfg import PS5_IP` still works, resolved on first use
    if name == "PS5_IP":
        return _read()
    raise AttributeError(name)
