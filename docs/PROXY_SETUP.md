# Reddit Access

The crawler uses the cookie-backed Unbrowser transport for Reddit HTML. It
preserves the existing `old.reddit.com` listing, thread, and comment parsing
without relying on a residential proxy credential.

See [REDDIT_UNBROWSER_SETUP.md](REDDIT_UNBROWSER_SETUP.md) for the required
local solver and SSH Unix-socket forward.

WireGuard remains enabled for the rest of production traffic. The integration
refreshes its in-memory Reddit cookies after an unusable Reddit response and
does not intentionally write them to GitHub secrets, the database, logs, or
`/opt/crypto-sentiment/.env`. See the runtime-storage caveat in
`REDDIT_UNBROWSER_SETUP.md`.

## Verification

```bash
sudo wg show
curl --unix-socket /opt/crypto-sentiment/run/reddit-cookie-solver.sock \
  http://localhost/healthz
docker exec crypto-crawler sh -c 'test "$REDDIT_FETCH_MODE" = unbrowser'
```

If the solver socket is unavailable, deployment continues with standard Reddit
fetching so unrelated services remain available.
