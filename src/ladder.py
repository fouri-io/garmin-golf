"""Approach Ladder & Green Zone — how good is the approach game, by yardage.

Deterministic (no LLM). One row per approach in the window (any real stroke whose
distance-to-pin falls in the band — geometry, not Garmin's shot_type label), binned by
yardage and scored against the Green Zone:

    Green Zone = the approach finished on the green, OR inside the zone radius of the
                 pin, OR in the hole.

Geometric and pin-centred. This is NOT Garmin's green-in-regulation stat — that one is
unchanged everywhere it already appears and is reported separately (ADR #19).

Row-level facts come from `derived.shot_play` (threshold-free by design); every cut —
window, band, bin edges, zone radius, rings, leave classes, coverage floors — lives in
config/analysis.json -> approachLadder and is read once, here, then passed down as a
`cfg` dict. Nothing re-reads config inside a helper.

    python -m src.ladder

Output: data/processed/approach_ladder.{json,md}. The md is what the coach prompt
ingests; the json is inlined into the site and feeds insight candidates.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import approach_ladder as _ladder_cfg
from .constants import LEAVE_CLASS_LABELS, LEAVE_CLASSES, PUTTER_CLUB_TYPE_ID

OUT_JSON = Path("data/processed/approach_ladder.json")
OUT_MD = Path("data/processed/approach_ladder.md")

SCHEMA = 1
FLAT_BAND_PTS = 2         # |delta| at or below this reads as flat, not a real move


# --------------------------------------------------------------------------- pure fns
# Everything below is DB-free and unit-tested: the bin/zone/leave vocabulary the whole
# feature speaks, with the config values passed in rather than read.

def in_band(to_pin_yds: float | None, band: list) -> bool:
    """Is this stroke an approach? Inclusive at both ends of the band."""
    return to_pin_yds is not None and band[0] <= to_pin_yds <= band[1]


def display_bin(to_pin_yds: float | None, edges: list) -> str | None:
    """Coarse bin key ("100-125"). Half-open [lo, hi) per bin; the final bin is closed
    so an exact 170.0 is never dropped."""
    if to_pin_yds is None:
        return None
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        last = i == len(edges) - 2
        if lo <= to_pin_yds < hi or (last and to_pin_yds == hi):
            return f"{lo}-{hi}"
    return None


def detail_bin(to_pin_yds: float | None, width: int, band: list) -> str | None:
    """Fine bin key ("110-120") at the detail width, same closed-at-the-top rule."""
    if not in_band(to_pin_yds, band):
        return None
    lo = band[0] + int((to_pin_yds - band[0]) // width) * width
    lo = min(lo, band[1] - width)          # the closing edge belongs to the last bin
    return f"{lo}-{lo + width}"


def in_zone(end_lie: str | None, leave_yds: float | None, holed: bool,
            zone_radius_yds: float) -> bool | None:
    """The locked definition, verbatim: on the green, or inside the radius, or holed.
    None means unmeasurable (no leave, not green, not holed) — those count in coverage
    but never in the rate."""
    if end_lie == "Green" or holed:
        return True
    if leave_yds is None:
        return None
    return leave_yds <= zone_radius_yds


def in_ring(leave_yds: float | None, radius_yds: float) -> bool | None:
    """Rings are pin-centred and need a measured leave — a 'Green' end lie alone does
    not satisfy one (green centre is not the pin)."""
    return None if leave_yds is None else leave_yds <= radius_yds


def putter_next(next_club_type_id: int | None) -> bool | None:
    """Did he putt next? Keyed on CLUB, because Garmin marks shot_type='PUTT' only from
    the green — fringe putts read as chips. DIAGNOSTIC ONLY: never inside in_zone.
    None = the hole ended, or the next stroke's club is unattributed (club_type_id 0)."""
    if not next_club_type_id:
        return None
    return next_club_type_id == PUTTER_CLUB_TYPE_ID


def leave_class(end_lie: str | None, leave_yds: float | None, putter_next_flag: bool | None,
                edges: list, holed: bool = False) -> str | None:
    """Where the approach left him, in the vocabulary the payoff anchors price. A holed
    approach has nothing left to finish, so it classes as None and is counted apart."""
    if holed:
        return None
    if putter_next_flag and end_lie == "Green":
        return "greenPutted"
    if putter_next_flag:
        return "fringePutted"              # putter off the green: fringe/apron
    if end_lie == "Green":
        return "greenPutted"               # green, next club unattributed or a non-putt
    if leave_yds is None:
        return None
    if leave_yds <= edges[0]:
        return "chipped"
    return "pitch" if leave_yds <= edges[1] else "long"


