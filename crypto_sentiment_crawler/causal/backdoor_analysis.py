"""
Backdoor-adjusted causal analysis: Sentiment → Price.

Compares:
1. Naive (unadjusted) estimate
2. Backdoor-adjusted estimate (conditioning on observable confounders)
3. Sensitivity analysis for unobserved confounding
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

try:
    import statsmodels.api as sm
    from statsmodels.regression.linear_model import OLS
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

from ..logging_config import logger


def load_aligned_data(db_path: str = "data/sentiment.db") -> pd.DataFrame:
    """
    Load and align sentiment, price, and confounder data.

    Returns hourly DataFrame with all variables.
    """
    conn = sqlite3.connect(db_path)

    # Load hourly sentiment
    sentiment_df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
            AVG(score) as sentiment,
            COUNT(*) as sentiment_n
        FROM sentiment_scores
        WHERE source != 'fear_greed'
        GROUP BY hour
    """, conn)

    # Load hourly prices
    price_df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
            coin,
            AVG(price_usd) as price
        FROM price_data
        GROUP BY hour, coin
    """, conn)

    # Pivot prices by coin
    price_wide = price_df.pivot(index='hour', columns='coin', values='price')
    price_wide.columns = [f'price_{c.lower()}' for c in price_wide.columns]
    price_wide = price_wide.reset_index()

    # Load hourly confounders
    confounder_df = pd.read_sql_query("""
        SELECT
            strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
            AVG(fear_greed_index) as fear_greed,
            AVG(vix_level) as vix,
            AVG(dxy_value) as dxy,
            AVG(sp500_price) as sp500,
            AVG(volatility_24h) as volatility,
            AVG(btc_trend_7d) as btc_trend_7d,
            AVG(btc_dominance) as btc_dominance
        FROM confounders
        GROUP BY hour
    """, conn)

    conn.close()

    # Merge all data
    df = sentiment_df.merge(price_wide, on='hour', how='inner')
    df = df.merge(confounder_df, on='hour', how='inner')

    # Convert hour to datetime
    df['hour'] = pd.to_datetime(df['hour'])
    df = df.sort_values('hour')

    # Calculate returns (outcome variable)
    df['returns_1h'] = df['price_btc'].pct_change() * 100
    df['returns_4h'] = df['price_btc'].pct_change(4) * 100

    # Lagged sentiment (treatment at t-1)
    df['sentiment_lag1'] = df['sentiment'].shift(1)
    df['sentiment_lag4'] = df['sentiment'].shift(4)

    # Lagged confounders
    df['fear_greed_lag1'] = df['fear_greed'].shift(1)
    df['volatility_lag1'] = df['volatility'].shift(1)
    df['vix_lag1'] = df['vix'].shift(1)

    return df


def naive_regression(df: pd.DataFrame) -> dict[str, Any]:
    """
    Naive (unadjusted) regression: Returns ~ Sentiment.

    This estimate is likely biased due to confounding.
    """
    if not HAS_STATSMODELS:
        return {"error": "statsmodels not installed"}

    # Use lagged sentiment to predict returns
    valid = df.dropna(subset=['sentiment_lag1', 'returns_1h'])

    if len(valid) < 20:
        return {"error": "Insufficient data"}

    X = sm.add_constant(valid['sentiment_lag1'])
    y = valid['returns_1h']

    model = OLS(y, X).fit()

    return {
        "method": "Naive OLS",
        "coefficient": model.params['sentiment_lag1'],
        "std_error": model.bse['sentiment_lag1'],
        "t_stat": model.tvalues['sentiment_lag1'],
        "p_value": model.pvalues['sentiment_lag1'],
        "ci_lower": model.conf_int().loc['sentiment_lag1', 0],
        "ci_upper": model.conf_int().loc['sentiment_lag1', 1],
        "r_squared": model.rsquared,
        "n_obs": int(model.nobs),
        "model": model,
    }


def backdoor_adjusted_regression(df: pd.DataFrame) -> dict[str, Any]:
    """
    Backdoor-adjusted regression: Returns ~ Sentiment | Confounders.

    Conditions on observable confounders to block backdoor paths.
    """
    if not HAS_STATSMODELS:
        return {"error": "statsmodels not installed"}

    # Define adjustment set (confounders to condition on)
    adjustment_vars = [
        'fear_greed_lag1',    # Market regime
        'volatility_lag1',    # Market regime
        'vix_lag1',           # Macro
        'btc_trend_7d',       # Trend/momentum
    ]

    # Filter to rows with all variables
    required_cols = ['sentiment_lag1', 'returns_1h'] + adjustment_vars
    valid = df.dropna(subset=required_cols)

    if len(valid) < 30:
        return {"error": f"Insufficient data ({len(valid)} rows)"}

    # Build design matrix
    X_vars = ['sentiment_lag1'] + adjustment_vars
    X = valid[X_vars].copy()
    X = sm.add_constant(X)
    y = valid['returns_1h']

    model = OLS(y, X).fit()

    return {
        "method": "Backdoor-Adjusted OLS",
        "coefficient": model.params['sentiment_lag1'],
        "std_error": model.bse['sentiment_lag1'],
        "t_stat": model.tvalues['sentiment_lag1'],
        "p_value": model.pvalues['sentiment_lag1'],
        "ci_lower": model.conf_int().loc['sentiment_lag1', 0],
        "ci_upper": model.conf_int().loc['sentiment_lag1', 1],
        "r_squared": model.rsquared,
        "n_obs": int(model.nobs),
        "adjustment_set": adjustment_vars,
        "all_coefficients": model.params.to_dict(),
        "all_pvalues": model.pvalues.to_dict(),
        "model": model,
    }


def sensitivity_analysis(
    df: pd.DataFrame,
    naive_coef: float,
    adjusted_coef: float,
) -> dict[str, Any]:
    """
    Sensitivity analysis for unobserved confounding (whale intent).

    Estimates how strong unobserved confounding would need to be
    to explain away the effect.
    """
    # Calculate the change due to observed confounding
    confounding_removed = naive_coef - adjusted_coef

    # If adjusted coefficient is close to zero, effect may be spurious
    if abs(adjusted_coef) < 0.001:
        robustness = "LOW - Effect disappears after adjustment"
    elif abs(confounding_removed) > abs(adjusted_coef):
        robustness = "MEDIUM - Observed confounding explains >50% of naive effect"
    else:
        robustness = "HIGH - Effect persists after adjustment"

    # Calculate how much additional confounding would nullify effect
    if adjusted_coef != 0:
        nullifying_factor = abs(adjusted_coef / (naive_coef - adjusted_coef)) if confounding_removed != 0 else float('inf')
    else:
        nullifying_factor = 0

    return {
        "naive_coefficient": naive_coef,
        "adjusted_coefficient": adjusted_coef,
        "confounding_removed": confounding_removed,
        "percent_change": ((adjusted_coef - naive_coef) / naive_coef * 100) if naive_coef != 0 else 0,
        "robustness_assessment": robustness,
        "nullifying_factor": nullifying_factor,
        "interpretation": (
            f"Unobserved confounding (e.g., whale intent) would need to be "
            f"{nullifying_factor:.1f}x as strong as observed confounding to nullify the effect."
            if nullifying_factor != float('inf') and nullifying_factor > 0 else
            "Effect is robust to reasonable levels of unobserved confounding."
        ),
    }


def run_full_causal_analysis(db_path: str = "data/sentiment.db") -> dict[str, Any]:
    """
    Run complete causal analysis with backdoor adjustment.
    """
    print("=" * 70)
    print("CAUSAL ANALYSIS: SENTIMENT → PRICE (BACKDOOR ADJUSTMENT)")
    print("=" * 70)

    # Load data
    print("\nLoading aligned data...")
    df = load_aligned_data(db_path)
    print(f"  Total rows: {len(df)}")
    print(f"  Date range: {df['hour'].min()} to {df['hour'].max()}")

    # Check data availability
    valid_naive = df.dropna(subset=['sentiment_lag1', 'returns_1h'])
    print(f"  Valid for naive analysis: {len(valid_naive)}")

    adjustment_vars = ['fear_greed_lag1', 'volatility_lag1', 'vix_lag1', 'btc_trend_7d']
    valid_adjusted = df.dropna(subset=['sentiment_lag1', 'returns_1h'] + adjustment_vars)
    print(f"  Valid for adjusted analysis: {len(valid_adjusted)}")

    results = {
        "data_summary": {
            "total_rows": len(df),
            "valid_naive": len(valid_naive),
            "valid_adjusted": len(valid_adjusted),
            "date_range": f"{df['hour'].min()} to {df['hour'].max()}",
        }
    }

    # Naive regression
    print("\n" + "=" * 70)
    print("1. NAIVE (UNADJUSTED) REGRESSION")
    print("   Model: Returns(t) ~ Sentiment(t-1)")
    print("=" * 70)

    naive_result = naive_regression(df)
    results["naive"] = naive_result

    if "error" not in naive_result:
        sig = "***" if naive_result['p_value'] < 0.01 else "**" if naive_result['p_value'] < 0.05 else "*" if naive_result['p_value'] < 0.1 else ""
        print(f"\n  Coefficient: {naive_result['coefficient']:.4f} {sig}")
        print(f"  Std Error:   {naive_result['std_error']:.4f}")
        print(f"  t-statistic: {naive_result['t_stat']:.3f}")
        print(f"  p-value:     {naive_result['p_value']:.4f}")
        print(f"  95% CI:      [{naive_result['ci_lower']:.4f}, {naive_result['ci_upper']:.4f}]")
        print(f"  R-squared:   {naive_result['r_squared']:.4f}")
        print(f"  N:           {naive_result['n_obs']}")

        if naive_result['p_value'] < 0.05:
            direction = "positive" if naive_result['coefficient'] > 0 else "negative"
            print(f"\n  Interpretation: Sentiment has a significant {direction} effect on returns.")
            print(f"                  1 unit increase in sentiment → {naive_result['coefficient']:.2f}% return")
        else:
            print(f"\n  Interpretation: No significant effect detected (p > 0.05)")
    else:
        print(f"  Error: {naive_result['error']}")

    # Backdoor-adjusted regression
    print("\n" + "=" * 70)
    print("2. BACKDOOR-ADJUSTED REGRESSION")
    print("   Model: Returns(t) ~ Sentiment(t-1) | Confounders")
    print("   Adjustment Set: Fear&Greed, Volatility, VIX, BTC Trend")
    print("=" * 70)

    adjusted_result = backdoor_adjusted_regression(df)
    results["adjusted"] = adjusted_result

    if "error" not in adjusted_result:
        sig = "***" if adjusted_result['p_value'] < 0.01 else "**" if adjusted_result['p_value'] < 0.05 else "*" if adjusted_result['p_value'] < 0.1 else ""
        print(f"\n  Sentiment Coefficient: {adjusted_result['coefficient']:.4f} {sig}")
        print(f"  Std Error:             {adjusted_result['std_error']:.4f}")
        print(f"  t-statistic:           {adjusted_result['t_stat']:.3f}")
        print(f"  p-value:               {adjusted_result['p_value']:.4f}")
        print(f"  95% CI:                [{adjusted_result['ci_lower']:.4f}, {adjusted_result['ci_upper']:.4f}]")
        print(f"  R-squared:             {adjusted_result['r_squared']:.4f}")
        print(f"  N:                     {adjusted_result['n_obs']}")

        print(f"\n  Confounder Coefficients:")
        for var, coef in adjusted_result['all_coefficients'].items():
            if var != 'const' and var != 'sentiment_lag1':
                pval = adjusted_result['all_pvalues'][var]
                sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
                print(f"    {var:20}: {coef:+.4f} (p={pval:.3f}) {sig}")
    else:
        print(f"  Error: {adjusted_result['error']}")

    # Comparison and sensitivity analysis
    print("\n" + "=" * 70)
    print("3. COMPARISON & SENSITIVITY ANALYSIS")
    print("=" * 70)

    if "error" not in naive_result and "error" not in adjusted_result:
        sensitivity = sensitivity_analysis(
            df,
            naive_result['coefficient'],
            adjusted_result['coefficient'],
        )
        results["sensitivity"] = sensitivity

        print(f"\n  Naive coefficient:      {sensitivity['naive_coefficient']:.4f}")
        print(f"  Adjusted coefficient:   {sensitivity['adjusted_coefficient']:.4f}")
        print(f"  Change from adjustment: {sensitivity['confounding_removed']:.4f} ({sensitivity['percent_change']:.1f}%)")
        print(f"\n  Robustness: {sensitivity['robustness_assessment']}")
        print(f"\n  {sensitivity['interpretation']}")

    # Granger causality comparison
    print("\n" + "=" * 70)
    print("4. GRANGER CAUSALITY (for comparison)")
    print("=" * 70)

    from .granger import GrangerAnalyzer

    analyzer = GrangerAnalyzer(max_lag=6, significance=0.05)
    valid = df.dropna(subset=['sentiment', 'returns_1h'])

    if len(valid) > 30:
        granger_result = analyzer.test_granger_causality(
            cause=valid['sentiment'],
            effect=valid['returns_1h'],
            source_name="sentiment",
            target_name="returns",
        )
        results["granger"] = {
            "is_causal": granger_result.is_causal,
            "optimal_lag": granger_result.optimal_lag,
            "p_value": granger_result.pvalue,
            "f_statistic": granger_result.f_statistic,
        }

        sig = "***" if granger_result.pvalue < 0.01 else "**" if granger_result.pvalue < 0.05 else "*" if granger_result.pvalue < 0.1 else ""
        print(f"\n  Granger causal: {granger_result.is_causal} {sig}")
        print(f"  Optimal lag:    {granger_result.optimal_lag} hours")
        print(f"  F-statistic:    {granger_result.f_statistic:.3f}")
        print(f"  p-value:        {granger_result.pvalue:.4f}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if "error" not in naive_result and "error" not in adjusted_result:
        naive_sig = naive_result['p_value'] < 0.05
        adj_sig = adjusted_result['p_value'] < 0.05

        print(f"""
  ┌─────────────────────────────────────────────────────────────────┐
  │ Method                    │ Coefficient │ p-value │ Significant │
  ├─────────────────────────────────────────────────────────────────┤
  │ Naive (unadjusted)        │ {naive_result['coefficient']:+.4f}     │ {naive_result['p_value']:.4f}  │ {'Yes' if naive_sig else 'No':11} │
  │ Backdoor-adjusted         │ {adjusted_result['coefficient']:+.4f}     │ {adjusted_result['p_value']:.4f}  │ {'Yes' if adj_sig else 'No':11} │
  └─────────────────────────────────────────────────────────────────┘
        """)

        if adj_sig:
            print("  CONCLUSION: Sentiment appears to have a CAUSAL effect on price returns,")
            print("              even after controlling for observable confounders.")
            print("\n  CAVEAT: Unobserved confounding (whale intent) cannot be ruled out.")
        elif naive_sig and not adj_sig:
            print("  CONCLUSION: The apparent effect of sentiment on price is likely SPURIOUS.")
            print("              It disappears after controlling for confounders.")
        else:
            print("  CONCLUSION: No significant causal effect detected.")

    print("\n" + "=" * 70)

    return results


if __name__ == "__main__":
    run_full_causal_analysis()
