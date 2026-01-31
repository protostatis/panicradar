"""
Inference module: Analyze sentiment data and predict price movements.

Uses collected sentiment signals to infer price direction for the next 4 hours.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .logging_config import logger


@dataclass
class SentimentSignal:
    """Aggregated sentiment signal."""

    source: str
    coin: str
    score: float
    confidence: float
    sample_size: int
    timestamp: datetime


@dataclass
class PricePoint:
    """Price data point."""

    coin: str
    price: float
    volume: float
    timestamp: datetime


@dataclass
class PredictionResult:
    """Price movement prediction."""

    coin: str
    current_price: float
    predicted_direction: str  # 'up', 'down', 'neutral'
    confidence: float
    sentiment_score: float
    signals: dict
    reasoning: str
    timestamp: datetime


class SentimentAnalyzer:
    """Analyze sentiment data and compute aggregate signals."""

    # Source weights based on expected informativeness
    SOURCE_WEIGHTS = {
        "fear_greed": 0.25,        # Market-wide baseline
        "reddit_cryptocurrency": 0.20,
        "reddit_bitcoin": 0.15,
        "reddit_ethereum": 0.15,
        "reddit_solana": 0.10,
        "reddit_altcoin": 0.05,
        "coindesk": 0.05,
        "cointelegraph": 0.05,
    }

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_recent_sentiment(
        self,
        hours: int = 4,
        coin: str | None = None,
    ) -> pd.DataFrame:
        """Get recent sentiment scores."""
        conn = self.get_connection()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Get recent sentiment, but always include fear_greed (may be older)
        query = """
            SELECT source, coin, score, confidence, sample_size, timestamp
            FROM sentiment_scores
            WHERE (timestamp >= ? OR source = 'fear_greed')
        """
        params = [cutoff]

        if coin:
            query += " AND (coin = ? OR coin = 'MARKET')"
            params.append(coin)

        query += " ORDER BY timestamp DESC"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df

    def get_latest_fear_greed(self) -> float:
        """Get the most recent Fear & Greed score."""
        conn = self.get_connection()
        row = conn.execute("""
            SELECT score FROM sentiment_scores
            WHERE source = 'fear_greed'
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        conn.close()
        return row[0] if row else 0.0

    def get_recent_prices(self, hours: int = 4, coin: str = "BTC") -> pd.DataFrame:
        """Get recent price data."""
        conn = self.get_connection()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        query = """
            SELECT coin, price_usd, volume_24h, timestamp
            FROM price_data
            WHERE coin = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """

        df = pd.read_sql_query(query, conn, params=[coin, cutoff])
        conn.close()

        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df

    def compute_aggregate_sentiment(
        self,
        hours: int = 4,
        coin: str = "BTC",
    ) -> dict:
        """
        Compute weighted aggregate sentiment score.

        Returns dict with:
        - composite_score: weighted average (-1 to 1)
        - by_source: individual source scores
        - confidence: based on sample size and agreement
        - signal_strength: absolute value of composite
        """
        df = self.get_recent_sentiment(hours=hours, coin=coin)

        if df.empty:
            return {
                "composite_score": 0.0,
                "by_source": {},
                "confidence": 0.0,
                "signal_strength": 0.0,
                "n_sources": 0,
            }

        # Group by source, take most recent or average
        by_source = {}
        for source in df["source"].unique():
            source_df = df[df["source"] == source]
            avg_score = source_df["score"].mean()
            by_source[source] = {
                "score": avg_score,
                "n": len(source_df),
                "weight": self.SOURCE_WEIGHTS.get(source, 0.05),
            }

        # Compute weighted average
        total_weight = 0
        weighted_sum = 0

        for source, data in by_source.items():
            weight = data["weight"]
            weighted_sum += data["score"] * weight
            total_weight += weight

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Compute confidence based on:
        # 1. Number of sources
        # 2. Agreement between sources (low variance = high confidence)
        scores = [d["score"] for d in by_source.values()]
        n_sources = len(scores)

        if n_sources > 1:
            score_std = np.std(scores)
            agreement = 1.0 - min(score_std, 1.0)  # Lower std = higher agreement
        else:
            agreement = 0.5

        confidence = min(1.0, (n_sources / 5) * 0.5 + agreement * 0.5)

        return {
            "composite_score": composite,
            "by_source": by_source,
            "confidence": confidence,
            "signal_strength": abs(composite),
            "n_sources": n_sources,
        }

    def compute_price_momentum(self, hours: int = 4, coin: str = "BTC") -> dict:
        """Compute price momentum indicators."""
        df = self.get_recent_prices(hours=hours, coin=coin)

        if len(df) < 2:
            return {
                "price_change_pct": 0.0,
                "direction": "neutral",
                "volatility": 0.0,
                "current_price": df["price_usd"].iloc[-1] if len(df) > 0 else 0.0,
            }

        prices = df["price_usd"].values
        current = prices[-1]
        start = prices[0]

        change_pct = ((current - start) / start) * 100
        volatility = np.std(np.diff(prices) / prices[:-1]) * 100 if len(prices) > 1 else 0

        if change_pct > 0.5:
            direction = "up"
        elif change_pct < -0.5:
            direction = "down"
        else:
            direction = "neutral"

        return {
            "price_change_pct": change_pct,
            "direction": direction,
            "volatility": volatility,
            "current_price": current,
            "start_price": start,
            "n_points": len(prices),
        }


