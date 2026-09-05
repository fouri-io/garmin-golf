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
it, --no-coach suppresses). --publish copies the site to config publish.targetDir.

--push does three things, and exits 2 if any of them fails to land:
  1. ARCHIVE — commits data/processed + site/index.html in THIS repo and pushes. The
     deploy target only ever receives index.html, so without this the processed rounds
     and coach reports exist nowhere but the laptop (data/raw is gitignored too).
  2. DEPLOY — commits+pushes the built site to the publish repo, whose Action syncs it
     to S3. Note this is a *different repo*; pushing this one deploys nothing.
  3. VERIFY — fetches publish.verifyUrl until it serves the bytes we just built. A green
     push only proves the Action was triggered; if its AWS credentials have expired the
     push still succeeds while the site quietly serves the previous build.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from . import analyze, coach, db, derive, ingest, parse, progress, pull, site
from .config import publish_target, publish_verify_url

SITE_FILE = Path("site/index.html")

# Paths this repo auto-commits as the round archive. Deliberately NOT src/ or config/:
# update.sh runs unattended, and a blanket `git add -A` would sweep half-finished code
# edits into a robot commit. Code stays a human decision.
ARCHIVE_PATHS = ["data/processed", "data/raw", "data/annotations", "site/index.html"]

DEPLOY_POLL_SECONDS = 480   # Action + S3 sync + CloudFront invalidation, generously
DEPLOY_POLL_INTERVAL = 20


def _tracked_ids() -> list[int]:
    """Scorecard ids we currently keep processed docs for (the analysis set)."""
    ids = []
    for f in sorted(glob.glob("data/processed/rounds/*.json")):
        ids.append(json.loads(Path(f).read_text())["scorecardId"])
    return ids


def _git(root: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                          check=check)


def _archive_message(root: str) -> str:
    """Describe what's staged: '<n> rounds through <date>', else an aggregate rebuild."""
    staged = _git(root, "diff", "--cached", "--name-only").stdout.split()
    stems = sorted({Path(p).stem for p in staged
                    if p.startswith("data/processed/rounds/")})
    if not stems:
        return "data: rebuild aggregates + site"
    n, newest = len(stems), stems[-1][:10].replace("_", "-")
    return f"data: sync {n} round{'' if n == 1 else 's'} through {newest}"


def _archive(push: bool) -> bool:
    """Commit (and optionally push) the regenerated data + built site in THIS repo.

    The deploy target only ever receives index.html, so without this the processed
    rounds live nowhere but the laptop — data/raw is gitignored, so a disk loss takes
    the coach reports and parsed rounds with it. Returns False on a real failure.
    """
    root = _git(".", "rev-parse", "--show-toplevel").stdout.strip()
    _git(root, "add", "--", *ARCHIVE_PATHS)
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("  archive: nothing new to commit")
        return True
    msg = _archive_message(root)
    if _git(root, "commit", "-m", msg, check=False).returncode != 0:
        print("  archive FAILED: commit rejected")
        return False
    print(f"  archived — {msg}")
    if not push:
        return True
    # Only this machine writes here, but rebase anyway so a push can't wedge on a
    # remote that moved (e.g. a commit made from another checkout).
    _git(root, "fetch", "origin", check=False)
    if _git(root, "pull", "--rebase", "--autostash", check=False).returncode != 0:
        print("  archive FAILED: rebase onto origin hit a conflict — resolve by hand")
        return False
    r = _git(root, "push", check=False)
    if r.returncode != 0:
        print(f"  archive FAILED: push rejected — {r.stderr.strip().splitlines()[-1:]}")
        return False
    print(f"  archive pushed -> {root}")
    return True


def _verify_deploy(expect: bytes) -> bool:
    """Poll the public URL until it serves the bytes we just built.

    A successful git push only proves the deploy Action was TRIGGERED. If its AWS
    credentials have expired (or Actions is disabled), the push still succeeds and the
    site silently keeps serving the previous build — which is exactly how a run can
    report a green deploy while the dashboard stays days stale.
    """
    url = publish_verify_url()
    if not url:
        print("  deploy verify skipped — no publish.verifyUrl in config/analysis.json")
        return True
    want = hashlib.sha256(expect).hexdigest()
    deadline = time.time() + DEPLOY_POLL_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(
                url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if hashlib.sha256(resp.read()).hexdigest() == want:
                    print(f"  deploy verified — live matches build "
                          f"(after {attempt} check{'' if attempt == 1 else 's'})")
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"  deploy check {attempt}: {type(e).__name__}")
        if time.time() + DEPLOY_POLL_INTERVAL >= deadline:
            print(f"  DEPLOY NOT VERIFIED — {url} still serving a different build after "
                  f"{DEPLOY_POLL_SECONDS}s. The push landed but the Action did not "
                  f"deploy it; check the repo's Actions tab (expired AWS secrets?).")
            return False
        time.sleep(DEPLOY_POLL_INTERVAL)


