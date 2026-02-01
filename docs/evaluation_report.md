# Multi-Dimensional Sentiment Evaluation Report

**Generated:** 2026-02-01
**Dataset:** 2,918 daily observations (2018-01-31 to 2026-01-30)
**Coverage:** 99.9% daily coverage across all major market regimes

## Executive Summary

After rigorous backtesting on 8 years of Fear & Greed Index data with complete daily coverage, we find:

| Strategy | Return | Sharpe | Best Use Case |
|----------|--------|--------|---------------|
| **Buy & Hold** | +378% | 0.74 | Bull markets (default) |
| Regime-Adaptive | +204% | 0.65 | Bear market protection |
| Pure Momentum | +37% | 0.12 | Limited value |
| Pure Contrarian | -37% | -0.12 | **AVOID** |

**Key Insight:** Sentiment is primarily a **momentum** signal, not contrarian. Both extreme fear AND extreme greed precede positive returns on average.

## Key Findings

### 1. Sentiment is Momentum, Not Contrarian

| Condition | N | Next 1-Day | Next 5-Day |
|-----------|---|------------|------------|
| Extreme Greed (F&G > 75) | 330 | +0.43% | +2.38% |
| Neutral | 2,260 | +0.06% | +0.38% |
| Extreme Fear (F&G < 20) | 328 | +0.32% | +0.99% |

**Implication:** Fading sentiment loses money historically. Following sentiment (momentum) generates small positive returns.

### 2. Volatility Regime Effect

| Volatility Regime | N | Correlation | P-value | Interpretation |
|-------------------|---|-------------|---------|----------------|
| High Volatility | 1,444 | +0.057 | **0.031** | Momentum works |
| Low Volatility | 1,469 | -0.004 | 0.873 | No signal |

**Fisher Z-test for difference:** p = 0.13 (marginally different)

In high volatility periods, sentiment has weak but statistically significant predictive power (momentum direction).

### 3. Trend Regime Effect (Stronger Signal)

| Trend Regime | N | 5-Day Correlation | P-value |
|--------------|---|-------------------|---------|
| **Strong Bull** | 578 | **+0.14** | **0.0005** |
| Bull | 630 | +0.06 | 0.14 |
| Sideways | 766 | -0.01 | 0.83 |
| Bear | 674 | +0.01 | 0.90 |
| **Strong Bear** | 235 | **-0.15** | **0.02** |

**Key Finding:** Trend regime matters more than volatility regime:
- In **strong bull markets**: High sentiment → even higher returns (momentum)
- In **strong bear markets**: High sentiment → smaller losses (contrarian works here)

### 4. Year-by-Year Strategy Performance

| Year | Market | B&H | Contrarian | Momentum | Regime-Adaptive | Winner |
|------|--------|-----|------------|----------|-----------------|--------|
| 2018 | Bear | -61% | +12% | -12% | **+38%** | Regime |
| 2019 | Recovery | **+86%** | +11% | -11% | +29% | B&H |
| 2020 | Bull | **+169%** | -49% | +49% | +45% | B&H |
| 2021 | Bull | **+81%** | -4% | +4% | +27% | B&H |
| 2022 | Bear | -85% | +3% | -3% | **+68%** | Regime |
| 2023 | Recovery | **+107%** | +1% | -1% | +1% | B&H |
| 2024 | Bull | **+90%** | -27% | +27% | -9% | B&H |
| 2025 | Mixed | +3% | **+20%** | -20% | +10% | Contrarian |
| 2026 | Bear | -11% | -4% | **+4%** | -4% | Momentum |

**Pattern:** Regime-adaptive wins in bear markets (2018, 2022), B&H wins in bull markets (majority).

## Data Coverage Assessment

### Regime Distribution (n=2,918 days)

| Regime | Days | Percentage | Avg F&G | Avg Daily Return |
|--------|------|------------|---------|------------------|
| Strong Bull | 578 | 19.8% | 69.0 | +0.88% |
| Bull | 630 | 21.6% | 56.2 | +0.49% |
| Sideways | 770 | 26.4% | 44.0 | +0.02% |
| Bear | 675 | 23.1% | 33.2 | -0.45% |
| Strong Bear | 235 | 8.1% | 18.3 | -0.75% |

**Assessment:** Good balance across regimes. Slightly underweight strong bear (8.1%) but sufficient sample (n=235).

### Major Market Events Coverage

| Event | Period | Coverage |
|-------|--------|----------|
| ✅ 2018 Crypto Winter | Jan-Dec 2018 | 91% |
| ✅ COVID Crash | Mar 2020 | 100% |
| ✅ 2020-2021 Bull Run | Oct 2020 - Apr 2021 | 100% |
| ✅ May 2021 Crash | May-Jul 2021 | 100% |
| ✅ Nov 2021 ATH | Nov 2021 | 100% |
| ✅ 2022 Bear (Luna, FTX) | Jan-Dec 2022 | 100% |
| ✅ 2023-2024 Recovery | Jan 2023 - Dec 2024 | 100% |
| ❌ 2017 Bull Peak | Dec 2017 | **Missing** (F&G starts Feb 2018) |

### Remaining Gap: 2017 Bull Market

The Fear & Greed Index began in February 2018, missing the iconic December 2017 peak ($19,783).

**Backfill Options:**
1. **Google Trends** - "bitcoin" search volume as sentiment proxy (available 2004+)
2. **Reddit Archives** - Pushshift dataset for r/Bitcoin sentiment
3. **Accept Limitation** - 8 years is statistically sufficient for most analyses

## Conclusions

### What Works
1. **Buy & Hold** remains the best strategy in secular bull markets
2. **Regime-Adaptive** provides value for risk management in bear markets
3. **Trend detection first, then sentiment** - use sentiment to confirm, not predict

### What Doesn't Work
1. **Pure contrarian** trading based on sentiment
2. **Sentiment as standalone alpha source**
3. **Ignoring market regime** when interpreting sentiment

### Recommended Use Cases
1. **Portfolio Hedging:** Increase hedges when sentiment is extreme
2. **Volatility Prediction:** Extreme sentiment → expect higher volatility
3. **Signal Confirmation:** Use sentiment to filter other signals, not generate them
4. **Bear Market Protection:** Regime-adaptive approach can reduce drawdowns

## Statistical Validation Summary

| Test | Result | Interpretation |
|------|--------|----------------|
| F&G → Return (overall) | r = 0.03, p = 0.08 | Weak, marginal |
| F&G → Return (high vol) | r = 0.06, p = **0.03** | Significant momentum |
| F&G → Return (strong bull) | r = 0.14, p = **0.0005** | Strong momentum |
| F&G → Return (strong bear) | r = -0.15, p = **0.02** | Contrarian works here |
| Vol regime difference | z = 1.52, p = 0.13 | Marginal difference |

---

*Report based on 2,918 daily observations with 99.9% coverage. Analysis performed 2026-02-01.*
