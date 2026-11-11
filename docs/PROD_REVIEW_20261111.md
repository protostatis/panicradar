# Production Data Review — 2026-11-11

Read-only inspection of `panicradar-prod` (34.236.47.243, t3.small, us-east-1).
Nothing on the host was modified. Local test suite is green at review time
(`pytest -q` → 344 passed, 1 skipped).

Access used:

```bash
ssh panicradar            # ~/.ssh/panicradar-ec2.pem
sqlite3 "file:/opt/crypto-sentiment/data/sentiment.db?mode=ro"
```

## 1. Live state

| Item | Value |
|---|---|
| Containers | crawler, api, frontend, signals, game-server, trending-scout — all up 24h |
| Host | 1.9 GB RAM, 880 MB used, 431 MB swap used, load 0.24 |
| Disk | 27 G / 40 G (67%) — 8.1 G backups, 3.9 G shadow artifacts, 0.46 G DB |
| DB | `sentiment.db` 458 MB, `journal_mode=delete`, no WAL |
| API | healthy; every endpoint responds in 130–400 ms |
| Crawl volume | **65 posts stored in 23.7 h** from 1,715 seen (3.8%) |
| Sources yielding | 16 in 7 d, 14 in 24 h (43 configured, 23 "active") |
| Price | 10 coins, ~4.6 min cadence, fresh |
| On-chain | 19 BTC metrics + ETH set, ~14 min cadence, fresh |
| Confounders | VIX, F&G, funding, BTC dominance populated; `news_count_1h` always 0 |
| Real traffic | 82 `GET /` today; 164 requests were scanner probes; 119 unique IPs total |

Pipeline health endpoint is honest about freshness but not about quality:
`/api/ops/health` returns `healthy` while the product shows 6 coins, 39 sources
and a sentiment score that cannot leave ±0.3.

## 2. What is actually broken

### P0-a. Every dashboard time window is longer than it claims

Timestamps are stored as ISO-8601 with `T` and `+00:00`
(`datetime.isoformat()`), but queries compare them against SQLite's
space-separated `datetime('now', …)` strings. In byte order `'T'` (0x54) sorts
after `' '` (0x20), so a cutoff of `2026-11-10 13:40:36` also accepts
`2026-11-10T00:39:07+00:00` — every row on the cutoff *date* that sorts after the
`T` slips through, which is up to ~14 h of extra data depending on the hour the
query runs.

Measured on the live DB:

```
bad_window(24h)  iso_window(24h)  earliest row admitted
71               52               2026-11-10T00:39:07+00:00   <- 37 hours
```

Reproduced deterministically in-memory (3/3 rows pass a cutoff that only 1 should).

13 occurrences, all in window filters:

- `dashboard/queries.py:58,221,279,303,447,501,527,562,592,593,845,864`
- `processing/user_sentiment.py:788`

Impact: the 24 h panic score, the 7-day baseline used by its "relative shift"
component, and the 7/30-day rankings are all computed over wider windows than
labelled. This is the flagship number on the site.

### P0-b. Source weights are identical — the learning layer is inert

`active_source_weights` for belief version 5072: **39 rows, every `weight` =
0.01, sum = 0.39**. Not a stale snapshot — recomputed every 30 min.

Cause (`analysis/source_weights.py:73-131`):

```python
distance = max(0.0, ci_lower - 0.5)     # needs CI lower bound above 0.5
weight   = 0.01 + distance * 2 * confidence * 0.29
```

With observed accuracies of 39–66 % and n of 20–540, the credible-interval lower
bound never clears 0.5, so `distance` is 0 for every source and the weight stays
at the 0.01 floor. Sources tagged `insufficient_data` return 0.01 immediately.
The dashboard therefore renders 39 sources at equal weight — the "dynamic source
weights" claim in the README is currently false in a way users can see.

### P0-c. Eight phantom sources inflate the source list

The belief store (`orchestrator_state.json`) holds 39 entries, of which 8 are
case-variant duplicates of real sources, frozen since `2026-02-03`:

```
reddit_BitcoinMarkets   reddit_CryptoCurrency   reddit_CryptoMarkets
reddit_CryptoMoonShots  reddit_CryptoTax        reddit_CryptoTechnology
reddit_Crypto_General   reddit_CryptoCurrency (meta/memes variants)
```

All have `sample_size = 0` and `accuracy = NULL`, and all are rendered as
sources. `_find_ghost_sources()` only filters **non-Reddit** ghosts
(`belief_updater.py:49-51`), so Reddit case variants are filtered forever.

