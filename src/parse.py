"""Raw JSON -> a single self-contained 'round document' per round (the source of truth).

Design contract (SPEC §2, and the structuring discussion):
  - The raw files in data/raw/ are the immutable asset. This module only reads them.
  - The round document is a faithful SUPERSET: every Garmin field is preserved, and
    every value we compute is added ALONGSIDE (never replacing) and clearly derived.
  - The scorecard layer (strokes/putts/penalties) is AUTHORITATIVE. The shot layer is
    the spatial/club detail and may undercount; the reconciliation block makes the gap
    explicit so a consumer (UI or LLM) never "corrects" the score to match shots.

Outputs, per scorecard id:
  - data/processed/rounds/{id}.json  — the nested round document
  - data/processed/rounds/{id}.md    — a compact, token-efficient card for LLM prompts

Usage:
    python -m src.parse                # parse the default scorecard
    python -m src.parse 364945310      # parse a specific scorecard id
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import strokes_gained
from .geo import semicircles_to_degrees as s2d
from .geo import shot_geometry

GREENSIDE_YDS = 50.0  # within this of the pin counts as a greenside up-and-down chance

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed/rounds")
CLUBS_CONFIG = Path("config/clubs.json")

SCHEMA_VERSION = 1
METERS_TO_YARDS = 1.09361
DEFAULT_SCORECARD = 364945310

SCORE_NAMES = {-3: "Albatross", -2: "Eagle", -1: "Birdie", 0: "Par", 1: "Bogey",
               2: "Double Bogey", 3: "Triple Bogey"}


# --- loading -----------------------------------------------------------------------

def _load(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)


def load_club_config() -> dict:
    """Club identity config: physical-club names (byClubId), coarse type fallback
    (byType), and the set of retired clubIds."""
    cfg = _load(CLUBS_CONFIG)
    return {
        "byClubId": cfg.get("byClubId", {}),                      # str(clubId) -> name
        "byType": {int(k): v for k, v in cfg.get("map", {}).items()},  # clubTypeId -> name
        "retired": {int(c) for c in cfg.get("retiredClubIds", [])},
    }


def _resolve_club(club_id: int, club_type: int | None, cfg: dict) -> str:
    """Prefer the physical club (clubId); fall back to Garmin's coarse type."""
    return (cfg["byClubId"].get(str(club_id))
            or cfg["byType"].get(club_type)
            or "unknown")


# --- small helpers -----------------------------------------------------------------

def _yards(meters: float | None) -> float | None:
    return round(meters * METERS_TO_YARDS, 1) if meters is not None else None


def _loc(raw: dict | None) -> dict | None:
    """Normalize a Garmin location: keep lie/lieSource verbatim, add decimal lat/lon."""
    if not raw:
        return None
    return {
        "lat": s2d(raw["lat"]) if raw.get("lat") is not None else None,
        "lon": s2d(raw["lon"]) if raw.get("lon") is not None else None,
        "lie": raw.get("lie"),
        "lieSource": raw.get("lieSource"),  # CARTOGRAPHY = map-derived, not a ground sensor
    }


