# Causal Inference Analysis: Crypto Sentiment → Price

> **Document Location**: `docs/causal_inference_analysis.md`
> **Figures**: `docs/figures/`

## 1. Problem Statement

**Research Question**: Does social media sentiment (Reddit) *cause* cryptocurrency price movements?

**Why Causation Matters**:
- Correlation alone may be spurious (both driven by common causes)
- For trading: need to know if acting on sentiment signal is profitable
- For understanding: need to know the true mechanism

**Challenge**: Many confounders affect both sentiment and price simultaneously, making causal identification difficult.

---

## 2. Causal DAG Structure

### 2.1 Naive Model (Confounded)

```
                    U (Unobserved)
                   ╱             ╲
                  ↓               ↓
            Sentiment ───?───→ Price
```

Where U represents all common causes (news, macro, whales, etc.)

### 2.2 Expanded DAG with All Confounders

```
         News ─────────────────────────────┐
           │                               │
           ↓                               ↓
    ┌─→ Sentiment ─────────────────────→ Price ←─┐
    │      ↑                               ↑     │
    │      │                               │     │
 Macro ────┘                               └──── Macro
    │                                            │
    │      ↑                               ↑     │
    └── Regime                           Regime ─┘
           ↑                               ↑
           │                               │
      Whale Intent ────────────────────────┘
      (UNOBSERVED)
```

**Figures**:
- Identification strategies overview: `figures/causal_dag_strategies.png`
- Detailed DAG with all variables: `figures/causal_dag_detailed.png`

---

## 3. Confounder Inventory

### 3.1 Categories

| Category | Examples | Observable? | Timing |
|----------|----------|-------------|--------|
| **Market-Wide** | BTC dominance, total market cap, risk-on/off | ✅ Yes | Slow (days) |
| **Macro Economic** | Fed rates, CPI, DXY, VIX | ✅ Yes | Scheduled |
| **Crypto News** | Hacks, regulations, ETF approvals | ✅ Yes | Event-driven |
| **Whale Activity** | Large transactions, exchange flows | ⚠️ Partial | Fast (hours) |
| **Whale Intent** | Why whales act, insider info | ❌ No | Unobservable |
| **Social Contagion** | Virality, echo chambers | ⚠️ Partial | Fast (hours) |

### 3.2 Detailed Confounder Mechanisms

#### NEWS EVENTS
- **→ Sentiment**: People read news → form opinions → post on Reddit (10-60 min lag)
- **→ Price**: Algo traders react instantly (seconds), institutions act on fundamentals
- **Timing Problem**: News affects price before it shows up in sentiment

#### MACRO FACTORS (Fed, CPI, Geopolitical)
- **→ Sentiment**: Rate hikes trigger "risk-off" discussions, inflation fears drive crypto-as-hedge narrative
- **→ Price**: Direct institutional allocation changes, dollar strength affects BTC/USD
- **Advantage**: Scheduled releases allow clean conditioning

#### WHALE ACTIVITY
- **→ Sentiment**: Whales may pay for coverage, whale moves get posted (Whale Alert), insider circles leak
- **→ Price**: Direct market impact from large orders, OTC deals affect supply/demand
- **Critical Issue**: We observe *actions* but not *intent*

#### MARKET REGIME
- **→ Sentiment**: Bull markets → optimistic posts dominate; bear markets → pessimism/capitulation
- **→ Price**: Trend persistence (momentum), liquidity conditions, correlation structures
- **Advantage**: Slow-moving, easy to condition on

**Figures**:
- Confounder categories and pathways: `figures/confounders_review.png`
- Detailed causal mechanisms: `figures/confounder_mechanisms.png`

---

## 4. Observable Proxy Variables

### 4.1 News Events Proxy

| Variable | Description | Source |
|----------|-------------|--------|
| `news_count_1h` | Count of crypto news in past hour | CryptoPanic API |
| `news_sentiment_1h` | Avg sentiment of news headlines | CryptoPanic sentiment field |
| `news_has_btc` | Binary: BTC mentioned in news | Keyword filter |
| `news_category` | Category: regulation/hack/adoption/etc | CryptoPanic categories |

**Blocks**: News → Sentiment, News → Price
**Residual Risk**: Breaking news not yet in API (~1-5 min delay)

