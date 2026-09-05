"""Recompute the Python-written derived tables: shot geometry, per-shot SG, and
per-hole putting expectations.

Everything here is disposable: derived tables are rebuilt from canon whenever the
underlying rounds change (ingest returns the changed ids) or wholesale on rebuild.
Geometry reuses src/geo.py and SG reuses src/sg_core.py verbatim — the same code
paths the legacy parser used, so the numbers match the committed round documents.

Usage:
    python -m src.derive             # recompute for all rounds
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .config import sg_distance_cuts
from .constants import METERS_TO_YARDS
from .geo import shot_geometry
from .sg_core import Baseline, categorize, shot_sg

RAW_DIR = Path("data/raw")

# Bump when SG derivation logic changes; rows in derived.shot_sg carry it so a
# stale-version scan is one query away.
SG_VERSION = 1


def derive_geom(con: duckdb.DuckDBPyConnection, round_ids: list[int] | None = None) -> int:
    """(Re)compute derived.shot_geom for the given rounds (None = all). Returns rows."""
    where, params = ("WHERE s.round_id IN (SELECT unnest(?))", [round_ids]) \
        if round_ids is not None else ("", [])
    rows = con.execute(f"""
        SELECT s.shot_id, s.meters,
               s.start_lat, s.start_lon, s.end_lat, s.end_lon,
               h.pin_lat, h.pin_lon
        FROM canon.shot s
        JOIN canon.hole h ON h.round_id = s.round_id AND h.hole_number = s.hole_number
        {where}
        """, params).fetchall()

    con.execute("BEGIN")
    if round_ids is None:
        con.execute("DELETE FROM derived.shot_geom")
    else:
        con.execute("DELETE FROM derived.shot_geom WHERE shot_id IN "
                    "(SELECT shot_id FROM canon.shot WHERE round_id IN (SELECT unnest(?)))",
                    [round_ids])
    n = 0
    for shot_id, meters, slat, slon, elat, elon, plat, plon in rows:
        yards = round(meters * METERS_TO_YARDS, 1) if meters is not None else None
        geom = None
        if None not in (slat, slon, elat, elon, plat, plon):
            geom = shot_geometry((slat, slon), (elat, elon), (plat, plon))
        con.execute("INSERT INTO derived.shot_geom VALUES (?,?,?,?,?,?,?)", [
            shot_id, yards,
            geom["toPinBeforeYds"] if geom else None,
            geom["remainingYds"] if geom else None,
            geom["range"] if geom else None,
            geom["side"] if geom else None,
            geom["lateralYds"] if geom else None,
        ])
        n += 1
    con.execute("COMMIT")
    return n


def _round_filter(round_ids: list[int] | None, column: str) -> tuple[str, list]:
    if round_ids is None:
        return "", []
    return f"AND {column} IN (SELECT unnest(?))", [round_ids]


def derive_sg(con: duckdb.DuckDBPyConnection, round_ids: list[int] | None = None) -> int:
    """(Re)compute derived.shot_sg for non-phantom shots. Putts get category 'putting'
    with NULL strokes_gained (putting SG is count-based, see derive_putting)."""
    base = Baseline()
    cuts = sg_distance_cuts()
    where, params = _round_filter(round_ids, "s.round_id")
    rows = con.execute(f"""
        SELECT s.shot_id, s.round_id, s.start_lie, s.end_lie, h.par,
               g.to_pin_before_yds, g.remaining_yds
        FROM canon.shot s
        JOIN canon.hole h ON h.round_id = s.round_id AND h.hole_number = s.hole_number
        JOIN derived.shot_flags f ON f.shot_id = s.shot_id
        LEFT JOIN derived.shot_geom g ON g.shot_id = s.shot_id
        WHERE NOT f.phantom {where}
        """, params).fetchall()

    con.execute("BEGIN")
    if round_ids is None:
        con.execute("DELETE FROM derived.shot_sg")
    else:
        con.execute("DELETE FROM derived.shot_sg WHERE shot_id IN "
                    "(SELECT shot_id FROM canon.shot WHERE round_id IN (SELECT unnest(?)))",
                    [round_ids])
    n = 0
    for shot_id, _rid, from_lie, to_lie, par, d_before, d_after in rows:
        shot = {"from": from_lie, "distanceToPinBeforeYds": d_before}
        cat = categorize(shot, par, cuts)
        sg = None
        if cat != "putting":
            sg = shot_sg(base, from_lie=from_lie, to_lie=to_lie,
                         dist_before_yds=d_before, dist_after_yds=d_after)
        con.execute("INSERT INTO derived.shot_sg VALUES (?,?,?,?)",
                    [shot_id, cat, sg, SG_VERSION])
        n += 1
    con.execute("COMMIT")
    return n


def derive_putting(con: duckdb.DuckDBPyConnection,
                   round_ids: list[int] | None = None) -> int:
    """(Re)compute derived.hole_putting: expected putts from the first-putt distance,
    on holes where that distance is trustworthy (see derived.hole_first_putt)."""
    base = Baseline()
    where, params = _round_filter(round_ids, "fp.round_id")
    rows = con.execute(f"""
        SELECT fp.round_id, fp.hole_number, fp.first_putt_ft, h.putts
        FROM derived.hole_first_putt fp
        JOIN canon.hole h ON h.round_id = fp.round_id AND h.hole_number = fp.hole_number
        WHERE h.putts >= 1 {where}
        """, params).fetchall()
    con.execute("BEGIN")
    if round_ids is None:
        con.execute("DELETE FROM derived.hole_putting")
    else:
        con.execute("DELETE FROM derived.hole_putting WHERE round_id IN (SELECT unnest(?))",
                    [round_ids])
    for rid, hole, fp_ft, _putts in rows:
        con.execute("INSERT INTO derived.hole_putting VALUES (?,?,?,?)",
                    [rid, hole, fp_ft, base.expected_putts(fp_ft)])
    con.execute("COMMIT")
    return len(rows)


def derive_all(con: duckdb.DuckDBPyConnection, round_ids: list[int] | None = None) -> dict:
    """Recompute every Python-written derived table for the given rounds (None = all)."""
    return {
        "shotGeom": derive_geom(con, round_ids),
        "shotSg": derive_sg(con, round_ids),
        "holePutting": derive_putting(con, round_ids),
    }


def main() -> None:
    from .db import connect
    con = connect()
    res = derive_all(con)
    print(f"derived: {res}")


if __name__ == "__main__":
    main()
