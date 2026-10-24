#!/usr/bin/env python3
"""Reverse debug channel server for the PS5 app. The app dials out to this PC on TCP 9998.
  python dbg.py serve            run the listener (logs to dbg.log, control port 127.0.0.1:9997)
  python dbg.py <cmd...>         send one command through the running server, e.g.
       dbg.py ping | ver | ls /data/opengoal/log | tail /data/opengoal/log/ps5.log 4000
       dbg.py get /remote/path local | put local /remote/path | rm /remote/path | exit
"""
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
state = {"c": None}
lock = threading.Lock()
replies = []
cv = threading.Condition()


def rd_line(s):
    b = b""
    while True:
        c = s.recv(1)
        if not c:
            raise EOFError
        if c == b"\n":
            return b.decode(errors="replace")
        b += c


def rd_n(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(min(1 << 20, n - len(b)))
        if not c:
            raise EOFError
        b += c
    return b


def next_reply(timeout=20):
    with cv:
        if not cv.wait_for(lambda: replies, timeout):
            raise TimeoutError("no reply")
        return replies.pop(0)


def handle(k):
    line = rd_line(k)
    with lock:
        c = state["c"]
    if not c:
        k.sendall(b"E ps5 not connected\n")
        return
    parts = line.split(" ", 2)
    with cv:
        replies.clear()
    if parts[0] == "put":  # put <local> <remote>
        data = open(parts[1], "rb").read()
        c.sendall(f"put {parts[2]} {len(data)}\n".encode())
        c.sendall(data)
        k.sendall((next_reply(120)[0] + "\n").encode())
        return
    c.sendall((line + "\n").encode())
    hdr, data = next_reply()
    k.sendall((hdr + "\n").encode())
    if data is not None:
        k.sendall(data)


def serve():
    logf = open(os.path.join(os.path.dirname(HERE), "out", "dbg.log"), "a", encoding="utf-8")

    def accept_ps5():
        ls = socket.socket()
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("0.0.0.0", 9998))
        ls.listen(2)
        while True:
            c, a = ls.accept()
            with lock:
                state["c"] = c
            print("ps5 connected", a, flush=True)
            try:
                while True:
                    ln = rd_line(c)
                    if ln.startswith("L "):
                        logf.write(ln[2:] + "\n")
                        logf.flush()
                    elif ln.startswith("R hello"):
                        pass
                    elif ln.startswith("B "):
                        data = rd_n(c, int(ln[2:]))
                        with cv:
                            replies.append((ln, data))
                            cv.notify_all()
                    else:
                        with cv:
                            replies.append((ln, None))
                            cv.notify_all()
            except Exception:
                pass
            with lock:
                state["c"] = None
            print("ps5 disconnected", flush=True)

    threading.Thread(target=accept_ps5, daemon=True).start()
    cs = socket.socket()
    cs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    cs.bind(("127.0.0.1", 9997))
    cs.listen(4)
    while True:
        k, _ = cs.accept()
        try:
            handle(k)
        except Exception as e:
            try:
                k.sendall(f"E {e}\n".encode())
            except Exception:
                pass
        k.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        serve()
    else:
        k = socket.create_connection(("127.0.0.1", 9997), timeout=90)
        args = ["shot"] + sys.argv[3:5] if sys.argv[1] == "shot" else (sys.argv[1:3] if sys.argv[1] == "get" else sys.argv[1:])
        k.sendall((" ".join(args) + "\n").encode())
        hdr = rd_line(k)
        if hdr.startswith("B "):
            data = rd_n(k, int(hdr[2:]))
            if sys.argv[1] == "shot":
                from PIL import Image
                import io
                name = sys.argv[2] if len(sys.argv) > 2 else "snap.png"
                Image.open(io.BytesIO(data)).save(name)
                print("saved", name)
            elif sys.argv[1] == "get" and len(sys.argv) > 3:
                open(sys.argv[3], "wb").write(data)
                print("saved", len(data))
            else:
                sys.stdout.buffer.write(data)
                print()
        else:
            print(hdr)
