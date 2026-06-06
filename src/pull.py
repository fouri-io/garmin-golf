"""Orchestrate pulls — ALWAYS dump raw JSON to data/raw/ before any parsing.

The single most important rule (SPEC §9): the raw response hits disk before
parsing, so a server-side change can never cost data already retrieved.

Usage:
    python -m src.pull                 # pull DEFAULT_SCORECARD's summary+detail+shots
    python -m src.pull 364945310       # pull a specific scorecard id
    python -m src.pull --all           # pull every REAL round (skips SIMULATION), parse each
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
from .config import analysis_start_date

RAW_DIR = Path("data/raw")

# The round the user pointed at:
# https://connect.garmin.com/app/golf-shots/.../scorecard/364945310/hole/1
DEFAULT_SCORECARD = 364945310

# Be gentle with the unofficial endpoints (SPEC §10).
PAUSE_SECONDS = 1.5

# Garmin simulator rounds are not real golf — exclude from bulk pulls.
EXCLUDE_ROUND_TYPES = {"SIMULATION"}


def dump(obj: Any, name: str) -> Path:
    """Persist a raw API response to data/raw/<name>.json and return the path."""
    os.makedirs(RAW_DIR, exist_ok=True)
    path = RAW_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    size = path.stat().st_size
    print(f"  dumped {path}  ({size:,} bytes)")
    return path


def _raw_exists(scorecard_id: int | str) -> bool:
    return ((RAW_DIR / f"scorecard_{scorecard_id}_detail.json").exists()
            and (RAW_DIR / f"scorecard_{scorecard_id}_shots.json").exists())


def pull_summary(api) -> list[dict]:
    """Pull and persist the recent-rounds summary list."""
    print("golf summary (recent rounds)...")
    summaries = garmin_client.get_scorecard_summaries(api)
    dump(summaries, "golf_summary")
    return summaries


def pull_one(api, scorecard_id: int | str) -> None:
    """Pull one scorecard's detail + per-hole shots, raw-dumping each."""
    detail = garmin_client.get_scorecard_detail(api, scorecard_id)
    dump(detail, f"scorecard_{scorecard_id}_detail")
    time.sleep(PAUSE_SECONDS)
    shots = garmin_client.get_all_shots(api, scorecard_id, pause=PAUSE_SECONDS)
    dump(shots, f"scorecard_{scorecard_id}_shots")


def pull_scorecard(api, scorecard_id: int | str) -> None:
    """Pull the summary list plus a single scorecard's detail and shots."""
    pull_summary(api)
    time.sleep(PAUSE_SECONDS)
    print(f"scorecard {scorecard_id} detail + shots...")
    pull_one(api, scorecard_id)


def _summary_records(summaries: list[dict] | dict) -> list[dict]:
    """get_golf_summary returns {..., 'scorecardSummaries': [...]}; tolerate either shape."""
    if isinstance(summaries, dict):
        return summaries.get("scorecardSummaries", [])
    return summaries


def real_round_ids(summaries: list[dict] | dict, since_date: str | None = None) -> list[int]:
    """Scorecard ids for real rounds, oldest first.

    Excludes simulator rounds, and (if ``since_date`` is given) rounds that started
    before it — older rounds predate the current sensor/club setup (see config/analysis.json).
    """
    records = _summary_records(summaries)
    real = [r for r in records if r.get("roundType") not in EXCLUDE_ROUND_TYPES]
    if since_date:
        real = [r for r in real if (r.get("startTime") or "")[:10] >= since_date]
    return [r["id"] for r in sorted(real, key=lambda r: r["startTime"])]


def pull_all(api, *, skip_existing: bool = True) -> None:
    """Pull every real round, parse each into a round document. Idempotent and gentle:
    already-pulled rounds are skipped so a re-run resumes where it left off."""
    from .parse import parse_scorecard  # local import: parse reads only from data/raw

    summaries = pull_summary(api)
    since = analysis_start_date()
    ids = real_round_ids(summaries, since_date=since)
    n_real_all = len(real_round_ids(summaries))
    print(f"\n{len(ids)} rounds to pull (>= {since}; excluding SIMULATION and "
          f"{n_real_all - len(ids)} pre-cutoff rounds).\n")

    pulled = skipped = failed = 0
    for i, scorecard_id in enumerate(ids, 1):
        if skip_existing and _raw_exists(scorecard_id):
            print(f"[{i}/{len(ids)}] {scorecard_id} already pulled — skipping")
            parse_scorecard(scorecard_id)  # ensure processed doc is fresh
            skipped += 1
            continue
        print(f"[{i}/{len(ids)}] pulling {scorecard_id}...")
        try:
            time.sleep(PAUSE_SECONDS)
            pull_one(api, scorecard_id)
            parse_scorecard(scorecard_id)
            pulled += 1
        except Exception as e:  # noqa: BLE001 — one bad round shouldn't abort the batch
            print(f"  FAILED {scorecard_id}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\nDone. pulled={pulled} skipped={skipped} failed={failed}")


def main() -> None:
    load_dotenv()
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    print("Logging in (reusing cached tokens if present)...")
    api = garmin_client.login()
    print("Login OK.\n")

    if arg == "--all":
        pull_all(api)
    else:
        pull_scorecard(api, int(arg) if arg else DEFAULT_SCORECARD)
        print("\nDone. Raw responses are in data/raw/.")


if __name__ == "__main__":
    main()
