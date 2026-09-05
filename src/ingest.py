"""Raw JSON + config -> canon tables. Idempotent and incremental.

Per round, in one transaction: if the raw pair's sha256s (and the loader version)
match canon.ingest_meta, skip; otherwise delete that round's canon rows and re-insert
from the raw files. Reference tables (clubs, SG baseline) reload from config each run
— the files are truth, the database is a projection.

Normalization here is deterministic unit conversion only (semicircles -> degrees,
holePars digits -> per-hole par, holeHandicaps -> stroke index). Interpretations
(phantom flags, GIR, SG) live in derived.*.

Usage:
    python -m src.ingest             # ingest anything new/changed in data/raw/
    python -m src.ingest 364945310   # one round
    python -m src.ingest --force     # re-ingest everything regardless of shas
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import duckdb

from .geo import semicircles_to_degrees as s2d

RAW_DIR = Path("data/raw")
BIRDIES_DIR = Path("data/raw/18birdies")
ANN_DIR = Path("data/annotations")
CLUBS_CONFIG = Path("config/clubs.json")
SG_BASELINE_CONFIG = Path("config/sg_baseline.json")

# Bump when the normalization below changes meaning; `python -m src.db rebuild`
# then re-ingests every round under the new logic.
LOADER_VERSION = 3   # v3: + round source, observed GIR, 18birdies backfill loader


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deg(semicircles) -> float | None:
    return s2d(semicircles) if semicircles is not None else None


def raw_round_ids(raw_dir: Path = RAW_DIR) -> list[int]:
    """Every round with a complete raw pair on disk, ascending id order."""
    ids = []
    for f in raw_dir.glob("scorecard_*_detail.json"):
        m = re.match(r"scorecard_(\d+)_detail\.json", f.name)
        if m and (raw_dir / f"scorecard_{m.group(1)}_shots.json").exists():
            ids.append(int(m.group(1)))
    return sorted(ids)


def _tee_stroke_index(course: dict, tee_name: str | None) -> list[int] | None:
    """Per-hole handicap/stroke index for the played tee, parsed from holeHandicaps
    (2 digits per hole; length 18 for a 9-hole layout, 36 for 18)."""
    if not tee_name:
        return None
    for tee in course.get("tees") or []:
        hh = tee.get("holeHandicaps")
        if tee.get("name") == tee_name and hh and len(hh) >= 2 and len(hh) % 2 == 0:
            return [int(hh[i:i + 2]) for i in range(0, len(hh), 2)]
    return None


def load_reference(con: duckdb.DuckDBPyConnection,
                   clubs_path: Path = CLUBS_CONFIG,
                   baseline_path: Path = SG_BASELINE_CONFIG) -> None:
    """(Re)load canon.club / canon.club_type / canon.sg_baseline from config."""
    cfg = json.loads(clubs_path.read_text())
    retired = {int(c) for c in cfg.get("retiredClubIds", [])}
    con.execute("BEGIN")
    con.execute("DELETE FROM canon.club")
    for cid, name in cfg.get("byClubId", {}).items():
        con.execute("INSERT INTO canon.club VALUES (?, ?, ?)",
                    [int(cid), name, int(cid) in retired])
    con.execute("DELETE FROM canon.club_type")
    for tid, name in cfg.get("map", {}).items():
        con.execute("INSERT INTO canon.club_type VALUES (?, ?)", [int(tid), name])
    base = json.loads(baseline_path.read_text())
    con.execute("DELETE FROM canon.sg_baseline")
    for lie, table in base["throughGreen"].items():
        for dist, expected in table.items():
            con.execute("INSERT INTO canon.sg_baseline VALUES (?, ?, ?)",
                        [lie, float(dist), expected])
    for dist_ft, expected in base["putting"].items():
        con.execute("INSERT INTO canon.sg_baseline VALUES ('putt', ?, ?)",
                    [float(dist_ft), expected])
    con.execute("COMMIT")


def _round_id_from_name(name: str) -> int:
    """data/annotations names are <YYYY_MM_DD_roundId>[.tags].json/.md."""
    return int(name.split(".")[0].rsplit("_", 1)[1])


def _ts(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso).replace(tzinfo=None) if iso else None


def load_annotations(con: duckdb.DuckDBPyConnection, ann_dir: Path = ANN_DIR) -> dict:
    """Fully reload annot.* from data/annotations/ — the files are truth. Narratives
    load from *.md; confirmed tags from *.tags.json (proposed drafts are ignored)."""
    con.execute("BEGIN")
    for t in ("annot.shot_context", "annot.hole_context",
              "annot.round_narrative", "annot.annotation_meta"):
        con.execute(f"DELETE FROM {t}")
    narratives = tagged = 0
    if ann_dir.exists():
        for md in sorted(ann_dir.glob("*.md")):
            con.execute("INSERT OR REPLACE INTO annot.round_narrative VALUES (?,?,?,?)", [
                _round_id_from_name(md.name), md.read_text(), str(md),
                datetime.fromtimestamp(md.stat().st_mtime)])
            narratives += 1
        for tf in sorted(ann_dir.glob("*.tags.json")):
            rid = _round_id_from_name(tf.name)
            tags = json.loads(tf.read_text())
            for t in tags.get("shots", []):
                con.execute("INSERT INTO annot.shot_context VALUES (?,?,?,?,?,?,?,?,?)", [
                    rid, t.get("shotId"), t.get("hole"), t.get("intent") or "other",
                    t.get("lieQuality"), t.get("evaluation"),
                    bool(t.get("excludeFromStock", (t.get("intent") or "other") != "normal")),
                    "confirmed", t.get("note")])
            for t in tags.get("unmatched", []):
                con.execute("INSERT INTO annot.shot_context VALUES (?,?,?,?,?,?,?,?,?)", [
                    rid, None, t.get("hole"), t.get("intent") or "other",
                    None, None, False, "unmatched", t.get("text")])
            for t in tags.get("holes", []):
                con.execute("INSERT OR REPLACE INTO annot.hole_context VALUES (?,?,?,?,?,?)", [
                    rid, t["hole"], t.get("postTeeState"), t.get("doubleClass"),
                    t.get("preventableEscalation"), t.get("note")])
            con.execute("INSERT OR REPLACE INTO annot.annotation_meta VALUES (?,?,?,?)", [
                rid, str(tf), tags.get("tagSchemaVersion"), _ts(tags.get("confirmedAt"))])
            tagged += 1
    con.execute("COMMIT")
    return {"narratives": narratives, "taggedRounds": tagged}


def ingest_round(con: duckdb.DuckDBPyConnection, scorecard_id: int,
                 raw_dir: Path = RAW_DIR, force: bool = False) -> str:
    """Load one round's raw pair into canon. Returns 'ingested' | 'skipped'."""
    detail_path = raw_dir / f"scorecard_{scorecard_id}_detail.json"
    shots_path = raw_dir / f"scorecard_{scorecard_id}_shots.json"
    detail_sha, shots_sha = _sha256(detail_path), _sha256(shots_path)

    if not force:
        row = con.execute(
            "SELECT raw_detail_sha256, raw_shots_sha256, loader_version "
            "FROM canon.ingest_meta WHERE round_id = ?", [scorecard_id]).fetchone()
        if row == (detail_sha, shots_sha, LOADER_VERSION):
            return "skipped"

    detail_raw = json.loads(detail_path.read_text())
    shots_raw = json.loads(shots_path.read_text())
    det = detail_raw["scorecardDetails"][0]
    sc = det["scorecard"]
    course = detail_raw["courseSnapshots"][0]
    pars = [int(c) for c in course.get("holePars", "")]
    stroke_index = _tee_stroke_index(course, sc.get("teeBox"))

    con.execute("BEGIN")
    for table in ("canon.shot", "canon.hole", "canon.round", "canon.ingest_meta"):
        con.execute(f"DELETE FROM {table} WHERE round_id = ?", [scorecard_id])

    con.execute("""
        INSERT INTO canon.round VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                                        ?,?,?,?,?,?,?,?,?,?,?,?,?, 'garminconnect')
    """, [
        sc["id"], (sc.get("startTime") or "")[:10] or None,
        sc.get("startTime"), sc.get("endTime"),
        sc.get("scoreType"), sc.get("roundType"), sc.get("holesCompleted"),
        sc.get("teeBox"), sc.get("teeBoxRating"), sc.get("teeBoxSlope"),
        sc.get("playerHandicap"), sc.get("handicappedStrokes"),
        sc.get("sensorOnPutter"), sc.get("distanceWalked"), sc.get("stepsTaken"),
        course.get("courseGlobalId"), course.get("courseSnapshotId"),
        course.get("name"), course.get("city"), course.get("state"),
        course.get("country"), course.get("street"), course.get("zip"),
        _deg(course.get("lat")), _deg(course.get("lon")),
        course.get("roundPar"), course.get("frontNinePar"), course.get("backNinePar"),
        course.get("holePars"),
        sum(h.get("strokes", 0) for h in sc["holes"]),
        sum(h.get("putts", 0) for h in sc["holes"]),
        sum(h.get("penalties", 0) for h in sc["holes"]),
        det.get("longestShotInMeters"),
    ] + [json.dumps(det.get("scorecardStats", {}).get("round")),
         json.dumps(det.get("statsComparison"))])

    for h in sc["holes"]:
        n = h["number"]
        # Wrap with modulo so a 9-hole layout played as 18 (two loops) reuses holes 1-9.
        par = pars[(n - 1) % len(pars)] if pars else None
        si = stroke_index[(n - 1) % len(stroke_index)] if stroke_index else None
        con.execute("INSERT INTO canon.hole VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)", [
            scorecard_id, n, par, si,
            h.get("strokes"), h.get("putts"), h.get("penalties"),
            h.get("fairwayShotOutcome"), h.get("handicapScore"),
            _deg(h.get("pinPositionLat")), _deg(h.get("pinPositionLon")),
        ])

    club_type_by_id: dict[int, int] = {}
    for ph in shots_raw["perHole"]:
        for cd in ph["response"].get("clubDetails", []):
            club_type_by_id[cd["id"]] = cd.get("clubTypeId")
    for ph in shots_raw["perHole"]:
        for hs in ph["response"].get("holeShots", []):
            for s in hs["shots"]:
                start, end = s.get("startLoc") or {}, s.get("endLoc") or {}
                con.execute(
                    "INSERT INTO canon.shot VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        s["id"], scorecard_id, s["holeNumber"], s["shotOrder"],
                        s.get("shotTime"), s.get("shotTimeZoneOffset"),
                        s.get("clubId"), club_type_by_id.get(s["clubId"]),
                        s.get("shotType"), s.get("autoShotType"), s.get("shotSource"),
                        s.get("meters"),
                        _deg(start.get("lat")), _deg(start.get("lon")),
                        start.get("lie"), start.get("lieSource"),
                        _deg(end.get("lat")), _deg(end.get("lon")),
                        end.get("lie"), end.get("lieSource"),
                        s.get("excludeFromStats"),
                    ])

    con.execute("""
        INSERT INTO canon.ingest_meta
        VALUES (?, ?, ?, ?, ?, ?, current_localtimestamp())
    """, [scorecard_id, str(detail_path), str(shots_path),
          detail_sha, shots_sha, LOADER_VERSION])
    con.execute("COMMIT")
    return "ingested"


