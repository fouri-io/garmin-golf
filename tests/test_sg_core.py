"""Unit tests for the pure Strokes Gained math in src/sg_core.py."""

from __future__ import annotations

import json

import pytest

from src.sg_core import Baseline, categorize, interp, shot_sg

CUTS = {"longApproachMinYds": 150, "insideMaxYds": 50, "headlineMaxYds": 100}


# --- interp ---------------------------------------------------------------

TABLE = {0.0: 1.0, 100.0: 3.0, 200.0: 4.0}


def test_interp_below_table_clamps():
    assert interp(TABLE, -5.0) == 1.0


def test_interp_above_table_clamps():
    assert interp(TABLE, 500.0) == 4.0


def test_interp_exact_key():
    assert interp(TABLE, 100.0) == 3.0


def test_interp_linear_between_keys():
    assert interp(TABLE, 50.0) == pytest.approx(2.0)
    assert interp(TABLE, 150.0) == pytest.approx(3.5)


# --- Baseline -------------------------------------------------------------

@pytest.fixture()
def baseline(tmp_path):
    raw = {
        "throughGreen": {
            "tee": {"100": 2.9, "400": 4.0},
            "fairway": {"20": 2.4, "100": 2.8, "200": 3.4},
            "rough": {"20": 2.6, "100": 3.0, "200": 3.7},
            "sand": {"20": 2.7, "100": 3.1, "200": 3.8},
            "recovery": {"20": 3.5, "200": 3.9},
        },
        "putting": {"3": 1.0, "10": 1.6, "30": 2.0, "60": 2.4},
    }
    p = tmp_path / "sg_baseline.json"
    p.write_text(json.dumps(raw))
    return Baseline(p)


def test_expected_green_converts_yards_to_feet(baseline):
    # 10 yards on the green = 30 feet -> putting table at 30
    assert baseline.expected(lie="Green", dist_yds=10.0) == pytest.approx(2.0)


def test_expected_unknown_lie_maps_to_fairway(baseline):
    assert baseline.expected(lie="Unknown", dist_yds=100.0) == \
        baseline.expected(lie="Fairway", dist_yds=100.0)


def test_expected_none_distance_is_none(baseline):
    assert baseline.expected(lie="Fairway", dist_yds=None) is None


def test_expected_putts_uses_feet_directly(baseline):
    assert baseline.expected_putts(10.0) == pytest.approx(1.6)
    assert baseline.expected_putts(20.0) == pytest.approx(1.8)  # midway 10->30


def test_real_baseline_loads_and_is_monotonic():
    base = Baseline()  # config/sg_baseline.json from the repo
    e50 = base.expected(lie="Fairway", dist_yds=50)
    e150 = base.expected(lie="Fairway", dist_yds=150)
    e250 = base.expected(lie="Fairway", dist_yds=250)
    assert e50 < e150 < e250
    assert base.expected_putts(3) < base.expected_putts(30)


# --- categorize -----------------------------------------------------------

def _shot(frm="Fairway", d=None):
    return {"from": frm, "distanceToPinBeforeYds": d}


def test_categorize_green_is_putting():
    assert categorize(_shot("Green", 5), par=4, cuts=CUTS) == "putting"


def test_categorize_par45_tee_is_off_tee_regardless_of_distance():
    assert categorize(_shot("TeeBox", 380), par=4, cuts=CUTS) == "offTee"
    assert categorize(_shot("TeeBox", 520), par=5, cuts=CUTS) == "offTee"


def test_categorize_par3_tee_falls_into_distance_buckets():
    assert categorize(_shot("TeeBox", 165), par=3, cuts=CUTS) == "longApproach"
    assert categorize(_shot("TeeBox", 120), par=3, cuts=CUTS) == "midApproach"


def test_categorize_distance_boundaries():
    assert categorize(_shot(d=150), par=4, cuts=CUTS) == "longApproach"   # >= 150
    assert categorize(_shot(d=149.9), par=4, cuts=CUTS) == "midApproach"
    assert categorize(_shot(d=50.1), par=4, cuts=CUTS) == "midApproach"   # > 50
    assert categorize(_shot(d=50), par=4, cuts=CUTS) == "inside50"        # <= 50
    assert categorize(_shot(d=None), par=4, cuts=CUTS) == "midApproach"   # unknown distance


# --- shot_sg --------------------------------------------------------------

def test_shot_sg_arithmetic(baseline):
    # Fairway 100 (E=2.8) -> Green 10yds=30ft (E=2.0): SG = 2.8 - 2.0 - 1 = -0.2
    sg = shot_sg(baseline, from_lie="Fairway", to_lie="Green",
                 dist_before_yds=100.0, dist_after_yds=10.0)
    assert sg == pytest.approx(-0.2)


def test_shot_sg_gains_when_shot_beats_baseline(baseline):
    # Tee 400 (E=4.0) -> Fairway 100 (E=2.8): SG = 4.0 - 2.8 - 1 = +0.2
    sg = shot_sg(baseline, from_lie="TeeBox", to_lie="Fairway",
                 dist_before_yds=400.0, dist_after_yds=100.0)
    assert sg == pytest.approx(0.2)


def test_shot_sg_none_when_endpoint_unknown(baseline):
    assert shot_sg(baseline, from_lie="Fairway", to_lie="Green",
                   dist_before_yds=None, dist_after_yds=10.0) is None
    assert shot_sg(baseline, from_lie="Fairway", to_lie="Green",
                   dist_before_yds=100.0, dist_after_yds=None) is None
