#!/bin/bash
# Push application to EC2 and deploy
# Usage: ./push-to-ec2.sh <EC2_IP> [KEY_PATH]

set -e

EC2_IP="${1:-}"
KEY_PATH="${2:-~/.ssh/crypto-sentiment-key.pem}"
REMOTE_DIR="/opt/crypto-sentiment"

if [ -z "$EC2_IP" ]; then
    echo "Usage: $0 <EC2_IP> [KEY_PATH]"
    echo "Example: $0 54.123.45.67"
    exit 1
fi

echo "=== Deploying to EC2: $EC2_IP ==="

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Create deployment package
echo ""
echo "Creating deployment package..."
DEPLOY_TMP=$(mktemp -d)
mkdir -p "$DEPLOY_TMP/app"

# Copy necessary files
cp -r crypto_sentiment_crawler "$DEPLOY_TMP/app/"
cp -r dashboard-frontend "$DEPLOY_TMP/app/"
cp Dockerfile "$DEPLOY_TMP/app/"
cp docker-compose.yml "$DEPLOY_TMP/app/"
cp pyproject.toml "$DEPLOY_TMP/app/"
cp uv.lock "$DEPLOY_TMP/app/" 2>/dev/null || true
cp roadmap.md "$DEPLOY_TMP/app/"
cp .dockerignore "$DEPLOY_TMP/app/"
cp .env.docker.example "$DEPLOY_TMP/app/.env.example"
cp -r deploy "$DEPLOY_TMP/app/"

# Create tarball
TARBALL="$DEPLOY_TMP/crypto-sentiment.tar.gz"
tar -czf "$TARBALL" -C "$DEPLOY_TMP" app

echo "Package size: $(du -h "$TARBALL" | cut -f1)"

# Upload to EC2
echo ""
echo "Uploading to EC2..."
scp -i "$KEY_PATH" -o StrictHostKeyChecking=no "$TARBALL" "ec2-user@$EC2_IP:/tmp/"

# Deploy on EC2
echo ""
echo "Deploying on EC2..."
ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no "ec2-user@$EC2_IP" << 'ENDSSH'
set -e

APP_DIR=/opt/crypto-sentiment
PERSIST_DIR=/tmp/crypto-sentiment-persist

# Retire the legacy host-wide VPN before any destructive deployment step.
# Reddit uses the cookie-backed Unbrowser transport in production.
sudo systemctl disable --now wg-quick@wg0 >/dev/null 2>&1 || true
if /sbin/ip link show wg0 >/dev/null 2>&1; then
    echo "Stopping legacy WireGuard interface..."
    if ! command -v wg-quick >/dev/null 2>&1; then
        echo "ERROR: wg0 is active but wg-quick is unavailable"
        exit 1
    fi
    sudo wg-quick down wg0
fi
if /sbin/ip link show wg0 >/dev/null 2>&1; then
    echo "ERROR: Legacy WireGuard interface is still active"
    exit 1
fi
WG_UNIT_STATE=$(sudo systemctl is-enabled wg-quick@wg0 2>/dev/null || true)
case "$WG_UNIT_STATE" in
    enabled|enabled-runtime|linked|linked-runtime)
        echo "ERROR: Legacy WireGuard service remains enabled ($WG_UNIT_STATE)"
        exit 1
        ;;
esac
sudo rm -f /etc/wireguard/wg0.conf
if ! timeout 15 getent ahostsv4 github.com >/dev/null 2>&1; then
    echo "ERROR: Direct EC2 DNS is unavailable after WireGuard cleanup"
    exit 1
fi
if ! curl -fsS --connect-timeout 5 --max-time 15 https://github.com/robots.txt >/dev/null; then
    echo "ERROR: Direct EC2 HTTPS egress is unavailable after WireGuard cleanup"
    exit 1
fi

# Preserve runtime state before replacing application files.
rm -rf "$PERSIST_DIR"
mkdir -p "$PERSIST_DIR"
for name in data logs backups run .env; do
    if [ -e "$APP_DIR/$name" ]; then
        mv "$APP_DIR/$name" "$PERSIST_DIR/$name"
    fi
done

# Extract application. Restore runtime state even if extraction fails.
restore_runtime_state() {
    sudo mkdir -p "$APP_DIR"
    sudo chown ec2-user:ec2-user "$APP_DIR"
    for name in data logs backups run .env; do
        if [ -e "$PERSIST_DIR/$name" ]; then
            rm -rf "$APP_DIR/$name"
            mv "$PERSIST_DIR/$name" "$APP_DIR/$name"
        fi
    done
}
trap restore_runtime_state EXIT

sudo rm -rf "$APP_DIR"
sudo tar -xzf /tmp/crypto-sentiment.tar.gz -C /opt
sudo mv /opt/app "$APP_DIR"
sudo chown -R ec2-user:ec2-user "$APP_DIR"
restore_runtime_state
trap - EXIT
rm -rf "$PERSIST_DIR"

cd "$APP_DIR"

# Create data directories
mkdir -p data logs backups run

# Check for .env file
if [ ! -f .env ]; then
    echo ""
    echo "WARNING: No .env file found!"
    echo "Please create /opt/crypto-sentiment/.env with your API keys"
    echo "Template available at: .env.example"
    echo ""
fi

# Build and start services
echo "Building Docker images..."
docker-compose build --no-cache

echo "Starting services..."
docker-compose up -d --remove-orphans

echo ""
echo "Checking service status..."
sleep 5
docker-compose ps

echo ""
echo "=== Deployment Complete ==="
ENDSSH

# Cleanup
rm -rf "$DEPLOY_TMP"

echo ""
echo "=== Application Deployed ==="
echo "Dashboard: http://$EC2_IP"
echo ""
echo "Useful commands:"
echo "  SSH:         ssh -i $KEY_PATH ec2-user@$EC2_IP"
echo "  Logs:        ssh -i $KEY_PATH ec2-user@$EC2_IP 'cd /opt/crypto-sentiment && docker-compose logs -f'"
echo "  Restart:     ssh -i $KEY_PATH ec2-user@$EC2_IP 'cd /opt/crypto-sentiment && docker-compose restart'"
