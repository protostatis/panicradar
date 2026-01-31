"""
Market regime confounder data collection.

Collects: Fear & Greed, BTC dominance, funding rates, volatility.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any
import math

import httpx

from ..logging_config import logger


class RegimeCollector:
    """
    Collects market regime indicators.

    Uses:
    - Alternative.me for Fear & Greed Index
    - CoinGecko for BTC dominance and market cap
    - Binance for funding rates
    - CryptoCompare for historical prices (volatility calculation)
    """

    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
    # Use Binance public API (not futures, which may be geo-restricted)
    BINANCE_FUNDING_URL = "https://www.binance.com/fapi/v1/fundingRate"
    # Alternative: use Coinglass or other funding rate aggregators
    COINGLASS_FUNDING_URL = "https://open-api.coinglass.com/public/v2/funding"
    CRYPTOCOMPARE_URL = "https://min-api.cryptocompare.com/data/v2/histohour"

    def __init__(self):
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

    async def fetch_fear_greed(self) -> dict[str, Any]:
        """Fetch Fear & Greed Index."""
        if not self.client:
            await self.start()

        try:
            response = await self.client.get(self.FEAR_GREED_URL)
            response.raise_for_status()
            data = response.json()

            fng_data = data.get("data", [{}])[0]
            return {
                "value": int(fng_data.get("value", 0)),
                "classification": fng_data.get("value_classification"),
            }
        except Exception as e:
            logger.error(f"Fear & Greed fetch error: {e}")
            return {"error": str(e)}

    async def fetch_global_market(self) -> dict[str, Any]:
        """Fetch global crypto market data from CoinGecko."""
        if not self.client:
            await self.start()

        try:
            response = await self.client.get(self.COINGECKO_GLOBAL_URL)
            response.raise_for_status()
            data = response.json()

            market_data = data.get("data", {})
            return {
                "btc_dominance": market_data.get("market_cap_percentage", {}).get("btc"),
                "eth_dominance": market_data.get("market_cap_percentage", {}).get("eth"),
                "total_market_cap": market_data.get("total_market_cap", {}).get("usd"),
                "total_volume": market_data.get("total_volume", {}).get("usd"),
                "market_cap_change_24h": market_data.get("market_cap_change_percentage_24h_usd"),
            }
        except Exception as e:
            logger.error(f"CoinGecko global fetch error: {e}")
            return {"error": str(e)}

    async def fetch_funding_rate(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        Fetch perpetual funding rate.

        Note: Binance futures API may be geo-restricted in some regions.
        Returns None if unavailable rather than failing.
        """
        if not self.client:
            await self.start()

        # Try multiple endpoints
        endpoints = [
            (self.BINANCE_FUNDING_URL, {"symbol": symbol, "limit": 1}),
        ]

        for url, params in endpoints:
            try:
                response = await self.client.get(url, params=params, timeout=10.0)

                # Skip if geo-restricted or forbidden
                if response.status_code in [451, 403, 418]:
                    logger.debug(f"Funding rate API restricted: {response.status_code}")
                    continue

                response.raise_for_status()
                data = response.json()

                if data and isinstance(data, list) and len(data) > 0:
                    return {
                        "funding_rate": float(data[0].get("fundingRate", 0)),
                        "funding_time": data[0].get("fundingTime"),
                    }
            except httpx.TimeoutException:
                logger.debug(f"Funding rate API timeout for {symbol}")
                continue
            except Exception as e:
                logger.debug(f"Funding rate fetch error for {symbol}: {e}")
                continue

        # Return None if all endpoints fail (not an error, just unavailable)
        return {"funding_rate": None}

    async def calculate_volatility(self, coin: str = "BTC", hours: int = 24) -> dict[str, Any]:
        """
        Calculate realized volatility from hourly returns.

        Uses CryptoCompare hourly data.
        """
        if not self.client:
            await self.start()

        try:
            params = {
                "fsym": coin,
                "tsym": "USD",
                "limit": hours + 1,
            }
            response = await self.client.get(self.CRYPTOCOMPARE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            prices = [
                point.get("close")
                for point in data.get("Data", {}).get("Data", [])
                if point.get("close")
            ]

            if len(prices) < 2:
                return {"error": "Insufficient price data"}

            # Calculate hourly returns
            returns = []
            for i in range(1, len(prices)):
                if prices[i-1] > 0:
                    ret = (prices[i] - prices[i-1]) / prices[i-1]
                    returns.append(ret)

            if not returns:
                return {"error": "No returns calculated"}

            # Realized volatility (std of returns, annualized)
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance)

            # Annualize (hourly to annual: sqrt(24 * 365))
            annualized_vol = std_dev * math.sqrt(24 * 365) * 100  # as percentage

            # 7-day trend (if we have enough data)
            trend_7d = None
            if len(prices) >= 168:  # 7 days of hourly data
                trend_7d = ((prices[-1] - prices[-168]) / prices[-168]) * 100

            return {
                "volatility_24h": annualized_vol,
                "trend_7d": trend_7d,
                "current_price": prices[-1] if prices else None,
            }
        except Exception as e:
            logger.error(f"Volatility calculation error: {e}")
            return {"error": str(e)}

    async def collect(self) -> dict[str, Any]:
        """
        Collect all regime proxy variables.

        Returns:
            Dict with regime confounder data.
        """
        errors = []

        # Fetch Fear & Greed
        fng_data = await self.fetch_fear_greed()
        if fng_data.get("error"):
            errors.append(f"FNG: {fng_data['error']}")

        # Fetch global market data
        global_data = await self.fetch_global_market()
        if global_data.get("error"):
            errors.append(f"Global: {global_data['error']}")

        # Fetch funding rates
        btc_funding = await self.fetch_funding_rate("BTCUSDT")
        if btc_funding.get("error"):
            errors.append(f"BTC Funding: {btc_funding['error']}")

        eth_funding = await self.fetch_funding_rate("ETHUSDT")
        if eth_funding.get("error"):
            errors.append(f"ETH Funding: {eth_funding['error']}")

        # Calculate volatility
        vol_data = await self.calculate_volatility("BTC", hours=24)
        if vol_data.get("error"):
            errors.append(f"Volatility: {vol_data['error']}")

        return {
            "fear_greed_index": fng_data.get("value"),
            "fear_greed_class": fng_data.get("classification"),
            "btc_dominance": global_data.get("btc_dominance"),
            "total_market_cap": global_data.get("total_market_cap"),
            "market_cap_change_24h": global_data.get("market_cap_change_24h"),
            "funding_rate_btc": btc_funding.get("funding_rate"),
            "funding_rate_eth": eth_funding.get("funding_rate"),
            "volatility_24h": vol_data.get("volatility_24h"),
            "btc_trend_7d": vol_data.get("trend_7d"),
            "errors": errors if errors else None,
        }


