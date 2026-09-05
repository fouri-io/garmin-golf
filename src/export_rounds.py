"""DB -> round documents: data/processed/rounds/<stem>.{json,md}, SCHEMA_VERSION 2.

The round document is an EXPORT of the DuckDB spine now, not a source: a faithful
superset of the Garmin facts (ADR #2's contract survives) plus everything derived,
regenerated whenever the underlying round changes. Schema v2 additions over the
legacy parser's v1: per-shot `shotId` (Garmin's stable id), per-shot `confidence`
(authoritative|inferred|approximate|anomalous), per-shot `annotation` where a
confirmed tag exists, and a round-level `annotations` block (narrative + tags).

Usage:
    python -m src.export_rounds            # export every round in the analysis window
    python -m src.export_rounds <id>       # one round
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import analysis_start_date

OUT_DIR = Path("data/processed/rounds")
ANN_DIR = Path("data/annotations")

SCHEMA_VERSION = 2

SCORE_NAMES = {-3: "Albatross", -2: "Eagle", -1: "Birdie", 0: "Par", 1: "Bogey",
               2: "Double Bogey", 3: "Triple Bogey"}

_ROUND_COLS = [
    "round_id", "round_date", "start_time", "end_time", "score_type", "round_type",
    "holes_completed", "tee_box", "tee_rating", "tee_slope", "player_handicap",
    "handicapped_strokes", "sensor_on_putter", "distance_walked_m", "steps_taken",
    "course_global_id", "course_snapshot_id", "course_name", "course_city",
    "course_state", "course_country", "course_street", "course_zip", "course_lat",
    "course_lon", "round_par", "front_nine_par", "back_nine_par", "hole_pars",
    "total_strokes", "total_putts", "total_penalties", "longest_shot_m",
    "garmin_stats", "garmin_ratings",
]


def _score_name(to_par: int) -> str:
    return SCORE_NAMES.get(to_par, f"+{to_par}" if to_par > 0 else str(to_par))


def _iso(epoch_ms: int | None, offset_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    tz = timezone(timedelta(milliseconds=offset_ms or 0))
    return datetime.fromtimestamp(epoch_ms / 1000, tz).isoformat()


def _result_category(shot: dict) -> str | None:
    """A simple, LLM-friendly outcome tag: putt / green / bunker / off-map / short-right…"""
    if shot["type"] == "PUTT" or shot["from"] == "Green":
        return "putt"
    to = shot["to"]
    if to == "Green":
        return "green"
    if to == "Bunker":
        return "bunker"
    if to == "Unknown":
        return "off-map"
    miss = shot.get("miss")
    if not miss or miss["range"] is None:
        return None
    if miss["side"] in ("left", "right"):
        return f"{miss['range']}-{miss['side']}"
    return miss["range"]


def _annotations(con, rid: int, stem: str) -> tuple[dict | None, dict[int, dict]]:
    """(round-level annotations block, confirmed tags by shot_id)."""
    narrative = con.execute(
        "SELECT narrative FROM annot.round_narrative WHERE round_id = ?", [rid]).fetchone()
    tag_rows = con.execute("""
        SELECT shot_id, hole_number, intent, lie_quality, evaluation,
               exclude_from_stock, match_status, note
        FROM annot.shot_context WHERE round_id = ?""", [rid]).fetchall()
    hole_rows = con.execute("""
        SELECT hole_number, post_tee_state, double_class, preventable_escalation, note
        FROM annot.hole_context WHERE round_id = ?""", [rid]).fetchall()
    if not narrative and not tag_rows and not hole_rows:
        return None, {}
    by_shot = {}
    shots, unmatched = [], []
    for sid, hole, intent, lie_q, ev, excl, status, note in tag_rows:
        entry = {"shotId": sid, "hole": hole, "intent": intent, "lieQuality": lie_q,
                 "evaluation": ev, "excludeFromStock": excl, "note": note}
        if status == "confirmed" and sid is not None:
            shots.append(entry)
            by_shot[sid] = {"intent": intent, "evaluation": ev, "note": note,
                            "excludeFromStock": excl}
        else:
            unmatched.append({"hole": hole, "text": note, "intent": intent})
    block = {
        "narrative": narrative[0] if narrative else None,
        "shots": shots,
        "holes": [{"hole": h, "postTeeState": st, "doubleClass": dc,
                   "preventableEscalation": pe, "note": n}
                  for h, st, dc, pe, n in hole_rows],
        "unmatched": unmatched,
    }
    return block, by_shot


def build_round_document(con, rid: int) -> dict:
    r = dict(zip(_ROUND_COLS, con.execute(
        f"SELECT {', '.join(_ROUND_COLS)} FROM canon.round WHERE round_id = ?",
        [rid]).fetchone()))
    pars = [int(c) for c in (r["hole_pars"] or "")]
    gstats = json.loads(r["garmin_stats"]) if r["garmin_stats"] else None
    gratings = json.loads(r["garmin_ratings"]) if r["garmin_ratings"] else None

    hole_rows = con.execute("""
        SELECT h.hole_number, h.par, h.stroke_index, h.strokes, h.putts, h.penalties,
               h.fairway_outcome, h.handicap_score, h.pin_lat, h.pin_lon,
               hf.gir, hf.scramble_opportunity, hf.scramble_save, hf.first_putt_ft,
               hr.shots_recorded, hr.phantom_shots
        FROM canon.hole h
        JOIN derived.hole_facts hf
          ON hf.round_id = h.round_id AND hf.hole_number = h.hole_number
        JOIN derived.hole_recon hr
          ON hr.round_id = h.round_id AND hr.hole_number = h.hole_number
        WHERE h.round_id = ? ORDER BY h.hole_number""", [rid]).fetchall()

    shot_rows = con.execute("""
        SELECT s.hole_number, s.shot_order, s.shot_id,
               coalesce(c.name, ct.name, 'unknown') AS club,
               s.club_type_id, s.club_id, coalesce(c.retired, FALSE) AS retired,
               s.shot_type, s.auto_shot_type, s.shot_source, s.meters,
               s.start_lat, s.start_lon, s.start_lie, s.start_lie_source,
               s.end_lat, s.end_lon, s.end_lie, s.end_lie_source,
               s.shot_time_ms, s.shot_tz_offset_ms, s.exclude_from_stats,
               g.yards, g.to_pin_before_yds, g.remaining_yds,
               g.miss_range, g.miss_side, g.lateral_yds,
               f.phantom, f.phantom_reason, f.confidence,
               sg.sg_category, sg.strokes_gained
        FROM canon.shot s
        LEFT JOIN canon.club c ON c.club_id = s.club_id
        LEFT JOIN canon.club_type ct ON ct.club_type_id = s.club_type_id
        LEFT JOIN derived.shot_geom g ON g.shot_id = s.shot_id
        JOIN derived.shot_flags f ON f.shot_id = s.shot_id
        LEFT JOIN derived.shot_sg sg ON sg.shot_id = s.shot_id
        WHERE s.round_id = ? ORDER BY s.hole_number, s.shot_order""", [rid]).fetchall()

    date_stem = str(r["round_date"]).replace("-", "_")
    ann_block, ann_by_shot = _annotations(con, rid, f"{date_stem}_{rid}")

    shots_by_hole: dict[int, list[dict]] = {}
    for (hole, order, sid, club, club_type, club_id, retired, stype, auto, source,
         meters, slat, slon, slie, sliesrc, elat, elon, elie, eliesrc,
         t_ms, tz_ms, excl, yards, to_pin, remaining, m_range, m_side, m_lat,
         phantom, phantom_reason, confidence, sg_cat, sg_val) in shot_rows:
        geom_computed = to_pin is not None or remaining is not None
        shot = {
            "shotId": sid,                                       # NEW in v2
            "shotNumber": order,
            "club": club,
            "clubTypeId": club_type,
            "clubId": club_id,
            "clubRetired": retired,
            "type": stype,
            "autoShotType": auto,
            "source": source,
            "yards": yards,
            "meters": meters,
            "from": slie,
            "to": elie,
            "start": ({"lat": slat, "lon": slon, "lie": slie, "lieSource": sliesrc}
                      if not (slat is None and slon is None and slie is None) else None),
            "end": ({"lat": elat, "lon": elon, "lie": elie, "lieSource": eliesrc}
                    if not (elat is None and elon is None and elie is None) else None),
            "shotTime": _iso(t_ms, tz_ms),
            "excludeFromStats": excl,
            "offMap": elie == "Unknown",
            "distanceToPinBeforeYds": to_pin,
            "distanceRemainingYds": remaining,
            "miss": ({"range": m_range, "side": m_side, "lateralYds": m_lat}
                     if geom_computed else None),
            "phantom": phantom,
            "phantomReason": phantom_reason,
            "sgCategory": sg_cat,                                # None for phantoms
            "strokesGained": round(sg_val, 3) if sg_val is not None else None,
            "confidence": confidence,                            # NEW in v2
        }
        shot["resultCategory"] = _result_category(shot)
        if sid in ann_by_shot:
            shot["annotation"] = ann_by_shot[sid]                # NEW in v2
        shots_by_hole.setdefault(hole, []).append(shot)

    holes = []
    for (n, par, si, strokes, putts, pens, fairway, hcp_score, pin_lat, pin_lon,
         gir, scr_opp, scr_save, first_putt, shots_recorded, phantom_shots) in hole_rows:
        hole_shots = shots_by_hole.get(n, [])
        real_shots = [s for s in hole_shots if not s["phantom"]]
        to_par = (strokes - par) if (strokes is not None and par is not None) else None
        holes.append({
            "number": n,
            "par": par,
            "strokeIndex": si,
            "playedLengthYds": real_shots[0]["distanceToPinBeforeYds"] if real_shots else None,
            "strokes": strokes,
            "putts": putts,
            "penalties": pens,
            "scoreToPar": to_par,
            "scoreName": _score_name(to_par) if to_par is not None else None,
            "fairway": fairway,
            "gir": gir,
            "firstPuttDistanceFt": first_putt,
            "scrambleOpportunity": scr_opp,
            "scrambleSave": scr_save,
            "shotCountDelta": (len(real_shots) - strokes) if strokes is not None else None,
            "handicapScore": hcp_score,
            "pin": {"lat": pin_lat, "lon": pin_lon, "lie": None, "lieSource": None},
            "shotsRecorded": shots_recorded,
            "phantomShots": phantom_shots,
            "shots": hole_shots,
        })

    raw_recorded = sum(len(shots_by_hole.get(h["number"], [])) for h in holes)
    phantom_count = sum(h["phantomShots"] for h in holes)
    real_count = raw_recorded - phantom_count

    sg_row = con.execute("""
        SELECT sg_off_tee, sg_long_approach, sg_mid_approach, sg_inside50, sg_putting,
               sg_0_100, categorized_shots, putt_holes_measured, putts_covered
        FROM derived.round_sg WHERE round_id = ?""", [rid]).fetchone()
    by_cat = {"offTee": round(sg_row[0], 2), "longApproach": round(sg_row[1], 2),
              "midApproach": round(sg_row[2], 2), "inside50": round(sg_row[3], 2),
              "putting": round(sg_row[4], 2)}
    three_putts = sum(1 for h in holes if (h["putts"] or 0) >= 3)
    doubles = sum(1 for h in holes if (h["scoreToPar"] or 0) >= 2)
    strokes_gained_summary = {
        "baseline": "PGA Tour (scratch), approximate",
        "totalRecordedVsScratch": round(sum(by_cat.values()), 2),
        "byCategory": by_cat,
        "sg0to100": round(sg_row[5], 2),
        "categorizedShots": sg_row[6],
        "penaltyStrokes": r["total_penalties"],
        "doublesOrWorse": doubles,
        "putting": {
            "totalPutts": r["total_putts"],
            "threePutts": three_putts,
            "sgFromCounts": by_cat["putting"],
            "holesMeasured": sg_row[7],
            "puttsCovered": sg_row[8],
        },
        "note": (
            "Tee-to-green SG is per-shot over recorded shots (penalties & un-sensed shots "
            "excluded). Buckets are distance-based (offTee = par4/5 tee; long 150+, mid "
            "50-150, inside-50). sg0to100 is the leverage metric (100yd-and-in, no putts). "
            "Putting is count-based (3-putts penalized; totalPutts/threePutts authoritative)."
        ),
    }

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "scorecardId": rid,
        "source": "garminconnect",
        "round": {
            "date": r["start_time"],
            "endTime": r["end_time"],
            "scoreType": r["score_type"],
            "roundType": r["round_type"],
            "holesCompleted": r["holes_completed"],
            "teeBox": r["tee_box"],
            "teeBoxRating": r["tee_rating"],
            "teeBoxSlope": r["tee_slope"],
            "playerHandicap": r["player_handicap"],
            "sensorOnPutter": r["sensor_on_putter"],
            "distanceWalkedMeters": r["distance_walked_m"],
            "stepsTaken": r["steps_taken"],
        },
        "course": {
            "name": r["course_name"],
            "globalId": r["course_global_id"],
            "snapshotId": r["course_snapshot_id"],
            "city": r["course_city"], "state": r["course_state"],
            "country": r["course_country"], "street": r["course_street"],
            "zip": r["course_zip"],
            "lat": r["course_lat"], "lon": r["course_lon"],
            "par": r["round_par"],
            "frontNinePar": r["front_nine_par"],
            "backNinePar": r["back_nine_par"],
            "holePars": pars,
        },
        "score": {  # AUTHORITATIVE
            "strokes": r["total_strokes"],
            "par": r["round_par"],
            "toPar": r["total_strokes"] - r["round_par"] if r["round_par"] else None,
            "putts": r["total_putts"],
            "penalties": r["total_penalties"],
            "holesCompleted": r["holes_completed"],
            "handicappedStrokes": r["handicapped_strokes"],
        },
        "coachSummary": _coach_summary(holes, r["total_strokes"], r["total_putts"],
                                       r["total_penalties"], gstats or {}, gratings),
        "strokesGained": strokes_gained_summary,
        "garminStats": gstats,
        "garminRatings": gratings,
        "garminLongestShotMeters": r["longest_shot_m"],
        "reconciliation": {
            "recordedShots": real_count,
            "rawRecordedShots": raw_recorded,
            "strokes": r["total_strokes"],
            "penalties": r["total_penalties"],
            "shotCountDelta": real_count - r["total_strokes"],
            "phantomShots": phantom_count,
            "phantomShotHoles": [h["number"] for h in holes if h["phantomShots"]],
            "suspectHoles": [h["number"] for h in holes
                             if h["strokes"] and (h["shotsRecorded"] - h["strokes"]) > 2],
            "emptyShotHoles": [h["number"] for h in holes
                               if h["strokes"] and h["shotsRecorded"] == 0],
            "note": (
                "Score is authoritative. The sensor shot layer is imperfect: it can "
                "under-record (un-sensed short shots; penalties carry no position) or "
                "over-record (phantom/practice strokes). Treat shot counts as spatial "
                "detail, not stroke truth; discount suspectHoles for club/distance stats. "
                "Counts here EXCLUDE phantomShots (between-hole transit logged as strokes); "
                "those shots stay in `holes[].shots` flagged with phantom=true."
            ),
        },
        "annotations": ann_block,                                # NEW in v2
        "holes": holes,
    }
    return doc


def _coach_summary(holes: list[dict], strokes: int, putts: int, penalties: int,
                   gstats: dict, gratings: dict | None) -> dict:
    """The round-level metrics an LLM coach asked for. Garmin-authoritative where Garmin
    provides it (fairways/GIR/ups-and-downs); derived (and labeled) otherwise."""
    first_putts = [h["firstPuttDistanceFt"] for h in holes if h["firstPuttDistanceFt"] is not None]
    drives = [s["yards"] for h in holes for s in h["shots"]
              if s["type"] == "TEE" and s["yards"] is not None and not s["phantom"]]
    return {
        "score": strokes,
        "putts": putts,
        "penalties": penalties,
        "fairways_hit": gstats.get("fairwaysHit"),
        "fairways_recorded": gstats.get("fairwaysRecorded"),
        "gir": gstats.get("greensInRegulation"),
        "greens_recorded": gstats.get("greensRecorded"),
        "double_or_worse": sum(1 for h in holes if (h["scoreToPar"] or 0) >= 2),
        "three_putts": sum(1 for h in holes if (h["putts"] or 0) >= 3),
        "scramble_opportunities": sum(1 for h in holes if h["scrambleOpportunity"]),
        "up_and_down_saves": gstats.get("upsAndDowns"),  # authoritative (Garmin)
        "up_and_down_saves_derived": sum(1 for h in holes if h["scrambleSave"]),
        "scramble_pct": round(100 * (gstats.get("upsAndDowns") or 0)
                              / sum(1 for h in holes if h["scrambleOpportunity"]), 1)
                        if any(h["scrambleOpportunity"] for h in holes) else None,
        "first_putt_distance_avg_ft": round(sum(first_putts) / len(first_putts), 1)
                                      if first_putts else None,
        "first_putt_distance_basis": f"{len(first_putts)} holes that reached the green (GPS-based)",
        "longest_drive_yds": round(max(drives), 1) if drives else None,
        "garmin_ratings": gratings,
    }


# --- markdown card -----------------------------------------------------------------

def _recon_line(r: dict) -> str:
    delta = r["shotCountDelta"]
    direction = ("matches score" if delta == 0
                 else f"{delta:+d} vs score "
                      + ("(sensor over-recorded)" if delta > 0 else "(some shots un-sensed)"))
    line = f"Shots recorded: {r['recordedShots']}/{r['strokes']} — {direction}"
    if r.get("phantomShots"):
        line += (f" · {r['phantomShots']} phantom shot(s) dropped "
                 f"on holes {r['phantomShotHoles']}")
    if r["suspectHoles"]:
        line += f" · suspect holes {r['suspectHoles']}"
    if r["emptyShotHoles"]:
        line += f" · no-shot-data holes {r['emptyShotHoles']}"
    return line


def _sg_line(sg: dict) -> str:
    c = sg["byCategory"]
    short = {"offTee": "OTT", "longApproach": "Long", "midApproach": "Mid",
             "inside50": "In50", "putting": "Putt"}
    parts = " · ".join(f"{short[k]} {c[k]:+.1f}" for k in short)
    return (f"Strokes Gained vs scratch: {parts} = {sg['totalRecordedVsScratch']:+.1f}\n"
            f"SG 0–100 (leverage): {sg['sg0to100']:+.1f} · {sg['penaltyStrokes']} penalties · "
            f"{sg['doublesOrWorse']} doubles+")


def render_markdown(doc: dict) -> str:
    s, c, sc = doc["round"], doc["course"], doc["score"]
    cs = doc["coachSummary"]
    lines = [
        f"# {c['name']} ({c.get('city')} {c.get('state')}) — {s['date'][:10]}",
        f"Par {sc['par']}, Score {sc['strokes']} ({sc['toPar']:+d}), "
        f"{sc['putts']} putts, {sc['penalties']} penalties — tees: {s['teeBox']} "
        f"({s['teeBoxRating']}/{s['teeBoxSlope']})",
        f"FW {cs['fairways_hit']}/{cs['fairways_recorded']} · "
        f"GIR {cs['gir']}/{cs['greens_recorded']} · "
        f"3-putts {cs['three_putts']} · dbl+ {cs['double_or_worse']} · "
        f"scramble {cs['up_and_down_saves']}/{cs['scramble_opportunities']} "
        f"({cs['scramble_pct']}%) · "
        f"avg 1st putt {cs['first_putt_distance_avg_ft']}ft · "
        f"long drive {cs['longest_drive_yds']}y",
        _recon_line(doc["reconciliation"]),
        _sg_line(doc["strokesGained"]),
        "",
    ]
    ann = doc.get("annotations") or {}
    tagged = {t["shotId"]: t for t in ann.get("shots", [])}
    hole_notes = {t["hole"]: t for t in ann.get("holes", [])}
    for h in doc["holes"]:
        fw = f"FW:{h['fairway']}" if h["fairway"] else "FW:-"
        gir = "GIR:yes" if h["gir"] else "GIR:no"
        si = f"SI{h['strokeIndex']}" if h["strokeIndex"] else ""
        plen = f"~{h['playedLengthYds']:.0f}y" if h["playedLengthYds"] else ""
        lines.append(
            f"H{h['number']} P{h['par']} {plen} {si}  {h['strokes']} ({h['scoreToPar']:+d} "
            f"{h['scoreName']})  {fw}  {gir}  putts:{h['putts']}  pen:{h['penalties']}"
        )
        hn = hole_notes.get(h["number"])
        if hn and (hn.get("postTeeState") or hn.get("doubleClass")):
            bits = [b for b in (
                f"after-tee: {hn['postTeeState']}" if hn.get("postTeeState") else None,
                f"double: {hn['doubleClass']}" if hn.get("doubleClass") else None,
                "preventable escalation" if hn.get("preventableEscalation") else None,
            ) if b]
            lines.append(f"  ctx: {' · '.join(bits)}")
        for sh in h["shots"]:
            club = sh["club"] if sh["club"] != "unknown" else "(?)"
            tag = " [auto,no club]" if sh["source"] == "DEVICE_AUTO" else ""
            yd = f"{sh['yards']:.0f}y" if sh["yards"] is not None else "?"
            rem = (f" →{sh['distanceRemainingYds']:.0f}y left"
                   if sh["distanceRemainingYds"] is not None else "")
            res = f" [{sh['resultCategory']}]" if sh["resultCategory"] else ""
            t = tagged.get(sh["shotId"])
            ctx = f" «{t['intent']}{': ' + t['evaluation'] if t.get('evaluation') else ''}»" \
                if t else ""
            lines.append(
                f"  {sh['shotNumber']}. {club:10} {yd:>5}  {sh['from']}→{sh['to']}"
                f"{rem}{res}{ctx}{tag}"
            )
        lines.append("")
    return "\n".join(lines)


# --- entrypoint --------------------------------------------------------------------

def round_stem(doc: dict) -> str:
    """Browsable filename stem: YYYY_MM_DD_<scorecardId> (date first, sorts chronologically)."""
    date = doc["round"]["date"][:10].replace("-", "_")
    return f"{date}_{doc['scorecardId']}"


def export_round(con, rid: int) -> dict:
    doc = build_round_document(con, rid)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob(f"*{rid}.json"):
        old.unlink()
    for old in OUT_DIR.glob(f"*{rid}.md"):
        old.unlink()
    stem = round_stem(doc)
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(doc, indent=2))
    (OUT_DIR / f"{stem}.md").write_text(render_markdown(doc))
    return doc


def export_all(con, round_ids: list[int] | None = None) -> int:
    """Export the given rounds (None = every round in the analysis window)."""
    if round_ids is None:
        round_ids = [r[0] for r in con.execute(
            "SELECT round_id FROM canon.round WHERE round_date >= ? ORDER BY round_date",
            [analysis_start_date()]).fetchall()]
    else:
        since = analysis_start_date()
        round_ids = [rid for rid in round_ids
                     if con.execute("SELECT round_date >= ? FROM canon.round "
                                    "WHERE round_id = ?", [since, rid]).fetchone()[0]]
    for rid in round_ids:
        export_round(con, rid)
    return len(round_ids)


def main() -> None:
    from .db import connect
    con = connect()
    ids = [int(a) for a in sys.argv[1:] if a.isdigit()] or None
    n = export_all(con, ids)
    print(f"exported {n} round document(s) -> {OUT_DIR}")


if __name__ == "__main__":
    main()
