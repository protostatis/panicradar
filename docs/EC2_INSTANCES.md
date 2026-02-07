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
- Docker containers inherit VPN routing transparently via host NAT
- Two `PostUp` mechanisms keep non-VPN traffic working correctly:

#### SSH split routing (ip rule)

WireGuard's `AllowedIPs = 0.0.0.0/0` would normally route ALL traffic through
the VPN, including SSH replies — which would lock you out. The `PostUp` adds:

```
ip rule add from <EC2_PRIVATE_IP> table main priority 90
```

This tells the kernel: "packets originating from the EC2's own IP should use
the normal routing table (eth0), not the VPN." SSH replies have the EC2's IP
as source, so they bypass the VPN and reach your client normally.

#### Connmark routing (iptables) — Docker + VPN coexistence

The SSH rule above only covers traffic from the EC2's own IP (172.31.x.x).
Docker containers use a different IP range (172.18.0.x), so their response
packets to incoming HTTP requests would still get routed through the VPN —
making the dashboard unreachable from outside.

**The problem in detail:**

```
1. Client visits dashboard → SYN arrives at eth0 → Docker NAT → container (172.18.0.3)
2. Container sends SYN-ACK → source IP is 172.18.0.3 (Docker bridge)
3. Kernel routing: 172.18.0.3 doesn't match the SSH split rule (172.31.x.x)
4. Falls through to WireGuard routing → sent through VPN tunnel
5. Client never receives the response → connection timeout
```

**The fix — connmark:** Linux's connection tracking (conntrack) remembers every
TCP/UDP connection. Connmark lets you "tag" a connection and later apply that
tag to individual packets for routing decisions.

Two iptables rules in `PostUp` solve this:

```bash
# Rule 1: When a NEW connection arrives on eth0, stamp it with mark 0xca6c
iptables -t mangle -A PREROUTING -i eth0 -m conntrack --ctstate NEW -j CONNMARK --set-mark 0xca6c

# Rule 2: For every packet, copy its connection's mark onto the packet itself
iptables -t mangle -A PREROUTING -j CONNMARK --restore-mark
```

How it plays out:

```
1. Client SYN arrives on eth0     → conntrack creates entry, stamped 0xca6c
2. Container sends SYN-ACK        → conntrack recognizes same connection
                                   → restores fwmark 0xca6c onto the packet
3. WireGuard rule: "fwmark 0xca6c → skip VPN"
4. Packet routes through eth0     → client gets the response ✓
```

`0xca6c` is the same fwmark WireGuard uses internally to avoid routing loops.
By reusing it, incoming-connection responses get the same "bypass VPN" treatment.

Meanwhile, outbound traffic from the crawler originates from Docker (not eth0),
so it has **no** connmark and still routes through the VPN as intended.

#### Service bypass routes

Some AWS and external services don't work through the VPN and need explicit
bypass routes through eth0:

| Route | Why |
|-------|-----|
| `140.82.112.0/20` | GitHub API — ghcr.io blocks Mullvad IPs, breaking `docker pull` during deploys |
| `185.199.108.0/22` | GitHub CDN (pkg-containers.githubusercontent.com) — same issue |
| `169.254.169.254` | EC2 instance metadata — required for IAM credential retrieval (S3 backups, AWS CLI) |

These are added in `PostUp` and removed in `PostDown` automatically by the
setup script.

**Instance metadata (169.254.169.254):** EC2 instances get IAM credentials by
querying `http://169.254.169.254/latest/meta-data/`. This is a link-local
address handled by the hypervisor on the local network interface (eth0). When
the VPN routes all traffic (`AllowedIPs = 0.0.0.0/0`), metadata requests get
sent through the WireGuard tunnel instead, where they fail — the Mullvad server
has no idea what `169.254.169.254` is. Without this route, `aws s3 cp` and any
AWS SDK call fails with "Unable to locate credentials" because the SDK can't
reach the metadata endpoint to fetch the IAM role's temporary credentials.

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

### S3 Backup Failing ("Unable to locate credentials")
The VPN is routing instance metadata requests through the tunnel. Verify:
```bash
# Should return IAM role info — if it hangs, the route is missing
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```
Fix by re-running the WireGuard setup script (which adds the metadata bypass route):
```bash
bash deploy/setup-wireguard.sh .env
```

### Dashboard Not Accessible (but SSH works)
This likely means the VPN conntrack rules are missing. The WireGuard `PostUp` must include iptables connmark rules so Docker response packets route back through eth0 instead of through the VPN tunnel. Re-run:
```bash
bash deploy/setup-wireguard.sh .env
```
