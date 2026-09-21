# Reddit Unbrowser Cookie Transport

Reddit blocks the crawler's normal HTTP client from EC2. The crawler uses
Unbrowser over direct EC2 egress for existing `old.reddit.com` listing, thread,
and comment parsing. It asks a Mac-only solver for fresh cookies only after
Reddit returns a `403` or an HTTP-200 blocked/welcome page.

The integration does not intentionally log cookie values or write them to its
database. The Unbrowser client clears its cookies on orderly shutdown, but its
behavior after a crash must be treated as runtime-dependent; use an ephemeral
crawler image filesystem and do not rely on that cleanup as a security boundary.

## Prerequisites

- Use the dedicated `reddit-crawler` **Unchained sandbox profile** below with
  its own Reddit-only account. Do not use a personal Chrome or Reddit account.
  The solver defaults to this isolated sandbox; `--use-existing-profile` is
  only for a separately reviewed dedicated profile.
- The tested minimum allowlist is `reddit_session`. It is an authenticated
  session cookie, so export it only from the dedicated crawler account. Do not
  allow `token_v2` or cookies from a personal profile.
- Run the solver and SSH forward under a supervisor such as `launchd` with
  restart-on-failure. Manual terminal processes are for diagnostics only.

## Configure the shared solver token

Generate one random token on the Mac. Do not pass it on a command line or add
it to the repository. This export is for a manual foreground diagnostic only.

```bash
export REDDIT_COOKIE_SOLVER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
/usr/bin/security add-generic-password -U \
  -a reddit-crawler \
  -s panicradar-reddit-solver-token \
  -w "$REDDIT_COOKIE_SOLVER_TOKEN"
```

Put the same value in EC2's protected crawler environment file:

```bash
sudo touch /opt/crypto-sentiment/.env
sudo chmod 600 /opt/crypto-sentiment/.env
sudoedit /opt/crypto-sentiment/.env
# UNBROWSER_COOKIE_SERVICE_TOKEN=<the generated value>
```

Keep any existing contents of that file. The deployment passes it only to the
crawler and its short-lived canary container.

## Mac setup

Run the solver on loopback only. `--cookie-name` is required and can be repeated
only for the minimal, reviewed cookie set from the dedicated profile.

```bash
cd /path/to/crypto_sentiment_crawler
python3 scripts/reddit_cookie_solver.py \
  --profile reddit-crawler \
  --cookie-name reddit_session
```

The manual solver reads the token from `REDDIT_COOKIE_SOLVER_TOKEN`. The
launchd-managed solver reads the same token from macOS Keychain service
`panicradar-reddit-solver-token`, account `reddit-crawler`. The solver does not
return cookies from arbitrary domains or cookie names outside this allowlist.
It launches Chrome headlessly by default; use `--headed` only for local
diagnostics.

Create a remote Unix-socket forward to EC2. Replace `panicradar` with the
existing SSH host alias if needed.

```bash
ssh -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o StreamLocalBindUnlink=yes \
  -o StreamLocalBindMask=0177 \
  -R /opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock:127.0.0.1:18765 \
  -N panicradar
```

The runtime socket lives in the dedicated EC2 directory
`/opt/crypto-sentiment/run/reddit-solver/`, and the crawler container mounts
that directory (not the socket file) read-only at `/run/reddit-solver`. sshd
recreates the socket inode on every tunnel reconnect, so a single-file bind
mount would keep pointing at a stale inode after any reconnect and silently
break cookie refresh until the container was restarted. Do not create a TCP
bridge or set `UNBROWSER_COOKIE_SERVICE_URL` in production.

## macOS supervision

The solver and socket forward must run under `launchd`, not in terminal tabs.
The entrypoints retrieve only the solver token from the macOS Keychain; the
Reddit account password is not sent to EC2.

Install the templates after the repository is at its durable checkout path:

```bash
REPO_PATH=/path/to/crypto_sentiment_crawler
PLIST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/PanicRadar"
mkdir -p "$PLIST_DIR" "$LOG_DIR"

python3 - "$REPO_PATH" "$PLIST_DIR" "$LOG_DIR" <<'PY'
from pathlib import Path
import sys

repo_path, plist_dir, log_dir = map(Path, sys.argv[1:])
for name in (
    "ai.panicradar.reddit-cookie-solver.plist",
    "ai.panicradar.reddit-cookie-tunnel.plist",
):
    source = repo_path / "deploy" / "launchd" / name
    target = plist_dir / name
    target.write_text(
        source.read_text()
        .replace("__REPO_PATH__", str(repo_path))
        .replace("__HOME__", str(Path.home()))
    )
PY

for label in reddit-cookie-solver reddit-cookie-tunnel; do
  launchctl bootout "gui/$(id -u)/ai.panicradar.$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_DIR/ai.panicradar.$label.plist"
done
```

Verify both agents after installation:

```bash
launchctl print "gui/$(id -u)/ai.panicradar.reddit-cookie-solver"
launchctl print "gui/$(id -u)/ai.panicradar.reddit-cookie-tunnel"
```

The tunnel entrypoint ensures its fixed EC2 socket directory exists and removes
only the fixed stale socket before each supervised reconnect, so a prior unclean
SSH exit does not block recovery.

## Verification

On EC2, verify socket reachability without requesting cookies:

```bash
curl --unix-socket /opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock \
  http://localhost/healthz
stat -c '%a:%U:%G' /opt/crypto-sentiment/run/reddit-solver/reddit-cookie-solver.sock
```

The expected metadata is mode `600` and the deployment SSH user's owner/group.

Verify the socket from the crawler's point of view as well, since that is the
path that can go stale after a tunnel reconnect:

```bash
docker exec crypto-crawler \
  python3 -c 'import socket; s=socket.socket(socket.AF_UNIX); s.connect("/run/reddit-solver/reddit-cookie-solver.sock"); print("ok")'
```

`scripts/check_cookie_tunnel.sh` runs both probes, plus a token-authenticated
container probe (`/verify`), a keychain-to-running-solver token check (manual
runs only: a cron session cannot read the login keychain), and launchd
restart-churn detection, so prefer it for routine checks. A probe-host
network failure (ssh exit 255) is retried once and then logged without paging
until it persists across several consecutive probes; only tunnel-level
failures page immediately. The release workflow verifies the socket,
token-authenticated cookie solver, and a crawlable `old.reddit.com` listing
before enabling Unbrowser for the new crawler. The host remains on direct EC2
networking; WireGuard is not required.

If the solver is unavailable or canary fails, deployment continues with standard
Reddit fetching so unrelated API, frontend, and security releases remain
available. Reddit collection will be degraded until the supervised solver and
forward are restored.

## Failure behavior

- `403` or an HTTP-200 blocked/welcome page: crawler requests one cookie
  refresh, retries once, then opens a ten-minute refresh circuit breaker if
  Reddit remains unusable.
- `429`: crawler does **not** invoke the solver and observes a bounded cooldown.
- Private, banned, or quarantined subreddits: the transport classifies the
  subreddit-level denial page (for example `<title>CryptoTech: private</title>`)
  separately from the datacenter block page. These are not cookie problems, so
  the crawler does not treat them as refresh failures, and source discovery
  rejects such candidates instead of re-probing them on every discovery run.
- Solver/tunnel outage: only Reddit collection degrades; no cookie values are
  logged and unrelated services continue running.