### P0-d. `sentiment_scores` is read by analysis code but nothing writes it

- `sentiment_scores`: 9 rows, all between `2026-02-01T23:59` and
  `2026-02-02T03:05`. The live pipeline writes `user_sentiment_scores`
  (32,526 rows) instead.
- The table still has **readers**: `analysis/backtest_analysis.py:84`,
  `analysis/bayesian_learning.py:74,178,231,238`,
  `causal/backdoor_analysis.py:42`, `analysis/rescore_transformer.py`.
  Any correlation/causal/backtest run today silently joins 9-month-old stored
  sentiment with current prices. It does not fail — it produces numbers.
- `confounders.news_count_1h`: 0 in all 347 rows of the last 3 days (not NULL —
  literally zero), and `News=0` is logged every confounder cycle. Whatever was
  supposed to supply it is disconnected; `/news/trending` gets its data from the
  separate trending-scout container instead.

### P1-a. The ingestion funnel throws away 96 %

24 h of crawler logs:

```
crawls selected            239
crawls that stored 0       194  (81%)
posts seen                 1,715
posts stored               65   (3.8%)
```

The request budget is spent almost entirely on work that is then discarded,
because thread fetches happen **before** any dedup or quality check
(`crawler/pipeline.py:470` vs `orchestrator.py:755`):

- `crawl_subreddit(limit=25, max_age_hours=24)` fetches 1 listing, then one
  thread request per post — up to 25 per crawl.
- Dedup (`content_hash = sha256(source:url)`) and the `MIN_HUMAN_COMMENTS = 4`
  gate only run in `_store_content`, after the thread is already fetched.
- For `reddit_bitcoin`: 16 crawls × 24.5 posts = 392 thread fetches → 25 stored.
  ~94 % of those requests paid for a row that was a duplicate or below the gate.
- A post that has <4 comments when first seen is dropped and only re-examined if
  it is still on page 1 of `/new` on a later cycle. Page 1 is fetched repeatedly
  in full.

The listing page already exposes `data-permalink` and `num_comments`, so both
checks are available **for free before** the thread request.

### P1-b. The sentiment score cannot move

`user_sentiment_scores` over the last 30 d (n = 1,757):

```
mean |final_score|   0.0659
max / min            +0.242 / -0.324
|score| <= 0.1       1,377  (78%)
|score| >= 0.3       3      (0.17%)
```

`final_score` averages a title score with the mean of up to 20 segment scores
(`processing/user_sentiment.py`), which concentrates the distribution around
zero. Downstream, `|calibrated_score| < 0.05` is classified "flat", so ~47 % of
all outcomes are no-calls and the panic-score components that depend on
post-level polarity (bearish/bullish counts) see 1–7 posts/day out of ~70.

### P1-c. The headline accuracy is inflated by flat calls

`prediction_outcomes` (n = 5,212): 2,896 correct → **55.6 %**.

```
direction   n      accuracy   avg |4h move|
down        1,592  48.0 %     0.575 %   (30d: 54.8 %)
flat        2,348  63.6 %     0.572 %   (30d: 61.9 %)
up          1,265  50.4 %     0.532 %   (30d: 48.1 %)
```

Directional accuracy (down+up only) is **51.9 %**, i.e. indistinguishable from
chance with this sample (±3.6 pp at 95 %). The 55.6 % figure is produced by
counting sub-0.5 % moves as correct "flat" calls. The 30-day `down` edge (54.8 %)
is not separable from a falling market (BTC −1.97 %/24 h, −4.9 %/7 d).

### P1-d. Every prediction is graded against BTC

`prediction_outcomes` has no `coin` column, and both `price_before` and
`price_after` come from `_get_current_price("BTC")`
(`orchestrator.py:631, 838`). 30-day posts mentioning a coin: BTC 688, ETH 100,
SOL 63, … and **862 of 1,757 (49 %) mention no tracked coin at all**. Non-BTC
sentiment is being scored against BTC returns, adding pure noise to every belief.

### P2. Feature claims that are not implemented

- `run_causal_discovery()` is a stub with a `TODO`, is not registered in the
  scheduler, and `last_causal_update` has been `None` since inception.
  README/roadmap/architecture diagrams advertise causal discovery as a pillar.
- `belief_publications` has exactly one row (version 5072) for ~5,073 versions of
  snapshots; the publish path only started recording recently, so historical
  weight series cannot be resolved through the view.

