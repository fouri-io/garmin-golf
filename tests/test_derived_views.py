"""Derived-view tests: phantom flags, reconciliation, first-putt guard, hole facts.

The fixture round: hole 1 par 4 (tee -> fairway -> approach to green -> putt, plus a
890m phantom transit shot), hole 2 par 3 (tee to green -> putt). Hole 1 scored 5(2),
hole 2 scored 4(2) with a penalty.
"""

from __future__ import annotations

import pytest


def test_phantom_transit_shot_flagged(ingested_db):
    phantom, reason, off_map, conf = ingested_db.execute(
        "SELECT phantom, phantom_reason, off_map, confidence FROM derived.shot_flags "
        "WHERE shot_id = 90000000004").fetchone()
    assert phantom is True
    assert reason == "implausible-distance"   # 890m ≈ 973 yds > 400
    assert off_map is True                    # endpoint lie Unknown
    assert conf == "anomalous"


def test_real_shots_not_flagged(ingested_db):
    n = ingested_db.execute(
        "SELECT count(*) FROM derived.shot_flags WHERE phantom").fetchone()[0]
    assert n == 1


def test_device_auto_confidence_is_inferred(ingested_db):
    # The phantom shot is DEVICE_AUTO but anomalous wins; a clean SENSOR shot is
    # authoritative.
    conf = ingested_db.execute(
        "SELECT confidence FROM derived.shot_flags WHERE shot_id = 90000000001"
    ).fetchone()[0]
    assert conf == "authoritative"


def test_hole_recon(ingested_db):
    rows = {r[0]: r for r in ingested_db.execute(
        "SELECT hole_number, strokes, shots_recorded, phantom_shots, shot_count_delta, "
        "suspect, empty_shot_data FROM derived.hole_recon").fetchall()}
    assert rows[1][1:] == (5, 3, 1, -2, False, False)
    assert rows[2][1:] == (4, 2, 0, -2, False, False)


def test_round_recon_clean_gate(ingested_db):
    shots, phantoms, delta, clean = ingested_db.execute(
        "SELECT shots_recorded, phantom_shots, shot_count_delta, clean "
        "FROM derived.round_recon").fetchone()
    assert (shots, phantoms, delta) == (5, 1, -4)
    assert clean is True  # under-recorded rounds are clean; only over-recording pollutes


def test_first_putt_requires_recorded_putt(ingested_db):
    rows = dict(ingested_db.execute(
        "SELECT hole_number, first_putt_ft FROM derived.hole_first_putt").fetchall())
    assert set(rows) == {1, 2}          # both holes reached green AND recorded a putt
    assert rows[1] > 0
    # first_putt = remaining of the green-reaching shot, in feet (yds * 3)
    remaining = ingested_db.execute(
        "SELECT remaining_yds FROM derived.shot_geom WHERE shot_id = 90000000002"
    ).fetchone()[0]
    assert rows[1] == pytest.approx(round(remaining * 3.0, 1))


def test_first_putt_absent_without_putt_shot(ingested_db):
    # Remove the putt on hole 2: its first_putt row must disappear (Garmin snaps the
    # approach onto the pin on putt-less holes -> false 0 ft).
    ingested_db.execute("DELETE FROM canon.shot WHERE shot_id = 90000000006")
    rows = dict(ingested_db.execute(
        "SELECT hole_number, first_putt_ft FROM derived.hole_first_putt").fetchall())
    assert set(rows) == {1}


def test_hole_facts(ingested_db):
    rows = {r[0]: r for r in ingested_db.execute(
        "SELECT hole_number, gir, scramble_opportunity, scramble_save, double_plus, "
        "score_to_par FROM derived.hole_facts").fetchall()}
    # Hole 1: par 4, strokes 5, putts 2 -> 3 non-putt strokes > 2 -> no GIR, bogey.
    assert rows[1][1:] == (False, True, False, False, 1)
    # Hole 2: par 3, strokes 4, putts 2 -> no GIR, missed save, bogey.
    assert rows[2][1:] == (False, True, False, False, 1)


def test_putting_bands(ingested_db):
    rows = ingested_db.execute(
        "SELECT hole_number, band, made_first FROM derived.putting_bands "
        "ORDER BY hole_number").fetchall()
    assert len(rows) == 2
    assert all(made is False for _, _, made in rows)  # both holes 2-putted
