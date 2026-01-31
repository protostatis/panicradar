"""
Macro economic confounder data collection.

Uses Yahoo Finance for VIX, DXY, S&P500.
Uses economic calendar for Fed/CPI events.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from ..logging_config import logger


# Known Fed meeting dates for 2026 (FOMC schedule)
# These are typically announced a year in advance
FED_MEETING_DATES_2026 = [
    "2026-01-28", "2026-01-29",  # January
    "2026-03-17", "2026-03-18",  # March
    "2026-05-05", "2026-05-06",  # May
    "2026-06-16", "2026-06-17",  # June
    "2026-07-28", "2026-07-29",  # July
    "2026-09-15", "2026-09-16",  # September
    "2026-11-03", "2026-11-04",  # November
    "2026-12-15", "2026-12-16",  # December
]

# CPI release dates (usually around 10th-15th of each month)
CPI_RELEASE_DATES_2026 = [
    "2026-01-14", "2026-02-12", "2026-03-12", "2026-04-10",
    "2026-05-13", "2026-06-11", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-13", "2026-11-12", "2026-12-11",
]


class MacroCollector:
    """
    Collects macro economic indicators.

    Uses Yahoo Finance API for market data.
    """

    # Yahoo Finance API (unofficial but widely used)
    YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    # Symbols
    SYMBOLS = {
        "vix": "^VIX",
        "dxy": "DX-Y.NYB",  # Dollar index
        "sp500": "^GSPC",
    }

    def __init__(self):
        self.client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    async def fetch_yahoo_quote(self, symbol: str) -> dict[str, Any]:
        """
        Fetch current quote from Yahoo Finance.

        Returns:
            Dict with price, change, etc.
        """
        if not self.client:
            await self.start()

        url = self.YAHOO_QUOTE_URL.format(symbol=symbol)
        params = {
            "interval": "1h",
            "range": "2d",
        }

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            chart = data.get("chart", {})
            result = chart.get("result", [{}])[0]
            meta = result.get("meta", {})
            indicators = result.get("indicators", {})
            quotes = indicators.get("quote", [{}])[0]

            # Get timestamps and closes
            timestamps = result.get("timestamp", [])
            closes = quotes.get("close", [])

            if not closes or not timestamps:
                return {"error": "No data"}

            # Current price (most recent)
            current_price = None
            for c in reversed(closes):
                if c is not None:
                    current_price = c
                    break

            # Price 24h ago for change calculation
            price_24h_ago = None
            now = datetime.now(timezone.utc)
            target_time = now - timedelta(hours=24)

            for i, ts in enumerate(timestamps):
                ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if ts_dt <= target_time and closes[i] is not None:
                    price_24h_ago = closes[i]

            # Price 1h ago for hourly change
            price_1h_ago = None
            target_time_1h = now - timedelta(hours=1)

            for i, ts in enumerate(timestamps):
                ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if ts_dt <= target_time_1h and closes[i] is not None:
                    price_1h_ago = closes[i]

            change_24h = None
            if current_price and price_24h_ago:
                change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100

            change_1h = None
            if current_price and price_1h_ago:
                change_1h = ((current_price - price_1h_ago) / price_1h_ago) * 100

            return {
                "price": current_price,
                "change_24h": change_24h,
                "change_1h": change_1h,
                "currency": meta.get("currency"),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Yahoo Finance API error for {symbol}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Macro collection error for {symbol}: {e}")
            return {"error": str(e)}

    def check_fed_event_today(self) -> bool:
        """Check if today is a Fed meeting day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return today in FED_MEETING_DATES_2026

    def check_cpi_release_today(self) -> bool:
        """Check if today is a CPI release day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return today in CPI_RELEASE_DATES_2026

    async def collect(self) -> dict[str, Any]:
        """
        Collect all macro proxy variables.

        Returns:
            Dict with macro confounder data.
        """
        errors = []

        # Fetch VIX
        vix_data = await self.fetch_yahoo_quote(self.SYMBOLS["vix"])
        if vix_data.get("error"):
            errors.append(f"VIX: {vix_data['error']}")

        # Fetch DXY
        dxy_data = await self.fetch_yahoo_quote(self.SYMBOLS["dxy"])
        if dxy_data.get("error"):
            errors.append(f"DXY: {dxy_data['error']}")

        # Fetch S&P500
        sp500_data = await self.fetch_yahoo_quote(self.SYMBOLS["sp500"])
        if sp500_data.get("error"):
            errors.append(f"SP500: {sp500_data['error']}")

        return {
            "vix_level": vix_data.get("price"),
            "dxy_value": dxy_data.get("price"),
            "dxy_change_24h": dxy_data.get("change_24h"),
            "sp500_price": sp500_data.get("price"),
            "sp500_change_1h": sp500_data.get("change_1h"),
            "fed_event_today": self.check_fed_event_today(),
            "cpi_release_today": self.check_cpi_release_today(),
            "errors": errors if errors else None,
        }


async def test_macro_collector():
    """Test the macro collector."""
    collector = MacroCollector()
    await collector.start()

    try:
        data = await collector.collect()
        print("Macro Confounder Data:")
        print(f"  VIX Level: {data['vix_level']}")
        print(f"  DXY Value: {data['dxy_value']}")
        print(f"  DXY Change 24h: {data['dxy_change_24h']:.2f}%" if data['dxy_change_24h'] else "  DXY Change 24h: N/A")
        print(f"  S&P500 Price: {data['sp500_price']}")
        print(f"  S&P500 Change 1h: {data['sp500_change_1h']:.2f}%" if data['sp500_change_1h'] else "  S&P500 Change 1h: N/A")
        print(f"  Fed Event Today: {data['fed_event_today']}")
        print(f"  CPI Release Today: {data['cpi_release_today']}")
        if data.get("errors"):
            print(f"  Errors: {data['errors']}")
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(test_macro_collector())
