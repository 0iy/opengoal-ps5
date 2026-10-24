// The import web page served by the console (single file, no external requests, no dependencies).
// Talks to webserver.cpp: GET /api/events (SSE) or /api/status, POST /api/begin, PUT /api/chunk, POST /api/start|cancel,
// /api/settings (see docs/ONBOARDING_WEB.md).
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
#drop{position:relative;border-radius:var(--r);padding:38px 18px;text-align:center;color:var(--dim);cursor:pointer;background:linear-gradient(var(--card),var(--card)) padding-box,repeating-linear-gradient(90deg,var(--line) 0 10px,transparent 10px 20px) border-box;border:2px dashed transparent;transition:transform .2s,box-shadow .2s,color .2s,background-color .2s}
#drop svg{width:46px;height:46px;stroke:var(--acc);fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;display:block;margin:0 auto 8px;animation:bob 2.4s ease-in-out infinite}
#drop b{color:var(--acc2)}#drop small{display:block;margin-top:4px;font-size:13px}
#drop:hover,#drop.over{color:var(--fg);box-shadow:0 0 0 1px var(--acc),0 10px 40px -10px #ff8a1f88}
#drop.over{transform:scale(1.02);background:linear-gradient(#24160a,#24160a) padding-box,repeating-linear-gradient(90deg,var(--acc) 0 10px,transparent 10px 20px) border-box}
#drop.pulse{animation:pulse .5s}
@keyframes bob{50%{transform:translateY(-5px)}}
@keyframes pulse{40%{transform:scale(.97)}}
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
.bad{margin-top:14px;font-size:14px}.bad div{color:var(--err);margin:4px 0}
label.set{display:flex;gap:8px;align-items:center;color:var(--dim);font-size:14px;margin-top:22px;cursor:pointer}
label.set input{accent-color:var(--acc);width:18px;height:18px}
p.foot{color:var(--dim);font-size:13px;margin-top:16px}
@media(max-width:520px){.art{flex-basis:64px}.art span{font-size:40px}#drop{padding:28px 12px}h1{font-size:22px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
</style></head><body><main>
<header><h1>OpenGOAL<b>-PS5</b></h1><button class="lang" id="lang"></button></header>
<p class="lead" id="lead"></p>
<div id="drop" role="button" tabindex="0"><svg viewBox="0 0 48 48"><path d="M24 34V10M14 20l10-10 10 10M8 40h32"/></svg><span id="droptxt"></span></div>
<input type="file" id="file" accept=".iso" multiple hidden>
<div id="overall"><div class="row"><b id="ovt"></b><span class="sp"></span><span class="pct" id="ovp"></span></div><div class="bar" id="ovbw"><i id="ovb"></i></div><div class="meta" id="ovm"></div></div>
<div id="cards"></div>
<div class="bad" id="bad"></div>
<label class="set"><input type="checkbox" id="deliso"><span id="delisot"></span></label>
<p class="foot" id="foot"></p>
</main>
<script>
const T={en:{
lead:"Send your own copy of the games to the console. Nothing goes to the internet; the files go straight to your PS5. You can drop several discs at once, the games are processed one after another.",
drop:"Drop your <b>.iso</b> files here<small>or click to choose. The game is detected automatically.</small>",
inst:"Installed",notinst:"Not installed",
waiting:"Waiting for upload",uploading:"Uploading",verifying:"Checking the disc image",queued:"In the queue, starts when the previous game is finished",
prepare:"Preparing tools",install:"Installing the game sent from your PC",extract:"Unpacking the disc image",decompile:"Analysing game data",compile:"Building the game",
done:"Done. Open the game on your PS5.",idle:"Drop the matching .iso to install.",again:"Installed. Drop the .iso again to reinstall.",
elapsed:"elapsed",eta:"left",retry:"Choose file again",cancel:"Cancel",cancelling:"Cancelling...",dismiss:"OK",
stalled:"Upload interrupted. Drop the same file again to continue where it stopped",
s_upload:"Upload",s_verify:"Check",s_extract:"Unpack",s_decompile:"Analyse",s_compile:"Build",
ovt:"All games",ovn:"games",
delete_iso:"Delete the .iso from the console after a successful import (frees several GB)",
foot:"Only unmodified .iso images of your own legally owned discs work. .bin/.cue files must be converted to .iso first. Keep this page open while uploading; an interrupted upload can be continued.",
bad:"Not accepted:",
ext:"Not an .iso file.",notiso:"This does not look like a PS2 disc image.",tiny:"The file is too small to be a game disc.",
raw:"This is a raw .bin image. Convert it to a plain .iso first.",truncated:"The file is smaller than the disc it describes, so the copy is incomplete. Copy it again.",
nosys:"The disc has no SYSTEM.CNF, so it is not a bootable PS2 disc.",unknown:"Not a supported Jak and Daxter disc (unknown serial).",
wrong_game:"The upload turned out to be a different game.",dup:"Another file for this game is already being handled.",busy:"This game is being processed right now.",
no_space:"Not enough free space on the console.",io:"The console could not write the file.",net:"Connection lost during upload. Try again.",
toolchain:"The tool pack inside the app is missing or damaged. Reinstall the app.",unknown_disc:"This disc version is not in the list of known discs.",
bad_contents:"The disc contents do not match the original (modified or damaged image).",bad_iso:"The console could not read this image.",
f_extract:"Unpacking the disc failed. The image may be damaged.",f_decompile:"Analysing the game data failed.",f_compile:"Building the game failed.",
cancelled:"Cancelled.",incomplete:"Some parts of the upload are missing. Choose the file again to continue.",
failed:"Failed"},
de:{
lead:"Schick deine eigenen Spielkopien an die Konsole. Nichts geht ins Internet; die Dateien gehen direkt an deine PS5. Du kannst mehrere Discs auf einmal ablegen, die Spiele werden nacheinander verarbeitet.",
drop:"<b>.iso</b>-Dateien hier ablegen<small>oder klicken zum Auswählen. Das Spiel wird automatisch erkannt.</small>",
inst:"Installiert",notinst:"Nicht installiert",
waiting:"Wartet auf den Upload",uploading:"Lade hoch",verifying:"Disc-Abbild wird geprüft",queued:"In der Warteschlange, startet nach dem vorherigen Spiel",
prepare:"Werkzeuge werden vorbereitet",install:"Das vom PC gesendete Spiel wird eingerichtet",extract:"Disc-Abbild wird entpackt",decompile:"Spieldaten werden analysiert",compile:"Spiel wird gebaut",
done:"Fertig. Öffne das Spiel auf deiner PS5.",idle:"Passende .iso ablegen zum Installieren.",again:"Installiert. Zum Neuinstallieren die .iso erneut ablegen.",
elapsed:"vergangen",eta:"verbleibend",retry:"Datei neu wählen",cancel:"Abbrechen",cancelling:"Wird abgebrochen...",dismiss:"OK",
stalled:"Upload unterbrochen. Leg dieselbe Datei erneut ab, dann geht es dort weiter, wo es aufgehört hat",
s_upload:"Upload",s_verify:"Prüfen",s_extract:"Entpacken",s_decompile:"Analyse",s_compile:"Bauen",
ovt:"Alle Spiele",ovn:"Spiele",
delete_iso:"Die .iso nach erfolgreichem Import von der Konsole löschen (gibt mehrere GB frei)",
foot:"Es funktionieren nur unveränderte .iso-Abbilder deiner eigenen, legal erworbenen Discs. .bin/.cue müssen zuerst in .iso umgewandelt werden. Lass diese Seite beim Hochladen offen; ein unterbrochener Upload kann fortgesetzt werden.",
bad:"Nicht angenommen:",
ext:"Keine .iso-Datei.",notiso:"Das sieht nicht wie ein PS2-Disc-Abbild aus.",tiny:"Die Datei ist zu klein für eine Spiel-Disc.",
raw:"Das ist ein rohes .bin-Abbild. Wandle es zuerst in eine normale .iso um.",truncated:"Die Datei ist kleiner als die Disc, die sie beschreibt. Die Kopie ist unvollständig, bitte neu kopieren.",
nosys:"Die Disc hat keine SYSTEM.CNF und ist daher keine startbare PS2-Disc.",unknown:"Keine unterstützte Jak-and-Daxter-Disc (unbekannte Seriennummer).",
wrong_game:"Der Upload war ein anderes Spiel.",dup:"Für dieses Spiel wird bereits eine andere Datei verarbeitet.",busy:"Dieses Spiel wird gerade verarbeitet.",
no_space:"Nicht genug freier Speicher auf der Konsole.",io:"Die Konsole konnte die Datei nicht schreiben.",net:"Verbindung beim Upload verloren. Versuch es noch einmal.",
toolchain:"Das Werkzeugpaket in der App fehlt oder ist beschädigt. Installiere die App neu.",unknown_disc:"Diese Disc-Version steht nicht in der Liste bekannter Discs.",
bad_contents:"Der Disc-Inhalt passt nicht zum Original (verändertes oder beschädigtes Abbild).",bad_iso:"Die Konsole konnte dieses Abbild nicht lesen.",
f_extract:"Das Entpacken der Disc ist fehlgeschlagen. Das Abbild ist vielleicht beschädigt.",f_decompile:"Die Analyse der Spieldaten ist fehlgeschlagen.",f_compile:"Das Bauen des Spiels ist fehlgeschlagen.",
cancelled:"Abgebrochen.",incomplete:"Es fehlen Teile des Uploads. Wähle die Datei erneut, um fortzufahren.",
failed:"Fehlgeschlagen"}};
const G=[["jak1","Jak and Daxter: The Precursor Legacy","1"],["jak2","Jak II","2"],["jak3","Jak 3","3"]];
// serial (from the ELF name in the disc root) -> [game, region]; same list as importer.cpp / the upstream extractor database
const DISCS={"SCUS-97124":["jak1","NTSC-U"],"SCES-50361":["jak1","PAL"],"SCPS-15021":["jak1","NTSC-J"],"SCPS-56003":["jak1","NTSC-K"],
"SCUS-97265":["jak2","NTSC-U"],"SCES-51608":["jak2","PAL"],"SCPS-15057":["jak2","NTSC-J"],"SCKA-20010":["jak2","NTSC-K"],
"SCUS-97330":["jak3","NTSC-U"],"SCUS-97516":["jak3","NTSC-U"],"SCES-52460":["jak3","PAL"],"SCKA-20040":["jak3","NTSC-K"]};
const STEPS=["upload","verify","extract","decompile","compile"];
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let L=(navigator.language||"en").slice(0,2)==="de"?"de":"en";try{if(localStorage.lang)L=localStorage.lang}catch(e){}
const t=k=>T[L][k]||k;
let st={games:{}},loc={},bad=[],queue=[],running=false,lastMsg=0,pend=false,built=false;
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

// Fast integrity pre-check in the browser: reads ~100 KB of the file, no hashing.
async function detect(file){
 const rd=async(o,n)=>new Uint8Array(await file.slice(o,o+n).arrayBuffer());
 if(!/\.iso$/i.test(file.name))throw"ext";
 if(file.size<(64<<20))throw"tiny";
 const p=await rd(16*2048,2048),dv=new DataView(p.buffer);
 if(p[0]!==1||String.fromCharCode(...p.slice(1,6))!=="CD001"){
  const h=await rd(0,12);if(h[0]===0&&h[11]===0&&h.slice(1,11).every(x=>x===255))throw"raw";throw"notiso"}
 if(file.size<dv.getUint32(80,true)*2048)throw"truncated";
 const lba=dv.getUint32(158,true),len=dv.getUint32(166,true);
 if(!len||len>(1<<20))throw"notiso";
 const d=await rd(lba*2048,len);let sys=false,serial="";
 for(let pos=0;pos+34<=d.length;){
  const rl=d[pos];if(!rl){pos=(Math.floor(pos/2048)+1)*2048;continue}
  const name=String.fromCharCode(...d.slice(pos+33,pos+33+d[pos+32]));
  if(name==="SYSTEM.CNF;1")sys=true;
  const m=/^([A-Z]{4})_(\d{3})\.(\d{2});1$/.exec(name);if(m&&!serial)serial=m[1]+"-"+m[2]+m[3];
  pos+=rl}
 if(!sys)throw"nosys";
 const k=DISCS[serial];if(!k)throw"unknown";
 return{game:k[0],region:k[1],serial}}

const stalled=s=>s.phase==="uploading"&&(s.idle<0||s.idle>=4);  // the console holds a half upload nobody is feeding
async function addFiles(files){
 for(const f of files){
  try{const d=await detect(f),s=st.games[d.game]||{};
   if((loc[d.game]&&["pending","uploading","verifying"].includes(loc[d.game].phase))||["verifying","queued","importing"].includes(s.phase)||(s.phase==="uploading"&&!stalled(s)))throw"dup";
   loc[d.game]={file:f,det:d,phase:"pending"};queue.push(d.game)}
  catch(e){bad.push({name:f.name,why:typeof e==="string"?e:"notiso"})}}
 render();run()}

async function run(){
 if(running)return;running=true;
 while(queue.length){await upload(queue.shift());render()}
 running=false}

// Resumable: /api/begin answers the chunk offsets the console already has (same file fingerprint), only the rest is sent.
async function upload(id){
 const l=loc[id],f=l.file,CH=32<<20,PAR=4,total=f.size;
 const fp=encodeURIComponent(total+"-"+(f.lastModified||0)+"-"+f.name).slice(0,180);
 l.phase="uploading";l.ac=typeof AbortController==="function"?new AbortController():null;render();
 const sig=l.ac?{signal:l.ac.signal}:{};
 try{
  for(let att=0;att<2;att++){
   const r=await fetch(`/api/begin?game=${id}&total=${total}&chunk=${CH}&fp=${fp}`,{method:"POST"});
   if(!r.ok){l.phase="failed";l.err=(await r.json().catch(()=>({}))).error||"net";return}
   const info=await r.json().catch(()=>({})),have=new Set(info.resume||[]),todo=[];
   for(let o=0;o<total;o+=CH)if(!have.has(o))todo.push(o);
   let fail=false;
   const worker=async()=>{for(;;){const off=todo.shift();if(off===undefined||fail||l.cancel)return;
    const blob=f.slice(off,Math.min(off+CH,total));let ok=false;
    for(let a=0;a<6&&!ok&&!l.cancel;a++){try{ok=(await fetch(`/api/chunk?game=${id}&off=${off}&total=${total}`,{method:"PUT",body:blob,...sig})).ok}catch(e){}if(!ok&&!l.cancel)await new Promise(r=>setTimeout(r,500))}
    if(!ok){fail=true;return}}};
   await Promise.all(Array.from({length:PAR},worker));
   if(l.cancel){l.phase="gone";return}
   if(fail){l.phase="failed";l.err="net";return}
   l.phase="verifying";render();
   const s=await fetch(`/api/start?game=${id}`,{method:"POST"});  // 422 = rejected, the reason arrives through the status
   if(s.status!==409){l.phase="sent";return}}
  l.phase="failed";l.err="incomplete"}
 catch(e){if(l.cancel)l.phase="gone";else{l.phase="failed";l.err="net"}}}

async function cancel(id){
 const l=loc[id];if(l){l.cancel=true;if(l.ac)l.ac.abort()}
 const q=queue.indexOf(id);if(q>=0)queue.splice(q,1);
 try{await fetch(`/api/cancel?game=${id}`,{method:"POST"})}catch(e){}
 if(l&&(l.phase==="pending"||l.phase==="failed"||l.phase==="gone"))delete loc[id];
 poll(true)}

function view(id){  // -> {ph, reason}
 const l=loc[id],s=st.games[id]||{phase:"idle"};
 if(l&&l.phase==="failed")return{ph:"failed",reason:l.err};
 if(l&&["pending","uploading","verifying"].includes(l.phase)&&s.phase!=="uploading")return{ph:l.phase};
 if(l&&l.phase==="sent"&&s.phase==="idle")return{ph:"verifying"};
 return{ph:s.phase,reason:s.reason}}

function build(){
 built=true;
 $("#cards").innerHTML=G.map(([id,name,n])=>`<section class="card g${n}" id="c-${id}"><div class="art"><span>${n}</span></div><div class="body">
<div class="row"><h2>${name}</h2><span class="tag acc" id="${id}-reg"></span><span class="tag" id="${id}-inst"></span><span class="pct" id="${id}-pct"></span></div>
<div class="msg" id="${id}-msg"></div><div class="bar" id="${id}-bw"><i id="${id}-b"></i></div><div class="bar thin" id="${id}-sw"><i id="${id}-sb"></i></div>
<div class="meta" id="${id}-meta"></div><div class="steps" id="${id}-steps"></div><div class="acts" id="${id}-acts"></div></div></section>`).join("")}

function render(){
 if(!built)build();
 setT("#lang",L==="en"?"Deutsch":"English");setT("#lead",t("lead"));setH("#droptxt",t("drop"));setT("#foot",t("foot"));setT("#delisot",t("delete_iso"));
 document.documentElement.lang=L;
 setH("#bad",bad.length?t("bad")+bad.map(b=>`<div>${esc(b.name)}: ${t(b.why)}</div>`).join(""):"");
 const cb=$("#deliso");if(st.settings&&document.activeElement!==cb)cb.checked=!!st.settings.delete_iso;
 for(const [id] of G){
  const s=st.games[id]||{},v=view(id),l=loc[id],det=(l&&l.det)||(s.serial?{serial:s.serial,region:s.region}:null),ph=v.ph;
  let msg=s.installed?t("again"):t("idle"),cls="msg",pct=-1,spct=-1,meta="",step=-1,acts="",card="card g"+id.slice(3),bcls="bar",sbcls="bar thin";
  const eta=s.eta>=0?" · "+mmss(s.eta)+" "+t("eta"):"",cbtn=`<button class="sub" onclick="cancel('${id}')">${t("cancel")}</button>`;
  if(ph==="pending"){msg=t("waiting");step=0;acts=cbtn}
  else if(ph==="uploading"){
   const mine=l&&l.phase==="uploading",b=s.bytes||0,tot=s.total||(l&&l.file.size)||1,sp=s.speed||0;step=0;card+=" act";
   pct=s.percent>=0?s.percent:0;spct=Math.min(100,100*b/tot);
   if(mine||!stalled(s)){msg=t("uploading")+" "+spct.toFixed(0)+"%";meta=`${fmt(b)} / ${fmt(tot)}${sp?" · "+rate(sp):""}${eta}`}
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
   const r=v.reason||"extract";msg=t(["extract","decompile","compile"].includes(r)?"f_"+r:r);cls+=" err";card+=" err";bcls+=" err";pct=Math.max(0,s.percent||0);
   acts=`<button class="go" onclick="$('#file').click()">${t("retry")}</button><button class="sub" onclick="cancel('${id}')">${t("dismiss")}</button>`}
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
$("#drop").onclick=()=>$("#file").click();
$("#drop").onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();$("#file").click()}};
$("#file").onchange=e=>{addFiles([...e.target.files]);e.target.value=""};
$("#deliso").onchange=e=>{fetch("/api/settings?delete_iso="+(e.target.checked?1:0),{method:"POST"}).then(r=>r.json()).then(onStatus).catch(()=>{})};
for(const ev of["dragover","dragenter"])document.addEventListener(ev,e=>{e.preventDefault();$("#drop").classList.add("over")});
for(const ev of["dragleave","drop"])document.addEventListener(ev,e=>{e.preventDefault();$("#drop").classList.remove("over")});
document.addEventListener("drop",e=>{const d=$("#drop");d.classList.add("pulse");setTimeout(()=>d.classList.remove("pulse"),500);addFiles([...e.dataTransfer.files])});
window.addEventListener("beforeunload",e=>{if(running){e.preventDefault();e.returnValue=""}});
setInterval(poll,250);live();poll(true);render();
</script></body></html>)HTML";
}  // namespace

const char* ps5_web_page() { return kPage; }
