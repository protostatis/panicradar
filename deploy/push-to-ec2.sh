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

# Extract application
sudo rm -rf /opt/crypto-sentiment/*
sudo tar -xzf /tmp/crypto-sentiment.tar.gz -C /opt
sudo mv /opt/app/* /opt/crypto-sentiment/
sudo rmdir /opt/app
sudo chown -R ec2-user:ec2-user /opt/crypto-sentiment

cd /opt/crypto-sentiment

# Create data directories
mkdir -p data logs

# Check for .env file
if [ ! -f .env ]; then
    echo ""
    echo "WARNING: No .env file found!"
    echo "Please create /opt/crypto-sentiment/.env with your API keys"
    echo "Template available at: .env.example"
    echo ""
fi

# Prefer the app-level residential proxy for Reddit. WireGuard remains only as
# a legacy fallback for hosts that have not been moved to proxy-based access.
if grep -Eq '^(PROXY_URL|RESIDENTIAL_PROXY)=[^[:space:]]+' .env 2>/dev/null; then
    echo "Residential proxy configured; skipping WireGuard setup..."
    sudo systemctl disable --now wg-quick@wg0 2>/dev/null || true
elif grep -q WG_PRIVATE_KEY .env 2>/dev/null; then
    echo "Setting up legacy WireGuard VPN..."
    bash deploy/setup-wireguard.sh .env
fi

# Build and start services
echo "Building Docker images..."
docker-compose build --no-cache

echo "Starting services..."
docker-compose up -d

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