### 4.2 Macro Factors Proxy

| Variable | Description | Source |
|----------|-------------|--------|
| `fed_event_today` | Binary: Fed meeting/speech today | Fed calendar |
| `cpi_release_today` | Binary: CPI release today | Economic calendar |
| `dxy_change_24h` | Dollar index % change | FRED / Yahoo Finance |
| `vix_level` | VIX fear index level | Yahoo Finance |
| `sp500_change_1h` | S&P500 hourly return | Yahoo Finance |

**Blocks**: Macro → Sentiment, Macro → Price
**Residual Risk**: Unscheduled geopolitical events

### 4.3 Market Regime Proxy

| Variable | Description | Source |
|----------|-------------|--------|
| `btc_trend_7d` | BTC 7-day return (trend direction) | Price data |
| `volatility_24h` | Realized volatility (24h) | Price data |
| `btc_dominance` | BTC market cap share | CoinGecko |
| `fear_greed_index` | Fear & Greed Index (0-100) | Alternative.me |
| `funding_rate` | Perpetual funding rate | Binance API |

**Blocks**: Regime → Sentiment, Regime → Price
**Residual Risk**: Regime shifts (structural breaks)

### 4.4 Whale Activity Proxy (Partial)

| Variable | Description | Source |
|----------|-------------|--------|
| `exchange_inflow_1h` | BTC flowing into exchanges | Glassnode / CryptoQuant |
| `large_tx_count` | Transactions > 100 BTC | Blockchain.com API |
| `whale_alert_count` | Whale Alert notifications | Whale Alert API |
| `miner_outflow` | Miner wallet outflows | Glassnode |

**Blocks**: Observable whale *actions* only
**Residual Risk**: Whale *intent* (why they move) - **FUNDAMENTALLY UNBLOCKABLE**

### 4.5 Social Contagion Proxy

| Variable | Description | Source |
|----------|-------------|--------|
| `reddit_post_volume` | Posts per hour (activity level) | Reddit API |
| `avg_upvote_ratio` | Engagement quality | Reddit API |
| `unique_authors` | Distinct posters (breadth) | Reddit API |
| `crosspost_count` | Cross-subreddit spread | Reddit API |

**Blocks**: Viral dynamics separate from content
**Residual Risk**: Content-engagement entanglement

**Figures**:
- Proxy specifications: `figures/proxy_specifications.png`
- Blocked vs open paths: `figures/dag_blocking_v1.png`

---

## 5. Identification Strategy Assessment

### 5.1 Backdoor Adjustment

**Approach**: Condition on all observed confounders to block backdoor paths.

**Adjustment Set**: {News Proxy, Macro Proxy, Regime Proxy, Whale Flow Proxy, Social Contagion Proxy}

**Estimand**:
```
E[Price | do(Sentiment)] = Σ_c E[Price | Sentiment, Confounders=c] × P(Confounders=c)
```

**Limitations**:
- ❌ Cannot condition on unobserved whale intent
- ⚠️ News timing lag creates residual confounding
- ⚠️ Measurement error in sentiment

### 5.2 Instrumental Variable (IV)

**Approach**: Find variable Z that affects Sentiment but not Price directly.

**Candidate Instruments**:

| Instrument | Relevance | Exclusion Restriction |
|------------|-----------|----------------------|
| Reddit server outages | Affects post volume | ✅ Likely valid |
| Subreddit mod actions | Affects what gets posted | ⚠️ Maybe valid |
| Platform algorithm changes | Affects visibility | ✅ Likely valid |
| Karma requirements | Affects who can post | ✅ Likely valid |
| Time-of-day (US sleep hours) | Affects Reddit activity | ❌ Also affects trading |

**Best Candidates**: Reddit outages, platform algorithm changes

**Challenge**: Weak instruments (may not explain much sentiment variation)

### 5.3 Frontdoor Adjustment

**Approach**: Find mediator M where Sentiment → M → Price, and M is not confounded.

**Candidate Mediators**:

| Mediator | Sentiment→M | M→Price | U→M blocked? |
|----------|-------------|---------|--------------|
| Retail order flow | ✅ | ✅ | ⚠️ Hard to verify |
| Small wallet txns | ✅ | ✅ | ⚠️ Hard to verify |
| Google Trends | ✅ | ✅ | ❌ News affects too |
| App downloads | ✅ | ⚠️ Weak | ⚠️ Maybe |

