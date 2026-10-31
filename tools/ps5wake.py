#!/usr/bin/env python3
"""Turn the PS5 on from rest mode and start the jailbreak (YouTube app + ps5-y2jb-autoloader) without touching it.

  ps5wake.py status                  console state (on / standby / gone), payload ports, ps5key
  ps5wake.py wake                    Remote Play wake-up packet (needs "Turn on PS5 from network" in rest mode settings)
  ps5wake.py jb [--seq S]            wake if needed, press keys on the home screen, wait for ELF loader 9021 + FTP 2121
  ps5wake.py key NAME | seq S        send keys through ps5key (tools/ps5key, ESP32-S3 on a PS5 USB port)
  ps5wake.py diag                    ps5key USB state (mounted by the PS5 or not)
  ps5wake.py flash [COM3|--ota]      build and flash tools/ps5key: over USB on this PC, or over Wi-Fi (arduino-cli)

The wake credential is the Remote Play registration key of a Chiaki pairing (read from the Windows registry) or env
PS5_RP_KEY (8 hex digits). ps5key address: env PS5KEY_IP, else ps5key.local. Default key sequence "!6000,enter": the
home screen opens on the last used app, so start YouTube once by hand and it stays the first tile."""
import os, socket, subprocess, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ps5cfg import ip

HERE = os.path.dirname(os.path.abspath(__file__))
DDP_PORT = 9302  # PS5 device discovery (PS4: 987)
DDP_VER = "00030010"
ARDUINO = os.environ.get("ARDUINO_CLI", r"C:\Users\user\tools\arduino-cli\arduino-cli.exe")
FQBN = "esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=default"  # USB-OTG (TinyUSB), needed for the HID keyboard


def rp_key():
    k = os.environ.get("PS5_RP_KEY")
    if k:
        return k
    import winreg  # Chiaki (Qt) stores rp_regist_key as "@ByteArray(<8 hex chars><zero padding>)" in UTF-16
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Chiaki\Chiaki\registered_hosts\1") as h:
        raw = winreg.QueryValueEx(h, "rp_regist_key")[0]
    s = raw.decode("utf-16-le") if isinstance(raw, bytes) else raw
    return s.split("(", 1)[1].split("\0", 1)[0].rstrip(")")


def ddp(msg, wait=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(wait)
    try:
        s.sendto(msg.encode(), (ip(), DDP_PORT))
        return s.recvfrom(2048)[0].decode(errors="replace")
    except OSError:
        return ""
    finally:
        s.close()


def state():
    r = ddp(f"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{DDP_VER}\n")
    return "on" if " 200 " in r.split("\n", 1)[0] else "standby" if " 620 " in r.split("\n", 1)[0] else "gone"


def wake():
    cred = int(rp_key(), 16)
    ddp(f"WAKEUP * HTTP/1.1\nclient-type:vr\nauth-type:R\nmodel:w\napp-type:r\nuser-credential:{cred}\n"
        f"device-discovery-protocol-version:{DDP_VER}\n", wait=0.2)


def port_open(port, t=1.0):
    try:
        socket.create_connection((ip(), port), t).close()
        return True
    except OSError:
        return False


_key_ip = None


def key_host():
    """ps5key address; mDNS on Windows answers only now and then, so resolve with retries and keep the result."""
    global _key_ip
    if os.environ.get("PS5KEY_IP"):
        return os.environ["PS5KEY_IP"]
    for _ in range(10):
        if _key_ip:
            break
        try:
            _key_ip = socket.gethostbyname("ps5key.local")
        except OSError:
            time.sleep(1)
    return _key_ip or "ps5key.local"


def ps5key(path, timeout=40):
    with urllib.request.urlopen(f"http://{key_host()}{path}", timeout=timeout) as r:
        return r.read().decode()


def wait_for(cond, secs, what):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return True
        time.sleep(2)
    print(f"timeout waiting for {what} ({secs} s)")
    return False


def cmd_status():
    print("console:", state())
    print("ELF loader 9021:", port_open(9021), " FTP 2121:", port_open(2121))
    try:
        print("ps5key:", ps5key("/ping", 5))
    except OSError as e:
        print("ps5key: not reachable", e)


def cmd_jb(seq):
    if port_open(9021) and port_open(2121):
        print("payloads already running")
        return 0
    if state() != "on":
        print("waking the console")
        wake()
        if not wait_for(lambda: state() == "on", 90, "the console to wake"):
            return 1
    print("starting the jailbreak app:", seq)
    print(ps5key("/seq?s=" + urllib.parse.quote(seq)))
    ok = wait_for(lambda: port_open(9021) and port_open(2121), 300, "ELF loader 9021 and FTP 2121")  # WebKit autoloader needs about 2-4 min
    print("payloads up" if ok else "payloads did not come up: check the TV")
    return 0 if ok else 1


def cmd_flash(port):
    sketch = os.path.join(HERE, "ps5key")
    up = ["upload", "-p", port, "--fqbn", FQBN, sketch]
    if port == "--ota":  # over Wi-Fi, needs a running ps5key with OTA (firmware since /diag)
        up = ["upload", "-p", socket.gethostbyname(key_host()), "--protocol", "network", "--fqbn", FQBN, sketch]
    for args in (["compile", "--fqbn", FQBN, sketch], up):
        if subprocess.run([ARDUINO] + args).returncode:
            return 1
    print("flashed. Connect to Wi-Fi 'ps5key-setup', open http://192.168.4.1 and enter your Wi-Fi, then plug it into the PS5")
    return 0


def main(a):
    if not a:
        print(__doc__)
        return 0
    seq = a[a.index("--seq") + 1] if "--seq" in a else "!6000,enter"
    if a[0] == "status":
        cmd_status()
    elif a[0] == "wake":
        wake()
        print("wake-up sent; state now:", state())
    elif a[0] == "jb":
        return cmd_jb(seq)
    elif a[0] == "key":
        print(ps5key("/key?k=" + urllib.parse.quote(a[1])))
    elif a[0] == "seq":
        print(ps5key("/seq?s=" + urllib.parse.quote(a[1])))
    elif a[0] == "diag":
        print(ps5key("/diag", 5))
    elif a[0] == "flash":
        return cmd_flash(a[1] if len(a) > 1 else "COM3")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
