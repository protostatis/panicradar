# Crypto Contrarian Signals Service

> Revenue Model: Subscription-based signal alerts

## Overview

The Contrarian Signal Service detects sentiment-price divergences that historically precede market reversals. Based on our causal analysis finding that sentiment **lags** price by ~15 hours, we flip the script: extreme sentiment at stable prices indicates potential reversals.

## How It Works

### Signal Types

| Signal | Condition | Interpretation |
|--------|-----------|----------------|
| **BULLISH_DIVERGENCE** | Extreme fear + price stable/rising | Crowd scared but price not falling → potential bottom |
| **BEARISH_DIVERGENCE** | Extreme greed + price stable/falling | Crowd euphoric but price not rising → potential top |
| **CAPITULATION** | Extreme negative sentiment spike | Panic selling → often marks local bottoms |
| **EUPHORIA** | Extreme positive sentiment spike | Irrational exuberance → often marks local tops |

### Signal Strength

- **Strong** 🔥: Z-score > 2σ, high divergence
- **Moderate** 🟡: Z-score > 1.5σ, moderate divergence
- **Weak** ⚪: Z-score > 1σ, low divergence

## Pricing Tiers

| Tier | Price | Signals | Coins | Features |
|------|-------|---------|-------|----------|
| **Free** | $0 | 3/week | BTC | Basic alerts |
| **Pro** | $9.99/mo | Unlimited | All | Priority alerts |
| **Enterprise** | $49.99/mo | Unlimited | All | API access, priority support |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Signal Service                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Crawler    │───▶│   Database   │───▶│   Detector   │  │
│  │ (sentiment)  │    │  (SQLite)    │    │  (signals)   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                     │        │
│                                                     ▼        │
│                                          ┌──────────────┐   │
│                                          │   Alerts     │   │
│                                          │ (Telegram)   │   │
│                                          └──────────────┘   │
│                                                     │        │
│                                                     ▼        │
│                                          ┌──────────────┐   │
│                                          │ Subscribers  │   │
│                                          │ (Stripe)     │   │
│                                          └──────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Description |
|------|-------------|
| `signals/detector.py` | Core signal detection algorithm |
| `signals/models.py` | Signal and strength data models |
| `signals/alerts.py` | Telegram/Discord alert delivery |
| `signals/subscriptions.py` | Stripe subscription management |
| `signals/service.py` | Main service orchestrator |
| `signals/api.py` | REST API (FastAPI) |
| `signals/cli.py` | Command-line interface |

## Usage

### CLI Commands

```bash
# Run a single signal check
uv run signals check

# Start continuous monitoring
uv run signals run

# Start Telegram bot
TELEGRAM_BOT_TOKEN=xxx uv run signals bot
```

### API

```bash
# Start API server
uv run python -m crypto_sentiment_crawler.signals.api

# Endpoints
GET /                    # Service info
GET /market/BTC          # Current market summary
GET /signals             # Check for signals
GET /signals/history     # Recent signals (Enterprise)
GET /pricing             # Subscription tiers
POST /subscribe          # Start subscription checkout
```

### Example API Response

```json
{
  "signal_detected": true,
  "signal": {
    "timestamp": "2026-01-31T18:30:00",
    "signal_type": "bullish_divergence",
    "strength": "moderate",
    "coin": "BTC",
    "sentiment_score": -0.45,
    "sentiment_zscore": -1.8,
    "price_change_24h": 0.5,
    "price_change_7d": -8.2,
    "divergence_score": 0.35,
    "description": "Extreme fear detected while price stabilizing...",
    "confidence": 0.72
  }
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | Path to sentiment database | `data/sentiment.db` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | - |
| `STRIPE_API_KEY` | Stripe secret key | - |
| `SIGNAL_CHECK_INTERVAL` | Check interval (minutes) | 60 |

### Telegram Bot Setup

1. Create bot via [@BotFather](https://t.me/botfather)
2. Get bot token
3. Set `TELEGRAM_BOT_TOKEN` environment variable
4. Run: `uv run signals bot`

### Stripe Setup

1. Create Stripe account at [stripe.com](https://stripe.com)
2. Create products for Pro and Enterprise tiers
3. Get API keys from Dashboard
4. Set `STRIPE_API_KEY` environment variable
5. Configure webhook for subscription events

## Revenue Projections

| Scenario | Subscribers | Monthly Revenue |
|----------|-------------|-----------------|
| Conservative | 100 Pro | $999/mo |
| Moderate | 500 Pro + 10 Enterprise | $5,495/mo |
| Optimistic | 2000 Pro + 50 Enterprise | $22,480/mo |

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

## Limitations

1. **Not Financial Advice**: Signals are informational only
2. **Historical Patterns**: Past divergences don't guarantee future results
3. **Market Conditions**: Works best in ranging/reversing markets
4. **Data Latency**: ~15 min delay from real-time

## Next Steps

1. [ ] Set up Telegram bot in production
2. [ ] Create Stripe products and configure pricing
3. [ ] Deploy API to cloud (Railway/Render)
4. [ ] Add Discord webhook support
5. [ ] Implement email alerts
6. [ ] Build landing page for conversions
7. [ ] Add more coins (ETH, SOL, etc.)

---

*Created: 2026-01-31*
*Branch: feature/revenue-model*
