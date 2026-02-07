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

## Creating a New EC2 Instance

### 1. Launch Configuration

- **AMI:** Amazon Linux 2 AMI
- **Instance Type:** t3.small (minimum for Docker)
- **Storage:** 40GB gp3
- **Security Group:** Allow ports 22, 80, 443, 8000

### 2. User Data Script (IMPORTANT)

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

# Install git
yum install -y git

# Create 2GB swap (prevents OOM during deployments)
dd if=/dev/zero of=/swapfile bs=128M count=16
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

# Install socat (for proxy tunnel)
yum install -y socat
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
5. **Set up proxy tunnel** (see PROXY_SETUP.md)

---

## Proxy Tunnel Setup

Reddit blocks AWS IPs. The crawler needs a proxy through your local Mac.

```bash
# 1. Start local proxy (on Mac)
python3 /tmp/simple_proxy.py &

# 2. Create SSH tunnel (on Mac)
ssh -i ~/.ssh/panicradar-ec2.pem -R 18888:127.0.0.1:18888 -N -f ec2-user@34.236.47.243

# 3. Start socat on EC2
ssh -i ~/.ssh/panicradar-ec2.pem ec2-user@34.236.47.243 \
  "nohup socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888 &"
```

See `docs/PROXY_SETUP.md` for full details.

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
