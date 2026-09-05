"""Annotation loading, effective-context semantics, and context metrics."""

from __future__ import annotations

import json

import pytest

from src.annotate import validate_tags
from src.derive import derive_all
from src.ingest import load_annotations
from tests.conftest import FIXTURE_SCORECARD_ID

STEM = f"2026_06_15_{FIXTURE_SCORECARD_ID}"

TAGS = {
    "tagSchemaVersion": 1,
    "roundId": FIXTURE_SCORECARD_ID,
    "confirmedAt": "2026-09-05T12:00:00-05:00",
    "shots": [
        {"shotId": 90000000001, "hole": 1, "intent": "punch",
         "evaluation": "recovery_success", "note": "punched out of the trees"},
    ],
    "holes": [
        {"hole": 1, "postTeeState": "compromised", "doubleClass": None,
         "preventableEscalation": False},
    ],
    "unmatched": [
        {"hole": 2, "text": "chunked a wedge somewhere in here", "intent": "other"},
    ],
}


@pytest.fixture()
def annotated_db(ingested_db, tmp_path):
    derive_all(ingested_db)
    ann = tmp_path / "annotations"
    ann.mkdir()
    (ann / f"{STEM}.md").write_text("# notes\nPunched out on 1; hole 2 was scrappy.")
    (ann / f"{STEM}.tags.json").write_text(json.dumps(TAGS))
    load_annotations(ingested_db, ann_dir=ann)
    return ingested_db


def test_annotation_rows_loaded(annotated_db):
    con = annotated_db
    assert con.execute("SELECT count(*) FROM annot.round_narrative").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM annot.hole_context").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM annot.annotation_meta").fetchone()[0] == 1
    rows = con.execute("SELECT match_status, count(*) FROM annot.shot_context "
                       "GROUP BY match_status").fetchall()
    assert dict(rows) == {"confirmed": 1, "unmatched": 1}


def test_reload_is_idempotent(annotated_db, tmp_path):
    load_annotations(annotated_db, ann_dir=tmp_path / "annotations")
    assert annotated_db.execute(
        "SELECT count(*) FROM annot.shot_context").fetchone()[0] == 2


def test_effective_context_tagged_shot(annotated_db):
    intent, ev, excl = annotated_db.execute(
        "SELECT intent, evaluation, exclude_from_stock FROM derived.shot_effective_context "
        "WHERE shot_id = 90000000001").fetchone()
    assert (intent, ev, excl) == ("punch", "recovery_success", True)


def test_effective_context_untagged_shot_on_annotated_round_is_normal(annotated_db):
    intent, excl = annotated_db.execute(
        "SELECT intent, exclude_from_stock FROM derived.shot_effective_context "
        "WHERE shot_id = 90000000002").fetchone()
    assert (intent, excl) == ("normal", False)


def test_effective_context_null_on_unannotated_round(ingested_db):
    derive_all(ingested_db)
    intent, annotated = ingested_db.execute(
        "SELECT intent, round_annotated FROM derived.shot_effective_context "
        "WHERE shot_id = 90000000002").fetchone()
    assert intent is None and annotated is False


def test_round_context_metrics(annotated_db):
    row = annotated_db.execute("""
        SELECT tee_states, tee_clean, tee_compromised, recovery_attempts,
               recovery_successes, normal_approaches, normal_approach_greens
        FROM derived.round_context_metrics""").fetchone()
    states, clean, comp, rec_a, rec_s, appr, greens = row
    assert (states, clean, comp) == (1, 0, 1)
    assert (rec_a, rec_s) == (1, 1)
    # Both real approaches (H1 approach + H2 par-3 tee) are untagged -> normal; both
    # found the green. The punch-tagged tee shot is offTee, so it never counts here.
    assert (appr, greens) == (2, 2)


def test_validate_tags_catches_bad_references(ingested_db):
    bad = {"roundId": FIXTURE_SCORECARD_ID,
           "shots": [{"shotId": 123, "hole": 1, "intent": "flop"}],
           "holes": [{"hole": 9, "postTeeState": "great"}]}
    problems = validate_tags(ingested_db, FIXTURE_SCORECARD_ID, bad)
    text = "\n".join(problems)
    assert "shotId 123 not in round" in text
    assert "bad intent" in text
    assert "hole 9 not in round" in text
    assert "bad postTeeState" in text


def test_validate_tags_clean(ingested_db):
    problems = validate_tags(ingested_db, FIXTURE_SCORECARD_ID, TAGS)
    assert problems == []
