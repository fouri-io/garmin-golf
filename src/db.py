"""The DuckDB spine — connect, bootstrap the schema, rebuild from committed files.

data/turn.duckdb is a durable materialized index over the committed raw files: it
persists between runs and ingests incrementally, but it never holds unique state —
every write originates in a file (raw Garmin JSON, annotation files, config). It is
therefore gitignored and fully rebuildable:

    python -m src.db rebuild     # drop + re-ingest everything (schema/loader changes)
    python -m src.db status      # what's in the database
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_PATH = Path("data/turn.duckdb")
SCHEMA_DIR = Path("sql/schema")


def bootstrap(con: duckdb.DuckDBPyConnection) -> None:
    """Execute sql/schema/*.sql in filename order. Tables are IF NOT EXISTS, views are
    CREATE OR REPLACE — so a definition change deploys on the next connect."""
    for f in sorted(SCHEMA_DIR.glob("*.sql")):
        con.execute(f.read_text())


def connect(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the database and ensure the schema is current."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    bootstrap(con)
    return con


def rebuild(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Drop the database file and rebuild it from the committed inputs (raw JSON,
    annotations, config). The escape hatch for schema or loader changes."""
    from . import derive, ingest  # local: avoid import cycles at module load

    path.unlink(missing_ok=True)
    Path(str(path) + ".wal").unlink(missing_ok=True)
    con = connect(path)
    ingest.ingest_all(con, force=True)
    derive.derive_all(con)
    return con


def status(con: duckdb.DuckDBPyConnection) -> dict:
    counts = {}
    for label, q in {
        "rounds": "SELECT count(*) FROM canon.round",
        "holes": "SELECT count(*) FROM canon.hole",
        "shots": "SELECT count(*) FROM canon.shot",
        "shot_geom": "SELECT count(*) FROM derived.shot_geom",
        "shot_sg": "SELECT count(*) FROM derived.shot_sg",
        "annotated_rounds": "SELECT count(*) FROM annot.round_narrative",
    }.items():
        counts[label] = con.execute(q).fetchone()[0]
    span = con.execute(
        "SELECT min(round_date), max(round_date) FROM canon.round").fetchone()
    counts["dateRange"] = f"{span[0]} .. {span[1]}" if span[0] else "empty"
    return counts


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "rebuild":
        con = rebuild()
        print("Rebuilt", DB_PATH)
    elif cmd == "status":
        con = connect()
    else:
        raise SystemExit(f"unknown command: {cmd} (use: rebuild | status)")
    for k, v in status(con).items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
