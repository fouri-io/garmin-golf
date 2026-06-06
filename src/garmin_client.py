"""THE isolated API layer — the ONLY module that touches unofficial Garmin endpoints.

Design rules (SPEC §2, §9, §10):
  - All unofficial Garmin Connect calls live here and nowhere else.
  - A breakage here must be a contained problem, not a data-loss event.
  - Callers persist raw responses to disk *before* parsing (see pull.py).

Golf method names confirmed against garminconnect 0.3.5 via src/introspect.py:
  - get_golf_summary(start=0, limit=100) -> list[dict]   # scorecard summary list
  - get_golf_scorecard(scorecard_id) -> dict             # per-hole detail
  - get_golf_shot_data(scorecard_id, hole_numbers) -> dict  # shot-by-shot
Re-run `python -m src.introspect` after any library upgrade to reconfirm.
"""

from __future__ import annotations

import getpass
import os
import time
from collections.abc import Callable, Iterable

from garminconnect import Garmin


def _default_mfa_prompt() -> str:
    """Prompt for an MFA code. Reads GARMIN_MFA from the env first (so a run can be
    fed a code non-interactively), else falls back to an interactive prompt."""
    return os.environ.get("GARMIN_MFA") or getpass.getpass("MFA code: ")


def login(
    email: str | None = None,
    password: str | None = None,
    prompt_mfa: Callable[[], str] | None = None,
) -> Garmin:
    """Create an authenticated Garmin client, reusing the cached token store if present.

    Credentials come from explicit args or env vars (GARMIN_EMAIL / GARMIN_PASSWORD).
    Passing a tokenstore path to ``api.login()`` makes the library both *load* cached
    tokens (if present — no creds/MFA needed) and *dump* fresh tokens automatically
    after a new login. The store lives under ~/.garminconnect/ (or $GARMINTOKENS).
    MFA, if the account enforces it, is resolved via ``prompt_mfa``.
    """
    email = email or os.environ.get("GARMIN_EMAIL")
    password = password or os.environ.get("GARMIN_PASSWORD")
    tokenstore = os.environ.get("GARMINTOKENS", os.path.expanduser("~/.garminconnect"))

    api = Garmin(email, password, prompt_mfa=prompt_mfa or _default_mfa_prompt)
    api.login(tokenstore)  # loads cached tokens if present, else logs in and caches
    return api


# --- golf wrappers (confirmed against garminconnect 0.3.5) -----------------------


def get_scorecard_summaries(api: Garmin, start: int = 0, limit: int = 100) -> list[dict]:
    """Recent rounds, summary level. The scorecard ID field keys the detail/shot calls."""
    return api.get_golf_summary(start=start, limit=limit)


def get_scorecard_detail(api: Garmin, scorecard_id: int | str) -> dict:
    """Per-hole detail for one scorecard."""
    return api.get_golf_scorecard(scorecard_id)


def get_shot_hole(api: Garmin, scorecard_id: int | str, hole: int) -> dict:
    """Shot data for a SINGLE hole.

    The shot endpoint rejects comma-separated multi-hole requests
    (400 'Invalid hole-numbers'), so callers fetch one hole at a time.
    """
    return api.get_golf_shot_data(scorecard_id, hole_numbers=str(hole))


def get_all_shots(
    api: Garmin,
    scorecard_id: int | str,
    holes: Iterable[int] = range(1, 19),
    pause: float = 1.5,
) -> dict:
    """Fetch shots for every hole, one request per hole (gentle — SPEC §10).

    Returns a raw, loss-free structure: each hole's untouched response is kept under
    ``perHole``. Merging/normalizing is parse.py's job, not this layer's.
    """
    per_hole: list[dict] = []
    for hole in holes:
        resp = get_shot_hole(api, scorecard_id, hole)
        per_hole.append({"hole": hole, "response": resp})
        time.sleep(pause)
    return {"scorecardId": scorecard_id, "perHole": per_hole}
