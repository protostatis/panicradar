#!/bin/bash
# Fetch trending_today.json from prod EC2 to local machine
#
# The trendscout runs as a cron job on prod EC2 and produces
# trending_today.json at /opt/crypto-sentiment/data/. This script
# fetches that artifact to the local marketing repo so marketing
# content pipelines (daily_engage, trending_tiktok, etc.) have
# fresh data to work from.
#
# Cron example (local Mac — runs before marketing jobs at ~8:16 AM):
#   10 8 * * * /Users/zhiminzou/Projects/crypto_sentiment_crawler/scripts/fetch_ec2_trending.sh >> /tmp/fetch_ec2_trending.log 2>&1
#
# Environment:
#   EC2_HOST       - EC2 hostname or IP (default: 34.236.47.243)
#   EC2_USER       - SSH username (default: ec2-user)
#   EC2_KEY        - SSH private key path (default: ~/.ssh/panicradar-ec2.pem)
#   REMOTE_PATH    - remote JSON path (default: /opt/crypto-sentiment/data/trending_today.json)
#   LOCAL_PATH     - local destination path (default: see below)
#   VALIDATE_SCRIPT - path to validate_trending_today.py (optional)
#   PR_DRY_RUN     - set to 1 to skip write (default: 0)

set -euo pipefail

# ---- Config ----
EC2_HOST="${EC2_HOST:-34.236.47.243}"
EC2_USER="${EC2_USER:-ec2-user}"
EC2_KEY="${EC2_KEY:-~/.ssh/panicradar-ec2.pem}"
REMOTE_PATH="${REMOTE_PATH:-/opt/crypto-sentiment/data/trending_today.json}"

# Default local path: the marketing repo's trending_today.json
MARKETING_REPO="${MARKETING_REPO:-/Users/zhiminzou/Projects/panicradar-marketing-opencode}"
LOCAL_PATH="${LOCAL_PATH:-$MARKETING_REPO/trending_today.json}"

VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-$MARKETING_REPO/scripts/validate_trending_today.py}"
PR_DRY_RUN="${PR_DRY_RUN:-0}"

SSH_OPTS="-i $EC2_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# ---- Main ----
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching trending_today.json from EC2 ($EC2_HOST)..."

# 1. Check SSH connectivity
if ! ssh $SSH_OPTS "$EC2_USER@$EC2_HOST" "test -f $REMOTE_PATH" 2>/dev/null; then
  echo "ERROR: Cannot reach $EC2_HOST or $REMOTE_PATH does not exist"
  exit 1
fi

# 2. Get remote file timestamp and size for logging
REMOTE_INFO=$(ssh $SSH_OPTS "$EC2_USER@$EC2_HOST" "stat -c '%y %s' $REMOTE_PATH 2>/dev/null || stat -f '%Sm %z' $REMOTE_PATH 2>/dev/null || echo 'unknown'")
echo "Remote file: $REMOTE_INFO"

# 3. Fetch the file via SCP to a temp path (atomic write)
TMP_PATH="${LOCAL_PATH}.tmp"
scp $SSH_OPTS "$EC2_USER@$EC2_HOST:$REMOTE_PATH" "$TMP_PATH"

# 4. Validate the downloaded JSON
if [ -f "$VALIDATE_SCRIPT" ]; then
  if python3 "$VALIDATE_SCRIPT" --fix --skip-date-check "$TMP_PATH"; then
    echo "Validation passed."
  else
    echo "WARNING: Validation failed for fetched JSON (date check skipped). Proceeding..."
  fi
else
  echo "NOTE: Validator not found at $VALIDATE_SCRIPT — skipping validation"
  # Basic JSON validation
  if ! python3 -c "import json; json.load(open('$TMP_PATH'))" 2>/dev/null; then
    echo "ERROR: Downloaded file is not valid JSON"
    rm -f "$TMP_PATH"
    exit 1
  fi
fi

# 5. Atomic move into place
if [ "$PR_DRY_RUN" = "1" ]; then
  echo "[DRY RUN] Would move $TMP_PATH → $LOCAL_PATH"
else
  mv "$TMP_PATH" "$LOCAL_PATH"
  echo "Written to $LOCAL_PATH"
fi

# 6. Log the result
if [ -f "$LOCAL_PATH" ]; then
  LOCAL_SIZE=$(stat -f '%z' "$LOCAL_PATH" 2>/dev/null || stat -c '%s' "$LOCAL_PATH" 2>/dev/null || echo "?")
  echo "Local file: $LOCAL_PATH ($LOCAL_SIZE bytes)"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done."
else
  echo "WARNING: $LOCAL_PATH was not written"
fi