class PricePredictor:
    """Predict price movements based on sentiment signals."""

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.analyzer = SentimentAnalyzer(db_path)

    def predict(
        self,
        coin: str = "BTC",
        horizon_hours: int = 4,
        lookback_hours: int = 4,
    ) -> PredictionResult:
        """
        Predict price direction for the next horizon_hours.

        Uses:
        - Recent sentiment signals
        - Price momentum
        - Fear & Greed index
        - Source agreement

        Returns PredictionResult with direction, confidence, and reasoning.
        """
        # Get sentiment
        sentiment = self.analyzer.compute_aggregate_sentiment(
            hours=lookback_hours,
            coin=coin,
        )

        # Get price momentum
        momentum = self.analyzer.compute_price_momentum(
            hours=lookback_hours,
            coin=coin,
        )

        # Build prediction
        composite = sentiment["composite_score"]
        confidence = sentiment["confidence"]
        signal_strength = sentiment["signal_strength"]

        # Decision logic
        reasoning_parts = []

        # 1. Sentiment direction
        if composite > 0.2:
            sent_direction = "bullish"
            reasoning_parts.append(f"Sentiment is bullish ({composite:+.3f})")
        elif composite < -0.2:
            sent_direction = "bearish"
            reasoning_parts.append(f"Sentiment is bearish ({composite:+.3f})")
        else:
            sent_direction = "neutral"
            reasoning_parts.append(f"Sentiment is neutral ({composite:+.3f})")

        # 2. Fear & Greed context
        fear_greed = sentiment["by_source"].get("fear_greed", {}).get("score", 0)
        if fear_greed < -0.4:
            reasoning_parts.append(f"Market in Extreme Fear ({fear_greed:.2f}) - contrarian bullish signal")
            # Extreme fear can be contrarian bullish
            contrarian_boost = 0.1
        elif fear_greed > 0.4:
            reasoning_parts.append(f"Market in Extreme Greed ({fear_greed:.2f}) - contrarian bearish signal")
            contrarian_boost = -0.1
        else:
            contrarian_boost = 0

        # 3. Price momentum alignment
        if momentum["direction"] == "up" and sent_direction == "bullish":
            reasoning_parts.append("Price momentum confirms bullish sentiment")
            momentum_factor = 1.2
        elif momentum["direction"] == "down" and sent_direction == "bearish":
            reasoning_parts.append("Price momentum confirms bearish sentiment")
            momentum_factor = 1.2
        elif momentum["direction"] != "neutral" and sent_direction != "neutral":
            reasoning_parts.append(f"Sentiment diverges from price momentum ({momentum['direction']})")
            momentum_factor = 0.8
        else:
            momentum_factor = 1.0

        # 4. Compute final prediction
        adjusted_score = (composite + contrarian_boost) * momentum_factor
        adjusted_confidence = confidence * momentum_factor

        if adjusted_score > 0.15:
            predicted_direction = "up"
        elif adjusted_score < -0.15:
            predicted_direction = "down"
        else:
            predicted_direction = "neutral"

        # 5. Adjust confidence based on signal strength
        if signal_strength < 0.1:
            reasoning_parts.append("Weak signal strength - low confidence")
            adjusted_confidence *= 0.5

        reasoning = ". ".join(reasoning_parts) + "."

        return PredictionResult(
            coin=coin,
            current_price=momentum["current_price"],
            predicted_direction=predicted_direction,
            confidence=min(1.0, adjusted_confidence),
            sentiment_score=composite,
            signals={
                "sentiment": sentiment,
                "momentum": momentum,
                "adjusted_score": adjusted_score,
                "contrarian_boost": contrarian_boost,
            },
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
        )

    def predict_all_coins(
        self,
        coins: list[str] = ["BTC", "ETH", "SOL"],
        horizon_hours: int = 4,
    ) -> dict[str, PredictionResult]:
        """Predict for multiple coins."""
        return {coin: self.predict(coin, horizon_hours) for coin in coins}


