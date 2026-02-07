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
7. **Set up WireGuard VPN** (see below)
8. **Deploy the application** using `deploy/push-to-ec2.sh` or CI/CD
9. **Set up daily S3 backup cron:**
   ```bash
   crontab -e
   # Add: 0 0 * * * /home/ec2-user/crypto_sentiment_crawler/deploy/backup-db.sh
   ```

---

## WireGuard VPN Setup

Reddit blocks AWS/datacenter IPs. WireGuard VPN routes outbound traffic through a Mullvad VPN server so the crawler can access `old.reddit.com`.

### How it works

- WireGuard runs on the EC2 **host** (not inside Docker)
- `AllowedIPs = 0.0.0.0/0` routes all outbound traffic through the VPN
- SSH split routing (`PostUp` ip rule) ensures SSH replies use eth0, not the VPN
- Conntrack marking (`PostUp` iptables rules) ensures incoming HTTP responses route back through eth0 to clients (not through VPN)
- Docker containers inherit VPN routing transparently via host NAT

### Setup

1. **Add WireGuard config to `.env`** on the EC2:
   ```
   WG_PRIVATE_KEY=<your_wireguard_private_key>
   WG_ADDRESS=10.x.x.x/32
   WG_DNS=10.64.0.1
   WG_PEER_PUBKEY=<mullvad_server_public_key>
   WG_ENDPOINT=<mullvad_server_ip>:51820
   ```

2. **Run the setup script:**
   ```bash
   cd /opt/crypto-sentiment
   bash deploy/setup-wireguard.sh .env
   ```

3. **Verify:**
   ```bash
   # Should show Mullvad IP (not EC2 IP)
   curl https://ipinfo.io/ip

   # Should return Reddit HTML (200)
   curl -L -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
     https://old.reddit.com/r/cryptocurrency/

   # Dashboard should be accessible from outside
   curl -I http://<ELASTIC_IP>/
   ```

### Key recovery

If the EC2 is terminated and you lose the WireGuard private key:

1. Generate a new key pair:
   ```bash
   wg genkey | tee /tmp/wg_private.key | wg pubkey > /tmp/wg_public.key
   ```
2. Register with Mullvad:
   ```bash
   curl -sSL https://api.mullvad.net/wg/ \
     -d account=YOUR_ACCOUNT_NUMBER \
     --data-urlencode pubkey="$(cat /tmp/wg_public.key)"
   ```
3. Use the returned address as `WG_ADDRESS` and the private key as `WG_PRIVATE_KEY`

### Changing VPN servers

Not all Mullvad servers work for Reddit. Known working US servers:
- Atlanta: endpoint `45.134.140.130:51820`
- Seattle: endpoint `138.199.43.91:51820`
- Chicago: endpoint `87.249.134.1:51820`

Server public keys can be found at: https://api.mullvad.net/www/relays/wireguard/

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

### VPN Issues
```bash
# Check VPN status
sudo wg show

# Check routing rules
sudo /sbin/ip rule list

# Check outbound IP
curl https://ipinfo.io/ip

# Restart VPN
sudo wg-quick down wg0 && sudo wg-quick up wg0
```

### Dashboard Not Accessible (but SSH works)
This likely means the VPN conntrack rules are missing. The WireGuard `PostUp` must include iptables connmark rules so Docker response packets route back through eth0 instead of through the VPN tunnel. Re-run:
```bash
bash deploy/setup-wireguard.sh .env
```