def stat(hits: int, n: int) -> dict:
    """The coverage primitive. EVERY rate in this export goes through it, so a consumer
    physically cannot render a percentage without its n in hand."""
    return {"pct": round(100 * hits / n) if n else None, "n": n}


def window_label(days: int) -> str:
    if days == 30:
        return "last month"
    if days >= 60 and days % 30 == 0:
        return f"last {days // 30} mo"
    return f"last {days} days"


def scope_label(band: list, days: int) -> str:
    return f"{band[0]}–{band[1]}y · {window_label(days)}"


def scope_suffix(band: list, days: int, n: int) -> str:
    return f"{scope_label(band, days)} · n={n}"


# ---------------------------------------------------------------------------- dataset

_ROW_SQL = """
SELECT shot_id, round_id, round_date, hole_number, par, play_order,
       club_id, club_type_id, club_name, start_lie, end_lie,
       to_pin_yds, leave_yds, miss_range, miss_side,
       next_club_type_id, hole_strokes, hole_putts, strokes_to_finish, holed
FROM derived.shot_play
WHERE round_date >= ? AND round_date <= ? AND to_pin_yds IS NOT NULL
ORDER BY round_date, hole_number, play_order"""


def _club_name(name: str | None) -> str | None:
    """A real club name, or None when Garmin logged no sensor for the swing. Those
    shots still count in every bin total — only the per-club rows lose them."""
    if not name or name.lower().startswith("unknown"):
        return None
    return name


def _row(r: tuple, cfg: dict) -> dict:
    """One approach, with every config cut already applied to it."""
    (shot_id, round_id, round_date, hole, par, play_order, club_id, club_type_id,
     club_name, start_lie, end_lie, to_pin, leave, miss_range, miss_side,
     next_club_type_id, hole_strokes, hole_putts, stf, holed) = r
    holed = bool(holed)
    pn = putter_next(next_club_type_id)
    return {
        "shotId": shot_id, "roundId": round_id, "date": str(round_date), "hole": hole,
        "par": par, "playOrder": play_order, "club": _club_name(club_name),
        "clubTypeId": club_type_id, "startLie": start_lie, "endLie": end_lie,
        "toPin": to_pin, "leave": leave, "missRange": miss_range, "missSide": miss_side,
        "nextClubTypeId": next_club_type_id, "strokesToFinish": stf, "holed": holed,
        "displayBin": display_bin(to_pin, cfg["displayBinEdges"]),
        "detailBin": detail_bin(to_pin, cfg["detailBinWidthYds"], cfg["bandYds"]),
        "zone": in_zone(end_lie, leave, holed, cfg["zoneRadiusYds"]),
        "rings": {f"ring{int(r_)}": in_ring(leave, r_) for r_ in cfg["ringYds"]},
        "putterNext": pn,
        "leaveClass": leave_class(end_lie, leave, pn, cfg["leaveClassEdgesYds"], holed),
    }


def load_rows(con, cfg: dict, as_of: date, days: int | None = None) -> dict:
    """The windowed, band-filtered, artifact-excluded approach population.

    The band filter and the end-lie exclusion live here rather than in the view: the
    view stays threshold-free, and keeping `end_lie` on the row makes the drop
    auditable — excluded approaches are counted, not quietly missing."""
    days = cfg["windowDays"] if days is None else days
    start = as_of - timedelta(days=days)
    rows = con.execute(_ROW_SQL, [start, as_of]).fetchall()
    band = cfg["bandYds"]
    eligible = [_row(r, cfg) for r in rows if in_band(r[11], band)]
    excluded = [r for r in eligible if r["endLie"] in set(cfg["excludeEndLie"])]
    kept = [r for r in eligible if r["endLie"] not in set(cfg["excludeEndLie"])]
    return {"rows": kept, "eligible": len(eligible), "excluded": len(excluded),
            "from": start.isoformat(), "to": as_of.isoformat(), "days": days}


def _median(vals: list) -> float | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _rate(rows: list, pred) -> dict:
    """A rate over the rows where the predicate is measurable (None = unmeasurable and
    excluded from the denominator, never counted as a miss)."""
    vals = [pred(r) for r in rows]
    known = [v for v in vals if v is not None]
    return stat(sum(1 for v in known if v), len(known))


