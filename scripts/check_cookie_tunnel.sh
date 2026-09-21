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
#   2. Keychain token -> local solver /verify.  /healthz is unauthenticated, so
#      a one-sided token rotation (keychain vs the running solver) would
#      otherwise stay invisible until the next solver restart.
#   3. Remote socket roundtrip: EC2 host -> Unix socket -> tunnel -> local solver
#   4. Container socket roundtrip: crawler container -> mounted dir -> tunnel
#      -> local solver, authenticated with the container's configured token via
#      /verify.  The directory (not the file) is mounted, so a stale container
#      mount after a tunnel reconnect is a real, silent failure mode that
#      probes 1-3 alone cannot see; /verify also catches a token mismatch
#      between EC2 and the Mac solver before the next Reddit block event.
#   5. launchd restart churn: launchd `runs` is cumulative and never resets, so
#      an absolute threshold warns forever after a single old outage.  This
#      probe compares against the previous run (state file) and alerts only on
#      recent churn.
#
# Probe-host reachability is NOT tunnel health.  A flaky Mac->EC2 path makes
# ssh itself fail (exit 255) while the supervised tunnel stays up, so transport
# failures are retried once and then logged softly; they only page after
# MAX_TRANSPORT_FAILURES consecutive probes.
#
# Any tunnel failure is logged and surfaced as a macOS notification
# (best-effort).  The script exits nonzero on failure so a cron/launchd wrapper
# can alert further.  Run it periodically, e.g. every 5-10 minutes:
#
#   */10 * * * * /Users/zhiminzou/Projects/crypto_sentiment_crawler-release/scripts/check_cookie_tunnel.sh >> /Users/zhiminzou/Projects/crypto_sentiment_crawler-release/logs/cookie_tunnel_health.log 2>&1
#
# Environment:
#   SSH_HOST            - ssh host alias (default: panicradar)
#   REMOTE_SOCKET       - remote Unix socket path (default: /opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock)
#   LOCAL_HEALTH_URL    - local solver health URL (default: http://127.0.0.1:18765/healthz)
#   LOCAL_VERIFY_URL    - local solver token-verify URL (default: http://127.0.0.1:18765/verify)
#   SOLVER_KEYCHAIN_SERVICE - keychain service for the solver token (default: panicradar-reddit-solver-token)
#   SOLVER_KEYCHAIN_ACCOUNT - keychain account for the solver token (default: reddit-crawler)
#   CONTAINER_NAME      - crawler container (default: crypto-crawler)
#   CONTAINER_SOCKET    - socket path inside the container (default: /run/reddit-solver/reddit-cookie-solver.sock)
#   TUNNEL_LABEL        - launchd label (default: ai.panicradar.reddit-cookie-tunnel)
#   SOLVER_LABEL        - launchd label (default: ai.panicradar.reddit-cookie-solver)
#   MAX_RESTART_DELTA   - alert if a job restarted more than this many times
#                         since the previous probe (default: 2)
#   MAX_TRANSPORT_FAILURES - page after this many consecutive probe-host
#                            transport failures (default: 3)
#   HEALTH_LOG          - probe log path (default: logs/cookie_tunnel_health.log)
#   RUNS_STATE_FILE     - churn baseline state (default: logs/.cookie_tunnel_runs_state)
#   TRANSPORT_FAIL_STATE_FILE - transport failure streak state
#                               (default: logs/.cookie_tunnel_transport_failures)
#   MAX_TUNNEL_LOG_BYTES - rotate tunnel log if larger than this (default: 1048576 = 1 MiB)
#
# The authenticated /solve POST is deliberately NOT probed on every run: it
# launches a full Chrome solve (~seconds, heavy).  /healthz proves the server
# is alive and reachable through the tunnel; /verify proves the configured
# token still matches without launching Chrome; the periodic /solve path is
# covered by the pipeline that consumes the socket.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_HOST="${SSH_HOST:-panicradar}"
REMOTE_SOCKET="${REMOTE_SOCKET:-/opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock}"
LOCAL_HEALTH_URL="${LOCAL_HEALTH_URL:-http://127.0.0.1:18765/healthz}"
LOCAL_VERIFY_URL="${LOCAL_VERIFY_URL:-http://127.0.0.1:18765/verify}"
SOLVER_KEYCHAIN_SERVICE="${SOLVER_KEYCHAIN_SERVICE:-panicradar-reddit-solver-token}"
SOLVER_KEYCHAIN_ACCOUNT="${SOLVER_KEYCHAIN_ACCOUNT:-reddit-crawler}"
CONTAINER_NAME="${CONTAINER_NAME:-crypto-crawler}"
CONTAINER_SOCKET="${CONTAINER_SOCKET:-/run/reddit-solver/reddit-cookie-solver.sock}"
TUNNEL_LABEL="${TUNNEL_LABEL:-ai.panicradar.reddit-cookie-tunnel}"
SOLVER_LABEL="${SOLVER_LABEL:-ai.panicradar.reddit-cookie-solver}"
MAX_RESTART_DELTA="${MAX_RESTART_DELTA:-2}"
MAX_TRANSPORT_FAILURES="${MAX_TRANSPORT_FAILURES:-3}"
HEALTH_LOG="${HEALTH_LOG:-$ROOT/logs/cookie_tunnel_health.log}"
RUNS_STATE_FILE="${RUNS_STATE_FILE:-$ROOT/logs/.cookie_tunnel_runs_state}"
TRANSPORT_FAIL_STATE_FILE="${TRANSPORT_FAIL_STATE_FILE:-$ROOT/logs/.cookie_tunnel_transport_failures}"
MAX_TUNNEL_LOG_BYTES="${MAX_TUNNEL_LOG_BYTES:-1048576}"
TUNNEL_LOG="${TUNNEL_LOG:-$HOME/Library/Logs/PanicRadar/reddit-cookie-tunnel.log}"

