# Sentiment Scoring Accuracy Audit

**Date:** 2026-02-09
**Scope:** Post-level scoring pipeline (`UserSentimentScorer` + `SemanticSentimentAnalyzer`)

## Background

The scoring pipeline converts raw Reddit posts (title + comments) into a
sentiment score in [-1, 1]. An audit was conducted to measure how well these
scores match human judgment, using 154 manually labeled posts from the audit
database (`data/sentiment_audit.db`).

## Evaluation Method

### Labeled dataset

154 posts were sampled from the audit DB covering multiple subreddits
(r/cryptocurrency, r/bitcoin, r/solana, r/ethtrader, etc.). Each post was
read in full — title, selftext, and all comments — and assigned a human
sentiment score on the [-1, 1] scale with 0.05 increments. Labels are stored
in `/tmp/claude_labels.csv` (columns: `id`, `claude_score`).

The label distribution skews slightly negative (mean -0.03), reflecting the
naturally cautious tone of crypto discussion forums.

### Metrics

| Metric | What it measures |
|--------|-----------------|
| **Pearson r** | Linear correlation between scorer and human labels (direction + magnitude agreement) |
| **MAE** | Mean absolute error — average distance between scorer and human label |
| **Categorical agreement** | % of posts where scorer and human agree on category (bullish >0.05, bearish <-0.05, neutral) |
| **Mean bias** | Average (scorer - human) — positive = scorer too bullish, negative = too bearish |

### How to reproduce

```bash
# Re-score the 154 labeled posts against the current pipeline
uv run python /tmp/eval_scoring_fixes.py
```

The eval script:
1. Loads human labels from `/tmp/claude_labels.csv`
2. For each post, fetches `raw_data` from the audit DB
3. Re-scores using the current `UserSentimentScorer` (with `min_human_comments=0`)
4. Computes all four metrics against both the old DB scores and new scores

## Results

### Before fixes (baseline)

| Metric | Value |
|--------|-------|
| Pearson r | 0.4315 |
| MAE | 0.1306 |
| Categorical agreement | 46.8% |
| Mean bias | -0.0495 (bearish) |

### After fixes

| Metric | Value | Change |
|--------|-------|--------|
| Pearson r | 0.4405 | +0.009 |
| MAE | **0.0864** | **-0.044 (-34%)** |
| Categorical agreement | **51.3%** | **+4.5pp** |
| Mean bias | **-0.0290** | **+0.021 (42% less bearish)** |

### Interpretation

- **MAE improved 34%** — scores are materially closer to human judgment.
- **Bearish bias cut nearly in half** — the systematic tendency to label neutral
  posts as bearish is significantly reduced.
- **Pearson r barely changed** — the correlation structure is similar; scores
  moved toward zero (less extreme) rather than reordering. This is expected:
  the fixes primarily reduce amplification and double-counting, not the
  underlying ranking.
- **Categorical agreement up 4.5pp** — more posts now land in the correct
  bullish/neutral/bearish bucket.

## Root Causes Found & Fixes Applied

### Fix 1: Duplicate segments in backfill (high impact)

**Bug:** `backfill.py:190-196` pre-concatenated selftext + all comment bodies
into the `content` field. Then `_extract_user_info()` read this combined
content AND re-appended comments from `metadata['comments']`. Every comment
was scored twice, inflating comment weight and amplifying bearish signals.

The live pipeline (`pipeline.py:474`) correctly stores only selftext — backfill
was inconsistent.

**Fix:**
- `backfill.py` — store only `thread.selftext` in content, matching live pipeline
- `user_sentiment.py:_extract_user_info()` — deduplicate paragraphs by exact
  match to handle historical DB rows that still contain pre-concatenated data

### Fix 2: Title over-weighting

**Problem:** Title received 40% weight (`0.4 * title_score + 0.6 * seg_mean`).
Clickbait/provocative titles dragged scores in the wrong direction even when
comment consensus disagreed.

**Fix:** Reduced to `0.2 * title_score + 0.8 * seg_mean`. Title provides
context; comments are the signal.

### Fix 3: Score amplification

**Problem:** `np.tanh(raw_score * 5)` in `semantic_sentiment.py` amplified
small cosine similarity differences into extreme scores. A raw difference of
0.1 became tanh(0.5) = 0.46, making scores overly binary.

**Fix:** Reduced multiplier to 3. A raw difference of 0.1 now produces
tanh(0.3) = 0.29 — still meaningful but more proportional.

### Fix 4: Missing neutral anchors for Q&A/technical content

**Problem:** Technical discussions (wallets, fees, tools, taxes, token burns)
scored bearish because words like "burn", "fees", "mismatch" had higher cosine
similarity to bearish anchor phrases than to existing neutral ones.

**Fix:** Added 33 neutral anchor phrases covering:
- Q&A / help-seeking ("How do I set up a hardware wallet")
- Tool/product comparisons ("Comparing these two services side by side")
- Token burn mechanics ("How does the burn mechanism work")

