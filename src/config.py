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


def scoring_zone_max_yds() -> float:
    """Shots going for the green within this distance are 'shortGame' (wedge/pitch zone);
    beyond it they're full 'approach'. Player-tunable in config/analysis.json."""
    return _analysis_config().get("strokesGained", {}).get("scoringZoneMaxYds", 90)
