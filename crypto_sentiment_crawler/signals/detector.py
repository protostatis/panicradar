"""Contrarian signal detection based on sentiment-price divergence.

Uses multi-dimensional sentiment scoring:
- final_score: Filtered sentiment (excludes bot/scam content)
- explicit_fear_rate: Proportion of segments with literal loss/panic phrases (e.g. "panic sell")
- explicit_euphoria_rate: Proportion of segments with literal moon/FOMO phrases (e.g. "to the moon")
- warning_scam_rate: Proportion of segments with scam alerts and exchange complaints
"""

import statistics
from datetime import datetime, timedelta
from typing import Optional

from .models import Signal, SignalStrength, SignalType


class ContrarianSignalDetector:
    """
    Detects contrarian trading signals based on sentiment-price divergence.

    Key insight from causal analysis:
    - Sentiment LAGS price by ~15 hours (people react to price moves)
    - Extreme sentiment often marks local tops/bottoms
    - Divergence between sentiment and price trend can signal reversals

    Signal Types:
    1. BULLISH_DIVERGENCE: Extreme fear + price stabilizing/rising
       → Crowd is scared but price isn't falling anymore
       → Potential accumulation opportunity

    2. BEARISH_DIVERGENCE: Extreme greed + price stabilizing/falling
       → Crowd is euphoric but price isn't rising anymore
       → Potential distribution warning

    3. CAPITULATION: Extreme negative sentiment spike
       → Panic selling, often marks local bottoms

    4. EUPHORIA: Extreme positive sentiment spike
       → Irrational exuberance, often marks local tops
    """

    # Thresholds (tunable)
    EXTREME_FEAR_THRESHOLD = -0.3  # Sentiment below this = extreme fear
    EXTREME_GREED_THRESHOLD = 0.5  # Sentiment above this = extreme greed
    ZSCORE_EXTREME = 1.5  # Z-score above this = statistically extreme
    PRICE_STABLE_THRESHOLD = 2.0  # Price change % below this = stable

    def __init__(
        self,
        sentiment_history: list[tuple[datetime, float]],
        price_history: list[tuple[datetime, float]],
        lookback_days: int = 30,
    ):
        """
        Initialize detector with historical data.

        Args:
            sentiment_history: List of (timestamp, sentiment_score) tuples
            price_history: List of (timestamp, price) tuples
            lookback_days: Days of history for calculating statistics
        """
        self.sentiment_history = sorted(sentiment_history, key=lambda x: x[0])
        self.price_history = sorted(price_history, key=lambda x: x[0])
        self.lookback_days = lookback_days

        # Calculate baseline statistics
        self._calculate_baselines()

    def _calculate_baselines(self) -> None:
        """Calculate baseline statistics for z-score calculations."""
        cutoff = datetime.now() - timedelta(days=self.lookback_days)

        # Sentiment baseline - handle both timezone-aware and naive datetimes
        def normalize_ts(ts: datetime) -> datetime:
            """Convert to naive datetime for comparison."""
            if ts.tzinfo is not None:
                return ts.replace(tzinfo=None)
            return ts

        recent_sentiments = [s for ts, s in self.sentiment_history if normalize_ts(ts) >= cutoff]
        if len(recent_sentiments) >= 5:
            self.sentiment_mean = statistics.mean(recent_sentiments)
            self.sentiment_std = statistics.stdev(recent_sentiments) or 0.1
        else:
            self.sentiment_mean = 0.0
            self.sentiment_std = 0.3  # Default

        # Price returns baseline
        recent_prices = [(ts, p) for ts, p in self.price_history if normalize_ts(ts) >= cutoff]
        if len(recent_prices) >= 2:
            returns = []
            for i in range(1, len(recent_prices)):
                ret = (recent_prices[i][1] - recent_prices[i - 1][1]) / recent_prices[i - 1][1] * 100
                returns.append(ret)
            self.return_mean = statistics.mean(returns) if returns else 0.0
            self.return_std = statistics.stdev(returns) if len(returns) > 1 else 5.0
        else:
            self.return_mean = 0.0
            self.return_std = 5.0

    def _get_latest_sentiment(self) -> tuple[float, float]:
        """Get latest sentiment and its z-score."""
        if not self.sentiment_history:
            return 0.0, 0.0

        latest = self.sentiment_history[-1][1]
        zscore = (latest - self.sentiment_mean) / self.sentiment_std
        return latest, zscore

    def _get_price_changes(self) -> tuple[float, float, float]:
        """Get price changes: 24h, 7d, and current price."""
        if len(self.price_history) < 2:
            return 0.0, 0.0, 0.0

        current_price = self.price_history[-1][1]
        now = self.price_history[-1][0]

        # Find price 24h ago
        price_24h_ago = current_price
        for ts, p in reversed(self.price_history):
            if now - ts >= timedelta(hours=24):
                price_24h_ago = p
                break

        # Find price 7d ago
        price_7d_ago = current_price
        for ts, p in reversed(self.price_history):
            if now - ts >= timedelta(days=7):
                price_7d_ago = p
                break

        change_24h = (current_price - price_24h_ago) / price_24h_ago * 100 if price_24h_ago else 0
        change_7d = (current_price - price_7d_ago) / price_7d_ago * 100 if price_7d_ago else 0

        return change_24h, change_7d, current_price

    def _calculate_divergence(
        self, sentiment: float, sentiment_zscore: float, price_change_24h: float
    ) -> float:
        """
        Calculate sentiment-price divergence score.

        Returns value between -1 and +1:
        - Positive: Bullish divergence (fear + rising/stable price)
        - Negative: Bearish divergence (greed + falling/stable price)
        - Near 0: No divergence
        """
        # Normalize price change to -1 to +1 scale (assuming ±10% is extreme)
        price_normalized = max(-1, min(1, price_change_24h / 10))

        # Divergence = when sentiment and price move in opposite directions
        # Fear (negative sentiment) + rising price = bullish divergence
        # Greed (positive sentiment) + falling price = bearish divergence
        divergence = -sentiment * price_normalized

        # Weight by how extreme the sentiment is
        extremity_weight = min(1.0, abs(sentiment_zscore) / 2)
        divergence *= (0.5 + 0.5 * extremity_weight)

        return max(-1, min(1, divergence))

    def _determine_signal_strength(
        self, sentiment_zscore: float, divergence: float
    ) -> SignalStrength:
        """Determine signal strength based on metrics."""
        score = abs(sentiment_zscore) * 0.5 + abs(divergence) * 0.5

        if score >= 1.5:
            return SignalStrength.STRONG
        elif score >= 0.8:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK

    def detect(self, coin: str = "BTC", multi_dimensional: Optional[dict] = None) -> Optional[Signal]:
        """
        Detect if current conditions warrant a contrarian signal.

        Args:
            coin: Cryptocurrency symbol
            multi_dimensional: Optional dict with explicit_fear_rate, explicit_euphoria_rate, warning_scam_rate

        Returns Signal if conditions are met, None otherwise.
        """
        sentiment, sentiment_zscore = self._get_latest_sentiment()
        change_24h, change_7d, current_price = self._get_price_changes()
        divergence = self._calculate_divergence(sentiment, sentiment_zscore, change_24h)

        # Extract multi-dimensional signals if provided (accept both old and new keys)
        explicit_fear_rate = 0.0
        explicit_euphoria_rate = 0.0
        warning_scam_rate = 0.0
        if multi_dimensional:
            explicit_fear_rate = multi_dimensional.get('explicit_fear_rate', multi_dimensional.get('fear_index', 0.0))
            explicit_euphoria_rate = multi_dimensional.get('explicit_euphoria_rate', multi_dimensional.get('euphoria_index', 0.0))
            warning_scam_rate = multi_dimensional.get('warning_scam_rate', multi_dimensional.get('activity_level', 0.0))

        signal_type = None
        description = ""
        confidence = 0.0

        # Pre-compute conditions for multi-dimensional signal detection
        fear_condition = (
            sentiment < self.EXTREME_FEAR_THRESHOLD
            and sentiment_zscore < -self.ZSCORE_EXTREME
        ) or explicit_fear_rate > 0.15  # High literal fear phrase ratio

        greed_condition = (
            sentiment > self.EXTREME_GREED_THRESHOLD
            and sentiment_zscore > self.ZSCORE_EXTREME
        ) or explicit_euphoria_rate > 0.15  # High literal euphoria phrase ratio

        # Check for BULLISH DIVERGENCE
        # Extreme fear + price not falling (or rising)
        if (
            fear_condition
            and change_24h > -self.PRICE_STABLE_THRESHOLD
        ):
            signal_type = SignalType.BULLISH_DIVERGENCE
            fear_note = f" Explicit fear phrases: {explicit_fear_rate:.1%}." if explicit_fear_rate > 0.1 else ""
            description = (
                f"Extreme fear detected (sentiment {sentiment:+.2f}, "
                f"{sentiment_zscore:.1f}σ below mean) while price is "
                f"{'rising' if change_24h > 0 else 'stabilizing'} "
                f"({change_24h:+.1f}% 24h).{fear_note} "
                f"Historically, this divergence precedes recoveries."
            )
            # Boost confidence if explicit_fear_rate confirms signal
            confidence = min(0.9, 0.4 + abs(divergence) * 0.5 + explicit_fear_rate * 0.2)

        # Check for BEARISH DIVERGENCE
        # Extreme greed + price not rising (or falling)
        elif (
            greed_condition
            and change_24h < self.PRICE_STABLE_THRESHOLD
        ):
            signal_type = SignalType.BEARISH_DIVERGENCE
            euphoria_note = f" Explicit euphoria phrases: {explicit_euphoria_rate:.1%}." if explicit_euphoria_rate > 0.1 else ""
            description = (
                f"Extreme greed detected (sentiment {sentiment:+.2f}, "
                f"{sentiment_zscore:.1f}σ above mean) while price is "
                f"{'falling' if change_24h < 0 else 'stabilizing'} "
                f"({change_24h:+.1f}% 24h).{euphoria_note} "
                f"Historically, this divergence precedes corrections."
            )
            # Boost confidence if explicit_euphoria_rate confirms signal
            confidence = min(0.9, 0.4 + abs(divergence) * 0.5 + explicit_euphoria_rate * 0.2)

        # Check for CAPITULATION
        # Extremely negative sentiment spike OR high explicit_fear_rate
        elif sentiment_zscore < -2.5 or explicit_fear_rate > 0.25:
            signal_type = SignalType.CAPITULATION
            fear_note = f" Explicit fear phrases: {explicit_fear_rate:.1%}." if explicit_fear_rate > 0.1 else ""
            description = (
                f"Capitulation detected: sentiment at {sentiment:+.2f} "
                f"({sentiment_zscore:.1f}σ, extremely unusual).{fear_note} "
                f"Price {change_24h:+.1f}% 24h, {change_7d:+.1f}% 7d. "
                f"Extreme fear often marks local bottoms."
            )
            confidence = min(0.85, 0.3 + abs(sentiment_zscore) * 0.2 + explicit_fear_rate * 0.3)

        # Check for EUPHORIA
        # Extremely positive sentiment spike OR high explicit_euphoria_rate
        elif sentiment_zscore > 2.5 or explicit_euphoria_rate > 0.25:
            signal_type = SignalType.EUPHORIA
            euphoria_note = f" Explicit euphoria phrases: {explicit_euphoria_rate:.1%}." if explicit_euphoria_rate > 0.1 else ""
            description = (
                f"Euphoria detected: sentiment at {sentiment:+.2f} "
                f"({sentiment_zscore:.1f}σ, extremely unusual).{euphoria_note} "
                f"Price {change_24h:+.1f}% 24h, {change_7d:+.1f}% 7d. "
                f"Extreme greed often marks local tops."
            )
            confidence = min(0.85, 0.3 + abs(sentiment_zscore) * 0.2 + explicit_euphoria_rate * 0.3)

        if signal_type is None:
            return None

        strength = self._determine_signal_strength(sentiment_zscore, divergence)

        return Signal(
            timestamp=datetime.now(),
            signal_type=signal_type,
            strength=strength,
            coin=coin,
            sentiment_score=sentiment,
            sentiment_zscore=sentiment_zscore,
            price_change_24h=change_24h,
            price_change_7d=change_7d,
            divergence_score=divergence,
            description=description,
            confidence=confidence,
        )

    def get_market_summary(self, coin: str = "BTC") -> dict:
        """Get current market sentiment summary without requiring a signal."""
        sentiment, sentiment_zscore = self._get_latest_sentiment()
        change_24h, change_7d, current_price = self._get_price_changes()
        divergence = self._calculate_divergence(sentiment, sentiment_zscore, change_24h)

        # Classify current state
        if sentiment < -0.2:
            sentiment_state = "Fear"
        elif sentiment > 0.3:
            sentiment_state = "Greed"
        else:
            sentiment_state = "Neutral"

        if abs(sentiment_zscore) > 2:
            sentiment_state = f"Extreme {sentiment_state}"

        return {
            "coin": coin,
            "timestamp": datetime.now().isoformat(),
            "current_price": current_price,
            "price_change_24h": change_24h,
            "price_change_7d": change_7d,
            "sentiment_score": sentiment,
            "sentiment_zscore": sentiment_zscore,
            "sentiment_state": sentiment_state,
            "divergence_score": divergence,
            "baseline_stats": {
                "sentiment_mean": self.sentiment_mean,
                "sentiment_std": self.sentiment_std,
                "lookback_days": self.lookback_days,
            },
        }
