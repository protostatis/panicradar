# WireGuard and Residential Proxy Setup for Reddit Access

Reddit blocks AWS/cloud IP addresses and can also block a WireGuard exit IP.
Production keeps WireGuard for host networking and routes Reddit requests through
a residential proxy injected into the crawler at release time.

## Configuration

Add the WireGuard values to `/opt/crypto-sentiment/.env` on EC2:

```bash
WG_PRIVATE_KEY=your_wireguard_private_key
WG_ADDRESS=10.x.x.x/32
WG_DNS=10.64.0.1
WG_PEER_PUBKEY=server_public_key
WG_ENDPOINT=server_ip:51820
```

Store the residential proxy URL in the GitHub Actions `RESIDENTIAL_PROXY` secret.
Do not add it to `/opt/crypto-sentiment/.env`: the release workflow passes it to
the crawler as `PROXY_URL` only.

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
images are pulled and before the crawler starts. Before replacing any running
containers, the release image must fetch crawlable `old.reddit.com` HTML through
the residential proxy. The crawler receives that proxy as `PROXY_URL`; no other
service receives it.

## Verification

Verify the host egress IP:

```bash
curl https://httpbin.org/ip
sudo wg show
```

Verify the crawler has a proxy without printing its credential:

```bash
docker exec crypto-crawler sh -c 'test -n "$PROXY_URL"'
```

The command should exit successfully. The release canary already verifies that
the proxy returns Reddit HTML containing `data-timestamp`.

## Troubleshooting

If Reddit returns `403` or the crawler logs no fresh posts, first verify that
the `RESIDENTIAL_PROXY` GitHub secret is present and that the release canary
succeeds. Restarting WireGuard will not help when its current exit IP is blocked.

To check WireGuard independently:

```bash
sudo wg show
sudo systemctl status wg-quick@wg0
sudo wg-quick down wg0 && sudo wg-quick up wg0
```

If Docker pulls or S3 backups fail while the VPN is up, re-run the setup script
to restore the bypass routes for GitHub and EC2 instance metadata.
