#!/usr/bin/env python3
"""Offline tests for installer/ps5_setup.py. Everything runs against fake consoles on 127.0.0.1 (tests/fake_ps5.py); no real address is contacted.
Run: python tests/test_ps5_setup.py"""
import argparse, contextlib, functools, hashlib, http.server, io, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "installer", "ps5_setup.py")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(SCRIPT))
import fake_ps5
import ps5_setup as S

MARKER = S.MARKER
AGENT = b"\x7fELF" + b"FAKE:agent" + os.urandom(400) + MARKER + b"x" * 32 + os.urandom(300)


def mac(sep, parts=("a4", "b5", "c6", "01", "02", "03")):
    return sep.join(parts)


def fake_elf(kind, size=3000):
    return b"\x7fELF\x02\x01\x01" + b"FAKE:" + kind.encode() + os.urandom(size)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ogtest-")
        self.home = os.path.join(self.tmp, "home")
        os.environ["OGPS5_HOME"] = self.home
        os.environ.pop("PS5_IP", None)
        self.c = fake_ps5.FakeConsole()
        # the app: eboot.bin, param.json, 40 assets and one bigger file
        self.app = os.path.join(self.tmp, "app", "LAPY77001")
        self.local = {"eboot.bin": os.urandom(50000), "sce_sys/param.json": b'{"titleId":"LAPY77001"}', "assets/big.bin": os.urandom(1500000)}
        for i in range(40):
            self.local["assets/d%d/f%d.dat" % (i % 4, i)] = os.urandom(300 + i)
        for rel, data in self.local.items():
            p = os.path.join(self.app, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data)
        # payloads served by a local http server, pinned in a table
        self.srv_dir = os.path.join(self.tmp, "srv")
        os.makedirs(self.srv_dir)
        self.http = fake_ps5.run(fake_ps5.HttpServer(("127.0.0.1", 0), functools.partial(Quiet, directory=self.srv_dir)))
        self.payload("kstuff")
        self.payload("smp")
        self.agent_elf = os.path.join(self.tmp, "ogagent.elf")
        open(self.agent_elf, "wb").write(AGENT)
        self.scan_elf = os.path.join(self.tmp, "scan.elf")
        open(self.scan_elf, "wb").write(fake_elf("scan"))

    def payload(self, key, pin=None):
        data = fake_elf(key)
        open(os.path.join(self.srv_dir, key + ".elf"), "wb").write(data)
        self.table = getattr(self, "table", {})
        self.table[key] = {"url": "http://127.0.0.1:%d/%s.elf" % (self.http.server_address[1], key), "size": len(data),
                           "sha256": pin or hashlib.sha256(data).hexdigest()}
        self.table_path = os.path.join(self.tmp, "table.json")
        json.dump(self.table, open(self.table_path, "w"))

    def tearDown(self):
        self.c.close()
        self.http.shutdown()
        self.http.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def args(self, extra=(), ip=True):
        a = self.c.base_args()
        if not ip:
            del a[:2]
        return a + ["--agent-elf", self.agent_elf, "--app", self.app, "--payload-table", self.table_path, "--scan-elf", self.scan_elf, "--flush", "5",
                    "--max-wait", "40"] + list(extra)

    def run_setup(self, extra=(), ip=True):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = S.main(self.args(extra, ip))
        return rc, buf.getvalue()

    def kinds(self):
        return [k for k, _ in self.c.received]

    def app_puts(self):
        return [p for p in self.c.puts if p.startswith(fake_ps5.APP + "/") and not p.endswith(S.MANIFEST)]

    def assert_tree(self):
        for rel, data in self.local.items():
            self.assertEqual(self.c.files.get(fake_ps5.APP + "/" + rel), data, rel)


