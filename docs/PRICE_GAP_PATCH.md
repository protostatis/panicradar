# Price Gap Patch Tooling

Reusable, spec-driven tooling for backfilling full-UTC-hour CoinGecko price
rows that were lost during an outage. It supersedes the one-off August 2026
tool (see `PRICE_GAP_PATCH_20260811.md` for the historical record) with a
strict, checked-in specification model.

Collection, validation, inspection, and application are all driven by a
`PriceGapSpec` loaded from `--spec`. The only hardcoded historical reference is
`LEGACY_V1_SPEC` in `crypto_sentiment_crawler/maintenance/price_gap_patch.py`,
used solely to read the already-produced v1 artifact and v1 manifest.

## Spec model

`crypto_sentiment_crawler/maintenance/price_gap_spec.py` defines an immutable
`PriceGapSpec` and a strict parser. A spec is a JSON object:

```json
{
  "schema_version": 1,
  "incident_id": "vpn-dns-20260811",
  "provider": "coingecko",
  "source_tag": "coingecko_gap_backfill:vpn-dns-20260811",
  "start_hour": "2026-08-11T02:00:00+00:00",
  "end_exclusive": "2026-08-13T14:00:00+00:00",
  "coins": {
    "BTC": "bitcoin",
    "ETH": "ethereum"
  }
}
```

Rules enforced by the parser:

- Exact key set (unknown/missing/duplicate keys are rejected).
- `provider` must be `coingecko`; `source_tag` must equal
  `coingecko_gap_backfill:<incident_id>`.
- `start_hour` and `end_exclusive` must be full UTC hours with
  `end_exclusive` after `start_hour`.
- At most 7 days (`MAX_HOURS`), at most 25 coins (`MAX_COINS`), and at most
  2,000 `coins x hours` candidates (`MAX_CANDIDATES`).

The canonical digest of a spec is `spec.sha256`, the sha256 of its canonical
(sorted-key, compact) JSON. `source_tag` is derived deterministically from the
spec, so an applied run's rows are always attributable.

## Workflow

The script has four subcommands:

```bash
# 1. Collect (spec required; rejects a future end_exclusive)
uv run python scripts/price_gap_patch.py collect \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact /absolute/offline/vpn-dns-20260811.sqlite

# 2. Inspect an artifact and optionally a target (spec required)
uv run python scripts/price_gap_patch.py inspect \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact "$ARTIFACT" [--target "$TARGET"]

# 2b. Inspect one applied run read-only (no artifact/spec required)
uv run python scripts/price_gap_patch.py inspect-run \
  --target "$TARGET" --run-id "$RUN_ID"

# 3. Apply (spec + exact confirmations required)
uv run python scripts/price_gap_patch.py apply \
  --spec crypto_sentiment_crawler/maintenance/specs/vpn-dns-20260811.json \
  --artifact "$ARTIFACT" --artifact-sha256 "$DIGEST" \
  --target "$TARGET" --backup "$BACKUP" \
  --confirm-spec-sha256 "$SPEC_DIGEST" \
  --confirm-candidates 600 \
  --confirm-incident vpn-dns-20260811 \
  --confirm-target "$TARGET" \
  --confirm-writers-paused

# 4. Rollback one run (no spec required)
uv run python scripts/price_gap_patch.py rollback \
  --target "$TARGET" --backup "$ROLLBACK_BACKUP" \
  --run-id "$RUN_ID" --confirm-run-id "$RUN_ID" \
  --confirm-incident "$INCIDENT_ID" \
  --confirm-target "$TARGET" \
  --confirm-writers-paused
```

### Collection

Never accepts a database path. Writes a read-only SQLite artifact, a
`<artifact>.sha256` receipt, and a `<artifact>.raw/` directory of retained HTTP
responses with a verified `index.json`. Collection refuses to overwrite
existing output and refuses a spec whose `end_exclusive` is later than the
current full UTC hour.

### Artifact

Artifact schema v2 embeds the canonical spec JSON and its `spec_sha256` in
`patch_metadata`. `validate_artifact` requires the supplied spec to match the
embedded canonical spec and re-derives every candidate from the raw
responses. The historical v1 artifact (schema v1, no embedded spec) is still
validated read-only against `LEGACY_V1_SPEC`.

Artifact validation also verifies the original request URL/parameters, attempt
sequence, HTTP status consistency, response hashes, candidate-to-response
links, and regular-file sidecars. Apply reads candidates from the same private
artifact snapshot that passed validation, preventing path replacement between
validation and insertion.

### Apply

Requires: artifact digest, exact spec digest confirmation, incident
confirmation, candidate-count confirmation, canonical target path, writers
paused, and a fresh absolute backup path. Everything runs inside one
`BEGIN IMMEDIATE` transaction from classification through commit, so the target
either gains all rows (plus their audit manifest) or none. A consistent
pre-apply backup is created and hashed before any mutation, and the pre-existing
foreign-key violation multiset is verified unchanged before commit.

### Rollback

Spec-independent. It uses the run's own `inserted_count` and `incident_id` (not
the active spec or a hardcoded count) to verify and delete only the exact,
unchanged rows recorded for one applied run. It refuses if a row was edited,
removed, or shares its candidate bucket with an extra row, and records a fresh
pre-rollback backup.

## Target manifest schema

The target keeps three audit tables: `price_gap_patch_schema`,
`price_gap_patch_runs`, and `price_gap_patch_rows`.

- **v1** (historical, production): fixed `CHECK (inserted_count = 600)`, no spec
  columns. Read-only inspect and rollback remain fully supported.
- **v2** (current): variable `inserted_count`, nullable `spec_json` and
  `spec_sha256` columns recording the spec used for each run.

A v1 manifest is migrated to v2 in place only when a genuinely new apply needs
it, after classification and backup, inside the uninterrupted `BEGIN IMMEDIATE`
transaction and without `executescript`. Existing already-applied v1 runs are
left untouched (returning `already_applied` without migration), and migrated
legacy rows keep `NULL` spec columns.

## Local verification

```bash
uv run pytest -q tests/test_price_gap_patch.py
uv run ruff check \
  crypto_sentiment_crawler/maintenance/price_gap_patch.py \
  crypto_sentiment_crawler/maintenance/price_gap_spec.py \
  scripts/price_gap_patch.py \
  tests/test_price_gap_patch.py
```

No command should be pointed at production until the collected artifact and
read-only target inspection have been reviewed and explicitly approved.
