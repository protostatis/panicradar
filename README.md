# Crypto Sentiment Crawler

An intelligent web crawler that uses Bayesian inference and causal discovery to maximize the informativeness of crawled crypto sentiment data for price prediction.

## Overview

This project implements a **Bayesian-guided crawler** that learns which sources provide the most predictive sentiment signals for cryptocurrency prices. Key features:

1. **Bayesian Beliefs**: Maintains probabilistic beliefs about each source's informativeness using Beta distributions
2. **Thompson Sampling**: Balances exploration vs exploitation when selecting sources to crawl
3. **Dynamic Source Weights**: Learns accuracy-based weights stored in database, used for weighted sentiment aggregation
4. **Contrarian Signals**: Detects sentiment-price divergences that historically precede market reversals
5. **Multi-Dimensional Sentiment**: Segment-level analysis with fear_index, euphoria_index, and activity_level
6. **Transformer Sentiment**: Uses FinBERT (ProsusAI/finbert) for advanced sentiment analysis
7. **Real-time Alerts**: Telegram and Ntfy.sh push notifications for detected signals

## Key Discovery

**Causal analysis revealed that price leads sentiment by ~15 hours** - people react to price moves, not the reverse. This led to a pivot from momentum-based predictions to **contrarian signal detection**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BAYESIAN DECISION LAYER                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Source    │  │   Thompson  │  │   Dynamic   │             │
│  │   Beliefs   │──│   Sampling  │──│   Weights   │             │
│  │  Beta(α,β)  │  │   Bandit    │  │ (learned)   │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CRAWLER EXECUTION LAYER                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Fetcher   │  │   Parser    │  │  Sentiment  │             │
│  │   (httpx)   │──│(BeautifulSoup──│   Analysis  │             │
│  │ rate-limit  │  │  +selectors)│  │(VADER+BERT) │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SIGNAL DETECTION LAYER                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ Contrarian  │  │   Weighted  │  │   Alerts    │             │
│  │  Detector   │──│ Aggregation │──│(Telegram/   │             │
│  │             │  │ (+inversion)│  │    Ntfy)    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
# Clone and enter directory
cd crypto_sentiment_crawler

# Install with uv
uv sync

# Copy environment template
cp .env.example .env
```

## Quick Start

```bash
# Start all services
uv run python -m crypto_sentiment_crawler.taskmanager start crawler
uv run python -m crypto_sentiment_crawler.taskmanager start signals
uv run python -m crypto_sentiment_crawler.taskmanager start belief_auto

# Check status
uv run python -m crypto_sentiment_crawler.taskmanager status

# Run inference (price prediction)
uv run python -m crypto_sentiment_crawler.inference

