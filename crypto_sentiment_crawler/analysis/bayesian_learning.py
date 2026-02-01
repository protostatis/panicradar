"""
Analyze Bayesian crawler learning over time.

Retroactively computes:
1. Prediction accuracy per source
2. Utility scores (accuracy + novelty)
3. Simulated belief updates
4. Learning curves
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
class SourcePerformance:
    """Performance metrics for a source."""
    source: str
    total_predictions: int
    correct_predictions: int
    accuracy: float
    avg_sentiment: float
    correlation_1h: float
    correlation_4h: float
    correlation_24h: float
    utility_score: float  # 0.7*accuracy + 0.3*novelty

    # Simulated Bayesian beliefs
    alpha: float  # Pseudo-count of informative
    beta: float   # Pseudo-count of non-informative
    belief_mean: float


@dataclass
class LearningPoint:
    """A point in time for learning curve."""
    timestamp: datetime
    cumulative_accuracy: float
    rolling_accuracy: float  # Last N predictions
    belief_mean: float
    sample_size: int


class BayesianLearningAnalyzer:
    """Analyze how the Bayesian crawler learns over time."""

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.db: Optional[Database] = None

    async def connect(self):
        self.db = Database(Path(self.db_path))
        await self.db.connect()

    async def close(self):
        if self.db:
            await self.db.close()

    async def compute_source_performance(self, lag_hours: int = 4) -> list[SourcePerformance]:
        """Compute prediction accuracy and utility for each source."""

        # Get all sentiment scores with timestamps
        cursor = await self.db.conn.execute("""
            SELECT timestamp, source, score
            FROM sentiment_scores
            ORDER BY timestamp
        """)
        sentiment_rows = await cursor.fetchall()

        # Get all price data
        cursor = await self.db.conn.execute("""
            SELECT timestamp, price_usd
            FROM price_data
            WHERE coin = 'BTC'
            ORDER BY timestamp
        """)
        price_rows = await cursor.fetchall()

        # Build price lookup by hour
        price_by_hour = {}
        for ts_str, price in price_rows:
            ts = datetime.fromisoformat(ts_str)
            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            if hour_key not in price_by_hour:
                price_by_hour[hour_key] = []
            price_by_hour[hour_key].append(price)

        price_by_hour = {h: np.mean(p) for h, p in price_by_hour.items()}

        # Track predictions per source
        source_predictions = defaultdict(lambda: {
            'correct': 0,
            'total': 0,
            'sentiments': [],
            'price_changes': [],
        })

        # Evaluate each sentiment prediction
        for ts_str, source, score in sentiment_rows:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)

            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            future_hour = hour_key + timedelta(hours=lag_hours)

            if hour_key not in price_by_hour or future_hour not in price_by_hour:
                continue

            price_now = price_by_hour[hour_key]
            price_future = price_by_hour[future_hour]
            price_change = (price_future - price_now) / price_now

            # Check if sentiment correctly predicted direction
            correct = (score > 0 and price_change > 0) or (score < 0 and price_change < 0)

            source_predictions[source]['total'] += 1
            source_predictions[source]['correct'] += int(correct)
            source_predictions[source]['sentiments'].append(score)
            source_predictions[source]['price_changes'].append(price_change * 100)

        # Compute metrics for each source
        results = []
        for source, data in source_predictions.items():
            if data['total'] < 10:
                continue

            accuracy = data['correct'] / data['total'] if data['total'] > 0 else 0
            avg_sentiment = np.mean(data['sentiments'])

            # Correlations at different lags
            corr_1h = await self._compute_correlation(source, 1)
            corr_4h = await self._compute_correlation(source, 4)
            corr_24h = await self._compute_correlation(source, 24)

            # Novelty (simplified - assume 0.5 average)
            novelty = 0.5

            # Utility score
            utility = 0.7 * accuracy + 0.3 * novelty

            # Simulate Bayesian belief update
            # Start with uniform prior Beta(1, 1)
            alpha = 1 + data['correct']
            beta = 1 + (data['total'] - data['correct'])
            belief_mean = alpha / (alpha + beta)

            results.append(SourcePerformance(
                source=source,
                total_predictions=data['total'],
                correct_predictions=data['correct'],
                accuracy=accuracy,
                avg_sentiment=avg_sentiment,
                correlation_1h=corr_1h,
                correlation_4h=corr_4h,
                correlation_24h=corr_24h,
                utility_score=utility,
                alpha=alpha,
                beta=beta,
                belief_mean=belief_mean,
            ))

        return sorted(results, key=lambda x: x.utility_score, reverse=True)

    async def _compute_correlation(self, source: str, lag_hours: int) -> float:
        """Compute correlation between source sentiment and price change."""
        cursor = await self.db.conn.execute("""
            SELECT timestamp, score
            FROM sentiment_scores
            WHERE source = ?
            ORDER BY timestamp
        """, (source,))
        sent_rows = await cursor.fetchall()

        cursor = await self.db.conn.execute("""
            SELECT timestamp, price_usd
            FROM price_data
            WHERE coin = 'BTC'
            ORDER BY timestamp
        """)
        price_rows = await cursor.fetchall()

        # Build price lookup
        price_by_hour = {}
        for ts_str, price in price_rows:
            ts = datetime.fromisoformat(ts_str)
            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            if hour_key not in price_by_hour:
                price_by_hour[hour_key] = []
            price_by_hour[hour_key].append(price)
        price_by_hour = {h: np.mean(p) for h, p in price_by_hour.items()}

        sentiments = []
        price_changes = []

        for ts_str, score in sent_rows:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)

            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            future_hour = hour_key + timedelta(hours=lag_hours)

            if hour_key in price_by_hour and future_hour in price_by_hour:
                change = (price_by_hour[future_hour] - price_by_hour[hour_key]) / price_by_hour[hour_key]
                sentiments.append(score)
                price_changes.append(change)

        if len(sentiments) < 5:
            return 0.0

        corr, _ = stats.pearsonr(sentiments, price_changes)
        return corr if not np.isnan(corr) else 0.0

    async def compute_learning_curve(self, source: str = None, window: int = 50) -> list[LearningPoint]:
        """Compute learning curve over time."""

        # Get predictions in chronological order
        if source:
            cursor = await self.db.conn.execute("""
                SELECT timestamp, source, score
                FROM sentiment_scores
                WHERE source = ?
                ORDER BY timestamp
            """, (source,))
        else:
            cursor = await self.db.conn.execute("""
                SELECT timestamp, source, score
                FROM sentiment_scores
                ORDER BY timestamp
            """)
        sent_rows = await cursor.fetchall()

        # Get prices
        cursor = await self.db.conn.execute("""
            SELECT timestamp, price_usd
            FROM price_data
            WHERE coin = 'BTC'
            ORDER BY timestamp
        """)
        price_rows = await cursor.fetchall()

        price_by_hour = {}
        for ts_str, price in price_rows:
            ts = datetime.fromisoformat(ts_str)
            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            if hour_key not in price_by_hour:
                price_by_hour[hour_key] = []
            price_by_hour[hour_key].append(price)
        price_by_hour = {h: np.mean(p) for h, p in price_by_hour.items()}

        # Track predictions over time
        predictions = []  # (timestamp, correct)

        for ts_str, src, score in sent_rows:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)

            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            future_hour = hour_key + timedelta(hours=4)

            if hour_key not in price_by_hour or future_hour not in price_by_hour:
                continue

            price_change = price_by_hour[future_hour] - price_by_hour[hour_key]
            correct = (score > 0 and price_change > 0) or (score < 0 and price_change < 0)
            predictions.append((ts, correct))

        # Compute learning curve
        learning_curve = []
        cumulative_correct = 0
        recent_correct = []
        alpha, beta = 1.0, 1.0  # Bayesian belief

        for i, (ts, correct) in enumerate(predictions):
            cumulative_correct += int(correct)
            recent_correct.append(int(correct))
            if len(recent_correct) > window:
                recent_correct.pop(0)

            # Update Bayesian belief
            if correct:
                alpha += 1
            else:
                beta += 1

            if (i + 1) % 100 == 0 or i == len(predictions) - 1:
                learning_curve.append(LearningPoint(
                    timestamp=ts,
                    cumulative_accuracy=cumulative_correct / (i + 1),
                    rolling_accuracy=sum(recent_correct) / len(recent_correct),
                    belief_mean=alpha / (alpha + beta),
                    sample_size=i + 1,
                ))

        return learning_curve


def print_learning_report(performances: list[SourcePerformance], learning_curve: list[LearningPoint]):
    """Print formatted learning report."""

    print("\n" + "=" * 70)
    print("BAYESIAN CRAWLER LEARNING ANALYSIS")
    print("=" * 70)

    # Source rankings
    print("\n📊 SOURCE PERFORMANCE RANKINGS")
    print("-" * 70)
    print(f"{'Source':<25} {'Accuracy':<10} {'Utility':<10} {'Belief':<10} {'Samples'}")
    print("-" * 70)

    for p in performances[:15]:
        accuracy_bar = "█" * int(p.accuracy * 10)
        print(f"{p.source:<25} {p.accuracy:>6.1%}     {p.utility_score:>.3f}     {p.belief_mean:>.3f}     {p.total_predictions}")

    # Top sources
    print("\n🏆 TOP SOURCES BY UTILITY")
    print("-" * 70)
    for i, p in enumerate(performances[:5], 1):
        print(f"  {i}. {p.source}")
        print(f"     Accuracy: {p.accuracy:.1%} ({p.correct_predictions}/{p.total_predictions})")
        print(f"     Correlations: 1h={p.correlation_1h:+.3f}, 4h={p.correlation_4h:+.3f}, 24h={p.correlation_24h:+.3f}")
        print(f"     Bayesian belief: Beta({p.alpha:.0f}, {p.beta:.0f}) → mean={p.belief_mean:.3f}")

    # Learning curve
    if learning_curve:
        print("\n📈 LEARNING CURVE")
        print("-" * 70)
        print(f"{'Samples':<10} {'Cumulative Acc':<16} {'Rolling Acc':<14} {'Belief Mean'}")
        print("-" * 70)

        for point in learning_curve:
            trend = "↑" if point.rolling_accuracy > point.cumulative_accuracy else "↓"
            print(f"{point.sample_size:<10} {point.cumulative_accuracy:>10.1%}       {point.rolling_accuracy:>10.1%} {trend}   {point.belief_mean:.3f}")

    # Learning assessment
    print("\n🔍 LEARNING ASSESSMENT")
    print("-" * 70)

    if learning_curve and len(learning_curve) >= 2:
        initial_acc = learning_curve[0].cumulative_accuracy
        final_acc = learning_curve[-1].cumulative_accuracy
        improvement = final_acc - initial_acc

        initial_belief = learning_curve[0].belief_mean
        final_belief = learning_curve[-1].belief_mean
        belief_change = final_belief - initial_belief

        print(f"Initial accuracy: {initial_acc:.1%}")
        print(f"Final accuracy: {final_acc:.1%}")
        print(f"Improvement: {improvement:+.1%}")
        print()
        print(f"Initial belief mean: {initial_belief:.3f}")
        print(f"Final belief mean: {final_belief:.3f}")
        print(f"Belief change: {belief_change:+.3f}")

        if improvement > 0.02:
            print("\n✅ LEARNING DETECTED: Accuracy improving over time")
        elif improvement < -0.02:
            print("\n⚠️ DEGRADATION: Accuracy decreasing (market regime change?)")
        else:
            print("\n➖ STABLE: No significant learning trend detected")

    # Best predictive sources
    print("\n💡 RECOMMENDATIONS")
    print("-" * 70)

    high_accuracy = [p for p in performances if p.accuracy > 0.55]
    if high_accuracy:
        print("Sources with >55% accuracy (better than random):")
        for p in high_accuracy[:5]:
            print(f"  - {p.source}: {p.accuracy:.1%}")
    else:
        print("No sources consistently beat 50% accuracy")
        print("This suggests sentiment alone may not predict price direction")

    high_corr = [p for p in performances if abs(p.correlation_4h) > 0.15]
    if high_corr:
        print("\nSources with significant correlation (|r| > 0.15):")
        for p in sorted(high_corr, key=lambda x: abs(x.correlation_4h), reverse=True)[:5]:
            print(f"  - {p.source}: r={p.correlation_4h:+.3f}")

    print("\n" + "=" * 70)


async def main():
    """Run learning analysis."""
    analyzer = BayesianLearningAnalyzer()
    await analyzer.connect()

    try:
        # Compute source performance
        performances = await analyzer.compute_source_performance(lag_hours=4)

        # Compute overall learning curve
        learning_curve = await analyzer.compute_learning_curve(window=100)

        # Print report
        print_learning_report(performances, learning_curve)

    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
