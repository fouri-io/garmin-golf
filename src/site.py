"""Static site generator — renders a responsive PWA dashboard from the processed JSON.

Reads data/processed/{progress,club_stats}.json and emits site/index.html: one
self-contained file (data inlined, no fetch/CORS) that works opened locally today
and drops into S3 + CloudFront unchanged later. Mobile-first and responsive — the
phone view and the wide view are the same page.

Baselines are computed from real data only:
  - Scratch  : the SG numbers as stored (the fixed ruler)
  - My average: each window minus your all-time average (re-centered on yourself;
    + = better than your season norm)
A "Target handicap" baseline needs published handicap expected-strokes tables — a
future addition; not faked here.

Usage:  python -m src.site
"""

from __future__ import annotations

import json
from pathlib import Path

PROCESSED = Path("data/processed")
OUT_DIR = Path("site")


def build() -> Path:
    progress = json.loads((PROCESSED / "progress.json").read_text())
    clubs = json.loads((PROCESSED / "club_stats.json").read_text())
    data = {"progress": progress, "clubs": clubs}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.replace("/*__DATA__*/null", json.dumps(data))
    out = OUT_DIR / "index.html"
    out.write_text(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#15497a">
<title>Golf Progress</title>
<style>
  :root{--bg:#eef1f4;--card:#fff;--ink:#1c2530;--muted:#7a8794;--line:#e9edf1;
    --good:#1f9d57;--bad:#d6443c;--accent:#15497a;--warn:#e8a33d;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
  .app{max-width:920px;margin:0 auto;min-height:100vh;background:var(--bg);
    padding:0 14px calc(84px + env(safe-area-inset-bottom));position:relative}
  .top{display:flex;align-items:center;justify-content:space-between;
    padding:calc(14px + env(safe-area-inset-top)) 4px 8px}
  .top h1{font-size:19px;margin:0} .top .date{font-size:12px;color:var(--muted)}
  .refresh{width:38px;height:38px;border-radius:50%;background:var(--accent);color:#fff;border:0;
    font-size:18px;box-shadow:0 2px 6px rgba(21,73,122,.4);cursor:pointer}
  .ctl{margin:8px 0}.ctl .lab{font-size:10px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.05em;margin:0 2px 4px;display:block}
  .seg{display:flex;background:#e2e7ec;border-radius:12px;padding:3px}
  .seg button{flex:1;border:0;background:none;padding:9px 4px;border-radius:9px;font-size:13px;
    color:var(--muted);font-weight:600;cursor:pointer}
  .seg button.on{background:#fff;color:var(--accent);box-shadow:0 1px 2px rgba(0,0,0,.1)}
  .hero{background:linear-gradient(135deg,#15497a,#1d6fb8);color:#fff;border-radius:18px;
    padding:16px;margin:12px 0}
  .hero .lab{font-size:11px;opacity:.85;text-transform:uppercase;letter-spacing:.05em}
  .hero .big{font-size:42px;font-weight:800;line-height:1;margin:4px 0}
  .hero .sub{font-size:12px;opacity:.92}
  .pill{display:inline-block;background:rgba(255,255,255,.22);border-radius:20px;padding:1px 9px;
    font-size:11px;font-weight:700;margin-left:6px;vertical-align:middle}
  .tiles{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:12px}
  @media(min-width:620px){.tiles{grid-template-columns:repeat(4,1fr)}}
  .tile{background:var(--card);border-radius:14px;padding:12px}
  .tile .lab{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .tile .v{font-size:22px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
  .neg{color:var(--bad)}.pos{color:var(--good)}.mut{color:var(--muted)}
  .card{background:var(--card);border-radius:16px;padding:14px;margin-bottom:12px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 8px}
  .leakcall{display:flex;align-items:center;gap:10px;background:#fbeceb;border-radius:12px;
    padding:12px;margin-bottom:12px}
  .leakcall .ico{font-size:22px}.leakcall b{color:var(--bad)}
  .bars{display:flex;justify-content:space-between;height:160px;position:relative;margin:6px 0 26px}
  .zero{position:absolute;left:0;right:0;top:50%;border-top:1px dashed #c4ccd4}
  .col{flex:1;position:relative}
  .bar{position:absolute;left:22%;right:22%;border-radius:5px}
  .bar.r{background:var(--bad)}.bar.g{background:var(--good)}
  .vlab{position:absolute;left:0;right:0;text-align:center;font-size:11px;font-weight:700;
    font-variant-numeric:tabular-nums}
  .clab{position:absolute;left:-6px;right:-6px;bottom:-22px;text-align:center;font-size:10px;color:var(--muted)}
  .foot{font-size:11px;color:var(--muted)}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
  th,td{text-align:right;padding:7px 6px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}
  thead th{font-size:11px;color:var(--muted);font-weight:600}
  .warn{color:var(--warn)}
  .tabbar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--line);
    display:flex;justify-content:space-around;padding:8px 0 calc(10px + env(safe-area-inset-bottom));
    z-index:10}
  .tabbar .t{font-size:11px;color:var(--muted);text-align:center;cursor:pointer;border:0;background:none}
  .tabbar .t.on{color:var(--accent)}.tabbar .t .i{font-size:18px;display:block}
  .hide{display:none}
  .legend{font-size:12px;color:#2c4763;background:#eef4fb;border:1px solid #d8e6f5;
    border-radius:10px;padding:8px 12px;margin-bottom:10px}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div><h1>⛳ Golf Progress</h1><div class="date" id="date"></div></div>
    <button class="refresh" title="Rebuild from latest data (wire to your pipeline)">⟳</button>
  </div>

  <!-- PROGRESS TAB -->
  <div id="tab-progress">
    <div class="ctl"><span class="lab">Window — which rounds you're viewing</span>
      <div class="seg" id="win">
        <button data-w="thisRound">This round</button>
        <button class="on" data-w="last5">Last 5</button>
        <button data-w="allTime">All-time</button>
      </div></div>

    <div class="hero">
      <div class="lab">Scoring · over rating <span class="pill" id="winpill">Last 5</span></div>
      <div class="big" id="score">—</div>
      <div class="sub" id="scoresub"></div>
    </div>

    <div class="tiles">
      <div class="tile"><div class="lab">SG 0–100</div><div class="v" id="lev">—</div></div>
      <div class="tile"><div class="lab">Penalties /18</div><div class="v" id="pen">—</div></div>
      <div class="tile"><div class="lab">Doubles+ /18</div><div class="v" id="dbl">—</div></div>
      <div class="tile"><div class="lab">3-putts /18</div><div class="v" id="tp">—</div></div>
    </div>

    <div class="leakcall"><div class="ico">🎯</div>
      <div>#1 leak: <b id="leak">—</b><br><span class="foot">your highest-return practice target</span></div></div>

    <div class="card">
      <h2>Strokes Gained</h2>
      <div class="ctl" style="margin:0 0 6px"><span class="lab">Compare vs</span>
        <div class="seg" id="base">
          <button class="on" data-b="scratch">Scratch</button>
          <button data-b="myavg">My average</button>
        </div></div>
      <div class="bars" id="bars"><div class="zero"></div></div>
      <div class="foot" id="bf"></div>
    </div>
  </div>

  <!-- ROUNDS TAB -->
  <div id="tab-rounds" class="hide">
    <div class="legend">vsRtg = score over course rating (per 18). ⚠ = over-recorded (excluded from SG form).</div>
    <div class="card"><table><thead><tr><th>Date</th><th>Course</th><th>Score</th><th>vsRtg</th></tr></thead>
      <tbody id="roundsbody"></tbody></table></div>
  </div>

  <!-- CLUBS TAB -->
  <div id="tab-clubs" class="hide">
    <div class="legend">Full-swing shots only; median is your stock yardage. ⚠ = low sample.</div>
    <div class="card"><table><thead><tr><th>Club</th><th>n</th><th>Median</th><th>p25–p75</th><th>Max</th></tr></thead>
      <tbody id="clubsbody"></tbody></table></div>
  </div>

  <!-- MAPS TAB -->
  <div id="tab-maps" class="hide">
    <div class="card"><h2>Shot maps</h2>
      <div class="foot">Coming soon — satellite overlays of your georeferenced shots (we already store lat/lon for every shot).</div></div>
  </div>
</div>

<div class="tabbar" id="tabs">
  <button class="t on" data-t="progress"><span class="i">📊</span>Progress</button>
  <button class="t" data-t="rounds"><span class="i">⛳</span>Rounds</button>
  <button class="t" data-t="clubs"><span class="i">🏌️</span>Clubs</button>
  <button class="t" data-t="maps"><span class="i">🗺️</span>Maps</button>
</div>

<script>
const DATA = /*__DATA__*/null;
const P = DATA.progress, SG = P.sg, AU = P.authoritative;
const CATS=[["offTee","Off-Tee"],["longApproach","Long"],["midApproach","Mid"],
            ["inside50","In50"],["putting","Putt"]];
const WLAB={thisRound:"This round",last5:"Last 5",allTime:"All-time"};
let win="last5", base="scratch";

document.getElementById('date').textContent =
  "Updated "+(P.thisRoundDate||"")+" · "+P.generatedFromRounds+" rounds";

function bucket(w,b,key){
  const s = SG[w] ? SG[w].byCategory[key] : null;
  if(s===null) return null;
  return b==="scratch" ? s : s - SG.allTime.byCategory[key];   // myavg = vs season norm
}
function lever(w,b){
  if(!SG[w]) return null;
  const s = SG[w].sg0to100;
  return b==="scratch" ? s : s - SG.allTime.sg0to100;
}
function fmt(v){return v===null?"—":(v>0?"+":"")+v.toFixed(1);}

function renderProgress(){
  document.getElementById('winpill').textContent=WLAB[win];
  const sc=AU[win];
  document.getElementById('score').textContent = sc.overRating18===null?"—":"+"+sc.overRating18;
  document.getElementById('scoresub').textContent =
    `potential +${P.scoring.potentialOverRating18} · Break 90 = +${P.scoring.break90OverRating} · authoritative`;
  const lv=lever(win,base), le=document.getElementById('lev');
  le.textContent=fmt(lv); le.className="v "+(lv===null?"":lv>=0?"pos":"neg");
  document.getElementById('pen').textContent=sc.penalties18.toFixed(1);
  const db=document.getElementById('dbl'); db.textContent=sc.doubles18.toFixed(1);
  db.className="v "+(sc.doubles18>=4?"neg":"");
  document.getElementById('tp').textContent=sc.threePutts18.toFixed(1);

  const vals=CATS.map(([k])=>bucket(win,base,k));
  if(vals.some(v=>v===null)){
    document.getElementById('leak').textContent="this round was over-recorded — SG unavailable";
  } else {
    let li=0; vals.forEach((v,i)=>{if(v<vals[li])li=i;});
    const full={offTee:"Off-the-Tee",longApproach:"Long approach 150+",midApproach:"Mid approach 50–150",
      inside50:"Inside 50",putting:"Putting"}[CATS[li][0]];
    document.getElementById('leak').textContent=`${full} (${vals[li].toFixed(1)})`;
  }
  document.getElementById('bf').innerHTML = base==="scratch"
    ? "Bars vs <b>scratch</b> (the fixed ruler) — negative is normal, toward 0 is better."
    : "Bars vs <b>your season average</b> — green = better than your norm, red = worse.";
  drawBars(vals);
}
function drawBars(vals){
  const host=document.getElementById('bars');
  host.querySelectorAll('.col').forEach(c=>c.remove());
  const clean=vals.filter(v=>v!==null);
  const mx=Math.max(...clean.map(v=>Math.abs(v)),3), half=70;
  CATS.forEach(([k,short],i)=>{
    const v=vals[i], col=document.createElement('div'); col.className='col';
    if(v===null){col.innerHTML=`<div class="clab">${short}</div>`;host.appendChild(col);return;}
    const h=Math.abs(v)/mx*half;
    const top = v>=0 ? (half-h) : half;
    const vtop = v>=0 ? (half-h-15) : (half+h+2);
    col.innerHTML=`<div class="bar ${v>=0?'g':'r'}" style="top:${top}px;height:${h}px"></div>
      <div class="vlab ${v>=0?'pos':'neg'}" style="top:${vtop}px">${v>0?'+':''}${v.toFixed(1)}</div>
      <div class="clab">${short}</div>`;
    host.appendChild(col);
  });
}
function renderRounds(){
  document.getElementById('roundsbody').innerHTML = P.timeSeries.slice().reverse().map(r=>{
    const flag = r.clean ? "" : " ⚠";
    const ovr = r.overRating18===null?"—":"+"+r.overRating18;
    return `<tr><td>${r.date}${flag}</td><td>${r.course.slice(0,22)}</td>
      <td>${r.score} <span class="mut">(${r.holes})</span></td><td>${ovr}</td></tr>`;
  }).join("");
}
function renderClubs(){
  document.getElementById('clubsbody').innerHTML = DATA.clubs.clubs.map(c=>{
    if(c.medianYds===null) return `<tr><td>${c.club}</td><td>${c.shots}</td><td>—</td><td>—</td><td>—</td></tr>`;
    const w=c.lowConfidence?" ⚠":"";
    return `<tr><td>${c.club}${w}</td><td>${c.distanceShots}</td><td><b>${c.medianYds}</b></td>
      <td>${c.p25Yds}–${c.p75Yds}</td><td>${c.maxYds}</td></tr>`;
  }).join("");
}

document.getElementById('win').onclick=e=>{if(!e.target.dataset.w)return;win=e.target.dataset.w;
  [...e.currentTarget.children].forEach(b=>b.classList.toggle('on',b===e.target));renderProgress();};
document.getElementById('base').onclick=e=>{if(!e.target.dataset.b)return;base=e.target.dataset.b;
  [...e.currentTarget.children].forEach(b=>b.classList.toggle('on',b===e.target));renderProgress();};
document.getElementById('tabs').onclick=e=>{const t=e.target.closest('[data-t]');if(!t)return;
  [...e.currentTarget.children].forEach(b=>b.classList.toggle('on',b===t));
  ['progress','rounds','clubs','maps'].forEach(n=>
    document.getElementById('tab-'+n).classList.toggle('hide',n!==t.dataset.t));};

renderProgress(); renderRounds(); renderClubs();
</script>
</body>
</html>
"""


def main() -> None:
    out = build()
    print(f"Wrote {out}  (open it, or host site/ on S3 + CloudFront)")


if __name__ == "__main__":
    main()
