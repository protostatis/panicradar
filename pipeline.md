# Pipeline Documentation

This document describes the background pipeline that continuously collects crypto sentiment data, updates Bayesian beliefs about source informativeness, and detects contrarian trading signals.

## Overview

The pipeline runs as a background daemon with scheduled jobs that:

1. **Crawl** sources using Bayesian selection (Thompson Sampling)
2. **Collect** price data for evaluation
3. **Analyze** sentiment using VADER + FinBERT transformer
4. **Evaluate** past predictions against actual price movements
5. **Update** beliefs about which sources are most informative
6. **Compute** dynamic source weights based on learned accuracy
7. **Detect** contrarian signals from sentiment-price divergence
8. **Alert** users via Telegram and Ntfy.sh push notifications

```
┌─────────────────────────────────────────────────────────────────────┐
│                      BACKGROUND PIPELINE                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│   │  Scheduler  │───▶│    Jobs     │───▶│   Storage   │            │
│   │ (APScheduler│    │  (async)    │    │  (SQLite)   │            │
│   └─────────────┘    └─────────────┘    └─────────────┘            │
│          │                  │                                       │
│          ▼                  ▼                                       │
│   ┌─────────────────────────────────────────────────────┐          │
│   │                    JOB SCHEDULE                      │          │
│   ├─────────────────────────────────────────────────────┤          │
│   │  Every 2 min   │  Crawl (Bayesian selection)        │          │
│   │  Every 5 min   │  Price collection                  │          │
│   │  Every 15 min  │  Outcome evaluation + belief update│          │
│   │  Every 30 min  │  Auto belief update + source weights│          │
│   │  Every 1 min   │  Signal detection (verbose mode)   │          │
│   │  Every 4 hours │  Fear & Greed index                │          │
│   │  Every 10 min  │  Statistics logging                │          │
│   └─────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Start All Services

```bash
# Start the crawler
uv run python -m crypto_sentiment_crawler.taskmanager start crawler

# Start signal detection
uv run python -m crypto_sentiment_crawler.taskmanager start signals

# Start belief auto-updater
uv run python -m crypto_sentiment_crawler.taskmanager start belief_auto

# Check status
uv run python -m crypto_sentiment_crawler.taskmanager status
```

### Single Commands

```bash
# Run inference (price prediction)
uv run python -m crypto_sentiment_crawler.inference

# Run signal check once
uv run signals check

# Update beliefs manually
uv run python -m crypto_sentiment_crawler.analysis.belief_updater
```

## Running Services

### Task Manager

The task manager provides unified control over all services:

```bash
# List all tasks and their status
uv run python -m crypto_sentiment_crawler.taskmanager status

# Start a specific task
uv run python -m crypto_sentiment_crawler.taskmanager start <task_name>

# Stop a running task
uv run python -m crypto_sentiment_crawler.taskmanager stop <task_name>

