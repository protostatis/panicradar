# WireGuard Setup for Reddit Access

Reddit blocks AWS/cloud IP addresses. Production uses a WireGuard VPN on the EC2
host so Docker containers inherit the VPN egress path through host NAT.

## Configuration

Add the WireGuard values to `/opt/crypto-sentiment/.env` on EC2:

```bash
WG_PRIVATE_KEY=your_wireguard_private_key
WG_ADDRESS=10.x.x.x/32
WG_DNS=10.64.0.1
WG_PEER_PUBKEY=server_public_key
WG_ENDPOINT=server_ip:51820
```

`PROXY_URL` is still supported as an optional crawler override, but it is not
needed when WireGuard is active.

## Setup

Run the setup script on EC2:

```bash
cd /home/ec2-user/crypto_sentiment_crawler
bash deploy/setup-wireguard.sh /opt/crypto-sentiment/.env
```

The script writes `/etc/wireguard/wg0.conf`, starts `wg0`, and enables
`wg-quick@wg0` on boot.

## Deployment

Release deploys set up WireGuard from `/opt/crypto-sentiment/.env` after Docker
images are pulled and before the crawler starts. The crawler is started with
`PROXY_URL` and `RESIDENTIAL_PROXY` blank so Reddit traffic uses the host VPN.

## Verification

Verify the host egress IP:

```bash
curl https://httpbin.org/ip
sudo wg show
```

Verify Reddit returns crawlable HTML from EC2:

```bash
curl -sL -A "Mozilla/5.0" \
  "https://old.reddit.com/r/bitcoin/new/" | grep -c "data-timestamp"
```

The result should be greater than `0`.

Verify the crawler is not using an app-level proxy:

```bash
docker exec crypto-crawler printenv PROXY_URL
docker exec crypto-crawler printenv RESIDENTIAL_PROXY
```

Both commands should print nothing.

## Troubleshooting

If Reddit returns `403` or the crawler logs no fresh posts:

```bash
sudo wg show
sudo systemctl status wg-quick@wg0
sudo wg-quick down wg0 && sudo wg-quick up wg0
```

If Docker pulls or S3 backups fail while the VPN is up, re-run the setup script
to restore the bypass routes for GitHub and EC2 instance metadata.