def _miss(rows: list) -> dict:
    """Short/long and left/right/straight shares for a slice, each over the rows that
    carry the reading."""
    rng = [r["missRange"] for r in rows if r["missRange"]]
    side = [r["missSide"] for r in rows if r["missSide"]]
    d = {"n": len(rows)}
    for key, vals, want in (("shortPct", rng, "short"), ("longPct", rng, "long"),
                            ("leftPct", side, "left"), ("rightPct", side, "right"),
                            ("straightPct", side, "straight")):
        d[key] = round(100 * sum(1 for v in vals if v == want) / len(vals)) if vals else None
    return d


def payoff_anchors(rows: list, cfg: dict) -> dict:
    """Average strokes to hole out after an approach, by where it left the ball.

    Strokes to finish is the authoritative hole score minus the stroke's ordinal, never
    a count of remaining shot rows — the shot layer under-records tap-ins and penalties,
    which would price every leave class too cheaply."""
    over_recorded = sum(1 for r in rows if r["strokesToFinish"] is not None
                        and r["strokesToFinish"] < 0)
    by_class: dict[str, list] = {k: [] for k in LEAVE_CLASSES}
    for r in rows:
        stf = r["strokesToFinish"]
        if r["leaveClass"] in by_class and stf is not None and stf >= 0:
            by_class[r["leaveClass"]].append(stf)
    classes = []
    for key in LEAVE_CLASSES:
        vals = by_class[key]
        classes.append({
            "key": key, "label": LEAVE_CLASS_LABELS[key],
            "strokes": round(sum(vals) / len(vals), 2) if vals else None,
            "n": len(vals), "provisional": len(vals) < cfg["minAnchorN"]})
    legend = "Miss the zone and it costs you: " + " · ".join(
        f"{c['label'].lower()} {c['strokes']:.2f} strokes to hole out"
        if c["key"] == LEAVE_CLASSES[0] else f"{c['label'].lower()} {c['strokes']:.2f}"
        for c in classes if c["strokes"] is not None)
    return {
        "basis": "average strokes to hole out after an approach in the band, by where it "
                 "left the ball; strokes counted from the authoritative scorecard, never "
                 "from shot rows",
        "classes": classes, "excludedOverRecorded": over_recorded, "legend": legend}


def _anchor_map(anchors: dict) -> dict:
    return {c["key"]: c["strokes"] for c in anchors["classes"] if c["strokes"] is not None}


def _payoff(rows: list, amap: dict, min_n: int) -> dict | None:
    """What an approach from this slice costs, on average, by pricing each leave."""
    vals = [amap[r["leaveClass"]] for r in rows if r["leaveClass"] in amap]
    if len(vals) < min_n:
        return None
    return {"strokes": round(sum(vals) / len(vals), 2), "n": len(vals)}


def _club_rows(rows: list, cfg: dict) -> tuple[list, dict]:
    """Per-club rows at or above the floor, plus the shots that did not make one —
    unattributed swings and thin clubs still count in the bin, they just cannot be
    rated on their own."""
    groups: dict[str, list] = {}
    for r in rows:
        if r["club"]:
            groups.setdefault(r["club"], []).append(r)
    out, below = [], len([r for r in rows if not r["club"]])
    for club, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < cfg["minClubRowN"]:
            below += len(rs)
            continue
        out.append({"club": club, "clubTypeId": rs[0]["clubTypeId"],
                    "zone": _rate(rs, lambda r: r["zone"]),
                    "medianLeaveYds": round(_median([r["leave"] for r in rs]), 1)
                    if _median([r["leave"] for r in rs]) is not None else None,
                    "miss": _miss(rs)})
    return out, {"shots": below, "minN": cfg["minClubRowN"]}


def _bin_doc(key: str, lo: float, hi: float, rows: list, cfg: dict, amap: dict,
             detail: list | None = None) -> dict:
    ring_keys = [f"ring{int(r_)}" for r_ in cfg["ringYds"]]
    clubs, below = _club_rows(rows, cfg)
    lies: dict[str, list] = {}
    for r in rows:
        lies.setdefault(r["startLie"] or "Unknown", []).append(r)
    doc = {
        "key": key, "label": f"{lo:g}–{hi:g}y", "loYds": lo, "hiYds": hi,
        "zone": _rate(rows, lambda r: r["zone"]),
        "medianLeaveYds": round(_median([r["leave"] for r in rows]), 1) if rows else None,
        "payoffStrokes": _payoff(rows, amap, cfg["minBinN"]),
        "provisional": len(rows) < cfg["minBinN"],
        "miss": _miss(rows),
        "fromLie": [{"lie": lie, "zone": _rate(rs, lambda r: r["zone"])}
                    for lie, rs in sorted(lies.items(), key=lambda kv: -len(kv[1]))],
        "clubs": clubs, "clubsBelowMin": below,
    }
    for rk in ring_keys:
        doc[rk] = _rate(rows, lambda r, rk=rk: r["rings"][rk])
    if detail is not None:
        doc["detail"] = detail
    return doc