### P2. Operational debt (none of it urgent, all of it cheap)

| Issue | Evidence |
|---|---|
| 5 pre-incident DBs never pruned | `sentiment.pre-*.db` (288–291 MB each) don't match the retention globs in `deploy/backup-db.sh` |
| 14 daily 457 MB full copies | 8.1 G on a 40 G disk; S3 already holds them |
| 3.9 G in `maintenance/reddit-shadow` | one-off recovery artifacts |
| Container logs unbounded | `json-file` with `LogConfig.Config = {}` (no rotation) |
| `journal_mode=delete` | 3 writers (crawler, api, signals), no `busy_timeout`; 0 lock errors so far |
| Unbounded tables | `pipeline_heartbeats` 186 k rows, `source_weight_snapshots` 196 k rows, no retention |
| Stuck outcome claim | one row has `evaluated_at = 'claim:2026-08-14T…:b8bc…'`; a claim token lives in the `evaluated_at` column, which corrupts `MAX(evaluated_at)` and never expires |
| Telegram resets | `Cannot connect to host api.telegram.org` ×3 in 24 h; no alert activity logged |
| Image churn | `docker system df`: 8.9 G images, 118 MB reclaimable (1 %) |

## 3. Self-review of this analysis

What is directly measured (high confidence): every number in §1, §2-P0-a/b/c/d,
P1-a/b/c, the disk/backup/log facts, and the traffic counts. Each was read from
the live DB, live logs, or the live API, and the timestamp bug was reproduced in
an isolated in-memory SQLite.

What is inference rather than proof:

1. **"The gate + page-1 repetition causes the 96 % waste."** I can prove the
   order of operations in code and prove 1,715 → 65. I cannot split that 96 %
   into *duplicate* vs *below-comment-gate* vs *other*, because the funnel is
   not instrumented (both failures return 0 silently). Phase 1 starts by
   instrumenting it, so the fix is validated rather than assumed.
2. **"Mean-of-segments causes the compression."** Consistent with the code and
   the distribution, but not isolated experimentally. The proposed fix is
   evaluated offline against stored raw data before it touches production.
3. **The 30-day `down` edge (54.8 %).** Plausible in a downtrend, not proven to
   be signal. Treat as unresolved until there is a baseline comparison.
4. **Traffic numbers.** `access.log` is partially rotated and the report already
   filters internal health checks; unique-IP counts over-count scanners. The
   conclusion "there is no meaningful user traffic" is robust to that.

Not examined: the game server and PvP flow, the newsletter/email path, the
frontend bundle for stale endpoints, and Reddit cookie-solver health beyond the
socket documented in `REDDIT_UNBROWSER_SETUP.md`.

## 4. Plan

Ordered by (impact ÷ risk). Each phase has an acceptance check that can be run
against production without guessing.

### Phase 0 — correctness and hygiene (≈1 day, no model behavior change)

1. **One timestamp helper, used everywhere.** Cutoffs must be produced in the
   same format the rows are stored in — `strftime('%Y-%m-%dT%H:%M:%S','now', ?)`
   is a drop-in for the 13 `datetime('now', …)` comparisons and needs no data
   migration (ISO-T prefix comparison also tolerates fractional seconds and the
   `+00:00` suffix). Add a regression test that inserts
   `2026-11-10T00:39:07+00:00` and asserts a 24 h window excludes it.
   *Accept:* panic-score `total_posts` drops from 71 to ~52 and matches a
   hand-computed window on the same day.
2. **Normalize source keys.** Lowercase every source key in
   `orchestrator_state.json` and `source_weight_snapshots`; drop the 8 case
   ghosts; extend `_find_ghost_sources()` to any source with zero rows in
   `sentiment_raw` over the lookback, Reddit included.
   *Accept:* `/api/dashboard/sources` shows 31 sources, none with
   `sample_size = 0 AND weight = 0.01 AND accuracy = null`.
3. **Retire dead paths.** Either write `sentiment_scores` from the rollup or drop
   it *and* its four readers — a table that four analysis modules read and
   nothing writes is worse than a missing table. Wire `news_count_1h` to the
   trending scout or remove it from `confounders`.
