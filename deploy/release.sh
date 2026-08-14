#!/usr/bin/env bash
# Run the fail-closed production cutover after the release tag is checked out.

set -euo pipefail

for required_name in \
  RELEASE_TAG RELEASE_IMAGE_TAG REGISTRY IMAGE_PREFIX GHCR_ACTOR GHCR_TOKEN \
  TELEGRAM_BOT_TOKEN; do
  if [ -z "${!required_name:-}" ]; then
    echo "ERROR: Required deployment variable is empty: $required_name"
    exit 1
  fi
done

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

echo "========== DEPLOYMENT START: $RELEASE_TAG =========="

# Ensure persistent directories exist.
sudo mkdir -p \
  /opt/crypto-sentiment/data \
  /opt/crypto-sentiment/backups \
  /opt/crypto-sentiment/logs \
  /opt/crypto-sentiment/run
sudo chown -R ec2-user:ec2-user /opt/crypto-sentiment

if [ ! -f /opt/crypto-sentiment/.env ]; then
  echo "ERROR: /opt/crypto-sentiment/.env is required for production"
  exit 1
fi
CRAWLER_ENV_ARGS=(--env-file /opt/crypto-sentiment/.env)

# Existing production data is mandatory. Never bootstrap an empty database or
# repository state during a release deployment.
if [ ! -s /opt/crypto-sentiment/data/sentiment.db ]; then
  echo "ERROR: Production database is missing or empty"
  exit 1
fi
if [ ! -s /opt/crypto-sentiment/data/orchestrator_state.json ]; then
  echo "ERROR: Production orchestrator state is missing or empty"
  exit 1
fi

# ========== DISK SPACE CHECK & CLEANUP ==========
echo "Pre-cleanup disk usage:"
df -h /
docker system prune -af || true
docker builder prune -af || true

echo "Post-cleanup disk usage:"
AVAIL_KB=$(df -kP / | awk 'NR == 2 {print $4}')
df -h /
case "$AVAIL_KB" in
  ''|*[!0-9]*)
    echo "ERROR: Could not determine available disk space"
    exit 1
    ;;
esac
if [ "$AVAIL_KB" -lt 8000000 ]; then
  echo "ERROR: Insufficient disk space. Need 8GB, have ${AVAIL_KB}KB"
  exit 1
fi
echo "Disk space OK: ${AVAIL_KB}KB available"

# ========== DOCKER LOGIN & PULL ==========
printf '%s' "$GHCR_TOKEN" | \
  docker login "$REGISTRY" -u "$GHCR_ACTOR" --password-stdin

REMOTE_IMAGE="$REGISTRY/$IMAGE_PREFIX"
echo "Pulling immutable release images ($RELEASE_IMAGE_TAG)..."
for component in crawler api frontend game-server; do
  local_image="crypto-sentiment-$component"
  remote_image="$REMOTE_IMAGE-$component:$RELEASE_IMAGE_TAG"
  # `latest` advances only after a verified deployment, so it remains the
  # known-good image even if a candidate pull or cutover fails.
  if docker image inspect "$local_image:latest" >/dev/null 2>&1; then
    docker tag "$local_image:latest" "$local_image:previous"
  fi
  docker pull "$remote_image"
  docker tag "$remote_image" "$local_image:current"
  docker image rm "$remote_image" >/dev/null || true
done

docker network create --subnet=172.18.0.0/16 \
  crypto-sentiment_crypto-net 2>/dev/null || echo "Network already exists"

# Prove the candidate can make a real uncached OpenRouter request before
# replacing healthy production services.
echo "Checking candidate OpenRouter embedding access..."
docker run --rm \
  --network crypto-sentiment_crypto-net \
  "${CRAWLER_ENV_ARGS[@]}" \
  crypto-sentiment-crawler:current \
  uv run python -m crypto_sentiment_crawler.maintenance.deployment_checks \
    openrouter \
    --expected-model qwen/qwen3-embedding-8b \
    --expected-dimensions 4096
echo "Candidate OpenRouter canary passed."

