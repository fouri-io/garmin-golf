"""Canonical loader tests against the hand-built 2-hole fixture raw pair."""

from __future__ import annotations

import pytest

from src.ingest import ingest_round
from tests.conftest import FIXTURE_SCORECARD_ID, FIXTURES

RAW = FIXTURES / "raw"


def test_ingest_counts(ingested_db):
    con = ingested_db
    assert con.execute("SELECT count(*) FROM canon.round").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM canon.hole").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM canon.shot").fetchone()[0] == 6


def test_garmin_shot_id_preserved(ingested_db):
    ids = {r[0] for r in ingested_db.execute("SELECT shot_id FROM canon.shot").fetchall()}
    assert 90000000001 in ids and 90000000004 in ids


def test_round_authoritative_totals(ingested_db):
    strokes, putts, pens = ingested_db.execute(
        "SELECT total_strokes, total_putts, total_penalties FROM canon.round").fetchone()
    assert (strokes, putts, pens) == (9, 4, 1)


def test_hole_par_from_holepars_string(ingested_db):
    rows = dict(ingested_db.execute(
        "SELECT hole_number, par FROM canon.hole ORDER BY hole_number").fetchall())
    assert rows == {1: 4, 2: 3}


def test_par_wraps_modulo_for_nine_as_eighteen(db, tmp_path):
    """A 9-hole layout played twice reuses pars for holes 10-18."""
    import json
    detail = json.loads((RAW / f"scorecard_{FIXTURE_SCORECARD_ID}_detail.json").read_text())
    shots = json.loads((RAW / f"scorecard_{FIXTURE_SCORECARD_ID}_shots.json").read_text())
    sc = detail["scorecardDetails"][0]["scorecard"]
    sc["holes"] = sc["holes"] + [dict(sc["holes"][0], number=3), dict(sc["holes"][1], number=4)]
    raw2 = tmp_path / "raw2"
    raw2.mkdir()
    (raw2 / f"scorecard_{FIXTURE_SCORECARD_ID}_detail.json").write_text(json.dumps(detail))
    (raw2 / f"scorecard_{FIXTURE_SCORECARD_ID}_shots.json").write_text(json.dumps(shots))
    ingest_round(db, FIXTURE_SCORECARD_ID, raw_dir=raw2)
    rows = dict(db.execute("SELECT hole_number, par FROM canon.hole").fetchall())
    assert rows == {1: 4, 2: 3, 3: 4, 4: 3}  # holePars "43" wraps


def test_semicircles_become_degrees(ingested_db):
    lat, lon = ingested_db.execute(
        "SELECT start_lat, start_lon FROM canon.shot WHERE shot_id = 90000000001").fetchone()
    assert lat == pytest.approx(30.507, abs=0.01)
    assert lon == pytest.approx(-97.579, abs=0.01)


def test_stroke_index_from_hole_handicaps(ingested_db):
    rows = dict(ingested_db.execute(
        "SELECT hole_number, stroke_index FROM canon.hole").fetchall())
    assert rows == {1: 1, 2: 2}  # holeHandicaps "0102"


def test_reingest_is_skipped_when_sha_matches(ingested_db):
    assert ingest_round(ingested_db, FIXTURE_SCORECARD_ID, raw_dir=RAW) == "skipped"


def test_force_reingest_keeps_counts_stable(ingested_db):
    assert ingest_round(ingested_db, FIXTURE_SCORECARD_ID, raw_dir=RAW,
                        force=True) == "ingested"
    assert ingested_db.execute("SELECT count(*) FROM canon.shot").fetchone()[0] == 6
    assert ingested_db.execute("SELECT count(*) FROM canon.round").fetchone()[0] == 1
