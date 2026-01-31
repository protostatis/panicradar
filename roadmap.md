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
│  │  │              │   │   + rules)   │   │              │            │   │
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
│  │                    CAUSAL DISCOVERY LAYER (Weekly)                  │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │                                                                     │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │   │
│  │  │   Granger    │   │   Causal     │   │   Update     │            │   │
│  │  │  Causality   │──▶│   Graph      │──▶│   Source     │            │   │
│  │  │   Tests      │   │   (DAG)      │   │   Priors     │            │   │
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

    # Causal strength (updated weekly)
    granger_pvalue: float  # p-value from Granger test
    lead_time_hours: float # How far ahead does it signal?
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

def initialize_source_prior(baseline: float) -> SourceBelief:
    """Initialize new source with weak prior scaled by baseline."""
    return SourceBelief(
        alpha=1.0 + baseline,  # Slightly optimistic if baseline high
        beta=1.0,
    )
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

### 6. Belief Update After Crawl

```python
def update_belief(
    belief: SourceBelief,
    content: CrawledContent,
    price_outcome: float,
    recent_contents: list[str]
) -> SourceBelief:
    """Update posterior after observing crawl outcome."""

    # Compute utility
    accuracy = 1.0 if sign(content.sentiment) == sign(price_outcome) else 0.0
    novelty = 1.0 - max_similarity(content.text, recent_contents)
    utility = 0.7 * accuracy + 0.3 * novelty

    # Threshold for "informative"
    if utility > 0.5:
        belief.alpha += 1
    else:
        belief.beta += 1

    return belief
```

### 7. Causal Discovery (Weekly)

```python
def weekly_causal_update(
    source_sentiments: dict[str, Series],
    prices: Series,
    beliefs: dict[str, SourceBelief]
) -> dict[str, SourceBelief]:
    """
    Run Granger causality tests to identify leading indicators.
    Updates source priors based on causal strength.
    """
    for source, sentiment in source_sentiments.items():
        # Test: does sentiment Granger-cause price?
        result = granger_causality_test(
            effect=prices,
            cause=sentiment,
            max_lag=24  # hours
        )

        beliefs[source].granger_pvalue = result.pvalue
        beliefs[source].lead_time_hours = result.optimal_lag

        # Boost prior for causal sources
        if result.pvalue < 0.05:  # Significant
            beliefs[source].alpha += 2  # Stronger prior

    return beliefs
```

---

## Data Sources

| Source | Type | Initial Prior | Notes |
|--------|------|---------------|-------|
| Crypto news (CoinDesk, etc.) | News | Baseline + 0.5 | Headlines often lead |
| Reddit (old.reddit.com) | Social | Baseline | High volume, mixed quality |
| Bitcointalk | Forum | Baseline + 0.3 | OG community, slower |
| Google Trends | Search | Baseline - 0.2 | Lagging indicator usually |
| Fear & Greed Index | Composite | Baseline | Useful baseline signal |

---

## Phase 1: Foundation ✅ (Complete)

- [x] Project setup with uv
- [x] SQLite database
- [x] Fear & Greed collector
- [x] Price data collector
- [x] Sentiment analysis with crypto lexicon

---

## Phase 2: Bayesian Decision Engine

### 2.1 Source Belief System
```python
# bayesian/beliefs.py
```
- [ ] `SourceBelief` dataclass with Beta parameters
- [ ] Persistence to database
- [ ] Prior initialization from price autocorrelation
- [ ] Posterior update logic

### 2.2 Utility Computation
```python
# bayesian/utility.py
```
- [ ] Accuracy scorer (sentiment vs price direction)
- [ ] Novelty scorer (TF-IDF or embedding similarity)
- [ ] Combined utility function (0.7/0.3 weighting)

### 2.3 Source Selection
```python
# bayesian/bandit.py
```
- [ ] Thompson Sampling implementation
- [ ] Exploration decay schedule
- [ ] Action logging for analysis

### 2.4 Database Schema for Beliefs

