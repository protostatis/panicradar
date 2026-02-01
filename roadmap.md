# Crypto Sentiment Crawler - Development Roadmap

## Project Goal
Build an intelligent web crawler that uses Bayesian inference and causal discovery to maximize the informativeness of crawled crypto sentiment data for price prediction.

## Design Philosophy
- **Crawler-first**: Scrape data directly, minimize API dependencies
- **Bayesian**: Maintain beliefs about source quality, update with evidence
- **Causal**: Discover which sources *cause* price moves, not just correlate
- **Adaptive**: Learn and improve crawl priorities over time
- **Async**: High-performance concurrent crawling with httpx + BeautifulSoup

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BAYESIAN INTELLIGENT CRAWLER                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    DECISION LAYER (Bayesian)                        │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │   │
│  │  │   Source     │   │    Loss      │   │   Action     │            │   │
│  │  │   Beliefs    │──▶│   Function   │──▶│  Selection   │            │   │
│  │  │  P(θ|data)   │   │  (explore/   │   │  (Thompson   │            │   │
│  │  │              │   │   exploit)   │   │   Sampling)  │            │   │
│  │  └──────────────┘   └──────────────┘   └──────────────┘            │   │
│  │         ▲                                      │                    │   │
│  │         │                                      ▼                    │   │
│  │  ┌──────────────┐                     ┌──────────────┐             │   │
│  │  │  Outcome     │                     │   Crawl      │             │   │
│  │  │  Evaluation  │◀────────────────────│   Priority   │             │   │
│  │  │  (accuracy + │                     │   Queue      │             │   │
│  │  │   novelty)   │                     │              │             │   │
│  │  └──────────────┘                     └──────────────┘             │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                       │                                     │
│                                       ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      EXECUTION LAYER                                │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │   │
│  │  │   Fetcher    │   │   Parser     │   │  Sentiment   │            │   │
│  │  │   (httpx)    │──▶│(BeautifulSoup│──▶│  Analysis    │            │   │
│  │  │              │   │   + rules)   │   │ (VADER/BERT) │            │   │
│  │  └──────────────┘   └──────────────┘   └──────────────┘            │   │
│  │                                               │                     │   │
│  │                                               ▼                     │   │
│  │                                        ┌──────────────┐            │   │
│  │                                        │   Storage    │            │   │
│  │                                        └──────────────┘            │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                       │                                     │
│                                       ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    CAUSAL DISCOVERY LAYER (Continuous)              │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │   │
│  │  │   Granger    │   │   Dynamic    │   │   Update     │            │   │
│  │  │  Causality   │──▶│   Source     │──▶│   Beliefs    │            │   │
│  │  │   Tests      │   │   Weights    │   │   (auto)     │            │   │
│  │  └──────────────┘   └──────────────┘   └──────────────┘            │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                       │                                     │
│                                       ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    SIGNAL DETECTION LAYER                           │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │   │
│  │  │  Contrarian  │   │   Alert      │   │   REST       │            │   │
│  │  │  Detector    │──▶│   System     │──▶│   API        │            │   │
│  │  │              │   │(Telegram/Ntfy│   │              │            │   │
│  │  └──────────────┘   └──────────────┘   └──────────────┘            │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Mathematical Framework

### 1. Utility Function

```
U(content) = 0.7 × accuracy_score + 0.3 × novelty_score
```

Where:
- **accuracy_score**: Did sentiment correctly predict price direction?
  ```
  accuracy = 1 if sign(sentiment) == sign(Δprice_{t+lag}) else 0
  ```
- **novelty_score**: Information gain over recent content
  ```
  novelty = 1 - max(cosine_similarity(content, recent_contents))
  ```

### 2. Loss Function (Exploration-Exploitation)

```
L(source, t) = E[regret] + λ(t) × uncertainty_bonus

where:
  regret = U(optimal_source) - U(chosen_source)
  uncertainty_bonus = -σ(source)    # Negative because we WANT uncertainty
  λ(t) = λ₀ × decay(t)              # Exploration decays over time
```

**Intuition**:
- High regret → penalize choosing bad sources
- High uncertainty → bonus for exploring (reduces over time)

### 3. Source Belief Model

```python
class SourceBelief:
    """Bayesian belief about source informativeness."""

    # Beta distribution for P(source is informative)
    alpha: float  # Pseudo-count of informative crawls
    beta: float   # Pseudo-count of non-informative crawls

    # Posterior mean: E[θ] = α / (α + β)
    # Posterior variance: Var[θ] = αβ / [(α+β)²(α+β+1)]

    # Learned metrics
    accuracy: float       # Historical prediction accuracy
    correlation: float    # Sentiment-price correlation
    is_contrarian: bool   # True if accuracy < 45% (invert signal)
```

### 4. Cold Start: Price Autocorrelation Baseline

```python
def compute_baseline_informativeness(prices: Series, max_lag: int = 24) -> float:
    """
    Baseline = how much price is NOT predictable from its own history.

    If price is a random walk → baseline ≈ 1.0 (any signal is valuable)
    If price is highly autocorrelated → baseline ≈ 0.0 (easy to predict)
    """
    # Fit AR model: price_t = Σ φ_i × price_{t-i} + ε
    # R² = variance explained by past prices
    r_squared = fit_ar_model(prices, max_lag).rsquared

    return 1.0 - r_squared  # Residual unpredictability
```

### 5. Thompson Sampling for Source Selection

```python
def select_next_source(beliefs: dict[str, SourceBelief]) -> str:
    """
    Thompson Sampling: Sample from each posterior, pick highest.
    Naturally balances exploration (uncertain sources) vs exploitation (known good).
    """
    samples = {}
    for source, belief in beliefs.items():
        # Sample from Beta posterior
        theta = np.random.beta(belief.alpha, belief.beta)

        # Weight by causal strength (if known)
        causal_weight = 1.0 if belief.granger_pvalue > 0.05 else 2.0

        samples[source] = theta * causal_weight

    return max(samples, key=samples.get)
```

### 6. Dynamic Source Weights

```python
def compute_weight_from_belief(belief: dict) -> tuple[float, bool]:
    """
    Compute inference weight from Bayesian belief.

    Returns (weight, should_invert).
    Sources with accuracy far from 50% get higher weights.
    Sources with <45% accuracy are marked as contrarian (invert signal).
    """
    accuracy = belief.get("accuracy", 0.5)
    sample_size = belief.get("alpha", 1) + belief.get("beta", 1)

    # Distance from uninformative baseline (0.5)
    distance = abs(accuracy - 0.5)
    predictive_power = distance * 2  # 0 to 1

    # Confidence from sample size
    confidence = min(1.0, sample_size / 200)

    # Weight = predictive power × confidence
    weight = 0.01 + (predictive_power * confidence * 0.29)
    is_contrarian = accuracy < 0.45

    return weight, is_contrarian
```

### 7. Causal Discovery & Key Finding

```python
# IMPORTANT DISCOVERY: Price leads sentiment by ~15 hours
# This means sentiment REACTS to price, not the reverse.
# Therefore, we use CONTRARIAN signals instead of momentum.

def detect_contrarian_signal(sentiment, price_change, zscore):
    """
    Signal types based on sentiment-price divergence:
    - BULLISH_DIVERGENCE: Extreme fear + price stable/rising
    - BEARISH_DIVERGENCE: Extreme greed + price stable/falling
    - CAPITULATION: Extreme negative spike (panic selling)
    - EUPHORIA: Extreme positive spike (irrational exuberance)
    """
```

---

## Data Sources

| Source | Type | Status | Notes |
|--------|------|--------|-------|
| Reddit (20+ subreddits) | Social | ✅ Complete | High volume, mixed quality |
| 4chan /biz/ | Social | ✅ Complete | High contrarian signal value |
| Stocktwits | Social | ✅ Complete | Trader sentiment |
| Bitcointalk | Forum | ✅ Complete | OG community |
| Twitter/X | Social | ✅ Complete | Requires API key |
| CoinDesk/CoinTelegraph | News | ✅ Basic | Headlines |
| Fear & Greed Index | Composite | ✅ Complete | Market baseline (collider, not confounder) |
| Google Trends | Search | ❌ Not implemented | Low priority (lagging) |

---

## Phase 1: Foundation ✅ (Complete)

- [x] Project setup with uv
- [x] SQLite database
- [x] Fear & Greed collector
- [x] Price data collector
- [x] Sentiment analysis with crypto lexicon

---

## Phase 2: Bayesian Decision Engine ✅ (Complete)

### 2.1 Source Belief System
```python
# bayesian/beliefs.py
```
- [x] `SourceBelief` dataclass with Beta parameters
- [x] Persistence to database
- [x] Prior initialization from price autocorrelation
- [x] Posterior update logic

### 2.2 Utility Computation
```python
# bayesian/utility.py
```
- [x] Accuracy scorer (sentiment vs price direction)
- [x] Novelty scorer (TF-IDF cosine similarity)
- [x] Combined utility function (0.7/0.3 weighting)

### 2.3 Source Selection
```python
# bayesian/bandit.py
```
- [x] Thompson Sampling implementation
- [x] Exploration decay schedule
- [x] Action logging for analysis
- [x] UCB1 alternative implementation

### 2.4 Database Schema for Beliefs
- [x] `source_weights` table with learned parameters
- [x] State persistence to JSON

---

## Phase 3: Crawler Execution Engine ✅ (Complete)

### 3.1 Fetcher
- [x] Async httpx with rate limiting (token bucket)
- [x] User-agent rotation (6 realistic browser UAs)
- [x] Retry with exponential backoff (2s-30s, 3 retries)

### 3.2 Parser
- [x] BeautifulSoup with CSS selectors
- [x] Source configuration system
- [x] Text extraction and cleaning
- [x] Datetime parsing (10+ formats)

### 3.3 Content Pipeline
- [x] Coin detection (14 cryptocurrencies)
- [x] Sentiment scoring (VADER + FinBERT)
- [x] Novelty computation against recent content
- [x] Storage with outcome tracking

---

## Phase 4: Causal Discovery ✅ (Complete)

### 4.1 Granger Causality Tests
```python
# causal/granger.py
```
- [x] VAR model fitting
- [x] F-test for Granger causality
- [x] Optimal lag selection (1-24 hours)
- [x] Stationarity testing (ADF)

### 4.2 Key Finding: Price Leads Sentiment
- [x] Discovered price leads sentiment by ~15 hours
- [x] Fear & Greed is a collider, not confounder
- [x] Pivoted to contrarian signal strategy

### 4.3 Belief Auto-Updates
- [x] Continuous belief updates (every 30 minutes)
- [x] Dynamic source weight computation
- [x] Contrarian source detection (accuracy < 45%)

---

## Phase 5: Source Implementations ✅ (Complete)

### 5.1 Social Crawlers
- [x] Reddit (20+ crypto subreddits)
- [x] 4chan /biz/
- [x] Stocktwits
- [x] Twitter/X (API-based)

### 5.2 Forum Crawlers
- [x] Bitcointalk

### 5.3 News Crawlers
- [x] CoinDesk (basic)
- [x] CoinTelegraph (basic)

### 5.4 Data Sources
- [x] CoinGecko (price data)
- [x] Fear & Greed Index

---

## Phase 6: Signal Detection & Alerts ✅ (Complete)

### 6.1 Contrarian Signal Detector
- [x] BULLISH_DIVERGENCE signal
- [x] BEARISH_DIVERGENCE signal
- [x] CAPITULATION signal
- [x] EUPHORIA signal
- [x] Z-score based extremeness detection

### 6.2 Alert System
- [x] Telegram integration
- [x] Ntfy.sh push notifications
- [x] Signal cooldown (6-hour minimum)

### 6.3 REST API
- [x] FastAPI endpoints
- [x] Subscription tiers (FREE/PRO/ENTERPRISE)
- [x] Market summary endpoint

---

## Phase 7: Analysis & Inference ✅ (Complete)

### 7.1 Dynamic Source Weights
- [x] Weights learned from prediction accuracy
- [x] Stored in `source_weights` database table
- [x] Used in `inference.py` for weighted aggregation
- [x] Used in `signals/service.py` for signal detection

### 7.2 Contrarian Source Handling
- [x] Sources with <45% accuracy marked as contrarian
- [x] Sentiment inverted for contrarian sources
- [x] Higher weight for sources far from 50% accuracy

### 7.3 Transformer Sentiment
- [x] FinBERT (ProsusAI/finbert) integration
- [x] Apple Silicon MPS GPU support
- [x] Transformer enabled by default

---

## Phase 8: Multi-Dimensional Sentiment ✅ (Complete)

### 8.1 Segment Categorization
- [x] `FILTER`: Bot messages, automod - excluded from sentiment
- [x] `ACTIVITY`: Scam warnings - tracked as market activity indicator
- [x] `TRUE_BEARISH`: Actual losses, panic - included + tracked as fear
- [x] `EUPHORIA`: Moon talk, FOMO - tracked as contrarian sell signal
- [x] `STANDARD`: Regular content - included in sentiment

### 8.2 Multi-Dimensional Signals
- [x] `final_score`: Filtered sentiment (for Bayesian accuracy)
- [x] `fear_index`: Proportion of loss/panic segments (0-1)
- [x] `euphoria_index`: Proportion of moon/FOMO segments (0-1)
- [x] `activity_level`: Proportion of scam/warning segments (0-1)

### 8.3 User-Centric Scoring
- [x] `user_profiles` table tracking 3,000+ users
- [x] User credibility weights
- [x] Hierarchical aggregation (title + segments)

### 8.4 Integration
- [x] Signal detector uses multi-dimensional data
- [x] Belief updater uses filtered scores
- [x] API exposes multi-dimensional fields
- [x] Database schema includes new tables

---

## Project Structure (Current)

```
crypto_sentiment_crawler/
├── pyproject.toml
├── roadmap.md                    # This file
├── pipeline.md                   # Pipeline documentation
├── README.md                     # Project overview
│
├── data/                         # Data storage
│   ├── sentiment.db              # SQLite database
│   ├── orchestrator_state.json   # Persisted beliefs
│   └── backtest_results.log      # Backtest history
│
├── logs/                         # Log files
│
├── docs/                         # Documentation
│   ├── causal_analysis_findings.md
│   ├── causal_inference_analysis.md
│   ├── historical_sentiment_price_report.md
│   └── signal_service.md
│
└── crypto_sentiment_crawler/
    ├── __init__.py
    ├── config.py                 # Settings
    ├── main.py                   # Entry point
    ├── taskmanager.py            # Task management CLI
    ├── orchestrator.py           # Integration layer
    ├── scheduler.py              # Background scheduler
    ├── inference.py              # Price prediction
    │
    ├── bayesian/                 # ✅ Decision layer
    │   ├── beliefs.py            # SourceBelief model
    │   ├── utility.py            # Accuracy + novelty scoring
    │   ├── bandit.py             # Thompson Sampling
    │   └── cold_start.py         # Price autocorrelation
    │
    ├── causal/                   # ✅ Causal discovery
    │   ├── granger.py            # Granger causality tests
    │   └── backdoor_analysis.py  # Causal inference
    │
    ├── analysis/                 # ✅ Analysis layer
    │   ├── belief_updater.py     # Update beliefs from accuracy
    │   ├── belief_auto_updater.py # Continuous updates
    │   ├── source_weights.py     # Dynamic weight computation
    │   ├── backtest_analysis.py  # Backtesting
    │   └── rescore_transformer.py # Transformer rescoring
    │
    ├── signals/                  # ✅ Signal detection
    │   ├── detector.py           # Contrarian signals
    │   ├── service.py            # Signal service
    │   ├── alerts.py             # Telegram/Ntfy alerts
    │   ├── api.py                # REST API
    │   ├── models.py             # Signal models
    │   ├── subscriptions.py      # Subscription tiers
    │   └── backtest.py           # Signal backtesting
    │
    ├── crawler/                  # ✅ Execution layer
    │   ├── fetcher.py            # Async HTTP + rate limiting
    │   ├── parser.py             # BeautifulSoup parsing
    │   ├── pipeline.py           # Full crawl pipeline
    │   └── sources.py            # Source configuration
    │
    ├── collectors/               # ✅ API collectors
    │   ├── fear_greed.py
    │   ├── price.py
    │   ├── reddit.py
    │   ├── twitter.py
    │   └── onchain.py
    │
    ├── processing/               # ✅ Content processing
    │   ├── sentiment.py          # VADER + FinBERT + crypto lexicon
    │   ├── semantic_sentiment.py # Semantic similarity scoring
    │   └── user_sentiment.py     # Multi-dimensional scoring + segment categorization
    │
    └── storage/                  # ✅ Database layer
        ├── models.py
        └── db.py
```

---

## Success Metrics

### Crawl Efficiency ✅
- [x] Sources with high posterior (α >> β) deliver more informative content
- [x] Exploration decreases over time as beliefs converge
- [x] Dynamic weights prioritize accurate sources

### Prediction Quality
- [x] Sentiment-price relationship characterized (price leads sentiment)
- [x] Contrarian signal strategy developed
- [x] Source accuracy varies 30-60% (contrarian vs momentum)

### System Health ✅
- [x] Beliefs converge (variance decreasing over time)
- [x] Continuous belief updates (every 30 minutes)
- [x] Source diversity maintained (32+ sources)

---

## Key Learnings

1. **Price leads sentiment by ~15 hours** - People react to price moves
2. **Fear & Greed is a collider** - Should not be used as confounder
3. **Contrarian signals work** - Extreme sentiment often marks reversals
4. **Source accuracy varies widely** - From 30% to 60%
5. **Dynamic weights improve inference** - Better than static weights
6. **VADER has positive bias** - Scores 69% positive vs 19% for filtered scores
7. **Scam warnings ≠ negative sentiment** - High scam activity indicates bull market
8. **Segment-level analysis improves signal quality** - Separate fear from activity

---

## Future Enhancements

- [ ] Google Trends integration (low priority)
- [ ] Discord webhook alerts
- [ ] Email alerts
- [ ] More sophisticated causal models
- [ ] Real-time websocket API

---

*Last updated: 2026-02-01*
*Status: All core phases complete*
