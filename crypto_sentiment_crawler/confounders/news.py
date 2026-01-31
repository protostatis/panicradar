"""
News confounder data collection.

Uses CryptoPanic API for crypto news sentiment.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from ..logging_config import logger


class NewsCollector:
    """
    Collects crypto news data from multiple sources.

    Primary: CoinGecko trending/news (free, no auth)
    Fallback: CryptoPanic (requires API key)
    """

    # CoinGecko status updates (free)
    COINGECKO_STATUS_URL = "https://api.coingecko.com/api/v3/status_updates"
    # CryptoPanic (requires auth token)
    CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"

    def __init__(self, api_key: str | None = None):
        """
        Initialize news collector.

        Args:
            api_key: Optional CryptoPanic API key.
        """
        self.api_key = api_key
        self.client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    async def fetch_coingecko_updates(self, hours: int = 1) -> dict[str, Any]:
        """
        Fetch recent status updates from CoinGecko (free, no auth).

        Returns news-like updates from crypto projects.
        """
        if not self.client:
            await self.start()

        try:
            params = {"per_page": 50}
            response = await self.client.get(self.COINGECKO_STATUS_URL, params=params)

            if response.status_code == 429:
                logger.debug("CoinGecko rate limited")
                return {"count": 0, "rate_limited": True}

            response.raise_for_status()
            data = response.json()

            updates = data.get("status_updates", [])

            # Filter by time
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            recent = []

            for item in updates:
                created = item.get("created_at")
                if created:
                    try:
                        item_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if item_time >= cutoff:
                            recent.append(item)
                    except (ValueError, TypeError):
                        continue

            # Analyze content
            has_btc = False
            has_eth = False
            categories = set()

            for item in recent:
                desc = (item.get("description") or "").lower()
                title = (item.get("project", {}).get("name") or "").lower()
                full_text = f"{title} {desc}"

                if "bitcoin" in full_text or "btc" in full_text:
                    has_btc = True
                if "ethereum" in full_text or "eth" in full_text:
                    has_eth = True

                cat = item.get("category")
                if cat:
                    categories.add(cat)

            return {
                "count": len(recent),
                "sentiment_avg": 0.0,  # CoinGecko doesn't provide sentiment
                "has_btc": has_btc,
                "has_eth": has_eth,
                "categories": list(categories),
                "items": recent,
            }

        except Exception as e:
            logger.debug(f"CoinGecko status updates error: {e}")
            return {"error": str(e), "count": 0}

    async def fetch_cryptopanic(self, hours: int = 1) -> dict[str, Any]:
        """
        Fetch from CryptoPanic (requires API key).
        """
        if not self.api_key:
            return {"count": 0, "error": "No API key"}

        if not self.client:
            await self.start()

        try:
            params = {"auth_token": self.api_key, "public": "true"}
            response = await self.client.get(self.CRYPTOPANIC_URL, params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])

            # Filter by time
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            recent = []

            for item in results:
                pub_date = item.get("published_at")
                if pub_date:
                    try:
                        item_time = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        if item_time >= cutoff:
                            recent.append(item)
                    except (ValueError, TypeError):
                        continue

            # Calculate metrics
            sentiment_values = []
            categories = set()
            has_btc = False
            has_eth = False

            for item in recent:
                votes = item.get("votes", {})
                positive = votes.get("positive", 0)
                negative = votes.get("negative", 0)
                total_votes = positive + negative

                if total_votes > 0:
                    sentiment = (positive - negative) / total_votes
                    sentiment_values.append(sentiment)

                kind = item.get("kind")
                if kind:
                    categories.add(kind)

                for curr in item.get("currencies", []):
                    code = curr.get("code", "").upper()
                    if code == "BTC":
                        has_btc = True
                    elif code == "ETH":
                        has_eth = True

            sentiment_avg = sum(sentiment_values) / len(sentiment_values) if sentiment_values else 0.0

            return {
                "count": len(recent),
                "sentiment_avg": sentiment_avg,
                "has_btc": has_btc,
                "has_eth": has_eth,
                "categories": list(categories),
                "items": recent,
            }

        except Exception as e:
            logger.debug(f"CryptoPanic error: {e}")
            return {"error": str(e), "count": 0}

    async def fetch_recent_news(self, hours: int = 1, currencies: list[str] | None = None) -> dict[str, Any]:
        """
        Fetch recent crypto news from available sources.

        Tries CoinGecko first (free), then CryptoPanic (if API key available).
        """
        # Try CoinGecko first (free)
        result = await self.fetch_coingecko_updates(hours)

        if result.get("count", 0) > 0 or not result.get("error"):
            return result

        # Fallback to CryptoPanic if we have an API key
        if self.api_key:
            return await self.fetch_cryptopanic(hours)

        # Return empty result if all sources fail
        return {
            "count": 0,
            "sentiment_avg": 0.0,
            "has_btc": False,
            "has_eth": False,
            "categories": [],
            "items": [],
        }

    async def collect(self) -> dict[str, Any]:
        """
        Collect all news proxy variables.

        Returns:
            Dict with news confounder data.
        """
        data = await self.fetch_recent_news(hours=1)

        return {
            "news_count_1h": data.get("count", 0),
            "news_sentiment_avg": data.get("sentiment_avg", 0.0),
            "news_has_btc": data.get("has_btc", False),
            "news_has_eth": data.get("has_eth", False),
            "news_categories": data.get("categories", []),
            "error": data.get("error"),
        }


async def test_news_collector():
    """Test the news collector."""
    collector = NewsCollector()
    await collector.start()

    try:
        data = await collector.collect()
        print("News Confounder Data:")
        print(f"  Count (1h): {data['news_count_1h']}")
        print(f"  Sentiment: {data['news_sentiment_avg']:.3f}")
        print(f"  Has BTC: {data['news_has_btc']}")
        print(f"  Has ETH: {data['news_has_eth']}")
        print(f"  Categories: {data['news_categories']}")
        if data.get("error"):
            print(f"  Error: {data['error']}")
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(test_news_collector())
