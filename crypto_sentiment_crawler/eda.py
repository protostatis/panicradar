"""
Exploratory Data Analysis: Sentiment vs Price relationships.
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Optional: for visualization
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def load_data(db_path: str = "data/sentiment.db") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load sentiment and price data from database."""
    conn = sqlite3.connect(db_path)

    # Load sentiment scores
    sentiment_df = pd.read_sql_query("""
        SELECT timestamp, source, coin, score, confidence, sample_size
        FROM sentiment_scores
        WHERE source != 'fear_greed'
        ORDER BY timestamp
    """, conn)
    sentiment_df['timestamp'] = pd.to_datetime(sentiment_df['timestamp'], format='ISO8601')

    # Load price data
    price_df = pd.read_sql_query("""
        SELECT timestamp, coin, price_usd, volume_24h
        FROM price_data
        ORDER BY timestamp
    """, conn)
    price_df['timestamp'] = pd.to_datetime(price_df['timestamp'], format='ISO8601')

    # Load raw sentiment with content
    raw_df = pd.read_sql_query("""
        SELECT timestamp, source, coin, raw_data
        FROM sentiment_raw
        ORDER BY timestamp
    """, conn)
    raw_df['timestamp'] = pd.to_datetime(raw_df['timestamp'], format='ISO8601')

    conn.close()

    return sentiment_df, price_df, raw_df


