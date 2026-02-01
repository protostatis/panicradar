# Multi-Dimensional Sentiment Evaluation Report

**Generated:** 2026-02-01
**Short-term Data:** 2026-01-01 to 2026-02-01 (622 hourly observations)
**Historical Validation:** 2018-06 to 2026-01 (699 daily observations)

## Executive Summary

Initial backtesting on 1-month data showed promising results for regime-adaptive strategies.
**However, historical validation on 8 years of data shows these results do not hold.**

| Strategy | 1-Month Return | Historical Return (8yr) | Verdict |
|----------|----------------|-------------------------|---------|
| Buy & Hold | -12.23% | +390.2% | **WINNER** |
| Simple Contrarian | +7.16% | -151.9% | FAILS |
| Regime-Adaptive | +14.93% | -137.9% | FAILS |

## Why Initial Results Were Misleading

1. **Small sample size**: 622 hourly ≈ 26 daily observations
2. **Bear market bias**: January 2026 was -12%, contrarian works in downtrends
3. **Overfitting**: Strategies tuned to recent conditions
4. **No out-of-sample validation**: All results were in-sample

## Historical Validation Results (2018-2026)

### Correlation by Regime (Fear & Greed Index)

| Regime | Correlation | P-value | N |
|--------|-------------|---------|---|
| Low Volatility | +0.096 | 0.073 | 350 |
| High Volatility | +0.055 | 0.302 | 349 |

**Fisher Z-test for difference: p = 0.59 (NOT significant)**

The correlations are:
- Both positive (momentum, not contrarian)
- Not significantly different between regimes
- Weak overall (r < 0.1)

### Year-by-Year Performance

| Year | Market | B&H | Contrarian | Regime-Adaptive |
|------|--------|-----|------------|-----------------|
| 2018 | Bear | -55.6% | -24.5% ★ | -29.9% |
| 2019 | Recovery | +87.8% ★ | -10.5% | -28.7% |
| 2020 | Bull | +162.8% ★ | -70.6% | -91.2% |
| 2021 | Bull | +78.4% ★ | -26.3% | -13.0% |
| 2022 | Bear | -82.9% | +7.6% | +33.7% ★ |
| 2023 | Recovery | +105.7% ★ | -18.1% | -18.1% |
| 2024 | Bull | +92.9% ★ | -42.5% | -23.6% |
| 2025 | Mixed | +1.9% | +35.0% ★ | +35.0% ★ |

**Pattern:** Contrarian strategies only work in bear markets (2018, 2022, 2025).
In bull markets (majority of history), they lose significantly.

## Honest Assessment

### What the Multi-Dimensional Scores Provide

1. **NOT standalone trading signals** - underperform buy & hold
2. **Possibly useful for:**
   - Risk management (increase hedges during euphoria)
   - Volatility prediction (extreme sentiment → higher vol)
   - Entry timing within established trends
   - Filtering/confirming other signals

### What We Learned

1. **Sentiment follows price** - momentum, not contrarian
2. **Regime differences are not statistically significant**
3. **Short-term backtests are dangerous** - easy to overfit
4. **Historical validation is essential** - 8 years reveals truth

## Data Quality

| Dataset | Records | Date Range |
|---------|---------|------------|
| User Sentiment Scores | 3,994 | 2026-01 |
| Price Data | 1,874 | 2026-01 |
| Fear & Greed (historical) | 2,919 | 2018-2026 |
| On-Chain Metrics | 42 | Just started |

## Recommendations

1. **Do not deploy regime-adaptive strategy** - fails on historical data
2. **Continue collecting multi-dimensional data** - may find other uses
3. **Focus on risk management applications** - not directional trading
4. **Combine with trend-following signals** - sentiment as filter, not driver
5. **Collect on-chain data longer** - may provide orthogonal signal

---
*This report reflects an honest assessment after historical validation revealed initial findings were likely overfitting.*