def _detail_bins(rows: list, cfg: dict, amap: dict) -> list:
    """The 10-yard grid across the whole band. It is a BAND grid, not a per-display-bin
    one: a display edge like 125 falls mid-grid, so each detail bin is filed under the
    display bin its lower edge sits in and keeps its own (grid-aligned) rows."""
    width, (lo0, hi0) = cfg["detailBinWidthYds"], cfg["bandYds"]
    out, edge = [], lo0
    while edge < hi0:
        key = f"{edge:g}-{edge + width:g}"
        rs = [r for r in rows if r["detailBin"] == key]
        out.append(_bin_doc(key, edge, edge + width, rs, cfg, amap))
        edge += width
    return out


def _verdict(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if abs(delta) <= FLAT_BAND_PTS:
        return "flat"
    return "improving" if delta > 0 else "slipping"


def _coverage(con, cfg: dict, win: dict, rows: list) -> dict:
    n_rounds, holes, with_pin = con.execute("""
        SELECT count(DISTINCT round_id), count(*), count(*) FILTER (WHERE has_pin)
        FROM derived.hole_pin_coverage WHERE round_date >= ? AND round_date <= ?""",
        [win["from"], win["to"]]).fetchone()
    n = len(rows)
    return {
        "rounds": n_rounds, "holes": holes, "holesWithPin": with_pin,
        "holesWithoutPin": holes - with_pin, "pinCoverage": stat(with_pin, holes),
        "eligible": win["eligible"], "excludedTeeBoxArtifact": win["excluded"],
        "approaches": n,
        "leaveMeasured": stat(sum(1 for r in rows if r["leave"] is not None), n),
        "clubAttributed": stat(sum(1 for r in rows if r["club"]), n),
        "nextShotKnown": stat(sum(1 for r in rows if r["putterNext"] is not None), n),
        "note": "Holes without pin coordinates carry no shot data at all, so they "
                "contribute no approaches — they are counted here so the shrunken "
                "denominator stays visible. Approaches recorded as finishing on a tee "
                "box are next-tee GPS artifacts (shot_flags does not catch them) and are "
                "excluded; the count is shown so the drop is visible.",
    }


def candidate_findings(doc: dict, cfg: dict) -> list:
    """Bin-level findings offered to the insight ranker. Candidates, never a standing
    list — insights.py scores them against everything else and only the winners show."""
    out, band_zone = [], (doc["headline"]["zone"]["pct"] or 0)
    bins = doc["bins"]
    detail = [d for b in bins for d in b["detail"]]

    # 1. Reach swing — a club pushed past its stock max leaks short AND right together.
    for d in detail:
        for c in d["clubs"]:
            m = c["miss"]
            if (m["n"] >= cfg["minClubRowN"] and (m["shortPct"] or 0) >= 65
                    and (m["rightPct"] or 0) >= 55):
                out.append({
                    "cat": "Approach ladder", "key": "reach-swing", "binKey": d["key"],
                    "club": c["club"], "n": m["n"],
                    "magnitude": round((m["shortPct"] + m["rightPct"] - 120) / 60, 3),
                    "weight": 1.15,
                    "text": f"{c['club']} from {d['label']} is a reach swing: of "
                            f"{m['n']} shots, {m['shortPct']}% finish short and "
                            f"{m['rightPct']}% finish right, and only "
                            f"{c['zone']['pct']}% reach the Green Zone. One more club "
                            f"is the whole fix."})

    # 2. The cliff — where the ladder stops holding, at display resolution.
    rated = [b for b in bins if not b["provisional"] and b["zone"]["pct"] is not None]
    for lower, upper in zip(rated, rated[1:]):
        drop = lower["zone"]["pct"] - upper["zone"]["pct"]
        if drop >= 12:
            out.append({
                "cat": "Approach ladder", "key": "cliff", "binKey": upper["key"],
                "club": None, "n": upper["zone"]["n"], "magnitude": round(drop / 25, 3),
                "weight": 1.2,
                "text": f"Your approach game falls off a cliff at {upper['loYds']:g} "
                        f"yards: {lower['label']} reaches the Green Zone "
                        f"{lower['zone']['pct']}% of the time (n={lower['zone']['n']}) "
                        f"but {upper['label']} only {upper['zone']['pct']}% "
                        f"(n={upper['zone']['n']}), leaving a median "
                        f"{upper['medianLeaveYds']:.0f} yards. Lay up to the range that "
                        f"still works."})
            break

    # 3. Best window — the yardage worth manufacturing, when it clearly beats the band.
    rated_d = [d for d in detail if not d["provisional"] and d["zone"]["pct"] is not None]
    if rated_d:
        best = max(rated_d, key=lambda d: d["zone"]["pct"])
        edge = best["zone"]["pct"] - band_zone
        if edge >= 12:
            out.append({
                "cat": "Approach ladder", "key": "best-window", "binKey": best["key"],
                "club": None, "n": best["zone"]["n"], "magnitude": round(edge / 25, 3),
                "weight": 1.0,
                "text": f"{best['label']} is your best window: {best['zone']['pct']}% of "
                        f"{best['zone']['n']} approaches reach the Green Zone, against "
                        f"{band_zone}% across the whole {doc['band']['label']} band. "
                        f"Worth leaving yourself that number off the tee."})
    return out


def build_doc(con, cfg: dict, as_of: date) -> dict:
    win = load_rows(con, cfg, as_of)
    rows = win["rows"]
    prev = load_rows(con, cfg, as_of - timedelta(days=cfg["windowDays"]))
    band, days = cfg["bandYds"], cfg["windowDays"]
    anchors = payoff_anchors(rows, cfg)
    amap = _anchor_map(anchors)
    edges = cfg["displayBinEdges"]

    detail = _detail_bins(rows, cfg, amap)
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        key = f"{lo:g}-{hi:g}"
        rs = [r for r in rows if r["displayBin"] == key]
        bins.append(_bin_doc(key, lo, hi, rs, cfg, amap,
                             detail=[d for d in detail if lo <= d["loYds"] < hi]))

    zone = _rate(rows, lambda r: r["zone"])
    prev_zone = _rate(prev["rows"], lambda r: r["zone"])
    delta = (zone["pct"] - prev_zone["pct"]
             if zone["pct"] is not None and prev_zone["pct"] is not None else None)
    ring0 = f"ring{int(cfg['ringYds'][0])}"
    headline = {
        "key": "greenZonePct", "label": "Green Zone %", "scope": scope_label(band, days),
        "zone": zone, ring0: _rate(rows, lambda r: r["rings"][ring0]),
        "putterNext": {**_rate(rows, lambda r: r["putterNext"]), "diagnostic": True},
        "prev": {**prev_zone, "label": f"previous {window_label(days).replace('last ', '')}"},
        "deltaPts": delta, "verdict": _verdict(delta),
        "payoffStrokes": _payoff(rows, amap, cfg["minBinN"]),
    }

    doc = {
        "schema": SCHEMA,
        "generatedFor": as_of.isoformat(),
        "window": {"days": days, "from": win["from"], "to": win["to"],
                   "label": window_label(days)},
        "band": {"minYds": band[0], "maxYds": band[1], "label": f"{band[0]}–{band[1]}y"},
        "scope": scope_suffix(band, days, len(rows)),
        "headline": headline,
        "bins": bins,
        "payoffAnchors": anchors,
        "coverage": _coverage(con, cfg, win, rows),
        "config": cfg,
        "note": "Green Zone means the approach finished on the green, or inside "
                f"{cfg['zoneRadiusYds']:g} yards of the pin, or in the hole — a "
                "geometric, pin-centred measure. It is not Garmin's green-in-regulation "
                "stat, which is unchanged and reported separately. Green Zone % is a "
                "RATE, so it uses every round in the window, 9- and 18-hole alike; only "
                "scoring-level metrics are restricted to 18-hole regulation rounds.",
    }
    doc["findings"] = candidate_findings(doc, cfg)
    return doc


# --------------------------------------------------------------------------- renders

def render_markdown(doc: dict) -> str:
    """The coach-facing render: the season strip with an n on every row, the payoff
    line, the coverage line. Kept short — it shares a prompt with everything else."""
    h, cov = doc["headline"], doc["coverage"]
    d = h["deltaPts"]
    trend = ("no comparable previous window" if d is None else
             f"{d:+d} pts vs the {h['prev']['label']} ({h['prev']['pct']}%, "
             f"n={h['prev']['n']}) — {h['verdict']}")
    lines = [
        f"Green Zone % — {doc['scope']}: {h['zone']['pct']}% ({trend}).",
        "Green Zone = finished on the green, inside "
        f"{doc['config']['zoneRadiusYds']:g} yards of the pin, or holed. NOT Garmin's "
        "green-in-regulation stat.",
        "",
        "| Bin | Green Zone % | n | median leave |",
        "|---|---|---|---|",
    ]
    for b in doc["bins"]:
        pct = "too few to rate" if b["provisional"] or b["zone"]["pct"] is None \
            else f"{b['zone']['pct']}%"
        leave = f"{b['medianLeaveYds']:.1f}y" if b["medianLeaveYds"] is not None else "—"
        lines.append(f"| {b['label']} | {pct} | {b['zone']['n']} | {leave} |")
    lines += ["", doc["payoffAnchors"]["legend"] + ".",
              f"Coverage: {cov['approaches']} approaches over {cov['rounds']} rounds; "
              f"{cov['excludedTeeBoxArtifact']} dropped as next-tee GPS artifacts; "
              f"club named on {cov['clubAttributed']['pct']}%; pin coordinates on "
              f"{cov['pinCoverage']['pct']}% of {cov['holes']} holes."]
    return "\n".join(lines) + "\n"


def round_samples(con, round_id: int, cfg: dict | None = None) -> dict:
    """THIS round's approaches in each display bin — the per-round companion to the
    season strip, so a coach read anchors to real shots or says the bin went untested.
    No window filter: the round is the scope."""
    cfg = cfg or _ladder_cfg()
    rows = con.execute(_ROW_SQL.replace("WHERE round_date >= ? AND round_date <= ?",
                                        "WHERE round_id = ?"), [round_id]).fetchall()
    band, edges = cfg["bandYds"], cfg["displayBinEdges"]
    kept = [_row(r, cfg) for r in rows
            if in_band(r[11], band) and r[10] not in set(cfg["excludeEndLie"])]
    bins = {f"{lo:g}-{hi:g}": [] for lo, hi in zip(edges, edges[1:])}
    for r in kept:
        if r["displayBin"] in bins:
            bins[r["displayBin"]].append({
                "hole": r["hole"], "fromYds": round(r["toPin"]), "lie": r["startLie"],
                "leaveYds": round(r["leave"], 1) if r["leave"] is not None else None,
                "end": r["endLie"], "zone": r["zone"], "missRange": r["missRange"],
                "missSide": r["missSide"]})
    return {"bins": bins, "zone": _rate(kept, lambda r: r["zone"])}


def render_round_samples(samples: dict) -> str:
    lines = ["THIS ROUND'S APPROACHES BY BIN (the strip above is his SEASON profile — "
             "anchor your read to these shots, or say the bin went untested this round):"]
    for key, shots in samples["bins"].items():
        label = key.replace("-", "–") + "y"
        if not shots:
            lines.append(f"  {label}: none this round — bin untested")
            continue
        parts = []
        for s in shots:
            miss = ", ".join(m for m in (s["missRange"], s["missSide"]) if m
                             and m != "straight")
            verdict = "ZONE" if s["zone"] else f"missed{' — ' + miss if miss else ''}"
            parts.append(f"H{s['hole']} {s['fromYds']:.0f}y ({(s['lie'] or '?').lower()}) "
                         f"-> left {s['leaveYds']:.0f}y, {(s['end'] or '?').lower()} "
                         f"— {verdict}")
        lines.append(f"  {label}: " + "; ".join(parts))
    z = samples["zone"]
    lines.append(f"  Round Green Zone: {z['pct']}% of {z['n']} approaches in the band"
                 if z["n"] else "  Round Green Zone: no approaches in the band")
    return "\n".join(lines)


def build(write: bool = True, as_of: date | None = None, cfg: dict | None = None,
          con=None) -> dict:
    """Build the ladder document. `as_of` and `cfg` are injectable because the window is
    date-relative: tests pin a date so the fixture round stays visible."""
    from .db import connect
    full = dict(_ladder_cfg())
    full.update(cfg or {})
    doc = build_doc(con or connect(), full, as_of or date.today())
    if write:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(doc, indent=2))
        OUT_MD.write_text(render_markdown(doc))
        print(f"  approach ladder -> {OUT_MD}")
    return doc


def main() -> None:
    doc = build()
    print(render_markdown(doc))


if __name__ == "__main__":
    main()