# View task logs
uv run python -m crypto_sentiment_crawler.taskmanager logs <task_name>
```

### Available Tasks

| Task | Command | Description |
|------|---------|-------------|
| `crawler` | `start crawler` | Live Reddit sentiment crawler |
| `signals` | `start signals` | Contrarian signal detector (1-min checks) |
| `belief_auto` | `start belief_auto` | Auto-update beliefs every 30 min |
| `backfill` | `start backfill` | Historical Reddit backfill |
| `biz_backfill` | `start biz_backfill` | 4chan /biz/ backfill |
| `stocktwits_backfill` | `start stocktwits_backfill` | Stocktwits backfill |
| `bitcointalk_backfill` | `start bitcointalk_backfill` | Bitcointalk forum backfill |
| `twitter_backfill` | `start twitter_backfill` | Twitter/X backfill (needs API key) |
| `price_backfill` | `start price_backfill` | Historical price data |
| `collector` | `start collector` | Scheduled multi-source collector |
| `backtest` | `start backtest` | Run backtest analysis |

## Scheduled Jobs

### 1. Crawl Job (Default: Every 2 minutes)

**Purpose**: Select a source using Thompson Sampling and crawl it.

**Process**:
1. Sample from each source's Beta posterior
2. Select source with highest sample (exploration-exploitation balance)
3. Crawl the source (Reddit, 4chan, Stocktwits, etc.)
4. Extract content, detect coins, analyze sentiment
5. Store raw data and sentiment scores
6. Queue for later evaluation

**Code Path**: `scheduler.py` → `orchestrator.py` → `crawler/pipeline.py`

### 2. Price Job (Default: Every 5 minutes)

**Purpose**: Collect current prices for tracked coins.

**Process**:
1. Fetch BTC, ETH, SOL prices from CoinGecko
2. Store price, volume, market cap
3. Used later for accuracy evaluation

**Code Path**: `scheduler.py` → `collectors/price.py`

### 3. Evaluation Job (Default: Every 15 minutes)

**Purpose**: Evaluate past predictions and update beliefs.

**Process**:
1. Find pending outcomes older than evaluation lag (default: 4 hours)
2. For each pending outcome:
   - Get current price
   - Compute accuracy: did sentiment predict price direction?
   - Compute novelty: how different from recent content?
   - Calculate utility: `0.7 * accuracy + 0.3 * novelty`
3. Update source beliefs (Bayesian update):
   - If utility > 0.5: `α += 1` (informative)
   - If utility ≤ 0.5: `β += 1` (not informative)
4. Save updated state

**Code Path**: `scheduler.py` → `orchestrator.py` → `bayesian/utility.py`

### 4. Belief Auto-Update Job (Default: Every 30 minutes)

**Purpose**: Update Bayesian beliefs and dynamic source weights.

**Process**:
1. Compute accuracy for each source (correct predictions / total)
2. Update belief parameters (alpha, beta)
3. Identify contrarian sources (accuracy < 45%)
4. Compute dynamic weights from beliefs
5. Save weights to `source_weights` database table
6. Log top momentum and contrarian sources

**Code Path**: `analysis/belief_auto_updater.py` → `analysis/belief_updater.py` → `analysis/source_weights.py`

### 5. Signal Detection Job (Default: Every 1 minute)

**Purpose**: Detect contrarian trading signals.

**Process**:
1. Load sentiment history with weighted aggregation
2. Invert sentiment for contrarian sources
3. Compute Z-scores against 30-day baseline
4. Check for signal conditions:
   - BULLISH_DIVERGENCE: Extreme fear + price stable/rising
   - BEARISH_DIVERGENCE: Extreme greed + price stable/falling
   - CAPITULATION: Extreme negative sentiment spike
   - EUPHORIA: Extreme positive sentiment spike
5. Apply signal cooldown (6 hours minimum between signals)
6. Send alerts via Telegram and/or Ntfy.sh

**Code Path**: `signals/service.py` → `signals/detector.py` → `signals/alerts.py`

### 6. Fear & Greed Job (Default: Every 4 hours)

**Purpose**: Collect market-wide sentiment baseline.

**Process**:
1. Fetch Fear & Greed Index from alternative.me
2. Normalize to -1 to +1 scale
3. Store as market-wide sentiment score

**Note**: Fear & Greed is a **collider** (caused by price), not a confounder. It's used for context but not for causal adjustment.

**Code Path**: `scheduler.py` → `collectors/fear_greed.py`

## Configuration

### Environment Variables

```bash
# .env
DATABASE_PATH=data/sentiment.db
TRACKED_COINS=BTC,ETH,SOL
LOG_LEVEL=INFO

# Alerts (optional)
TELEGRAM_BOT_TOKEN=your_token_here
NTFY_TOPIC=your_topic_here

# Twitter (optional)
TWITTER_BEARER_TOKEN=your_token_here
```

### Signal Detection Configuration

```bash
# Set check interval (default: 1 minute)
SIGNAL_CHECK_INTERVAL=1

# Set Ntfy topic for phone notifications
NTFY_TOPIC=my-crypto-signals
```

## Data Flow

```
1. STARTUP
   ├── Load saved state (beliefs, pending outcomes)
   ├── Load dynamic source weights from database
   ├── Initialize database connection
   └── Start scheduler

2. CRAWL CYCLE (every 2 min)
   ├── Thompson Sampling selects source
   │   └── Sample θ ~ Beta(α, β) for each source
   │   └── Pick source with highest θ
   ├── Crawl selected source
   │   └── Fetch HTML (rate-limited)
   │   └── Parse content
   │   └── Detect coins mentioned
   │   └── Analyze sentiment (VADER or FinBERT)
   ├── Store to database
   │   └── sentiment_raw (full content)
   │   └── sentiment_scores (processed)
   └── Queue for evaluation
       └── Record price at crawl time

3. EVALUATION CYCLE (every 15 min)
   ├── Find outcomes older than eval_lag (4 hours)
   ├── For each outcome:
   │   ├── Get current price
   │   ├── Compute accuracy
   │   │   └── 1.0 if sentiment direction == price direction
   │   │   └── 0.0 otherwise
   │   ├── Compute novelty
   │   │   └── 1.0 - max(cosine_similarity with recent)
   │   ├── Utility = 0.7 * accuracy + 0.3 * novelty
   │   └── Update belief
   │       └── α += 1 if utility > 0.5
   │       └── β += 1 if utility ≤ 0.5
   └── Save state

4. BELIEF AUTO-UPDATE (every 30 min)
   ├── Compute source accuracy from historical data
   ├── Update Bayesian beliefs (alpha, beta)
   ├── Identify contrarian sources (accuracy < 45%)
   ├── Compute dynamic weights
   │   └── weight = distance_from_50% × confidence
   │   └── Normalize to sum to 1.0
   └── Save weights to source_weights table

