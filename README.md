# Crypto Sentiment Crawler

An intelligent web crawler that uses Bayesian inference and causal discovery to maximize the informativeness of crawled crypto sentiment data for price prediction.

## Overview

This project implements a **Bayesian-guided crawler** that learns which sources provide the most predictive sentiment signals for cryptocurrency prices. Instead of crawling all sources equally, it:

1. Maintains probabilistic beliefs about each source's informativeness
2. Uses Thompson Sampling to balance exploration vs exploitation
3. Updates beliefs based on observed prediction accuracy and content novelty
4. Runs weekly causal discovery to identify leading indicators

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BAYESIAN DECISION LAYER                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Source    │  │   Thompson  │  │   Utility   │             │
│  │   Beliefs   │──│   Sampling  │──│   Scoring   │             │
│  │  Beta(α,β)  │  │   Bandit    │  │  0.7A+0.3N  │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CRAWLER EXECUTION LAYER                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Fetcher   │  │   Parser    │  │  Sentiment  │             │
│  │   (httpx)   │──│(BeautifulSoup──│   Analysis  │             │
│  │ rate-limit  │  │  +selectors)│  │   (VADER)   │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CAUSAL DISCOVERY (Weekly)                    │
│  ┌─────────────┐  ┌─────────────┐                              │
│  │   Granger   │  │   Update    │                              │
│  │  Causality  │──│   Priors    │                              │
│  └─────────────┘  └─────────────┘                              │
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
# Run background daemon (recommended for continuous collection)
uv run crawler

# Run with custom intervals
uv run crawler background --crawl-interval 60 --price-interval 300

# Run fixed iterations then exit
uv run crawler bayesian -n 20 -d 30

# View current stats
uv run crawler stats

# Run demo
uv run crawler demo
```

> **See [pipeline.md](pipeline.md) for detailed documentation on the background pipeline, scheduled jobs, and deployment options.**

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
    alpha: float  # Pseudo-count of informative crawls
    beta: float   # Pseudo-count of non-informative crawls

    @property
    def mean(self) -> float:
        """Expected probability of being informative."""
        return self.alpha / (self.alpha + self.beta)
```

### 3. Thompson Sampling

Source selection uses Thompson Sampling for explore-exploit balance:

```python
def select_source(beliefs: dict[str, SourceBelief]) -> str:
    # Sample from each source's posterior
    samples = {
        source: np.random.beta(b.alpha, b.beta)
        for source, b in beliefs.items()
    }
    # Select highest sample
    return max(samples, key=samples.get)
```

### 4. Cold Start

New sources are initialized using price autocorrelation:

```
baseline = 1 - R²(price ~ lagged_price)
```

- High autocorrelation → low baseline (price is predictable)
- Low autocorrelation → high baseline (any signal helps)

### 5. Causal Discovery

Weekly Granger causality tests identify which sources *cause* price moves:

```python
# Test: does sentiment Granger-cause price?
result = granger_causality_test(sentiment, price, max_lag=24)

if result.pvalue < 0.05:
    # This source has causal power
    belief.alpha += 2  # Boost prior
```

## Project Structure