def _publish(push: bool) -> str:
    """Copy (and with push=True commit+push) the build to the deploy repo.

    Returns "skipped" | "copied" | "pushed" | "current" — "current" meaning the remote
    already carries this exact build. Both "pushed" and "current" warrant a deploy
    check: if an earlier run pushed but its Action failed, the remote matches our build
    while the live site is still stale, and only fetching the URL can tell them apart.
    """
    target = publish_target()
    if not target:
        print("  publish skipped — no publish.targetDir in config/analysis.json")
        return "skipped"
    target.mkdir(parents=True, exist_ok=True)
    dst = target / "index.html"

    if not push:
        shutil.copy(SITE_FILE, dst)
        print(f"  published -> {dst}")
        return "copied"

    root = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    branch = subprocess.run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    rel = str(dst.resolve().relative_to(root))

    # The published file is regenerated every run, and another machine (e.g. the
    # server) may have pushed newer builds since this clone last synced. Sync to the
    # remote tip first, lay our fresh build on top, and retry if a push races us — so
    # a stale local clone can never wedge the deploy. NOTE: reset --hard discards any
    # uncommitted local changes in the publish repo; it is meant as a deploy target.
    for attempt in range(3):
        subprocess.run(["git", "-C", root, "fetch", "origin", branch], check=True)
        subprocess.run(["git", "-C", root, "reset", "--hard", f"origin/{branch}"], check=True)
        shutil.copy(SITE_FILE, dst)
        print(f"  published -> {dst}")
        subprocess.run(["git", "-C", root, "add", rel], check=True)
        if subprocess.run(["git", "-C", root, "diff", "--cached", "--quiet"]).returncode == 0:
            print("  remote already carries this build — no push needed")
            return "current"
        subprocess.run(["git", "-C", root, "commit", "-m", "update golf dashboard"], check=True)
        if subprocess.run(["git", "-C", root, "push"]).returncode == 0:
            print(f"  pushed {root} — deploy triggered")
            return "pushed"
        print(f"  push rejected (attempt {attempt + 1}/3) — re-syncing with remote")
    raise RuntimeError(f"git push to {root} failed after 3 attempts")


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
                    help="publish AND git commit+push that repo (auto-deploys), commit "
                         "the round archive here, and verify the deploy went live")
    ap.add_argument("--coach", action="store_true",
                    help="generate an AI coach report for the latest round")
    ap.add_argument("--no-coach", action="store_true",
                    help="skip the coach even when new rounds were pulled")
    ap.add_argument("--archive", action="store_true",
                    help="commit data/processed + site here even without --push")
    ap.add_argument("--no-archive", action="store_true",
                    help="skip the round-archive commit that --push normally makes")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the post-push check that the deploy actually went live")
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

    # Sync the DuckDB spine: incremental ingest (sha-gated per round), then re-derive
    # just the changed rounds. A fresh/empty derived layer triggers a full derive.
    print("Syncing database...")
    con = db.connect()
    res = ingest.ingest_all(con)
    if res["ingestedIds"]:
        derive.derive_all(con, res["ingestedIds"])
        print(f"  db: ingested {res['ingested']} rounds, derived updates applied")
    elif con.execute("SELECT count(*) FROM derived.shot_sg").fetchone()[0] == 0:
        derive.derive_all(con)
        print("  db: derived layer rebuilt")
    else:
        print(f"  db: up to date ({res['skipped']} rounds unchanged)")

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

    # Archive BEFORE deploying: if the deploy verification then fails, the rounds are
    # already safely committed rather than held hostage to a broken Action.
    ok = True
    if (a.push or a.archive) and not a.no_archive:
        ok &= _archive(push=a.push)

    if a.publish or a.push:
        state = _publish(push=a.push)
        if a.push and state in ("pushed", "current") and not a.no_verify:
            ok &= _verify_deploy(SITE_FILE.read_bytes())

    print("Done." if ok else "Done — WITH FAILURES (see above).")
    if not ok:
        # Distinct from 1 (a crash): the pipeline ran, but something didn't land.
        raise SystemExit(2)


if __name__ == "__main__":
    main()