class Parsing(unittest.TestCase):
    def test_token_patch_replaces_exactly_32_bytes(self):
        tok = "0123456789abcdef0123456789abcdef"
        out = S.patch_token(AGENT, tok)
        i = AGENT.index(MARKER) + len(MARKER)
        self.assertEqual(len(out), len(AGENT))
        self.assertEqual(out[:i], AGENT[:i])
        self.assertEqual(out[i:i + 32], tok.encode())
        self.assertEqual(out[i + 32:], AGENT[i + 32:])
        self.assertEqual([j for j in range(len(out)) if out[j] != AGENT[j]], [j for j in range(i, i + 32) if tok.encode()[j - i] != AGENT[j]])

    def test_token_patch_refuses_bad_input(self):
        with self.assertRaises(S.Fail):
            S.patch_token(b"\x7fELF" + MARKER, "0" * 32)  # marker without its 32 filler bytes
        with self.assertRaises(S.Fail):
            S.patch_token(AGENT + MARKER + b"x" * 32, "0" * 32)  # two markers
        with self.assertRaises(ValueError):
            S.patch_token(AGENT, "short")

    def test_ipconfig(self):
        en = ("Ethernet adapter Ethernet:\n\n   Connection-specific DNS Suffix  . :\n   IPv4 Address. . . . . . . . . . . : 192.0.2.10(Preferred)\n"
              "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\n   Default Gateway . . . . . . . . . : 192.0.2.1\n")
        de = ("Ethernet-Adapter Ethernet:\n\n   IPv4-Adresse  . . . . . . . . . . : 198.51.100.20\n   Subnetzmaske  . . . . . . . . . . : 255.255.254.0\n"
              "   Standardgateway . . . . . . . . . : 198.51.100.1\n")
        self.assertEqual(S.parse_ipconfig(en), [("192.0.2.10", 24)])
        self.assertEqual(S.parse_ipconfig(de), [("198.51.100.20", 23)])

    def test_ip_addr_ifconfig_and_networks(self):
        ipa = ("1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n2: eth0    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth0\\ x\n"
               "3: wlan0    inet 198.51.100.77/26 brd 198.51.100.127 scope global wlan0\n4: wide    inet 203.0.113.9/16 scope global x\n")
        pairs = S.parse_ip_addr(ipa)
        self.assertEqual(pairs[1], ("192.0.2.10", 24))
        nets = [str(n) for n, _ in S.normalize_networks(pairs + pairs)]
        self.assertEqual(nets, ["192.0.2.0/24", "198.51.100.64/26", "203.0.113.0/24"])  # loopback dropped, /16 cut to /24, duplicates merged
        lin = "eth0: flags=4163<UP>  mtu 1500\n        inet 192.0.2.10  netmask 255.255.255.0  broadcast 192.0.2.255\n"
        mac_os = "en0: flags=8863<UP>\n\tinet 192.0.2.77 netmask 0xffffff00 broadcast 192.0.2.255\n\tinet6 fe80::1 prefixlen 64\n"
        old = "eth0      inet addr:192.0.2.5  Bcast:192.0.2.255  Mask:255.255.255.0\n"
        self.assertEqual(S.parse_ifconfig(lin), [("192.0.2.10", 24)])
        self.assertEqual(S.parse_ifconfig(mac_os), [("192.0.2.77", 24)])
        self.assertEqual(S.parse_ifconfig(old), [("192.0.2.5", 24)])

    def test_arp(self):
        win = ("Interface: 192.0.2.10 --- 0x5\n  Internet Address      Physical Address      Type\n  192.0.2.1             %s     dynamic\n"
               "  192.0.2.255           %s     static\n  224.0.0.22            %s     static\n" % (mac("-"), mac("-", ["ff"] * 6), mac("-", ["01", "00", "5e", "00", "00", "16"])))
        lin = "? (192.0.2.1) at %s [ether] on eth0\n? (192.0.2.50) at <incomplete> on eth0\n" % mac(":")
        osx = "? (192.0.2.7) at a4:b5:c6:1:2:3 on en0 ifscope [ethernet]\n? (192.0.2.8) at (incomplete) on en0 ifscope [ethernet]\n"
        want = mac(":").upper()
        self.assertEqual(S.parse_arp(win), {"192.0.2.1": want})
        self.assertEqual(S.parse_arp(lin), {"192.0.2.1": want})
        self.assertEqual(S.parse_arp(osx), {"192.0.2.7": want})

    def test_oui_and_score(self):
        st = {"open": {k: False for k in S.PORTS}, "agent": None, "agent_locked": False, "app": None, "ftpsrv": False, "shell": False, "web_other": True}
        sony = mac(":", ["F4", "64", "12", "01", "02", "03"])
        s, why = S.score(st, sony, None)
        self.assertEqual(s, 1 + 4)
        self.assertLess(S.score(st, None, None)[0], 3)  # a web server alone is not a console
        s, _ = S.score(st, None, {"host-type": "PS5", "state": "standby"})
        self.assertGreaterEqual(s, 3)

    def test_plan_is_deterministic(self):
        def st(**kw):
            base = {"app": None, "loader": True, "agent": None, "procs": None, "smp": False, "kstuff": "unknown", "onion": False, "open": {"ftp": False}}
            base.update(kw)
            return base
        o = argparse.Namespace(no_agent=False, update=False, with_kstuff=True)
        up = {"agent": {}, "procs": ["x"]}
        cases = [
            (st(), o, set(), ["agent", "kstuff", "smp", "upload", "launch"]),
            (st(loader=False), o, set(), ["loader", "agent", "kstuff", "smp", "upload", "launch"]),
            (st(**up), o, set(), ["kstuff", "smp", "upload", "launch"]),
            (st(smp=True, kstuff="inferred", **up), o, set(), ["upload", "launch"]),
            (st(onion=True, **up), o, set(), ["smp", "upload", "launch"]),
            (st(**up), argparse.Namespace(no_agent=False, update=False, with_kstuff=None), set(), ["smp", "upload", "launch"]),
            (st(app={"install_api": 1}), o, set(), []),
            (st(app={"install_api": 1}, smp=True, **up), argparse.Namespace(no_agent=False, update=True, with_kstuff=None), {"upload"}, ["launch"]),
        ]
        for state, opts, done, want in cases:
            for _ in range(3):
                self.assertEqual(S.make_plan(state, opts, done), want)

    def test_ddp_probe(self):
        got = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))

        def serve():
            data, addr = sock.recvfrom(2048)
            got.append(data)
            sock.sendto(b"HTTP/1.1 620 Server Standby\nhost-type:PS5\nhost-name:Test\nsystem-version:0\nhost-request-port:997\n", addr)

        t = threading.Thread(target=serve)
        t.start()
        res = S.ddp_probe(["127.0.0.1"], sock.getsockname()[1], wait=1.0)
        t.join()
        sock.close()
        self.assertEqual(got, [b"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n"])
        self.assertEqual(res["127.0.0.1"]["state"], "standby")
        self.assertEqual(res["127.0.0.1"]["host-type"], "PS5")


