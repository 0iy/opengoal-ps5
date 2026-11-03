// Headless test of the status page script (node >= 18): node tests/test_onboarding_web.js
// Extracts the <script> from app/shim/webpage.cpp, runs it against a stubbed DOM and a mock of the console API.
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const src = fs.readFileSync(__dirname + "/../app/shim/webpage.cpp", "utf8");
const html = src.split('R"HTML(')[1].split(')HTML"')[0];
const js = html.split("<script>")[1].split("</script>")[0];

const calls = []; let games = {}; let overall = { games: 0, percent: -1, eta: -1 }; 
const els = {}; const el = k => els[k] ??= { innerHTML: "", textContent: "", style: {}, className: "", checked: false, classList: { add() {}, remove() {} }, click() {} };
const ctx = {
  console, performance, Date, setInterval: () => 0, setTimeout, Promise, DataView, Uint8Array, Set,
  navigator: { language: "de-DE" }, localStorage: {}, window: { addEventListener() {} },
  document: { querySelector: el, querySelectorAll: () => [], addEventListener() {}, documentElement: {}, activeElement: null },
  fetch: async (url, o = {}) => {
    calls.push((o.method || "GET") + " " + url);
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
  // the PC install panel and the idle text point to the one-liner
  await run("poll(true)"); await tick();
  assert(text("#pch").includes("PC"), text("#pch"));
  assert(text("#jak1-msg").includes("Zeile oben"), text("#jak1-msg"));
  // an install from the PC (pc_import) shows its stage
  games.jak1 = { phase: "importing", stage: "install", percent: 37, stage_percent: 37, bytes: 0, total: 0, elapsed: 20, eta: 30, speed: 0, serial: "SCUS-97124", region: "NTSC-U", reason: "" };
  await run("poll(true)"); await tick();
  assert(text("#jak1-msg").includes("37%") && text("#jak1-reg").includes("NTSC-U"), text("#jak1-msg"));

  // live numbers: uploading with speed and eta
  games.jak3 = { phase: "uploading", bytes: 500e6, total: 1000e6, percent: 5, stage_percent: -1, speed: 40e6, eta: 12, idle: 0, serial: "SCUS-97330", region: "NTSC-U" };
  await run("poll(true)"); await tick();
  assert(text("#jak3-msg").includes("50%"), text("#jak3-msg"));
  assert(text("#jak3-meta").includes("40.0 MB/s") && text("#jak3-meta").includes("0:12"), text("#jak3-meta"));
  assert.strictEqual(text("#jak3-pct"), "5%");
  assert.strictEqual(el("#jak3-b").style.width, "5%");
  // interrupted install (nobody sends)
  games.jak3.idle = 30;
  await run("poll(true)"); await tick();
  assert(text("#jak3-msg").includes("unterbrochen"), text("#jak3-msg"));
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
  console.log("ok");
})().catch(e => { console.error(e); process.exit(1); });
