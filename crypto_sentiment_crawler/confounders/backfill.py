"""
Backfill historical confounder data for model training.

Fetches historical data for:
- Fear & Greed Index (Alternative.me has historical)
- VIX, DXY, S&P500 (Yahoo Finance historical)
- BTC Dominance (CoinGecko historical)
- Volatility (calculated from price data)
"""

import asyncio
import json
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..logging_config import logger


class ConfounderBackfiller:
    """Backfill historical confounder data."""

    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    CRYPTOCOMPARE_HISTOHOUR_URL = "https://min-api.cryptocompare.com/data/v2/histohour"

    def __init__(self, db_path: str = "data/sentiment.db"):
        self.db_path = db_path
        self.client: httpx.AsyncClient | None = None
        self.stats = {
            "fear_greed_fetched": 0,
            "macro_fetched": 0,
            "regime_fetched": 0,
            "records_stored": 0,
            "errors": 0,
        }

    async def start(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )
        self._init_db()
        logger.info("Confounder backfiller initialized")

    async def close(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    def _init_db(self) -> None:
        """Ensure database table exists."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confounders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                news_count_1h INTEGER,
                news_sentiment_avg REAL,
                news_has_btc INTEGER,
                news_has_eth INTEGER,
                news_categories TEXT,
                vix_level REAL,
                dxy_value REAL,
                dxy_change_24h REAL,
                sp500_price REAL,
                sp500_change_1h REAL,
                fed_event_today INTEGER,
                cpi_release_today INTEGER,
                fear_greed_index INTEGER,
                btc_dominance REAL,
                total_market_cap REAL,
                btc_trend_7d REAL,
                volatility_24h REAL,
                funding_rate_btc REAL,
                funding_rate_eth REAL,
                exchange_inflow_btc REAL,
                exchange_outflow_btc REAL,
                large_tx_count INTEGER,
                reddit_post_volume_1h INTEGER,
                reddit_unique_authors_1h INTEGER,
                reddit_avg_score REAL,
                collection_errors TEXT,
                UNIQUE(timestamp)
            )
        """)
        conn.commit()
        conn.close()

    async def fetch_fear_greed_history(self, days: int = 30) -> list[dict]:
        """Fetch historical Fear & Greed data."""
        try:
            params = {"limit": days, "format": "json"}
            response = await self.client.get(self.FEAR_GREED_URL, params=params)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("data", []):
                ts = int(item.get("timestamp", 0))
                if ts > 0:
                    results.append({
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                        "fear_greed_index": int(item.get("value", 0)),
                        "classification": item.get("value_classification"),
                    })

            self.stats["fear_greed_fetched"] = len(results)
            logger.info(f"Fetched {len(results)} Fear & Greed records")
            return results

        except Exception as e:
            logger.error(f"Fear & Greed history fetch error: {e}")
            self.stats["errors"] += 1
            return []

    async def fetch_yahoo_history(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[dict]:
        """Fetch historical data from Yahoo Finance."""
        try:
            url = self.YAHOO_CHART_URL.format(symbol=symbol)
            params = {
                "interval": "1h",
                "range": f"{days}d",
            }

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            chart = data.get("chart", {})
            result = chart.get("result", [{}])[0]
            timestamps = result.get("timestamp", [])
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            closes = quotes.get("close", [])

            results = []
            for i, ts in enumerate(timestamps):
                if closes[i] is not None:
                    results.append({
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                        "price": closes[i],
                    })

            logger.info(f"Fetched {len(results)} {symbol} records from Yahoo")
            return results

        except Exception as e:
            logger.error(f"Yahoo history fetch error for {symbol}: {e}")
            self.stats["errors"] += 1
            return []

    async def fetch_btc_dominance_history(self, days: int = 30) -> list[dict]:
        """Fetch historical BTC dominance from CoinGecko."""
        try:
            # CoinGecko market chart gives us market cap data
            params = {
                "vs_currency": "usd",
                "days": days,
                "interval": "hourly" if days <= 90 else "daily",
            }

            response = await self.client.get(self.COINGECKO_MARKET_CHART_URL, params=params)

            if response.status_code == 429:
                logger.warning("CoinGecko rate limited, waiting...")
                await asyncio.sleep(60)
                return []

            response.raise_for_status()
            data = response.json()

            # Get BTC market caps
            btc_market_caps = data.get("market_caps", [])

            # We need total market cap too - fetch global data
            # For now, estimate dominance based on typical range
            results = []
            for mc in btc_market_caps:
                ts_ms, market_cap = mc
                ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                # Rough estimate: BTC is typically 40-60% of total
                # We'll use actual market cap and estimate total
                results.append({
                    "timestamp": ts,
                    "btc_market_cap": market_cap,
                })

            logger.info(f"Fetched {len(results)} BTC market cap records")
            return results

        except Exception as e:
            logger.error(f"CoinGecko history fetch error: {e}")
            self.stats["errors"] += 1
            return []

    async def fetch_btc_prices_for_volatility(self, days: int = 30) -> list[dict]:
        """Fetch BTC hourly prices for volatility calculation."""
        try:
            # Fetch in chunks (CryptoCompare limits to 2000)
            hours = days * 24
            all_prices = []

            params = {
                "fsym": "BTC",
                "tsym": "USD",
                "limit": min(hours, 2000),
            }

            response = await self.client.get(self.CRYPTOCOMPARE_HISTOHOUR_URL, params=params)
            response.raise_for_status()
            data = response.json()

            for point in data.get("Data", {}).get("Data", []):
                ts = point.get("time", 0)
                close = point.get("close", 0)
                if ts > 0 and close > 0:
                    all_prices.append({
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
                        "price": close,
                    })

            logger.info(f"Fetched {len(all_prices)} BTC price records for volatility")
            return all_prices

        except Exception as e:
            logger.error(f"CryptoCompare fetch error: {e}")
            self.stats["errors"] += 1
            return []

    def calculate_volatility_at_time(
        self,
        prices: list[dict],
        target_time: datetime,
        window_hours: int = 24,
    ) -> float | None:
        """Calculate realized volatility at a specific time."""
        # Get prices in the window before target_time
        window_start = target_time - timedelta(hours=window_hours)

        window_prices = [
            p["price"] for p in prices
            if window_start <= p["timestamp"] <= target_time
        ]

        if len(window_prices) < 2:
            return None

        # Calculate hourly returns
        returns = []
        for i in range(1, len(window_prices)):
            if window_prices[i-1] > 0:
                ret = (window_prices[i] - window_prices[i-1]) / window_prices[i-1]
                returns.append(ret)

        if not returns:
            return None

        # Realized volatility (std of returns, annualized)
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        # Annualize
        annualized_vol = std_dev * math.sqrt(24 * 365) * 100
        return annualized_vol

    def calculate_trend_at_time(
        self,
        prices: list[dict],
        target_time: datetime,
        days: int = 7,
    ) -> float | None:
        """Calculate price trend (return) over N days."""
        start_time = target_time - timedelta(days=days)

        # Find prices closest to start and end
        start_price = None
        end_price = None

        for p in prices:
            if p["timestamp"] <= start_time:
                start_price = p["price"]
            if p["timestamp"] <= target_time:
                end_price = p["price"]

        if start_price and end_price and start_price > 0:
            return ((end_price - start_price) / start_price) * 100

        return None

    async def backfill(self, days: int = 30) -> dict:
        """
        Run full backfill of confounder data.

        Args:
            days: Number of days to backfill.

        Returns:
            Statistics dict.
        """
        logger.info("=" * 60)
        logger.info(f"STARTING CONFOUNDER BACKFILL ({days} days)")
        logger.info("=" * 60)

        # Fetch all historical data
        logger.info("Fetching Fear & Greed history...")
        fear_greed_data = await self.fetch_fear_greed_history(days)
        await asyncio.sleep(1)

        logger.info("Fetching VIX history...")
        vix_data = await self.fetch_yahoo_history("^VIX", days)
        await asyncio.sleep(1)

        logger.info("Fetching DXY history...")
        dxy_data = await self.fetch_yahoo_history("DX-Y.NYB", days)
        await asyncio.sleep(1)

        logger.info("Fetching S&P500 history...")
        sp500_data = await self.fetch_yahoo_history("^GSPC", days)
        await asyncio.sleep(1)

        logger.info("Fetching BTC prices for volatility...")
        btc_prices = await self.fetch_btc_prices_for_volatility(days)
        await asyncio.sleep(1)

        # Create hourly timestamps for the backfill period
        end_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start_time = end_time - timedelta(days=days)

        # Build lookup dicts for faster access
        fng_lookup = {
            d["timestamp"].replace(hour=0, minute=0, second=0, microsecond=0): d
            for d in fear_greed_data
        }
        vix_lookup = {d["timestamp"]: d["price"] for d in vix_data}
        dxy_lookup = {d["timestamp"]: d["price"] for d in dxy_data}
        sp500_lookup = {d["timestamp"]: d["price"] for d in sp500_data}

        # Generate hourly snapshots
        logger.info("Generating hourly confounder snapshots...")
        conn = sqlite3.connect(self.db_path)
        records_stored = 0

        current_time = start_time
        while current_time <= end_time:
            # Get Fear & Greed for this day
            day_key = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            fng = fng_lookup.get(day_key, {}).get("fear_greed_index")

            # Find closest VIX, DXY, S&P500 values
            vix = self._find_closest_value(vix_lookup, current_time)
            dxy = self._find_closest_value(dxy_lookup, current_time)
            sp500 = self._find_closest_value(sp500_lookup, current_time)

            # Calculate volatility and trend
            volatility = self.calculate_volatility_at_time(btc_prices, current_time, 24)
            trend_7d = self.calculate_trend_at_time(btc_prices, current_time, 7)

            # Store if we have at least some data
            if fng is not None or vix is not None or volatility is not None:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO confounders (
                            timestamp, fear_greed_index, vix_level, dxy_value,
                            sp500_price, volatility_24h, btc_trend_7d
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        current_time.isoformat(),
                        fng,
                        vix,
                        dxy,
                        sp500,
                        volatility,
                        trend_7d,
                    ))
                    records_stored += 1
                except Exception as e:
                    logger.debug(f"Error storing confounder: {e}")

            current_time += timedelta(hours=1)

        conn.commit()
        conn.close()

        self.stats["records_stored"] = records_stored

        logger.info("=" * 60)
        logger.info("CONFOUNDER BACKFILL COMPLETE")
        logger.info(f"  Fear & Greed records: {self.stats['fear_greed_fetched']}")
        logger.info(f"  Total records stored: {records_stored}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info("=" * 60)

        return self.stats

    def _find_closest_value(
        self,
        lookup: dict[datetime, float],
        target: datetime,
        max_hours: int = 2,
    ) -> float | None:
        """Find the closest value within max_hours of target time."""
        if not lookup:
            return None

        # Try exact match first
        if target in lookup:
            return lookup[target]

        # Search nearby hours
        for offset in range(1, max_hours + 1):
            for direction in [1, -1]:
                check_time = target + timedelta(hours=offset * direction)
                if check_time in lookup:
                    return lookup[check_time]

        return None


async def run_confounder_backfill(days: int = 30) -> dict:
    """Main entry point for confounder backfill."""
    backfiller = ConfounderBackfiller()

    try:
        await backfiller.start()
        stats = await backfiller.backfill(days)
        return stats
    finally:
        await backfiller.close()


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    asyncio.run(run_confounder_backfill(days))
