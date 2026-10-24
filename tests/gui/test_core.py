#!/usr/bin/env python3
"""Headless tests for gui/OpenGOAL-PS5-gui.py: ISO detection, progress parser, discovery, engine run (fake engine), optional Tk smoke.
Run: python tests/gui/test_core.py   (everything stays on 127.0.0.1, no console is contacted)"""
import importlib.util, os, subprocess, sys, tempfile, threading, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.update(OGPS5_PORT="18081", OGPS5_SCAN_PREFIX="127.0.0.", OGPS5_LANG="en", OGPS5_ENGINE=os.path.join(ROOT, "pc_import_fake.py"), FAKE_SLEEP="0.01")
spec = importlib.util.spec_from_file_location("ogui", os.path.join(ROOT, "gui", "OpenGOAL-PS5-gui.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
sys.path.insert(0, os.path.dirname(__file__)); import make_fake_iso

tmp = tempfile.mkdtemp()
def iso(name, boot, **k):
    p = os.path.join(tmp, name); make_fake_iso.make(p, boot, **k); return p

# detection
assert g.detect_iso(iso("a.iso", "SCUS_971.24")) == {"ok": True, "game": "jak1", "region": "NTSC-U", "serial": "SCUS-97124"}
assert g.detect_iso(iso("b.iso", "SCES_524.60"))["game"] == "jak3" and g.detect_iso(iso("c.iso", "SCUS_972.65"))["game"] == "jak2"
assert g.detect_iso(iso("d.iso", "SLUS_123.45"))["reason"] == "unknown"
open(os.path.join(tmp, "e.iso"), "wb").write(os.urandom(100000)); assert g.detect_iso(os.path.join(tmp, "e.iso"))["reason"] == "notiso"
assert g.detect_iso(os.path.join(tmp, "a.bin"))["reason"] == "notiso"
d = open(iso("f.iso", "SCUS_971.24"), "rb").read()[:20 * 2048]; open(os.path.join(tmp, "trunc.iso"), "wb").write(d)
assert g.detect_iso(os.path.join(tmp, "trunc.iso"))["reason"] == "trunc"

# parser
assert g.parse_line('{"phase":"upload","percent":50}')["percent"] == 50
assert g.parse_line("random log") is None and g.parse_line("{broken") is None and g.parse_line('{"x":1}') is None
assert "50%" in g.status_text({"phase": "upload", "percent": 50, "speed_bps": 3_000_000, "eta_s": 75, "message": "m"})
assert "2.9 MB/s" in g.status_text({"phase": "upload", "percent": 50, "speed_bps": 3_000_000, "eta_s": 75}) and "1:15" in g.status_text({"phase": "upload", "percent": 1, "eta_s": 75})
assert g.fmt_eta(3725) == "1:02:05"

# discovery against a fake console
srv = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "fake_ps5.py"), "18081"]); time.sleep(1)
try:
    assert g.find_ps5() == "127.0.0.1" and g.test_ps5("127.0.0.1")
    g.PORT = 18999; assert not g.test_ps5("127.0.0.1", 0.5); g.PORT = 18081
    # engine run: success and failure
    got = []; ok, n, why = g.run_queue(os.environ["OGPS5_ENGINE"], [("jak1", "a.iso"), ("jak2", "c.iso")], "127.0.0.1", lambda i, o: got.append((i, o)), lambda *a: None, threading.Event())
    assert (ok, n) == (2, 2) and got[-1][1]["phase"] == "done" and any(o["phase"] == "upload" and o["speed_bps"] for _, o in got)
    os.environ["FAKE_FAIL"] = "1"; ok, n, why = g.run_queue(os.environ["OGPS5_ENGINE"], [("jak1", "a.iso")], "127.0.0.1", lambda *a: None, lambda *a: None, threading.Event())
    assert ok == 0 and "connection refused" in why and g.hint(why) == g.T("hint_conn"); del os.environ["FAKE_FAIL"]
    # cancel
    stop = threading.Event(); os.environ["FAKE_SLEEP"] = "0.2"; threading.Timer(0.8, stop.set).start()
    t0 = time.time(); ok, n, why = g.run_queue(os.environ["OGPS5_ENGINE"], [("jak1", "a.iso")], "127.0.0.1", lambda *a: None, lambda *a: None, stop)
    assert ok == 0 and time.time() - t0 < 4, "cancel too slow"; os.environ["FAKE_SLEEP"] = "0.01"
    # Tk smoke: build the UI, run the fake engine for a few seconds, read the label texts
    try:
        import tkinter as tk
        orig = tk.Tk.mainloop
        def ml(self):
            def dump():
                def walk(w): return ([w.cget("text")] if w.winfo_class() == "Label" else []) + [x for c in w.winfo_children() for x in walk(c)]
                print("TK labels:", [x for x in walk(self) if x]); self.destroy()
            self.after(5000, dump); orig(self)
        tk.Tk.mainloop = ml
        os.environ["OGPS5_AUTOSTART"] = "1"; os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
        g.HOME = tmp; g.CFG = os.path.join(tmp, "config.json"); g.save_ip("127.0.0.1")
        g.main([os.path.join(tmp, "a.iso"), os.path.join(tmp, "d.iso")])
    except ImportError:
        print("tkinter missing: Tk smoke skipped")
finally:
    srv.kill()
print("OK")
