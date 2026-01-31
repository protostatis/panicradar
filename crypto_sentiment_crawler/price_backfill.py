"""
Backfill historical price data from CryptoCompare.

Fetches hourly prices for the past 30+ days.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import httpx

from .logging_config import logger
from .storage.db import Database
from .storage.models import PriceData


# Coin symbols
COINS = ["BTC", "ETH", "SOL"]

# CryptoCompare API (free tier - no key needed for basic endpoints)
CRYPTOCOMPARE_API = "https://min-api.cryptocompare.com/data/v2"


class PriceBackfiller:
    """Backfill historical price data."""

    def __init__(self, db: Database):
        self.db = db
        self.client: httpx.AsyncClient | None = None
        self.stats = {
            "prices_fetched": 0,
            "prices_stored": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )
        logger.info("Price backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.client:
            await self.client.aclose()
        logger.info("Price backfiller shutdown complete")

    async def fetch_historical_prices(
        self,
        coin: str,
        hours: int = 720,  # 30 days
    ) -> list[dict]:
        """
        Fetch historical hourly prices from CryptoCompare.

        Args:
            coin: Coin symbol (e.g., "BTC")
            hours: Number of hours of history (max 2000)

        Returns:
            List of {timestamp, price, volume} dicts
        """
        # CryptoCompare limits to 2000 data points per request
        # For hourly data, that's ~83 days
        limit = min(hours, 2000)

        url = f"{CRYPTOCOMPARE_API}/histohour"
        params = {
            "fsym": coin,
            "tsym": "USD",
            "limit": limit,
        }

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("Response") == "Error":
                logger.error(f"CryptoCompare error for {coin}: {data.get('Message')}")
                self.stats["errors"] += 1
                return []

            result = []
            for point in data.get("Data", {}).get("Data", []):
                ts = point.get("time", 0)
                if ts == 0:
                    continue

                # Use close price
                price = point.get("close", 0)
                # Volume in USD
                volume = point.get("volumeto", 0)

                result.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                    "price": price,
                    "volume": volume,
                })

            self.stats["prices_fetched"] += len(result)
            return result

        except Exception as e:
            logger.error(f"Failed to fetch prices for {coin}: {e}")
            self.stats["errors"] += 1
            return []

    async def store_prices(
        self,
        coin: str,
        prices: list[dict],
    ) -> int:
        """Store prices to database."""
        stored = 0
        for p in prices:
            try:
                price_data = PriceData(
                    timestamp=p["timestamp"],
                    coin=coin,
                    price_usd=p["price"],
                    volume_24h=p["volume"],
                )
                await self.db.insert_price_data(price_data)
                stored += 1
            except Exception as e:
                logger.debug(f"Error storing price: {e}")
                continue

        self.stats["prices_stored"] += stored
        return stored

    async def backfill_coin(
        self,
        coin: str,
        days: int = 30,
    ) -> int:
        """
        Backfill historical prices for a coin.

        Returns number of prices stored.
        """
        hours = days * 24
        logger.info(f"Backfilling {coin} prices ({days} days = {hours} hours)...")

        prices = await self.fetch_historical_prices(coin, hours)
        if not prices:
            logger.warning(f"No prices fetched for {coin}")
            return 0

        stored = await self.store_prices(coin, prices)

        logger.info(
            f"  {coin}: fetched {len(prices)} prices, stored {stored} "
            f"(range: {prices[0]['timestamp'].date()} to {prices[-1]['timestamp'].date()})"
        )

        return stored

    async def run_backfill(self, days: int = 30) -> dict:
        """Run backfill for all coins."""
        logger.info("=" * 60)
        logger.info("STARTING PRICE BACKFILL")
        logger.info(f"Fetching {days} days of hourly data from CryptoCompare")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        for coin in COINS:
            await self.backfill_coin(coin, days)
            await asyncio.sleep(1)  # Rate limit

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("PRICE BACKFILL COMPLETE")
        logger.info(f"  Prices fetched: {self.stats['prices_fetched']}")
        logger.info(f"  Prices stored: {self.stats['prices_stored']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_price_backfill(days: int = 30) -> dict:
    """Main entry point for price backfill."""
    db = Database()
    await db.connect()

    backfiller = PriceBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_backfill(days)
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


async def show_price_summary():
    """Show summary of price data in database."""
    import sqlite3

    conn = sqlite3.connect("data/sentiment.db")
    conn.row_factory = sqlite3.Row

    print("\nPRICE DATA SUMMARY")
    print("=" * 60)

    for coin in ["BTC", "ETH", "SOL"]:
        row = conn.execute("""
            SELECT
                COUNT(*) as cnt,
                MIN(timestamp) as first_ts,
                MAX(timestamp) as last_ts,
                MIN(price_usd) as min_price,
                MAX(price_usd) as max_price,
                AVG(price_usd) as avg_price
            FROM price_data
            WHERE coin = ?
        """, [coin]).fetchone()

        if row["cnt"] > 0:
            print(f"\n{coin}:")
            print(f"  Data points: {row['cnt']}")
            print(f"  Range: {row['first_ts'][:10]} to {row['last_ts'][:10]}")
            print(f"  Price: ${row['min_price']:,.2f} - ${row['max_price']:,.2f}")
            print(f"  Average: ${row['avg_price']:,.2f}")

    conn.close()
    print("=" * 60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        asyncio.run(show_price_summary())
    else:
        days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
        asyncio.run(run_price_backfill(days))
