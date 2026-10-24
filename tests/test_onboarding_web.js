// Headless test of the onboarding page script (node >= 18): node tests/test_onboarding_web.js
// Extracts the <script> from app/shim/webpage.cpp, runs it against a stubbed DOM and a mock of the console API.
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const src = fs.readFileSync(__dirname + "/../app/shim/webpage.cpp", "utf8");
const html = src.split('R"HTML(')[1].split(')HTML"')[0];
const js = html.split("<script>")[1].split("</script>")[0];

// Build a minimal fake disc: PVD at sector 16, root dir at sector 20 with SYSTEM.CNF;1 and an ELF named by serial.
function iso(serial, { blocks = 30000, size = blocks * 2048, sys = true, sig = "CD001" } = {}) {
  const b = Buffer.alloc(Math.max(size, 100 * 2048));
  b[16 * 2048] = 1; b.write(sig, 16 * 2048 + 1, "latin1");
  b.writeUInt32LE(blocks, 16 * 2048 + 80);
  b.writeUInt32LE(20, 16 * 2048 + 158); b.writeUInt32LE(2048, 16 * 2048 + 166);
  let pos = 20 * 2048;
  for (const n of [sys && "SYSTEM.CNF;1", serial && serial.replace("-", "_").replace(/(\d{3})(\d{2})$/, "$1.$2") + ";1"].filter(Boolean)) {
    b[pos] = 34 + n.length; b[pos + 32] = n.length; b.write(n, pos + 33, "latin1"); pos += 34 + n.length;
  }
  return b;
}
const mkFile = (name, buf, size) => ({ name, size: size ?? buf.length, slice: (a, e) => ({ arrayBuffer: async () => buf.subarray(a, e).buffer.slice(buf.byteOffset + a, buf.byteOffset + Math.min(e, buf.length)) }) });

const calls = []; let games = {}; let overall = { games: 0, percent: -1, eta: -1 }; let resume = [];
const els = {}; const el = k => els[k] ??= { innerHTML: "", textContent: "", style: {}, className: "", checked: false, classList: { add() {}, remove() {} }, click() {} };
const ctx = {
  console, performance, Date, setInterval: () => 0, setTimeout, Promise, DataView, Uint8Array, Set,
  navigator: { language: "de-DE" }, localStorage: {}, window: { addEventListener() {} },
  document: { querySelector: el, addEventListener() {}, documentElement: {}, activeElement: null },
  fetch: async (url, o = {}) => {
    calls.push((o.method || "GET") + " " + url);
    const g = (url.match(/game=(\w+)/) || [])[1];
    if (url.startsWith("/api/begin")) { games[g] = { phase: "uploading", bytes: 0, total: +url.match(/total=(\d+)/)[1], idle: 0 }; return { ok: true, json: async () => ({ resume, chunk: 32 << 20 }) }; }
    if (url.startsWith("/api/chunk")) { return { ok: true }; }
    if (url.startsWith("/api/start")) { games[g].phase = "queued"; return { ok: true, status: 200 }; }
    if (url.startsWith("/api/cancel")) { return { ok: true, json: async () => ({}) }; }
    return { ok: true, json: async () => ({ version: 3, games, overall, settings: { delete_iso: true } }) };
  },
};
vm.createContext(ctx); vm.runInContext(js, ctx);
const run = c => vm.runInContext(c, ctx);
const tick = () => new Promise(r => setTimeout(r, 30));
const text = id => el(id).textContent;