def run_inference(lookback_hours: int = 4, horizon_hours: int = 4) -> dict:
    """
    Run inference and print results.

    Returns dict with predictions and analysis.
    """
    predictor = PricePredictor()

    print("=" * 70)
    print("CRYPTO SENTIMENT INFERENCE")
    print(f"Lookback: {lookback_hours}h | Prediction Horizon: {horizon_hours}h")
    print("=" * 70)

    results = {}

    for coin in ["BTC", "ETH", "SOL"]:
        prediction = predictor.predict(
            coin=coin,
            horizon_hours=horizon_hours,
            lookback_hours=lookback_hours,
        )
        results[coin] = prediction

        # Direction emoji
        if prediction.predicted_direction == "up":
            arrow = "📈"
        elif prediction.predicted_direction == "down":
            arrow = "📉"
        else:
            arrow = "➡️"

        # Confidence bar
        conf_bars = "█" * int(prediction.confidence * 10)
        conf_empty = "░" * (10 - int(prediction.confidence * 10))

        print(f"\n{coin} {arrow}")
        print("-" * 50)
        print(f"  Current Price:  ${prediction.current_price:,.2f}")
        print(f"  Prediction:     {prediction.predicted_direction.upper()}")
        print(f"  Confidence:     [{conf_bars}{conf_empty}] {prediction.confidence:.0%}")
        print(f"  Sentiment:      {prediction.sentiment_score:+.3f}")
        print(f"  Reasoning:      {prediction.reasoning}")

    # Aggregate market view
    print("\n" + "=" * 70)
    print("MARKET SUMMARY")
    print("=" * 70)

    bullish = sum(1 for r in results.values() if r.predicted_direction == "up")
    bearish = sum(1 for r in results.values() if r.predicted_direction == "down")

    if bullish > bearish:
        market_view = "BULLISH"
        emoji = "🟢"
    elif bearish > bullish:
        market_view = "BEARISH"
        emoji = "🔴"
    else:
        market_view = "NEUTRAL"
        emoji = "🟡"

    avg_sentiment = np.mean([r.sentiment_score for r in results.values()])
    avg_confidence = np.mean([r.confidence for r in results.values()])

    print(f"\n  Market View:      {emoji} {market_view}")
    print(f"  Avg Sentiment:    {avg_sentiment:+.3f}")
    print(f"  Avg Confidence:   {avg_confidence:.0%}")
    print(f"  Bullish Signals:  {bullish}/3")
    print(f"  Bearish Signals:  {bearish}/3")

    # Fear & Greed context
    analyzer = SentimentAnalyzer()
    sentiment = analyzer.compute_aggregate_sentiment(hours=lookback_hours)
    fg = sentiment["by_source"].get("fear_greed", {}).get("score", 0)

    if fg < -0.4:
        fg_label = "EXTREME FEAR"
        fg_note = "(historically a buying opportunity)"
    elif fg < -0.2:
        fg_label = "FEAR"
        fg_note = ""
    elif fg > 0.4:
        fg_label = "EXTREME GREED"
        fg_note = "(historically a selling signal)"
    elif fg > 0.2:
        fg_label = "GREED"
        fg_note = ""
    else:
        fg_label = "NEUTRAL"
        fg_note = ""

    print(f"\n  Fear & Greed:     {fg:+.2f} ({fg_label}) {fg_note}")

    print("\n" + "=" * 70)

    return {
        "predictions": {coin: {
            "direction": r.predicted_direction,
            "confidence": r.confidence,
            "sentiment": r.sentiment_score,
            "price": r.current_price,
        } for coin, r in results.items()},
        "market_view": market_view,
        "avg_sentiment": avg_sentiment,
        "fear_greed": fg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    run_inference()
