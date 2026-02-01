"""Signal detection service that integrates with the crawler database."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..storage.db import Database
from ..analysis.source_weights import load_weights_from_db_sync
from .alerts import AlertManager, TelegramChannel, TelegramBot
from .detector import ContrarianSignalDetector
from .models import Signal

logger = logging.getLogger(__name__)


class SignalService:
    """
    Service that monitors sentiment and price data for contrarian signals.

    Runs periodically, checks for signals, and broadcasts alerts.
    """

    def __init__(
        self,
        db_path: str = "data/sentiment.db",
        check_interval_minutes: int = 60,
        telegram_token: Optional[str] = None,
    ):
        self.db_path = db_path
        self.check_interval = check_interval_minutes * 60  # Convert to seconds
        self.telegram_token = telegram_token

        self.alert_manager = AlertManager()
        self.last_signal: Optional[Signal] = None
        self._running = False

        # Signal cooldown to prevent spam (minimum 6 hours between signals)
        self.signal_cooldown = timedelta(hours=6)
        self._last_signal_time: Optional[datetime] = None

        # Load source weights for weighted aggregation
        self._load_source_weights()

    def _load_source_weights(self):
        """Load source weights from database."""
        try:
            weight_data = load_weights_from_db_sync(self.db_path)
            self.source_weights = weight_data.get("weights", {})
            self.contrarian_sources = weight_data.get("contrarian_sources", set())
            if self.source_weights:
                logger.info(
                    f"Loaded {len(self.source_weights)} source weights "
                    f"({len(self.contrarian_sources)} contrarian)"
                )
        except Exception as e:
            logger.warning(f"Could not load source weights: {e}")
            self.source_weights = {}
            self.contrarian_sources = set()

    async def _load_data(self) -> tuple[list, list]:
        """Load sentiment and price history from database with weighted aggregation."""
        db = Database(Path(self.db_path))
        await db.connect()

        # Get sentiment data with source (last 30 days)
        cutoff = datetime.now() - timedelta(days=30)
        cursor = await db.conn.execute(
            """
            SELECT timestamp, source, score FROM sentiment_scores
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (cutoff.isoformat(),),
        )
        sentiment_rows = await cursor.fetchall()

        # Group by hour with weighted aggregation
        hourly_sentiment = {}
        for ts_str, source, score in sentiment_rows:
            ts = datetime.fromisoformat(ts_str)
            hour_key = ts.replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_sentiment:
                hourly_sentiment[hour_key] = []

            # Get weight for source (default 0.01 for unknown)
            weight = self.source_weights.get(source, 0.01)

            # Invert sentiment for contrarian sources
            if source in self.contrarian_sources:
                score = -score

            hourly_sentiment[hour_key].append((score, weight))

        # Compute weighted average per hour
        sentiment_history = []
        for ts, scores_weights in sorted(hourly_sentiment.items()):
            total_weight = sum(w for _, w in scores_weights)
            if total_weight > 0:
                weighted_avg = sum(s * w for s, w in scores_weights) / total_weight
            else:
                weighted_avg = sum(s for s, _ in scores_weights) / len(scores_weights)
            sentiment_history.append((ts, weighted_avg))

        # Get price data (last 30 days)
        cursor = await db.conn.execute(
            """
            SELECT timestamp, price_usd FROM price_data
            WHERE coin = 'BTC' AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (cutoff.isoformat(),),
        )
        price_rows = await cursor.fetchall()
        price_history = [
            (datetime.fromisoformat(ts_str), price) for ts_str, price in price_rows
        ]

        await db.close()
        return sentiment_history, price_history

    async def check_signals(self) -> Optional[Signal]:
        """Check current conditions for signals."""
        try:
            sentiment_history, price_history = await self._load_data()

            if len(sentiment_history) < 10 or len(price_history) < 24:
                logger.warning("Insufficient data for signal detection")
                return None

            detector = ContrarianSignalDetector(
                sentiment_history=sentiment_history,
                price_history=price_history,
                lookback_days=30,
            )

            signal = detector.detect(coin="BTC")

            if signal:
                # Check cooldown
                if self._last_signal_time:
                    time_since_last = datetime.now() - self._last_signal_time
                    if time_since_last < self.signal_cooldown:
                        logger.info(
                            f"Signal detected but in cooldown "
                            f"({time_since_last.total_seconds() / 3600:.1f}h since last)"
                        )
                        return None

                self._last_signal_time = datetime.now()
                self.last_signal = signal
                logger.info(f"Signal detected: {signal.signal_type.value}")

            return signal

        except Exception as e:
            logger.error(f"Error checking signals: {e}")
            return None

    async def get_market_summary(self) -> dict:
        """Get current market summary without requiring a signal."""
        sentiment_history, price_history = await self._load_data()

        if len(sentiment_history) < 5 or len(price_history) < 2:
            return {"error": "Insufficient data"}

        detector = ContrarianSignalDetector(
            sentiment_history=sentiment_history,
            price_history=price_history,
            lookback_days=30,
        )

        return detector.get_market_summary(coin="BTC")

    async def run_once(self) -> Optional[Signal]:
        """Run signal detection once and broadcast if signal found."""
        signal = await self.check_signals()

        if signal:
            await self.alert_manager.broadcast_signal(signal)

        return signal

    async def run_forever(self, verbose: bool = True) -> None:
        """Run signal detection in a loop."""
        self._running = True
        self._check_count = 0
        logger.info(f"Starting signal service (check every {self.check_interval}s)")

        # Set up Telegram if configured
        if self.telegram_token:
            self.alert_manager.add_channel(
                "telegram", TelegramChannel(self.telegram_token)
            )

        while self._running:
            self._check_count += 1
            try:
                if verbose:
                    await self._run_once_verbose()
                else:
                    await self.run_once()
            except Exception as e:
                logger.error(f"Signal service error: {e}")
                if verbose:
                    print(f"\n❌ Error: {e}")

            await asyncio.sleep(self.check_interval)

    async def _run_once_verbose(self) -> None:
        """Run signal detection once with verbose status output."""
        from datetime import datetime as dt

        timestamp = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'─' * 60}")
        print(f"[{timestamp}] Check #{self._check_count}")
        print(f"{'─' * 60}")

        try:
            summary = await self.get_market_summary()
            if "error" in summary:
                print(f"  ⚠️  {summary['error']}")
                return

            # Price info
            price = summary.get('current_price', 0)
            change_24h = summary.get('price_change_24h', 0)
            change_7d = summary.get('price_change_7d', 0)

            # Sentiment info
            sentiment = summary.get('sentiment_score', 0)
            zscore = summary.get('sentiment_zscore', 0)
            state = summary.get('sentiment_state', 'Unknown')
            divergence = summary.get('divergence_score', 0)

            # Color coding for terminal
            price_color = "\033[32m" if change_24h >= 0 else "\033[31m"
            sent_color = "\033[32m" if sentiment >= 0 else "\033[31m"
            reset = "\033[0m"

            print(f"  💰 BTC: ${price:,.0f}  {price_color}{change_24h:+.1f}% (24h){reset}  {change_7d:+.1f}% (7d)")
            print(f"  📊 Sentiment: {sent_color}{sentiment:+.3f}{reset}  Z-Score: {zscore:+.2f}σ  State: {state}")
            print(f"  📈 Divergence: {divergence:+.3f}")

            # Check for signal
            signal = await self.check_signals()

            if signal:
                print(f"\n  🚨 \033[1;33mSIGNAL: {signal.signal_type.value}\033[0m")
                print(f"     Strength: {signal.strength.value}")
                print(f"     Confidence: {signal.confidence:.0%}")
                print(f"     {signal.description[:80]}...")
                await self.alert_manager.broadcast_signal(signal)
            else:
                print(f"  ✅ No signal - conditions within normal ranges")

        except Exception as e:
            print(f"  ❌ Error: {e}")

    def stop(self) -> None:
        """Stop the service."""
        self._running = False


async def run_signal_check(db_path: str = "data/sentiment.db") -> None:
    """Run a single signal check and print results."""
    service = SignalService(db_path=db_path)

    print("\n" + "=" * 60)
    print("CONTRARIAN SIGNAL CHECK")
    print("=" * 60)

    # Get market summary
    summary = await service.get_market_summary()
    if "error" in summary:
        print(f"\nError: {summary['error']}")
        return

    print(f"\n📊 MARKET SUMMARY ({summary['coin']})")
    print("-" * 40)
    print(f"  Price: ${summary['current_price']:,.0f}")
    print(f"  24h Change: {summary['price_change_24h']:+.1f}%")
    print(f"  7d Change: {summary['price_change_7d']:+.1f}%")
    print()
    print(f"  Sentiment: {summary['sentiment_score']:+.3f}")
    print(f"  Z-Score: {summary['sentiment_zscore']:+.2f}σ")
    print(f"  State: {summary['sentiment_state']}")
    print()
    print(f"  Divergence: {summary['divergence_score']:+.3f}")
    print()
    print(f"  Baseline (30d):")
    print(f"    Mean: {summary['baseline_stats']['sentiment_mean']:+.3f}")
    print(f"    Std: {summary['baseline_stats']['sentiment_std']:.3f}")

    # Check for signals
    signal = await service.check_signals()

    print("\n" + "-" * 40)
    if signal:
        print("\n🚨 SIGNAL DETECTED!")
        print()
        print(signal.format_alert())
    else:
        print("\n✅ No signal at this time.")
        print("   Conditions are within normal ranges.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_signal_check())
