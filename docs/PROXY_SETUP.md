# Residential Proxy Setup for Reddit Access

Reddit blocks AWS/cloud IP addresses. The crawler routes Reddit requests through
an app-level residential HTTP proxy instead of a host-level WireGuard VPN.

## Configuration

Set one of these in `/opt/crypto-sentiment/.env` on EC2:

```bash
# Preferred: reuse the searchagentsky.com proxy value
RESIDENTIAL_PROXY=http://user:pass@proxy.example.com:8080

# Optional override. If set, this takes precedence over RESIDENTIAL_PROXY.
PROXY_URL=http://user:pass@proxy.example.com:8080
```

The crawler accepts comma-separated proxy URLs for rotation:

```bash
PROXY_URL=http://proxy1.example:8080,http://proxy2.example:8080
```

## How It Works

1. The crawler requests Reddit through `crypto_sentiment_crawler.crawler.fetcher.Fetcher`.
2. `Fetcher` detects `reddit.com` and its subdomains, including `old.reddit.com`.
3. If `PROXY_URL` or `RESIDENTIAL_PROXY` is set, the request uses the proxy.
4. Non-Reddit sources continue to fetch directly unless `force_proxy=True` is used.

## Deployment

The release deploy reads `/opt/crypto-sentiment/.env` into the crawler container.
When a proxy is configured, deploy also stops `wg-quick@wg0` if it is still
enabled from the old WireGuard setup.

For manual Docker Compose runs, `docker-compose.yml` passes both `PROXY_URL` and
`RESIDENTIAL_PROXY` into the crawler service.

## Verification

From EC2, verify the proxy egress IP:

```bash
set -a; . /opt/crypto-sentiment/.env; set +a
PROXY="${PROXY_URL:-$RESIDENTIAL_PROXY}"
curl -x "$PROXY" https://httpbin.org/ip
```

Verify Reddit returns crawlable HTML through the proxy:

```bash
set -a; . /opt/crypto-sentiment/.env; set +a
PROXY="${PROXY_URL:-$RESIDENTIAL_PROXY}"
curl -sL -x "$PROXY" \
  -A "Mozilla/5.0" \
  "https://old.reddit.com/r/bitcoin/new/" | grep -c "data-timestamp"
```

The result should be greater than `0`.

Verify the running container received the proxy env:

```bash
docker exec crypto-crawler printenv RESIDENTIAL_PROXY
```

## Notes

The old SSH tunnel and WireGuard setup are no longer required for Reddit. If
`wg-quick@wg0` is still running, stop it after confirming the residential proxy
works:

```bash
sudo systemctl disable --now wg-quick@wg0
```