# A solver outage degrades only Reddit collection. It must not block unrelated
# API, frontend, or security releases.
REDDIT_SOCKET=/opt/crypto-sentiment/run/reddit-cookie-solver.sock
REDDIT_CRAWLER_ARGS=(
  -e REDDIT_FETCH_MODE=standard
  -e UNBROWSER_COOKIE_SERVICE_SOCKET=
  -e UNBROWSER_COOKIE_SERVICE_TOKEN=
)
EXPECTED_SOCKET_METADATA="600:$(id -u):$(id -g)"
SOCKET_METADATA=$(stat -c '%a:%u:%g' "$REDDIT_SOCKET" 2>/dev/null || true)

if [ -S "$REDDIT_SOCKET" ] && \
   [ "$SOCKET_METADATA" = "$EXPECTED_SOCKET_METADATA" ]; then
  echo "Checking cookie-backed Unbrowser Reddit access..."
  if docker run --rm \
    --network crypto-sentiment_crypto-net \
    "${CRAWLER_ENV_ARGS[@]}" \
    -v "$REDDIT_SOCKET":/run/reddit-cookie-solver.sock:ro \
    -e REDDIT_FETCH_MODE=unbrowser \
    -e UNBROWSER_COOKIE_SERVICE_SOCKET=/run/reddit-cookie-solver.sock \
    crypto-sentiment-crawler:current \
    uv run python -c '
import asyncio

from crypto_sentiment_crawler.crawler.fetcher import Fetcher


async def main() -> None:
    async with Fetcher(randomize_delay=False) as fetcher:
        if fetcher.reddit_transport is None:
            raise RuntimeError("Reddit Unbrowser transport was not configured")
        cookies = await asyncio.to_thread(
            fetcher.reddit_transport._request_cookies,
            "https://old.reddit.com/r/Bitcoin/new/",
        )
        if not cookies:
            raise RuntimeError("Reddit cookie solver returned no cookies")
        result = await fetcher.fetch(
            "https://old.reddit.com/r/Bitcoin/new/",
            rate_limit=1.0,
        )
    if result.status_code != 200 or "data-timestamp" not in result.content:
        raise RuntimeError(
            f"Reddit Unbrowser canary failed (status={result.status_code})"
        )


asyncio.run(main())
'; then
    REDDIT_CRAWLER_ARGS=(
      -v "$REDDIT_SOCKET:/run/reddit-cookie-solver.sock:ro"
      -e REDDIT_FETCH_MODE=unbrowser
      -e UNBROWSER_COOKIE_SERVICE_SOCKET=/run/reddit-cookie-solver.sock
    )
    echo "Reddit Unbrowser canary passed."
  else
    echo "WARNING: Reddit Unbrowser canary failed; using standard fetching."
  fi
else
  echo "WARNING: Reddit solver socket unavailable or unsafe ($SOCKET_METADATA; expected $EXPECTED_SOCKET_METADATA); using standard fetching."
fi

# ========== COHERENT PRE-DEPLOYMENT BACKUP ==========
# Retry if a live belief publication advances between the SQLite snapshot and
# the matching JSON state copy.
BACKUP_SUFFIX=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_NAME="sentiment_predeploy_${BACKUP_SUFFIX}.db"
STATE_BACKUP_NAME="orchestrator_state_predeploy_${BACKUP_SUFFIX}.json"
BACKUP_PATH="/opt/crypto-sentiment/backups/$BACKUP_NAME"
STATE_BACKUP_PATH="/opt/crypto-sentiment/backups/$STATE_BACKUP_NAME"
BACKUP_READY=0
for attempt in $(seq 1 5); do
  rm -f "$BACKUP_PATH" "$STATE_BACKUP_PATH"
  docker run --rm \
    -v /opt/crypto-sentiment/data:/app/data:ro \
    -v /opt/crypto-sentiment/backups:/app/backups \
    crypto-sentiment-api:current \
    python -m crypto_sentiment_crawler.maintenance.deployment_checks \
      backup /app/data/sentiment.db "/app/backups/$BACKUP_NAME"
  cp /opt/crypto-sentiment/data/orchestrator_state.json "$STATE_BACKUP_PATH"
  if docker run --rm \
    -v /opt/crypto-sentiment/backups:/app/backups:ro \
    crypto-sentiment-api:current \
    python -m crypto_sentiment_crawler.maintenance.deployment_checks \
      publication \
      --db "/app/backups/$BACKUP_NAME" \
      --state "/app/backups/$STATE_BACKUP_NAME"; then
    BACKUP_READY=1
    break
  fi
  echo "Backup pair changed during snapshot; retrying ($attempt/5)..."
  sleep 1
