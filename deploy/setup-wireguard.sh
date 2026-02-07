#!/bin/bash
# Setup WireGuard VPN on EC2 for Reddit access
# Reads configuration from environment variables or .env file
#
# Required env vars:
#   WG_PRIVATE_KEY  - WireGuard private key
#   WG_ADDRESS      - VPN address (e.g., 10.x.x.x/32)
#   WG_DNS          - DNS server (e.g., 10.64.0.1)
#   WG_PEER_PUBKEY  - Server public key
#   WG_ENDPOINT     - Server endpoint (e.g., server_ip:51820)

set -e

# Load .env if it exists
ENV_FILE="${1:-.env}"
if [ -f "$ENV_FILE" ]; then
    echo "Loading config from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
fi

# Validate required vars
for var in WG_PRIVATE_KEY WG_ADDRESS WG_DNS WG_PEER_PUBKEY WG_ENDPOINT; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var is not set"
        exit 1
    fi
done

# Install wireguard-tools if needed
if ! command -v wg &> /dev/null; then
    echo "Installing wireguard-tools..."
    sudo yum install -y wireguard-tools
fi

# Detect EC2 private IP for SSH split routing
EC2_IP=$(hostname -I | awk '{print $1}')
echo "EC2 private IP: $EC2_IP"

# Write WireGuard config
echo "Writing /etc/wireguard/wg0.conf..."
sudo bash -c "cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $WG_PRIVATE_KEY
Address = $WG_ADDRESS
DNS = $WG_DNS
PostUp = /sbin/ip rule add from $EC2_IP table main priority 90
PostDown = /sbin/ip rule del from $EC2_IP table main priority 90

[Peer]
PublicKey = $WG_PEER_PUBKEY
Endpoint = $WG_ENDPOINT
AllowedIPs = 0.0.0.0/0
EOF"

sudo chmod 600 /etc/wireguard/wg0.conf

# Stop existing VPN if running
sudo wg-quick down wg0 2>/dev/null || true

# Start VPN
echo "Starting WireGuard..."
sudo wg-quick up wg0

# Enable on boot
sudo systemctl enable wg-quick@wg0 2>/dev/null || true

# Verify
echo ""
echo "=== Verification ==="
VPN_IP=$(curl -s --max-time 10 https://httpbin.org/ip | grep -oP '"origin": "\K[^"]+' 2>/dev/null || echo "failed")
echo "VPN IP: $VPN_IP"
echo "EC2 IP: $EC2_IP"

if [ "$VPN_IP" != "failed" ] && [ "$VPN_IP" != "$EC2_IP" ]; then
    echo "WireGuard VPN is active."
else
    echo "WARNING: VPN may not be working. Check 'sudo wg show'."
fi
