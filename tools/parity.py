"""Cutover parity gate: DB-derived values vs the legacy round documents.

Compares every round in data/processed/rounds/ against the DuckDB derived layer:
  - EXACT: authoritative score fields, reconciliation counts, per-hole GIR /
    scrambling / first-putt distance, putting counts.
  - ±0.01: per-round SG by bucket, sg0to100 (rounding differences only).

Run after `python -m src.db rebuild` (or any ingest+derive):
    python -m tools.parity
Exit 0 = clean; exit 1 = mismatches (printed).
"""

from __future__ import annotations

import glob
import json

import duckdb

TOL = 0.011

SG_COLS = {"offTee": "sg_off_tee", "longApproach": "sg_long_approach",
           "midApproach": "sg_mid_approach", "inside50": "sg_inside50",
           "putting": "sg_putting"}


def check() -> list[str]:
    con = duckdb.connect("data/turn.duckdb", read_only=True)
    problems: list[str] = []
    docs = sorted(glob.glob("data/processed/rounds/*.json"))

    for f in docs:
        d = json.load(open(f))
        rid = d["scorecardId"]

        row = con.execute("""
            SELECT r.total_strokes, r.total_putts, r.total_penalties,
                   rr.shots_recorded, rr.phantom_shots, rr.shot_count_delta
            FROM canon.round r JOIN derived.round_recon rr USING (round_id)
            WHERE r.round_id = ?""", [rid]).fetchone()
        if row is None:
            problems.append(f"{rid}: missing from DB")
            continue
        want = (d["score"]["strokes"], d["score"]["putts"], d["score"]["penalties"],
                d["reconciliation"]["recordedShots"], d["reconciliation"]["phantomShots"],
                d["reconciliation"]["shotCountDelta"])
        if tuple(row) != want:
            problems.append(f"{rid}: round facts DB={tuple(row)} doc={want}")

        db_holes = {r[0]: r[1:] for r in con.execute("""
            SELECT hole_number, gir, scramble_opportunity, scramble_save, first_putt_ft
            FROM derived.hole_facts WHERE round_id = ?""", [rid]).fetchall()}
        for h in d["holes"]:
            want_h = (h["gir"], h["scrambleOpportunity"], h["scrambleSave"],
                      h["firstPuttDistanceFt"])
            if db_holes.get(h["number"]) != want_h:
                problems.append(f"{rid} H{h['number']}: DB={db_holes.get(h['number'])} "
                                f"doc={want_h}")

        sg_row = con.execute("""
            SELECT sg_off_tee, sg_long_approach, sg_mid_approach, sg_inside50,
                   sg_putting, sg_0_100, categorized_shots,
                   putt_holes_measured, putts_covered
            FROM derived.round_sg WHERE round_id = ?""", [rid]).fetchone()
        doc_sg = d["strokesGained"]
        db_by = dict(zip(SG_COLS, sg_row[:5]))
        for cat, col in SG_COLS.items():
            if abs(round(db_by[cat], 2) - doc_sg["byCategory"][cat]) > TOL:
                problems.append(f"{rid} SG {cat}: DB={round(db_by[cat], 2)} "
                                f"doc={doc_sg['byCategory'][cat]}")
        if abs(round(sg_row[5], 2) - doc_sg["sg0to100"]) > TOL:
            problems.append(f"{rid} sg0to100: DB={round(sg_row[5], 2)} "
                            f"doc={doc_sg['sg0to100']}")
        if sg_row[6] != doc_sg["categorizedShots"]:
            problems.append(f"{rid} categorizedShots: DB={sg_row[6]} "
                            f"doc={doc_sg['categorizedShots']}")
        if (sg_row[7], sg_row[8]) != (doc_sg["putting"]["holesMeasured"],
                                      doc_sg["putting"]["puttsCovered"]):
            problems.append(f"{rid} putting coverage: DB={sg_row[7:9]} "
                            f"doc=({doc_sg['putting']['holesMeasured']}, "
                            f"{doc_sg['putting']['puttsCovered']})")

    print(f"parity: {len(docs)} rounds checked, {len(problems)} problems")
    for p in problems:
        print("  " + p)
    return problems


if __name__ == "__main__":
    raise SystemExit(1 if check() else 0)
