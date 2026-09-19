"""Approach Ladder tests — the binning/zone vocabulary, the fixture round, and the
shape rules that keep every published rate next to its sample size.

The fixture round (2 holes, id 999000111) is dated well outside a live 90-day window,
so every build() here pins `as_of` or widens `windowDays` — the ladder is date-relative
by design and the fixture must stay visible regardless of when the suite runs.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.constants import LEAVE_CLASSES
from src.ladder import (detail_bin, display_bin, in_band, in_ring, in_zone, leave_class,
                        putter_next, scope_suffix, stat, window_label)

EDGES = [60, 80, 100, 125, 150, 170]
BAND = [60, 170]
CLASS_EDGES = [15, 25]


def test_in_band_is_inclusive_both_ends():
    assert in_band(60, BAND) and in_band(170, BAND)
    assert not in_band(59.9, BAND) and not in_band(170.1, BAND)
    assert in_band(None, BAND) is False


def test_display_bin_half_open_with_closed_top():
    assert display_bin(60, EDGES) == "60-80"
    assert display_bin(79.9, EDGES) == "60-80"
    assert display_bin(80, EDGES) == "80-100"
    assert display_bin(124.9, EDGES) == "100-125"
    assert display_bin(125, EDGES) == "125-150"
    assert display_bin(169.9, EDGES) == "150-170"
    assert display_bin(170.0, EDGES) == "150-170"      # the closing edge is never dropped
    assert display_bin(59.9, EDGES) is None
    assert display_bin(170.1, EDGES) is None
    assert display_bin(None, EDGES) is None


def test_detail_bin_walks_the_band_in_fixed_widths():
    assert detail_bin(60, 10, BAND) == "60-70"
    assert detail_bin(119.9, 10, BAND) == "110-120"
    assert detail_bin(120, 10, BAND) == "120-130"
    assert detail_bin(170, 10, BAND) == "160-170"
    assert detail_bin(59.9, 10, BAND) is None


def test_in_zone_is_the_locked_definition():
    assert in_zone("Green", 40.0, False, 15) is True       # on the green beats distance
    assert in_zone("Rough", 14.9, False, 15) is True
    assert in_zone("Rough", 15.0, False, 15) is True       # the radius is inclusive
    assert in_zone("Rough", 15.1, False, 15) is False
    assert in_zone("Rough", None, True, 15) is True        # holed
    # Unmeasurable: counted in coverage, excluded from the rate — never False.
    assert in_zone("Rough", None, False, 15) is None


def test_in_ring_needs_a_measured_leave():
    assert in_ring(9.9, 10) is True
    assert in_ring(10.0, 10) is True
    assert in_ring(10.1, 10) is False
    assert in_ring(None, 10) is None


def test_putter_next_keys_on_club_not_shot_type():
    assert putter_next(23) is True
    assert putter_next(19) is False
    assert putter_next(0) is None          # unattributed club
    assert putter_next(None) is None       # hole ended


def test_leave_class_precedence():
    # 1. holed — nothing left to finish
    assert leave_class("Green", 0.0, True, CLASS_EDGES, holed=True) is None
    # 2/3. putter next, on the green vs off it
    assert leave_class("Green", 12.0, True, CLASS_EDGES) == "greenPutted"
    assert leave_class("Fringe", 12.0, True, CLASS_EDGES) == "fringePutted"
    # 4. green with an unattributed next club still counts as green — without this
    #    fallback those shots would mislabel as "chipped".
    assert leave_class("Green", 12.0, None, CLASS_EDGES) == "greenPutted"
    assert leave_class("Green", 12.0, False, CLASS_EDGES) == "greenPutted"
    # 5. distance classes off the green
    assert leave_class("Rough", 15.0, False, CLASS_EDGES) == "chipped"
    assert leave_class("Rough", 25.0, False, CLASS_EDGES) == "pitch"
    assert leave_class("Rough", 25.1, False, CLASS_EDGES) == "long"
    # 6. unmeasurable
    assert leave_class("Rough", None, False, CLASS_EDGES) is None


def test_stat_always_carries_its_denominator():
    assert stat(0, 0) == {"pct": None, "n": 0}
    assert stat(3, 4)["pct"] == 75
    assert stat(3, 4)["n"] == 4


def test_window_and_scope_labels():
    assert window_label(90) == "last 3 mo"
    assert window_label(30) == "last month"
    assert window_label(45) == "last 45 days"
    s = scope_suffix(BAND, 90, 363)
    assert s == "60–170y · last 3 mo · n=363"


# ------------------------------------------------------------------ the fixture round
# Hole 1: 312y tee shot -> 126y approach to the green (6.8y leave), 2 putts, 5 strokes.
# Hole 2: 117y tee shot to the green (8.7y leave), 2 putts, 4 strokes. Both approaches
# are in the band; the tee shot on hole 1 is not.

FIXTURE_AS_OF = date(2026, 6, 16)          # the fixture round is dated 2026-06-15


def _fixture_doc(con, **over):
    from src.ladder import build
    return build(write=False, as_of=FIXTURE_AS_OF, cfg=over or None, con=con)


def test_fixture_ladder_population(ingested_db):
    doc = _fixture_doc(ingested_db)
    assert doc["coverage"]["approaches"] == 2          # the 312y tee shot is out of band
    assert doc["headline"]["zone"] == {"pct": 100, "n": 2}
    rated = {b["key"]: b["zone"]["n"] for b in doc["bins"] if b["zone"]["n"]}
    assert rated == {"100-125": 1, "125-150": 1}
    detail = {d["key"] for b in doc["bins"] for d in b["detail"] if d["zone"]["n"]}
    assert detail == {"110-120", "120-130"}
    assert all(b["provisional"] for b in doc["bins"])  # every bin is under minBinN
    assert doc["coverage"]["pinCoverage"] == {"pct": 100, "n": 2}


def test_fixture_anchors_and_club_rows(ingested_db):
    doc = _fixture_doc(ingested_db)
    anchors = {c["key"]: c for c in doc["payoffAnchors"]["classes"]}
    # Both approaches finished on the green; strokes to finish = 5-2 and 4-1... the
    # authoritative scorecard leaves 3 strokes after each.
    assert anchors["greenPutted"]["strokes"] == 3.0
    assert anchors["greenPutted"]["n"] == 2
    assert anchors["greenPutted"]["provisional"] is True      # under minAnchorN
    assert anchors["long"]["strokes"] is None and anchors["long"]["n"] == 0
    assert doc["payoffAnchors"]["excludedOverRecorded"] == 0
    # Both fixture clubs are unmapped (club_type 12) and below the per-club floor.
    assert all(b["clubs"] == [] for b in doc["bins"])
    assert sum(b["clubsBelowMin"]["shots"] for b in doc["bins"]) == 2


def test_fixture_out_of_band_shot_is_absent(ingested_db):
    doc = _fixture_doc(ingested_db)
    assert all(r is not None for r in [doc["headline"]["zone"]["n"]])
    binned = sum(b["zone"]["n"] for b in doc["bins"])
    assert binned == 2                     # the 312y stroke lands in no bin at all


def test_teebox_artifact_is_excluded_and_counted(ingested_db):
    # Re-point the hole-2 approach at a tee box: the next-tee GPS artifact shot_flags
    # does not catch. It must leave the ladder and show up in the coverage badge.
    ingested_db.execute("UPDATE canon.shot SET end_lie = 'TeeBox' "
                        "WHERE shot_id = 90000000005")
    doc = _fixture_doc(ingested_db)
    assert doc["coverage"]["eligible"] == 2
    assert doc["coverage"]["excludedTeeBoxArtifact"] == 1
    assert doc["coverage"]["approaches"] == 1
    assert sum(b["zone"]["n"] for b in doc["bins"]) == 1


def test_window_scopes_every_stat(ingested_db):
    from src.ladder import build
    doc = build(write=False, as_of=date(2026, 9, 19), con=ingested_db)
    assert doc["coverage"]["approaches"] == 0      # fixture round is ~96 days back
    assert doc["headline"]["zone"] == {"pct": None, "n": 0}
    wide = build(write=False, as_of=date(2026, 9, 19), cfg={"windowDays": 3650},
                 con=ingested_db)
    assert wide["coverage"]["approaches"] == 2


def test_round_samples_marks_untested_bins(ingested_db):
    from src.ladder import render_round_samples, round_samples
    s = round_samples(ingested_db, 999000111)
    filled = {k: v for k, v in s["bins"].items() if v}
    assert set(filled) == {"100-125", "125-150"}
    assert s["zone"] == {"pct": 100, "n": 2}
    txt = render_round_samples(s)
    assert txt.count("bin untested") == 3
    assert "ZONE" in txt


# ------------------------------------------------------------------- structural rules

def _walk(node, path="doc"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_no_bare_rates_anywhere_in_the_document(ingested_db):
    """The coverage mechanism is a SHAPE, not a convention: any dict that publishes a
    percentage publishes the n it came from, so no consumer can render one without it."""
    doc = _fixture_doc(ingested_db)
    for path, node in _walk(doc):
        pcts = [k for k in node if k == "pct" or k.endswith("Pct")]
        if pcts:
            assert "n" in node, f"{path} publishes {pcts} with no n"


def test_the_metric_is_never_called_gir(ingested_db):
    """Garmin's GIR stat is separate and unchanged; this feature never borrows the name
    (ADR #19) — not in the module, not in the document."""
    import re

    import src.ladder as ladder_mod
    src = Path(ladder_mod.__file__).read_text()
    assert not re.search(r"\bGIR\b", src)
    doc = json.dumps(_fixture_doc(ingested_db))
    assert not re.search(r"\bGIR\b", doc)
    # ...and not in the new card either. Scoped to the NEW markup/JS: Garmin's GIR row
    # elsewhere on the dashboard is untouched and must stay.
    site = Path("src/site.py").read_text()
    card = site[site.index('<div class="card" id="ladcard">'):
                site.index('<div class="card"><h2>What changed')]
    js = site[site.index("/* ---- Approach Ladder"):site.index("function drawCone(I){")]
    band = site[site.index("function renderGreenZoneBand"):site.index("function drawBars(")]
    assert not re.search(r"\bGIR\b", card + js + band)


def test_coach_prompt_carries_the_ladder_slot():
    """The coach gets the ladder as a deterministic block, and is told never to call it
    GIR. No LLM call is involved in checking this."""
    from src import coach
    assert "{benchmark}{ladder}" in coach.PROMPT
    assert "APPROACH LADDER" in coach.SYSTEM
    assert "NEVER call this GIR" in coach.SYSTEM
    assert coach._ladder_block.__doc__            # the block exists and is documented


# ----------------------------------------------------------------------- real data

@pytest.mark.skipif(not Path("data/turn.duckdb").exists(),
                    reason="no database — run `python -m src.db rebuild` first")
def test_build_against_real_data():
    from src.ladder import build
    doc = build(write=False)
    cfg = doc["config"]
    assert len(doc["bins"]) == len(cfg["displayBinEdges"]) - 1
    assert sum(len(b["detail"]) for b in doc["bins"]) == 11
    assert 300 <= doc["headline"]["zone"]["n"] <= 450
    assert 0 <= doc["headline"]["zone"]["pct"] <= 100
    assert doc["coverage"]["approaches"] + doc["coverage"]["excludedTeeBoxArtifact"] \
        == doc["coverage"]["eligible"]
    assert doc["coverage"]["pinCoverage"]["pct"] == 100
    anchors = {c["key"]: c["strokes"] for c in doc["payoffAnchors"]["classes"]}
    assert set(anchors) == set(LEAVE_CLASSES)
    assert all(v is not None for v in anchors.values())
    # Leaving it closer costs fewer strokes to finish — the whole point of the zone.
    assert anchors["greenPutted"] < anchors["pitch"] < anchors["long"]


@pytest.mark.skipif(not Path("data/turn.duckdb").exists(),
                    reason="no database — run `python -m src.db rebuild` first")
def test_preserved_findings_reproduce_in_shape():
    """The spec's three findings are ACCEPTANCE EVIDENCE for the generators: assert the
    shape and the direction, never the exact percentages (the window moves)."""
    from src.ladder import build
    doc = build(write=False)
    found = {f["key"] for f in doc["findings"]}
    assert {"reach-swing", "cliff", "best-window"} <= found
    reach = [f for f in doc["findings"] if f["key"] == "reach-swing"]
    assert all(f["club"] and f["n"] >= doc["config"]["minClubRowN"] for f in reach)
    cliff = next(f for f in doc["findings"] if f["key"] == "cliff")
    assert cliff["binKey"] == "150-170"          # the cliff starts at 150, not 160
    best = next(f for f in doc["findings"] if f["key"] == "best-window")
    assert best["binKey"] == "100-110"           # 100y is still his best window
    assert all(0 < f["magnitude"] for f in doc["findings"])
