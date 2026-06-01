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
7. **Set up WireGuard VPN for Reddit** (see below)
8. **Deploy the application** using `deploy/push-to-ec2.sh` or CI/CD
9. **Set up daily S3 backup cron:**
   ```bash
   crontab -e
   # Add: 0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh
   ```

---

## WireGuard VPN Setup

Reddit blocks AWS/datacenter IPs. WireGuard runs on the EC2 host and routes
outbound crawler traffic through the VPN. Docker containers inherit that route
through host NAT.

### Setup

1. **Add WireGuard config to `/opt/crypto-sentiment/.env`** on EC2:
   ```bash
   WG_PRIVATE_KEY=your_wireguard_private_key
   WG_ADDRESS=10.x.x.x/32
   WG_DNS=10.64.0.1
   WG_PEER_PUBKEY=server_public_key
   WG_ENDPOINT=server_ip:51820
   ```

2. **Run the setup script:**
   ```bash
   cd /home/ec2-user/crypto_sentiment_crawler
   bash deploy/setup-wireguard.sh /opt/crypto-sentiment/.env
   ```

3. **Deploy the application.** Release deploys also run the setup script after
   Docker images are pulled and before the crawler starts.

4. **Verify:**
   ```bash
   # Should show the VPN egress IP, not the EC2 IP
   curl https://ipinfo.io/ip

   # Should return a count greater than 0
   curl -sL -A "Mozilla/5.0" \
     https://old.reddit.com/r/cryptocurrency/new/ | grep -c "data-timestamp"

   sudo wg show
   ```

### Behavior

`Fetcher` does not proxy Reddit by default. Reddit traffic leaves the crawler
container through the EC2 host VPN. `PROXY_URL` remains available only as an
explicit override for future non-VPN proxy use.

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

### Reddit VPN Issues
```bash
# Check VPN status
sudo wg show
sudo systemctl status wg-quick@wg0

# Check VPN egress IP
curl https://ipinfo.io/ip

# Check Reddit through VPN
curl -sL -A "Mozilla/5.0" \
  https://old.reddit.com/r/bitcoin/new/ | grep -c "data-timestamp"
```

### S3 Backup Failing ("Unable to locate credentials")
Verify the instance can reach EC2 metadata:
```bash
# Should return IAM role info — if it hangs, the route is missing
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```
If it fails, re-run the WireGuard setup script to restore the metadata bypass
route:

```bash
bash deploy/setup-wireguard.sh /opt/crypto-sentiment/.env
```

### Dashboard Not Accessible (but SSH works)
If Docker response packets route through the VPN, the WireGuard connmark rules
are missing. Re-run setup:
```bash
bash deploy/setup-wireguard.sh /opt/crypto-sentiment/.env
```