async def test_regime_collector():
    """Test the regime collector."""
    collector = RegimeCollector()
    await collector.start()

    try:
        data = await collector.collect()
        print("Regime Confounder Data:")
        print(f"  Fear & Greed: {data['fear_greed_index']} ({data.get('fear_greed_class')})")
        print(f"  BTC Dominance: {data['btc_dominance']:.1f}%" if data['btc_dominance'] else "  BTC Dominance: N/A")
        print(f"  Total Market Cap: ${data['total_market_cap']:,.0f}" if data['total_market_cap'] else "  Total Market Cap: N/A")
        print(f"  BTC Funding Rate: {data['funding_rate_btc']:.4f}" if data['funding_rate_btc'] else "  BTC Funding Rate: N/A")
        print(f"  ETH Funding Rate: {data['funding_rate_eth']:.4f}" if data['funding_rate_eth'] else "  ETH Funding Rate: N/A")
        print(f"  Volatility 24h: {data['volatility_24h']:.1f}%" if data['volatility_24h'] else "  Volatility 24h: N/A")
        print(f"  BTC Trend 7d: {data['btc_trend_7d']:.1f}%" if data['btc_trend_7d'] else "  BTC Trend 7d: N/A")
        if data.get("errors"):
            print(f"  Errors: {data['errors']}")
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(test_regime_collector())
