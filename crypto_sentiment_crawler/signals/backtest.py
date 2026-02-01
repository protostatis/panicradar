"""Backtesting framework for contrarian signals."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..storage.db import Database
from .detector import ContrarianSignalDetector
from .models import Signal, SignalType


@dataclass
class Trade:
    """A simulated trade from a signal."""

    entry_time: datetime
    entry_price: float
    signal_type: SignalType
    signal_strength: str
    sentiment_at_entry: float
    sentiment_zscore: float

    # Filled after holding period
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_gain: Optional[float] = None


@dataclass
class BacktestResult:
    """Results from backtesting."""

    # Trade statistics
    total_signals: int
    bullish_signals: int
    bearish_signals: int

    # Performance
    trades: list[Trade]
    avg_return: float
    win_rate: float
    avg_winner: float
    avg_loser: float
    best_trade: float
    worst_trade: float

    # Risk metrics
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float

    # By signal type
    bullish_avg_return: float
    bearish_avg_return: float
    bullish_win_rate: float
    bearish_win_rate: float

    def print_report(self) -> None:
        """Print formatted backtest report."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)

        print(f"\n📊 SIGNAL SUMMARY")
        print("-" * 40)
        print(f"  Total signals: {self.total_signals}")
        print(f"  Bullish: {self.bullish_signals}")
        print(f"  Bearish: {self.bearish_signals}")

        print(f"\n💰 PERFORMANCE")
        print("-" * 40)
        print(f"  Average return: {self.avg_return:+.2f}%")
        print(f"  Win rate: {self.win_rate:.1f}%")
        print(f"  Avg winner: {self.avg_winner:+.2f}%")
        print(f"  Avg loser: {self.avg_loser:+.2f}%")
        print(f"  Best trade: {self.best_trade:+.2f}%")
        print(f"  Worst trade: {self.worst_trade:+.2f}%")

        print(f"\n📈 RISK METRICS")
        print("-" * 40)
        print(f"  Sharpe ratio: {self.sharpe_ratio:.2f}")
        print(f"  Max drawdown: {self.max_drawdown:.2f}%")
        print(f"  Profit factor: {self.profit_factor:.2f}")

        print(f"\n🔍 BY SIGNAL TYPE")
        print("-" * 40)
        print(f"  Bullish avg return: {self.bullish_avg_return:+.2f}%")
        print(f"  Bullish win rate: {self.bullish_win_rate:.1f}%")
        print(f"  Bearish avg return: {self.bearish_avg_return:+.2f}%")
        print(f"  Bearish win rate: {self.bearish_win_rate:.1f}%")

        # Verdict
        print(f"\n{'=' * 60}")
        if self.avg_return > 0 and self.win_rate > 50:
            print("✅ VERDICT: Signal shows positive edge")
        elif self.avg_return > 0:
            print("⚠️  VERDICT: Positive returns but low win rate")
        elif self.win_rate > 50:
            print("⚠️  VERDICT: High win rate but negative avg return")
        else:
            print("❌ VERDICT: No edge detected")
        print("=" * 60)


