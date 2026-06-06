"""Shared config loaders (analysis window, etc.)."""

from __future__ import annotations

import json
from pathlib import Path

ANALYSIS_CONFIG = Path("config/analysis.json")
_EPOCH = "0000-01-01"  # include everything if no cutoff configured


def analysis_start_date() -> str:
    """ISO date (YYYY-MM-DD); rounds before it are excluded from pulls and analysis."""
    if ANALYSIS_CONFIG.exists():
        return json.loads(ANALYSIS_CONFIG.read_text()).get("analysisStartDate", _EPOCH)
    return _EPOCH
