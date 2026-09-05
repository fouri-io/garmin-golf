"""SG derivation and round-metric view tests over the fixture round."""

from __future__ import annotations

import pytest

from src.derive import derive_all
from src.sg_core import Baseline


@pytest.fixture()
def derived_db(ingested_db):
    derive_all(ingested_db)
    return ingested_db


def test_phantom_shot_gets_no_sg_row(derived_db):
    n = derived_db.execute(
        "SELECT count(*) FROM derived.shot_sg WHERE shot_id = 90000000004").fetchone()[0]
    assert n == 0
    assert derived_db.execute("SELECT count(*) FROM derived.shot_sg").fetchone()[0] == 5


def test_putts_categorized_putting_with_null_sg(derived_db):
    rows = derived_db.execute(
        "SELECT sg_category, strokes_gained FROM derived.shot_sg "
        "WHERE shot_id IN (90000000003, 90000000006)").fetchall()
    assert all(cat == "putting" and sg is None for cat, sg in rows)


def test_tee_shot_categories(derived_db):
    cat_h1 = derived_db.execute(
        "SELECT sg_category FROM derived.shot_sg WHERE shot_id = 90000000001").fetchone()[0]
    assert cat_h1 == "offTee"      # par-4 tee shot
    cat_h2 = derived_db.execute(
        "SELECT sg_category FROM derived.shot_sg WHERE shot_id = 90000000005").fetchone()[0]
    assert cat_h2 in ("midApproach", "longApproach", "inside50")  # par-3 tee: by distance


def test_graded_shots_have_sg(derived_db):
    rows = derived_db.execute(
        "SELECT strokes_gained FROM derived.shot_sg "
        "WHERE sg_category != 'putting'").fetchall()
    assert rows and all(sg is not None for (sg,) in rows)


def test_hole_putting_matches_independent_baseline(derived_db):
    """SQL-side hole_putting must equal a from-scratch sg_core computation."""
    base = Baseline()
    rows = derived_db.execute("""
        SELECT hp.first_putt_ft, hp.expected_putts, h.putts
        FROM derived.hole_putting hp
        JOIN canon.hole h USING (round_id, hole_number)""").fetchall()
    assert len(rows) == 2
    for fp_ft, expected, _putts in rows:
        assert expected == pytest.approx(base.expected_putts(fp_ft))


def test_round_sg_putting_is_count_based(derived_db):
    sg_putting = derived_db.execute(
        "SELECT sg_putting FROM derived.round_sg").fetchone()[0]
    want = derived_db.execute("""
        SELECT sum(hp.expected_putts - h.putts)
        FROM derived.hole_putting hp
        JOIN canon.hole h USING (round_id, hole_number)""").fetchone()[0]
    assert sg_putting == pytest.approx(want)


def test_round_metrics_counts(derived_db):
    row = derived_db.execute("""
        SELECT holes, total_strokes, total_putts, total_penalties, doubles_plus,
               scramble_opps, scramble_saves, three_putt_holes,
               putts_3_6 + putts_6_10 + long_first_putts AS banded
        FROM derived.round_metrics""").fetchone()
    holes, strokes, putts, pens, dbl, opps, saves, three, banded = row
    assert (holes, strokes, putts, pens) == (2, 9, 4, 1)
    assert (dbl, opps, saves, three) == (0, 2, 0, 0)
    assert banded <= 2  # both first putts land in some band (unless short bands absorb)
