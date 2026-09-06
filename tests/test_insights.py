"""Insights engine: cone math, trend windows, ranking guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.insights import (CONE_MIN, CONE_PROVISIONAL, CONE_WINDOW, _conf,
                          _mid_iron_miss, _pct, _trend, cone_series)


def test_pct_bounds_and_interpolation():
    vals = [10, 20, 30, 40, 50]
    assert _pct(vals, 0) == 10
    assert _pct(vals, 1) == 50
    assert _pct(vals, 0.5) == 30
    assert _pct(vals, 0.25) == 20
    assert _pct([7], 0.8) == 7


def test_cone_series_waits_for_min_rounds():
    assert cone_series([30.0] * (CONE_PROVISIONAL - 1)) == []
    s = cone_series([30.0] * CONE_PROVISIONAL)
    assert len(s) == 1 and s[0]["p20"] == s[0]["p80"] == 30.0
    assert s[0]["full"] is False
    s = cone_series([30.0] * CONE_MIN)
    assert s[-1]["full"] is True and not s[-2]["full"]


def test_cone_series_rolls_and_narrows():
    # 30 rounds trending 40 -> 20: the window should slide and percentiles drop
    vals = [40 - i * 0.7 for i in range(30)]
    s = cone_series(vals)
    assert s[0]["i"] == CONE_PROVISIONAL - 1 and s[-1]["i"] == 29
    assert s[-1]["p50"] < s[0]["p50"]
    assert all(p["p20"] <= p["p50"] <= p["p80"] for p in s)
    assert [p["full"] for p in s] == [False] * (CONE_MIN - CONE_PROVISIONAL) + \
        [True] * (30 - CONE_MIN + 1)
    assert len(s) == 30 - CONE_PROVISIONAL + 1
    w = vals[30 - CONE_WINDOW:30]
    assert s[-1]["p50"] == round(_pct(w, .5), 1)


def test_conf_tiers():
    assert _conf(25) == (1.0, "High confidence")
    assert _conf(12)[1] == "Moderate confidence"
    assert _conf(4)[1] == "Emerging signal"


def test_trend_needs_two_full_windows():
    rounds = [{"m": 1.0} for _ in range(19)]
    assert _trend(rounds, "m") is None
    rounds = [{"m": 4.0}] * 10 + [{"m": 2.0}] * 10
    t = _trend(rounds, "m")
    assert t == {"now": 2.0, "prev": 4.0, "delta": -2.0}


def test_mid_iron_miss_guards_small_samples():
    clubs = [{"clubTypeId": 16, "dispersion": {"approachShots": 10, "leftPct": 20,
                                               "rightPct": 60, "shortPct": 80}}]
    assert _mid_iron_miss(clubs) is None      # < 20 shots
    clubs.append({"clubTypeId": 17, "dispersion": {"approachShots": 30, "leftPct": 30,
                                                   "rightPct": 50, "shortPct": 70}})
    m = _mid_iron_miss(clubs)
    assert m["n"] == 40 and 50 <= m["rightPct"] <= 53 and m["shortPct"] == 72
    # non-mid-irons never pollute the family
    clubs.append({"clubTypeId": 1, "dispersion": {"approachShots": 500, "leftPct": 0,
                                                  "rightPct": 100, "shortPct": 100}})
    assert _mid_iron_miss(clubs)["n"] == 40


@pytest.mark.skipif(not Path("data/turn.duckdb").exists(),
                    reason="no database — run `python -m src.db rebuild` first")
def test_build_against_real_data():
    from src.insights import build
    doc = build(write=False)
    assert doc["current"] and doc["start"]
    assert doc["current"]["ceiling"] <= doc["current"]["median"] <= doc["current"]["floor"]
    assert 1 <= len(doc["insights"]) <= 6
    assert all(i["score"] >= 0 and i["confidence"] for i in doc["insights"])
    assert 1 <= len(doc["priorities"]) <= 3
    assert doc["floorDrivers"] and all(d["verdict"] in ("improving", "flat", "worse")
                                       for d in doc["floorDrivers"])
    assert len(doc["benchmarks"]) >= 3
    for b in doc["benchmarks"]:
        assert b["modeled"] and b["ceiling"] < b["median"] < b["floor"]
    hs = [b["handicap"] for b in doc["benchmarks"]]
    assert hs == sorted(hs, reverse=True) and hs[-1] == 0
    scratch = doc["benchmarks"][-1]
    assert 3 <= scratch["median"] <= 5      # a real scratch's typical round: ~+4 over rating
    b20 = doc["benchmarks"][0]
    assert b20["floor"] - b20["ceiling"] > scratch["floor"] - scratch["ceiling"]


def test_adjusted_gap_shrinks_nine_hole_noise():
    from src.insights import adjusted_gap
    import random
    rng = random.Random(7)
    # stable golfer, sigma ~4, but half the rounds are noisy doubled 9-holers
    rounds = []
    for i in range(CONE_WINDOW):
        nine = i % 2 == 0
        noise = rng.gauss(0, 4 * (2 ** 0.5)) if nine else rng.gauss(0, 4)
        rounds.append({"over18": 25 + noise, "holes": 9 if nine else 18})
    raw = [r["over18"] for r in rounds]
    raw_gap = _pct(raw, .8) - _pct(raw, .2)
    adj = adjusted_gap(rounds, CONE_WINDOW - 1)
    assert adj is not None and adj < raw_gap          # correction shrinks the spread
    assert adjusted_gap(rounds[:CONE_WINDOW - 1], CONE_WINDOW - 2) is None  # needs full window