done
if [ "$BACKUP_READY" -ne 1 ]; then
  echo "ERROR: Could not create a coherent database/state backup"
  rm -f "$BACKUP_PATH" "$STATE_BACKUP_PATH"
  exit 1
fi
sha256sum "$BACKUP_PATH" "$STATE_BACKUP_PATH"

if [ -f /opt/crypto-sentiment/data/discovery_state.json ]; then
  DISCOVERY_BACKUP_PATH="/opt/crypto-sentiment/backups/discovery_state_predeploy_${BACKUP_SUFFIX}.json"
  DISCOVERY_BACKUP_READY=0
  for attempt in $(seq 1 3); do
    cp /opt/crypto-sentiment/data/discovery_state.json "$DISCOVERY_BACKUP_PATH"
    if python3 -m json.tool "$DISCOVERY_BACKUP_PATH" >/dev/null 2>&1; then
      DISCOVERY_BACKUP_READY=1
      break
    fi
    rm -f "$DISCOVERY_BACKUP_PATH"
    sleep 1
  done
  if [ "$DISCOVERY_BACKUP_READY" -ne 1 ]; then
    echo "ERROR: Could not create a valid discovery-state backup"
    exit 1
  fi
  sha256sum "$DISCOVERY_BACKUP_PATH"
fi
echo "Created and verified pre-deploy recovery set: $BACKUP_SUFFIX"
# shellcheck disable=SC2012
ls -t /opt/crypto-sentiment/backups/sentiment_predeploy_*.db \
  2>/dev/null | tail -n +15 | xargs -r rm || true
# shellcheck disable=SC2012
ls -t /opt/crypto-sentiment/backups/orchestrator_state_predeploy_*.json \
  2>/dev/null | tail -n +15 | xargs -r rm || true
# shellcheck disable=SC2012
ls -t /opt/crypto-sentiment/backups/discovery_state_predeploy_*.json \
  2>/dev/null | tail -n +15 | xargs -r rm || true

# ========== SYNC CONFIG FILES ==========
mkdir -p /opt/crypto-sentiment/dashboard-frontend
cp dashboard-frontend/blocklist.conf \
  /opt/crypto-sentiment/dashboard-frontend/blocklist.conf

# ========== PREPARE AUTOMATIC ROLLBACK ==========
SERVICES="crypto-crawler crypto-api crypto-frontend crypto-signals crypto-game-server"
RESTORE_ORDER="crypto-api crypto-game-server crypto-frontend crypto-crawler crypto-signals crypto-belief-auto"
PREVIOUS_SERVICES=""
for service in $SERVICES; do
  if docker inspect "$service-previous" >/dev/null 2>&1; then
    echo "ERROR: Stale rollback container exists: $service-previous"
    exit 1
  fi
  if ! docker inspect "$service" >/dev/null 2>&1; then
    echo "ERROR: Cannot deploy safely without rollback container $service"
    exit 1
  fi
  PREVIOUS_STATE=$(docker inspect --format '{{.State.Status}}' "$service")
  if [ "$PREVIOUS_STATE" != "running" ]; then
    echo "ERROR: Existing rollback container $service is not running ($PREVIOUS_STATE)"
    exit 1
  fi
  PREVIOUS_SERVICES="$PREVIOUS_SERVICES $service"
done
if docker inspect crypto-belief-auto-previous >/dev/null 2>&1; then
  echo "ERROR: Stale rollback container exists: crypto-belief-auto-previous"
  exit 1
fi
if docker inspect crypto-belief-auto >/dev/null 2>&1; then
  LEGACY_STATE=$(docker inspect --format '{{.State.Status}}' crypto-belief-auto)
  if [ "$LEGACY_STATE" = "running" ]; then
    PREVIOUS_SERVICES="$PREVIOUS_SERVICES crypto-belief-auto"
  fi