def _iso(epoch_ms: int | None, offset_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    tz = timezone(timedelta(milliseconds=offset_ms or 0))
    return datetime.fromtimestamp(epoch_ms / 1000, tz).isoformat()


def _score_name(to_par: int) -> str:
    return SCORE_NAMES.get(to_par, f"+{to_par}" if to_par > 0 else str(to_par))


# --- shot layer --------------------------------------------------------------------

def _build_shots_by_hole(shots_raw: dict, club_cfg: dict) -> dict[int, list[dict]]:
    """Index normalized shots by hole number. clubId -> clubTypeId comes from the
    per-payload clubDetails; the name is resolved by physical clubId then coarse type."""
    club_type_by_id: dict[int, int] = {}
    for hole in shots_raw["perHole"]:
        for cd in hole["response"].get("clubDetails", []):
            club_type_by_id[cd["id"]] = cd.get("clubTypeId")

    by_hole: dict[int, list[dict]] = {}
    for hole in shots_raw["perHole"]:
        for hs in hole["response"].get("holeShots", []):
            for s in hs["shots"]:
                club_type = club_type_by_id.get(s["clubId"])
                by_hole.setdefault(s["holeNumber"], []).append({
                    "shotNumber": s["shotOrder"],
                    "club": _resolve_club(s["clubId"], club_type, club_cfg),
                    "clubTypeId": club_type,
                    "clubId": s["clubId"],          # 0 = no sensor / unselected
                    "clubRetired": s["clubId"] in club_cfg["retired"],
                    "type": s.get("shotType"),
                    "autoShotType": s.get("autoShotType"),
                    "source": s.get("shotSource"),  # SENSOR (CT10) vs DEVICE_AUTO (watch)
                    "yards": _yards(s.get("meters")),
                    "meters": s.get("meters"),
                    "from": (s.get("startLoc") or {}).get("lie"),
                    "to": (s.get("endLoc") or {}).get("lie"),
                    "start": _loc(s.get("startLoc")),
                    "end": _loc(s.get("endLoc")),
                    "shotTime": _iso(s.get("shotTime"), s.get("shotTimeZoneOffset")),
                    "excludeFromStats": s.get("excludeFromStats"),
                })
    for shots in by_hole.values():
        shots.sort(key=lambda x: x["shotNumber"])
    return by_hole


def _result_category(shot: dict, geom: dict | None) -> str | None:
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
    if not geom or geom["range"] is None:
        return None
    if geom["side"] in ("left", "right"):
        return f"{geom['range']}-{geom['side']}"
    return geom["range"]


def _enrich_shots_with_pin(shots: list[dict], pin: dict | None) -> None:
    """Add distance-to-pin (before/after), result category, and off-map flag in place."""
    for shot in shots:
        shot["offMap"] = shot["to"] == "Unknown"  # factual; correlates with trouble/penalty
        geom = None
        start, end = shot.get("start"), shot.get("end")
        if pin and pin.get("lat") is not None and start and end \
                and start.get("lat") is not None and end.get("lat") is not None:
            geom = shot_geometry(
                (start["lat"], start["lon"]),
                (end["lat"], end["lon"]),
                (pin["lat"], pin["lon"]),
            )
            shot["distanceToPinBeforeYds"] = geom["toPinBeforeYds"]
            shot["distanceRemainingYds"] = geom["remainingYds"]
            shot["miss"] = {"range": geom["range"], "side": geom["side"],
                            "lateralYds": geom["lateralYds"]}
        else:
            shot["distanceToPinBeforeYds"] = None
            shot["distanceRemainingYds"] = None
            shot["miss"] = None
        shot["resultCategory"] = _result_category(shot, geom)


def _tee_stroke_index(course: dict, tee_name: str | None) -> list[int] | None:
    """Per-hole handicap/stroke index for the played tee, parsed from holeHandicaps."""
    if not tee_name:
        return None
    for tee in course.get("tees") or []:
        hh = tee.get("holeHandicaps")
        # 2 digits per hole; length is 18 (9-hole course) or 36 (18-hole).
        if tee.get("name") == tee_name and hh and len(hh) >= 2 and len(hh) % 2 == 0:
            return [int(hh[i:i + 2]) for i in range(0, len(hh), 2)]
    return None


# --- round document ----------------------------------------------------------------

def build_round_document(detail_raw: dict, shots_raw: dict, club_cfg: dict) -> dict:
    det = detail_raw["scorecardDetails"][0]
    sc = det["scorecard"]
    course = detail_raw["courseSnapshots"][0]
    pars = [int(c) for c in course["holePars"]]
    shots_by_hole = _build_shots_by_hole(shots_raw, club_cfg)

    total_strokes = sum(h.get("strokes", 0) for h in sc["holes"])
    total_putts = sum(h.get("putts", 0) for h in sc["holes"])
    total_penalties = sum(h.get("penalties", 0) for h in sc["holes"])
    recorded_shots = sum(len(v) for v in shots_by_hole.values())
    stroke_index = _tee_stroke_index(course, sc.get("teeBox"))

    holes = []
    for h in sc["holes"]:
        n = h["number"]
        # Wrap with modulo so a 9-hole layout played as 18 (two loops) reuses holes 1-9.
        par = pars[(n - 1) % len(pars)] if pars else None
        strokes = h.get("strokes")
        putts = h.get("putts")
        to_par = (strokes - par) if (strokes is not None and par is not None) else None
        # GIR (derived): reached green in (par - 2) or fewer non-putt strokes.
        gir = None
        if strokes is not None and putts is not None and par is not None:
            gir = (strokes - putts) <= (par - 2)
        hole_shots = shots_by_hole.get(n, [])
        pin = _loc({"lat": h.get("pinPositionLat"), "lon": h.get("pinPositionLon")})
        _enrich_shots_with_pin(hole_shots, pin)

        # Derived helpers from the (now enriched) shots:
        green_reach = next((s for s in hole_shots if s["to"] == "Green"), None)
        # First putt distance = how far the ball was from the cup when it reached the green.
        # Only reliable when a real putt was recorded: on holes with no putt shots, Garmin
        # snaps the approach's end onto the pin (→ a false 0 ft), so we report None there.
        has_recorded_putt = any(s["type"] == "PUTT" for s in hole_shots)
        first_putt_ft = None
        if green_reach and green_reach["distanceRemainingYds"] is not None and has_recorded_putt:
            first_putt_ft = round(green_reach["distanceRemainingYds"] * 3.0, 1)  # 1 yd = 3 ft
        # Scrambling (standard definition): a missed GIR is an opportunity; making par or
        # better despite it is a save. This reconciles with Garmin's upsAndDowns count.
        scramble_opportunity = gir is False
        scramble_save = bool(gir is False and to_par is not None and to_par <= 0)
        # Played length proxy: tee shot start -> pin (straight line; NOT architect yardage).
        played_len = hole_shots[0]["distanceToPinBeforeYds"] if hole_shots else None

        holes.append({
            "number": n,
            "par": par,
            "strokeIndex": stroke_index[(n - 1) % len(stroke_index)] if stroke_index else None,
            "playedLengthYds": played_len,           # DERIVED proxy (no true yardage from Garmin)
            "strokes": strokes,
            "putts": putts,
            "penalties": h.get("penalties"),
            "scoreToPar": to_par,
            "scoreName": _score_name(to_par) if to_par is not None else None,
            "fairway": h.get("fairwayShotOutcome"),  # HIT / LEFT / RIGHT / None(par 3)
            "gir": gir,                              # DERIVED
            "firstPuttDistanceFt": first_putt_ft,    # DERIVED (GPS-based, noisy at short range)
            "scrambleOpportunity": scramble_opportunity,  # DERIVED (missed GIR)
            "scrambleSave": scramble_save,                # DERIVED (missed GIR, par or better)
            "shotCountDelta": (len(hole_shots) - strokes) if strokes is not None else None,
            "handicapScore": h.get("handicapScore"),
            "pin": pin,
            "shotsRecorded": len(hole_shots),
            "shots": hole_shots,
        })

    # Strokes Gained annotates each shot (sgCategory, strokesGained) in place.
    strokes_gained_summary = strokes_gained.compute(holes)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "scorecardId": sc["id"],
        "source": "garminconnect",
        "round": {
            "date": sc.get("startTime"),
            "endTime": sc.get("endTime"),
            "scoreType": sc.get("scoreType"),
            "roundType": sc.get("roundType"),
            "holesCompleted": sc.get("holesCompleted"),
            "teeBox": sc.get("teeBox"),
            "teeBoxRating": sc.get("teeBoxRating"),
            "teeBoxSlope": sc.get("teeBoxSlope"),
            "playerHandicap": sc.get("playerHandicap"),
            "sensorOnPutter": sc.get("sensorOnPutter"),
            "distanceWalkedMeters": sc.get("distanceWalked"),
            "stepsTaken": sc.get("stepsTaken"),
        },
        "course": {
            "name": course.get("name"),
            "globalId": course.get("courseGlobalId"),
            "snapshotId": course.get("courseSnapshotId"),
            "city": course.get("city"), "state": course.get("state"),
            "country": course.get("country"), "street": course.get("street"),
            "zip": course.get("zip"),
            "lat": s2d(course["lat"]) if course.get("lat") is not None else None,
            "lon": s2d(course["lon"]) if course.get("lon") is not None else None,
            "par": course.get("roundPar"),
            "frontNinePar": course.get("frontNinePar"),
            "backNinePar": course.get("backNinePar"),
            "holePars": pars,
        },
        "score": {  # AUTHORITATIVE
            "strokes": total_strokes,
            "par": course.get("roundPar"),
            "toPar": total_strokes - course["roundPar"] if course.get("roundPar") else None,
            "putts": total_putts,
            "penalties": total_penalties,
            "holesCompleted": sc.get("holesCompleted"),
            "handicappedStrokes": sc.get("handicappedStrokes"),
        },
        "coachSummary": _coach_summary(holes, total_strokes, total_putts, total_penalties,
                                       det.get("scorecardStats", {}).get("round") or {},
                                       det.get("statsComparison")),
        "strokesGained": strokes_gained_summary,
        "garminStats": det.get("scorecardStats", {}).get("round"),   # preserved verbatim
        "garminRatings": det.get("statsComparison"),                 # preserved verbatim
        "garminLongestShotMeters": det.get("longestShotInMeters"),
        "reconciliation": {
            "recordedShots": recorded_shots,
            "strokes": total_strokes,
            "penalties": total_penalties,
            # + = sensor over-recorded (phantom/practice strokes); - = under-recorded.
            "shotCountDelta": recorded_shots - total_strokes,
            # Holes where the sensor logged many more shots than the score — suspect for
            # shot-level (club/distance/first-putt) analysis; the score is still trusted.
            "suspectHoles": [h["number"] for h in holes
                             if h["strokes"] and (h["shotsRecorded"] - h["strokes"]) > 2],
            # Holes with a real score but zero recorded shots (a shot-data gap).
            "emptyShotHoles": [h["number"] for h in holes
                               if h["strokes"] and h["shotsRecorded"] == 0],
            "note": (
                "Score is authoritative. The sensor shot layer is imperfect: it can "
                "under-record (un-sensed short shots; penalties carry no position) or "
                "over-record (phantom/practice strokes). Treat shot counts as spatial "
                "detail, not stroke truth; discount suspectHoles for club/distance stats."
            ),
        },
        "holes": holes,
    }


