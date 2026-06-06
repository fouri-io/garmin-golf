"""Static site generator — responsive PWA dashboard from the processed JSON.

Reads data/processed/{progress,club_stats}.json + the per-round documents and emits
site/index.html: one self-contained file (data inlined, no fetch — works from file://
and drops into S3 + CloudFront unchanged). Mobile-first and responsive.

Baselines come from progress.json (Scratch / My-average / Target-H), all computed
from real data; Target is a documented model, not faked.

Usage:  python -m src.site
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

PROCESSED = Path("data/processed")
ROUNDS_DIR = PROCESSED / "rounds"
OUT_DIR = Path("site")


def _ll(loc: dict | None) -> list | None:
    """A location dict -> [lat, lon] for mapping, or None if no coordinates."""
    return [loc["lat"], loc["lon"]] if loc and loc.get("lat") is not None else None


def _compact_round(path: Path) -> dict:
    d = json.loads(path.read_text())
    sc, rnd, course = d["score"], d["round"], d["course"]
    sg = d["strokesGained"]
    holes = sc["holesCompleted"] or 18
    rating = rnd.get("teeBoxRating")
    holes_detail = [{
        "n": h["number"], "par": h["par"], "strokes": h["strokes"], "putts": h["putts"],
        "pen": h["penalties"], "toPar": h["scoreToPar"], "name": h["scoreName"],
        "fw": h["fairway"], "gir": h["gir"], "pin": _ll(h.get("pin")),
        "shots": [{
            "n": s["shotNumber"], "club": s["club"], "type": s["type"], "yards": s["yards"],
            "from": s["from"], "to": s["to"], "sg": s["strokesGained"],
            "before": s["distanceToPinBeforeYds"], "rem": s["distanceRemainingYds"],
            "cat": s["sgCategory"], "src": s["source"],
            "start": _ll(s.get("start")), "end": _ll(s.get("end")),
        } for s in h["shots"]],
    } for h in d["holes"]]
    return {
        "stem": path.stem, "date": rnd["date"][:10], "course": course["name"],
        "score": sc["strokes"], "toPar": sc.get("toPar"), "par": course["par"], "holes": holes,
        "overRating18": round((sc["strokes"] - rating) * 18 / holes, 1) if rating else None,
        "tees": rnd.get("teeBox"), "rating": rating, "slope": rnd.get("teeBoxSlope"),
        "putts": sc["putts"], "penalties": sc["penalties"],
        "doubles": sg.get("doublesOrWorse", 0),
        "sg": sg["byCategory"], "sgTotal": sg["totalRecordedVsScratch"],
        "sg0to100": sg.get("sg0to100", 0),
        "putting": sg["putting"],
        "polluted": bool(d["reconciliation"]["suspectHoles"]),
        "holesDetail": holes_detail,
    }


def build() -> Path:
    progress = json.loads((PROCESSED / "progress.json").read_text())
    clubs = json.loads((PROCESSED / "club_stats.json").read_text())
    rounds = sorted((_compact_round(Path(p)) for p in glob.glob(str(ROUNDS_DIR / "*.json"))),
                    key=lambda r: r["date"], reverse=True)
    data = {"progress": progress, "clubs": clubs, "rounds": rounds}
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
<meta name="robots" content="noindex, nofollow">
<title>Golf Progress</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root{--bg:#eef1f4;--card:#fff;--ink:#1c2530;--muted:#7a8794;--line:#e9edf1;
    --good:#1f9d57;--bad:#d6443c;--accent:#15497a;--warn:#e8a33d;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
  .app{max-width:920px;margin:0 auto;min-height:100vh;
    padding:0 14px calc(86px + env(safe-area-inset-bottom))}
  .top{display:flex;align-items:center;justify-content:space-between;
    padding:calc(14px + env(safe-area-inset-top)) 4px 8px}
  .top h1{font-size:19px;margin:0}.top .date{font-size:12px;color:var(--muted)}
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
  .lever h2{margin-bottom:10px}
  .lev3{display:flex;gap:8px;text-align:center}
  .lev3>div{flex:1;border-radius:12px;padding:10px 4px;background:#f3f6f9;cursor:pointer;
    border:2px solid transparent}
  .lev3>div.on{background:#eaf1f8;border-color:var(--accent)}
  .lev3 .wl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .lev3 .wv{font-size:25px;font-weight:800;font-variant-numeric:tabular-nums;margin-top:2px}
  .leakcall{display:flex;align-items:center;gap:10px;background:#fbeceb;border-radius:12px;
    padding:12px;margin-bottom:12px}
  .leakcall .ico{font-size:22px}.leakcall b{color:var(--bad)}
  .bars{display:flex;justify-content:space-between;height:160px;position:relative;margin:6px 0 28px}
  .zero{position:absolute;left:0;right:0;top:50%;border-top:1px dashed #c4ccd4}
  .col{flex:1;position:relative}
  .bar{position:absolute;left:22%;right:22%;border-radius:5px}
  .bar.r{background:var(--bad)}.bar.g{background:var(--good)}
  .vlab{position:absolute;left:0;right:0;text-align:center;font-size:11px;font-weight:700;
    font-variant-numeric:tabular-nums}
  .clab{position:absolute;left:-6px;right:-6px;bottom:-22px;text-align:center;font-size:10px;color:var(--muted)}
  .foot{font-size:11px;color:var(--muted)}
  /* rounds list */
  .rcard{display:flex;align-items:center;gap:12px;background:var(--card);border-radius:14px;
    padding:12px 14px;margin-bottom:9px;cursor:pointer;border:1px solid var(--line)}
  .rcard:active{background:#f7f9fb}
  .rcard .sc{font-size:22px;font-weight:800;min-width:46px}
  .rcard .meta{flex:1}.rcard .meta .c{font-weight:600}.rcard .meta .d{font-size:12px;color:var(--muted)}
  .rcard .sg{text-align:right;font-size:12px;color:var(--muted)}
  /* round detail */
  .back{border:0;background:#e2e7ec;border-radius:10px;padding:7px 12px;font-weight:600;
    color:var(--accent);cursor:pointer;margin-bottom:10px;font-size:13px}
  .kchips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
  .chip{background:var(--card);border-radius:12px;padding:8px 12px;border:1px solid var(--line)}
  .chip .l{font-size:10px;color:var(--muted);text-transform:uppercase}
  .chip .v{font-size:18px;font-weight:700}
  .hole{background:var(--card);border-radius:12px;padding:10px 12px;margin-bottom:8px}
  .hrow{display:flex;align-items:center;gap:8px;font-size:13px}
  .sbox{min-width:26px;text-align:center;border-radius:6px;padding:1px 6px;font-weight:800}
  .par{background:#e6f4ec;color:#1f7a45}.bogey{background:#fdeee0;color:#b5701c}
  .dbl{background:#fbe2df;color:#b5322a}.birdie{background:#e2eefb;color:#2a5db5}
  .hrow .gap{flex:1}.hrow .mini{color:var(--muted);font-size:12px}
  .maplink{border:0;background:#eaf1f8;color:var(--accent);border-radius:8px;padding:4px 8px;
    font-size:12px;font-weight:600;cursor:pointer;margin-left:8px;white-space:nowrap}
  .shots{margin:8px 0 0;font-size:12.5px;color:#41505e}
  .shots div{padding:2px 0;display:flex;gap:6px}
  .shots .sn{color:var(--muted);min-width:16px}.shots .sg{margin-left:auto;font-variant-numeric:tabular-nums}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:13px}
  th,td{text-align:right;padding:7px 6px;border-bottom:1px solid var(--line)}
  th:first-child,td:first-child{text-align:left}thead th{font-size:11px;color:var(--muted);font-weight:600}
  .legend{font-size:12px;color:#2c4763;background:#eef4fb;border:1px solid #d8e6f5;
    border-radius:10px;padding:8px 12px;margin-bottom:10px}
  /* trend */
  .tpill{font-size:11px;font-weight:700;border-radius:20px;padding:2px 9px}
  .tpill.up{background:#e4f5ec;color:var(--good)}.tpill.down{background:#fbe7e5;color:var(--bad)}
  .tpill.flat{background:#eef1f4;color:var(--muted)}
  #trendhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
  /* maps */
  .rsel{width:100%;background:var(--card);color:var(--ink);border:1px solid var(--line);
    border-radius:12px;padding:11px 12px;font-size:15px;font-weight:600;margin-bottom:8px}
  .holenav{display:flex;align-items:center;gap:10px;margin-bottom:8px}
  .holenav button{flex:0 0 auto;width:46px;height:42px;border:0;border-radius:12px;background:var(--accent);
    color:#fff;font-size:18px;cursor:pointer}.holenav button:disabled{opacity:.35}
  .holenav .hl{flex:1;text-align:center;font-weight:700;font-size:15px}
  #map{height:60vh;min-height:340px;border-radius:14px;overflow:hidden;background:#1c2530}
  .dot{border:2px solid #fff;border-radius:50%;width:16px;height:16px;box-shadow:0 1px 3px rgba(0,0,0,.5)}
  .tag{background:rgba(17,21,27,.78);color:#fff;border:0;border-radius:6px;padding:1px 5px;
    font:600 11px -apple-system,Arial;white-space:nowrap}.leaflet-tooltip.tag:before{display:none}
  .mlegend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}
  .mlegend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px}
  .tabbar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--line);
    display:flex;justify-content:space-around;padding:8px 0 calc(10px + env(safe-area-inset-bottom));z-index:10}
  .tabbar .t{font-size:11px;color:var(--muted);text-align:center;cursor:pointer;border:0;background:none}
  .tabbar .t.on{color:var(--accent)}.tabbar .t .i{font-size:18px;display:block}
  .hide{display:none}
</style>
</head>
<body>
<div class="app">
  <div class="top"><div><h1>⛳ Golf Progress</h1><div class="date" id="date"></div></div>
    <button class="refresh" title="Rebuild from latest data">⟳</button></div>

  <div id="tab-progress">
    <div class="ctl"><span class="lab">Window — which rounds you're viewing</span>
      <div class="seg" id="win">
        <button data-w="thisRound">This round</button>
        <button class="on" data-w="last5">Last 5</button>
        <button data-w="allTime">All-time</button></div></div>
    <div class="hero"><div class="lab">Scoring · over rating <span class="pill" id="winpill"></span></div>
      <div class="big" id="score">—</div><div class="sub" id="scoresub"></div></div>
    <div class="card lever"><h2>SG 0–100 · leverage number
        <span class="mut" style="text-transform:none;font-weight:400;letter-spacing:0"> — 100yd &amp; in, no putts · where scores move</span></h2>
      <div class="lev3" id="lev3">
        <div data-w="thisRound"><div class="wl">This round</div><div class="wv">—</div></div>
        <div data-w="last5"><div class="wl">Last 5</div><div class="wv">—</div></div>
        <div data-w="allTime"><div class="wl">All-time</div><div class="wv">—</div></div></div></div>
    <div class="tiles">
      <div class="tile"><div class="lab">Putts /18</div><div class="v" id="putts">—</div></div>
      <div class="tile"><div class="lab">Penalties /18</div><div class="v" id="pen">—</div></div>
      <div class="tile"><div class="lab">Doubles+ /18</div><div class="v" id="dbl">—</div></div>
      <div class="tile"><div class="lab">3-putts /18</div><div class="v" id="tp">—</div></div></div>
    <div class="leakcall"><div class="ico">🎯</div>
      <div>#1 leak: <b id="leak">—</b><br><span class="foot">your highest-return practice target</span></div></div>
    <div class="card"><h2>Strokes Gained</h2>
      <div class="ctl" style="margin:0 0 6px"><span class="lab">Compare vs</span>
        <div class="seg" id="base"></div></div>
      <div class="bars" id="bars"><div class="zero"></div></div>
      <div class="foot" id="bf"></div></div>
  </div>

  <div id="tab-trend" class="hide">
    <div class="ctl"><span class="lab">Metric over time</span>
      <select class="rsel" id="trendMetric"></select></div>
    <div class="card"><div id="trendhead"></div><div id="trendchart"></div>
      <div class="foot" id="trendfoot"></div></div>
    <div class="foot" style="padding:0 4px">Each point is a round, oldest → newest.
      Filled = clean round; grey = over-recorded (kept for score, excluded from SG).</div>
  </div>

  <div id="tab-rounds" class="hide">
    <div id="roundsList"></div>
    <div id="roundDetail" class="hide"></div>
  </div>

  <div id="tab-clubs" class="hide">
    <div class="legend">Full-swing shots only; median is your stock yardage. ⚠ = low sample.</div>
    <div class="card"><table><thead><tr><th>Club</th><th>n</th><th>Median</th><th>p25–p75</th><th>Max</th></tr></thead>
      <tbody id="clubsbody"></tbody></table></div></div>

  <div id="tab-maps" class="hide">
    <select class="rsel" id="mapRound"></select>
    <div class="holenav"><button id="hprev">◀</button>
      <div class="hl" id="hlabel">—</div><button id="hnext">▶</button></div>
    <div id="map"></div>
    <div class="mlegend"><span><i style="background:#1f9d57"></i>gained</span>
      <span><i style="background:#e8a33d"></i>~even</span>
      <span><i style="background:#d6443c"></i>lost</span>
      <span><i style="background:#9aa6b2"></i>putt</span>
      <span>· tap a shot for detail · GPS-approximate</span></div></div>
</div>

<div class="tabbar" id="tabs">
  <button class="t on" data-t="progress"><span class="i">📊</span>Overview</button>
  <button class="t" data-t="trend"><span class="i">📈</span>Trend</button>
  <button class="t" data-t="rounds"><span class="i">⛳</span>Rounds</button>
  <button class="t" data-t="clubs"><span class="i">🏌️</span>Clubs</button>
  <button class="t" data-t="maps"><span class="i">🗺️</span>Maps</button>
</div>

<script>
const DATA = /*__DATA__*/null;
const P=DATA.progress, SG=P.sg, AU=P.authoritative, BL=P.baselines;
const CATS=[["offTee","Off-Tee"],["longApproach","Long"],["midApproach","Mid"],
            ["inside50","In50"],["putting","Putt"]];
const FULL={offTee:"Off-the-Tee",longApproach:"Long approach 150+",midApproach:"Mid approach 50–150",
  inside50:"Inside 50",putting:"Putting"};
const WLAB={thisRound:"This round",last5:"Last 5",allTime:"All-time"};
let win="last5", base="scratch", detailRound=0;

document.getElementById('date').textContent="Updated "+(P.thisRoundDate||"")+" · "+P.generatedFromRounds+" rounds";

// baseline buttons from data
document.getElementById('base').innerHTML=Object.keys(BL).map((k,i)=>
  `<button class="${i===0?'on':''}" data-b="${k}">${BL[k].label}</button>`).join("");

function off(b,key){return BL[b].byCategory[key]||0;}
function bucket(w,b,key){return SG[w]?SG[w].byCategory[key]-off(b,key):null;}
function lever(w,b){return SG[w]?SG[w].sg0to100-(BL[b].sg0to100||0):null;}
function fmt(v){return v===null?"—":(v>0?"+":"")+v.toFixed(1);}

function renderProgress(){
  document.getElementById('winpill').textContent=WLAB[win];
  const sc=AU[win];
  document.getElementById('score').textContent=sc.overRating18===null?"—":"+"+sc.overRating18;
  document.getElementById('scoresub').textContent=
    `potential +${P.scoring.potentialOverRating18} · Break 90 = +${P.scoring.break90OverRating} · authoritative`;
  ['thisRound','last5','allTime'].forEach(w=>{
    const lv=lever(w,base),cell=document.querySelector(`#lev3 [data-w="${w}"]`),v=cell.querySelector('.wv');
    v.textContent=fmt(lv);v.className="wv "+(lv===null?"mut":lv>=0?"pos":"neg");
    cell.classList.toggle('on',w===win);});
  document.getElementById('putts').textContent=sc.putts18.toFixed(0);
  document.getElementById('pen').textContent=sc.penalties18.toFixed(1);
  const db=document.getElementById('dbl');db.textContent=sc.doubles18.toFixed(1);
  db.className="v "+(sc.doubles18>=4?"neg":"");
  document.getElementById('tp').textContent=sc.threePutts18.toFixed(1);
  const vals=CATS.map(([k])=>bucket(win,base,k));
  if(vals.some(v=>v===null)){document.getElementById('leak').textContent="this round was over-recorded — SG unavailable";}
  else{let li=0;vals.forEach((v,i)=>{if(v<vals[li])li=i;});
    document.getElementById('leak').textContent=`${FULL[CATS[li][0]]} (${vals[li].toFixed(1)})`;}
  document.getElementById('bf').innerHTML=
    base==="scratch"?"Bars vs <b>scratch</b> (fixed ruler) — negative is normal, toward 0 is better.":
    base==="myAverage"?"Bars vs <b>your season average</b> — green = better than your norm.":
    "Bars vs <b>"+BL[base].label+"</b> (modeled) — each red is a gap to reach that level.";
  drawBars(vals);
}
function drawBars(vals){
  const host=document.getElementById('bars');host.querySelectorAll('.col').forEach(c=>c.remove());
  const clean=vals.filter(v=>v!==null),mx=Math.max(...clean.map(v=>Math.abs(v)),3),half=70;
  CATS.forEach(([k,short],i)=>{const v=vals[i],col=document.createElement('div');col.className='col';
    if(v===null){col.innerHTML=`<div class="clab">${short}</div>`;host.appendChild(col);return;}
    const h=Math.abs(v)/mx*half,top=v>=0?half-h:half,vt=v>=0?half-h-15:half+h+2;
    col.innerHTML=`<div class="bar ${v>=0?'g':'r'}" style="top:${top}px;height:${h}px"></div>
      <div class="vlab ${v>=0?'pos':'neg'}" style="top:${vt}px">${v>0?'+':''}${v.toFixed(1)}</div>
      <div class="clab">${short}</div>`;host.appendChild(col);});
}

/* ---- rounds ---- */
function renderRoundsList(){
  document.getElementById('roundDetail').classList.add('hide');
  const list=document.getElementById('roundsList');list.classList.remove('hide');
  list.innerHTML=`<div class="legend">Tap a round for hole-by-hole + every shot.</div>`+
    DATA.rounds.map((r,i)=>{
      const ovr=r.overRating18===null?"":`+${r.overRating18} vs rtg`;
      const flag=r.polluted?' ⚠':'';
      return `<div class="rcard" data-r="${i}"><div class="sc">${r.score}</div>
        <div class="meta"><div class="c">${r.course}</div>
          <div class="d">${r.date} · ${r.holes} holes${flag}</div></div>
        <div class="sg">${ovr}<br>SG ${r.sgTotal.toFixed(1)}</div></div>`;}).join("");
}
function box(toPar){return toPar===null?"":toPar<0?"birdie":toPar===0?"par":toPar===1?"bogey":"dbl";}
function renderRoundDetail(i){
  const r=DATA.rounds[i];detailRound=i;
  document.getElementById('roundsList').classList.add('hide');
  const el=document.getElementById('roundDetail');el.classList.remove('hide');
  const chips=[["Score",`${r.score} (${r.toPar>=0?'+':''}${r.toPar})`],["vs rating",r.overRating18===null?'—':'+'+r.overRating18],
    ["Putts",r.putts],["Penalties",r.penalties],["Doubles+",r.doubles]];
  const sgrow=CATS.map(([k,s])=>`${s} <b class="${r.sg[k]>=0?'pos':'neg'}">${r.sg[k]>=0?'+':''}${r.sg[k].toFixed(1)}</b>`).join(" · ");
  const holes=r.holesDetail.map(h=>{
    const shots=h.shots.map(s=>{
      const yd=s.yards===null?"?":`${Math.round(s.yards)}y`;
      const rem=s.rem===null?"":` →${Math.round(s.rem)}y`;
      const sg=s.sg===null?"":`<span class="sg ${s.sg>=0?'pos':'neg'}">${s.sg>=0?'+':''}${s.sg.toFixed(1)}</span>`;
      const club=s.club==="unknown"?"(?)":s.club;
      return `<div><span class="sn">${s.n}</span>${club} ${yd} <span class="mut">${s.from}→${s.to}${rem}</span>${sg}</div>`;
    }).join("");
    const fw=h.fw?`FW:${h.fw}`:"";const gir=h.gir?"GIR":"";
    const maplink=h.shots.some(s=>s.start&&s.end)?`<button class="maplink" data-h="${h.n}">🗺️ map</button>`:'';
    return `<div class="hole"><div class="hrow">
        <span class="sbox ${box(h.toPar)}">${h.strokes}</span>
        <b>H${h.n}</b> <span class="mini">par ${h.par}</span><span class="gap"></span>
        <span class="mini">${fw} ${gir} ${h.putts}p ${h.pen?'· pen '+h.pen:''}</span>${maplink}</div>
      <div class="shots">${shots||'<span class="mut">no shots recorded</span>'}</div></div>`;
  }).join("");
  el.innerHTML=`<button class="back" id="back">← All rounds</button>
    <h2 style="margin:0 0 2px">${r.course}</h2>
    <div class="foot" style="margin-bottom:10px">${r.date} · ${r.tees} tees (${r.rating}/${r.slope})${r.polluted?' · ⚠ over-recorded round':''}</div>
    <div class="kchips">${chips.map(c=>`<div class="chip"><div class="l">${c[0]}</div><div class="v">${c[1]}</div></div>`).join("")}</div>
    <div class="card"><h2>Strokes Gained this round</h2><div style="font-size:13px">${sgrow}</div>
      <div class="foot" style="margin-top:6px">SG 0–100: <b>${r.sg0to100.toFixed(1)}</b></div></div>
    <h2 style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Hole by hole</h2>
    ${holes}`;
  document.getElementById('back').onclick=renderRoundsList;
}
document.getElementById('roundsList').onclick=e=>{const c=e.target.closest('[data-r]');if(c)renderRoundDetail(+c.dataset.r);};

function renderClubs(){
  document.getElementById('clubsbody').innerHTML=DATA.clubs.clubs.map(c=>{
    if(c.medianYds===null)return `<tr><td>${c.club}</td><td>${c.shots}</td><td>—</td><td>—</td><td>—</td></tr>`;
    const w=c.lowConfidence?" ⚠":"";
    return `<tr><td>${c.club}${w}</td><td>${c.distanceShots}</td><td><b>${c.medianYds}</b></td>
      <td>${c.p25Yds}–${c.p75Yds}</td><td>${c.maxYds}</td></tr>`;}).join("");
}

function setWin(w){win=w;
  [...document.getElementById('win').children].forEach(b=>b.classList.toggle('on',b.dataset.w===w));
  renderProgress();}
document.getElementById('win').onclick=e=>{if(e.target.dataset.w)setWin(e.target.dataset.w);};
document.getElementById('lev3').onclick=e=>{const c=e.target.closest('[data-w]');if(c)setWin(c.dataset.w);};
document.getElementById('base').onclick=e=>{if(!e.target.dataset.b)return;base=e.target.dataset.b;
  [...e.currentTarget.children].forEach(b=>b.classList.toggle('on',b===e.target));renderProgress();};
/* ---- shot maps (Leaflet + Esri satellite) ---- */
let lmap=null,mlayer=null,mRound=0,mHole=0;
const mappable=r=>r.holesDetail.filter(h=>h.shots.some(s=>s.start&&s.end));
function abbr(c){if(c==='unknown')return'?';if(/Driver/.test(c))return'Dr';if(/Putter/.test(c))return'Pt';
  let m;if(m=c.match(/(\d+)\s*Wood/))return m[1]+'W';if(m=c.match(/(\d+)\s*Hybrid/))return m[1]+'H';
  if(m=c.match(/(\d+)\s*Iron/))return m[1]+'i';if(/PW/.test(c))return'PW';
  if(m=c.match(/(\d+)\s*°/))return m[1]+'°';return c.slice(0,3);}
const sgColor=sg=>sg==null?'#9aa6b2':sg>=0.1?'#1f9d57':sg<=-0.1?'#d6443c':'#e8a33d';
const dot=c=>L.divIcon({className:'',html:`<div class="dot" style="background:${c}"></div>`,iconSize:[16,16]});
function initMap(){
  if(lmap)return;
  document.getElementById('mapRound').innerHTML=DATA.rounds.map((r,i)=>
    `<option value="${i}">${r.date} · ${r.course}${r.polluted?' ⚠':''}</option>`).join("");
  lmap=L.map('map',{zoomControl:true});
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:21,maxNativeZoom:19,attribution:'Imagery © Esri'}).addTo(lmap);
  mlayer=L.layerGroup().addTo(lmap);
  document.getElementById('mapRound').onchange=e=>{mRound=+e.target.value;mHole=0;drawHole();};
  document.getElementById('hprev').onclick=()=>{if(mHole>0){mHole--;drawHole();}};
  document.getElementById('hnext').onclick=()=>{if(mHole<mappable(DATA.rounds[mRound]).length-1){mHole++;drawHole();}};
}
function drawHole(){
  const holes=mappable(DATA.rounds[mRound]);mlayer.clearLayers();
  if(!holes.length){document.getElementById('hlabel').textContent="no GPS shots in this round";return;}
  mHole=Math.max(0,Math.min(mHole,holes.length-1));const h=holes[mHole],pts=[];
  document.getElementById('hlabel').textContent=`Hole ${h.n} · par ${h.par} · scored ${h.strokes}`;
  document.getElementById('hprev').disabled=mHole===0;
  document.getElementById('hnext').disabled=mHole===holes.length-1;
  h.shots.forEach(s=>{if(!s.start||!s.end)return;
    L.polyline([s.start,s.end],{color:'#fff',weight:2,opacity:.65}).addTo(mlayer);pts.push(s.start,s.end);
    const yd=s.yards!=null?Math.round(s.yards):'';
    const m=L.marker(s.end,{icon:dot(sgColor(s.sg))});
    m.bindPopup(`<b>#${s.n} ${s.club}</b> ${yd}y<br>${s.from} → ${s.to}`+(s.sg!=null?` · SG ${s.sg>0?'+':''}${s.sg.toFixed(1)}`:''));
    if(s.type!=='PUTT')m.bindTooltip(`${abbr(s.club)} ${yd}`,{permanent:true,direction:'right',className:'tag',offset:[8,0]});
    m.addTo(mlayer);});
  const first=h.shots.find(s=>s.start);
  if(first)L.marker(first.start,{icon:dot('#1f9d57')}).bindTooltip('Tee',{permanent:true,direction:'left',className:'tag',offset:[-8,0]}).addTo(mlayer);
  if(h.pin){L.marker(h.pin).bindPopup('📍 Pin').addTo(mlayer);pts.push(h.pin);}
  if(pts.length)lmap.fitBounds(pts,{padding:[45,45]});
}
function showMap(){initMap();setTimeout(()=>{lmap.invalidateSize();drawHole();},30);}

/* ---- trend (SVG line charts over rounds) ---- */
const TS=P.timeSeries;
const sumCats=r=>CATS.reduce((a,[k])=>a+(r.per18[k]||0),0);
const TREND=[
  {k:'total',label:'SG total (toward 0 = better)',clean:true,low:false,get:sumCats},
  {k:'over',label:'Score vs rating (lower = better)',clean:false,low:true,get:r=>r.overRating18},
  {k:'offTee',label:'SG Off-the-Tee',clean:true,low:false,get:r=>r.per18.offTee},
  {k:'longApproach',label:'SG Long approach',clean:true,low:false,get:r=>r.per18.longApproach},
  {k:'midApproach',label:'SG Mid approach',clean:true,low:false,get:r=>r.per18.midApproach},
  {k:'inside50',label:'SG Inside 50',clean:true,low:false,get:r=>r.per18.inside50},
  {k:'putting',label:'SG Putting',clean:true,low:false,get:r=>r.per18.putting}];
let trendMetric='total';
document.getElementById('trendMetric').innerHTML=TREND.map(m=>`<option value="${m.k}">${m.label}</option>`).join("");
document.getElementById('trendMetric').onchange=e=>{trendMetric=e.target.value;renderTrend();};
function slope(ys){const n=ys.length;if(n<2)return 0;const mx=(n-1)/2,my=ys.reduce((a,b)=>a+b,0)/n;
  let nu=0,de=0;ys.forEach((y,i)=>{nu+=(i-mx)*(y-my);de+=(i-mx)**2;});return de?nu/de:0;}
function dir(ys,low){const s=slope(ys);if(Math.abs(s)<0.3)return{t:'→ flat',c:'flat'};
  return (low?-s:s)>0?{t:'↑ improving',c:'up'}:{t:'↓ slipping',c:'down'};}
function chart(pts,zero){
  if(pts.length<2)return '<div class="foot">need ≥2 rounds to show a trend</div>';
  const W=320,H=170,L=30,R=10,T=12,B=26;let ys=pts.map(p=>p.y);
  let mn=Math.min(...ys),mx=Math.max(...ys);if(zero){mn=Math.min(mn,0);mx=Math.max(mx,0);}
  if(mn===mx){mn-=1;mx+=1;}const pd=(mx-mn)*0.15||1;mn-=pd;mx+=pd;
  const X=i=>L+(W-L-R)*(i/(pts.length-1)),Y=v=>T+(H-T-B)*(1-(v-mn)/(mx-mn));
  let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">`;
  if(zero&&0>=mn&&0<=mx){const z=Y(0);s+=`<line x1="${L}" y1="${z}" x2="${W-R}" y2="${z}" stroke="#c4ccd4" stroke-dasharray="3"/>`;}
  s+=`<text x="2" y="${Y(mx)+3}" font-size="9" fill="#7a8794">${mx.toFixed(0)}</text>`;
  s+=`<text x="2" y="${Y(mn)+3}" font-size="9" fill="#7a8794">${mn.toFixed(0)}</text>`;
  s+=`<polyline points="${pts.map((p,i)=>X(i)+','+Y(p.y)).join(' ')}" fill="none" stroke="#15497a" stroke-width="2"/>`;
  pts.forEach((p,i)=>{s+=`<circle cx="${X(i)}" cy="${Y(p.y)}" r="3.5" fill="${p.clean?'#15497a':'#9aa6b2'}"/>`;
    if(pts.length<=8||i%2===0||i===pts.length-1)s+=`<text x="${X(i)}" y="${H-8}" font-size="8" fill="#7a8794" text-anchor="middle">${p.label}</text>`;});
  return s+'</svg>';
}
function renderTrend(){
  const m=TREND.find(x=>x.k===trendMetric);
  const pts=TS.filter(r=>m.clean?r.clean:(r.overRating18!=null))
    .map(r=>({label:r.date.slice(5).replace('-','/'),y:m.get(r),clean:r.clean}));
  const d=pts.length>=2?dir(pts.map(p=>p.y),m.low):{t:'',c:'flat'};
  document.getElementById('trendhead').innerHTML=`<b>${m.label}</b><span class="tpill ${d.c}">${d.t}</span>`;
  document.getElementById('trendchart').innerHTML=chart(pts,m.k!=='over');
  document.getElementById('trendfoot').textContent=`${pts.length} ${m.clean?'clean ':''}rounds`;
}

function setTab(name){
  [...document.getElementById('tabs').children].forEach(b=>b.classList.toggle('on',b.dataset.t===name));
  ['progress','trend','rounds','clubs','maps'].forEach(n=>document.getElementById('tab-'+n).classList.toggle('hide',n!==name));
  if(name==="trend")renderTrend();
  if(name==="rounds")renderRoundsList();
  if(name==="maps")showMap();}
document.getElementById('tabs').onclick=e=>{const t=e.target.closest('[data-t]');if(t)setTab(t.dataset.t);};
function gotoMap(ri,hn){
  initMap();mRound=ri;document.getElementById('mapRound').value=ri;
  const idx=mappable(DATA.rounds[ri]).findIndex(h=>h.n===hn);mHole=idx<0?0:idx;
  setTab('maps');}
document.getElementById('roundDetail').addEventListener('click',e=>{
  const b=e.target.closest('.maplink');if(b)gotoMap(detailRound,+b.dataset.h);});

renderProgress();renderRoundsList();renderClubs();
</script>
</body>
</html>
"""


def main() -> None:
    out = build()
    print(f"Wrote {out}  (open it, or host site/ on S3 + CloudFront)")


if __name__ == "__main__":
    main()