4. **Storage.** Add the `sentiment.pre-*.db` pattern to retention (or delete the
   5 files after confirming S3 has equivalents), gzip local dailies or keep 3
   local + S3-only beyond that, set `logging: {driver: json-file, options:
   {max-size: "50m", max-file: "3"}}` on all services, and `docker image prune`.
   *Accept:* `df -h /` below 55 %, `/opt/crypto-sentiment/backups` under 1.5 G.
5. **SQLite concurrency.** Enable WAL + `busy_timeout=5000` + `synchronous=NORMAL`
   in `Database.connect()`, then restart one container at a time.
   *Accept:* no "database is locked" in 24 h of all three containers; API p95
   unchanged.
6. **Claim-token cleanup.** Give claims their own column (or expire them), and
   clear the stuck `claim:` row. *Accept:* `MAX(evaluated_at)` is a valid
   timestamp.

### Phase 1 — ingestion efficiency (1–2 days, biggest value per line changed)

7. **Instrument the funnel** before changing it: per crawl count
   `seen / skipped_age / duplicate / below_gate / stored`, and put it in
   `pipeline_heartbeats.metadata` plus `/api/ops/health`.
   *Accept:* one day of data splits the 96 % into named buckets.
8. **Check before you fetch.** In `crawl_subreddit`, compute the content hash
   from `data-permalink` and check `num_comments` from the listing *before*
   `fetch_thread`. Skip the thread request when the row exists or the listing
   already shows < 4 comments (re-checked on later cycles for free).
   *Accept:* thread fetches/day drop from ~1,700 to < 300 at equal or better
   stored count; the funnel counters prove it.
9. **Two-phase ingestion.** Store the raw row (title/url/author/published) on
   first sight, and apply the engagement gate at scoring time with a
   re-score-eligible flag. This stops permanently discarding posts that earn
   comments after they leave page 1.
   *Accept:* ≥ 90 % of posts that reach 4 comments within 24 h are stored, on a
   sampled subreddit.
10. **Spend the freed budget on coverage.** Poll the top-volume subs on a fixed
    interval and let the bandit allocate only the remaining budget; paginate the
    listing (`?count=&after=`) instead of relying on page 1.
    *Accept:* capture ratio first — ≥ 90 % of posts that are ≤ 24 h old and have
    ≥ 4 comments, per subreddit — then volume, which will follow from it. Set the
    absolute target only after item 7 reports the eligible population; do not
    assume 800 posts/day exists in these 12 subreddits (page 1 of `/new` spans a
    full day in several of them, which caps what is currently visible).

### Phase 2 — make the signal capable of moving (≈1 week)

11. **Score aggregation experiment (offline, on existing raw data).** Compare
    mean-of-segments against (a) net bullish share, (b) top-k extreme mean,
    (c) per-source z-score vs 7-day baseline. Choose by out-of-sample
    directional accuracy with Wilson intervals, per coin.
12. **Grade against the coin the post is about.** Add `coin` to
    `prediction_outcomes`, price the outcome with that coin (fall back to BTC
    only for genuinely market-wide posts), and keep a "market" aggregate
    separate. Report flat calls separately — never inside "accuracy".
13. **Add baselines to the ledger report.** Always-down, always-up, and
    momentum. A source's accuracy is only interesting relative to the best
    baseline with overlapping timestamps.
14. **Fix the weight function.** Replace the `ci_lower > 0.5` cliff with a
    smooth skill score (log-loss or Brier skill vs 0.5, with shrinkage by n).
    *Accept:* top/bottom weight ratio ≥ 3 and weights spread across the 31 real
    sources instead of 39 × 0.01.
15. **Decide on causal discovery.** Implement it or delete the claim from
    README/roadmap and the `last_causal_update` state field. A pillar advertised
    in the architecture diagram that is a `TODO` is a credibility risk.

### Phase 3 — product

16. **Positioning check.** Current traffic is scanners. Either the data becomes
    defensible enough to sell (Phases 1–2), or lean on what already works — the
    trending-scout/news path, which is fresh and independent of the sentiment
    pipeline.
17. **Alert path verification.** Inject a synthetic signal end-to-end and
    confirm Telegram delivery, including during a connection reset; log
    delivery failures as metrics, not as a single stderr line.

### Sequencing rationale

Phase 0 is safe, isolated, and stops the site from publishing numbers that are
provably wrong (the 37-hour "24-hour" panic score, 39 equal weights, 8 phantom
sources). Phase 1 roughly decouples yield from request budget, which is what
makes any later statistical work possible. Phase 2 should not start until the
volume is there — with ~65 posts/day, no aggregation choice can be validated.
