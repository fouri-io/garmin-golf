"""Benchmark comparator (Broadie tables) + focus-card adherence plumbing."""

from __future__ import annotations

from src.benchmarks import (build_comparison, climb_split, load_cfg, measure, next_group,
                            placement, render_md, user_group)
from src.coach import extract_focus
from src.derive import derive_all

REPORT = """**Overall** — fine.

**Trend read** — flat.

**Next-round focus**
- Kill the tee-ball penalties: 4 of 5 doubles started off the tee.
- Scoring zone: In50 -13.9 today.

Some closing sentence.
"""


def test_user_group_by_score_range():
    cfg = load_cfg()
    assert user_group(80.0, cfg) == "Am1"
    assert user_group(96.6, cfg) == "Am2"
    assert user_group(97.0, cfg) == "Am2"
    assert user_group(105.0, cfg) == "Am3"
    assert user_group(150.0, cfg) == "Am3"


def test_next_group_ladder():
    assert next_group("Am3") == "Am2"
    assert next_group("Am2") == "Am1"
    assert next_group("Am1") is None


def test_placement_higher_is_better():
    groups = {"Am3": 25, "Am2": 46, "Am1": 63}
    assert placement(20, groups, "higher") == "below Am3"
    assert placement(26, groups, "higher") == "between Am3 and Am2 (nearer Am3)"
    assert placement(45, groups, "higher") == "between Am3 and Am2 (nearer Am2)"
    assert placement(50, groups, "higher") == "between Am2 and Am1 (nearer Am2)"
    assert placement(70, groups, "higher") == "at/above Am1"


def test_placement_lower_is_better():
    groups = {"Am3": 9.3, "Am2": 4.1, "Am1": 1.9}
    assert placement(12.0, groups, "lower") == "below Am3"
    assert placement(8.8, groups, "lower") == "between Am3 and Am2 (nearer Am3)"
    assert placement(1.0, groups, "lower") == "at/above Am1"


def test_measure_runs_on_fixture(ingested_db):
    derive_all(ingested_db)
    m = measure(ingested_db)
    # 2-hole fixture: sparse buckets must degrade to n=0 / None, never crash
    for k in ("approach100to150Fwy", "short20to60Fwy"):
        assert m[k]["n"] >= 0
        if m[k]["n"] == 0:
            assert m[k]["greenPct"] is None
    assert m["awful"]["nRounds"] >= 0
    assert "onePutt50PctFt" in m["putting"]


def test_build_comparison_and_md(ingested_db):
    derive_all(ingested_db)
    doc = build_comparison(ingested_db)
    assert doc["yourGroup"] in ("Am1", "Am2", "Am3")
    assert doc["source"]["citation"].startswith("Broadie")
    md = render_md(doc)
    assert "BENCHMARK READ" in md
    assert "Broadie" in md
    # interpretability bar: the Am1/Am2/Am3 dataset shorthand must never reach the
    # player-facing brief — brackets are named by score range in plain words
    assert "Am1" not in md and "Am2" not in md and "Am3" not in md
    assert "your bracket" in md
    for line in md.splitlines():
        if line.startswith("- "):
            assert "YOU" in line


def test_step_up_strokes_match_table4():
    # Am2 -> Am1 from the published shot-value table: 11.5 total strokes
    cfg = load_cfg()
    t4 = cfg["table4"]
    assert round(t4["total"]["Am1"] - t4["total"]["Am2"], 1) == 11.5
    assert round(t4["longGame"]["Am1"] - t4["longGame"]["Am2"], 1) == 7.1


def test_bracket_assignment_levels_tee_rating():
    # A raw average earned on easy tees must not flatter the bracket (Colby's catch):
    # 96.6 off 67.2-rated tees levels to ~101.4 on a standard course -> the 98-120
    # bracket, even though the raw number reads as 84-97.
    cfg = load_cfg()
    std = cfg["standardCourseRating"]
    raw, rating = 96.6, 67.2
    adj = raw - rating + std
    assert user_group(raw, cfg) == "Am2"
    assert user_group(adj, cfg) == "Am3"


def test_climb_split_directions():
    # higher-is-better behind, lower-is-better ahead — both directions must sort right,
    # and 'ahead' entries must carry the next-level target
    doc = {"yourGroup": "Am3", "nextGroup": "Am2", "metrics": [
        {"label": "green %", "yours": 15, "groups": {"Am3": 25, "Am2": 34},
         "betterIs": "higher"},
        {"label": "awful shots", "yours": 8.8, "groups": {"Am3": 9.3, "Am2": 4.1},
         "betterIs": "lower"},
        {"label": "no data", "yours": None, "groups": {"Am3": 1}, "betterIs": "higher"},
    ]}
    behind, ahead = climb_split(doc)
    assert behind == ["green % (15 vs bracket 25)"]
    assert ahead == ["awful shots (8.8 -> next level 4.1)"]


def test_extract_focus_parses_bullets():
    bullets = extract_focus(REPORT)
    assert len(bullets) == 2
    assert bullets[0].startswith("Kill the tee-ball penalties")
    assert "In50" in bullets[1]


def test_extract_focus_absent_section():
    assert extract_focus("**Overall** — fine.\n\n**Trend read** — flat.") == []
