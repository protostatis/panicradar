# Resolution Plan: Post-Audit Bug Fixes & Systematic Improvements

**Date:** 2026-07-23
**Scope:** All confirmed bugs and systematic issues discovered during the July 2026 production database audit.

---

## Phase 1: Critical Fixes (This Week)

### 1. Fix price cache — `_get_current_price()` never refreshes

**Files:** `orchestrator.py:323-331`, `storage/db.py`

**Problem:** The live outcome evaluator fetches BTC price once into a dict, never refreshes it. Result: `price_before ≈ price_after` for every evaluation. Live bandit utility becomes `0.35 + 0.3 × novelty` — the bandit learns to value novel content, not predictive accuracy.

**Approach:**
- Remove the unbounded `current_prices` cache
- Return a `PriceData` record with freshness metadata, not just a float
- Evaluate each outcome against the price nearest `outcome.timestamp + 4h`, not one latest price
- Require the matched price to be within one collection interval of the target timestamp
- If no valid price exists, leave the outcome pending — do not assign 0.5 accuracy

**Effort:** 3–4 hours

**Verification:**
- Seed test DB with different prices at t0 and t0+4h; assert expected direction
- Assert repeated calls observe newly inserted prices
- Assert stale/missing prices do not update beliefs

---

### 2. One canonical, idempotent belief pipeline

**Files:** `analysis/belief_updater.py`, `orchestrator.py`, `scheduler.py`, `bayesian/beliefs.py`, `analysis/source_weights.py`, `inference.py`, `signals/service.py`

**Problem:** Three divergent "accuracy" concepts: database accuracy (batch job, correct prices), live bandit utility (cached prices, broken), inference source weights (normalized). The 30-minute updater recomputes beliefs correctly but the running bandit never reloads them. The belief updater reuses all historical observations every run (inflating confidence).

**Approach:**
1. Define the Beta posterior as directional prediction accuracy only. Novelty must not update α/β.
2. Aggregate observations by `source + UTC hour` (posts in the same hour share the same price outcome — they are not independent trials).
3. Use a small sentiment deadband (±0.05); neutral observations are abstentions, not failures.
4. Recompute deterministically from a fixed neutral prior (α=1, β=1), using a configurable rolling window (default 90 days).
5. Have the updater return a complete versioned snapshot. Under an async lock, atomically apply it to the running bandit in-memory.
6. Compute and save source weights from the same snapshot version. Write JSON via temp file + `os.replace`.
7. Add TTL/version check to `SentimentAnalyzer` and `SignalService` (both load weights only at startup).
8. Rebuild α/β from raw data — current values are contaminated by the novelty utility.

**Effort:** 1.5–2 days

**Verification:**
- Two identical updater runs produce byte-equivalent beliefs except timestamps
- Modified beliefs are visible to the next bandit selection without restart
- Dashboard accuracy, source weights, and in-memory bandit share one version
- Novelty changes cannot change α/β

---

### 3. Fail closed on unsupported contrarian inversion

**Files:** `analysis/belief_updater.py`, `analysis/source_weights.py`, `dashboard/queries.py`

**Problem:** Sources are labeled "contrarian" at a fixed <45% threshold with no confidence interval, no minimum sample size, no out-of-time validation. Several contrarian sources have naive CIs that include 50%.

**Approach:**
Until out-of-time validation is implemented, classify a source as contrarian only when:
- At least 100 evaluated source-hours exist, AND
- The 95% Beta credible interval lies entirely below 50% (`P(p < 0.5) ≥ 0.975`)

Otherwise classify as neutral/insufficient and do NOT invert sentiment.

**Effort:** 3–4 hours

**Verification:**
- Source at 40% with 20 observations → neutral (not contrarian)
- Source at 44% with 100 observations → neutral (CI includes 50%)
- Source at 40% with 500 observations → contrarian

---

### 4. Quarantine inactive sources and archive ghosts

**Files:** `bayesian/beliefs.py`, `bayesian/bandit.py`, `orchestrator.py`, new `scripts/archive_ghost_sources.py`

**Problem:** Dead sources with zero data for months remain eligible after cooldown expires. Ghost entries (4chan_biz, stocktwits, coindesk, cointelegraph) have beliefs from an older system but zero raw posts in current DB.

**Approach:**
- Add `last_success_at`, `status`, and `next_probe_at` to beliefs
- After configurable empty threshold + inactivity period, mark source `inactive`
- Probe inactive sources at low frequency (daily), not hourly cooldown resets
- After 30 days without content, archive the source
- Remove the "if all are on cooldown, use all" fallback (reintroduces dead sources)
- Archive ghost entries: delete state + weights, never delete historical posts
- Remove hardcoded 4chan performance claims from frontend landing page

**Effort:** 0.5–1 day