fi

ROLLBACK_ACTIVE=1
NEW_CONTAINERS_STARTED=0
rollback_on_exit() {
  exit_code=$?
  if [ "$exit_code" -eq 0 ] || [ "$ROLLBACK_ACTIVE" -ne 1 ]; then
    return "$exit_code"
  fi

  echo "Deployment failed; restoring previous containers..."
  ROLLBACK_ACTIVE=0
  trap - EXIT INT TERM
  set +e
  ROLLBACK_FAILED=0
  if [ "$NEW_CONTAINERS_STARTED" -eq 1 ]; then
    for service in $SERVICES; do
      if docker inspect "$service" >/dev/null 2>&1; then
        docker rm -f "$service" >/dev/null 2>&1 || ROLLBACK_FAILED=1
      fi
    done
  fi
  for service in $RESTORE_ORDER; do
    if docker inspect "$service-previous" >/dev/null 2>&1; then
      if ! docker rename "$service-previous" "$service"; then
        echo "ROLLBACK ERROR: Could not rename $service-previous"
        ROLLBACK_FAILED=1
        continue
      fi
      if ! docker start "$service"; then
        echo "ROLLBACK ERROR: Could not start $service"
        ROLLBACK_FAILED=1
      fi
    else
      case " $PREVIOUS_SERVICES " in
        *" $service "*)
          if ! docker start "$service"; then
            echo "ROLLBACK ERROR: Could not restart $service"
            ROLLBACK_FAILED=1
          fi
          ;;
      esac
    fi
  done
  sleep 5
  for service in $PREVIOUS_SERVICES; do
    RESTORED_STATE=$(
      docker inspect --format '{{.State.Status}}' "$service" 2>/dev/null || \
        echo "missing"
    )
    if [ "$RESTORED_STATE" != "running" ]; then
      echo "ROLLBACK ERROR: $service is not running after restore ($RESTORED_STATE)"
      ROLLBACK_FAILED=1
    fi
  done
  if [ "$ROLLBACK_FAILED" -ne 0 ]; then
    echo "CRITICAL: Automatic rollback was incomplete; operator action required"
    docker ps -a
  else
    echo "Previous service set restored."
  fi
  return "$exit_code"
}
trap 'rollback_on_exit' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Stopping old containers..."
for service in $PREVIOUS_SERVICES; do
  docker stop "$service"
  docker rename "$service" "$service-previous"
done

HEARTBEAT_WATERMARK_JSON=$(docker run --rm \
  -v /opt/crypto-sentiment/data:/app/data:ro \
  crypto-sentiment-api:current \
  python -m crypto_sentiment_crawler.maintenance.deployment_checks \
    heartbeat-watermark --db /app/data/sentiment.db)
HEARTBEAT_WATERMARK=$(printf '%s' "$HEARTBEAT_WATERMARK_JSON" | \
  python3 -c 'import json, sys; print(json.load(sys.stdin)["heartbeat_id"])')
case "$HEARTBEAT_WATERMARK" in
  ''|*[!0-9]*)
    echo "ERROR: Invalid heartbeat watermark"
    exit 1
    ;;
esac
CANDIDATE_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Candidate heartbeat watermark: $HEARTBEAT_WATERMARK"
NEW_CONTAINERS_STARTED=1

# ========== START SERVICES ==========
echo "Starting API..."
docker run -d --name crypto-api --restart unless-stopped \
  -p 8000:8000 \
  --network crypto-sentiment_crypto-net \
  --network-alias api \
  -v /opt/crypto-sentiment/data:/app/data \
  -v /opt/crypto-sentiment/logs:/app/logs \
  -e DATABASE_PATH=/app/data/sentiment.db \
  crypto-sentiment-api:current

echo "Waiting for API to be healthy..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "API is healthy!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: API failed to become healthy"
    docker logs crypto-api --tail 50
    exit 1
  fi
  sleep 2
done

echo "Starting game server..."
docker run -d --name crypto-game-server --restart unless-stopped \
  --network crypto-sentiment_crypto-net \
  --network-alias game-server \
  --cpus 0.5 \
  --memory 256m \
  --pids-limit 50 \
  -e NODE_ENV=production \
  -e ALLOWED_ORIGINS=https://panicradar.ai,https://www.panicradar.ai \
  crypto-sentiment-game-server:current