# Run single signal check
uv run signals check
```

> **See [pipeline.md](pipeline.md) for detailed documentation on the background pipeline, scheduled jobs, and deployment options.**

## Data Sources

The crawler collects sentiment from multiple sources:

| Source | Type | Status | Notes |
|--------|------|--------|-------|
| Reddit (20+ subreddits) | Forum | ✅ Complete | High volume |
| 4chan /biz/ | Forum | ✅ Complete | High contrarian value |
| Stocktwits | Social | ✅ Complete | Trader sentiment |
| Bitcointalk | Forum | ✅ Complete | OG community |
| Twitter/X | Social | ✅ Complete | Requires API key |
| CoinDesk/CoinTelegraph | News | ✅ Basic | Headlines |
| Fear & Greed Index | Composite | ✅ Complete | Market baseline |

## Task Manager

Monitor and control all crawler tasks:

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
| `signals` | `start signals` | Contrarian signal detector |
| `belief_auto` | `start belief_auto` | Auto-update beliefs every 30 min |
| `backfill` | `start backfill` | Historical Reddit backfill |
| `biz_backfill` | `start biz_backfill` | 4chan /biz/ backfill |
| `stocktwits_backfill` | `start stocktwits_backfill` | Stocktwits backfill |
| `bitcointalk_backfill` | `start bitcointalk_backfill` | Bitcointalk forum backfill |
| `twitter_backfill` | `start twitter_backfill` | Twitter/X backfill (needs API key) |
| `price_backfill` | `start price_backfill` | Historical price data |
| `collector` | `start collector` | Scheduled multi-source collector |
| `backtest` | `start backtest` | Run backtest analysis |

## Signal Detection

The system detects 4 types of contrarian signals using **multi-dimensional sentiment**:

| Signal | Condition | Multi-Dimensional Enhancement |
|--------|-----------|------------------------------|
| **BULLISH_DIVERGENCE** | Extreme fear + price stable/rising | Boosted by high `fear_index` |
| **BEARISH_DIVERGENCE** | Extreme greed + price stable/falling | Boosted by high `euphoria_index` |
| **CAPITULATION** | Extreme negative sentiment spike | Triggers at `fear_index` > 25% |
| **EUPHORIA** | Extreme positive sentiment spike | Triggers at `euphoria_index` > 25% |

### Multi-Dimensional Signal Strength

The new segment-level analysis improves signal quality:
- **`fear_index`**: High values indicate actual losses/panic (not just negative words)
- **`euphoria_index`**: High values indicate FOMO/moon talk (not just positive words)
- **`activity_level`**: High values indicate scam activity (market is active)

### Alerts

Configure alerts in `.env`:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_token_here

# Ntfy.sh (free, no account needed)
NTFY_TOPIC=your_topic_here
```

Test Ntfy notifications:
```bash
uv run signals test-ntfy your_topic_here
```

## Dynamic Source Weights

The system learns which sources are most predictive:

1. **Accuracy Tracking**: Measures if sentiment correctly predicted price direction
2. **Bayesian Updates**: Updates Beta(α, β) beliefs based on accuracy
3. **Contrarian Detection**: Sources with <45% accuracy are marked as contrarian
4. **Weight Computation**: Weight = distance_from_50% × confidence
5. **Signal Inversion**: Contrarian source sentiment is inverted in aggregation

View current weights:
```bash
sqlite3 data/sentiment.db "SELECT source, weight, accuracy, is_contrarian FROM source_weights ORDER BY weight DESC"
```

## Core Concepts

### 1. Utility Function

Content informativeness is measured as:

```
U(content) = 0.7 × accuracy + 0.3 × novelty
```

- **Accuracy**: Did the sentiment correctly predict price direction?
- **Novelty**: How different is this from recently crawled content?

### 2. Source Beliefs

Each source has a Beta(α, β) distribution representing our belief about its informativeness:

```python
class SourceBelief:
    alpha: float   # Informative crawls
    beta: float    # Non-informative crawls
    accuracy: float
    is_contrarian: bool

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)
```

### 3. Thompson Sampling

Source selection uses Thompson Sampling for explore-exploit balance:

```python
def select_source(beliefs: dict[str, SourceBelief]) -> str:
    samples = {
        source: np.random.beta(b.alpha, b.beta)
        for source, b in beliefs.items()
    }
    return max(samples, key=samples.get)
```

### 4. Contrarian Signal Detection

Based on the key finding that **price leads sentiment by ~15 hours**:

```python
# Extreme sentiment at stable prices = potential reversal
if sentiment < -0.3 and zscore < -1.5 and price_stable:
    signal = BULLISH_DIVERGENCE  # Crowd scared but price not falling
```

## Sentiment Analysis

### Multi-Dimensional Scoring (Default)

The system uses **user-centric multi-dimensional scoring** that goes beyond simple sentiment:

```
┌─────────────────────────────────────────────────────────┐
│  Post Content                                           │
├─────────────────────────────────────────────────────────┤
│  ├── Segment 1 → FILTER (bot message, excluded)        │
│  ├── Segment 2 → ACTIVITY (scam warning, tracked)      │
│  ├── Segment 3 → TRUE_BEARISH (actual loss, included)  │
│  ├── Segment 4 → EUPHORIA (moon talk, tracked)         │
│  └── Segment 5 → STANDARD (normal content, included)   │
└─────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Multi-Dimensional Output                               │
│  ├── final_score: Filtered sentiment (for Bayesian)    │
│  ├── fear_index: 0-1 (contrarian BUY signal)           │
│  ├── euphoria_index: 0-1 (contrarian SELL signal)      │
│  └── activity_level: 0-1 (market activity indicator)   │
└─────────────────────────────────────────────────────────┘
```

**Segment Categories:**
| Category | Example Content | In Sentiment? | Tracked As |
|----------|-----------------|---------------|------------|
| `FILTER` | "I am a bot..." | ❌ Excluded | - |
| `ACTIVITY` | "Beware of scams..." | ❌ Excluded | `activity_level` |
| `TRUE_BEARISH` | "I lost $10k..." | ✅ Included | `fear_index` |
| `EUPHORIA` | "To the moon!" | ❌ Excluded | `euphoria_index` |
| `STANDARD` | Regular content | ✅ Included | - |

### VADER + Crypto Lexicon (Legacy)

Extended lexicon with 80+ crypto-specific terms:
- Bullish: "moon", "hodl", "diamond hands", "pump", etc.
- Bearish: "rekt", "rugpull", "scam", "dump", etc.
- Pattern-based corrections for complaints and questions

### FinBERT Transformer

```python
# Enable transformer
sentiment_analyzer = CryptoSentimentAnalyzer(use_transformer=True)
```

Uses ProsusAI/finbert with Apple Silicon MPS GPU support.

## Project Structure

```
crypto_sentiment_crawler/
├── pyproject.toml           # Dependencies (uv)
├── README.md                # This file
├── roadmap.md               # Development roadmap
├── pipeline.md              # Pipeline documentation
│
├── data/                    # Data storage
│   ├── sentiment.db         # SQLite database
│   ├── orchestrator_state.json  # Persisted beliefs
│   └── backtest_results.log # Backtest history
│
├── logs/                    # Log files
│
├── docs/                    # Documentation
│   ├── causal_analysis_findings.md
│   ├── signal_service.md
│   └── ...
│
└── crypto_sentiment_crawler/
    ├── config.py            # Settings
    ├── main.py              # Entry point
    ├── taskmanager.py       # Task manager CLI
    ├── orchestrator.py      # Integration layer
    ├── inference.py         # Price prediction
    │
    ├── bayesian/            # Decision layer
    │   ├── beliefs.py       # SourceBelief model
    │   ├── bandit.py        # Thompson Sampling
    │   ├── utility.py       # Accuracy + novelty
    │   └── cold_start.py    # Price autocorrelation
    │
    ├── causal/              # Causal discovery
    │   └── granger.py       # Granger causality
    │
    ├── analysis/            # Analysis layer
    │   ├── belief_updater.py      # Update beliefs
    │   ├── belief_auto_updater.py # Continuous updates
    │   ├── source_weights.py      # Dynamic weights
    │   └── backtest_analysis.py   # Backtesting
    │
    ├── signals/             # Signal detection
    │   ├── detector.py      # Contrarian signals
    │   ├── service.py       # Signal service
    │   ├── alerts.py        # Telegram/Ntfy
    │   ├── api.py           # REST API
    │   └── models.py        # Signal models
    │
    ├── crawler/             # Execution layer
    │   ├── fetcher.py       # Async HTTP
    │   ├── parser.py        # BeautifulSoup
    │   ├── pipeline.py      # Full pipeline
    │   └── sources.py       # Source config
    │
    ├── collectors/          # API collectors
    │   ├── fear_greed.py
    │   ├── price.py
    │   ├── reddit.py
    │   └── twitter.py
    │
    ├── processing/          # Content processing
    │   ├── sentiment.py     # VADER + FinBERT
    │   ├── semantic_sentiment.py  # Semantic similarity
    │   └── user_sentiment.py      # Multi-dimensional scoring
    │
    └── storage/             # Database layer
        ├── models.py
        └── db.py
```