**Challenge**: Hard to find mediator not affected by news/whale activity

### 5.4 Difference-in-Differences

**Approach**: Compare sentiment effect in "clean" vs "contaminated" periods.

**Design**:
- Treatment: High sentiment periods
- Control: Low sentiment periods
- Exclude: Periods with major news/whale activity

**Advantage**: Controls for time-invariant confounders
**Challenge**: Requires identifying "clean" periods

---

## 6. The Whale Intent Problem

### 6.1 Why It's Critical

Whale intent is the **fundamental unblockable confounder**:

```
Whale Intent (unobserved)
    │
    ├──→ Manipulates sentiment
    │       • Paid promotional posts
    │       • Coordinated narrative campaigns
    │       • Insider information leaks
    │
    └──→ Moves price
            • Large market orders
            • OTC deals affecting supply
            • Liquidation cascades
```

We can observe whale *actions* (on-chain flows) but not their *intent* (why they're acting).

**Figure**: Residual confounding analysis: `figures/residual_confounding.png`

### 6.2 Potential Solutions

#### Option A: Bound the Bias
- Assume whale manipulation is rare (e.g., <5% of periods)
- Estimate bounds on causal effect under different assumptions
- Use partial identification methods

#### Option B: Instrumental Variable
- Find exogenous shocks to sentiment that whales cannot anticipate
- Reddit platform issues are promising candidates
- Requires strong instruments

#### Option C: Anomaly Detection + Exclusion
- Detect suspicious on-chain patterns (coordinated whale activity)
- Exclude these periods from analysis
- Estimate effect in "clean" periods only

#### Option D: Sensitivity Analysis
- Estimate effect assuming no whale confounding
- Calculate how large whale confounding would need to be to nullify effect
- If implausibly large, effect is robust

#### Option E: Accept Prediction Over Causation
- If goal is trading profit, correlation may suffice
- Focus on out-of-sample prediction rather than causal identification
- Acknowledge limitations in interpretation

---

## 7. Recommended Path Forward

### Phase 1: Data Collection (Immediate)
1. Implement news proxy collection (CryptoPanic API)
2. Implement macro proxy collection (FRED, economic calendars)
3. Implement regime proxy collection (already have some via Fear & Greed)
4. Implement on-chain flow proxy (Whale Alert API or Glassnode)

### Phase 2: Backdoor Adjustment (Short-term)
1. Estimate sentiment → price effect conditioning on all observable proxies
2. Compare to naive (unadjusted) estimate
3. Assess how much confounding is removed

### Phase 3: Sensitivity Analysis (Medium-term)
1. Implement Rosenbaum-style sensitivity analysis
2. Determine robustness of effect to unobserved confounding
3. Report bounds under different assumptions

### Phase 4: IV Exploration (If needed)
1. Collect data on Reddit platform events
2. Test instrument strength (first-stage F-statistic)
3. Estimate IV effect if instruments are valid

---

## 8. Key Takeaways

1. **Causal identification is hard** in this domain due to multiple fast-moving confounders

2. **Most confounders are blockable** with observable proxies (news, macro, regime)

3. **Whale intent is unblockable** - this is the fundamental limitation

4. **Timing asymmetry matters** - news affects price faster than sentiment

5. **Prediction ≠ Causation** - may need to accept predictive validity over causal identification

6. **Sensitivity analysis is essential** - report bounds, not point estimates

---

## Appendix: Data Source Summary

| Data Type | Source | Cost | Priority |
|-----------|--------|------|----------|
| Crypto News | CryptoPanic API | Free tier | High |
| Macro Calendar | FRED / Investing.com | Free | High |
| Fear & Greed | Alternative.me | Free | High (already have) |
| BTC Dominance | CoinGecko | Free | High |
| Exchange Volume | CoinGecko | Free | High |
| Funding Rates | Binance API | Free | Medium |
| On-chain Flows | Glassnode | Paid ($29/mo) | Medium |
| Whale Alerts | Whale Alert API | Paid | Medium |
| Reddit Platform Status | Reddit Status Page | Free | Low (for IV) |

---

*Document created: 2026-01-31*
*Last updated: 2026-01-31*
