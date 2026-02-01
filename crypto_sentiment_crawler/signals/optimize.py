"""Optimize signal thresholds through backtesting."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Optional

from ..storage.db import Database
from .models import Signal, SignalStrength, SignalType


@dataclass
class ThresholdConfig:
    """Configuration for signal thresholds."""

    fear_threshold: float  # Sentiment below this = fear
    greed_threshold: float  # Sentiment above this = greed
    zscore_threshold: float  # Z-score magnitude for "extreme"
    price_stable_pct: float  # Price change % considered "stable"
    min_hours_between_signals: int  # Cooldown


@dataclass
class OptimizationResult:
    """Result from testing a threshold configuration."""

    config: ThresholdConfig
    total_signals: int
    avg_return: float
    win_rate: float
    profit_factor: float
    sharpe: float
    max_drawdown: float


class ThresholdOptimizer:
    """Find optimal signal thresholds through grid search."""

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.sentiment_data = []
        self.price_data = []

    async def load_data(self) -> None:
        """Load historical data."""
        db = Database(Path(self.db_path))
        await db.connect()

        # Load sentiment
        cursor = await db.conn.execute(
            "SELECT timestamp, score FROM sentiment_scores ORDER BY timestamp"
        )
        rows = await cursor.fetchall()

        hourly = {}
        for ts_str, score in rows:
            ts = datetime.fromisoformat(ts_str)
            hour = ts.replace(minute=0, second=0, microsecond=0)
            if hour not in hourly:
                hourly[hour] = []
            hourly[hour].append(score)

        self.sentiment_data = [(ts, sum(s) / len(s)) for ts, s in sorted(hourly.items())]

        # Load prices
        cursor = await db.conn.execute(
            "SELECT timestamp, price_usd FROM price_data WHERE coin='BTC' ORDER BY timestamp"
        )
        rows = await cursor.fetchall()
        self.price_data = [(datetime.fromisoformat(ts), p) for ts, p in rows]

        await db.close()
        print(f"Loaded {len(self.sentiment_data)} sentiment hours, {len(self.price_data)} price points")

    def _test_config(
        self, config: ThresholdConfig, holding_hours: int = 24
    ) -> OptimizationResult:
        """Test a single threshold configuration."""
        import statistics

        trades = []
        last_signal_time = None
        lookback = 7 * 24  # 7 days in hours

        for i in range(lookback, len(self.sentiment_data)):
            current_time = self.sentiment_data[i][0]
            if current_time.tzinfo:
                current_time = current_time.replace(tzinfo=None)

            # Cooldown check
            if last_signal_time:
                hours_since = (current_time - last_signal_time).total_seconds() / 3600
                if hours_since < config.min_hours_between_signals:
                    continue

            # Get baseline stats
            recent_sent = [s for _, s in self.sentiment_data[i - lookback : i]]
            if len(recent_sent) < 10:
                continue

            mean = statistics.mean(recent_sent)
            std = statistics.stdev(recent_sent) or 0.1

            current_sent = self.sentiment_data[i][1]
            zscore = (current_sent - mean) / std

            # Get price data
            cutoff = current_time - timedelta(days=1)
            recent_prices = [
                (ts.replace(tzinfo=None) if ts.tzinfo else ts, p)
                for ts, p in self.price_data
                if cutoff <= (ts.replace(tzinfo=None) if ts.tzinfo else ts) <= current_time
            ]

            if len(recent_prices) < 2:
                continue

            current_price = recent_prices[-1][1]
            price_24h_ago = recent_prices[0][1]
            price_change = (current_price - price_24h_ago) / price_24h_ago * 100

            # Check for signals
            signal_type = None

            # Bullish: extreme fear + price not crashing
            if (
                current_sent < config.fear_threshold
                and zscore < -config.zscore_threshold
                and price_change > -config.price_stable_pct
            ):
                signal_type = "bullish"

            # Bearish: extreme greed + price not mooning
            elif (
                current_sent > config.greed_threshold
                and zscore > config.zscore_threshold
                and price_change < config.price_stable_pct
            ):
                signal_type = "bearish"

            # Capitulation: extreme negative spike
            elif zscore < -2.5:
                signal_type = "bullish"

            # Euphoria: extreme positive spike
            elif zscore > 2.5:
                signal_type = "bearish"

            if signal_type is None:
                continue

            last_signal_time = current_time

            # Find exit price
            exit_time = current_time + timedelta(hours=holding_hours)
            exit_price = None
            for ts, p in self.price_data:
                ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
                if abs((ts_naive - exit_time).total_seconds()) < 7200:  # 2h tolerance
                    exit_price = p
                    break

            if exit_price is None:
                continue

            # Calculate return
            if signal_type == "bullish":
                ret = (exit_price - current_price) / current_price * 100
            else:
                ret = (current_price - exit_price) / current_price * 100

            trades.append(ret)

        # Calculate metrics
        if not trades:
            return OptimizationResult(
                config=config,
                total_signals=0,
                avg_return=0,
                win_rate=0,
                profit_factor=0,
                sharpe=0,
                max_drawdown=0,
            )

        winners = [r for r in trades if r > 0]
        losers = [r for r in trades if r <= 0]

        avg_ret = sum(trades) / len(trades)
        win_rate = len(winners) / len(trades) * 100 if trades else 0

        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 1
        pf = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        std = statistics.stdev(trades) if len(trades) > 1 else 1
        sharpe = avg_ret / std if std > 0 else 0

        # Max drawdown (simplified)
        cumulative = 0
        peak = 0
        max_dd = 0
        for r in trades:
            cumulative += r
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        return OptimizationResult(
            config=config,
            total_signals=len(trades),
            avg_return=avg_ret,
            win_rate=win_rate,
            profit_factor=pf,
            sharpe=sharpe,
            max_drawdown=max_dd,
        )

    async def optimize(self) -> list[OptimizationResult]:
        """Run grid search over threshold configurations."""
        await self.load_data()

        # Parameter grid
        fear_values = [-0.2, -0.3, -0.4, -0.5]
        greed_values = [0.4, 0.5, 0.6, 0.7]
        zscore_values = [1.5, 2.0, 2.5]
        stable_values = [2.0, 3.0, 5.0]
        cooldown_values = [6, 12, 24, 48]

        configs = []
        for fear, greed, zs, stable, cd in product(
            fear_values, greed_values, zscore_values, stable_values, cooldown_values
        ):
            configs.append(
                ThresholdConfig(
                    fear_threshold=fear,
                    greed_threshold=greed,
                    zscore_threshold=zs,
                    price_stable_pct=stable,
                    min_hours_between_signals=cd,
                )
            )

        print(f"Testing {len(configs)} configurations...")

        results = []
        for i, config in enumerate(configs):
            result = self._test_config(config)
            results.append(result)

            if (i + 1) % 100 == 0:
                print(f"  Tested {i + 1}/{len(configs)}")

        # Sort by Sharpe ratio (risk-adjusted return)
        results.sort(key=lambda r: r.sharpe, reverse=True)
        return results


async def run_optimization():
    """Run the optimization and print results."""
    print("=" * 70)
    print("THRESHOLD OPTIMIZATION")
    print("=" * 70)

    optimizer = ThresholdOptimizer()
    results = await optimizer.optimize()

    print("\n" + "=" * 70)
    print("TOP 10 CONFIGURATIONS (by Sharpe Ratio)")
    print("=" * 70)
    print(
        f"{'Fear':>6} {'Greed':>6} {'ZScore':>7} {'Stable':>7} {'Cooldown':>8} | "
        f"{'Signals':>7} {'AvgRet':>7} {'WinRate':>8} {'Sharpe':>7} {'PF':>6}"
    )
    print("-" * 70)

    for r in results[:10]:
        c = r.config
        print(
            f"{c.fear_threshold:>6.1f} {c.greed_threshold:>6.1f} "
            f"{c.zscore_threshold:>7.1f} {c.price_stable_pct:>7.1f} "
            f"{c.min_hours_between_signals:>8} | "
            f"{r.total_signals:>7} {r.avg_return:>+6.2f}% "
            f"{r.win_rate:>7.1f}% {r.sharpe:>7.2f} {r.profit_factor:>6.2f}"
        )

    # Show best config details
    best = results[0]
    print("\n" + "=" * 70)
    print("BEST CONFIGURATION")
    print("=" * 70)
    print(f"Fear threshold: {best.config.fear_threshold}")
    print(f"Greed threshold: {best.config.greed_threshold}")
    print(f"Z-score threshold: {best.config.zscore_threshold}")
    print(f"Price stable %: {best.config.price_stable_pct}")
    print(f"Cooldown hours: {best.config.min_hours_between_signals}")
    print()
    print(f"Total signals: {best.total_signals}")
    print(f"Average return: {best.avg_return:+.2f}%")
    print(f"Win rate: {best.win_rate:.1f}%")
    print(f"Sharpe ratio: {best.sharpe:.2f}")
    print(f"Profit factor: {best.profit_factor:.2f}")

    # Filter for minimum signal count
    print("\n" + "=" * 70)
    print("TOP 5 WITH >= 10 SIGNALS")
    print("=" * 70)
    filtered = [r for r in results if r.total_signals >= 10]
    for r in filtered[:5]:
        c = r.config
        print(
            f"Fear={c.fear_threshold:.1f} Greed={c.greed_threshold:.1f} "
            f"Z={c.zscore_threshold:.1f} Stable={c.price_stable_pct:.0f}% "
            f"CD={c.min_hours_between_signals}h | "
            f"n={r.total_signals} ret={r.avg_return:+.2f}% "
            f"win={r.win_rate:.0f}% sharpe={r.sharpe:.2f}"
        )


if __name__ == "__main__":
    asyncio.run(run_optimization())