def compute_hourly_sentiment(sentiment_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sentiment to hourly frequency."""
    sentiment_df = sentiment_df.copy()
    sentiment_df['hour'] = sentiment_df['timestamp'].dt.floor('h')

    hourly = sentiment_df.groupby(['hour', 'coin']).agg({
        'score': ['mean', 'std', 'count'],
        'confidence': 'mean',
    }).reset_index()

    hourly.columns = ['hour', 'coin', 'sentiment_mean', 'sentiment_std', 'count', 'confidence']
    return hourly


def align_sentiment_price(
    sentiment_df: pd.DataFrame,
    price_df: pd.DataFrame,
    coin: str = "BTC",
) -> pd.DataFrame:
    """Align sentiment and price data by timestamp."""

    # Get hourly sentiment
    hourly_sent = compute_hourly_sentiment(sentiment_df)

    # Filter for specific coin (or MARKET for general sentiment)
    coin_sent = hourly_sent[
        (hourly_sent['coin'] == coin) | (hourly_sent['coin'].isna())
    ].copy()

    if coin_sent.empty:
        # Use all sentiment if no coin-specific data
        coin_sent = hourly_sent.groupby('hour').agg({
            'sentiment_mean': 'mean',
            'sentiment_std': 'mean',
            'count': 'sum',
            'confidence': 'mean',
        }).reset_index()

    # Get price for coin
    coin_price = price_df[price_df['coin'] == coin].copy()
    coin_price['hour'] = coin_price['timestamp'].dt.floor('h')

    # Merge
    merged = pd.merge(
        coin_price,
        coin_sent,
        on='hour',
        how='inner',
    )

    if not merged.empty:
        # Compute price changes
        merged = merged.sort_values('hour')
        merged['price_change_1h'] = merged['price_usd'].pct_change() * 100
        merged['price_change_4h'] = merged['price_usd'].pct_change(4) * 100
        merged['price_change_24h'] = merged['price_usd'].pct_change(24) * 100

        # Lagged sentiment (sentiment from N hours ago)
        merged['sentiment_lag_1h'] = merged['sentiment_mean'].shift(1)
        merged['sentiment_lag_4h'] = merged['sentiment_mean'].shift(4)

        # Future price changes (for prediction analysis)
        merged['future_price_1h'] = merged['price_usd'].shift(-1)
        merged['future_change_1h'] = (merged['future_price_1h'] / merged['price_usd'] - 1) * 100
        merged['future_change_4h'] = (merged['price_usd'].shift(-4) / merged['price_usd'] - 1) * 100

    return merged


def compute_correlations(merged_df: pd.DataFrame) -> dict:
    """Compute correlations between sentiment and price."""
    results = {}

    if merged_df.empty or len(merged_df) < 10:
        return {"error": "Insufficient data for correlation analysis"}

    # Correlation: current sentiment vs current price change
    valid = merged_df.dropna(subset=['sentiment_mean', 'price_change_1h'])
    if len(valid) > 5:
        corr, pval = stats.pearsonr(valid['sentiment_mean'], valid['price_change_1h'])
        results['sentiment_vs_current_price_1h'] = {
            'correlation': corr,
            'p_value': pval,
            'n': len(valid),
        }

    # Correlation: lagged sentiment vs price change (predictive)
    valid = merged_df.dropna(subset=['sentiment_lag_4h', 'price_change_1h'])
    if len(valid) > 5:
        corr, pval = stats.pearsonr(valid['sentiment_lag_4h'], valid['price_change_1h'])
        results['sentiment_4h_ago_vs_price_change'] = {
            'correlation': corr,
            'p_value': pval,
            'n': len(valid),
        }

    # Correlation: current sentiment vs future price (predictive power)
    valid = merged_df.dropna(subset=['sentiment_mean', 'future_change_4h'])
    if len(valid) > 5:
        corr, pval = stats.pearsonr(valid['sentiment_mean'], valid['future_change_4h'])
        results['sentiment_vs_future_price_4h'] = {
            'correlation': corr,
            'p_value': pval,
            'n': len(valid),
        }

    return results


def analyze_sentiment_buckets(merged_df: pd.DataFrame) -> pd.DataFrame:
    """Analyze price movements for different sentiment levels."""
    if merged_df.empty:
        return pd.DataFrame()

    merged_df = merged_df.copy()

    # Create sentiment buckets
    merged_df['sentiment_bucket'] = pd.cut(
        merged_df['sentiment_mean'],
        bins=[-1, -0.3, -0.1, 0.1, 0.3, 1],
        labels=['Very Negative', 'Negative', 'Neutral', 'Positive', 'Very Positive']
    )

    # Analyze future price change by sentiment bucket
    bucket_analysis = merged_df.groupby('sentiment_bucket', observed=True).agg({
        'future_change_4h': ['mean', 'std', 'count'],
        'price_change_1h': ['mean', 'std'],
    }).round(3)

    return bucket_analysis


def print_eda_report(coin: str = "BTC"):
    """Generate and print EDA report."""
    print("=" * 70)
    print(f"EXPLORATORY DATA ANALYSIS: SENTIMENT vs PRICE ({coin})")
    print("=" * 70)

    # Load data
    sentiment_df, price_df, raw_df = load_data()

    print(f"\nDATA OVERVIEW:")
    print(f"  Sentiment records: {len(sentiment_df)}")
    print(f"  Price records: {len(price_df)}")
    print(f"  Raw content records: {len(raw_df)}")

    # Time range
    if not sentiment_df.empty:
        print(f"  Sentiment range: {sentiment_df['timestamp'].min()} to {sentiment_df['timestamp'].max()}")
    if not price_df.empty:
        print(f"  Price range: {price_df['timestamp'].min()} to {price_df['timestamp'].max()}")

    # Align data
    merged = align_sentiment_price(sentiment_df, price_df, coin)
    print(f"\n  Aligned records: {len(merged)}")

    if merged.empty:
        print("\n  ERROR: No aligned data available. Need overlapping sentiment and price timestamps.")
        return

    # Sentiment distribution
    print(f"\nSENTIMENT DISTRIBUTION:")
    print(f"  Mean: {merged['sentiment_mean'].mean():.3f}")
    print(f"  Std:  {merged['sentiment_std'].mean():.3f}")
    print(f"  Min:  {merged['sentiment_mean'].min():.3f}")
    print(f"  Max:  {merged['sentiment_mean'].max():.3f}")

    # Price stats
    print(f"\nPRICE STATISTICS ({coin}):")
    print(f"  Current: ${merged['price_usd'].iloc[-1]:,.2f}")
    print(f"  Min:     ${merged['price_usd'].min():,.2f}")
    print(f"  Max:     ${merged['price_usd'].max():,.2f}")
    print(f"  Volatility (1h): {merged['price_change_1h'].std():.2f}%")

    # Correlations
    print(f"\nCORRELATION ANALYSIS:")
    correlations = compute_correlations(merged)

    for name, data in correlations.items():
        if isinstance(data, dict) and 'correlation' in data:
            sig = "***" if data['p_value'] < 0.01 else "**" if data['p_value'] < 0.05 else "*" if data['p_value'] < 0.1 else ""
            print(f"  {name}:")
            print(f"    r = {data['correlation']:+.3f} {sig}")
            print(f"    p = {data['p_value']:.4f}")
            print(f"    n = {data['n']}")

    # Bucket analysis
    print(f"\nSENTIMENT BUCKET ANALYSIS (Future 4h Price Change):")
    bucket_analysis = analyze_sentiment_buckets(merged)
    if not bucket_analysis.empty:
        print(bucket_analysis.to_string())

    # Predictive signal check
    print(f"\nPREDICTIVE SIGNAL CHECK:")
    valid = merged.dropna(subset=['sentiment_mean', 'future_change_4h'])
    if len(valid) > 10:
        # When sentiment is positive, how often does price go up?
        positive_sent = valid[valid['sentiment_mean'] > 0.1]
        negative_sent = valid[valid['sentiment_mean'] < -0.1]

        if len(positive_sent) > 0:
            pos_up = (positive_sent['future_change_4h'] > 0).mean() * 100
            print(f"  When sentiment > 0.1: price up in next 4h {pos_up:.1f}% of time (n={len(positive_sent)})")

        if len(negative_sent) > 0:
            neg_down = (negative_sent['future_change_4h'] < 0).mean() * 100
            print(f"  When sentiment < -0.1: price down in next 4h {neg_down:.1f}% of time (n={len(negative_sent)})")

    print("\n" + "=" * 70)

    return merged


def create_visualizations(merged_df: pd.DataFrame, coin: str = "BTC", output_dir: str = "data"):
    """Create visualization plots."""
    if not HAS_MATPLOTLIB:
        print("matplotlib not installed. Skipping visualizations.")
        return

    if merged_df.empty:
        print("No data for visualization.")
        return

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # Plot 1: Price over time
    ax1 = axes[0]
    ax1.plot(merged_df['hour'], merged_df['price_usd'], 'b-', linewidth=1)
    ax1.set_ylabel(f'{coin} Price (USD)', color='b')
    ax1.tick_params(axis='y', labelcolor='b')
    ax1.set_title(f'{coin} Price vs Sentiment Over Time')
    ax1.grid(True, alpha=0.3)

    # Plot 2: Sentiment over time
    ax2 = axes[1]
    colors = ['red' if s < 0 else 'green' for s in merged_df['sentiment_mean']]
    ax2.bar(merged_df['hour'], merged_df['sentiment_mean'], color=colors, alpha=0.7, width=0.03)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax2.set_ylabel('Sentiment Score')
    ax2.set_ylim(-1, 1)
    ax2.grid(True, alpha=0.3)

    # Plot 3: Scatter - Sentiment vs Future Price Change
    ax3 = axes[2]
    valid = merged_df.dropna(subset=['sentiment_mean', 'future_change_4h'])
    if len(valid) > 0:
        ax3.scatter(valid['sentiment_mean'], valid['future_change_4h'], alpha=0.5, s=20)

        # Add trend line
        if len(valid) > 5:
            z = np.polyfit(valid['sentiment_mean'], valid['future_change_4h'], 1)
            p = np.poly1d(z)
            x_line = np.linspace(valid['sentiment_mean'].min(), valid['sentiment_mean'].max(), 100)
            ax3.plot(x_line, p(x_line), 'r--', linewidth=2, label=f'Trend (slope={z[0]:.2f})')
            ax3.legend()

        ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax3.axvline(x=0, color='black', linestyle='-', linewidth=0.5)
        ax3.set_xlabel('Sentiment Score')
        ax3.set_ylabel('Future 4h Price Change (%)')
        ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    plot_path = output_path / f"eda_{coin.lower()}.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"\nVisualization saved to: {plot_path}")


def run_full_eda():
    """Run full EDA for all coins."""
    for coin in ["BTC", "ETH", "SOL"]:
        merged = print_eda_report(coin)
        if merged is not None and not merged.empty:
            create_visualizations(merged, coin)
        print("\n")


if __name__ == "__main__":
    run_full_eda()
