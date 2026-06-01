# Claude Code Reminders

## Git Workflow

- **Never push directly to main.** Always create a feature branch and open a PR.
- **Never rebase.** Use merge commits only (`git pull` or `git merge`, not `git pull --rebase`).
- Use descriptive branch names (e.g., `fix/vader-removal`, `feat/new-collector`)

## CI/CD & Deployment

### Pipeline overview

1. **CI (on every push/PR to main):** `.github/workflows/ci.yml`
   - Runs backend tests (pytest, ruff, mypy)
   - Runs frontend lint + build
   - Builds Docker images (crawler, api, frontend) — no push

2. **Deploy (on release publish):** `.github/workflows/deploy.yml`
   - Builds and pushes Docker images to `ghcr.io/protostatis/crypto-sentiment-{crawler,api,frontend}`
   - SSHes into EC2 via `appleboy/ssh-action` using repository secrets (`EC2_HOST`, `EC2_USERNAME`, `EC2_SSH_KEY`)
   - On EC2: backs up DB, prunes Docker, pulls new images, restarts all 3 containers, verifies health

### How to release

```bash
# 1. Merge your PR into main
gh pr merge <PR_NUMBER> --merge

# 2. Pull latest main
git checkout main && git pull

# 3. Create a GitHub release (triggers deploy)
gh release create v1.X.0 --title "v1.X.0 — Description" --notes "Release notes here"
```

The release triggers the deploy workflow automatically. Monitor progress at:
`https://github.com/protostatis/panicradar/actions`

### Manual deploy (legacy)

`deploy/push-to-ec2.sh <EC2_IP>` — packages local code, uploads via SCP, rebuilds on EC2. Only use if CI/CD is broken.

## Reddit Access via Residential Proxy

Reddit blocks AWS/EC2 IP addresses. The crawler uses an app-level residential
proxy for `reddit.com` domains instead of a host-level WireGuard VPN.

### Setup (one-time):

1. Add `RESIDENTIAL_PROXY` to `/opt/crypto-sentiment/.env`, reusing the same value as searchagentsky.com.
2. Use `PROXY_URL` only if the crawler needs a different proxy; it takes precedence over `RESIDENTIAL_PROXY`.
3. Disable the legacy VPN if it is still enabled: `sudo systemctl disable --now wg-quick@wg0`.

### Verify proxy access:

```bash
PROXY="${PROXY_URL:-$RESIDENTIAL_PROXY}"
curl -x "$PROXY" https://httpbin.org/ip
curl -sL -x "$PROXY" -A "Mozilla/5.0" \
  https://old.reddit.com/r/bitcoin/new/ | grep -c "data-timestamp"
```

### If crawler shows "No fresh posts" or 403 errors:
- Confirm `docker exec crypto-crawler printenv RESIDENTIAL_PROXY` returns the proxy URL.
- Confirm Reddit returns posts through the proxy with the verification command above.
