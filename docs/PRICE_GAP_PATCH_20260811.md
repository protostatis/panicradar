# August 2026 Price Gap Patch (Historical Record)

This runbook documents incident `vpn-dns-20260811` and its production
application. The reusable, spec-driven tooling that superseded the original
hardcoded tool is documented in `PRICE_GAP_PATCH.md`.

The patch restores exactly 600 CoinGecko rows: 60 full UTC hours
(`2026-08-11T02:00:00Z` through `2026-08-13T13:00:00Z`) for BTC, ETH, SOL, BNB,
XRP, ADA, DOGE, AVAX, DOT, and LINK. The partial 01:00 and 14:00 boundary hours
are intentionally excluded.

## Checked-in spec

The incident is described by the checked-in spec:

```
crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json
```

It is also the single source of the `LEGACY_V1_SPEC` constant used to validate
and roll back the already-produced v1 artifact and v1 manifest.

## Production application record

- **Incident**: `vpn-dns-20260811`
- **Run ID**: `b46bb542-bc29-4f28-83d9-2c3ff45c9f27`
- **Applied**: `2026-08-13`
- **Rows inserted**: `600` (matches the checked-in spec's candidate count)
- **Pre-apply backup**: retained in the protected production backup directory;
  path and sha256 are recorded in the target manifest and operator notes
- **Pre-existing foreign-key violations**: `264`, verified unchanged before and
  after the commit (tracked separately; not introduced or repaired by this patch)

The original v1 run predates embedded spec metadata. The artifact and candidate
digests, backup receipt, and exact violation baseline were verified during the
operation; the target's `price_gap_patch_*` audit tables retain the row manifest
for rollback.

## Workflow

Collection, inspection, application, and rollback are separate phases. The
three guarded phases are:

```bash
# 1. Collect and review offline (spec required)
uv run python scripts/price_gap_patch.py collect \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact /absolute/offline/vpn-dns-20260811.sqlite

uv run python scripts/price_gap_patch.py inspect \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact /absolute/offline/vpn-dns-20260811.sqlite
```

Collection creates the read-only SQLite artifact, its `<artifact>.sha256`
receipt, and a `<artifact>.raw/` directory of retained responses with a
verified index. Expected inspection values are `status: valid`, `coins: 10`,
`hours_per_coin: 60`, and `candidates: 600`.

```bash
# 2. Inspect a target read-only (spec required)
uv run python scripts/price_gap_patch.py inspect \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact "$ARTIFACT" --target "$TARGET"
```

Proceed only when `target_status` is `ready` and `conflict_count` is `0`.

```bash
# 3. Apply after explicit approval
uv run python scripts/price_gap_patch.py apply \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact "$ARTIFACT" --artifact-sha256 "$DIGEST" \
  --target "$TARGET" --backup "$BACKUP" \
  --confirm-spec-sha256 "$SPEC_DIGEST" \
  --confirm-candidates 600 \
  --confirm-incident vpn-dns-20260811 \
  --confirm-target "$TARGET" \
  --confirm-writers-paused
```

Apply holds one `BEGIN IMMEDIATE` transaction through the final verification
and commit, inserting either all 600 price rows plus their audit manifest or
none. The inserted source is `coingecko_gap_backfill:vpn-dns-20260811`.

## Rollback

Rollback is spec-independent and uses the run's own `inserted_count` and
`incident_id`:

```bash
uv run python scripts/price_gap_patch.py rollback \
  --target "$TARGET" --backup "$ROLLBACK_BACKUP" \
  --run-id "$RUN_ID" --confirm-run-id "$RUN_ID" \
  --confirm-incident vpn-dns-20260811 \
  --confirm-target "$TARGET" \
  --confirm-writers-paused
```

Retain all artifact files, backups, command JSON output, and the target's
`price_gap_patch_*` audit tables with the incident record.
