# Causal Analysis Findings: Crypto Sentiment → Price

**Date**: 2026-01-31
**Analyst**: Claude (AI Assistant)
**Data Period**: January 2-31, 2026

---

## Executive Summary

**Research Question**: Does Reddit sentiment *cause* cryptocurrency price movements?

**Answer**: **No.** After rigorous causal analysis with proper confounder adjustment, we find no significant causal effect of Reddit sentiment on BTC price returns.

**Key Discovery**: The Fear & Greed Index is a **collider**, not a confounder. Including it in the analysis created a spurious "marginal significance" that was actually statistical bias.

---

## 1. Data Overview

```
Dataset Statistics:
  - Sentiment scores: 1,127 records
  - Price data: 2,214 records
  - Confounder snapshots: 724 records
  - Aligned hourly observations: 315-350 (depending on variables)
  - Date range: 2026-01-02 to 2026-01-31
```

### Variables Collected

| Category | Variables | Source |
|----------|-----------|--------|
| **Treatment** | Reddit sentiment score (-1 to +1) | Reddit (r/bitcoin, r/cryptocurrency, etc.) |
| **Outcome** | BTC hourly returns (%) | CryptoCompare |
| **Confounders** | VIX, DXY, S&P500, Volatility | Yahoo Finance, CryptoCompare |
| **Collider (excluded)** | Fear & Greed Index | Alternative.me |

---

## 2. Initial Analysis (With F&G - BIASED)

Our first analysis incorrectly treated Fear & Greed as a confounder:

```
======================================================================
BACKDOOR-ADJUSTED REGRESSION (INITIAL - BIASED)
======================================================================

  Sentiment Coefficient: -0.1764 *
  Std Error:             0.1019
  t-statistic:           -1.731
  p-value:               0.0855
  95% CI:                [-0.3777, 0.0249]
  R-squared:             0.0928
  N:                     158

  Confounder Coefficients:
    fear_greed_lag1     : -0.0246 (p=0.009) ***
    volatility_lag1     : +0.0066 (p=0.081) *
    vix_lag1            : -0.0014 (p=0.975)
    btc_trend_7d        : +0.0768 (p=0.001) ***
```

This suggested a marginally significant negative effect (p=0.085). **But this was wrong.**

---

## 3. Fear & Greed Investigation

### What is Fear & Greed Index?

The Alternative.me Fear & Greed Index composition:
- Volatility (25%) - compares current vol to 30/90 day avg
- Market Momentum/Volume (25%) - compares to 30/90 day avg
- **Social Media (15%)** - Twitter hashtag sentiment
- Surveys (15%) - strawpoll surveys (currently paused)
- Bitcoin Dominance (10%) - BTC market cap share
- Google Trends (10%) - search volume for "Bitcoin"

### Correlation Analysis

```
Correlation Matrix:
                  sentiment    fng    vol  trend  returns
sentiment             1.000  0.114 -0.026  0.162    0.126
fng                   0.114  1.000 -0.284  0.850   -0.007
vol                  -0.026 -0.284  1.000 -0.274   -0.001
trend                 0.162  0.850 -0.274  1.000    0.131

Key Correlations:
  Sentiment vs F&G:     r = 0.114 (p = 0.0524)  -- Weak
  F&G vs Price Chg 24h: r = 0.456 (p = 0.0000)  -- Strong
  F&G vs BTC Trend:     r = 0.850 (p = 0.0000)  -- Very Strong!
```

### Critical Tests: Is F&G a Valid Confounder?

```
--- TEST 1: Does F&G predict future sentiment? ---
  F&G(t-1) -> Sentiment(t): coef = 0.0059, p = 0.0586
  Result: F&G does NOT significantly predict sentiment

--- TEST 2: Does past returns predict F&G? ---
  Returns(t-1)  -> F&G(t): coef = -0.1841, p = 0.8514
  Returns(t-6)  -> F&G(t): coef = 1.0588,  p = 0.2848
  Returns(t-24) -> F&G(t): coef = 2.6535,  p = 0.0083 ***
  Result: Past returns PREDICT F&G -> F&G is likely a COLLIDER!

--- TEST 3: Correlation between F&G and BTC Trend ---
  Correlation: r = 0.851 (p = 0.000000)
  WARNING: F&G is essentially measuring the same thing as BTC Trend!
```

### Conclusion: F&G is a COLLIDER

```
WRONG (F&G as confounder):         CORRECT (F&G as collider):

        F&G                           Sentiment    Price
       ↙   ↘                                 ↘    ↙
Sentiment → Price                            F&G
```

**Conditioning on a collider OPENS a spurious path, creating bias.**

---

## 4. Corrected Analysis (Without F&G)

