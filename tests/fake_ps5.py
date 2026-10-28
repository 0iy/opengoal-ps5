"""Fake PS5 for the ps5_setup tests: everything listens on 127.0.0.1 on ephemeral ports. Never touches a real console.

A loader that records the ELF bytes it receives and then "opens" what that ELF stands for after a delay (the payload kind is read from a
FAKE:<kind> tag inside the bytes), fake ftpsrv/shsrv banners, and an agent that implements the ogagent HTTP contract with the token check."""
import http.server, json, os, socket, socketserver, threading, time, urllib.parse

APP = "/data/homebrew/LAPY77001"
MARKER = b"OGAGENT_TOKEN:"
KEYS = ["loader", "loader2", "ftp", "shsrv", "debug", "dbg_klog", "web", "agent", "eta_ftp", "eta_klog", "eta_pkg", "eta_webui", "eta_rpc", "smp_api"]


def reserve():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # a killed client resets its connection: not interesting


class HttpServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def run(server):
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


class FakeConsole:
    def __init__(self, delay=0.3, put_delay=0.0, firmware="13.60"):
        self.p = {k: reserve() for k in KEYS}
        self.delay, self.put_delay, self.firmware = delay, put_delay, firmware
        self.servers, self.lock = {}, threading.Lock()
        self.received = []          # (kind, bytes) in arrival order
        self.kstuff = self.smp = self.app_running = False
        self.extra_procs = []       # e.g. ["onionhen"]
        self.stuck = False          # a suspended copy of the app (process state STOP) that blocks every launch
        self.token = None
        self.files, self.dirs, self.puts, self.log_lines = {}, set(), [], []
        self.modes = {}             # path -> mode string of the last PUT
        self.shell_cmds, self.t0 = [], time.time()
        self.ftp_banner = None
        self.shell = False
        self.agent_req = 0
        self.launches = []

    # ---- arguments for ps5_setup
    def ports_arg(self):
        return ",".join("%s=%d" % kv for kv in self.p.items())

    def base_args(self):
        return ["--ip", "127.0.0.1", "--ports", self.ports_arg(), "--interval", "0.2", "--settle", "0.3", "--no-color", "--yes", "--lang", "en",
                "--ddp-port", "0", "--launch-timeout", "3"]

    # ---- lifecycle
    def start(self, name, server):
        self.servers[name] = run(server)

    def stop(self, name):
        s = self.servers.pop(name, None)
        if s:
            s.shutdown()
            s.server_close()

    def close(self):
        for n in list(self.servers):
            self.stop(n)

    def is_up(self, name):
        return name in self.servers

    # ---- loader
    def open_loader(self):
        console = self

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                data = b""
                self.request.settimeout(10)
                try:
                    while True:
                        b = self.request.recv(65536)
                        if not b:
                            break
                        data += b
                except OSError:
                    pass
                console.on_elf(data)

        self.start("loader", TcpServer(("127.0.0.1", self.p["loader"]), H))

    def on_elf(self, data):
        if not data:
            return  # a bare connect (port probe) carries no payload
        kind = "unknown"
        for k in ("agent", "kstuff", "smp", "ftpsrv", "scan"):
            if b"FAKE:" + k.encode() in data:
                kind = k
        self.received.append((kind, data))
        effect = {"agent": self.fx_agent, "kstuff": self.fx_kstuff, "smp": self.fx_smp, "ftpsrv": self.open_ftp}.get(kind)
        if effect:
            threading.Timer(self.delay, effect, [data] if kind == "agent" else []).start()

    def fx_kstuff(self):
        self.kstuff = True

    def fx_smp(self):
        self.smp = True

    def fx_agent(self, data):
        i = data.index(MARKER) + len(MARKER)
        self.start_agent(data[i:i + 32].decode())

    # ---- ftp / shell
    def open_ftp(self, banner=None):
        banner = banner or self.ftp_banner or b"220-Welcome to ftpsrv.elf running on pid 7\r\n220-Version: test\r\n220 Service is ready\r\n"
        self.ftp_banner = banner

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.sendall(banner)
                time.sleep(0.2)

        self.start("ftp", TcpServer(("127.0.0.1", self.p["ftp"]), H))

    def open_shell(self):
        console = self
        self.shell = True

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                r = self.request
                r.settimeout(3)
                r.sendall(b"\xff\xfb\x01/$ ")
                buf = b""
                try:
                    while True:
                        b = r.recv(1024)
                        if not b:
                            return
                        buf += b
                        while b"\n" in buf:
                            line, _, buf = buf.partition(b"\n")
                            cmd = line.strip().decode()
                            if not cmd or cmd.startswith("\xff"):
                                continue
                            console.shell_cmds.append(cmd)
                            if cmd == "ps":
                                out = "".join("%5d %5d %5d %5d 0 4800000000000028 Native SELF SLEEP 000d %6d %s\r\n" % (i + 1, 1, 1, 1, 40000 + i, n)
                                              for i, n in enumerate(console.proc_names()))
                                r.sendall(out.encode() + b"/$ ")
                            else:
                                r.sendall(b"unknown command\r\n/$ ")
                except OSError:
                    pass

        self.start("shsrv", TcpServer(("127.0.0.1", self.p["shsrv"]), H))

    # ---- processes
    def proc_names(self):
        n = ["SceShellCore", "SceSpZeroConf"]
        if self.smp:
            n.append("shadowmountplus.elf")
        if self.kstuff:
            n.append("kstuff")
        if self.app_running:
            n.append("eboot.bin")
        return n + list(self.extra_procs)

    def procs(self):
        out = [{"pid": 100 + i, "name": n, "title": ""} for i, n in enumerate(self.proc_names())]
        for p in out:
            if p["name"] == "eboot.bin":
                p["title"] = "LAPY77001"
            p["stopped"] = False
        if self.stuck:
            out.append({"pid": 1883, "name": "eboot.bin", "title": "LAPY77001", "stopped": True})
        return out

    # ---- the app
    def start_app(self):
        if self.app_running:
            return

        console = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                body = json.dumps({"install_api": 1, "max_frame": 16777216, "busy": False, "app": console.files.get(APP + "/VERSION", b"").decode().strip(),
                                   "formats": {}}).encode() if self.path == "/api/info" else b"{}"
                self.send_response(200 if self.path == "/api/info" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.app_running = True
        self.start("web", HttpServer(("127.0.0.1", self.p["web"]), H))

    def stop_app(self):
        self.app_running = False
        self.stop("web")

    # ---- the agent
    def start_agent(self, token):
        console = self
        self.token = token

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def reply(self, code, body=b"", ctype="application/json"):
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def allowed(self, path):  # ogagent.c path_ok: absolute, no trailing slash, strictly below one of the two roots
                return not path.endswith("/") and (path.startswith(APP + "/") or path.startswith("/data/opengoal/"))

            def handle_any(self):
                console.agent_req += 1
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                if self.headers.get("X-OG-Token") != console.token:
                    return self.reply(401, {"error": "token"})
                m, p = self.command, u.path
                if m == "GET" and p == "/v1/status":
                    eb = console.files.get(APP + "/eboot.bin")  # same layout as h_status in payloads/ogagent.c
                    return self.reply(200, {"ok": True, "agent": {"version": "1", "uptime_s": int(time.time() - console.t0), "lifetime_left_s": 3000, "launched": False},
                                            "system": {"kernel": "FreeBSD", "firmware": console.firmware, "uptime_s": 99}, "processes": console.procs(),
                                            "tcp_ports_open": [], "mounts": [{"path": "/data", "type": "ufs", "free_bytes": 1 << 40, "total_bytes": 1 << 41}],
                                            "paths": {"app_dir_exists": True, "data_dir_exists": True, "eboot_size": len(eb) if eb is not None else -1},
                                            "app": {"title": "LAPY77001", "running": console.app_running, "app_id": 1}, "caps": {"write_data": True, "launch": True}})
                if p in ("/v1/file", "/v1/rm") and not self.allowed(q.get("path", "")):
                    return self.reply(403, {"error": "path"})
                if m == "PUT" and p == "/v1/file":
                    if int(q.get("size", -1)) != len(body):
                        return self.reply(400, {"error": "size"})
                    if console.put_delay:
                        time.sleep(console.put_delay)
                    with console.lock:
                        console.files[q["path"]] = body
                        console.puts.append(q["path"])
                        console.modes[q["path"]] = q.get("mode", "0644")
                    return self.reply(200, {"ok": True, "size": len(body)})
                if m == "GET" and p == "/v1/file":
                    d = console.files.get(q["path"])
                    return self.reply(200, d, "application/octet-stream") if d is not None else self.reply(404, {"error": "none"})
                if m == "POST" and p == "/v1/mkdir":
                    return self.reply(200, {"ok": True}) if q["path"] == APP or self.allowed(q["path"]) else self.reply(403, {"error": "path"})
                if m == "POST" and p == "/v1/rm":
                    console.files.pop(q["path"], None)
                    return self.reply(200, {"ok": True})
                if m == "POST" and p == "/v1/launch":
                    ok = (APP + "/eboot.bin") in console.files and console.kstuff and console.smp and not any("onion" in x for x in console.extra_procs)
                    if ok:
                        threading.Timer(console.delay, console.start_app).start()
                    console.launches.append(ok)
                    return self.reply(200, {"ok": True, "title": "LAPY77001", "launch": 0}) if ok else self.reply(500, {"ok": False, "launch": -2146435064})
                if m == "POST" and p == "/v1/kill":
                    console.stop_app()
                    return self.reply(200, {"ok": True})
                if m == "GET" and p == "/v1/log":
                    return self.reply(200, {"ok": True, "lines": console.log_lines})
                if m == "POST" and p == "/v1/shutdown":
                    self.reply(200, {"ok": True})
                    threading.Timer(0.1, console.stop, ["agent"]).start()
                    return
                self.reply(404, {"error": "unknown"})

            do_GET = do_PUT = do_POST = handle_any

        self.start("agent", HttpServer(("127.0.0.1", self.p["agent"]), H))
