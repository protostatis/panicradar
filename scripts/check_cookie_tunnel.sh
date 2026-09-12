#!/bin/bash
# Functional health probe for the Reddit cookie solver tunnel.
#
# The solver + reverse tunnel run as launchd agents (KeepAlive=true).  A
# running process is NOT proof of a working tunnel: the ssh can be alive but
# the remote socket unreachable, the crawler container can hold a stale socket
# mount, or the solver can serve 502s.  This probe verifies the actual contract
# end-to-end:
#
#   1. Local solver /healthz on 127.0.0.1:18765 (fast, no ssh)
#   2. Remote socket roundtrip: EC2 host -> Unix socket -> tunnel -> local solver
#   3. Container socket roundtrip: crawler container -> mounted dir -> tunnel
#      -> local solver.  The directory (not the file) is mounted, so a stale
#      container mount after a tunnel reconnect is a real, silent failure mode
#      that probes 1-2 alone cannot see.
#   4. launchd restart churn: launchd `runs` is cumulative and never resets, so
#      an absolute threshold warns forever after a single old outage.  This
#      probe compares against the previous run (state file) and alerts only on
#      recent churn.
#
# Any failure is logged and surfaced as a macOS notification (best-effort).
# The script exits nonzero on failure so a cron/launchd wrapper can alert
# further.  Run it periodically, e.g. every 5-10 minutes:
#
#   */10 * * * * /Users/zhiminzou/Projects/crypto_sentiment_crawler-release/scripts/check_cookie_tunnel.sh >> /Users/zhiminzou/Projects/crypto_sentiment_crawler-release/logs/cookie_tunnel_health.log 2>&1
#
# Environment:
#   SSH_HOST            - ssh host alias (default: panicradar)
#   REMOTE_SOCKET       - remote Unix socket path (default: /opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock)
#   LOCAL_HEALTH_URL    - local solver health URL (default: http://127.0.0.1:18765/healthz)
#   CONTAINER_NAME      - crawler container (default: crypto-crawler)
#   CONTAINER_SOCKET    - socket path inside the container (default: /run/reddit-solver/reddit-cookie-solver.sock)
#   TUNNEL_LABEL        - launchd label (default: ai.panicradar.reddit-cookie-tunnel)
#   SOLVER_LABEL        - launchd label (default: ai.panicradar.reddit-cookie-solver)
#   MAX_RESTART_DELTA   - alert if a job restarted more than this many times
#                         since the previous probe (default: 2)
#   HEALTH_LOG          - probe log path (default: logs/cookie_tunnel_health.log)
#   RUNS_STATE_FILE     - churn baseline state (default: logs/.cookie_tunnel_runs_state)
#   MAX_TUNNEL_LOG_BYTES - rotate tunnel log if larger than this (default: 1048576 = 1 MiB)
#
# The authenticated /solve POST is deliberately NOT probed on every run: it
# launches a full Chrome solve (~seconds, heavy).  /healthz proves the server
# is alive and reachable through the tunnel; the periodic /solve path is
# covered by the pipeline that consumes the socket.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_HOST="${SSH_HOST:-panicradar}"
REMOTE_SOCKET="${REMOTE_SOCKET:-/opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock}"
LOCAL_HEALTH_URL="${LOCAL_HEALTH_URL:-http://127.0.0.1:18765/healthz}"
CONTAINER_NAME="${CONTAINER_NAME:-crypto-crawler}"
CONTAINER_SOCKET="${CONTAINER_SOCKET:-/run/reddit-solver/reddit-cookie-solver.sock}"
TUNNEL_LABEL="${TUNNEL_LABEL:-ai.panicradar.reddit-cookie-tunnel}"
SOLVER_LABEL="${SOLVER_LABEL:-ai.panicradar.reddit-cookie-solver}"
MAX_RESTART_DELTA="${MAX_RESTART_DELTA:-2}"
HEALTH_LOG="${HEALTH_LOG:-$ROOT/logs/cookie_tunnel_health.log}"
RUNS_STATE_FILE="${RUNS_STATE_FILE:-$ROOT/logs/.cookie_tunnel_runs_state}"
MAX_TUNNEL_LOG_BYTES="${MAX_TUNNEL_LOG_BYTES:-1048576}"
TUNNEL_LOG="${TUNNEL_LOG:-$HOME/Library/Logs/PanicRadar/reddit-cookie-tunnel.log}"

mkdir -p "$(dirname "$HEALTH_LOG")" "$(dirname "$RUNS_STATE_FILE")"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }

notify() {
    local title="$1" msg="$2"
    safe_title="${title//\"/\'}"
    safe_msg="${msg//\"/\'}"
    osascript -e "display notification \"$safe_msg\" with title \"$safe_title\"" >/dev/null 2>&1 || true
}

fail() {
    local reason="$1"
    echo "[$(stamp)] FAIL: $reason" >> "$HEALTH_LOG"
    notify "Cookie tunnel DOWN" "$reason"
    exit 1
}

warn() {
    echo "[$(stamp)] WARN: $1" >> "$HEALTH_LOG"
    notify "Cookie tunnel WARN" "$1"
}

ok() {
    echo "[$(stamp)] OK: $1" >> "$HEALTH_LOG"
}

note() {
    echo "[$(stamp)] NOTE: $1" >> "$HEALTH_LOG"
}

