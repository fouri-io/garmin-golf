#!/usr/bin/env bash
# Post-round update + deploy, for invoking from a server/Telegram process executor.
# Incremental sync (pulls only NEW rounds), runs the AI coach on them, rebuilds the
# dashboard, and pushes -> auto-deploys to colbyward.io.
#
# Point your Telegram command at the ABSOLUTE path of this script, e.g.:
#   /Users/colby/dev/garmin-golf/update.sh
# The LAST line of output is a one-line, Telegram-friendly summary (relay `tail -1`).
#
# Requirements for an unattended run:
#   - Run on the HOME machine (Garmin rate-limits/blocks datacenter IPs).
#   - .env present with GARMIN_EMAIL/PASSWORD + ANTHROPIC_API_KEY.
#   - Valid Garmin token cache (~/.garminconnect); if expired and MFA is required,
#     an unattended run fails — refresh by running once interactively.
#   - SSH key auth available to this process for the git push.

set -uo pipefail
cd "$(dirname "$0")" || { echo "SUMMARY: ⚠️ The Turn update FAILED — bad working dir"; exit 1; }

out="$(./.venv/bin/python -m src.update --push 2>&1)"; rc=$?
printf '%s\n' "$out" | tee -a data/update.log >/dev/null   # full log (not to stdout)

if [ "$rc" -ne 0 ]; then
  summary="⚠️ The Turn update FAILED (exit $rc) — see data/update.log"
else
  pulled="$(printf '%s' "$out" | grep -oE 'pulled=[0-9]+' | tail -1 | grep -oE '[0-9]+')"
  failed="$(printf '%s' "$out" | grep -oE 'failed=[0-9]+' | tail -1 | grep -oE '[0-9]+')"
  pulled="${pulled:-0}"; failed="${failed:-0}"
  coached="$(printf '%s' "$out" | grep -c 'coach report' || true)"
  deployed="$(printf '%s' "$out" | grep -c 'deploying' || true)"
  if [ "$pulled" -gt 0 ]; then
    rd="$(printf '%s' "$out" | grep -oE '[0-9]{4}_[0-9]{2}_[0-9]{2}' | tail -1 | tr '_' '-')"
    word="round"; [ "$pulled" -gt 1 ] && word="rounds"
    msg="$pulled new $word"; [ -n "$rd" ] && msg="$msg ($rd)"
    [ "$coached" -gt 0 ] && msg="$msg · coached"
    [ "$deployed" -gt 0 ] && msg="$msg · deployed"
    summary="✅ The Turn · $msg → colbyward.io/golf"
  else
    summary="✅ The Turn · no new rounds · rebuilt + deployed → colbyward.io/golf"
  fi
  [ "$failed" -gt 0 ] && summary="$summary  ⚠ $failed failed"
fi

echo "$summary" | tee -a data/update.log   # final line -> stdout (and log)
