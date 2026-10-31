"""Offline tests of the console tools' parsing (ps5live, ps5repl, ps5scene); no console and no WSL needed."""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ps5live as L
import ps5repl as R
import ps5scene as S

LOG = "\n".join(
    ["12:00:0%d fps: %d.0  (swap 0.1 ms, render %d.0 ms per frame, thread cpu 16.0 ms per frame)" % (i, f, 1000 // f) for i, f in enumerate((60, 58, 30, 59))]
    + ["frametime: max 40.0 ms, frames over 20 ms: 4, over 33 ms: 1 (of 100)",
       "ptree:  20.00 ms root", "ptree:  19.90 ms buckets", "ptree:   9.00 ms [205] merc-l2-pris", "ptree:   2.00 ms [313] particles",
       "blit: software blits=3 12.0 ms: [mask10 fmt279>279 1920x1080>1920x1080 s4 n=3 12.0ms]",
       "clear: [buf7 1920x1080 cb1 path2 n=2 0.1ms max 0.1ms]"]) + "\n"


class Tools(unittest.TestCase):
    def test_summary(self):
        out = "\n".join(L.summary_lines(1 << 20, LOG, 10))
        self.assertIn("4 fps samples", out)
        self.assertIn("min 30", out)
        self.assertIn("merc-l2-pris", out)
        self.assertIn("mask10 fmt279>279 1920x1080>1920x1080 s4", out)
        self.assertIn("path2", out)

    def test_repl_noise_filter(self):
        self.assertTrue(R.NOISE.match("[ 50%] [group   ]"))
        self.assertTrue(R.NOISE.match("0        #x0              0.0000        0"))
        self.assertFalse(R.NOISE.match("hello from ps5 42"))
        self.assertEqual(R.ANSI.sub("", "\x1b[1mhi\x1b[0m"), "hi")

    def test_scene_compare(self):
        rows = [dict(scene="city_idle", label=l, time="t", fps_median=m, fps_p5=m - 2, cpu_ms=c, over33_pct=0.5, hot="", fps_min=m - 3, crash=False)
                for l, m, c in (("a", 50, 18.0), ("b", 57, 16.0))]
        with tempfile.TemporaryDirectory() as d:
            S.OUT = os.path.join(d, "r.jsonl")
            open(S.OUT, "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                S.compare("city_idle")
            self.assertIn("fps median 50 -> 57", buf.getvalue())

    def test_teleport_and_scene_defs(self):
        self.assertIn("move-to-point!", S.teleport((1.0, 2.0, 3.0)))
        for name, sc in S.SCENES.items():
            self.assertTrue(sc["steps"], name)


if __name__ == "__main__":
    unittest.main()
