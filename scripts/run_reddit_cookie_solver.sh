#!/bin/zsh
# Launchd entrypoint for the local, headless Reddit cookie solver.

set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
profile="${REDDIT_SOLVER_PROFILE:-reddit-crawler}"
cookie_name="${REDDIT_SOLVER_COOKIE_NAME:-reddit_session}"
keychain_service="${REDDIT_SOLVER_KEYCHAIN_SERVICE:-panicradar-reddit-solver-token}"
keychain_account="${REDDIT_SOLVER_KEYCHAIN_ACCOUNT:-reddit-crawler}"

export REDDIT_COOKIE_SOLVER_TOKEN="$(
  /usr/bin/security find-generic-password \
    -a "$keychain_account" \
    -s "$keychain_service" \
    -w
)"

if [[ ${#REDDIT_COOKIE_SOLVER_TOKEN} -lt 32 ]]; then
  print -u2 "Reddit solver token is missing or too short in the macOS Keychain."
  exit 1
fi

exec /usr/bin/env python3 "$script_dir/reddit_cookie_solver.py" \
  --profile "$profile" \
  --cookie-name "$cookie_name"