def _birdies_round_id(date_str: str, seq: int) -> int:
    """Synthetic, deterministic round id for a backfill round: 18<YYYYMMDD><seq>.
    Far outside Garmin's id space, stable across rebuilds."""
    return int(f"18{date_str.replace('-', '')}{seq:02d}")


def ingest_18birdies_round(con: duckdb.DuckDBPyConnection, path: Path, seq: int,
                           force: bool = False) -> str:
    """Load one transcribed 18Birdies round into canon (source='18birdies').

    No shot layer exists for these rounds, so they feed the Outcome layer only —
    the SG/process pipeline filters on source. '-' cells were transcribed as null;
    a partially-recorded column yields a NULL round total, never a misleading sum.
    """
    sha = _sha256(path)
    d = json.loads(path.read_text())
    rid = _birdies_round_id(d["date"], seq)
    if not force:
        row = con.execute(
            "SELECT raw_detail_sha256, loader_version FROM canon.ingest_meta "
            "WHERE round_id = ?", [rid]).fetchone()
        if row == (sha, LOADER_VERSION):
            return "skipped"

    holes = d["holes"]
    tee = d.get("tee") or {}

    def total(key):
        vals = [h[key] for h in holes]
        return None if any(v is None for v in vals) else sum(vals)

    con.execute("BEGIN")
    for table in ("canon.shot", "canon.hole", "canon.round", "canon.ingest_meta"):
        con.execute(f"DELETE FROM {table} WHERE round_id = ?", [rid])
    con.execute("""
        INSERT INTO canon.round VALUES (?,?,?,NULL,'STROKE_PLAY','ALL',?,?,?,?,
                                        NULL,NULL,NULL,NULL,NULL,NULL,NULL,?,NULL,NULL,
                                        NULL,NULL,NULL,NULL,NULL,?,NULL,NULL,?,?,?,?,
                                        NULL,NULL,NULL,'18birdies')
    """, [
        rid, d["date"], f"{d['date']}T00:00:00.0",
        d["holesPlayed"], tee.get("name"), tee.get("rating"), tee.get("slope"),
        d["course"],
        sum(h["par"] for h in holes),
        "".join(str(h["par"]) for h in holes),
        d["totals"]["score"], total("putts"), total("penalties"),
    ])
    for h in holes:
        gir = h.get("gir")
        con.execute("INSERT INTO canon.hole VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL,?)", [
            rid, h["hole"], h["par"], h.get("strokeIndex"),
            h["score"], h.get("putts"), h.get("penalties"),
            h.get("fairway"), gir,
        ])
    con.execute("""
        INSERT INTO canon.ingest_meta
        VALUES (?, ?, ?, ?, ?, ?, current_localtimestamp())
    """, [rid, str(path), str(path), sha, sha, LOADER_VERSION])
    con.execute("COMMIT")
    return "ingested"


