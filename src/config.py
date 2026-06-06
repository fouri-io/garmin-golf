"""Shared config loaders (analysis window, etc.)."""

from __future__ import annotations

import json
from pathlib import Path

ANALYSIS_CONFIG = Path("config/analysis.json")
_EPOCH = "0000-01-01"  # include everything if no cutoff configured


def _analysis_config() -> dict:
    return json.loads(ANALYSIS_CONFIG.read_text()) if ANALYSIS_CONFIG.exists() else {}


def analysis_start_date() -> str:
    """ISO date (YYYY-MM-DD); rounds before it are excluded from pulls and analysis."""
    return _analysis_config().get("analysisStartDate", _EPOCH)


def sg_distance_cuts() -> dict:
    """Distance cuts (yards) for the SG approach buckets and the 0-100 headline metric.
    Player-tunable in config/analysis.json."""
    sg = _analysis_config().get("strokesGained", {})
    return {
        "longApproachMinYds": sg.get("longApproachMinYds", 150),
        "insideMaxYds": sg.get("insideMaxYds", 50),
        "headlineMaxYds": sg.get("headlineMaxYds", 100),
    }


_DEFAULT_WEIGHTS = {"offTee": 0.18, "longApproach": 0.20, "midApproach": 0.20,
                    "inside50": 0.24, "putting": 0.18}


def sg_target() -> dict:
    """Target-handicap baseline config (handicap + per-bucket weight distribution)."""
    sg = _analysis_config().get("strokesGained", {})
    return {
        "targetHandicap": sg.get("targetHandicap", 15),
        "weights": sg.get("handicapBucketWeights", _DEFAULT_WEIGHTS),
    }