class Backtester:
    """
    Backtest contrarian signals against historical data.

    Simulates entering trades when signals fire and measures
    forward returns over specified holding periods.
    """

    def __init__(
        self,
        db_path: str = "data/sentiment.db",
        holding_hours: int = 24,
        lookback_days: int = 30,
    ):
        self.db_path = db_path
        self.holding_hours = holding_hours
        self.lookback_days = lookback_days

    async def _load_all_data(self) -> tuple[list, list]:
        """Load all historical sentiment and price data."""
        db = Database(Path(self.db_path))
        await db.connect()

        # Get all sentiment data
        cursor = await db.conn.execute(
            """
            SELECT timestamp, score FROM sentiment_scores
            ORDER BY timestamp ASC
            """
        )
        sentiment_rows = await cursor.fetchall()

        # Group by hour
        hourly_sentiment = {}
        for ts_str, score in sentiment_rows:
            ts = datetime.fromisoformat(ts_str)
            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_sentiment:
                hourly_sentiment[hour_key] = []
            hourly_sentiment[hour_key].append(score)

        sentiment_data = [
            (ts, sum(scores) / len(scores))
            for ts, scores in sorted(hourly_sentiment.items())
        ]

        # Get all price data
        cursor = await db.conn.execute(
            """
            SELECT timestamp, price_usd FROM price_data
            WHERE coin = 'BTC'
            ORDER BY timestamp ASC
            """
        )
        price_rows = await cursor.fetchall()
        price_data = [
            (datetime.fromisoformat(ts_str), price) for ts_str, price in price_rows
        ]

        await db.close()
        return sentiment_data, price_data

    def _find_price_at_time(
        self, price_data: list, target_time: datetime, tolerance_hours: int = 2
    ) -> Optional[float]:
        """Find price closest to target time."""
        best_price = None
        best_diff = timedelta(hours=tolerance_hours)

        for ts, price in price_data:
            # Handle timezone
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)

            diff = abs(ts - target_time)
            if diff < best_diff:
                best_diff = diff
                best_price = price

        return best_price

    def _find_price_range(
        self, price_data: list, start_time: datetime, end_time: datetime
    ) -> tuple[Optional[float], Optional[float]]:
        """Find min and max price in time range."""
        prices_in_range = []

        for ts, price in price_data:
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if start_time <= ts <= end_time:
                prices_in_range.append(price)

        if not prices_in_range:
            return None, None

        return min(prices_in_range), max(prices_in_range)

    async def run(self) -> BacktestResult:
        """Run the backtest."""
        sentiment_data, price_data = await self._load_all_data()

        if len(sentiment_data) < self.lookback_days * 24:
            print(f"Warning: Only {len(sentiment_data)} hours of sentiment data")

        if len(price_data) < self.lookback_days * 24:
            print(f"Warning: Only {len(price_data)} hours of price data")

        trades: list[Trade] = []

        # Slide through time, checking for signals at each point
        # Start after lookback period to have baseline stats
        start_idx = self.lookback_days * 24  # hours

        print(f"Scanning {len(sentiment_data) - start_idx} data points for signals...")

        for i in range(start_idx, len(sentiment_data)):
            current_time = sentiment_data[i][0]

            # Build history up to this point
            history_start = max(0, i - self.lookback_days * 24)
            sentiment_history = sentiment_data[history_start:i + 1]

            # Find corresponding price history
            if current_time.tzinfo is not None:
                current_time_naive = current_time.replace(tzinfo=None)
            else:
                current_time_naive = current_time

            cutoff = current_time_naive - timedelta(days=self.lookback_days)
            price_history = [
                (ts.replace(tzinfo=None) if ts.tzinfo else ts, p)
                for ts, p in price_data
                if (ts.replace(tzinfo=None) if ts.tzinfo else ts) <= current_time_naive
                and (ts.replace(tzinfo=None) if ts.tzinfo else ts) >= cutoff
            ]

            if len(price_history) < 24:
                continue

            # Check for signal
            detector = ContrarianSignalDetector(
                sentiment_history=sentiment_history,
                price_history=price_history,
                lookback_days=self.lookback_days,
            )

            signal = detector.detect(coin="BTC")

            if signal:
                # Get entry price
                entry_price = self._find_price_at_time(price_data, current_time_naive)
                if entry_price is None:
                    continue

                # Get exit price (after holding period)
                exit_time = current_time_naive + timedelta(hours=self.holding_hours)
                exit_price = self._find_price_at_time(price_data, exit_time)

                if exit_price is None:
                    continue  # No exit price available (future data)

                # Calculate return based on signal type
                if signal.signal_type in [SignalType.BULLISH_DIVERGENCE, SignalType.CAPITULATION]:
                    # Long trade
                    return_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    # Short trade (or inverse)
                    return_pct = (entry_price - exit_price) / entry_price * 100

                # Get max drawdown and gain during holding
                min_price, max_price = self._find_price_range(
                    price_data, current_time_naive, exit_time
                )

                if min_price and max_price:
                    if signal.signal_type in [SignalType.BULLISH_DIVERGENCE, SignalType.CAPITULATION]:
                        max_drawdown = (entry_price - min_price) / entry_price * 100
                        max_gain = (max_price - entry_price) / entry_price * 100
                    else:
                        max_drawdown = (max_price - entry_price) / entry_price * 100
                        max_gain = (entry_price - min_price) / entry_price * 100
                else:
                    max_drawdown = 0
                    max_gain = 0

                trade = Trade(
                    entry_time=current_time_naive,
                    entry_price=entry_price,
                    signal_type=signal.signal_type,
                    signal_strength=signal.strength.value,
                    sentiment_at_entry=signal.sentiment_score,
                    sentiment_zscore=signal.sentiment_zscore,
                    exit_time=exit_time,
                    exit_price=exit_price,
                    return_pct=return_pct,
                    max_drawdown=max_drawdown,
                    max_gain=max_gain,
                )
                trades.append(trade)

        # Calculate statistics
        return self._calculate_results(trades)

    def _calculate_results(self, trades: list[Trade]) -> BacktestResult:
        """Calculate backtest statistics."""
        if not trades:
            return BacktestResult(
                total_signals=0,
                bullish_signals=0,
                bearish_signals=0,
                trades=[],
                avg_return=0,
                win_rate=0,
                avg_winner=0,
                avg_loser=0,
                best_trade=0,
                worst_trade=0,
                sharpe_ratio=0,
                max_drawdown=0,
                profit_factor=0,
                bullish_avg_return=0,
                bearish_avg_return=0,
                bullish_win_rate=0,
                bearish_win_rate=0,
            )

        returns = [t.return_pct for t in trades if t.return_pct is not None]
        winners = [r for r in returns if r > 0]
        losers = [r for r in returns if r <= 0]

        bullish_types = [SignalType.BULLISH_DIVERGENCE, SignalType.CAPITULATION]
        bullish_trades = [t for t in trades if t.signal_type in bullish_types]
        bearish_trades = [t for t in trades if t.signal_type not in bullish_types]

        bullish_returns = [t.return_pct for t in bullish_trades if t.return_pct is not None]
        bearish_returns = [t.return_pct for t in bearish_trades if t.return_pct is not None]

        # Sharpe ratio (simplified - assumes risk-free = 0)
        import statistics
        if len(returns) > 1:
            std = statistics.stdev(returns) or 1
            sharpe = (sum(returns) / len(returns)) / std
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        return BacktestResult(
            total_signals=len(trades),
            bullish_signals=len(bullish_trades),
            bearish_signals=len(bearish_trades),
            trades=trades,
            avg_return=sum(returns) / len(returns) if returns else 0,
            win_rate=len(winners) / len(returns) * 100 if returns else 0,
            avg_winner=sum(winners) / len(winners) if winners else 0,
            avg_loser=sum(losers) / len(losers) if losers else 0,
            best_trade=max(returns) if returns else 0,
            worst_trade=min(returns) if returns else 0,
            sharpe_ratio=sharpe,
            max_drawdown=max(t.max_drawdown or 0 for t in trades),
            profit_factor=profit_factor,
            bullish_avg_return=sum(bullish_returns) / len(bullish_returns) if bullish_returns else 0,
            bearish_avg_return=sum(bearish_returns) / len(bearish_returns) if bearish_returns else 0,
            bullish_win_rate=len([r for r in bullish_returns if r > 0]) / len(bullish_returns) * 100 if bullish_returns else 0,
            bearish_win_rate=len([r for r in bearish_returns if r > 0]) / len(bearish_returns) * 100 if bearish_returns else 0,
        )


