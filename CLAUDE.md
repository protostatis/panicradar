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

### Rollback procedure

If a release breaks something, roll back to the previous version:

```bash
# 1. Find the previous version tag on GHCR
#    Images are tagged as ghcr.io/protostatis/crypto-sentiment-{name}:v1.X.Y

# 2. SSH into EC2
ssh ec2-user@<EC2_IP>

# 3. Pull only the broken image's previous version and restart that container
#    e.g. frontend-only rollback:
docker pull ghcr.io/protostatis/crypto-sentiment-frontend:v1.5.0
docker tag ghcr.io/protostatis/crypto-sentiment-frontend:v1.5.0 crypto-sentiment-frontend:latest
cd /opt/crypto-sentiment && docker-compose up -d frontend

# 4. Full rollback (pull all four images at previous version):
VERSION=v1.5.0
for svc in crawler api frontend game-server; do
  docker pull ghcr.io/protostatis/crypto-sentiment-${svc}:${VERSION}
  docker tag ghcr.io/protostatis/crypto-sentiment-${svc}:${VERSION} crypto-sentiment-${svc}:latest
done
cd /opt/crypto-sentiment && docker-compose up -d
```

**Do NOT restore the DB** unless there's actual corruption (no schema migrations were applied).

### Manual deploy (legacy)

`deploy/push-to-ec2.sh <EC2_IP>` — packages local code, uploads via SCP, rebuilds on EC2. Only use if CI/CD is broken.

## Reddit Access via WireGuard VPN

Reddit blocks AWS/EC2 IP addresses. A WireGuard VPN on the EC2 host routes
outbound crawler traffic through a clean IP.

### Setup (one-time):

1. Add WireGuard config to `/opt/crypto-sentiment/.env` (see `.env.docker.example` for template).
2. Run `deploy/setup-wireguard.sh /opt/crypto-sentiment/.env` on EC2.

### Verify VPN is active:

```bash
# Should show the VPN egress IP, not the EC2 IP
curl https://httpbin.org/ip

# Check WireGuard status
sudo wg show
```

### If crawler shows "No fresh posts" or 403 errors:
- VPN may be down: `sudo wg-quick up wg0`.
- Check status: `sudo systemctl status wg-quick@wg0`.
