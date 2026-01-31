"""Price data collector from CoinGecko."""

from datetime import datetime, timezone

import httpx

from ..config import settings
from ..storage.db import Database
from ..storage.models import PriceData
from .base import BaseCollector

API_URL = "https://api.coingecko.com/api/v3/simple/price"

# Map our coin symbols to CoinGecko IDs
COIN_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
}


class PriceCollector(BaseCollector):
    """Collector for cryptocurrency prices from CoinGecko."""

    name = "coingecko"

    def __init__(self, db: Database, coins: list[str] | None = None):
        super().__init__(db)
        self.coins = coins or settings.coins_list
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    def _get_coingecko_ids(self) -> list[str]:
        """Convert our coin symbols to CoinGecko IDs."""
        ids = []
        for coin in self.coins:
            if coin.upper() in COIN_ID_MAP:
                ids.append(COIN_ID_MAP[coin.upper()])
            else:
                self.logger.warning(f"Unknown coin: {coin}, skipping")
        return ids

    async def collect(self) -> None:
        """Fetch prices for tracked coins and store them."""
        coin_ids = self._get_coingecko_ids()
        if not coin_ids:
            self.logger.warning("No valid coins to fetch")
            return

        params = {
            "ids": ",".join(coin_ids),
            "vs_currencies": "usd",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        }

        response = await self.client.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()

        timestamp = datetime.now(timezone.utc)

        # Reverse lookup: CoinGecko ID -> our symbol
        id_to_symbol = {v: k for k, v in COIN_ID_MAP.items()}

        for coin_id, values in data.items():
            symbol = id_to_symbol.get(coin_id, coin_id.upper())

            price_data = PriceData(
                timestamp=timestamp,
                coin=symbol,
                price_usd=values.get("usd", 0),
                volume_24h=values.get("usd_24h_vol"),
                market_cap=values.get("usd_market_cap"),
                source=self.name,
            )
            await self.db.insert_price_data(price_data)

            self.logger.info(
                f"{symbol}: ${values.get('usd', 0):,.2f} "
                f"(vol: ${values.get('usd_24h_vol', 0):,.0f})"
            )
