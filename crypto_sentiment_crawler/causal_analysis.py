"""
Run causal analysis: Does sentiment Granger-cause price movements?
"""

import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

from .causal.granger import GrangerAnalyzer, compute_lead_lag_correlation


def load_aligned_data(db_path: str = "data/sentiment.db", coin: str = "BTC") -> pd.DataFrame:
    """Load and align sentiment and price data."""
    conn = sqlite3.connect(db_path)

    # Load hourly prices
    price_df = pd.read_sql_query(f"""
        SELECT timestamp, price_usd
        FROM price_data
        WHERE coin = '{coin}'
        ORDER BY timestamp
    """, conn)
    price_df['timestamp'] = pd.to_datetime(price_df['timestamp'], format='ISO8601')
    price_df['hour'] = price_df['timestamp'].dt.floor('h')
    price_df = price_df.groupby('hour').agg({'price_usd': 'last'}).reset_index()

    # Load sentiment by source
    sentiment_df = pd.read_sql_query("""
        SELECT timestamp, source, score
        FROM sentiment_scores
        WHERE source != 'fear_greed'
        ORDER BY timestamp
    """, conn)
    sentiment_df['timestamp'] = pd.to_datetime(sentiment_df['timestamp'], format='ISO8601')
    sentiment_df['hour'] = sentiment_df['timestamp'].dt.floor('h')

    conn.close()

    # Aggregate sentiment by hour and source
    hourly_sent = sentiment_df.groupby(['hour', 'source']).agg({
        'score': 'mean'
    }).reset_index()

    # Pivot to get each source as a column
    sentiment_wide = hourly_sent.pivot(index='hour', columns='source', values='score')

    # Also compute overall sentiment
    overall_sent = sentiment_df.groupby('hour').agg({'score': 'mean'}).reset_index()
    overall_sent.columns = ['hour', 'overall_sentiment']

    # Merge all data
    merged = price_df.merge(overall_sent, on='hour', how='inner')
    merged = merged.merge(sentiment_wide, on='hour', how='left')

    # Compute returns
    merged = merged.sort_values('hour')
    merged['returns_1h'] = merged['price_usd'].pct_change() * 100
    merged['returns_4h'] = merged['price_usd'].pct_change(4) * 100

    return merged


