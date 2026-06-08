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
    md_path = path.with_suffix(".md")
    return {
        "stem": path.stem, "md": md_path.read_text() if md_path.exists() else "",
        "date": rnd["date"][:10], "course": course["name"],
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


def _coach_reports() -> dict:
    """AI coach round reports (markdown), newest first."""
    cdir = PROCESSED / "coach"
    reports = []
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            if f.name in ("context.md", "latest.md"):
                continue
            reports.append({"stem": f.stem, "date": f.stem[:10].replace("_", "-"),
                            "text": f.read_text()})
    reports.sort(key=lambda r: r["stem"], reverse=True)
    return {"reports": reports}


def build() -> Path:
    progress = json.loads((PROCESSED / "progress.json").read_text())
    clubs = json.loads((PROCESSED / "club_stats.json").read_text())
    rounds = sorted((_compact_round(Path(p)) for p in glob.glob(str(ROUNDS_DIR / "*.json"))),
                    key=lambda r: r["date"], reverse=True)
    data = {"progress": progress, "clubs": clubs, "rounds": rounds, "coach": _coach_reports()}
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
<title>The Turn</title>
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
  .leakcall{background:#fbeceb;border-left:4px solid var(--bad);border-radius:10px;
    padding:12px 14px;margin-bottom:12px}
  .leakcall b{color:var(--bad)}
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
  .exprow{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
  .expbtn{border:0;background:#eaf1f8;color:var(--accent);border-radius:10px;padding:8px 14px;
    font-weight:600;font-size:13px;cursor:pointer}
  .exprow .hint{font-size:11px;color:var(--muted)}
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
  /* coach */
  .coachhdr{display:flex;align-items:center;gap:8px;margin-bottom:8px}
  .coachhdr .ai{background:linear-gradient(135deg,#15497a,#1d6fb8);color:#fff;border-radius:8px;
    padding:3px 8px;font-size:11px;font-weight:700}
  #coachReport h4{font-size:14px;margin:13px 0 4px;color:var(--accent)}
  #coachReport h4:first-child{margin-top:0}
  #coachReport p{margin:0 0 9px;font-size:14px;line-height:1.5}
  #coachReport ul{margin:0 0 9px;padding-left:18px}#coachReport li{margin:3px 0;font-size:14px}
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
  .tabbar .t.on{color:var(--accent)}.tabbar .t svg{width:22px;height:22px;display:block;margin:0 auto 2px}
  .ic{fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
  .top{justify-content:flex-start}
  .top h1{display:flex;align-items:center;gap:6px}.top h1 svg{width:19px;height:19px}
  .tagline{font-size:12px;color:var(--muted);font-style:italic;margin:2px 0 0}
  .refresh svg{width:18px;height:18px}
  .maplink svg{width:13px;height:13px;vertical-align:-2px;margin-right:3px}
  .hide{display:none}
</style>
</head>
<body>
<div class="app">
  <div class="top">
    <div><h1><svg class="ic" viewBox="0 0 24 24"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>The Turn</h1>
      <div class="tagline">round by round</div>
      <div class="date" id="date"></div></div></div>

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
    <div class="leakcall">#1 leak: <b id="leak">—</b><br>
      <span class="foot">your highest-return practice target</span></div>
    <div class="card"><h2>Strokes Gained<span id="sgtot" style="float:right;text-transform:none;font-weight:400;letter-spacing:0"></span></h2>
      <div class="ctl" style="margin:0 0 6px"><span class="lab">Compare vs</span>
        <div class="seg" id="base"></div></div>
      <div class="bars" id="bars"><div class="zero"></div></div>
      <div class="foot" id="bf"></div></div>
  </div>

  <div id="tab-trend" class="hide">
    <div class="ctl"><span class="lab">Metric over time</span>
      <select class="rsel" id="trendMetric"></select></div>
    <div class="card"><div id="trendhead"></div><div id="trendchart"></div>
      <div id="trendpick" style="font-size:13px;text-align:center;min-height:18px;color:var(--accent)"></div>
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

  <div id="tab-coach" class="hide">
    <div class="coachhdr"><span class="ai">AI COACH</span>
      <select class="rsel" id="coachRound" style="margin:0;flex:1"></select></div>
    <div class="card" id="coachReport"></div>
    <div class="foot" style="padding:0 4px">Generated at update time from your profile +
      this round + your trend. Honest about which numbers are GPS-approximate.</div>
  </div>

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
  <button class="t on" data-t="progress"><svg class="ic" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>Overview</button>
  <button class="t" data-t="trend"><svg class="ic" viewBox="0 0 24 24"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>Trend</button>
  <button class="t" data-t="rounds"><svg class="ic" viewBox="0 0 24 24"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>Rounds</button>
  <button class="t" data-t="clubs"><svg class="ic" viewBox="0 0 24 24"><path d="M2 20h.01"/><path d="M7 20v-4"/><path d="M12 20v-8"/><path d="M17 20V8"/><path d="M22 4v16"/></svg>Clubs</button>
  <button class="t" data-t="maps"><svg class="ic" viewBox="0 0 24 24"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/></svg>Maps</button>
  <button class="t" data-t="coach"><svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>Coach</button>
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
  const st=document.getElementById('sgtot');
  if(vals.some(v=>v===null)){st.textContent='';}
  else{const tot=vals.reduce((a,b)=>a+b,0);
    st.innerHTML=`total <b class="${tot>=0?'pos':'neg'}">${tot>=0?'+':''}${tot.toFixed(1)}</b> /18`;}
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
    const maplink=h.shots.some(s=>s.start&&s.end)?`<button class="maplink" data-h="${h.n}"><svg class="ic" viewBox="0 0 24 24"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/></svg>map</button>`:'';
    return `<div class="hole"><div class="hrow">
        <span class="sbox ${box(h.toPar)}">${h.strokes}</span>
        <b>H${h.n}</b> <span class="mini">par ${h.par}</span><span class="gap"></span>
        <span class="mini">${fw} ${gir} ${h.putts}p ${h.pen?'· pen '+h.pen:''}</span>${maplink}</div>
      <div class="shots">${shots||'<span class="mut">no shots recorded</span>'}</div></div>`;
  }).join("");
  el.innerHTML=`<button class="back" id="back">← All rounds</button>
    <div class="exprow"><button class="expbtn exp-copy">Copy for LLM</button>
      ${navigator.share?'<button class="expbtn exp-share">Share</button>':''}
      <span class="hint">round + coach + your trend</span></div>
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
  if(h.pin){L.marker(h.pin).bindPopup('Pin').addTo(mlayer);pts.push(h.pin);}
  if(pts.length)lmap.fitBounds(pts,{padding:[45,45]});
}
function showMap(){initMap();setTimeout(()=>{lmap.invalidateSize();drawHole();},30);}

/* ---- trend (SVG line charts over rounds) ---- */
const TS=P.timeSeries;
const sumCats=r=>CATS.reduce((a,[k])=>a+(r.per18[k]||0),0);
const TREND=[
  {k:'over',label:'Score vs rating (lower = better)',clean:false,low:true,get:r=>r.overRating18},
  {k:'total',label:'SG total per 18 (toward 0 = better)',clean:true,low:false,get:sumCats},
  {k:'offTee',label:'SG Off-the-Tee',clean:true,low:false,get:r=>r.per18.offTee},
  {k:'longApproach',label:'SG Long approach',clean:true,low:false,get:r=>r.per18.longApproach},
  {k:'midApproach',label:'SG Mid approach',clean:true,low:false,get:r=>r.per18.midApproach},
  {k:'inside50',label:'SG Inside 50',clean:true,low:false,get:r=>r.per18.inside50},
  {k:'putting',label:'SG Putting',clean:true,low:false,get:r=>r.per18.putting}];
let trendMetric='over',lastPts=[];
document.getElementById('trendMetric').innerHTML=TREND.map(m=>`<option value="${m.k}">${m.label}</option>`).join("");
document.getElementById('trendMetric').onchange=e=>{trendMetric=e.target.value;renderTrend();};
function slope(ys){const n=ys.length;if(n<2)return 0;const mx=(n-1)/2,my=ys.reduce((a,b)=>a+b,0)/n;
  let nu=0,de=0;ys.forEach((y,i)=>{nu+=(i-mx)*(y-my);de+=(i-mx)**2;});return de?nu/de:0;}
function dir(ys,low){const s=slope(ys);if(Math.abs(s)<0.3)return{t:'→ flat',c:'flat'};
  return (low?-s:s)>0?{t:'↑ improving',c:'up'}:{t:'↓ slipping',c:'down'};}
function chart(pts,zero){
  if(pts.length<2)return '<div class="foot">need ≥2 rounds to show a trend</div>';
  const W=340,H=205,L=34,R=14,T=22,B=30;let ys=pts.map(p=>p.y);
  let mn=Math.min(...ys),mx=Math.max(...ys);if(zero){mn=Math.min(mn,0);mx=Math.max(mx,0);}
  if(mn===mx){mn-=1;mx+=1;}const pd=(mx-mn)*0.2||1;mn-=pd;mx+=pd;
  const X=i=>L+(W-L-R)*(i/(pts.length-1)),Y=v=>T+(H-T-B)*(1-(v-mn)/(mx-mn));
  let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">`;
  // y gridlines + tick labels (top, mid, bottom)
  [mx,(mx+mn)/2,mn].forEach(t=>{const y=Y(t);
    s+=`<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#eef1f4"/>`;
    s+=`<text x="${L-4}" y="${y+3}" font-size="9" fill="#7a8794" text-anchor="end">${t>0?'+':''}${t.toFixed(0)}</text>`;});
  if(zero&&0>mn&&0<mx){const z=Y(0);s+=`<line x1="${L}" y1="${z}" x2="${W-R}" y2="${z}" stroke="#aab3bd" stroke-dasharray="3"/>`;}
  s+=`<polyline points="${pts.map((p,i)=>X(i)+','+Y(p.y)).join(' ')}" fill="none" stroke="#15497a" stroke-width="2"/>`;
  pts.forEach((p,i)=>{const x=X(i),y=Y(p.y);
    s+=`<circle cx="${x}" cy="${y}" r="4.5" fill="${p.clean?'#15497a':'#9aa6b2'}" data-i="${i}" style="cursor:pointer"/>`;
    s+=`<text x="${x}" y="${y-9}" font-size="9" font-weight="700" fill="#1c2530" text-anchor="middle">${p.y>0?'+':''}${p.y.toFixed(1)}</text>`;
    if(pts.length<=8||i%2===0||i===pts.length-1)s+=`<text x="${x}" y="${H-9}" font-size="8" fill="#7a8794" text-anchor="middle">${p.label}</text>`;});
  return s+'</svg>';
}
function renderTrend(){
  const m=TREND.find(x=>x.k===trendMetric);
  lastPts=TS.filter(r=>m.clean?r.clean:(r.overRating18!=null))
    .map(r=>({label:r.date.slice(5).replace('-','/'),date:r.date,y:m.get(r),clean:r.clean}));
  const d=lastPts.length>=2?dir(lastPts.map(p=>p.y),m.low):{t:'',c:'flat'};
  document.getElementById('trendhead').innerHTML=`<b>${m.label}</b><span class="tpill ${d.c}">${d.t}</span>`;
  document.getElementById('trendchart').innerHTML=chart(lastPts,m.k!=='over');
  document.getElementById('trendfoot').textContent=`${lastPts.length} ${m.clean?'clean ':''}rounds · tap a point for its date + value`;
  document.getElementById('trendpick').textContent='';
}
document.getElementById('trendchart').addEventListener('click',e=>{
  if(e.target.tagName!=='circle')return;const p=lastPts[+e.target.dataset.i];if(!p)return;
  document.getElementById('trendpick').innerHTML=`<b>${p.date}</b> — ${p.y>0?'+':''}${p.y.toFixed(1)}${p.clean?'':' <span class="mut">(over-recorded)</span>'}`;});

/* ---- coach (tiny markdown renderer) ---- */
function md(t){
  if(!t)return '';
  const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  const inline=s=>esc(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>');
  let out='',inList=false;
  t.split('\n').forEach(line=>{line=line.trim();let m;
    if(!line){if(inList){out+='</ul>';inList=false;}return;}
    if(m=line.match(/^#{1,4}\s+(.*)/)){if(inList){out+='</ul>';inList=false;}out+=`<h4>${inline(m[1])}</h4>`;}
    else if(m=line.match(/^[-*]\s+(.*)/)){if(!inList){out+='<ul>';inList=true;}out+=`<li>${inline(m[1])}</li>`;}
    else{if(inList){out+='</ul>';inList=false;}out+=`<p>${inline(line)}</p>`;}});
  if(inList)out+='</ul>';return out;
}
function renderCoach(){
  const reps=(DATA.coach&&DATA.coach.reports)||[],sel=document.getElementById('coachRound');
  if(!reps.length){sel.style.display='none';
    document.getElementById('coachReport').innerHTML=
      '<div class="foot">No coach reports yet. Set <code>ANTHROPIC_API_KEY</code> in .env, then run <code>python -m src.update &lt;id&gt; --coach</code> (or just pull a round).</div>';
    return;}
  sel.style.display='';
  if(!sel.dataset.init){sel.innerHTML=reps.map((r,i)=>`<option value="${i}">${r.date} round</option>`).join("");
    sel.dataset.init=1;sel.onchange=e=>{document.getElementById('coachReport').innerHTML=md(reps[+e.target.value].text);};}
  document.getElementById('coachReport').innerHTML=md(reps[0].text);
}

function setTab(name){
  [...document.getElementById('tabs').children].forEach(b=>b.classList.toggle('on',b.dataset.t===name));
  ['progress','trend','rounds','clubs','maps','coach'].forEach(n=>document.getElementById('tab-'+n).classList.toggle('hide',n!==name));
  if(name==="trend")renderTrend();
  if(name==="rounds")renderRoundsList();
  if(name==="maps")showMap();
  if(name==="coach")renderCoach();}
document.getElementById('tabs').onclick=e=>{const t=e.target.closest('[data-t]');if(t)setTab(t.dataset.t);};
function gotoMap(ri,hn){
  initMap();mRound=ri;document.getElementById('mapRound').value=ri;
  const idx=mappable(DATA.rounds[ri]).findIndex(h=>h.n===hn);mHole=idx<0?0:idx;
  setTab('maps');}
function buildPack(r){
  const L=[`# ${r.course} — ${r.date}`,'_exported from The Turn for LLM coaching_','',
    '## Round','',r.md||'(round detail unavailable)'];
  const cr=(DATA.coach.reports||[]).find(x=>x.stem===r.stem);
  L.push('','## AI coach report','',cr?cr.text:'_(no coach report for this round yet)_');
  L.push('','## Current form & trend (per 18, vs scratch — toward 0 is better)','');
  const sc=P.scoring,l5=SG.last5,all=SG.allTime,au=AU.last5;
  L.push(`Scoring level: +${sc.averageOverRating18}/18 over course rating `+
    `(potential +${sc.potentialOverRating18} ≈ handicap ${sc.garminHandicap}; break-90 ≈ +${sc.break90OverRating}). Lower over-rating = better.`);
  if(l5&&all){
    L.push('','Strokes Gained by bucket — Last 5 (current form) vs all-time:');
    CATS.forEach(([k])=>L.push(`- ${FULL[k]}: ${l5.byCategory[k].toFixed(1)} (all-time ${all.byCategory[k].toFixed(1)})`));
    L.push(`- SG 0–100 (leverage, 100yd & in, no putts): ${l5.sg0to100.toFixed(1)} (all-time ${all.sg0to100.toFixed(1)})`);
  }
  if(au)L.push('',`Authoritative (last 5): penalties ${au.penalties18}/18 · doubles+ ${au.doubles18}/18 · putts ${au.putts18.toFixed(0)}/18 · 3-putts ${au.threePutts18}/18.`);
  L.push('','_Data note: putting & inside-50 (short-game) SG are GPS-approximate (directional); off-the-tee & full-approach are reliable; trust the bucket ranking over the absolute total. Putt counts/penalties/score are authoritative._');
  return L.join('\n');
}
function copyText(t){
  if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(t);
  return new Promise((res,rej)=>{const ta=document.createElement('textarea');ta.value=t;
    ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');res();}catch(err){rej(err);}document.body.removeChild(ta);});
}
function copyPack(r,btn){copyText(buildPack(r)).then(()=>{const o=btn.textContent;btn.textContent='Copied ✓';
  setTimeout(()=>btn.textContent=o,1600);}).catch(()=>{btn.textContent='Copy failed';});}
function sharePack(r){const t=buildPack(r);
  if(navigator.share)navigator.share({title:`${r.course} ${r.date}`,text:t}).catch(()=>{});
  else copyText(t);}
document.getElementById('roundDetail').addEventListener('click',e=>{
  const b=e.target.closest('.maplink');if(b){gotoMap(detailRound,+b.dataset.h);return;}
  const c=e.target.closest('.exp-copy');if(c){copyPack(DATA.rounds[detailRound],c);return;}
  const s=e.target.closest('.exp-share');if(s){sharePack(DATA.rounds[detailRound]);return;}});

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
