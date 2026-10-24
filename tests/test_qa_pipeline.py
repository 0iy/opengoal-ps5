"""Offline tests for qa_pipeline.py (fake logs and images). Run: python -m unittest tests/test_qa_pipeline.py"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import qa_pipeline as Q  # noqa: E402


def scene(seed=1, h=270, w=480):
    r = np.random.RandomState(seed)
    base = r.randint(40, 200, (h // 10, w // 10, 3)).astype(np.uint8)
    img = np.kron(base, np.ones((10, 10, 1), np.uint8))
    img[:h // 10] = r.randint(0, 255, (h // 10, w, 3))  # busy top band (HUD)
    img[-h // 10:] = r.randint(0, 255, (h // 10, w, 3))
    return img


def log(fps, over33=0, over20=2, ts=False, n_ft=None):
    L = []
    for i, f in enumerate(fps):
        p = "10:00:%02d " % (i * 3 % 60) if ts else ""
        L.append("%sfps: %.1f  (swap 0.1 ms, render 10.0 ms per frame)" % (p, f))
        L.append("%sframetime: max 30.0 ms, frames over 20 ms: %d, over 33 ms: %d (of 170)" % (p, over20, over33))
    return L


def write_run(d, game, fps, over33=0, shots=(), trace=None, crash=None, secs=30):
    g = os.path.join(d, game)
    os.makedirs(g, exist_ok=True)
    L = ["opengoal-ps5: start"] + log(fps, over33) + ([crash] if crash else [])
    open(os.path.join(g, "udp.log"), "w").write("\n".join(L))
    for i, im in enumerate(shots):
        Image.fromarray(im).save(os.path.join(g, "shot_%d.png" % i))
    if trace:
        with open(os.path.join(g, "trace.txt"), "w") as f:
            f.write(trace)


TRACE = "frames 300, average frame 16.70 ms (59.9 fps)\ndriver draw_vbo                  8.60    530.0\nper draw (us): total 20.1 | glfix 3.0 | Mesa 4.0 | driver 9.6 | hand-over 1.0\n"
CFG = {"jak2": {"secs": 30, "warm": 0.4, "shots": [{"name": "a", "t": 5}, {"name": "b", "t": 9}]}}


class T(unittest.TestCase):
    def test_log_stats(self):
        s = Q.log_stats(log([20, 20, 60, 60, 60, 60, 60, 60, 60, 59], over33=1, over20=3), 0.4, 40)
        self.assertAlmostEqual(s["fps_avg"], 59.83, 1)
        self.assertEqual(s["over33_per3s"], 1.0)
        self.assertEqual(s["silent"], [])

    def test_silent_return(self):
        s = Q.log_stats(log([60, 60]), 0.4, 90)
        self.assertTrue(s["silent"])
        s = Q.log_stats(log([60] * 5, ts=True) + ["10:01:00 launcher: GL 4.6"], 0.4, 30)
        self.assertTrue(s["silent"])

    def test_crash_patterns(self):
        self.assertTrue(Q.find_crash(["x", "CRASH signal 11", "# fault address 0x0"]))
        self.assertTrue(Q.find_crash(["sceSblAuthMgrAuthHeader returned unexpected error 46"]))
        self.assertFalse(Q.find_crash(["killapp: ForceKillApp=0x80940004", "description of things", "glfix: draws 12"]))

    def test_trace_parse(self):
        t = Q.parse_trace(TRACE)
        self.assertEqual((t["driver_ms_frame"], t["driver_us_draw"]), (8.6, 9.6))

    def test_glitch_absolute(self):
        a = scene()
        self.assertEqual(Q.glitch_checks(a), [])
        self.assertEqual(Q.glitch_checks(np.zeros_like(a))[0][0], "FAIL")
        self.assertTrue(any("white" in m for _, m in Q.glitch_checks(np.full_like(a, 255))))
        mg = np.zeros_like(a)
        mg[..., 0] = mg[..., 2] = 255
        self.assertTrue(Q.glitch_checks(mg))
        self.assertTrue(Q.glitch_checks(np.full_like(a, 90)))

    def test_glitch_relative(self):
        g = scene()
        r = g.copy()
        r[:, :] = 90
        r[:20] = g[:20]
        self.assertTrue(any("uniform" in m for _, m in Q.glitch_checks(r, g)))
        r2 = g.copy()
        r2[:27] = 100  # HUD bands flat
        r2[-27:] = 100
        self.assertTrue(any("UI" in m for _, m in Q.glitch_checks(r2, g)))

    def test_mask_ignores_noise_flags_glitch(self):
        a = scene()
        a2 = a.copy()
        a2[100:130, 100:160] = 255 - a2[100:130, 100:160]  # animated region
        mask, raw = Q.learn_mask(a, a2)
        self.assertTrue(mask[110, 120] and mask[100:130, 100:160].all() and raw > 0)
        run = a.copy()
        run[100:130, 100:160] = 7  # same region differs again: masked
        run[200:240, 300:380] = 255 - run[200:240, 300:380]  # glitch elsewhere
        c = Q.compare_shot(run, a, mask)
        self.assertEqual(len(c["regions"]), 1)
        self.assertEqual(c["regions"][0][:2], (300, 200))
        self.assertEqual(Q.compare_shot(a, a, mask)["pct"], 0.0)

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            qa, root = os.path.join(d, "qa"), os.path.join(d, "runs")
            os.makedirs(qa)
            with open(os.path.join(qa, "scenarios.json"), "w") as f:
                json.dump({"quick": CFG}, f)
            A, A2 = scene(), scene()
            A2[50:80, 50:100] = 255 - A2[50:80, 50:100]
            for r, im in (("run1", A), ("run2", A2)):
                write_run(os.path.join(root, r), "jak2", [20, 30] + [60] * 8, shots=[im, im], trace=TRACE)
            self.assertEqual(Q.main(["--analyze", root, "--qa-dir", qa, "--games", "jak2", "--update-baseline"]), 0)
            with open(os.path.join(qa, "baseline.json")) as f:
                base = json.load(f)
            self.assertIn("fps_rel", base["modes"]["quick"]["jak2"]["noise"])
            self.assertTrue(os.path.exists(os.path.join(qa, "golden", "quick", "jak2_0.mask.png")))
            # same build again -> PASS
            r3 = os.path.join(d, "r3")
            write_run(os.path.join(r3, "run1"), "jak2", [20, 30] + [59] * 8, shots=[A2, A], trace=TRACE)
            self.assertEqual(Q.main(["--analyze", r3, "--qa-dir", qa, "--games", "jak2"]), 0)
            # regression: fps drop, more long frames, driver slower, glitch region, crash line
            r4 = os.path.join(d, "r4")
            bad = A.copy()
            bad[150:230, 200:400] = 255 - bad[150:230, 200:400]
            write_run(os.path.join(r4, "run1"), "jak2", [20, 30] + [40] * 8, over33=6, shots=[bad, A], trace=TRACE.replace("8.60", "12.0"), crash="CRASH signal 11")
            self.assertEqual(Q.main(["--analyze", r4, "--qa-dir", qa, "--games", "jak2"]), 2)
            rep = os.listdir(os.path.join(qa, "reports"))
            self.assertTrue(rep)
            # missing baseline -> WARN
            self.assertEqual(Q.main(["--analyze", r3, "--qa-dir", os.path.join(d, "none"), "--games", "jak2"]), 1)
            # baseline refuses a crashed run
            self.assertEqual(Q.main(["--analyze", r4, "--qa-dir", os.path.join(d, "q2"), "--games", "jak2", "--update-baseline"]), 2)

    def test_dry_run(self):
        self.assertEqual(Q.main(["--dry-run", "--full"]), 0)


if __name__ == "__main__":
    unittest.main()