async def run_backtest(
    db_path: str = "data/sentiment.db",
    holding_hours: int = 24,
) -> None:
    """Run backtest and print results."""
    print("\n" + "=" * 60)
    print("CONTRARIAN SIGNAL BACKTEST")
    print("=" * 60)
    print(f"\nParameters:")
    print(f"  Database: {db_path}")
    print(f"  Holding period: {holding_hours} hours")
    print(f"  Lookback for baseline: 30 days")

    backtester = Backtester(
        db_path=db_path,
        holding_hours=holding_hours,
    )

    result = await backtester.run()
    result.print_report()

    # Print individual trades
    if result.trades:
        print("\n📋 TRADE LOG")
        print("-" * 60)
        print(f"{'Date':<12} {'Type':<20} {'Entry':>10} {'Exit':>10} {'Return':>8}")
        print("-" * 60)
        for t in result.trades[:20]:  # Show first 20
            date_str = t.entry_time.strftime("%Y-%m-%d")
            type_str = t.signal_type.value[:18]
            print(
                f"{date_str:<12} {type_str:<20} "
                f"${t.entry_price:>9,.0f} ${t.exit_price:>9,.0f} "
                f"{t.return_pct:>+7.2f}%"
            )
        if len(result.trades) > 20:
            print(f"... and {len(result.trades) - 20} more trades")


if __name__ == "__main__":
    asyncio.run(run_backtest())
