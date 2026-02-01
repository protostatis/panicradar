"""
Comprehensive backtest analysis for sentiment vs price.

Analyzes:
1. Correlation between sentiment and price changes at various lags
2. Performance by data source
3. Extreme sentiment events
4. Time-of-day patterns
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats

from ..storage.db import Database


@dataclass
class CorrelationResult:
    """Result of correlation analysis."""
    lag_hours: int
    correlation: float
    p_value: float
    sample_size: int
    is_significant: bool  # p < 0.05


@dataclass
class SourceAnalysis:
    """Analysis results for a single source."""
    source: str
    post_count: int
    avg_sentiment: float
    sentiment_std: float
    correlation_1h: float
    correlation_24h: float
    extreme_bullish_count: int
    extreme_bearish_count: int


@dataclass
class ExtremeEvent:
    """An extreme sentiment event."""
    timestamp: datetime
    sentiment: float
    price_at_event: float
    price_1h_later: float
    price_24h_later: float
    return_1h: float
    return_24h: float


class SentimentPriceAnalyzer:
    """Analyze relationship between sentiment and price."""

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.db: Optional[Database] = None

    async def connect(self):
        """Connect to database."""
        self.db = Database(Path(self.db_path))
        await self.db.connect()

    async def close(self):
        """Close database connection."""
        if self.db:
            await self.db.close()

    async def load_hourly_sentiment(self) -> dict[datetime, dict]:
        """Load sentiment data aggregated by hour."""
        cursor = await self.db.conn.execute("""
            SELECT
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                source,
                AVG(score) as avg_score,
                COUNT(*) as count
            FROM sentiment_scores
            GROUP BY hour, source
            ORDER BY hour
        """)
        rows = await cursor.fetchall()

        hourly = defaultdict(lambda: {"scores": [], "sources": defaultdict(list)})
        for hour_str, source, score, count in rows:
            hour = datetime.strptime(hour_str, '%Y-%m-%d %H:%M:%S')
            hourly[hour]["scores"].append(score)
            hourly[hour]["sources"][source].append(score)

        # Aggregate
        result = {}
        for hour, data in hourly.items():
            result[hour] = {
                "sentiment": np.mean(data["scores"]) if data["scores"] else 0,
                "count": len(data["scores"]),
                "by_source": {s: np.mean(scores) for s, scores in data["sources"].items()}
            }

        return result

    async def load_hourly_prices(self, coin: str = "BTC") -> dict[datetime, float]:
        """Load price data aggregated by hour."""
        cursor = await self.db.conn.execute("""
            SELECT
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                AVG(price_usd) as avg_price
            FROM price_data
            WHERE coin = ?
            GROUP BY hour
            ORDER BY hour
        """, (coin,))
        rows = await cursor.fetchall()

        return {
            datetime.strptime(hour_str, '%Y-%m-%d %H:%M:%S'): price
            for hour_str, price in rows
        }

    async def analyze_correlations(
        self,
        lags: list[int] = [1, 2, 4, 8, 12, 24, 48]
    ) -> list[CorrelationResult]:
        """Analyze correlation at different time lags."""
        sentiment = await self.load_hourly_sentiment()
        prices = await self.load_hourly_prices()

        results = []

        for lag in lags:
            sentiment_vals = []
            price_changes = []

            for hour, sent_data in sentiment.items():
                future_hour = hour + timedelta(hours=lag)

                if hour in prices and future_hour in prices:
                    current_price = prices[hour]
                    future_price = prices[future_hour]
                    pct_change = (future_price - current_price) / current_price * 100

                    sentiment_vals.append(sent_data["sentiment"])
                    price_changes.append(pct_change)

            if len(sentiment_vals) >= 10:
                corr, p_value = stats.pearsonr(sentiment_vals, price_changes)
                results.append(CorrelationResult(
                    lag_hours=lag,
                    correlation=corr,
                    p_value=p_value,
                    sample_size=len(sentiment_vals),
                    is_significant=p_value < 0.05
                ))
            else:
                results.append(CorrelationResult(
                    lag_hours=lag,
                    correlation=0,
                    p_value=1,
                    sample_size=len(sentiment_vals),
                    is_significant=False
                ))

        return results

    async def analyze_by_source(self) -> list[SourceAnalysis]:
        """Analyze each data source separately."""
        sentiment = await self.load_hourly_sentiment()
        prices = await self.load_hourly_prices()

        # Collect all sources
        sources = set()
        for data in sentiment.values():
            sources.update(data["by_source"].keys())

        results = []

        for source in sorted(sources):
            # Get source-specific data
            source_sentiments_1h = []
            price_changes_1h = []
            source_sentiments_24h = []
            price_changes_24h = []
            all_sentiments = []

            for hour, data in sentiment.items():
                if source in data["by_source"]:
                    sent = data["by_source"][source]
                    all_sentiments.append(sent)

                    # 1 hour ahead
                    future_1h = hour + timedelta(hours=1)
                    if hour in prices and future_1h in prices:
                        change = (prices[future_1h] - prices[hour]) / prices[hour] * 100
                        source_sentiments_1h.append(sent)
                        price_changes_1h.append(change)

                    # 24 hours ahead
                    future_24h = hour + timedelta(hours=24)
                    if hour in prices and future_24h in prices:
                        change = (prices[future_24h] - prices[hour]) / prices[hour] * 100
                        source_sentiments_24h.append(sent)
                        price_changes_24h.append(change)

            # Calculate correlations
            corr_1h = 0
            corr_24h = 0
            if len(source_sentiments_1h) >= 5:
                corr_1h, _ = stats.pearsonr(source_sentiments_1h, price_changes_1h)
            if len(source_sentiments_24h) >= 5:
                corr_24h, _ = stats.pearsonr(source_sentiments_24h, price_changes_24h)

            # Count extremes
            extreme_bullish = sum(1 for s in all_sentiments if s > 0.5)
            extreme_bearish = sum(1 for s in all_sentiments if s < -0.5)

            if all_sentiments:
                results.append(SourceAnalysis(
                    source=source,
                    post_count=len(all_sentiments),
                    avg_sentiment=np.mean(all_sentiments),
                    sentiment_std=np.std(all_sentiments) if len(all_sentiments) > 1 else 0,
                    correlation_1h=corr_1h,
                    correlation_24h=corr_24h,
                    extreme_bullish_count=extreme_bullish,
                    extreme_bearish_count=extreme_bearish,
                ))

        return sorted(results, key=lambda x: x.post_count, reverse=True)

    async def find_extreme_events(
        self,
        threshold: float = 0.5,
        min_samples: int = 5
    ) -> list[ExtremeEvent]:
        """Find extreme sentiment events and their outcomes."""
        sentiment = await self.load_hourly_sentiment()
        prices = await self.load_hourly_prices()

        events = []

        for hour, data in sentiment.items():
            if data["count"] < min_samples:
                continue

            sent = data["sentiment"]
            if abs(sent) < threshold:
                continue

            # Get prices
            hour_1h = hour + timedelta(hours=1)
            hour_24h = hour + timedelta(hours=24)

            if hour not in prices:
                continue

            price_now = prices[hour]
            price_1h = prices.get(hour_1h)
            price_24h = prices.get(hour_24h)

            if price_1h is None or price_24h is None:
                continue

            events.append(ExtremeEvent(
                timestamp=hour,
                sentiment=sent,
                price_at_event=price_now,
                price_1h_later=price_1h,
                price_24h_later=price_24h,
                return_1h=(price_1h - price_now) / price_now * 100,
                return_24h=(price_24h - price_now) / price_now * 100,
            ))

        return sorted(events, key=lambda x: abs(x.sentiment), reverse=True)

    async def run_full_analysis(self) -> dict:
        """Run comprehensive analysis and return results."""
        await self.connect()

        try:
            # Correlation analysis
            correlations = await self.analyze_correlations()

            # Source analysis
            sources = await self.analyze_by_source()

            # Extreme events
            extreme_events = await self.find_extreme_events(threshold=0.3)

            return {
                "correlations": correlations,
                "sources": sources,
                "extreme_events": extreme_events,
            }
        finally:
            await self.close()


def print_analysis_report(results: dict):
    """Print formatted analysis report."""
    print("\n" + "=" * 70)
    print("SENTIMENT VS PRICE ANALYSIS")
    print("=" * 70)

    # Correlations
    print("\n📊 CORRELATION BY TIME LAG")
    print("-" * 70)
    print(f"{'Lag (hours)':<12} {'Correlation':<14} {'P-value':<12} {'Samples':<10} {'Significant'}")
    print("-" * 70)

    for c in results["correlations"]:
        sig = "✓ YES" if c.is_significant else "  no"
        print(f"{c.lag_hours:<12} {c.correlation:>+.4f}       {c.p_value:<12.4f} {c.sample_size:<10} {sig}")

    # Interpretation
    best_corr = max(results["correlations"], key=lambda x: abs(x.correlation))
    print(f"\nStrongest correlation: {best_corr.correlation:+.4f} at {best_corr.lag_hours}h lag")

    if any(c.is_significant for c in results["correlations"]):
        print("⚠️  Some correlations are statistically significant (p < 0.05)")
    else:
        print("ℹ️  No correlations are statistically significant")

    # Source analysis
    print("\n\n📰 ANALYSIS BY SOURCE")
    print("-" * 70)
    print(f"{'Source':<25} {'Posts':<8} {'Avg Sent':<10} {'Corr 1h':<10} {'Corr 24h':<10}")
    print("-" * 70)

    for s in results["sources"][:15]:
        print(f"{s.source:<25} {s.post_count:<8} {s.avg_sentiment:>+.3f}     {s.correlation_1h:>+.3f}     {s.correlation_24h:>+.3f}")

    # Find best predictive source
    if results["sources"]:
        best_1h = max(results["sources"], key=lambda x: abs(x.correlation_1h) if x.post_count > 10 else 0)
        best_24h = max(results["sources"], key=lambda x: abs(x.correlation_24h) if x.post_count > 10 else 0)
        print(f"\nBest 1h predictor: {best_1h.source} (r={best_1h.correlation_1h:+.3f})")
        print(f"Best 24h predictor: {best_24h.source} (r={best_24h.correlation_24h:+.3f})")

    # Extreme events
    print("\n\n🚨 EXTREME SENTIMENT EVENTS")
    print("-" * 70)
    print(f"{'Date':<12} {'Sentiment':<12} {'Price':<12} {'1h Return':<12} {'24h Return'}")
    print("-" * 70)

    bullish_events = [e for e in results["extreme_events"] if e.sentiment > 0][:5]
    bearish_events = [e for e in results["extreme_events"] if e.sentiment < 0][:5]

    if bullish_events:
        print("\nExtreme BULLISH events:")
        for e in bullish_events:
            date_str = e.timestamp.strftime("%Y-%m-%d")
            print(f"{date_str:<12} {e.sentiment:>+.3f}       ${e.price_at_event:>9,.0f}  {e.return_1h:>+.2f}%       {e.return_24h:>+.2f}%")

    if bearish_events:
        print("\nExtreme BEARISH events:")
        for e in bearish_events:
            date_str = e.timestamp.strftime("%Y-%m-%d")
            print(f"{date_str:<12} {e.sentiment:>+.3f}       ${e.price_at_event:>9,.0f}  {e.return_1h:>+.2f}%       {e.return_24h:>+.2f}%")

    # Summary statistics
    if results["extreme_events"]:
        bullish_24h = [e.return_24h for e in results["extreme_events"] if e.sentiment > 0.3]
        bearish_24h = [e.return_24h for e in results["extreme_events"] if e.sentiment < -0.3]

        print("\n\n📈 EXTREME SENTIMENT STRATEGY ANALYSIS")
        print("-" * 70)

        if bullish_24h:
            avg_bull = np.mean(bullish_24h)
            win_bull = sum(1 for r in bullish_24h if r > 0) / len(bullish_24h) * 100
            print(f"After extreme BULLISH sentiment:")
            print(f"  Avg 24h return: {avg_bull:+.2f}%")
            print(f"  Win rate (24h): {win_bull:.1f}%")
            print(f"  Sample size: {len(bullish_24h)}")

        if bearish_24h:
            avg_bear = np.mean(bearish_24h)
            # For bearish, we'd want to SHORT, so positive return = loss
            contrarian_bear = [-r for r in bearish_24h]  # Inverse for contrarian
            win_bear = sum(1 for r in contrarian_bear if r > 0) / len(contrarian_bear) * 100
            print(f"\nAfter extreme BEARISH sentiment (contrarian LONG):")
            print(f"  Avg 24h return: {-avg_bear:+.2f}%")
            print(f"  Win rate (24h): {win_bear:.1f}%")
            print(f"  Sample size: {len(bearish_24h)}")

    # Final verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    significant_corrs = [c for c in results["correlations"] if c.is_significant]
    if not significant_corrs:
        print("❌ No statistically significant correlation found between sentiment and price.")
        print("   This could mean:")
        print("   - Sentiment doesn't predict price (efficient market)")
        print("   - Need more data for significance")
        print("   - Relationship is non-linear")
    else:
        best_sig = max(significant_corrs, key=lambda x: abs(x.correlation))
        direction = "positive" if best_sig.correlation > 0 else "negative"
        print(f"✅ Found {direction} correlation (r={best_sig.correlation:+.3f}) at {best_sig.lag_hours}h lag")
        print(f"   Statistical significance: p={best_sig.p_value:.4f}")

        if best_sig.correlation > 0:
            print("   → Bullish sentiment predicts price increases")
        else:
            print("   → Contrarian signal: bullish sentiment predicts price decreases")

    print("=" * 70)


async def main():
    """Run analysis."""
    analyzer = SentimentPriceAnalyzer()
    results = await analyzer.run_full_analysis()
    print_analysis_report(results)


if __name__ == "__main__":
    asyncio.run(main())