def run_granger_analysis(coin: str = "BTC", max_lag: int = 12):
    """Run Granger causality analysis."""
    print("=" * 70)
    print(f"GRANGER CAUSALITY ANALYSIS: SENTIMENT -> {coin} PRICE")
    print("=" * 70)

    # Load data
    df = load_aligned_data(coin=coin)
    print(f"\nData points: {len(df)}")
    print(f"Time range: {df['hour'].min()} to {df['hour'].max()}")

    if len(df) < 50:
        print("\nERROR: Insufficient aligned data for Granger analysis (need 50+ points)")
        return None

    # Initialize analyzer
    analyzer = GrangerAnalyzer(max_lag=max_lag, significance=0.05)

    # Test overall sentiment -> returns
    print(f"\n{'='*70}")
    print("TEST 1: Overall Sentiment -> Price Returns")
    print("="*70)

    valid = df.dropna(subset=['overall_sentiment', 'returns_1h'])
    if len(valid) > max_lag * 2 + 10:
        result = analyzer.test_granger_causality(
            cause=valid['overall_sentiment'],
            effect=valid['returns_1h'],
            source_name="overall_sentiment",
            target_name=f"{coin}_returns",
        )

        print(f"\nResult: {'SENTIMENT GRANGER-CAUSES PRICE' if result.is_causal else 'No causal relationship detected'}")
        print(f"  Best lag: {result.optimal_lag} hours")
        print(f"  F-statistic: {result.f_statistic:.3f}")
        print(f"  P-value: {result.pvalue:.4f}")

        if result.all_lags and 'error' not in result.all_lags:
            print(f"\n  Results by lag:")
            for lag in sorted(result.all_lags.keys())[:6]:
                f_stat, pval = result.all_lags[lag]
                sig = "***" if pval < 0.01 else "**" if pval < 0.05 else "*" if pval < 0.1 else ""
                print(f"    Lag {lag:2d}h: F={f_stat:6.2f}, p={pval:.4f} {sig}")
    else:
        print("  Insufficient data")

    # Test stationarity
    print(f"\n{'='*70}")
    print("STATIONARITY TESTS")
    print("="*70)

    for col in ['overall_sentiment', 'returns_1h', 'price_usd']:
        if col in df.columns:
            series = df[col].dropna()
            stat_result = analyzer.test_stationarity(series)
            if 'error' not in stat_result:
                status = "STATIONARY" if stat_result['is_stationary'] else "NON-STATIONARY"
                print(f"  {col:25}: {status} (p={stat_result['pvalue']:.4f})")

    # Lead-lag correlation
    print(f"\n{'='*70}")
    print("LEAD-LAG CORRELATION ANALYSIS")
    print("="*70)

    valid = df.dropna(subset=['overall_sentiment', 'returns_1h'])
    if len(valid) > 20:
        ll_result = compute_lead_lag_correlation(
            valid['overall_sentiment'],
            valid['returns_1h'],
            max_lag=12,
        )

        if 'error' not in ll_result:
            print(f"\n  Optimal lag: {ll_result['optimal_lag']} hours")
            print(f"  Correlation at optimal lag: {ll_result['optimal_correlation']:.3f}")

            if ll_result['optimal_lag'] > 0:
                print(f"  Interpretation: Sentiment LEADS price by {ll_result['optimal_lag']}h")
            elif ll_result['optimal_lag'] < 0:
                print(f"  Interpretation: Price LEADS sentiment by {-ll_result['optimal_lag']}h")
            else:
                print(f"  Interpretation: Contemporaneous relationship")

            print(f"\n  Correlation by lag (positive = sentiment leads):")
            for lag in range(-6, 7):
                if lag in ll_result['correlations']:
                    corr = ll_result['correlations'][lag]
                    bar = '█' * int(abs(corr) * 20)
                    sign = '+' if corr > 0 else '-'
                    print(f"    Lag {lag:+3d}h: {sign}{abs(corr):.3f} {bar}")

    # Test by source
    print(f"\n{'='*70}")
    print("GRANGER CAUSALITY BY SOURCE")
    print("="*70)

    source_cols = [c for c in df.columns if c.startswith('reddit_')]
    results = []

    for source in source_cols:
        valid = df.dropna(subset=[source, 'returns_1h'])
        if len(valid) > max_lag * 2 + 10:
            result = analyzer.test_granger_causality(
                cause=valid[source],
                effect=valid['returns_1h'],
                source_name=source,
                target_name="returns",
            )
            results.append((source, result.pvalue, result.is_causal, result.optimal_lag, len(valid)))

    if results:
        # Sort by p-value
        results.sort(key=lambda x: x[1])
        print(f"\n  {'Source':<35} {'p-value':>10} {'Lag':>6} {'n':>6} {'Causal?':>10}")
        print("  " + "-" * 70)
        for source, pval, is_causal, lag, n in results:
            causal_str = "YES ***" if is_causal else "no"
            print(f"  {source:<35} {pval:>10.4f} {lag:>6}h {n:>6} {causal_str:>10}")
    else:
        print("  No source-specific data available")

    # Reverse test: Price -> Sentiment
    print(f"\n{'='*70}")
    print("REVERSE TEST: Price Returns -> Sentiment")
    print("="*70)

    valid = df.dropna(subset=['overall_sentiment', 'returns_1h'])
    if len(valid) > max_lag * 2 + 10:
        result = analyzer.test_granger_causality(
            cause=valid['returns_1h'],
            effect=valid['overall_sentiment'],
            source_name="price_returns",
            target_name="sentiment",
        )

        print(f"\nResult: {'PRICE GRANGER-CAUSES SENTIMENT' if result.is_causal else 'No causal relationship detected'}")
        print(f"  Best lag: {result.optimal_lag} hours")
        print(f"  P-value: {result.pvalue:.4f}")

        if result.is_causal:
            print("\n  NOTE: Price appears to drive sentiment (reactive sentiment)")

    print("\n" + "=" * 70)

    return df


if __name__ == "__main__":
    for coin in ["BTC", "ETH", "SOL"]:
        run_granger_analysis(coin)
        print("\n")