```
crypto_sentiment_crawler/
├── pyproject.toml           # Dependencies (uv)
├── README.md                # This file
├── roadmap.md               # Development roadmap
├── .env.example             # Environment template
│
├── sources/                 # Source YAML configs (future)
│   ├── reddit.yaml
│   └── coindesk.yaml
│
└── crypto_sentiment_crawler/
    ├── __init__.py
    ├── config.py            # Settings from env vars
    ├── logging_config.py    # Logging setup
    ├── main.py              # Entry point
    ├── demo.py              # Demo script
    │
    ├── bayesian/            # Decision layer
    │   ├── beliefs.py       # SourceBelief model
    │   ├── bandit.py        # Thompson Sampling
    │   ├── utility.py       # Accuracy + novelty scoring
    │   └── cold_start.py    # Price autocorrelation baseline
    │
    ├── causal/              # Causal discovery
    │   └── granger.py       # Granger causality tests
    │
    ├── crawler/             # Execution layer
    │   ├── fetcher.py       # Async HTTP + rate limiting
    │   ├── parser.py        # BeautifulSoup parsing
    │   ├── pipeline.py      # Full crawl pipeline
    │   └── sources.py       # Source configuration
    │
    ├── collectors/          # API-based collectors (fallback)
    │   ├── fear_greed.py    # Fear & Greed Index
    │   ├── price.py         # CoinGecko prices
    │   ├── reddit.py        # Reddit API (backup)
    │   └── onchain.py       # Whale Alert (future)
    │
    ├── processing/          # Content processing
    │   └── sentiment.py     # VADER + crypto lexicon
    │
    └── storage/             # Database layer
        ├── models.py        # Pydantic models
        └── db.py            # SQLite operations
```

## Implementation Details

### Bayesian Layer

#### `bayesian/beliefs.py`

The `SourceBelief` class models our uncertainty about each source:

```python
@dataclass
class SourceBelief:
    source: str
    alpha: float = 1.0  # Informative crawls
    beta: float = 1.0   # Non-informative crawls

    def sample(self) -> float:
        """Sample from Beta posterior (for Thompson Sampling)."""
        return np.random.beta(self.alpha, self.beta)

    def update(self, was_informative: bool) -> None:
        """Bayesian update after observing outcome."""
        if was_informative:
            self.alpha += 1
        else:
            self.beta += 1
```

The `SourceBeliefStore` manages beliefs for all sources with serialization support.

#### `bayesian/utility.py`

The `UtilityScorer` computes informativeness:

```python
class UtilityScorer:
    def compute_utility(self, content, sentiment, price_before, price_after):
        accuracy = 1.0 if sign(sentiment) == sign(Δprice) else 0.0
        novelty = 1.0 - max_cosine_similarity(content, recent_docs)
        return 0.7 * accuracy + 0.3 * novelty
```

Novelty uses TF-IDF vectorization with cosine similarity against a sliding window of recent content.

#### `bayesian/bandit.py`

The `CrawlBandit` implements Thompson Sampling with:

- Exploration decay (λ decreases over time)
- Causal bonus (2x weight for Granger-causal sources)
- Selection logging for analysis

```python
class CrawlBandit:
    def select_source(self, sources: list[str]) -> SelectionResult:
        samples = {}
        for source in sources:
            belief = self.belief_store.get(source)
            theta = belief.sample()  # Thompson Sampling
            bonus = self.exploration_weight * belief.std
            causal_mult = 1.5 if belief.is_causal else 1.0
            samples[source] = (theta + bonus) * causal_mult

        return max(samples, key=samples.get)
```

#### `bayesian/cold_start.py`

Initializes new source priors from price dynamics:

```python
def compute_baseline_informativeness(prices: pd.Series) -> float:
    # Fit AR model to returns
    returns = prices.pct_change()
    model = AutoReg(returns, lags=24).fit()
    r_squared = model.rsquared

    # Baseline = unpredictability
    return 1.0 - r_squared
```

### Crawler Layer

#### `crawler/fetcher.py`

Async HTTP with production-ready features:

```python
class Fetcher:
    # Rate limiting per domain (token bucket)
    rate_limiters: dict[str, RateLimiter]

    # User-agent rotation pool
    USER_AGENTS = [...]  # Real browser UAs

    async def fetch(self, url: str) -> FetchResult:
        await self.rate_limiter.acquire()
        await asyncio.sleep(random.uniform(0.5, 2.0))  # Politeness
        response = await self.client.get(url, headers=self._rotate_ua())
        return FetchResult(...)
```

#### `crawler/parser.py`

Configurable HTML parsing:

