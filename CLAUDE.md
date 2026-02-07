# Claude Code Reminders

## Git Workflow

- **Never push directly to main.** Always create a feature branch and open a PR.
- **Never rebase.** Use merge commits only (`git pull` or `git merge`, not `git pull --rebase`).
- Use descriptive branch names (e.g., `fix/vader-removal`, `feat/new-collector`)

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
