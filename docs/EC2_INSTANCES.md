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

# Install git and wireguard-tools
yum install -y git wireguard-tools

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
7. **Configure residential proxy for Reddit** (see below)
8. **Deploy the application** using `deploy/push-to-ec2.sh` or CI/CD
9. **Set up daily S3 backup cron:**
   ```bash
   crontab -e
   # Add: 0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh
   ```

---

## Residential Proxy Setup

Reddit blocks AWS/datacenter IPs. The crawler now uses an app-level residential
HTTP proxy for Reddit domains instead of routing the whole host through
WireGuard.

### Setup

1. **Add the proxy to `/opt/crypto-sentiment/.env`** on EC2:
   ```bash
   # Preferred: reuse the searchagentsky.com value
   RESIDENTIAL_PROXY=http://user:pass@proxy.example.com:8080

   # Optional override. If set, this takes precedence over RESIDENTIAL_PROXY.
   PROXY_URL=http://user:pass@proxy.example.com:8080
   ```

2. **Disable the old host VPN if it is still enabled:**
   ```bash
   sudo systemctl disable --now wg-quick@wg0
   ```

3. **Deploy the application.** The release deploy passes `/opt/crypto-sentiment/.env`
   into the crawler container and stops `wg-quick@wg0` automatically when a proxy
   is configured.

4. **Verify:**
   ```bash
   set -a; . /opt/crypto-sentiment/.env; set +a
   PROXY="${PROXY_URL:-$RESIDENTIAL_PROXY}"

   # Should show the residential proxy egress IP
   curl -x "$PROXY" https://ipinfo.io/ip

   # Should return a count greater than 0
   curl -sL -x "$PROXY" \
     -A "Mozilla/5.0" \
     https://old.reddit.com/r/cryptocurrency/new/ | grep -c "data-timestamp"

   # The crawler container should have the proxy env
   docker exec crypto-crawler printenv RESIDENTIAL_PROXY
   ```

### Behavior

`Fetcher` proxies `reddit.com` and all subdomains, including `old.reddit.com`.
Other crawler sources continue to fetch directly unless code explicitly forces a
proxy. `PROXY_URL` is useful if you want a crawler-specific proxy; otherwise use
the shared `RESIDENTIAL_PROXY` value from searchagentsky.com.

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

### Reddit Proxy Issues
```bash
set -a; . /opt/crypto-sentiment/.env; set +a
PROXY="${PROXY_URL:-$RESIDENTIAL_PROXY}"

# Confirm proxy env exists on host
grep -E '^(PROXY_URL|RESIDENTIAL_PROXY)=' /opt/crypto-sentiment/.env

# Confirm proxy env exists in crawler container
docker exec crypto-crawler printenv RESIDENTIAL_PROXY

# Check proxy egress IP
curl -x "$PROXY" https://ipinfo.io/ip

# Check Reddit through proxy
curl -sL -x "$PROXY" -A "Mozilla/5.0" \
  https://old.reddit.com/r/bitcoin/new/ | grep -c "data-timestamp"
```

### S3 Backup Failing ("Unable to locate credentials")
Verify the instance can reach EC2 metadata:
```bash
# Should return IAM role info — if it hangs, the route is missing
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```
If it fails and WireGuard is still active, disable the legacy VPN with
`sudo systemctl disable --now wg-quick@wg0`.

### Dashboard Not Accessible (but SSH works)
If WireGuard is still active from the old setup, Docker responses may route
through the VPN. Disable the legacy VPN:
```bash
sudo systemctl disable --now wg-quick@wg0
```