```python
class Parser:
    def parse(self, html: str, selectors: dict) -> ParseResult:
        soup = BeautifulSoup(html, "lxml")
        return ParseResult(
            title=self._extract(soup, selectors.get("title")),
            content=self._extract(soup, selectors.get("content")),
            timestamp=self._extract_datetime(soup, selectors.get("timestamp")),
            ...
        )
```

#### `crawler/pipeline.py`

Full crawl pipeline:

```python
class ContentPipeline:
    async def process_url(self, url: str, source: str) -> CrawledContent:
        # 1. Fetch
        fetch_result = await self.fetcher.fetch(url)

        # 2. Parse
        parse_result = self.parser.parse(fetch_result.content, selectors)

        # 3. Detect coins
        coins = detect_coins(parse_result.content)

        # 4. Sentiment analysis
        sentiment = sentiment_analyzer.analyze(parse_result.content)

        return CrawledContent(...)
```

### Causal Layer

#### `causal/granger.py`

Granger causality testing:

```python
class GrangerAnalyzer:
    def test_granger_causality(self, cause: Series, effect: Series) -> GrangerResult:
        # Make stationary
        cause = self.make_stationary(cause)
        effect = self.make_stationary(effect)

        # Test at multiple lags
        results = grangercausalitytests(data, maxlag=24)

        # Find best lag
        best_lag = min(results, key=lambda k: results[k].pvalue)

        return GrangerResult(
            optimal_lag=best_lag,
            pvalue=results[best_lag].pvalue,
            is_causal=pvalue < 0.05,
        )
```

### Sentiment Analysis

#### `processing/sentiment.py`

VADER with crypto-specific lexicon:

```python
CRYPTO_LEXICON = {
    "moon": 3.0, "mooning": 3.5,
    "rekt": -3.0, "rugpull": -4.0,
    "hodl": 2.0, "fud": -1.5,
    ...
}

class CryptoSentimentAnalyzer:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        self.analyzer.lexicon.update(CRYPTO_LEXICON)
```

## Configuration

### Environment Variables

```bash
# .env
REDDIT_CLIENT_ID=...        # Optional: Reddit API backup
REDDIT_CLIENT_SECRET=...
DATABASE_PATH=data/sentiment.db
TRACKED_COINS=BTC,ETH,SOL
LOG_LEVEL=INFO
```

### Source Configuration (YAML)

```yaml
# sources/coindesk.yaml
name: coindesk
base_url: https://www.coindesk.com
type: news

selectors:
  title: "h1"
  content: "article"
  timestamp: "time[datetime]"

rate_limit: 1.0
prior_adjustment: 0.3  # News sources get prior boost
```

### Orchestrator (Integration Layer)

#### `orchestrator.py`

The `CrawlerOrchestrator` integrates all components:

```python
class CrawlerOrchestrator:
    """
    Main loop:
    1. Thompson Sampling selects source
    2. Crawler fetches and parses content
    3. Sentiment analysis scores content
    4. Queue for utility evaluation after lag period
    5. Update beliefs based on outcomes
    """

    async def select_and_crawl(self) -> CrawledContent:
        # Select using Bayesian bandit
        selection = self.bandit.select_source(available_sources)

        # Crawl selected source
        content = await self._crawl_source(selection.source)

        # Queue for evaluation
        self.pending_outcomes.append(CrawlOutcome(
            content=content,
            price_at_crawl=current_price,
            timestamp=now,
        ))

        # Compute immediate novelty
        novelty = self.utility_scorer.compute_novelty_only(content.text)

        return content

    async def evaluate_pending_outcomes(self):
        # After lag period, evaluate accuracy
        for outcome in self.pending_outcomes:
            utility = self.utility_scorer.compute_utility(
                content=outcome.content.text,
                sentiment_score=outcome.content.sentiment_score,
                price_before=outcome.price_at_crawl,
                price_after=current_price,
            )

            # Bayesian update
            self.bandit.update_from_outcome(outcome.source, utility)
```

**State Persistence**: Beliefs and pending evaluations are saved to JSON, allowing the crawler to resume and retain learned preferences.