echo "Waiting for game server to be healthy..."
for i in $(seq 1 15); do
  GAME_HEALTH=$(
    docker inspect --format '{{.State.Health.Status}}' \
      crypto-game-server 2>/dev/null || echo "missing"
  )
  if [ "$GAME_HEALTH" = "healthy" ]; then
    echo "Game server is healthy!"
    break
  fi
  if [ "$i" -eq 15 ]; then
    echo "ERROR: Game server health check failed (status: $GAME_HEALTH)"
    docker logs crypto-game-server --tail 50
    exit 1
  fi
  sleep 2
done

echo "Starting frontend..."
docker run -d --name crypto-frontend --restart unless-stopped \
  -p 80:80 -p 443:443 \
  --network crypto-sentiment_crypto-net \
  -v /etc/letsencrypt:/etc/letsencrypt:ro \
  -v /opt/crypto-sentiment/logs:/var/log/nginx \
  -v /opt/crypto-sentiment/dashboard-frontend/blocklist.conf:/etc/nginx/conf.d/blocklist.conf:ro \
  crypto-sentiment-frontend:current

echo "Starting crawler..."
docker run -d --name crypto-crawler --restart unless-stopped \
  --network crypto-sentiment_crypto-net \
  "${CRAWLER_ENV_ARGS[@]}" \
  -v /opt/crypto-sentiment/data:/app/data \
  -v /opt/crypto-sentiment/logs:/app/logs \
  -e DATABASE_PATH=/app/data/sentiment.db \
  -e PROXY_URL= \
  "${REDDIT_CRAWLER_ARGS[@]}" \
  crypto-sentiment-crawler:current \
  uv run crawler background --crawl-interval 60

echo "Starting signals bot..."
docker run -d --name crypto-signals --restart unless-stopped \
  --network crypto-sentiment_crypto-net \
  -v /opt/crypto-sentiment/data:/app/data \
  -v /opt/crypto-sentiment/logs:/app/logs \
  -e TELEGRAM_BOT_TOKEN \
  -e DB_PATH=/app/data/sentiment.db \
  -e SIGNAL_CHECK_INTERVAL=30 \
  -e TELEGRAM_CHANNEL_ID=@PanicRadarAlerts \
  crypto-sentiment-crawler:current \
  uv run signals bot

# Keep rollback protection active until the candidate completes initial jobs.
echo "Waiting for stable services and fresh runtime heartbeats..."
RUNTIME_CHECK_OUT=/tmp/panicradar-runtime-check.out
RUNTIME_CHECK_ERR=/tmp/panicradar-runtime-check.err
RUNTIME_READY=0
for i in $(seq 1 360); do
  CRAWLER_STATE=$(
    docker inspect --format '{{.State.Status}}' crypto-crawler 2>/dev/null || \
      echo "missing"
  )
  CRAWLER_RESTARTS=$(
    docker inspect --format '{{.RestartCount}}' crypto-crawler 2>/dev/null || \
      echo "999"
  )
  if [ "$CRAWLER_STATE" = "restarting" ] || \
     [ "$CRAWLER_STATE" = "exited" ] || \
     [ "$CRAWLER_STATE" = "dead" ] || \
     [ "$CRAWLER_RESTARTS" -ne 0 ]; then
    echo "ERROR: Crawler unstable (state=$CRAWLER_STATE restarts=$CRAWLER_RESTARTS)"
    docker logs crypto-crawler --tail 100
    exit 1
  fi
  if [ "$CRAWLER_STATE" = "running" ] && docker exec crypto-api \
    python -m crypto_sentiment_crawler.maintenance.deployment_checks \
      runtime \
      --db /app/data/sentiment.db \
      --state /app/data/orchestrator_state.json \
      --since "$CANDIDATE_STARTED_AT" \
      --after-heartbeat-id "$HEARTBEAT_WATERMARK" \
      >"$RUNTIME_CHECK_OUT" 2>"$RUNTIME_CHECK_ERR"; then
    cat "$RUNTIME_CHECK_OUT"
    RUNTIME_READY=1
    break
  fi
  if [ "$i" -eq 360 ]; then
    echo "ERROR: Runtime checks did not pass within 12 minutes"
    cat "$RUNTIME_CHECK_ERR" 2>/dev/null || true
    docker logs crypto-crawler --tail 100
    exit 1
  fi
  sleep 2
