"""One-command pipeline: sync new rounds -> parse -> analyze -> progress -> coach -> site,
with optional publish/deploy. The everyday command — no round id needed.

    python -m src.update                 # SYNC: pull only NEW rounds (local cache), rebuild
    python -m src.update --push          # ...and deploy (the post-round one-liner)
    python -m src.update --no-pull       # rebuild only, no network (offline)
    python -m src.update 365394854       # pull just this one round
    python -m src.update --all           # force re-pull every real round (ignore the cache)
    python -m src.update --reparse       # re-parse all tracked rounds (apply config changes)

Default is an incremental sync: local raw is the cache, so only rounds you haven't pulled
hit the network. The coach runs automatically when new rounds are pulled (--coach forces
it, --no-coach suppresses). --publish copies the site to config publish.targetDir; --push
also commits+pushes that repo (auto-deploys via its Action).
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from . import analyze, coach, parse, progress, pull, site
from .config import publish_target

SITE_FILE = Path("site/index.html")


def _tracked_ids() -> list[int]:
    """Scorecard ids we currently keep processed docs for (the analysis set)."""
    ids = []
    for f in sorted(glob.glob("data/processed/rounds/*.json")):
        ids.append(json.loads(Path(f).read_text())["scorecardId"])
    return ids


def _publish(push: bool) -> None:
    target = publish_target()
    if not target:
        print("  publish skipped — no publish.targetDir in config/analysis.json")
        return
    target.mkdir(parents=True, exist_ok=True)
    dst = target / "index.html"
    shutil.copy(SITE_FILE, dst)
    print(f"  published -> {dst}")
    if not push:
        return
    root = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    rel = str(dst.resolve().relative_to(root))
    subprocess.run(["git", "-C", root, "add", rel], check=True)
    if subprocess.run(["git", "-C", root, "diff", "--cached", "--quiet"]).returncode == 0:
        print("  nothing changed — skipping push")
        return
    subprocess.run(["git", "-C", root, "commit", "-m", "update golf dashboard"], check=True)
    subprocess.run(["git", "-C", root, "push"], check=True)
    print(f"  pushed {root} — deploying")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m src.update",
        description="Default: incrementally sync NEW rounds from Garmin (local raw is the "
                    "cache — only rounds you haven't pulled hit the network), then rebuild "
                    "the dashboard. No scorecard id needed.")
    ap.add_argument("scorecard", nargs="?", type=int, help="pull just this one round id")
    ap.add_argument("--no-pull", action="store_true",
                    help="rebuild only from local data; no network (offline)")
    ap.add_argument("--all", action="store_true",
                    help="force re-pull EVERY real round, ignoring the local cache")
    ap.add_argument("--reparse", action="store_true",
                    help="re-parse all tracked rounds (apply parser/config changes)")
    ap.add_argument("--publish", action="store_true", help="copy built site to publish.targetDir")
    ap.add_argument("--push", action="store_true",
                    help="publish AND git commit+push that repo (auto-deploys)")
    ap.add_argument("--coach", action="store_true",
                    help="generate an AI coach report for the latest round")
    ap.add_argument("--no-coach", action="store_true",
                    help="skip the coach even when new rounds were pulled")
    a = ap.parse_args()

    pulled_new = 0
    if not a.no_pull:
        load_dotenv()
        print("Logging in...")
        api = pull.garmin_client.login()
        if a.scorecard:
            pull.pull_scorecard(api, a.scorecard)
            parse.parse_scorecard(a.scorecard)
            pulled_new = 1
        else:
            # Incremental sync: skip_existing=True pulls only rounds not already cached.
            # --all forces a full re-pull.
            res = pull.pull_all(api, skip_existing=not a.all)
            pulled_new = res["pulled"]

    if a.reparse:
        ids = _tracked_ids()
        for sid in ids:
            parse.parse_scorecard(sid)
        print(f"re-parsed {len(ids)} tracked rounds")

    print("Building aggregates...")
    analyze.build_club_stats()
    progress.build()

    # Coach runs before site so its report is inlined. Default: when new rounds were
    # pulled (and not suppressed); always when --coach is given.
    if a.coach or (pulled_new and not a.no_coach):
        print("AI coach...")
        coach.coach_round()

    out = site.build()
    print(f"  site -> {out}")

    if a.publish or a.push:
        _publish(push=a.push)
    print("Done.")


if __name__ == "__main__":
    main()