def ingest_all_18birdies(con: duckdb.DuckDBPyConnection, birdies_dir: Path = BIRDIES_DIR,
                         force: bool = False) -> dict:
    ingested = skipped = 0
    if birdies_dir.exists():
        by_date: dict[str, int] = {}
        for f in sorted(birdies_dir.glob("*.json")):
            date = json.loads(f.read_text())["date"]
            seq = by_date.get(date, 0) + 1
            by_date[date] = seq
            if ingest_18birdies_round(con, f, seq, force=force) == "ingested":
                ingested += 1
            else:
                skipped += 1
    return {"ingested": ingested, "skipped": skipped}


def ingest_all(con: duckdb.DuckDBPyConnection, raw_dir: Path = RAW_DIR,
               force: bool = False) -> dict:
    """Ingest reference config + every complete raw pair. Returns counts + the list of
    (re)ingested round ids so derive can recompute just those."""
    load_reference(con)
    load_annotations(con)
    ingested_ids: list[int] = []
    skipped = 0
    for rid in raw_round_ids(raw_dir):
        if ingest_round(con, rid, raw_dir=raw_dir, force=force) == "ingested":
            ingested_ids.append(rid)
        else:
            skipped += 1
    birdies = ingest_all_18birdies(con, force=force)
    return {"ingested": len(ingested_ids), "skipped": skipped,
            "ingestedIds": ingested_ids, "backfill": birdies}


def main() -> None:
    from .db import connect
    con = connect()
    args = sys.argv[1:]
    force = "--force" in args
    ids = [int(a) for a in args if a.isdigit()]
    if ids:
        load_reference(con)
        for rid in ids:
            print(f"  {rid}: {ingest_round(con, rid, force=force)}")
    else:
        res = ingest_all(con, force=force)
        print(f"ingested={res['ingested']} skipped={res['skipped']}")


if __name__ == "__main__":
    main()