class ReleaseFetch(Base):
    def stub(self):
        import types
        return types.SimpleNamespace(ui=S.UI("en", S.Log(), 0))

    def serve_release(self, sums_hash=None):
        import zipfile
        z = os.path.join(self.srv_dir, "OpenGOAL-PS5.zip")
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("OpenGOAL-PS5/app/LAPY77001/eboot.bin", b"eboot")
        h = sums_hash or hashlib.sha256(open(z, "rb").read()).hexdigest()
        open(os.path.join(self.srv_dir, "SHA256SUMS"), "w").write("%s  OpenGOAL-PS5.zip\n" % h)
        return "http://127.0.0.1:%d" % self.http.server_address[1]

    def test_release_is_fetched_and_verified(self):
        app = S.fetch_release(self.stub(), self.serve_release())
        self.assertEqual(open(os.path.join(app, "eboot.bin"), "rb").read(), b"eboot")

    def test_release_with_wrong_checksum_is_refused(self):
        with self.assertRaises(S.Fail):
            S.fetch_release(self.stub(), self.serve_release("0" * 64))
        self.assertFalse(os.path.exists(os.path.join(self.home, "release")))

    def test_real_agent_elf_has_exactly_one_marker(self):
        elf = os.path.join(HERE, "..", "payloads", "ogagent.elf")
        if not os.path.exists(elf):
            self.skipTest("payloads/ogagent.elf not built")
        data = open(elf, "rb").read()
        out = S.patch_token(data, "f" * 32)
        self.assertEqual((len(out), sum(a != b for a, b in zip(data, out))), (len(data), 32))