```sql
CREATE TABLE source_beliefs (
    id INTEGER PRIMARY KEY,
    source VARCHAR(50) UNIQUE NOT NULL,
    alpha FLOAT DEFAULT 1.0,
    beta FLOAT DEFAULT 1.0,
    granger_pvalue FLOAT,
    lead_time_hours FLOAT,
    last_updated DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE crawl_outcomes (
    id INTEGER PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    content_id INTEGER REFERENCES crawled_content(id),
    accuracy_score FLOAT,
    novelty_score FLOAT,
    utility FLOAT,
    price_at_crawl FLOAT,
    price_after_lag FLOAT,
    lag_hours INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Phase 3: Crawler Execution Engine

### 3.1 Fetcher
- [ ] Async httpx with rate limiting
- [ ] User-agent rotation
- [ ] Retry with exponential backoff

### 3.2 Parser
- [ ] BeautifulSoup with CSS selectors
- [ ] YAML-based source configs
- [ ] Text extraction and cleaning

### 3.3 Content Pipeline
- [ ] Coin detection
- [ ] Sentiment scoring
- [ ] Novelty computation against recent content
- [ ] Storage with outcome tracking

---

## Phase 4: Causal Discovery (Weekly Job)

### 4.1 Granger Causality Tests
```python
# causal/granger.py
```
- [ ] VAR model fitting
- [ ] F-test for Granger causality
- [ ] Optimal lag selection

### 4.2 Causal Graph Construction
```python
# causal/graph.py
```
- [ ] Build DAG from pairwise tests
- [ ] Identify root causes (upstream sources)
- [ ] Visualize information flow

### 4.3 Prior Updates
- [ ] Boost priors for causal sources
- [ ] Decay priors for non-causal sources
- [ ] Log causal structure changes

---

## Phase 5: Source Implementations

### 5.1 News Crawlers
- [ ] CoinDesk
- [ ] CoinTelegraph
- [ ] Decrypt
- [ ] The Block

### 5.2 Social Crawlers
- [ ] Reddit (old.reddit.com)
- [ ] Bitcointalk

### 5.3 Data Sources
- [ ] Google Trends
- [ ] CoinMarketCap (backup price data)

---

## Project Structure

```
crypto_sentiment_crawler/
├── pyproject.toml
├── roadmap.md
├── sources/                      # Source YAML configs
│   ├── coindesk.yaml
│   ├── reddit.yaml
│   └── ...
└── crypto_sentiment_crawler/
    ├── __init__.py
    ├── config.py
    ├── main.py
    │
    ├── bayesian/                 # NEW: Decision layer
    │   ├── __init__.py
    │   ├── beliefs.py            # SourceBelief model
    │   ├── utility.py            # Accuracy + novelty scoring
    │   ├── bandit.py             # Thompson Sampling
    │   └── cold_start.py         # Price autocorrelation baseline
    │
    ├── causal/                   # NEW: Causal discovery
    │   ├── __init__.py
    │   ├── granger.py            # Granger causality tests
    │   └── graph.py              # Causal DAG construction
    │
    ├── crawler/                  # Execution layer
    │   ├── __init__.py
    │   ├── fetcher.py
    │   ├── parser.py
    │   ├── pipeline.py
    │   └── sources.py
    │
    ├── collectors/               # API collectors (backup)
    │   ├── fear_greed.py         # ✅
    │   ├── price.py              # ✅
    │   └── ...
    │
    ├── processing/
    │   └── sentiment.py          # ✅
    │
    └── storage/
        ├── models.py             # ✅
        └── db.py                 # ✅ (extend for beliefs)
```

---

## Dependencies

```toml
dependencies = [
    # Existing
    "httpx>=0.24.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "vaderSentiment>=3.3.2",
    "aiosqlite==0.17.0",
    "apscheduler>=3.10.0",
    "pandas>=2.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "pyyaml>=6.0.0",
    "tenacity>=8.2.0",

    # NEW: Bayesian/Causal
    "numpy>=1.24.0",
    "scipy>=1.10.0",              # Beta distribution, stats
    "statsmodels>=0.14.0",        # Granger causality, VAR
    "scikit-learn>=1.3.0",        # TF-IDF for novelty
]
```

---

## Implementation Order

```
Week 1: Bayesian Core
├── Day 1-2: SourceBelief model + database schema
├── Day 3-4: Cold start (price autocorrelation baseline)
└── Day 5: Thompson Sampling implementation

Week 2: Utility & Feedback Loop
├── Day 1-2: Accuracy scoring (sentiment vs price)
├── Day 3-4: Novelty scoring (TF-IDF similarity)
└── Day 5: Belief update after crawl

Week 3: Crawler Execution
├── Day 1-2: Fetcher with rate limiting
├── Day 3-4: Parser with BeautifulSoup
└── Day 5: First source (Reddit)

Week 4: Causal Discovery
├── Day 1-2: Granger causality implementation
├── Day 3: Weekly job scheduler
└── Day 4-5: Integration + testing

Week 5+: Source Expansion
├── Add news sites
├── Add forums
└── Tune and iterate
```

---

## Success Metrics

### Crawl Efficiency
- Sources with high posterior (α >> β) should deliver more informative content
- Exploration should decrease over time as beliefs converge
- Causal sources should receive 2-3x more crawl budget

### Prediction Quality
- Aggregate sentiment should Granger-cause price with p < 0.05
- Accuracy score should exceed 55% (better than random)
- High-utility content should cluster around price inflection points

### System Health
- Beliefs should converge (variance decreasing over time)
- Causal graph should stabilize after 2-4 weeks
- No single source should dominate (diversity maintained)

---

## Notes

- **Cold start period**: First 1-2 weeks will be exploratory; beliefs need data
- **Lag selection**: Start with 4-hour lag for accuracy evaluation; tune based on data
- **Causal stability**: Re-run causal discovery weekly; crypto regimes change
- **Novelty decay**: Recent content window = last 24 hours for similarity comparison