mkdir -p "$(dirname "$HEALTH_LOG")" "$(dirname "$RUNS_STATE_FILE")" "$(dirname "$TRANSPORT_FAIL_STATE_FILE")"
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

# soft_warn logs without a macOS notification: used for ambiguous conditions
# (probe-host network blips) that must not page.
soft_warn() {
    echo "[$(stamp)] WARN: $1" >> "$HEALTH_LOG"
}

# run_remote runs a command on the probe host and captures both output and
# exit status.  ssh exits 255 when the transport itself fails (host
# unreachable, banner timeout, auth refused) as opposed to the remote command
# failing, which is the signal this probe needs to tell apart.
REMOTE_OUT=""
REMOTE_STATUS=0
run_remote() {
    REMOTE_STATUS=0
    REMOTE_OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "$1" 2>&1)" || REMOTE_STATUS=$?
}

# transport_failure records a probe-host reachability failure.  Single blips
# are logged softly; only MAX_TRANSPORT_FAILURES consecutive probes page, so a
# sustained EC2/network outage still alerts while a flaky path does not.
transport_failure() {
    local count
    count="$(cat "$TRANSPORT_FAIL_STATE_FILE" 2>/dev/null || echo 0)"
    case "$count" in
        ''|*[!0-9]*) count=0 ;;
    esac
    count=$((count + 1))
    echo "$count" > "$TRANSPORT_FAIL_STATE_FILE"
    if [ "$count" -ge "$MAX_TRANSPORT_FAILURES" ]; then
        fail "probe host $SSH_HOST unreachable for $count consecutive probes: $1"
    fi
    soft_warn "probe host $SSH_HOST unreachable (consecutive=$count/$MAX_TRANSPORT_FAILURES): $1"
    REMOTE_OK=0
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

# --- 1b. Keychain token -> running solver (restart resilience) ---
# The launchd entrypoint reads the solver token from the keychain on every
# restart.  /healthz is unauthenticated, so without this check a one-sided
# keychain rotation would only surface when the solver next restarts.
# A cron session cannot read the login keychain (only System.keychain is in
# its search list), so this check applies to manual runs; the container
# /verify probe below is the one that covers the cron path.
KEYCHAIN_TOKEN="$(security find-generic-password \
    -a "$SOLVER_KEYCHAIN_ACCOUNT" -s "$SOLVER_KEYCHAIN_SERVICE" -w 2>/dev/null || true)"
if [ -z "$KEYCHAIN_TOKEN" ]; then
    note "keychain solver token unavailable in this session (a cron session cannot read the login keychain); skipped keychain/solver token check"
else
    # Feed the header through stdin so the token never appears in argv/ps.
    VERIFY_CODE="$(printf 'header = "X-Reddit-Solver-Token: %s"\n' "$KEYCHAIN_TOKEN" \
        | curl -sS -o /dev/null -w '%{http_code}' --config - --max-time 5 "$LOCAL_VERIFY_URL" 2>/dev/null || true)"
    case "$VERIFY_CODE" in
        200) ok "keychain solver token matches the running solver" ;;
        401) warn "keychain solver token does NOT match the running solver; a solver restart would break cookie refresh" ;;
        *) note "keychain solver token check inconclusive (HTTP ${VERIFY_CODE:-none})" ;;
    esac
    unset KEYCHAIN_TOKEN
fi

# --- 2. Probe-host reachability (transport, not tunnel) ---
# Retry once: a transient Mac->EC2 network blip must not page.  Persistent
# transport failures escalate inside transport_failure.
REMOTE_OK=1
run_remote true
if [ "$REMOTE_STATUS" -eq 255 ]; then
    sleep 5
    run_remote true
