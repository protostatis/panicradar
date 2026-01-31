# Pipeline Documentation

This document describes the background pipeline that continuously collects crypto sentiment data and updates Bayesian beliefs about source informativeness.

## Overview

The pipeline runs as a background daemon with scheduled jobs that:

1. **Crawl** sources using Bayesian selection (Thompson Sampling)
2. **Collect** price data for evaluation
3. **Evaluate** past predictions against actual price movements
4. **Update** beliefs about which sources are most informative

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
│   │  Every 4 hours │  Fear & Greed index                │          │
│   │  Every 10 min  │  Statistics logging                │          │
│   └─────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Start the Background Daemon

```bash
# Default settings (recommended)
uv run crawler

# Custom intervals
uv run crawler background --crawl-interval 60 --price-interval 300 --eval-interval 900
```

### Check Status

```bash
# View current statistics
uv run crawler stats
```

### Stop the Daemon

Press `Ctrl+C` in the terminal, or if running in background:

```bash
kill $(cat crawler.pid)
```

## Running Methods

### Method 1: Foreground (Development)

Best for development and monitoring:

```bash
uv run crawler
```

Output is printed to terminal. Press `Ctrl+C` to stop.

### Method 2: Background with nohup

Run detached from terminal:

```bash
# Start
nohup uv run crawler > logs/crawler.log 2>&1 &
echo $! > crawler.pid

# View logs
tail -f logs/crawler.log

# Stop
kill $(cat crawler.pid)
```

### Method 3: Screen Session

Persistent terminal session:

```bash
# Create session
screen -S crawler

# Run crawler
uv run crawler

# Detach: Ctrl+A, then D

# Reattach later
screen -r crawler

# Stop: Ctrl+C in session
```

### Method 4: tmux Session

Alternative to screen:

```bash
# Create session
tmux new -s crawler

# Run crawler
uv run crawler

# Detach: Ctrl+B, then D

# Reattach later
tmux attach -t crawler
```

### Method 5: Systemd Service (Production)

Create `/etc/systemd/system/crypto-crawler.service`:

```ini
[Unit]
Description=Crypto Sentiment Crawler
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/crypto_sentiment_crawler
ExecStart=/path/to/.venv/bin/python -m crypto_sentiment_crawler.main background
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable crypto-crawler
sudo systemctl start crypto-crawler
sudo systemctl status crypto-crawler
```

## Scheduled Jobs

### 1. Crawl Job (Default: Every 2 minutes)

**Purpose**: Select a source using Thompson Sampling and crawl it.

**Process**:
1. Sample from each source's Beta posterior
2. Select source with highest sample (exploration-exploitation balance)
3. Crawl the source (Reddit, news, etc.)
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

### 4. Fear & Greed Job (Default: Every 4 hours)

**Purpose**: Collect market-wide sentiment baseline.

**Process**:
1. Fetch Fear & Greed Index from alternative.me
2. Normalize to -1 to +1 scale
3. Store as market-wide sentiment score

**Code Path**: `scheduler.py` → `collectors/fear_greed.py`

### 5. Stats Job (Default: Every 10 minutes)

**Purpose**: Log current statistics.

**Output**:
```
📊 Stats | uptime: 2.5h | crawls: 45 | prices: 30 | evals: 12 | errors: 0
```

## Configuration

### Command Line Options

```bash
uv run crawler background [OPTIONS]

Options:
  --crawl-interval INT    Seconds between crawls (default: 120)
  --price-interval INT    Seconds between price updates (default: 300)
  --eval-interval INT     Seconds between evaluations (default: 900)
```

### Environment Variables

```bash
# .env
DATABASE_PATH=data/sentiment.db
TRACKED_COINS=BTC,ETH,SOL
LOG_LEVEL=INFO
```

### Evaluation Lag

The evaluation lag (time before checking if prediction was correct) is set in the orchestrator:

```python
# orchestrator.py
orchestrator = CrawlerOrchestrator(db, eval_lag_hours=4)
```

Shorter lag = faster belief updates but less time for price to react.
Longer lag = more reliable signal but slower learning.

## Data Flow