## Implementation Status

### Complete

| Component | Status | Notes |
|-----------|--------|-------|
| Bayesian beliefs | ✅ | Beta distribution, Thompson Sampling |
| Utility scoring | ✅ | 0.7 accuracy + 0.3 novelty |
| Cold start | ✅ | Price autocorrelation baseline |
| Async fetcher | ✅ | Rate limiting, UA rotation |
| Reddit crawler | ✅ | 20+ subreddits |
| 4chan /biz/ crawler | ✅ | JSON API |
| Stocktwits crawler | ✅ | Public API |
| Bitcointalk crawler | ✅ | HTML scraping |
| Twitter/X crawler | ✅ | Requires API key |
| Sentiment analysis | ✅ | VADER + FinBERT + Semantic |
| **Multi-dimensional scoring** | ✅ | fear_index, euphoria_index, activity_level |
| **Segment categorization** | ✅ | FILTER, ACTIVITY, TRUE_BEARISH, EUPHORIA, STANDARD |
| **User-centric scoring** | ✅ | Tracks 3,000+ users with credibility |
| Granger causality | ✅ | Price leads sentiment finding |
| Dynamic source weights | ✅ | Learned from filtered accuracy |
| Contrarian signals | ✅ | 4 signal types with multi-dimensional boost |
| Signal alerts | ✅ | Telegram + Ntfy.sh |
| REST API | ✅ | FastAPI with multi-dimensional fields |
| Belief auto-updater | ✅ | Every 30 minutes |
| Task manager | ✅ | Start/stop/status |

### Pending

| Component | Status | Notes |
|-----------|--------|-------|
| Google Trends | ❌ | Low priority (lagging indicator) |
| Discord alerts | 📋 | Planned |
| Email alerts | 📋 | Planned |

## Example Output

### Inference

```
======================================================================
CRYPTO SENTIMENT INFERENCE
Lookback: 4h | Prediction Horizon: 4h
======================================================================

Using 32 learned weights from Bayesian beliefs (15 contrarian)

BTC ➡️
--------------------------------------------------
  Current Price:  $78,096.00
  Prediction:     NEUTRAL
  Confidence:     [████░░░░░░] 43%
  Sentiment:      -0.100
  Reasoning:      Sentiment is neutral (-0.100). Market in Extreme Fear...
```

### Signal Detection

```
────────────────────────────────────────────────────────────
[2026-02-01 08:19:21] Check #1
────────────────────────────────────────────────────────────
  💰 BTC: $78,095  -4.0% (24h)  -11.9% (7d)
  📊 Sentiment: -0.241  Z-Score: -0.28σ  State: Fear
  📈 Divergence: -0.056
  🔍 Activity: 15.2%  Fear: 3.2%  Euphoria: 4.1%
  ✅ No signal - conditions within normal ranges
```

### Belief Update

```
================================================================================
SOURCE WEIGHTS (from Bayesian Beliefs)
================================================================================

Source                         Weight     Accuracy   Type         Samples
--------------------------------------------------------------------------------
4chan_biz                      0.0800     37.9%      CONTRARIAN   6582
reddit_solana                  0.0697     38.7%      CONTRARIAN   183
stocktwits                     0.0677     40.1%      CONTRARIAN   1202
reddit_dogecoin                0.0311     58.8%      MOMENTUM     83
reddit_defi                    0.0292     53.6%      MOMENTUM     185
================================================================================
```

## Configuration

### Environment Variables

```bash
# .env
DATABASE_PATH=data/sentiment.db
TRACKED_COINS=BTC,ETH,SOL
LOG_LEVEL=INFO

# Alerts
TELEGRAM_BOT_TOKEN=...
NTFY_TOPIC=my-crypto-signals

# Twitter (optional)
TWITTER_BEARER_TOKEN=...

# Signal detection
SIGNAL_CHECK_INTERVAL=1  # minutes
```

## License

MIT

---

*Last updated: 2026-02-01*
