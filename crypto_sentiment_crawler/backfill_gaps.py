"""
Targeted backfill for sources with missing daily coverage.

Focuses on sources that don't have at least 1 post per day over the last 30 days.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from .backfill import HistoricalBackfiller, RATE_LIMIT_DELAY
from .logging_config import logger
from .storage.db import Database


# Sources that need more backfilling, with pages to fetch
# More pages = more historical data to fill gaps
SPARSE_SOURCES = [
    # Very sparse (< 10 days coverage) - fetch more pages
    {"sub": "nft", "pages": 8, "time_periods": ["week", "month", "year"]},
    {"sub": "CryptoCurrencyMemes", "pages": 6, "time_periods": ["week", "month", "year"]},
    {"sub": "CryptoCurrencyMeta", "pages": 6, "time_periods": ["week", "month", "year"]},
    {"sub": "SatoshiStreetBets", "pages": 8, "time_periods": ["week", "month", "year"]},
    {"sub": "ripple", "pages": 8, "time_periods": ["week", "month", "year"]},
    # Moderate gaps (10-25 days) - fetch some pages
    {"sub": "dogecoin", "pages": 6, "time_periods": ["week", "month"]},
    {"sub": "Crypto_General", "pages": 5, "time_periods": ["week", "month"]},
    {"sub": "altcoin", "pages": 5, "time_periods": ["week", "month"]},
    {"sub": "CryptoTechnology", "pages": 5, "time_periods": ["week", "month"]},
    {"sub": "binance", "pages": 5, "time_periods": ["week", "month"]},
    {"sub": "cardano", "pages": 5, "time_periods": ["week", "month"]},
    {"sub": "litecoin", "pages": 5, "time_periods": ["week", "month"]},
    # Small gaps (< 5 days) - fetch recent posts
    {"sub": "bitcoinbeginners", "pages": 4, "time_periods": ["week", "month"]},
    {"sub": "coinbase", "pages": 4, "time_periods": ["week", "month"]},
    {"sub": "CryptoTax", "pages": 4, "time_periods": ["week", "month"]},
    {"sub": "CryptoMoonShots", "pages": 4, "time_periods": ["week", "month"]},
    {"sub": "BitcoinMarkets", "pages": 4, "time_periods": ["week", "month"]},
]


async def run_gap_backfill() -> dict:
    """Run targeted backfill for sources with coverage gaps."""
    db = Database()
    await db.connect()

    backfiller = HistoricalBackfiller(db)

    try:
        await backfiller.initialize()

        logger.info("=" * 60)
        logger.info("TARGETED GAP BACKFILL")
        logger.info(f"Sources to backfill: {len(SPARSE_SOURCES)}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        for i, config in enumerate(SPARSE_SOURCES):
            subreddit = config["sub"]
            pages = config["pages"]
            time_periods = config["time_periods"]

            logger.info(f"\n[{i+1}/{len(SPARSE_SOURCES)}] r/{subreddit}")

            for time_period in time_periods:
                try:
                    logger.info(f"  Fetching {pages} pages of {time_period} posts...")
                    await backfiller.backfill_subreddit(
                        subreddit,
                        pages=pages,
                        sort="top",
                        time_filter=time_period,
                    )
                except Exception as e:
                    logger.error(f"  Error: {e}")
                    backfiller.stats["errors"] += 1

                # Pause between time periods
                await asyncio.sleep(3)

            # Pause between subreddits
            await asyncio.sleep(5)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("\n" + "=" * 60)
        logger.info("GAP BACKFILL COMPLETE")
        logger.info(f"  Posts fetched: {backfiller.stats['posts_fetched']}")
        logger.info(f"  Posts stored: {backfiller.stats['posts_stored']}")
        logger.info(f"  Errors: {backfiller.stats['errors']}")
        logger.info(f"  Time: {elapsed:.1f}s")
        logger.info("=" * 60)

        return backfiller.stats

    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_gap_backfill())