```
1. STARTUP
   ├── Load saved state (beliefs, pending outcomes)
   ├── Initialize database connection
   ├── Run initial price collection
   └── Start scheduler

2. CRAWL CYCLE (every 2 min)
   ├── Thompson Sampling selects source
   │   └── Sample θ ~ Beta(α, β) for each source
   │   └── Pick source with highest θ
   ├── Crawl selected source
   │   └── Fetch HTML (rate-limited)
   │   └── Parse content
   │   └── Detect coins mentioned
   │   └── Analyze sentiment
   ├── Store to database
   │   └── sentiment_raw (full content)
   │   └── sentiment_scores (processed)
   └── Queue for evaluation
       └── Record price at crawl time

3. EVALUATION CYCLE (every 15 min)
   ├── Find outcomes older than eval_lag
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

4. BELIEF EVOLUTION
   ├── Initially: all sources equal (α=1.5, β=1.0)
   ├── Over time: good sources get higher α
   ├── Thompson Sampling favors high-α sources
   └── But still explores uncertain sources
```

## Monitoring

### Log Output

The crawler logs to stdout with timestamps:

```
2026-01-31 11:15:42 - crypto_sentiment - INFO - Selected: reddit_ethereum (sampled=0.966, mean=0.600)
2026-01-31 11:15:45 - crypto_sentiment - INFO - Crawled: Bitcoin price surge... (novelty=1.000)
2026-01-31 11:15:57 - crypto_sentiment - INFO - Evaluated 3 outcomes, updated beliefs
2026-01-31 11:15:57 - crypto_sentiment - INFO - Updated rankings:
2026-01-31 11:15:57 - crypto_sentiment - INFO -   reddit_bitcoin: 0.720 (n=15)
2026-01-31 11:15:57 - crypto_sentiment - INFO -   reddit_cryptocurrency: 0.650 (n=12)
```

### State File

Beliefs are persisted to `data/orchestrator_state.json`:

```json
{
  "beliefs": {
    "reddit_bitcoin": {
      "source": "reddit_bitcoin",
      "alpha": 8.5,
      "beta": 3.0,
      "total_crawls": 11
    }
  },
  "total_crawls": 45,
  "baseline_informativeness": 0.5
}
```

### Database

Query the SQLite database directly:

```bash
sqlite3 data/sentiment.db "SELECT source, COUNT(*) FROM sentiment_raw GROUP BY source"
```

### Stats Command

```bash
uv run crawler stats
```

Output:
```
📊 LIVE STATS
==================================================
Total crawls: 45
Raw records: 67
Scores: 89
Prices: 54
Last crawl: reddit_bitcoin at 2026-01-31T12:45:00
==================================================
```

## Troubleshooting

### Crawler Not Starting

1. Check Python environment:
   ```bash
   uv run python --version
   ```

2. Check database directory exists:
   ```bash
   mkdir -p data
   ```

3. Check for port conflicts (if any web server):
   ```bash
   lsof -i :8080
   ```

### No Belief Updates

Beliefs only update after the evaluation lag (default 4 hours). Check:

1. Pending outcomes exist:
   ```bash
   uv run crawler stats
   ```

2. Price data is being collected:
   ```sql
   SELECT COUNT(*) FROM price_data WHERE timestamp > datetime('now', '-1 hour');
   ```

### High Error Rate

Check the logs for specific errors:

```bash
grep "ERROR" logs/crawler.log | tail -20
```

Common issues:
- Rate limiting (reduce crawl frequency)
- Network timeouts (check internet connection)
- Site structure changed (update selectors)

### Memory Usage

The crawler maintains recent content for novelty comparison. If memory is high:

1. Reduce `max_recent_docs` in `UtilityScorer`
2. Increase crawl interval
3. Clear old data periodically

## Files

| File | Purpose |
|------|---------|
| `scheduler.py` | Background job scheduler |
| `orchestrator.py` | Integration layer |
| `bayesian/bandit.py` | Thompson Sampling |
| `bayesian/beliefs.py` | Source belief model |
| `bayesian/utility.py` | Accuracy + novelty scoring |
| `crawler/pipeline.py` | Crawl execution |
| `data/sentiment.db` | SQLite database |
| `data/orchestrator_state.json` | Persisted beliefs |