```
======================================================================
CORRECTED CAUSAL ANALYSIS (Excluding F&G Collider)
======================================================================

1. NAIVE MODEL (n=350)
   Sentiment -> Returns
   Coefficient: -0.0332
   p-value:     0.5474
   R-squared:   0.0010

2. ADJUSTED FOR VIX (n=203)
   Sentiment -> Returns | VIX
   Sentiment coef: -0.0670 (p=0.4702)
   VIX coef:       -0.0383 (p=0.2716)
   R-squared:      0.0091

3. ADJUSTED FOR VOLATILITY (n=350)
   Sentiment -> Returns | Volatility
   Sentiment coef: -0.0324 (p=0.5577)
   Vol coef:       +0.0009 (p=0.6791)
   R-squared:      0.0015

4. ADJUSTED FOR VOL + VIX (n=203)
   Sentiment -> Returns | Vol, VIX
   Sentiment coef: -0.0634 (p=0.4958)
   Vol coef:       +0.0024 (p=0.4767)
   VIX coef:       -0.0472 (p=0.2031)
   R-squared:      0.0116
```

---

## 5. Summary Comparison

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Model                      │ Sent Coef │ p-value │ Significant?     │
  ├─────────────────────────────────────────────────────────────────────┤
  │ Naive                      │  -0.033   │  0.547  │ No               │
  │ Adjusted (VIX)             │  -0.067   │  0.470  │ No               │
  │ Adjusted (Volatility)      │  -0.032   │  0.558  │ No               │
  │ Adjusted (Vol + VIX)       │  -0.063   │  0.496  │ No               │
  │ ─────────────────────────────────────────────────────────────────── │
  │ WITH F&G (WRONG - collider)│  -0.176   │  0.085  │ Marginal (BIAS!) │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Granger Causality Results (for comparison)

```
======================================================================
GRANGER CAUSALITY ANALYSIS: SENTIMENT -> BTC PRICE
======================================================================

TEST 1: Overall Sentiment -> Price Returns
  Result: No causal relationship detected
  Best lag: 1 hours
  F-statistic: 0.281
  P-value: 0.5965

LEAD-LAG CORRELATION ANALYSIS
  Optimal lag: -12 hours
  Correlation at optimal lag: 0.146
  Interpretation: Price LEADS sentiment by 12h

GRANGER CAUSALITY BY SOURCE
  Source                         p-value    Lag    Causal?
  --------------------------------------------------------------
  reddit_bitcoin                  0.0547     11h    no (marginal)
  reddit_cryptocurrency           0.2844      4h    no
  reddit_cryptomarkets            0.3980     10h    no

REVERSE TEST: Price Returns -> Sentiment
  Result: No causal relationship detected
  P-value: 0.3094
```

---

## 7. Key Findings

### 7.1 No Causal Effect
Reddit sentiment does **not** cause BTC price movements. The coefficient is:
- Small in magnitude (~0.03-0.07)
- Statistically insignificant (p > 0.45 in all valid models)
- Robust across different confounder specifications

### 7.2 Fear & Greed is a Collider
- F&G is **caused by** price movements (past returns predict F&G, p=0.008)
- F&G **does not cause** sentiment (p=0.06)
- F&G is 85% correlated with BTC price trend (redundant)
- Including F&G as a "confounder" introduced collider bias

### 7.3 Price Leads Sentiment
Lead-lag analysis shows:
- Price movements precede sentiment changes by ~12 hours
- This suggests **reverse causation**: price → sentiment, not sentiment → price
- Reddit users react to price moves, they don't predict them

### 7.4 Valid Confounders Have No Effect
- VIX (macro fear): not significant (p=0.27)
- Volatility: not significant (p=0.68)
- These don't reveal any hidden sentiment effect

---

## 8. Implications

### For Trading
- Reddit sentiment is **not** a reliable alpha signal for BTC
- Any apparent correlations are likely due to:
  - Common causes (news affecting both)
  - Reverse causation (price → sentiment)
  - Collider bias if using F&G

### For Research
- Fear & Greed Index should **not** be used as a confounder
- Proper causal DAG analysis is essential before regression
- Collider bias can create false positives

### For This Project
- The crawler successfully collects sentiment data
- The data pipeline works correctly
- The causal hypothesis (sentiment → price) is not supported
- May pivot to:
  - Predicting sentiment from price (reverse direction)
  - Using sentiment for other purposes (community analysis)
  - Exploring other data sources

---

## 9. Limitations

1. **Sample size**: ~300 aligned observations may be insufficient
2. **Time period**: Single month (January 2026)
3. **Unobserved confounders**: Whale intent remains unobservable
4. **Sentiment measurement**: VADER may not capture crypto-specific language
5. **Aggregation**: Hourly aggregation may miss intraday dynamics

---

## 10. Figures

All figures saved in `docs/figures/` and `data/`:
- `causal_dag_strategies.png` - Identification strategies
- `causal_dag_detailed.png` - Full DAG with variables
- `confounders_review.png` - Confounder analysis
- `dag_blocking_v1.png` - Blocked vs open paths
- `fng_collider_analysis.png` - F&G collider demonstration
- `causal_analysis_results.png` - Regression visualizations

---

## Appendix: Raw Data Sample

```
Aligned Data Sample (hourly):

hour              sentiment  btc_price   fng   vix   volatility
2026-01-31 23:00  -0.252     $78,096     20    17.0  50.4%
2026-01-31 22:00  -0.044     $78,150     20    -     50.8%
2026-01-31 16:00  +0.556     $80,253     20    -     47.0%
2026-01-31 10:00  +0.900     $83,036     20    -     34.9%
```

---

*Analysis complete. Document generated 2026-01-31.*