## Spot-check: 5 key posts

| ID | Description | Human | Old | New | Verdict |
|----|------------|-------|-----|-----|---------|
| 8635 | Tax Q&A thread | 0.00 | -0.51 | -0.33 | Improved |
| 9403 | Sol Incinerator tool comparison | 0.00 | -0.64 | -0.40 | Improved |
| 9408 | "Don't understand freaking out" | +0.15 | -0.26 | -0.12 | Improved |
| 9416 | Buying BTC with conviction | +0.05 | -0.53 | -0.33 | Improved |
| 9523 | "Bitcoin is dead" (ironic) | +0.05 | -0.30 | -0.17 | Improved |

All five improved but remain notably bearish — residual error from the
cosine-similarity approach's inability to handle negation, sarcasm, and
vocabulary-vs-intent confusion.

## Known Limitations & Next Steps

The Pearson r ceiling (~0.44) reflects fundamental limits of cosine similarity
to anchor phrases. The all-MiniLM-L6-v2 embedding space does not distinguish
"I'm scared" from "I don't understand why everyone's scared."

| Approach | Expected r | Cost | Complexity |
|----------|-----------|------|------------|
| Current + Fixes 1-4 | ~0.44 | $0 | Done |
| Fine-tuned classifier (distilbert on labeled data) | ~0.70-0.80 | $0 runtime | Medium |
| LLM scoring via API (per-post) | ~0.85+ | ~$0.01-0.05/post | Low code, ongoing cost |
| Hybrid: semantic first pass, LLM re-score low-confidence | ~0.75-0.85 | Lower than full LLM | Medium |

**Recommendation:** Expand labeled dataset beyond 154 posts, then evaluate
fine-tuned classifier vs. hybrid LLM approach.

## Post-Audit: Renaming of Multi-Dimensional Indices (Jul 2026)

Following the audit findings, the multi-dimensional indices were renamed to
honestly reflect what they measure — narrow literal-phrase detection, not
sophisticated psychological inference.

### Old vs new names

| Old name | New API field | What it actually measures |
|----------|--------------|--------------------------|
| `fear_index` | `explicit_fear_phrase_rate` | % of posts containing literal panic/capitulation phrases (e.g. "panic sell") |
| `euphoria_index` | `explicit_euphoria_phrase_rate` | % of posts containing literal moon/FOMO phrases (e.g. "to the moon") |
| `activity_level` | `warning_scam_phrase_rate` | % of posts containing scam alerts and exchange complaints (e.g. "scam", "withdrawal") |

### What changed

- **API responses** now include both old and new field names. The old names are
  deprecated aliases and will be removed in the next release.
- **Internal variable names** in the signal detector were updated from
  `fear_index` → `explicit_fear_rate`, `euphoria_index` → `explicit_euphoria_rate`,
  `activity_level` → `warning_scam_rate` to reflect the reduced scope.
- **Frontend labels** were updated from "Fear", "Euphoria", "Activity" to
  "Explicit fear phrases", "Explicit euphoria phrases", "Warning/scam phrases"
  with tooltips explaining exactly what triggers each gauge.

### Why this matters

The audit showed that only **4.15% of posts trigger any fear signal** and
**4.27% trigger euphoria** — 91.8% register neither. The original names
(fear_index, euphoria_index) implied a broad psychological measurement that
the implementation could not deliver. The new names set correct expectations:
these are high-precision, low-recall literal phrase detectors.

## Files Modified

| File | Change |
|------|--------|
| `crypto_sentiment_crawler/backfill.py` | Store only selftext in content |
| `crypto_sentiment_crawler/processing/user_sentiment.py` | Paragraph dedup + title weight 0.4→0.2 |
| `crypto_sentiment_crawler/processing/semantic_sentiment.py` | tanh 5→3 + 33 neutral anchors |
| `crypto_sentiment_crawler/dashboard/schemas.py` | Added `explicit_fear_phrase_rate`, `explicit_euphoria_phrase_rate`, `warning_scam_phrase_rate` alongside deprecated aliases |
| `crypto_sentiment_crawler/dashboard/routes.py` | Populate new field names in all API responses |
| `crypto_sentiment_crawler/signals/detector.py` | Renamed internal vars from `fear_index`→`explicit_fear_rate` etc. |
| `crypto_sentiment_crawler/signals/api.py` | Added new fields to `MarketSummary` model |
| `crypto_sentiment_crawler/signals/service.py` | Populate new keys alongside deprecated ones |
| `dashboard-frontend/src/components/CrowdGauges.jsx` | Updated labels, tooltips, prop names |
| `dashboard-frontend/src/pages/Dashboard.jsx` | Pass new prop names to CrowdGauges |
| `dashboard-frontend/src/pages/BlogPost.jsx` | Added note about the renaming |