done
rm -f "$RUNTIME_CHECK_OUT" "$RUNTIME_CHECK_ERR"
if [ "$RUNTIME_READY" -ne 1 ]; then
  echo "ERROR: Runtime readiness was not established"
  exit 1
fi

# Stopped rollback containers still protect their known-good images here.
echo "Cleaning up unused images..."
docker image prune -af
df -h /

# ========== VERIFY DEPLOYMENT ==========
echo "Verifying all containers are running..."
sleep 5
RUNNING=$(
  docker ps --format '{{.Names}}' | \
    awk '/^crypto-(api|frontend|crawler|signals|game-server)$/ {count++} END {print count + 0}'
)
if [ "$RUNNING" -ne 5 ]; then
  echo "ERROR: Not all containers are running!"
  docker ps -a
  exit 1
fi

for service in $SERVICES; do
  SERVICE_STATE=$(docker inspect --format '{{.State.Status}}' "$service")
  SERVICE_RESTARTS=$(docker inspect --format '{{.RestartCount}}' "$service")
  if [ "$SERVICE_STATE" != "running" ] || [ "$SERVICE_RESTARTS" -ne 0 ]; then
    echo "ERROR: $service unstable (state=$SERVICE_STATE restarts=$SERVICE_RESTARTS)"
    docker logs "$service" --tail 100 2>/dev/null || true
    exit 1
  fi
done

echo "Checking frontend and API through Nginx..."
if ! curl -ksf -o /dev/null https://localhost; then
  echo "ERROR: Frontend HTTPS check failed"
  docker logs crypto-frontend --tail 100
  exit 1
fi
if ! curl -ksf -o /dev/null https://localhost/api/dashboard/summary; then
  echo "ERROR: API proxy check failed"
  docker logs crypto-frontend --tail 100
  docker logs crypto-api --tail 100
  exit 1
fi

ROLLBACK_ACTIVE=0
for service in $PREVIOUS_SERVICES; do
  docker rm "$service-previous" >/dev/null 2>&1 || true
done
docker rm crypto-belief-auto >/dev/null 2>&1 || true
trap - EXIT INT TERM

for component in crawler api frontend game-server; do
  docker tag "crypto-sentiment-$component:current" \
    "crypto-sentiment-$component:latest"
done
echo "All 5 containers passed runtime and proxy checks."

# ========== SETUP CRON ==========
chmod +x deploy/backup-db.sh scripts/daily_traffic_report.sh
sudo mkdir -p /opt/crypto-sentiment/reports
BACKUP_CRON="0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh >> /opt/crypto-sentiment/logs/backup.log 2>&1"
TRAFFIC_CRON="5 0 * * * REPORT_EMAIL_TO=protostatis.dev@gmail.com REPORT_EMAIL_FROM=protostatis.dev@gmail.com /home/ec2-user/crypto_sentiment_crawler/scripts/daily_traffic_report.sh >> /opt/crypto-sentiment/logs/traffic_report.log 2>&1"
MORNING_TRAFFIC_CRON="0 12 * * * REPORT_EMAIL_TO=protostatis.dev@gmail.com REPORT_EMAIL_FROM=protostatis.dev@gmail.com /home/ec2-user/crypto_sentiment_crawler/scripts/daily_traffic_report.sh --date \$(date -u +\%Y-\%m-\%d) >> /opt/crypto-sentiment/logs/traffic_report.log 2>&1"
{
  crontab -l 2>/dev/null | \
    grep -v "backup-db.sh" | grep -v "daily_traffic_report.sh" || true
  echo "$BACKUP_CRON"
  echo "$TRAFFIC_CRON"
  echo "$MORNING_TRAFFIC_CRON"
} | crontab -

echo "========== DEPLOYMENT COMPLETE =========="
docker ps