class Fingerprints(Base):
    def ident(self):
        ports = self.c.p
        opened = S.sweep(["127.0.0.1"], ports.values(), timeout=0.5).get("127.0.0.1", set())
        return S.identify("127.0.0.1", ports, opened, None, want_ps=True)

    def test_banners_and_read_only_shell(self):
        self.c.open_loader()
        self.c.open_ftp()
        self.c.open_shell()
        self.c.smp = True
        st = self.ident()
        self.assertTrue(st["ftpsrv"] and st["shell"] and st["loader"])
        self.assertIn("SceShellCore", " ".join(st["procs"]))
        self.assertTrue(st["smp"])
        self.assertEqual(st["kstuff"], "inferred")
        self.assertEqual(set(self.c.shell_cmds), {"ps"})  # nothing but ps was ever typed into the shell

    def test_other_ftp_is_not_ftpsrv(self):
        self.c.open_ftp(b"220 ProFTPD ready\r\n")
        st = self.ident()
        self.assertFalse(st["ftpsrv"])
        self.assertTrue(st["open"]["ftp"])

    def test_web_server_of_someone_else(self):
        self.c.start_app()
        self.c.stop_app()  # app gone: nothing answers
        self.assertIsNone(self.ident()["app"])


class EndToEnd(Base):
    def test_fresh_console_with_loader_only(self):
        c = self.c
        c.open_loader()
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.kinds(), ["agent", "kstuff", "smp", "scan"])
        sent = c.received[0][1]
        i = AGENT.index(MARKER) + len(MARKER)
        self.assertEqual(len(sent), len(AGENT))
        self.assertTrue(all(sent[j] == AGENT[j] for j in range(len(AGENT)) if not i <= j < i + 32))
        self.assertEqual(sent[i:i + 32].decode(), c.token)
        self.assert_tree()
        puts = self.app_puts()
        self.assertEqual(puts[-1], fake_ps5.APP + "/eboot.bin")  # eboot.bin last
        self.assertEqual(sorted(set(puts)), sorted(fake_ps5.APP + "/" + r for r in self.local))
        self.assertIn(fake_ps5.APP + "/" + S.MANIFEST, c.files)
        self.assertEqual(c.files["/data/opengoal/config/ps5.cfg"], b"resolution=0\nrefresh=60\nlast_game=0\nlang=0\n")
        self.assertTrue(c.app_running)
        for _ in range(40):
            if not c.is_up("agent"):
                break
            time.sleep(0.1)
        self.assertFalse(c.is_up("agent"), "agent was not shut down")
        self.assertFalse(os.path.exists(os.path.join(self.home, "agent.token")))
        self.assertNotIn(c.token, open(os.path.join(self.home, "setup.log")).read())  # token is masked in the log
        self.assertEqual(json.load(open(os.path.join(self.home, "config.json")))["ps5"], "127.0.0.1")
        self.assertIn("http://127.0.0.1:%d" % c.p["web"], out)

    def test_second_run_on_a_finished_console_does_nothing(self):
        c = self.c
        c.kstuff = c.smp = True
        c.open_loader()
        c.start_app()
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(c.received, [])
        self.assertEqual((c.agent_req, c.puts), (0, []))
        self.assertIn("Nothing to do", out)

    def test_agent_already_running_but_app_missing(self):
        c = self.c
        c.kstuff = c.smp = True
        c.open_loader()
        c.start_agent("a" * 32)
        os.makedirs(self.home)
        open(os.path.join(self.home, "agent.token"), "w").write("a" * 32)
        rc, out = self.run_setup()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.kinds(), ["scan"])  # no agent, kstuff or ShadowMountPlus sent again
        self.assert_tree()
        self.assertTrue(c.app_running)
        # a second pass over the same files re-sends nothing (manifest matches)
        c.stop_app()
        before = len(c.puts)
        c.start_agent("a" * 32)  # the first run shut it down
        open(os.path.join(self.home, "agent.token"), "w").write("a" * 32)
        rc, out = self.run_setup()
        self.assertEqual(rc, 0, out)
        self.assertEqual([p for p in c.puts[before:] if not p.endswith(S.MANIFEST)], [])

    def test_onionhen_warning_and_no_kstuff(self):
        c = self.c
        c.kstuff = c.smp = True
        c.extra_procs = ["onionhen.elf"]
        c.open_loader()
        c.start_agent("b" * 32)
        os.makedirs(self.home)
        open(os.path.join(self.home, "agent.token"), "w").write("b" * 32)
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 1, out)  # the fake refuses to launch with OnionHEN present, like the real console
        self.assertIn("OnionHEN is loaded", out)
        self.assertNotIn("kstuff", self.kinds())

    def test_hash_mismatch_is_refused_before_anything_is_sent(self):
        self.payload("smp", pin="0" * 64)
        self.c.open_loader()
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 1, out)
        self.assertIn("Refused", out)
        self.assertEqual(self.c.received, [])
        cached = os.listdir(os.path.join(self.home, "payloads")) if os.path.isdir(os.path.join(self.home, "payloads")) else []
        self.assertFalse([n for n in cached if n.startswith("smp")], "a payload that failed the pin was cached")

    def test_waits_for_the_loader_and_continues_by_itself(self):
        threading.Timer(1.2, self.c.open_loader).start()
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.c.app_running)

    def test_gives_up_after_max_wait(self):
        t0 = time.time()
        rc, out = self.run_setup(["--max-wait", "2"])
        self.assertEqual(rc, 3, out)
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(self.c.received, [])

    def test_dry_run_sends_nothing(self):
        self.c.open_loader()
        rc, out = self.run_setup(["--dry-run"])
        self.assertEqual(rc, 0, out)
        self.assertIn("plan:", out)
        self.assertEqual((self.c.received, self.c.agent_req, self.c.puts), ([], 0, []))

    def test_kstuff_needs_consent(self):
        self.c.open_loader()
        rc, out = self.run_setup()  # --yes without --with-kstuff
        self.assertEqual(rc, 1, out)
        self.assertNotIn("kstuff", self.kinds())
        self.assertIn("kstuff does not look loaded", out)

    def test_json_events(self):
        c = self.c
        c.kstuff = c.smp = True
        c.open_loader()
        c.start_app()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = S.main(self.args(["--json"]))
        self.assertEqual(rc, 0)
        ev = [json.loads(l) for l in buf.getvalue().splitlines()]
        types = [e["type"] for e in ev]
        self.assertIn("state", types)
        self.assertIn("plan", types)
        self.assertEqual([e for e in ev if e["type"] not in ("state", "change")][-1]["type"], "done")

    def test_discovery_finds_the_console_without_an_address(self):
        c = self.c
        c.kstuff = c.smp = True
        c.open_loader()
        c.start_app()
        rc, out = self.run_setup(["--scan-net", "127.0.0.0/30"], ip=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("Console found: 127.0.0.1", out)
        self.assertEqual(json.load(open(os.path.join(self.home, "config.json")))["ps5"], "127.0.0.1")
        # next run: the remembered address is used without a scan
        rc, out = self.run_setup([], ip=False)
        self.assertEqual(rc, 0, out)
        self.assertIn("remembered address 127.0.0.1", out)

    def test_resume_after_a_killed_run(self):
        c = self.c
        c.put_delay = 0.03
        c.open_loader()
        env = dict(os.environ, OGPS5_HOME=self.home)
        proc = subprocess.Popen([sys.executable, SCRIPT] + self.args(["--with-kstuff"]), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(400):
                if len(c.puts) >= 18:
                    break
                time.sleep(0.1)
            self.assertGreaterEqual(len(c.puts), 18, "upload never started")
        finally:
            proc.kill()
            proc.wait()
        self.assertTrue(c.is_up("agent"))
        self.assertTrue(os.path.exists(os.path.join(self.home, "agent.token")))
        time.sleep(0.5)  # in-flight requests of the dead run finish
        done_before = set(self.app_puts())
        n1 = len(c.puts)
        c.put_delay = 0
        rc, out = self.run_setup(["--with-kstuff"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.kinds(), ["agent", "kstuff", "smp", "scan"])  # the agent was not sent a second time
        self.assert_tree()
        second = [p for p in c.puts[n1:] if not p.endswith(S.MANIFEST) and p.startswith(fake_ps5.APP + "/")]
        self.assertLess(len(second), len(self.local) - 5, "resume re-sent (almost) everything")
        self.assertTrue(c.app_running)
        self.assertTrue(done_before)


if __name__ == "__main__":
    unittest.main(verbosity=1)
