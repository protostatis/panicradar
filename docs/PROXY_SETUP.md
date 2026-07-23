# Residential Proxy Setup for Reddit Access

Reddit blocks AWS/cloud and Mullvad exit IPs. Production routes Reddit requests
through the Bright Data residential proxy injected into the crawler at release
time.

## Configuration

Store the residential proxy URL in the GitHub Actions `RESIDENTIAL_PROXY` secret.
Do not add it to `/opt/crypto-sentiment/.env`: the release workflow passes it to
the crawler as `PROXY_URL` only.

WireGuard values may remain in `/opt/crypto-sentiment/.env` for emergency/manual
recovery, but the production release disables `wg0`. The proxy must connect from
the EC2 public egress rather than through a Mullvad exit IP.

```bash
# Optional emergency WireGuard configuration
WG_PRIVATE_KEY=your_wireguard_private_key
WG_ADDRESS=10.x.x.x/32
WG_DNS=10.64.0.1
WG_PEER_PUBKEY=server_public_key
WG_ENDPOINT=server_ip:51820
```

## Setup

Use WireGuard only for emergency diagnostics:

```bash
cd /home/ec2-user/crypto_sentiment_crawler
bash deploy/setup-wireguard.sh /opt/crypto-sentiment/.env
```

The release workflow stops `wg0` before GitHub/Docker network operations and
recovers the EC2 DNS resolver before starting the crawler.

## Deployment

Before replacing any running containers, the release image must fetch crawlable
`old.reddit.com` HTML through the residential proxy. The crawler receives that
proxy as `PROXY_URL`; no other service receives it.

## Verification

Verify WireGuard is stopped after a proxy deployment:

```bash
sudo systemctl is-active wg-quick@wg0
```

The expected result is `inactive`.

Verify the crawler has a proxy without printing its credential:

```bash
docker exec crypto-crawler sh -c 'test -n "$PROXY_URL"'
```

The command should exit successfully. The release canary first verifies the
credential with `curl`, then tests the crawler's HTTP client against a neutral
HTTPS page and Reddit HTML containing `data-timestamp`.

## Troubleshooting

If Reddit returns `403` or the crawler logs no fresh posts, first verify that
the `RESIDENTIAL_PROXY` GitHub secret is present and that the release canary
succeeds. Do not re-enable WireGuard while the crawler is using that proxy.

To check WireGuard independently:

```bash
sudo wg show
sudo systemctl status wg-quick@wg0
sudo wg-quick down wg0 && sudo wg-quick up wg0
```

If Docker pulls or S3 backups fail while the VPN is up, re-run the setup script
to restore the bypass routes for GitHub and EC2 instance metadata.
