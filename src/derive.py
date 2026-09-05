"""Recompute the Python-written derived tables (geometry now; SG in Phase 2).

Everything here is disposable: derived tables are rebuilt from canon whenever the
underlying rounds change (ingest returns the changed ids) or wholesale on rebuild.
Geometry reuses src/geo.py verbatim — the same code path the legacy parser used, so
the numbers match the committed round documents exactly.

Usage:
    python -m src.derive             # recompute for all rounds
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .constants import METERS_TO_YARDS
from .geo import shot_geometry

RAW_DIR = Path("data/raw")


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


def derive_all(con: duckdb.DuckDBPyConnection, round_ids: list[int] | None = None) -> dict:
    """Recompute every Python-written derived table for the given rounds (None = all)."""
    return {"shotGeom": derive_geom(con, round_ids)}


def main() -> None:
    from .db import connect
    con = connect()
    res = derive_all(con)
    print(f"derived: {res}")


if __name__ == "__main__":
    main()
