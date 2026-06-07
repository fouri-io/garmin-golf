#!/usr/bin/env bash
# Post-round update + deploy, for invoking from a server/Telegram process executor.
# Incremental sync (pulls only NEW rounds), runs the AI coach on them, rebuilds the
# dashboard, and pushes -> auto-deploys to colbyward.io.
#
# Point your Telegram command at the ABSOLUTE path of this script, e.g.:
#   /Users/colby/dev/garmin-golf/update.sh
#
# Notes / requirements (must hold for this to succeed unattended):
#   - Run on the HOME machine (Garmin rate-limits/blocks datacenter IPs).
#   - .env present here with GARMIN_EMAIL/PASSWORD + ANTHROPIC_API_KEY.
#   - A valid Garmin token cache (~/.garminconnect); if it has expired and Garmin
#     wants MFA, an unattended run will fail — refresh it by running once interactively.
#   - git push to the colbyward.io repo needs SSH key auth available to this process.

set -uo pipefail
cd "$(dirname "$0")" || exit 1

./.venv/bin/python -m src.update --push 2>&1 | tee -a data/update.log