def _coach_summary(holes: list[dict], strokes: int, putts: int, penalties: int,
                   gstats: dict, gratings: dict | None) -> dict:
    """The round-level metrics an LLM coach asked for. Garmin-authoritative where Garmin
    provides it (fairways/GIR/ups-and-downs); derived (and labeled) otherwise."""
    first_putts = [h["firstPuttDistanceFt"] for h in holes if h["firstPuttDistanceFt"] is not None]
    drives = [s["yards"] for h in holes for s in h["shots"]
              if s["type"] == "TEE" and s["yards"] is not None]
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
    if r["suspectHoles"]:
        line += f" · suspect holes {r['suspectHoles']}"
    if r["emptyShotHoles"]:
        line += f" · no-shot-data holes {r['emptyShotHoles']}"
    return line


def _sg_line(sg: dict) -> str:
    c = sg["byCategory"]
    return (f"Strokes Gained vs scratch (recorded shots): "
            f"OTT {c['offTee']:+.1f} · APP {c['approach']:+.1f} · "
            f"ARG {c['aroundGreen']:+.1f} · PUTT {c['putting']:+.1f} "
            f"= {sg['totalRecordedVsScratch']:+.1f}; +{sg['penaltyStrokes']} penalties")


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
    for h in doc["holes"]:
        fw = f"FW:{h['fairway']}" if h["fairway"] else "FW:-"
        gir = "GIR:yes" if h["gir"] else "GIR:no"
        si = f"SI{h['strokeIndex']}" if h["strokeIndex"] else ""
        plen = f"~{h['playedLengthYds']:.0f}y" if h["playedLengthYds"] else ""
        lines.append(
            f"H{h['number']} P{h['par']} {plen} {si}  {h['strokes']} ({h['scoreToPar']:+d} "
            f"{h['scoreName']})  {fw}  {gir}  putts:{h['putts']}  pen:{h['penalties']}"
        )
        for sh in h["shots"]:
            club = sh["club"] if sh["club"] != "unknown" else "(?)"
            tag = " [auto,no club]" if sh["source"] == "DEVICE_AUTO" else ""
            yd = f"{sh['yards']:.0f}y" if sh["yards"] is not None else "?"
            rem = (f" →{sh['distanceRemainingYds']:.0f}y left"
                   if sh["distanceRemainingYds"] is not None else "")
            res = f" [{sh['resultCategory']}]" if sh["resultCategory"] else ""
            lines.append(
                f"  {sh['shotNumber']}. {club:10} {yd:>5}  {sh['from']}→{sh['to']}{rem}{res}{tag}"
            )
        lines.append("")
    return "\n".join(lines)


# --- entrypoint --------------------------------------------------------------------

def parse_scorecard(scorecard_id: int) -> dict:
    detail = _load(RAW_DIR / f"scorecard_{scorecard_id}_detail.json")
    shots = _load(RAW_DIR / f"scorecard_{scorecard_id}_shots.json")
    doc = build_round_document(detail, shots, load_club_config())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{scorecard_id}.json").write_text(json.dumps(doc, indent=2))
    (OUT_DIR / f"{scorecard_id}.md").write_text(render_markdown(doc))
    return doc


def main() -> None:
    scorecard_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SCORECARD
    doc = parse_scorecard(scorecard_id)
    r = doc["reconciliation"]
    print(f"Wrote {OUT_DIR}/{scorecard_id}.json and .md")
    print(f"  {len(doc['holes'])} holes, {r['recordedShots']} shots, "
          f"score {doc['score']['strokes']} ({doc['score']['toPar']:+d}), "
          f"shot delta {r['shotCountDelta']:+d}")


if __name__ == "__main__":
    main()
