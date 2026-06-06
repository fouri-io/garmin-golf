"""Orchestrate pulls — ALWAYS dump raw JSON to data/raw/ before any parsing.

The single most important rule (SPEC §9): the raw response hits disk before
parsing, so a server-side change can never cost data already retrieved.

Usage:
    python -m src.pull                 # pull DEFAULT_SCORECARD's summary+detail+shots
    python -m src.pull 364945310       # pull a specific scorecard id
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import garmin_client

RAW_DIR = Path("data/raw")

# The round the user pointed at:
# https://connect.garmin.com/app/golf-shots/.../scorecard/364945310/hole/1
DEFAULT_SCORECARD = 364945310

# Be gentle with the unofficial endpoints (SPEC §10).
PAUSE_SECONDS = 1.5


def dump(obj: Any, name: str) -> Path:
    """Persist a raw API response to data/raw/<name>.json and return the path."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = RAW_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    size = path.stat().st_size
    print(f"  dumped {path}  ({size:,} bytes)")
    return path


def pull_scorecard(api, scorecard_id: int | str) -> None:
    """Pull summary list, one scorecard's detail, and its shots — raw-dumping each."""
    print("[1/3] golf summary (recent rounds)...")
    summaries = garmin_client.get_scorecard_summaries(api)
    dump(summaries, "golf_summary")
    time.sleep(PAUSE_SECONDS)

    print(f"[2/3] scorecard detail for {scorecard_id}...")
    detail = garmin_client.get_scorecard_detail(api, scorecard_id)
    dump(detail, f"scorecard_{scorecard_id}_detail")
    time.sleep(PAUSE_SECONDS)

    print(f"[3/3] shot data for {scorecard_id} (one request per hole)...")
    shots = garmin_client.get_all_shots(api, scorecard_id, pause=PAUSE_SECONDS)
    dump(shots, f"scorecard_{scorecard_id}_shots")


def main() -> None:
    load_dotenv()
    scorecard_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SCORECARD

    print("Logging in (reusing cached tokens if present)...")
    api = garmin_client.login()
    print("Login OK.\n")

    pull_scorecard(api, scorecard_id)
    print("\nDone. Raw responses are in data/raw/ — pausing here for analysis.")


if __name__ == "__main__":
    main()
