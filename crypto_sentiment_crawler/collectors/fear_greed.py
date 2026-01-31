"""Fear & Greed Index collector from alternative.me."""

from datetime import datetime, timezone

import httpx

from ..storage.db import Database
from ..storage.models import SentimentRaw, SentimentScore
from .base import BaseCollector

API_URL = "https://api.alternative.me/fng/"


class FearGreedCollector(BaseCollector):
    """Collector for the Crypto Fear & Greed Index."""

    name = "fear_greed"

    def __init__(self, db: Database):
        super().__init__(db)
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def collect(self) -> None:
        """Fetch the Fear & Greed index and store it."""
        response = await self.client.get(API_URL)
        response.raise_for_status()
        data = response.json()

        if "data" not in data or not data["data"]:
            self.logger.warning("No data in Fear & Greed response")
            return

        entry = data["data"][0]
        value = int(entry["value"])
        classification = entry["value_classification"]
        timestamp = datetime.fromtimestamp(int(entry["timestamp"]), tz=timezone.utc)

        # Store raw data
        raw = SentimentRaw(
            timestamp=timestamp,
            source=self.name,
            coin=None,  # Market-wide indicator
            raw_data={
                "value": value,
                "classification": classification,
                "timestamp": entry["timestamp"],
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Normalize to -1 to 1 scale and store as score
        # 0 (Extreme Fear) -> -1, 50 (Neutral) -> 0, 100 (Extreme Greed) -> 1
        normalized_score = (value - 50) / 50

        score = SentimentScore(
            timestamp=timestamp,
            coin="MARKET",  # Market-wide indicator
            source=self.name,
            score=normalized_score,
            confidence=1.0,  # Direct measurement, high confidence
            sample_size=1,
        )
        await self.db.insert_sentiment_score(score)

        self.logger.info(
            f"Fear & Greed: {value} ({classification}) -> normalized: {normalized_score:.2f}"
        )
