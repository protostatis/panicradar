"""
Stocktwits backfill for crypto sentiment data.

Stocktwits has crypto symbols with community sentiment.
Uses their public web pages (no API key needed).

Symbols use $ prefix: $BTC.X, $ETH.X, etc.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from .crawler.fetcher import Fetcher
from .logging_config import logger
from .processing.sentiment import sentiment_analyzer
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# Crypto symbols on Stocktwits (use .X suffix for crypto)
CRYPTO_SYMBOLS = [
    {"symbol": "BTC.X", "coin": "BTC", "name": "Bitcoin"},
    {"symbol": "ETH.X", "coin": "ETH", "name": "Ethereum"},
    {"symbol": "SOL.X", "coin": "SOL", "name": "Solana"},
    {"symbol": "XRP.X", "coin": "XRP", "name": "Ripple"},
    {"symbol": "ADA.X", "coin": "ADA", "name": "Cardano"},
    {"symbol": "DOGE.X", "coin": "DOGE", "name": "Dogecoin"},
    {"symbol": "DOT.X", "coin": "DOT", "name": "Polkadot"},
    {"symbol": "AVAX.X", "coin": "AVAX", "name": "Avalanche"},
    {"symbol": "LINK.X", "coin": "LINK", "name": "Chainlink"},
    {"symbol": "MATIC.X", "coin": "MATIC", "name": "Polygon"},
    {"symbol": "LTC.X", "coin": "LTC", "name": "Litecoin"},
    {"symbol": "SHIB.X", "coin": "SHIB", "name": "Shiba Inu"},
    {"symbol": "UNI.X", "coin": "UNI", "name": "Uniswap"},
    {"symbol": "ATOM.X", "coin": "ATOM", "name": "Cosmos"},
    {"symbol": "FTM.X", "coin": "FTM", "name": "Fantom"},
]

# Stocktwits URLs
SYMBOL_URL = "https://stocktwits.com/symbol/{symbol}"
API_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

# Rate limiting
RATE_LIMIT_DELAY = 2.0
MAX_MESSAGES_PER_SYMBOL = 100


class StocktwitsBackfiller:
    """Backfill Stocktwits data for crypto sentiment."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.stats = {
            "messages_fetched": 0,
            "messages_stored": 0,
            "symbols_scraped": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher."""
        self.fetcher = Fetcher(
            default_rate_limit=0.5,
            timeout=30.0,
            randomize_delay=True,
            delay_range=(1.0, 3.0),
        )
        await self.fetcher.start()
        logger.info("Stocktwits backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("Stocktwits backfiller shutdown complete")

    async def fetch_symbol_messages(self, symbol: str, coin: str) -> list[dict]:
        """Fetch messages for a crypto symbol."""
        # Try the public API first
        url = API_URL.format(symbol=symbol)

        result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

        if result.success:
            try:
                data = json.loads(result.content)
                messages = data.get("messages", [])

                parsed = []
                for msg in messages[:MAX_MESSAGES_PER_SYMBOL]:
                    # Extract sentiment label if available
                    sentiment_label = None
                    if msg.get("entities", {}).get("sentiment"):
                        sentiment_label = msg["entities"]["sentiment"].get("basic")

                    # Parse timestamp
                    timestamp = datetime.now(timezone.utc)
                    created = msg.get("created_at", "")
                    if created:
                        try:
                            timestamp = datetime.fromisoformat(
                                created.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass

                    parsed.append({
                        "id": msg.get("id"),
                        "body": msg.get("body", ""),
                        "username": msg.get("user", {}).get("username", "unknown"),
                        "timestamp": timestamp,
                        "sentiment_label": sentiment_label,  # "Bullish", "Bearish", or None
                        "likes": msg.get("likes", {}).get("total", 0),
                        "coin": coin,
                        "symbol": symbol,
                    })

                self.stats["messages_fetched"] += len(parsed)
                return parsed

            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse API response: {e}")

        # Fall back to HTML scraping
        return await self._scrape_symbol_page(symbol, coin)

    async def _scrape_symbol_page(self, symbol: str, coin: str) -> list[dict]:
        """Scrape messages from Stocktwits web page."""
        url = SYMBOL_URL.format(symbol=symbol)

        result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            logger.warning(f"Failed to fetch {symbol}: {result.error}")
            return []

        messages = []
        soup = BeautifulSoup(result.content, "lxml")

        # Find message containers (Stocktwits uses React, so check for data)
        for script in soup.select("script"):
            text = script.string or ""
            if "window.__initialState" in text or "messages" in text:
                # Try to extract JSON from script
                try:
                    # Look for JSON data
                    json_match = re.search(r'\{.*"messages":\s*\[.*\].*\}', text, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                        for msg in data.get("messages", [])[:MAX_MESSAGES_PER_SYMBOL]:
                            messages.append({
                                "id": msg.get("id"),
                                "body": msg.get("body", ""),
                                "username": msg.get("user", {}).get("username", "unknown"),
                                "timestamp": datetime.now(timezone.utc),
                                "sentiment_label": None,
                                "likes": 0,
                                "coin": coin,
                                "symbol": symbol,
                            })
                except (json.JSONDecodeError, AttributeError):
                    continue

        # Also try to parse visible message elements
        for msg_div in soup.select("article, div[class*='message'], div[class*='Message']"):
            try:
                body = msg_div.get_text(strip=True)
                if len(body) > 10:
                    messages.append({
                        "id": None,
                        "body": body[:500],
                        "username": "unknown",
                        "timestamp": datetime.now(timezone.utc),
                        "sentiment_label": None,
                        "likes": 0,
                        "coin": coin,
                        "symbol": symbol,
                    })
            except Exception:
                continue

        self.stats["messages_fetched"] += len(messages)
        return messages

    async def store_message(self, msg: dict) -> None:
        """Store a Stocktwits message to the database."""
        body = msg["body"]
        if not body or len(body) < 5:
            return

        # Get sentiment - use label if available, otherwise analyze text
        if msg["sentiment_label"] == "Bullish":
            score = 0.7
        elif msg["sentiment_label"] == "Bearish":
            score = -0.7
        else:
            sentiment = sentiment_analyzer.analyze(body)
            score = sentiment["compound"]

        # Build URL for deduplication
        msg_url = f"https://stocktwits.com/symbol/{msg['symbol']}/{msg['id'] or 'post'}"

        # Store raw
        raw = SentimentRaw(
            timestamp=msg["timestamp"],
            source="stocktwits",
            coin=msg["coin"],
            raw_data={
                "url": msg_url,
                "title": body[:100],
                "text": body[:1000],
                "username": msg["username"],
                "symbol": msg["symbol"],
                "sentiment_label": msg["sentiment_label"],
                "likes": msg["likes"],
                "backfill": True,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment score
        confidence = 0.8 if msg["sentiment_label"] else 0.5

        sentiment_score = SentimentScore(
            timestamp=msg["timestamp"],
            coin=msg["coin"],
            source="stocktwits",
            score=max(-1.0, min(1.0, score)),
            confidence=confidence,
            sample_size=1,
        )
        await self.db.insert_sentiment_score(sentiment_score)

        self.stats["messages_stored"] += 1

    async def backfill_symbol(self, symbol_info: dict) -> int:
        """Backfill messages for a single symbol."""
        symbol = symbol_info["symbol"]
        coin = symbol_info["coin"]
        name = symbol_info["name"]

        logger.info(f"Fetching ${symbol} ({name})...")

        messages = await self.fetch_symbol_messages(symbol, coin)
        stored = 0

        for msg in messages:
            try:
                await self.store_message(msg)
                stored += 1
            except Exception as e:
                logger.debug(f"Error storing message: {e}")
                self.stats["errors"] += 1

        self.stats["symbols_scraped"] += 1
        logger.info(f"  ${symbol}: {stored} messages")
        return stored

    async def run_full_backfill(self) -> dict:
        """Run complete Stocktwits backfill."""
        logger.info("=" * 60)
        logger.info("STARTING STOCKTWITS BACKFILL")
        logger.info(f"Symbols to fetch: {len(CRYPTO_SYMBOLS)}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        for symbol_info in CRYPTO_SYMBOLS:
            try:
                await self.backfill_symbol(symbol_info)
                await asyncio.sleep(3)  # Pause between symbols
            except Exception as e:
                logger.error(f"Error on {symbol_info['symbol']}: {e}")
                self.stats["errors"] += 1

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("STOCKTWITS BACKFILL COMPLETE")
        logger.info(f"  Symbols scraped: {self.stats['symbols_scraped']}")
        logger.info(f"  Messages fetched: {self.stats['messages_fetched']}")
        logger.info(f"  Messages stored: {self.stats['messages_stored']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_stocktwits_backfill() -> dict:
    """Main entry point for Stocktwits backfill."""
    db = Database()
    await db.connect()

    backfiller = StocktwitsBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_stocktwits_backfill())