# --- 0. Bounded rotation of the tunnel log ---
# launchd KeepAlive + ThrottleInterval=10 re-launches the tunnel every ~10s
# during a network outage, appending ssh errors.  Cap the log so a prolonged
# outage cannot grow it without bound; never touch it while healthy-sized.
if [ -f "$TUNNEL_LOG" ] && [ "$(stat -f '%z' "$TUNNEL_LOG" 2>/dev/null || echo 0)" -gt "$MAX_TUNNEL_LOG_BYTES" ]; then
    ROTATED="$TUNNEL_LOG.$(date '+%Y%m%d-%H%M%S')"
    if mv "$TUNNEL_LOG" "$ROTATED" 2>/dev/null; then
        warn "rotated oversized tunnel log ($(stat -f '%z' "$ROTATED") bytes) -> $ROTATED"
    else
        # mv failed (e.g. launchd holds the fd differently); fall back to
        # truncation so the file cannot keep growing.
        : > "$TUNNEL_LOG" 2>/dev/null || true
        warn "truncated oversized tunnel log ($MAX_TUNNEL_LOG_BYTES limit)"
    fi
fi

# --- 1. Local solver health (no ssh) ---
if ! curl -fsS -m 5 "$LOCAL_HEALTH_URL" >/dev/null 2>&1; then
    fail "local solver /healthz unreachable at $LOCAL_HEALTH_URL"
fi
ok "local solver /healthz"

# --- 2. Remote socket roundtrip through the tunnel (EC2 host view) ---
# EC2 reaches the tunnel's Unix socket; socat forwards it over ssh -R back to
# the local solver.  A healthy tunnel returns HTTP 200 with {"ok":true}.
REMOTE_OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" \
    "echo -e 'GET /healthz HTTP/1.0\r\n\r\n' | timeout 8 socat - UNIX-CONNECT:'$REMOTE_SOCKET'" 2>&1 || true)"
if ! printf '%s' "$REMOTE_OUT" | grep -q '"ok":true'; then
    fail "remote socket roundtrip failed ($SSH_HOST:$REMOTE_SOCKET): $(printf '%s' "$REMOTE_OUT" | tr '\n' ' ' | head -c 200)"
fi
ok "remote socket roundtrip ($SSH_HOST:$REMOTE_SOCKET)"

# --- 3. Container socket roundtrip (what the crawler actually uses) ---
# The crawler bind-mounts the socket *directory*.  A container started before a
# tunnel reconnect could still be bound to the previous socket inode if the
# deploy had used a file mount; the directory mount avoids that, and this probe
# proves the live container sees a working socket rather than a stale one.
#
# Only probe when the crawler is actually on Unbrowser fetching: a deliberate
# standard-fetching fallback has no mounted socket and must not alarm here.
CRAWLER_MODE="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" \
    "docker exec '$CONTAINER_NAME' printenv REDDIT_FETCH_MODE" 2>/dev/null || true)"
CRAWLER_MODE="$(printf '%s' "$CRAWLER_MODE" | tr -d '[:space:]')"
if [ "$CRAWLER_MODE" != "unbrowser" ]; then
    note "crawler $CONTAINER_NAME is not on unbrowser fetching (REDDIT_FETCH_MODE=${CRAWLER_MODE:-unset}); skipping container socket probe"
elif CONTAINER_OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" \
    "docker exec -i -e PROBE_SOCKET='$CONTAINER_SOCKET' '$CONTAINER_NAME' python3 -" <<'PY' 2>&1
import os
import socket

path = os.environ["PROBE_SOCKET"]
conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
conn.settimeout(8)
try:
    conn.connect(path)
    conn.sendall(b"GET /healthz HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    data = b""
    while True:
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
finally:
    conn.close()

if b'"ok":true' not in data:
    raise SystemExit("container socket did not return ok")
print("container socket ok")
PY
)"; then
    ok "container socket roundtrip ($CONTAINER_NAME:$CONTAINER_SOCKET)"
else
    fail "container socket roundtrip failed ($CONTAINER_NAME:$CONTAINER_SOCKET): $(printf '%s' "$CONTAINER_OUT" | tr '\n' ' ' | head -c 200)"
fi

# --- 4. launchd restart churn ---
# KeepAlive can mask a crash-looping job with a "running" process.  launchd
# `runs` is cumulative and never resets, so compare against the previous probe
# (persisted in RUNS_STATE_FILE) and alert only on recent churn; an absolute
# threshold would warn forever after one old outage.
[ -f "$RUNS_STATE_FILE" ] || : > "$RUNS_STATE_FILE"
for label in "$TUNNEL_LABEL" "$SOLVER_LABEL"; do
    state="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null || true)"
    runs="$(printf '%s' "$state" | awk -F'= ' '/runs =/{print $2; exit}')"
    last_exit="$(printf '%s' "$state" | awk -F'= ' '/last exit code =/{print $2; exit}')"
    pid="$(printf '%s' "$state" | awk -F'= ' '/pid =/{print $2; exit}')"
    if [ -z "$pid" ]; then
        fail "$label is NOT running (launchd)"
    fi
    prev_runs="$(awk -F'\t' -v l="$label" '$1==l{print $2; exit}' "$RUNS_STATE_FILE" 2>/dev/null || true)"
    if [ -n "$runs" ] && [ -n "$prev_runs" ] && [ "$runs" -gt "$prev_runs" ]; then
        delta=$((runs - prev_runs))
        if [ "$delta" -gt "$MAX_RESTART_DELTA" ]; then
            warn "$label restart churn: +$delta since last probe (runs=$runs last_exit=${last_exit:-unknown})"
        fi
    fi
    if [ -n "$runs" ]; then
        tmp_state="$(mktemp)"
        awk -F'\t' -v l="$label" -v r="$runs" '$1!=l{print} END{print l"\t"r}' "$RUNS_STATE_FILE" > "$tmp_state"
        mv "$tmp_state" "$RUNS_STATE_FILE"
    fi
    ok "$label running (pid=$pid runs=$runs)"
done

ok "cookie tunnel healthy"
