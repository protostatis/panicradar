"""Signal data models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalType(Enum):
    """Type of contrarian signal."""

    BULLISH_DIVERGENCE = "bullish_divergence"  # Extreme fear + price stabilizing/rising
    BEARISH_DIVERGENCE = "bearish_divergence"  # Extreme greed + price stabilizing/falling
    CAPITULATION = "capitulation"  # Extreme negative sentiment spike
    EUPHORIA = "euphoria"  # Extreme positive sentiment spike


class SignalStrength(Enum):
    """Signal strength level."""

    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


@dataclass
class Signal:
    """A contrarian trading signal."""

    timestamp: datetime
    signal_type: SignalType
    strength: SignalStrength
    coin: str

    # Metrics at signal time
    sentiment_score: float  # Current sentiment (-1 to +1)
    sentiment_zscore: float  # How extreme (std devs from mean)
    price_change_24h: float  # Price change in last 24h (%)
    price_change_7d: float  # Price change in last 7 days (%)

    # Divergence metrics
    divergence_score: float  # Sentiment vs price divergence (-1 to +1)

    # Context
    description: str
    confidence: float  # 0 to 1

    # Optional metadata
    subreddit_breakdown: Optional[dict] = None
    sample_posts: Optional[list] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/API."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "signal_type": self.signal_type.value,
            "strength": self.strength.value,
            "coin": self.coin,
            "sentiment_score": self.sentiment_score,
            "sentiment_zscore": self.sentiment_zscore,
            "price_change_24h": self.price_change_24h,
            "price_change_7d": self.price_change_7d,
            "divergence_score": self.divergence_score,
            "description": self.description,
            "confidence": self.confidence,
            "subreddit_breakdown": self.subreddit_breakdown,
            "sample_posts": self.sample_posts,
        }

    def format_alert(self) -> str:
        """Format signal for alert notification."""
        emoji = {
            SignalType.BULLISH_DIVERGENCE: "🟢",
            SignalType.BEARISH_DIVERGENCE: "🔴",
            SignalType.CAPITULATION: "💀",
            SignalType.EUPHORIA: "🚀",
        }

        strength_emoji = {
            SignalStrength.WEAK: "⚪",
            SignalStrength.MODERATE: "🟡",
            SignalStrength.STRONG: "🔥",
        }

        return f"""
{emoji.get(self.signal_type, "📊")} **{self.signal_type.value.replace('_', ' ').upper()}** {strength_emoji.get(self.strength, "")}

**{self.coin}** | {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}

📉 Sentiment: {self.sentiment_score:+.2f} (z-score: {self.sentiment_zscore:+.1f}σ)
💰 Price 24h: {self.price_change_24h:+.1f}%
📈 Price 7d: {self.price_change_7d:+.1f}%
🔀 Divergence: {self.divergence_score:+.2f}

{self.description}

Confidence: {self.confidence:.0%}
""".strip()