fi
if [ "$REMOTE_STATUS" -eq 255 ]; then
    transport_failure "$(printf '%s' "$REMOTE_OUT" | tr '\n' ' ' | head -c 200)"
else
    echo 0 > "$TRANSPORT_FAIL_STATE_FILE"
fi

# --- 3. Remote socket roundtrip through the tunnel (EC2 host view) ---
# EC2 reaches the tunnel's Unix socket; socat forwards it over ssh -R back to
# the local solver.  A healthy tunnel returns HTTP 200 with {"ok":true}.
if [ "$REMOTE_OK" -eq 1 ]; then
    run_remote "echo -e 'GET /healthz HTTP/1.0\r\n\r\n' | timeout 8 socat - UNIX-CONNECT:'$REMOTE_SOCKET'"
    if [ "$REMOTE_STATUS" -eq 255 ]; then
        transport_failure "$(printf '%s' "$REMOTE_OUT" | tr '\n' ' ' | head -c 200)"
    elif ! printf '%s' "$REMOTE_OUT" | grep -q '"ok":true'; then
        fail "remote socket roundtrip failed ($SSH_HOST:$REMOTE_SOCKET): $(printf '%s' "$REMOTE_OUT" | tr '\n' ' ' | head -c 200)"
    else
        ok "remote socket roundtrip ($SSH_HOST:$REMOTE_SOCKET)"
    fi
fi

# --- 4. Container socket roundtrip (what the crawler actually uses) ---
# The crawler bind-mounts the socket *directory*.  A container started before a
# tunnel reconnect could still be bound to the previous socket inode if the
# deploy had used a file mount; the directory mount avoids that, and this probe
# proves the live container sees a working socket rather than a stale one.
# The probe authenticates with the container's own configured token against
# /verify, which also catches an EC2-vs-solver token mismatch.
#
# Only probe when the crawler is actually on Unbrowser fetching: a deliberate
# standard-fetching fallback has no mounted socket and must not alarm here.
if [ "$REMOTE_OK" -eq 1 ]; then
    run_remote "docker exec '$CONTAINER_NAME' printenv REDDIT_FETCH_MODE"
    if [ "$REMOTE_STATUS" -eq 255 ]; then
        transport_failure "$(printf '%s' "$REMOTE_OUT" | tr '\n' ' ' | head -c 200)"
    else
        CRAWLER_MODE="$(printf '%s' "$REMOTE_OUT" | tr -d '[:space:]')"
        if [ "$CRAWLER_MODE" != "unbrowser" ]; then
            note "crawler $CONTAINER_NAME is not on unbrowser fetching (REDDIT_FETCH_MODE=${CRAWLER_MODE:-unset}); skipping container socket probe"
        else
            CONTAINER_STATUS=0
            CONTAINER_OUT="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" \
                "docker exec -i -e PROBE_SOCKET='$CONTAINER_SOCKET' '$CONTAINER_NAME' python3 -" <<'PY' 2>&1
import os
import socket

path = os.environ["PROBE_SOCKET"]
token = os.environ.get("UNBROWSER_COOKIE_SERVICE_TOKEN", "")
if not token:
    raise SystemExit("UNBROWSER_COOKIE_SERVICE_TOKEN is not set in the container")

conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
conn.settimeout(8)
try:
    conn.connect(path)
    request = (
        "GET /verify HTTP/1.0\r\nHost: localhost\r\n"
        "X-Reddit-Solver-Token: " + token + "\r\nConnection: close\r\n\r\n"
    )
    conn.sendall(request.encode())
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
    if b"401" in data.split(b"\r\n", 1)[0]:
        raise SystemExit(
            "container token rejected by solver (HTTP 401): "
            "EC2 and the Mac solver tokens do not match"
        )
    raise SystemExit("container /verify did not return ok")
print("container token verify ok")
PY
            )" || CONTAINER_STATUS=$?
            if [ "$CONTAINER_STATUS" -eq 0 ]; then
                ok "container socket roundtrip + token verify ($CONTAINER_NAME:$CONTAINER_SOCKET)"
            elif [ "$CONTAINER_STATUS" -eq 255 ]; then
                transport_failure "$(printf '%s' "$CONTAINER_OUT" | tr '\n' ' ' | head -c 200)"
            else
                fail "container socket roundtrip failed ($CONTAINER_NAME:$CONTAINER_SOCKET): $(printf '%s' "$CONTAINER_OUT" | tr '\n' ' ' | head -c 200)"
            fi
        fi
    fi
fi

# --- 5. launchd restart churn ---
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

if [ "$REMOTE_OK" -eq 1 ]; then
    ok "cookie tunnel healthy"
else
    note "cookie tunnel probe incomplete: probe host unreachable, remote checks skipped"
fi