5. SIGNAL DETECTION (every 1 min)
   ├── Load sentiment with weighted aggregation
   │   └── Apply source weights from database
   │   └── Invert contrarian source sentiment
   ├── Compute Z-scores against 30-day baseline
   ├── Check signal conditions
   │   └── BULLISH_DIVERGENCE: fear + stable price
   │   └── BEARISH_DIVERGENCE: greed + falling price
   │   └── CAPITULATION: extreme negative spike
   │   └── EUPHORIA: extreme positive spike
   ├── Apply cooldown (6 hours between signals)
   └── Send alerts (Telegram, Ntfy.sh)

6. INFERENCE (on demand)
   ├── Load dynamic source weights from database
   ├── Compute weighted aggregate sentiment
   │   └── Invert contrarian source sentiment
   ├── Get price momentum
   ├── Apply prediction logic
   └── Return direction + confidence
```

## Monitoring

### Log Output

The services log to stdout and log files:

```
2026-02-01 08:19:21 - crypto_sentiment - INFO - Loaded 32 dynamic source weights (15 contrarian)
────────────────────────────────────────────────────────────
[2026-02-01 08:19:21] Check #1
────────────────────────────────────────────────────────────
  💰 BTC: $78,095  -4.0% (24h)  -11.9% (7d)
  📊 Sentiment: -0.241  Z-Score: -0.28σ  State: Fear
  📈 Divergence: -0.056
  ✅ No signal - conditions within normal ranges
```

### State Files

**Beliefs**: `data/orchestrator_state.json`
```json
{
  "beliefs": {
    "reddit_bitcoin": {
      "source": "reddit_bitcoin",
      "alpha": 8.5,
      "beta": 3.0,
      "accuracy": 0.502,
      "correlation": 0.15,
      "is_contrarian": false,
      "total_crawls": 461
    }
  },
  "total_crawls": 7400,
  "last_belief_update": "2026-02-01T08:14:36+00:00"
}
```

**Source Weights**: `source_weights` database table
```sql
SELECT source, weight, accuracy, is_contrarian FROM source_weights ORDER BY weight DESC;
```

### Database Queries

```bash
# Count records by source
sqlite3 data/sentiment.db "SELECT source, COUNT(*) FROM sentiment_raw GROUP BY source ORDER BY 2 DESC"

# Check recent sentiment
sqlite3 data/sentiment.db "SELECT source, score, timestamp FROM sentiment_scores ORDER BY timestamp DESC LIMIT 10"

# View source weights
sqlite3 data/sentiment.db "SELECT source, weight, accuracy, is_contrarian FROM source_weights ORDER BY weight DESC"
```

## Files

| File | Purpose |
|------|---------|
| `scheduler.py` | Background job scheduler |
| `orchestrator.py` | Integration layer |
| `inference.py` | Price prediction with dynamic weights |
| `taskmanager.py` | Task management CLI |
| `bayesian/bandit.py` | Thompson Sampling |
| `bayesian/beliefs.py` | Source belief model |
| `bayesian/utility.py` | Accuracy + novelty scoring |
| `analysis/belief_updater.py` | Update beliefs from data |
| `analysis/belief_auto_updater.py` | Continuous belief updates |
| `analysis/source_weights.py` | Dynamic weight computation |
| `signals/detector.py` | Contrarian signal detection |
| `signals/service.py` | Signal service with weighted aggregation |
| `signals/alerts.py` | Telegram + Ntfy.sh alerts |
| `crawler/pipeline.py` | Crawl execution |
| `processing/sentiment.py` | VADER + FinBERT sentiment |
| `data/sentiment.db` | SQLite database |
| `data/orchestrator_state.json` | Persisted beliefs |

## Troubleshooting

### No Belief Updates

Beliefs only update with sufficient data (minimum 20 samples per source). Check:

```bash
# Count samples per source
sqlite3 data/sentiment.db "SELECT source, COUNT(*) FROM sentiment_scores GROUP BY source"
```

### Signals Not Detecting

1. Check signal service is running:
   ```bash
   uv run python -m crypto_sentiment_crawler.taskmanager status
   ```

2. Check for signal cooldown (6 hours between signals)

3. Verify sentiment data exists:
   ```bash
   sqlite3 data/sentiment.db "SELECT COUNT(*) FROM sentiment_scores WHERE timestamp > datetime('now', '-1 hour')"
   ```

### Dynamic Weights Not Loading

Run belief updater to create/update weights:

```bash
uv run python -m crypto_sentiment_crawler.analysis.belief_updater
```

Check weights exist:
```bash
sqlite3 data/sentiment.db "SELECT COUNT(*) FROM source_weights"
```

---

*Last updated: 2026-02-01*
