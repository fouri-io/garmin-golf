"""Shared test fixtures.

Tests run from the repo root (pytest testpaths=["tests"]); modules under src/ resolve
paths like config/sg_baseline.json relative to the cwd, so keep it that way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_SCORECARD_ID = 999000111


@pytest.fixture()
def fixture_detail() -> dict:
    return json.loads((FIXTURES / "raw" / f"scorecard_{FIXTURE_SCORECARD_ID}_detail.json")
                      .read_text())


@pytest.fixture()
def fixture_shots() -> dict:
    return json.loads((FIXTURES / "raw" / f"scorecard_{FIXTURE_SCORECARD_ID}_shots.json")
                      .read_text())