**Verification:**
- Repeated empty crawls → source cannot return through cooldown expiry
- Successful probe reactivates the source
- All-inactive pool does not silently select archived sources
- Archive script reconciles active config, state, weights, and raw-post counts

---

### 5. Make CI enforce correctness

**File:** `.github/workflows/ci.yml`

**Problem:** CI uses `|| true` fallbacks for ruff, mypy, and pytest — all three can fail without blocking merge.

**Approach:**
Remove all `|| true` and `|| echo` fallbacks. At minimum, pytest and backend lint must block merging.

**Effort:** 30–60 minutes

**Verification:**
- Introduce a temporary failing assertion on the feature branch → CI fails
- Remove the assertion → CI passes

---

## Phase 2: Systematic Improvements (Next 2 Weeks)

### 6. Persistent, auditable outcome ledger

**Files:** `storage/db.py`, new `analysis/outcomes.py`, `orchestrator.py`, `scheduler.py`

Create a `prediction_outcomes` table with source, signal hour, before/after prices with timestamps, direction, correctness/abstention. Materialize one outcome per source-hour. All performance queries, baselines, and monitoring read this table. Eliminates loss of pending outcomes on restart.

**Effort:** 2 days

---

### 7. Calibrate sentiment zero and preserve scorer versions

**Files:** `processing/semantic_sentiment.py`, `processing/user_sentiment.py`, new calibration scripts

Fit affine or isotonic calibration using grouped cross-validation on the 154 human-labeled posts. Persist raw score, calibrated score, and calibration version. Fix `analyze()` vs `analyze_batch()` scoring divergence (different multipliers). Backfill scores into a new version rather than silently overwriting.

**Effort:** 2–3 days

---

### 8. Naive baselines and walk-forward evaluation

**Files:** `analysis/backtest_analysis.py`, new `analysis/baselines.py`

Test the system against always-bullish, always-bearish, 4-hour price persistence, and lagged majority direction. Use monthly walk-forward splits with block-bootstrap confidence intervals. Fit source weights only on training windows before evaluating test windows.

**Effort:** 2 days

---

### 9. Confidence-aware contrarian status and weights

**Files:** `analysis/belief_updater.py`, `analysis/source_weights.py`, dashboard frontend

Require: sufficient effective source-hours, posterior probability excluding 50%, positive inverted edge over the strongest naive baseline, AND persistence in at least two consecutive out-of-time windows. Derive weight from conservative expected edge, not raw `abs(accuracy - 0.5)`.

**Effort:** 1–1.5 days

---

### 10. Rename narrow regex dimensions honestly

**Files:** `processing/user_sentiment.py`, dashboard, frontend

Rename `fear_index` → "explicit fear-phrase rate", `euphoria_index` → "explicit euphoria/FOMO-phrase rate", `activity_level` → "warning/scam phrase rate". Expose matched count, total segment count, and coverage. Remove language implying these are comprehensive latent psychological indices.

**Effort:** 0.5–1 day

---

## Phase 3: Monitoring & Prevention (Ongoing)

### 11. End-to-end production-path integration test

**Files:** new `tests/test_crawl_to_bandit_integration.py`

Synthetic crawl → raw insert → score → source-hour outcome → two time-correct prices → evaluation → posterior rebuild → in-memory apply → source weight write → bandit selection. Assert correct prices, idempotent outcomes, expected α/β, version agreement.

**Effort:** 1–2 days

---

### 12. Operational heartbeats and data health dashboard

**Files:** `storage/db.py` (new `pipeline_heartbeats` table), `scheduler.py`, `dashboard/routes.py` (new `/api/ops/health`)

Track: latest price age, last scored content age, oldest pending outcome, version mismatch between in-memory/DB/state, inactive source selections (expected: 0). Return 503 on critical freshness failures. Emit structured logs for external uptime monitoring.

**Effort:** 1–2 days

---

### 13. Scheduled data-quality audit

**Files:** new `scripts/audit_pipeline_health.py`, scheduler job

Run daily: fail on duplicate outcomes, stale prices, impossible timestamps, source-count disagreement, weights without data, non-idempotent beliefs, unsupported contrarian inversion.

**Effort:** 1 day

---

## Key Principles

1. **DB outcomes/performance are authoritative.** JSON state and in-memory beliefs are derived checkpoints.
2. **Version every derived snapshot.** Never overwrite without versioning.
3. **Price matching must target exact signal + horizon timestamps.** Never use one latest price for all outcomes.
4. **Hourly aggregation is essential.** Thousands of posts sharing overlapping 4-hour returns are not independent trials.
5. **Rebuild α/β from raw data under new evaluator version.** Current values are contaminated.
6. **Quarantine first, probe slowly, archive only with explicit evidence.** Never auto-delete.

---

*Generated from the July 2026 production database audit. All items verified against live codebase and 255MB production SQLite DB.*
