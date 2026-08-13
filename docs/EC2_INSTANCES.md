# EC2 Instance Setup

## Current Production

| Property | Value |
|----------|-------|
| **Name** | panicradar-prod |
| **Instance ID** | i-06541a97dc2c502c6 |
| **Elastic IP** | 34.236.47.243 |
| **Instance Type** | t3.small (2GB RAM) |
| **Region** | us-east-1 |
| **Key Pair** | panicradar-key |
| **SSH Key Path** | ~/.ssh/panicradar-ec2.pem |
| **Domain** | panicradar.ai |

**SSH Command:**
```bash
ssh -i ~/.ssh/panicradar-ec2.pem ec2-user@34.236.47.243
```

---

## Creating a New EC2 Instance (Clean Start)

### 1. Launch Configuration

- **AMI:** Amazon Linux 2 AMI
- **Instance Type:** t3.small (minimum for Docker)
- **Storage:** 40GB gp3
- **Security Group:** Allow ports 22, 80, 443, 8000

### 2. User Data Script

When launching, paste this in **Advanced Details → User Data**:

```bash
#!/bin/bash
# Update system
yum update -y

# Install Docker
amazon-linux-extras install docker -y
systemctl start docker
systemctl enable docker
usermod -a -G docker ec2-user

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Install git
yum install -y git

# Create 2GB swap (prevents OOM during deployments)
dd if=/dev/zero of=/swapfile bs=128M count=16
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
```

### 3. After Launch

1. **Allocate Elastic IP** and associate with instance
2. **Update DNS** (panicradar.ai A record → Elastic IP)
3. **Update GitHub Secrets:**
   - `EC2_HOST` → new Elastic IP
   - `EC2_SSH_KEY` → private key content
4. **Set up SSL certificate:**
   ```bash
   sudo yum install -y certbot
   sudo certbot certonly --standalone -d panicradar.ai -d www.panicradar.ai
   ```
5. **Create application directory:**
   ```bash
   sudo mkdir -p /opt/crypto-sentiment
   sudo chown ec2-user:ec2-user /opt/crypto-sentiment
   ```
6. **Create `.env` file** at `/opt/crypto-sentiment/.env` with API keys (see `.env.docker.example` for template)
7. **Set up the Reddit Unbrowser solver** (see `REDDIT_UNBROWSER_SETUP.md`)
8. **Deploy the application** using `deploy/push-to-ec2.sh` or CI/CD
9. **Set up daily S3 backup cron:**
   ```bash
   crontab -e
   # Add: 0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh
   ```

---

## Production Egress

The host and Docker containers use direct EC2 egress for CoinGecko, Telegram,
macro data, on-chain APIs, and Unbrowser navigation. Reddit cookies come from
the supervised solver described in `REDDIT_UNBROWSER_SETUP.md`; no host-wide
VPN is required.

Existing hosts previously configured with WireGuard must retire the full
tunnel before running collectors:

```bash
sudo systemctl disable --now wg-quick@wg0 2>/dev/null || true
if ip link show wg0 >/dev/null 2>&1; then
  sudo wg-quick down wg0
fi
sudo rm -f /etc/wireguard/wg0.conf

getent ahostsv4 api.coingecko.com
curl -fsS https://api.coingecko.com/api/v3/ping
```

Release and legacy deployment scripts perform this cleanup automatically.

---

## Troubleshooting

### Instance Unresponsive
If SSH/HTTP timeout, the instance likely ran out of memory:
```bash
# Force stop and start via AWS CLI
aws ec2 stop-instances --instance-ids i-06541a97dc2c502c6 --force
aws ec2 wait instance-stopped --instance-ids i-06541a97dc2c502c6
aws ec2 start-instances --instance-ids i-06541a97dc2c502c6
```

### Check Resources
```bash
# Memory
free -h

# Disk
df -h

# Swap (should show 2GB)
swapon --show
```

### Reddit Collection Issues
```bash
# Check the solver socket without requesting cookie values
curl --unix-socket /opt/crypto-sentiment/run/reddit-cookie-solver.sock \
  http://localhost/healthz

# Confirm the crawler is using Unbrowser
docker exec crypto-crawler sh -c 'test "$REDDIT_FETCH_MODE" = unbrowser'
```

Anonymous Reddit HTML can return `403`. Follow `REDDIT_UNBROWSER_SETUP.md` to
restore the supervised solver and socket forward.

### All Outbound Feeds Stop Updating

Check DNS from both the host and crawler. A legacy `wg0` interface must not be
present:

```bash
getent ahostsv4 api.coingecko.com
docker exec crypto-crawler getent ahostsv4 api.coingecko.com
ip link show wg0  # expected: device does not exist
```

If `wg0` exists, disable it using the Production Egress commands above, then
restart only the outbound workers so Docker refreshes their resolver state:

```bash
docker restart -t 120 crypto-crawler crypto-signals
```

### S3 Backup Failing ("Unable to locate credentials")
Verify the instance can reach EC2 metadata:
```bash
# Should return IAM role info — if it hangs, the route is missing
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```
With direct EC2 egress, a failure indicates an IAM role, metadata option, or
instance networking problem.

### Dashboard Not Accessible (but SSH works)
Check the frontend container and local HTTPS endpoint:
```bash
docker ps --filter name=crypto-frontend
curl -kfsS https://localhost/ >/dev/null
```
