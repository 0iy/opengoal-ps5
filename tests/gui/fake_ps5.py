#!/usr/bin/env python3
"""Fake console web server for GUI tests (127.0.0.1 only): GET /api/status -> {"version":3,...}. Usage: fake_ps5.py [port]"""
import http.server, sys

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"version":3,"ip":"127.0.0.1","busy":false,"games":{}}' if self.path == "/api/status" else b"{}"
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 18080), H).serve_forever()