(async () => {
  assert.strictEqual(run("L"), "de");
  // detection
  const cases = [["SCUS-97124", "jak1", "NTSC-U"], ["SCES-51608", "jak2", "PAL"], ["SCUS-97516", "jak3", "NTSC-U"], ["SCKA-20040", "jak3", "NTSC-K"]];
  for (const [s, g, r] of cases) {
    ctx.f = mkFile("x.iso", iso(s), 70 << 20);
    const d = await run("detect(f)"); assert.deepStrictEqual([d.game, d.region, d.serial], [g, r, s]);
  }
  const fail = async (f, why) => { ctx.f = f; try { await run("detect(f)"); } catch (e) { return assert.strictEqual(e, why); } assert.fail("no throw " + why); };
  await fail(mkFile("x.iso", iso("SCUS-97124", { blocks: 30000 }), 60 << 20), "tiny");
  await fail(mkFile("x.iso", iso("SCUS-97124", { blocks: 80000 }), 70 << 20), "truncated");
  await fail(mkFile("x.iso", iso("SCUS-97124", { sys: false }), 70 << 20), "nosys");
  await fail(mkFile("x.iso", iso("SCUS-11111"), 70 << 20), "unknown");
  await fail(mkFile("x.iso", iso("SCUS-97124", { sig: "XXXXX" }), 70 << 20), "notiso");
  await fail(mkFile("x.bin", iso("SCUS-97124"), 70 << 20), "ext");
  // many files at once: both queued, third (duplicate of jak1) rejected, uploads run sequentially
  ctx.fs = [mkFile("a.iso", iso("SCUS-97124"), 70 << 20), mkFile("b.iso", iso("SCUS-97265"), 70 << 20), mkFile("c.iso", iso("SCES-50361"), 70 << 20)];
  await run("addFiles(fs)"); await tick(); await run("poll(true)"); await tick();
  const order = calls.filter(c => /begin|start/.test(c)).map(c => c.replace("POST /api/", "").split("&")[0]);
  assert.deepStrictEqual(order, ["begin?game=jak1", "start?game=jak1", "begin?game=jak2", "start?game=jak2"]);
  assert.strictEqual(run("bad.length"), 1); // jak1 duplicate (PAL) rejected
  assert(text("#jak1-reg").includes("NTSC-U"));
  assert(text("#jak1-msg").includes("In der Warteschlange"));
  // 70 MB at 32 MB chunks = 3 chunks per game
  assert.strictEqual(calls.filter(c => c.startsWith("PUT /api/chunk?game=jak1")).length, 3);

  // live numbers: uploading with speed and eta
  games.jak3 = { phase: "uploading", bytes: 500e6, total: 1000e6, percent: 5, stage_percent: -1, speed: 40e6, eta: 12, idle: 0, serial: "SCUS-97330", region: "NTSC-U" };
  await run("poll(true)"); await tick();
  assert(text("#jak3-msg").includes("50%"), text("#jak3-msg"));
  assert(text("#jak3-meta").includes("40.0 MB/s") && text("#jak3-meta").includes("0:12"), text("#jak3-meta"));
  assert.strictEqual(text("#jak3-pct"), "5%");
  assert.strictEqual(el("#jak3-b").style.width, "5%");
  // interrupted upload (nobody sends): reload shows the resume hint, same file may be dropped again
  games.jak3.idle = 30;
  await run("poll(true)"); await tick();
  assert(text("#jak3-msg").includes("Upload unterbrochen"), text("#jak3-msg"));
  // importing: stage percent, overall percent, elapsed + eta, combined view
  games.jak2 = { phase: "importing", stage: "decompile", percent: 47, stage_percent: 50, bytes: 0, total: 0, elapsed: 125, eta: 140, speed: 0, serial: "SCUS-97265", region: "NTSC-U", reason: "" };
  games.jak3 = { phase: "queued", percent: 12, stage: "", stage_percent: -1, eta: -1, serial: "SCUS-97330", region: "NTSC-U" };
  overall = { games: 2, percent: 30, eta: 400 };
  await run("poll(true)"); await tick();
  assert(text("#jak2-msg").includes("50%") && text("#jak2-pct") === "47%", text("#jak2-msg"));
  assert(text("#jak2-meta").includes("2:05") && text("#jak2-meta").includes("2:20"), text("#jak2-meta"));
  assert.strictEqual(el("#overall").className, "on");
  assert.strictEqual(text("#ovp"), "30%");
  // failure + success + cancel call
  games.jak2 = { phase: "failed", reason: "bad_contents", percent: 40, stage: "", stage_percent: -1, eta: -1 };
  games.jak3 = { phase: "done", percent: 100, elapsed: 900, stage: "", stage_percent: -1, eta: -1 };
  await run("poll(true)"); await tick();
  assert(text("#jak2-msg").includes("passt nicht zum Original"), text("#jak2-msg"));
  assert(text("#jak3-msg").includes("Fertig"));
  await run("cancel('jak2')");
  assert(calls.includes("POST /api/cancel?game=jak2"));
  // English + failure key that is also a stage name
  run("L='en'"); games.jak1 = { phase: "failed", reason: "decompile" };
  await run("poll(true)"); await tick();
  assert.strictEqual(text("#jak1-msg"), "Analysing the game data failed.");
  // resume: chunks the console already has are not sent again
  calls.length = 0; resume = [0, 33554432]; games = {};
  ctx.fs = [mkFile("d.iso", iso("SCUS-97330"), 70 << 20)];
  await run("addFiles(fs)"); await tick();
  assert.strictEqual(calls.filter(c => c.startsWith("PUT /api/chunk")).length, 1);
  assert(calls.some(c => /fp=\d+-0-d\.iso/.test(c)));
  console.log("ok");
})().catch(e => { console.error(e); process.exit(1); });