**CLI Usage**:
```bash
# Run background daemon (default, recommended)
uv run crawler

# Run background with custom intervals
uv run crawler background --crawl-interval 60 --eval-interval 600

# Run fixed iterations then exit
uv run crawler bayesian -n 10 -d 30

# View current stats
uv run crawler stats

# Run legacy API collectors
uv run crawler collectors
```

### Background Scheduler (`scheduler.py`)

The `CrawlerScheduler` runs continuous jobs using APScheduler:

```python
class CrawlerScheduler:
    """
    Scheduled jobs:
    - Crawl: every 2 minutes (Bayesian selection)
    - Price: every 5 minutes
    - Evaluation: every 15 minutes (update beliefs)
    - Fear & Greed: every 4 hours
    - Stats: every 10 minutes (logging)
    """

    async def run(self):
        # Initial collection
        await self._job_price()
        await self._job_fear_greed()
        await self._job_crawl()

        # Start scheduled jobs
        self.scheduler.start()

        # Run until interrupted
        while self._running:
            await asyncio.sleep(1)
```

**Default Intervals**:
| Job | Interval | Purpose |
|-----|----------|---------|
| Crawl | 2 min | Bayesian source selection + crawl |
| Price | 5 min | Collect BTC/ETH/SOL prices |
| Evaluate | 15 min | Compare predictions to actual prices, update beliefs |
| Fear & Greed | 4 hours | Market sentiment baseline |
| Stats | 10 min | Log statistics |

## Data Flow

```
1. INITIALIZATION
   └── Compute baseline from price autocorrelation
   └── Initialize source beliefs with type-specific priors

2. CRAWL LOOP
   ├── Thompson Sampling selects source
   ├── Fetcher retrieves content (rate-limited)
   ├── Parser extracts text and metadata
   ├── Sentiment analyzer scores content
   └── Store raw + processed data

3. OUTCOME EVALUATION (after lag period)
   ├── Compare sentiment to actual price movement
   ├── Compute accuracy score
   ├── Compute novelty score
   ├── Calculate utility = 0.7*accuracy + 0.3*novelty
   └── Update source belief (Bayesian update)

4. CAUSAL DISCOVERY (weekly)
   ├── Run Granger tests for all sources
   ├── Identify leading indicators
   └── Boost priors for causal sources
```

## Current Status

### Working Features

| Component | Status | Notes |
|-----------|--------|-------|
| Bayesian beliefs | ✅ | Beta distribution, Thompson Sampling |
| Utility scoring | ✅ | 0.7 accuracy + 0.3 novelty |
| Cold start | ✅ | Price autocorrelation baseline |
| Fetcher | ✅ | Rate limiting, UA rotation |
| Reddit crawler | ✅ | old.reddit.com (no API needed) |
| Sentiment analysis | ✅ | VADER + crypto lexicon |
| Orchestrator | ✅ | Full integration loop |
| State persistence | ✅ | JSON serialization |
| Price collector | ✅ | CoinGecko API |
| Fear & Greed | ✅ | alternative.me API |

### Pending

| Component | Status | Notes |
|-----------|--------|-------|
| News crawlers | 🔄 | Need RSS feeds or JS rendering |
| Granger causality | 🔄 | Implemented, needs data |
| Scheduled jobs | 📋 | APScheduler integration |
| Database beliefs | 📋 | Currently JSON-based |

### Example Output

```
Selected: reddit_cryptocurrency (sampled=0.968, mean=0.600)
Crawled: Bitcoin reaches new high... (novelty=1.000)

Selected: reddit_bitcoin (sampled=0.954, mean=0.600)
Crawled: Buying the dip... (novelty=1.000)

Current rankings:
  reddit_cryptocurrency: mean=0.650 (α=2.5, β=1.0, n=5)
  reddit_bitcoin: mean=0.620 (α=2.2, β=1.0, n=3)
```

## License

MIT
