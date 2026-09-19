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


def publish_target() -> Path | None:
    """Directory `update --publish` copies the built site into (e.g. the colbyward.io
    /golf folder), or None if not configured."""
    p = (_analysis_config().get("publish") or {}).get("targetDir")
    return Path(p).expanduser() if p else None


def publish_verify_url() -> str | None:
    """Public URL of the deployed dashboard. `update --push` fetches it after pushing to
    confirm the deploy Action actually landed the build (a successful git push only means
    the Action was *triggered*). None disables verification."""
    return (_analysis_config().get("publish") or {}).get("verifyUrl")


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


_LADDER_DEFAULTS = {"windowDays": 90, "bandYds": [60, 170],
                    "displayBinEdges": [60, 80, 100, 125, 150, 170],
                    "detailBinWidthYds": 10, "zoneRadiusYds": 15, "ringYds": [10, 15],
                    "leaveClassEdgesYds": [15, 25], "excludeEndLie": ["TeeBox"],
                    "minClubRowN": 5, "minBinN": 8, "minAnchorN": 8}


def approach_ladder() -> dict:
    """Approach Ladder / Green Zone tunables (window, bin edges, radii, coverage floors).
    Defaults inline so a missing config block never breaks the pipeline."""
    cfg = dict(_LADDER_DEFAULTS)
    cfg.update({k: v for k, v in (_analysis_config().get("approachLadder") or {}).items()
                if not k.startswith("_")})
    return cfg
