# Crypto Contrarian Signals Service

> Real-time detection of sentiment-price divergences that historically precede market reversals.

## Overview

The Contrarian Signal Service detects sentiment-price divergences based on our causal analysis finding that sentiment **lags** price by ~15 hours. We flip the script: extreme sentiment at stable prices indicates potential reversals.

### Key Features

- **Dynamic Source Weights**: Learned from Bayesian beliefs, stored in database
- **Contrarian Source Handling**: Sources with <45% accuracy have sentiment inverted
- **Multi-Dimensional Signals**: fear_index, euphoria_index, activity_level from segment categorization
- **Filtered Sentiment**: Uses `final_score` from user_sentiment_scores (excludes bots/scams)
- **Real-time Alerts**: Telegram and Ntfy.sh push notifications
- **REST API**: FastAPI endpoints with subscription tiers and multi-dimensional fields
- **Signal Cooldown**: 6-hour minimum between signals to prevent spam

## How It Works

### Signal Types

| Signal | Condition | Multi-Dimensional Boost |
|--------|-----------|------------------------|
| **BULLISH_DIVERGENCE** | Extreme fear + price stable/rising | `fear_index > 15%` boosts confidence |
| **BEARISH_DIVERGENCE** | Extreme greed + price stable/falling | `euphoria_index > 15%` boosts confidence |
| **CAPITULATION** | Extreme negative sentiment OR `fear_index > 25%` | Actual losses detected |
| **EUPHORIA** | Extreme positive sentiment OR `euphoria_index > 25%` | FOMO/moon talk detected |

### Multi-Dimensional Signals

The service now uses segment-level categorization for more accurate signal detection:

| Metric | Source | Use Case |
|--------|--------|----------|
| `final_score` | Filtered sentiment (excludes bots/scams) | Bayesian accuracy measurement |
| `fear_index` | Proportion of loss/panic segments | Contrarian BUY signal strength |
| `euphoria_index` | Proportion of moon/FOMO segments | Contrarian SELL signal strength |
| `activity_level` | Proportion of scam/warning segments | Market activity indicator |

### Signal Strength

- **Strong**: Z-score > 2σ, high divergence
- **Moderate**: Z-score > 1.5σ, moderate divergence
- **Weak**: Z-score > 1σ, low divergence

### Weighted Sentiment Aggregation

The signal service uses dynamic source weights learned from Bayesian beliefs:

1. **Load weights** from `source_weights` database table
2. **Identify contrarian sources** (accuracy < 45%)
3. **Invert sentiment** for contrarian sources
4. **Compute weighted average** per hour
5. **Calculate Z-scores** against 30-day baseline

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Signal Service                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Crawler    │───▶│   Database   │───▶│   Detector   │  │
│  │ (sentiment)  │    │  (SQLite)    │    │  (signals)   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│          │                   │                    │        │
│          ▼                   ▼                    ▼        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Belief     │───▶│   Source     │───▶│   Weighted   │  │
│  │   Updater    │    │   Weights    │    │  Aggregation │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                    │        │
│                                                    ▼        │
│                                          ┌──────────────┐   │
│                                          │   Alerts     │   │
│                                          │(Telegram/Ntfy│   │
│                                          └──────────────┘   │
│                                                    │        │
│                                                    ▼        │
│                                          ┌──────────────┐   │
│                                          │   REST API   │   │
│                                          │  (FastAPI)   │   │
│                                          └──────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Description |
|------|-------------|
| `signals/detector.py` | Core signal detection algorithm |
| `signals/models.py` | Signal and strength data models |
| `signals/alerts.py` | Telegram + Ntfy.sh alert delivery |
| `signals/service.py` | Main service with weighted aggregation |
| `signals/api.py` | REST API (FastAPI) |
| `signals/cli.py` | Command-line interface |
| `signals/backtest.py` | Signal backtesting |
| `signals/optimize.py` | Parameter optimization |

## Usage

### CLI Commands

```bash
# Run a single signal check
uv run signals check

# Start continuous monitoring (default: 1-minute checks)
uv run signals run

# Run with custom interval
SIGNAL_CHECK_INTERVAL=5 uv run signals run

# Test Ntfy notifications
uv run signals test-ntfy your_topic_here

# Start Telegram bot
TELEGRAM_BOT_TOKEN=xxx uv run signals bot
```

### Task Manager

```bash
# Start signal service
uv run python -m crypto_sentiment_crawler.taskmanager start signals

# Check status
uv run python -m crypto_sentiment_crawler.taskmanager status

# View logs
uv run python -m crypto_sentiment_crawler.taskmanager logs signals
```

### REST API

```bash
# Start API server
uv run python -m crypto_sentiment_crawler.signals.api

# Endpoints
GET /                    # Service info
GET /market/BTC          # Current market summary
GET /signals             # Check for signals
GET /signals/history     # Recent signals
GET /pricing             # Subscription tiers
POST /subscribe          # Start subscription checkout
```

### Example API Response

**Market Summary (`GET /market/BTC`):**
```json
{
  "coin": "BTC",
  "timestamp": "2026-02-01T18:30:00",
  "current_price": 78095.0,
  "price_change_24h": -4.0,
  "price_change_7d": -11.9,
  "sentiment_score": -0.241,
  "sentiment_zscore": -0.28,
  "sentiment_state": "Fear",
  "divergence_score": -0.056,
  "activity_level": 0.152,
  "fear_index": 0.032,
  "euphoria_index": 0.041
}
```

**Signal Detected (`GET /signals`):**
```json
{
  "signal_detected": true,
  "signal": {
    "timestamp": "2026-02-01T18:30:00",
    "signal_type": "bullish_divergence",
    "strength": "moderate",
    "coin": "BTC",
    "sentiment_score": -0.45,
    "sentiment_zscore": -1.8,
    "price_change_24h": 0.5,
    "price_change_7d": -8.2,
    "divergence_score": 0.35,
    "description": "Extreme fear detected (sentiment -0.45, -1.8σ below mean) while price is stabilizing (+0.5% 24h). Fear index: 18.5%. Historically, this divergence precedes recoveries.",
    "confidence": 0.76
  }
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | Path to sentiment database | `data/sentiment.db` |
| `SIGNAL_CHECK_INTERVAL` | Check interval (minutes) | 1 |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | - |
| `NTFY_TOPIC` | Ntfy.sh topic for push notifications | - |

### Ntfy.sh Setup (Recommended)

Ntfy.sh provides free push notifications without account creation:

1. Choose a unique topic name (e.g., `my-crypto-signals-abc123`)
2. Subscribe on your phone:
   - iOS: Download Ntfy app, add topic
   - Android: Download Ntfy app, add topic
   - Or use web: `https://ntfy.sh/your_topic_here`
3. Set environment variable:
   ```bash
   export NTFY_TOPIC=your_topic_here
   ```
4. Test notification:
   ```bash
   uv run signals test-ntfy your_topic_here
   ```

### Telegram Bot Setup

1. Create bot via [@BotFather](https://t.me/botfather)
2. Get bot token
3. Set `TELEGRAM_BOT_TOKEN` environment variable
4. Run: `uv run signals bot`

## Technical Details

### Detection Algorithm

```python
# Bullish Divergence Detection
if (
    sentiment < -0.3 and           # Fear threshold
    sentiment_zscore < -1.5 and    # Statistically extreme
    price_change_24h > -2.0        # Price not crashing
):
    signal = BULLISH_DIVERGENCE
```

### Z-Score Calculation

```
z = (current_sentiment - mean_30d) / std_30d
```

### Divergence Score

```
divergence = -sentiment × normalized_price_change × extremity_weight
```

### Weighted Aggregation

```python
# Load weights from database
weight_data = load_weights_from_db_sync(db_path)
source_weights = weight_data["weights"]
contrarian_sources = weight_data["contrarian_sources"]

# Query user_sentiment_scores (filtered sentiment) instead of sentiment_scores
cursor = await db.conn.execute("""
    SELECT uss.timestamp, up.source, uss.final_score,
           uss.activity_level, uss.fear_index, uss.euphoria_index
    FROM user_sentiment_scores uss
    JOIN user_profiles up ON uss.user_id = up.user_id
    WHERE uss.timestamp >= ?
""", (cutoff.isoformat(),))

# Compute weighted sentiment per hour
for ts_str, source, score, activity, fear, euphoria in sentiment_rows:
    weight = source_weights.get(source, 0.01)

    # Invert sentiment for contrarian sources
    if source in contrarian_sources:
        score = -score

    hourly_sentiment[hour_key].append((score, weight))
    hourly_multidim[hour_key]['fear'].append(fear)
    hourly_multidim[hour_key]['euphoria'].append(euphoria)

# Weighted average
weighted_avg = sum(s * w for s, w in scores_weights) / total_weight
```

## Signal Cooldown

To prevent notification spam:
- Minimum 6 hours between signals
- Cooldown resets after signal detection
- Configurable via `signal_cooldown` parameter

## Output Example

```
────────────────────────────────────────────────────────────
[2026-02-01 08:19:21] Check #1
────────────────────────────────────────────────────────────
  💰 BTC: $78,095  -4.0% (24h)  -11.9% (7d)
  📊 Sentiment: -0.241  Z-Score: -0.28σ  State: Fear
  📈 Divergence: -0.056
  🔍 Activity: 15.2%  Fear: 3.2%  Euphoria: 4.1%
  ✅ No signal - conditions within normal ranges

────────────────────────────────────────────────────────────
[2026-02-01 08:20:21] Check #2
────────────────────────────────────────────────────────────
  💰 BTC: $77,500  -5.2% (24h)  -12.5% (7d)
  📊 Sentiment: -0.52  Z-Score: -1.8σ  State: Extreme Fear
  📈 Divergence: 0.35
  🔍 Activity: 12.1%  Fear: 18.5%  Euphoria: 2.3%

  🚨 SIGNAL: BULLISH_DIVERGENCE
     Strength: moderate
     Confidence: 76%
     Extreme fear detected while price stabilizing. Fear index: 18.5%...
```

## Pricing Tiers

| Tier | Price | Signals | Coins | Features |
|------|-------|---------|-------|----------|
| **Free** | $0 | 3/week | BTC | Basic alerts |
| **Pro** | $9.99/mo | Unlimited | All | Priority alerts |
| **Enterprise** | $49.99/mo | Unlimited | All | API access, priority support |

## Limitations

1. **Not Financial Advice**: Signals are informational only
2. **Historical Patterns**: Past divergences don't guarantee future results
3. **Market Conditions**: Works best in ranging/reversing markets
4. **Data Latency**: ~1 minute delay from real-time
5. **Signal Cooldown**: 6-hour minimum between signals

## Troubleshooting

### No Signals Detected

1. Check user sentiment scores exist (multi-dimensional):
   ```bash
   sqlite3 data/sentiment.db "SELECT COUNT(*) FROM user_sentiment_scores WHERE timestamp > datetime('now', '-1 hour')"
   ```

2. Check signal cooldown (6 hours since last signal)

3. Verify source weights are loaded:
   ```bash
   sqlite3 data/sentiment.db "SELECT COUNT(*) FROM source_weights"
   ```

4. Check multi-dimensional metrics:
   ```bash
   sqlite3 data/sentiment.db "SELECT AVG(fear_index), AVG(euphoria_index), AVG(activity_level) FROM user_sentiment_scores WHERE timestamp > datetime('now', '-24 hours')"
   ```

### Alerts Not Sending

1. Verify Ntfy topic is set:
   ```bash
   echo $NTFY_TOPIC
   ```

2. Test notification:
   ```bash
   uv run signals test-ntfy your_topic_here
   ```

3. Check Telegram token for bot alerts

### Weighted Aggregation Issues

Run belief updater to create/update weights:
```bash
uv run python -m crypto_sentiment_crawler.analysis.belief_updater
```

---

*Last updated: 2026-02-01*
*Status: Production-ready with dynamic source weights and multi-channel alerts*
