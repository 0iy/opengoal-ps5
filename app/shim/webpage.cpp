// The status web page served by the console (single file, no external requests, no dependencies). Games are installed from the PC
// (one line in a terminal, see README); this page shows that line, which games are installed and the progress of an install.
// Talks to webserver.cpp: GET /api/events (SSE) or /api/status, POST /api/cancel.
#include <string>

namespace {
const char* kPage = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>OpenGOAL-PS5</title>
<style>
:root{--bg:#0b0a12;--card:#16141f;--line:#2a2740;--fg:#f6f4ff;--dim:#9b98b8;--acc:#ff8a1f;--acc2:#ffc247;--ok:#4ade80;--err:#fb7185;--r:18px}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1100px 500px at 50% -120px,#2a1708,transparent 70%),var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}
main{max-width:860px;margin:0 auto;padding:22px 16px 56px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px}
h1{font-size:26px;margin:0;letter-spacing:-.5px}h1 b{background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
button{font:inherit;cursor:pointer;color:inherit}
button.lang{background:none;border:1px solid var(--line);color:var(--dim);border-radius:999px;padding:6px 14px}
button.lang:hover{border-color:var(--acc);color:var(--fg)}
p.lead{color:var(--dim);margin:10px 0 20px;max-width:62ch}
.pc{border-radius:var(--r);padding:16px;background:var(--card);border:1px solid #6b3a12;box-shadow:0 8px 30px -14px #ff8a1f88}
.pc h3{margin:0 0 4px;font-size:17px}.pc p{margin:0 0 10px;color:var(--dim);font-size:14px}
.os{font-size:13px;color:var(--acc2);margin:12px 0 4px;font-weight:600}
.cmd{display:flex;gap:8px;align-items:stretch}
.cmd code{flex:1;min-width:0;overflow-x:auto;white-space:nowrap;background:#0b0a12;border:1px solid var(--line);border-radius:10px;padding:9px 12px;font:13px/1.4 ui-monospace,Consolas,monospace;color:var(--fg)}
.cmd button{border-radius:10px;padding:0 14px;border:1px solid var(--line);background:#24213a;color:var(--fg);font-weight:600;white-space:nowrap}
.cmd button:hover{border-color:var(--acc)}
#overall{display:none;margin:16px 0 0;padding:14px 16px;border-radius:var(--r);background:linear-gradient(120deg,#2a1708,#16141f);border:1px solid #4a2a10}
#overall.on{display:block}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.row .sp{flex:1}
.pct{font-weight:700;font-variant-numeric:tabular-nums;font-size:20px;color:var(--acc2);min-width:3ch;text-align:right}
.bar{height:12px;background:#24213a;border-radius:99px;overflow:hidden;margin-top:8px}
.bar.thin{height:5px;margin-top:6px;opacity:.85}
.bar>i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .25s linear;position:relative;overflow:hidden}
.bar>i:after{content:"";position:absolute;inset:0;background:linear-gradient(100deg,transparent 30%,#fff5 50%,transparent 70%);transform:translateX(-100%);animation:sheen 1.8s infinite}
.bar.thin>i{background:linear-gradient(90deg,#c26a1c,#ffc247)}
.bar.ind>i{width:32%!important;transition:none;animation:slide 1.3s infinite ease-in-out}
.bar.ok>i{background:var(--ok)}.bar.ok>i:after,.bar.err>i:after{display:none}.bar.err>i{background:var(--err)}
@keyframes sheen{to{transform:translateX(100%)}}
@keyframes slide{0%{margin-left:-32%}100%{margin-left:100%}}
.card{display:flex;margin:14px 0;border-radius:var(--r);overflow:hidden;background:var(--card);border:1px solid var(--line);transition:border-color .3s,box-shadow .3s}
.card.act{border-color:#6b3a12;box-shadow:0 8px 30px -14px #ff8a1f88}.card.ok{border-color:#1e5a3a}.card.err{border-color:#7a2a3a}
.art{flex:0 0 108px;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden}
.art:before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 30% 20%,#fff4,transparent 45%),radial-gradient(circle at 80% 90%,#0008,transparent 60%)}
.art span{position:relative;font:800 64px/1 system-ui,sans-serif;color:transparent;-webkit-text-stroke:2px #ffffffcc;text-shadow:0 4px 18px #0006}
.g1 .art{background:linear-gradient(150deg,#0f766e,#22c55e 55%,#bef264)}
.g2 .art{background:linear-gradient(150deg,#1e1b4b,#7c3aed 55%,#f97316)}
.g3 .art{background:linear-gradient(150deg,#7c2d12,#f59e0b 55%,#fde68a)}
.body{flex:1;min-width:0;padding:14px 16px}
.body h2{font-size:18px;margin:0;flex:1 1 200px;line-height:1.25}
.tag{font-size:12px;border-radius:999px;padding:2px 10px;background:#25223a;color:var(--dim);white-space:nowrap}
.tag.ok{background:#123a26;color:var(--ok)}.tag.acc{background:#3a2208;color:var(--acc2)}
.msg{font-size:14px;color:var(--dim);margin-top:8px;word-break:break-word}.msg.err{color:var(--err)}.msg.ok{color:var(--ok);font-weight:600}
.meta{font-size:13px;color:var(--dim);margin-top:6px;font-variant-numeric:tabular-nums;min-height:1.2em}
.steps{display:flex;gap:6px;margin-top:10px;font-size:12px;color:var(--dim)}
.steps span{flex:1;border-top:3px solid #2a2740;padding-top:4px;transition:border-color .3s,color .3s}
.steps .d{border-color:var(--ok);color:var(--ok)}.steps .a{border-color:var(--acc);color:var(--acc2)}
.acts{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}.acts:empty{display:none}
button.go,button.sub{border-radius:999px;padding:6px 16px;font-weight:600;border:0}
button.go{background:linear-gradient(90deg,var(--acc),var(--acc2));color:#1a0e00}
button.sub{background:none;border:1px solid var(--line);color:var(--dim)}button.sub:hover{border-color:var(--err);color:var(--fg)}
p.foot{color:var(--dim);font-size:13px;margin-top:16px}
@media(max-width:520px){.art{flex-basis:64px}.art span{font-size:40px}h1{font-size:22px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
</style></head><body><main>
<header><h1>OpenGOAL<b>-PS5</b></h1><button class="lang" id="lang"></button></header>
<p class="lead" id="lead"></p>
<section class="pc"><h3 id="pch"></h3><p id="pcp"></p>
<div class="os">Windows (PowerShell)</div><div class="cmd"><code id="cw">irm https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.ps1 | iex</code><button data-c="cw"></button></div>
<div class="os">macOS / Linux (Terminal)</div><div class="cmd"><code id="cu">curl -fsSL https://github.com/0iy/opengoal-ps5/releases/latest/download/bootstrap.sh | bash</code><button data-c="cu"></button></div>
</section>
<div id="overall"><div class="row"><b id="ovt"></b><span class="sp"></span><span class="pct" id="ovp"></span></div><div class="bar" id="ovbw"><i id="ovb"></i></div><div class="meta" id="ovm"></div></div>
<div id="cards"></div>
<p class="foot" id="foot"></p>
</main>
<script>
const T={en:{
lead:"Your games and their install progress. Games are installed from your PC: it builds them from your own discs and sends them straight to your PS5 (nothing goes to the internet).",
pch:"Install games from your PC",pcp:"Paste this line into a terminal on a PC in the same network. It finds the PS5 and opens the import window: choose your .iso files and press Start.",copy:"Copy",copied:"Copied",
inst:"Installed",notinst:"Not installed",
waiting:"Waiting for upload",uploading:"Uploading",verifying:"Checking the disc image",queued:"In the queue, starts when the previous game is finished",
prepare:"Preparing tools",install:"Installing the game sent from your PC",extract:"Unpacking the disc image",decompile:"Analysing game data",compile:"Building the game",
done:"Done. Open the game on your PS5.",idle:"Install it from your PC with the line above.",again:"Installed.",
elapsed:"elapsed",eta:"left",cancel:"Cancel",cancelling:"Cancelling...",dismiss:"OK",
stalled:"Install interrupted. Start the import on the PC again",
s_upload:"Upload",s_verify:"Check",s_extract:"Unpack",s_decompile:"Analyse",s_compile:"Build",
ovt:"All games",ovn:"games",
foot:"Only unmodified .iso images of your own legally owned discs work. .bin/.cue files must be converted to .iso first. The PC part runs on Windows, macOS and Linux.",
wrong_game:"The upload turned out to be a different game.",dup:"Another file for this game is already being handled.",busy:"This game is being processed right now.",
no_space:"Not enough free space on the console.",io:"The console could not write the file.",net:"Connection lost during the install. Start the import on the PC again.",
toolchain:"The tool pack inside the app is missing or damaged. Reinstall the app.",unknown_disc:"This disc version is not in the list of known discs.",
bad_contents:"The disc contents do not match the original (modified or damaged image).",bad_iso:"The console could not read this image.",
f_extract:"Unpacking the disc failed. The image may be damaged.",f_decompile:"Analysing the game data failed.",f_compile:"Building the game failed.",
cancelled:"Cancelled.",incomplete:"Some parts of the upload are missing. Choose the file again to continue.",
failed:"Failed"},
de:{
lead:"Deine Spiele und ihr Installationsstand. Spiele werden vom PC aus installiert: Er baut sie aus deinen eigenen Discs und schickt sie direkt an deine PS5 (nichts geht ins Internet).",
pch:"Spiele vom PC aus installieren",pcp:"Füge diese Zeile in ein Terminal auf einem PC im selben Netz ein. Sie findet die PS5 und öffnet das Import-Fenster: .iso-Dateien wählen und Starten drücken.",copy:"Kopieren",copied:"Kopiert",
inst:"Installiert",notinst:"Nicht installiert",
waiting:"Wartet auf den Upload",uploading:"Lade hoch",verifying:"Disc-Abbild wird geprüft",queued:"In der Warteschlange, startet nach dem vorherigen Spiel",
prepare:"Werkzeuge werden vorbereitet",install:"Das vom PC gesendete Spiel wird eingerichtet",extract:"Disc-Abbild wird entpackt",decompile:"Spieldaten werden analysiert",compile:"Spiel wird gebaut",
done:"Fertig. Öffne das Spiel auf deiner PS5.",idle:"Installiere es vom PC aus mit der Zeile oben.",again:"Installiert.",
elapsed:"vergangen",eta:"verbleibend",cancel:"Abbrechen",cancelling:"Wird abgebrochen...",dismiss:"OK",
stalled:"Installation unterbrochen. Starte den Import am PC erneut",
s_upload:"Upload",s_verify:"Prüfen",s_extract:"Entpacken",s_decompile:"Analyse",s_compile:"Bauen",
ovt:"Alle Spiele",ovn:"Spiele",
foot:"Es funktionieren nur unveränderte .iso-Abbilder deiner eigenen, legal erworbenen Discs. .bin/.cue müssen zuerst in .iso umgewandelt werden. Der PC-Teil läuft unter Windows, macOS und Linux.",
wrong_game:"Der Upload war ein anderes Spiel.",dup:"Für dieses Spiel wird bereits eine andere Datei verarbeitet.",busy:"Dieses Spiel wird gerade verarbeitet.",
no_space:"Nicht genug freier Speicher auf der Konsole.",io:"Die Konsole konnte die Datei nicht schreiben.",net:"Verbindung bei der Installation verloren. Starte den Import am PC erneut.",
toolchain:"Das Werkzeugpaket in der App fehlt oder ist beschädigt. Installiere die App neu.",unknown_disc:"Diese Disc-Version steht nicht in der Liste bekannter Discs.",
bad_contents:"Der Disc-Inhalt passt nicht zum Original (verändertes oder beschädigtes Abbild).",bad_iso:"Die Konsole konnte dieses Abbild nicht lesen.",
f_extract:"Das Entpacken der Disc ist fehlgeschlagen. Das Abbild ist vielleicht beschädigt.",f_decompile:"Die Analyse der Spieldaten ist fehlgeschlagen.",f_compile:"Das Bauen des Spiels ist fehlgeschlagen.",
cancelled:"Abgebrochen.",incomplete:"Es fehlen Teile des Uploads. Wähle die Datei erneut, um fortzufahren.",
failed:"Fehlgeschlagen"}};
const G=[["jak1","Jak and Daxter: The Precursor Legacy","1"],["jak2","Jak II","2"],["jak3","Jak 3","3"]];
const STEPS=["upload","verify","extract","decompile","compile"];
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let L=(navigator.language||"en").slice(0,2)==="de"?"de":"en";try{if(localStorage.lang)L=localStorage.lang}catch(e){}
const t=k=>T[L][k]||k;
let st={games:{}},lastMsg=0,pend=false,built=false;
const fmt=n=>n>=1e9?(n/1e9).toFixed(2)+" GB":(n/1e6).toFixed(0)+" MB";
const mmss=s=>s>=3600?Math.floor(s/3600)+":"+String(Math.floor(s%3600/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0"):Math.floor(s/60)+":"+String(s%60).padStart(2,"0");
const rate=b=>b>=1e6?(b/1e6).toFixed(1)+" MB/s":(b/1e3).toFixed(0)+" kB/s";
// DOM writers that skip unchanged values (keeps CSS transitions and button clicks intact)
const memo={};
const setT=(s,v)=>{if(memo["t"+s]!==v){memo["t"+s]=v;$(s).textContent=v}};
const setH=(s,v)=>{if(memo["h"+s]!==v){memo["h"+s]=v;$(s).innerHTML=v}};
const setC=(s,v)=>{if(memo["c"+s]!==v){memo["c"+s]=v;$(s).className=v}};
const setW=(s,v)=>{if(memo["w"+s]!==v){memo["w"+s]=v;$(s).style.width=v+"%"}};
const setD=(s,v)=>{if(memo["d"+s]!==v){memo["d"+s]=v;$(s).style.display=v}};

async function cancel(id){
 try{await fetch(`/api/cancel?game=${id}`,{method:"POST"})}catch(e){}
 poll(true)}
const stalled=s=>s.phase==="uploading"&&(s.idle<0||s.idle>=4);  // an install nobody is feeding any more

function build(){
 built=true;
 $("#cards").innerHTML=G.map(([id,name,n])=>`<section class="card g${n}" id="c-${id}"><div class="art"><span>${n}</span></div><div class="body">
<div class="row"><h2>${name}</h2><span class="tag acc" id="${id}-reg"></span><span class="tag" id="${id}-inst"></span><span class="pct" id="${id}-pct"></span></div>
<div class="msg" id="${id}-msg"></div><div class="bar" id="${id}-bw"><i id="${id}-b"></i></div><div class="bar thin" id="${id}-sw"><i id="${id}-sb"></i></div>
<div class="meta" id="${id}-meta"></div><div class="steps" id="${id}-steps"></div><div class="acts" id="${id}-acts"></div></div></section>`).join("")}

function render(){
 if(!built)build();
 setT("#lang",L==="en"?"Deutsch":"English");setT("#lead",t("lead"));setT("#pch",t("pch"));setT("#pcp",t("pcp"));setT("#foot",t("foot"));
 for(const b of document.querySelectorAll(".cmd button"))if(!b.dataset.done)b.textContent=t("copy");
 document.documentElement.lang=L;
 for(const [id] of G){
  const s=st.games[id]||{phase:"idle"},v={ph:s.phase,reason:s.reason},det=s.serial?{serial:s.serial,region:s.region}:null,ph=v.ph;
  let msg=s.installed?t("again"):t("idle"),cls="msg",pct=-1,spct=-1,meta="",step=-1,acts="",card="card g"+id.slice(3),bcls="bar",sbcls="bar thin";
  const eta=s.eta>=0?" · "+mmss(s.eta)+" "+t("eta"):"",cbtn=`<button class="sub" onclick="cancel('${id}')">${t("cancel")}</button>`;
  if(ph==="uploading"){
   const b=s.bytes||0,tot=s.total||1,sp=s.speed||0;step=0;card+=" act";
   pct=s.percent>=0?s.percent:0;spct=Math.min(100,100*b/tot);
   if(!stalled(s)){msg=t("uploading")+" "+spct.toFixed(0)+"%";meta=`${fmt(b)} / ${fmt(tot)}${sp?" · "+rate(sp):""}${eta}`}
   else{msg=t("stalled")+` (${spct.toFixed(0)}%)`;meta=`${fmt(b)} / ${fmt(tot)}`;card=card.replace(" act","")}
   acts=cbtn}
  else if(ph==="verifying"){step=1;msg=t("verifying");pct=s.percent>=0?s.percent:-1;card+=" act"}
  else if(ph==="queued"){step=2;msg=t("queued");pct=s.percent;acts=cbtn}
  else if(ph==="importing"){
   const g=s.stage||"prepare";step=g==="decompile"?3:(g==="compile"||g==="install")?4:2;card+=" act";pct=s.percent;spct=s.stage_percent;
   msg=s.reason==="cancelling"?t("cancelling"):t(g)+(spct>=0?" "+spct+"%":"");
   meta=`${mmss(s.elapsed||0)} ${t("elapsed")}${eta}`;
   if(spct<0)sbcls+=" ind";
   acts=s.reason==="cancelling"?"":cbtn}
  else if(ph==="done"){msg=t("done");cls+=" ok";pct=100;card+=" ok";bcls+=" ok";meta=s.elapsed?mmss(s.elapsed):"";acts=`<button class="sub" onclick="cancel('${id}')">${t("dismiss")}</button>`}
  else if(ph==="failed"){
   const r=v.reason||"extract";msg=t(["extract","decompile","compile"].includes(r)?"f_"+r:r)+(v.detail||"");cls+=" err";card+=" err";bcls+=" err";pct=Math.max(0,s.percent||0);
   acts=`<button class="sub" onclick="cancel('${id}')">${t("dismiss")}</button>`}
  if(pct<0&&(ph==="importing"||ph==="verifying"))bcls+=" ind";
  const idle=ph==="idle";
  setC("#c-"+id,card);
  setT("#"+id+"-reg",det?det.region+" · "+det.serial:"");setD("#"+id+"-reg",det?"":"none");
  setC("#"+id+"-inst","tag"+(s.installed?" ok":""));setT("#"+id+"-inst",s.installed?t("inst"):t("notinst"));
  setT("#"+id+"-pct",pct>=0?pct+"%":"");
  setC("#"+id+"-msg",cls);setT("#"+id+"-msg",msg);
  setC("#"+id+"-bw",bcls);setW("#"+id+"-b",pct>=0?pct:0);setD("#"+id+"-bw",idle?"none":"");
  setC("#"+id+"-sw",sbcls);setW("#"+id+"-sb",spct>=0?spct:0);setD("#"+id+"-sw",(spct>=0||sbcls.indexOf("ind")>=0)&&ph!=="done"&&ph!=="failed"?"":"none");
  setT("#"+id+"-meta",meta);
  setH("#"+id+"-steps",step>=0?STEPS.map((k,i)=>`<span class="${i<step?"d":i===step?"a":""}">${t("s_"+k)}</span>`).join(""):"");
  setH("#"+id+"-acts",acts)}
 const o=st.overall||{games:0};
 setC("#overall",o.games>1?"on":"");
 if(o.games>1){setT("#ovt",t("ovt")+" · "+o.games+" "+t("ovn"));setT("#ovp",o.percent+"%");setW("#ovb",Math.max(0,o.percent));
  setT("#ovm",o.eta>=0?"~ "+mmss(o.eta)+" "+t("eta"):"")}}

function onStatus(j){st=j;lastMsg=Date.now();if(!pend){pend=true;(window.requestAnimationFrame||(f=>setTimeout(f,0)))(()=>{pend=false;render()})}}
async function poll(force){
 if(!force&&Date.now()-lastMsg<1500)return;  // the event stream is alive
 try{onStatus(await (await fetch("/api/status")).json())}catch(e){}}
function live(){
 if(typeof EventSource!=="function")return;
 try{const es=new EventSource("/api/events");es.onmessage=e=>{try{onStatus(JSON.parse(e.data))}catch(x){}}}catch(e){}}
$("#lang").onclick=()=>{L=L==="en"?"de":"en";try{localStorage.lang=L}catch(e){}render()};
// copy: the page is plain http on the LAN, where navigator.clipboard is not available; select the text and use execCommand
for(const b of document.querySelectorAll(".cmd button"))b.onclick=()=>{
 const c=$("#"+b.dataset.c),r=document.createRange();r.selectNodeContents(c);const sel=getSelection();sel.removeAllRanges();sel.addRange(r);
 let ok=false;try{ok=document.execCommand("copy")}catch(e){}
 if(ok){b.textContent=t("copied");b.dataset.done=1;setTimeout(()=>{delete b.dataset.done;b.textContent=t("copy")},1500)}};
setInterval(poll,250);live();poll(true);render();
</script></body></html>)HTML";
}  // namespace

const char* ps5_web_page() { return kPage; }
