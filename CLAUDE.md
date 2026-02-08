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

## Reddit Access via WireGuard VPN

Reddit blocks AWS/EC2 IP addresses. A WireGuard VPN on the EC2 host routes all
outbound traffic through a clean IP (Mullvad VPN).

### Setup (one-time):

1. Add WireGuard config to `/opt/crypto-sentiment/.env` (see `.env.example` for template)
2. Run `deploy/setup-wireguard.sh` on EC2

### Verify VPN is active:

```bash
# Should show Mullvad IP, not EC2 IP
curl https://httpbin.org/ip

# Check WireGuard status
sudo wg show
```

### If crawler shows "No fresh posts" or 403 errors:
- VPN may be down: `sudo wg-quick up wg0`
- Check status: `sudo systemctl status wg-quick@wg0`

### If VPN key is lost:
Generate a new one — no backup needed:
```bash
wg genkey | tee /tmp/wg_private.key | wg pubkey > /tmp/wg_public.key
curl -X POST https://api.mullvad.net/wg/ \
  -d account=YOUR_ACCOUNT_NUMBER \
  --data-urlencode "pubkey=$(cat /tmp/wg_public.key)"
```
Update `WG_PRIVATE_KEY` and `WG_ADDRESS` in `.env`, then re-run `deploy/setup-wireguard.sh`.
