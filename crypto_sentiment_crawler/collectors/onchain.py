"""On-chain data collector using Whale Alert API."""

from datetime import datetime, timezone

import httpx

from ..config import settings
from ..storage.db import Database
from ..storage.models import OnChainMetric, SentimentRaw, SentimentScore
from .base import BaseCollector

API_URL = "https://api.whale-alert.io/v1/transactions"

# Known exchange wallet labels (Whale Alert provides these)
EXCHANGE_KEYWORDS = [
    "binance",
    "coinbase",
    "kraken",
    "bitfinex",
    "huobi",
    "okex",
    "okx",
    "kucoin",
    "bybit",
    "gemini",
    "bitstamp",
    "ftx",
    "crypto.com",
    "gate.io",
    "bittrex",
]

# Map blockchain symbols to our standard symbols
BLOCKCHAIN_MAP = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "tron": "TRX",
    "avalanche": "AVAX",
    "polygon": "MATIC",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "litecoin": "LTC",
}


def is_exchange(owner: dict | None) -> bool:
    """Check if an address belongs to an exchange."""
    if not owner:
        return False
    owner_type = owner.get("owner_type", "").lower()
    owner_name = owner.get("owner", "").lower()

    if owner_type == "exchange":
        return True

    return any(ex in owner_name for ex in EXCHANGE_KEYWORDS)


def classify_transfer(from_owner: dict | None, to_owner: dict | None) -> str:
    """
    Classify a transfer based on source and destination.

    Returns:
        'exchange_inflow': Money moving TO exchange (selling pressure)
        'exchange_outflow': Money moving FROM exchange (accumulation)
        'exchange_internal': Exchange to exchange
        'whale_transfer': Unknown/wallet to wallet
    """
    from_exchange = is_exchange(from_owner)
    to_exchange = is_exchange(to_owner)

    if from_exchange and to_exchange:
        return "exchange_internal"
    elif to_exchange:
        return "exchange_inflow"
    elif from_exchange:
        return "exchange_outflow"
    else:
        return "whale_transfer"


class OnChainCollector(BaseCollector):
    """Collector for on-chain whale transactions."""

    name = "whale_alert"

    def __init__(self, db: Database, min_value_usd: int = 1_000_000):
        super().__init__(db)
        self.min_value_usd = min_value_usd
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def collect(self) -> None:
        """Fetch recent whale transactions and analyze flow."""
        if not settings.whale_alert_api_key:
            raise ValueError(
                "Whale Alert API key not configured. "
                "Set WHALE_ALERT_API_KEY in .env"
            )

        # Fetch transactions from the last hour
        now = int(datetime.now(timezone.utc).timestamp())
        start_time = now - 3600  # 1 hour ago

        params = {
            "api_key": settings.whale_alert_api_key,
            "min_value": self.min_value_usd,
            "start": start_time,
            "limit": 100,
        }

        response = await self.client.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            self.logger.warning(f"Whale Alert API error: {data.get('message', 'Unknown')}")
            return

        transactions = data.get("transactions", [])
        if not transactions:
            self.logger.info("No whale transactions in the last hour")
            return

        timestamp = datetime.now(timezone.utc)

        # Store raw data
        raw = SentimentRaw(
            timestamp=timestamp,
            source=self.name,
            coin=None,
            raw_data={"transactions": transactions, "count": len(transactions)},
        )
        await self.db.insert_sentiment_raw(raw)

        # Process and classify transactions
        flow_by_coin: dict[str, dict] = {}  # coin -> {inflow: $, outflow: $, transfers: []}

        for tx in transactions:
            blockchain = tx.get("blockchain", "").lower()
            coin = BLOCKCHAIN_MAP.get(blockchain)

            if not coin:
                continue  # Skip unsupported chains

            amount_usd = tx.get("amount_usd", 0)
            from_owner = tx.get("from", {})
            to_owner = tx.get("to", {})

            transfer_type = classify_transfer(from_owner, to_owner)

            # Store individual metric
            metric = OnChainMetric(
                timestamp=datetime.fromtimestamp(tx.get("timestamp", now), tz=timezone.utc),
                coin=coin,
                metric_type=transfer_type,
                value=amount_usd,
                metadata={
                    "hash": tx.get("hash"),
                    "from": from_owner.get("owner", "unknown"),
                    "to": to_owner.get("owner", "unknown"),
                    "amount": tx.get("amount"),
                    "symbol": tx.get("symbol"),
                },
            )
            await self.db.insert_on_chain_metric(metric)

            # Aggregate by coin
            if coin not in flow_by_coin:
                flow_by_coin[coin] = {"inflow": 0, "outflow": 0, "internal": 0, "transfers": 0}

            if transfer_type == "exchange_inflow":
                flow_by_coin[coin]["inflow"] += amount_usd
            elif transfer_type == "exchange_outflow":
                flow_by_coin[coin]["outflow"] += amount_usd
            elif transfer_type == "exchange_internal":
                flow_by_coin[coin]["internal"] += amount_usd

            flow_by_coin[coin]["transfers"] += 1

        # Calculate sentiment scores based on net flow
        for coin, flows in flow_by_coin.items():
            net_flow = flows["outflow"] - flows["inflow"]
            total_flow = flows["outflow"] + flows["inflow"]

            if total_flow == 0:
                score = 0.0
            else:
                # Normalize: outflow > inflow = positive (bullish)
                # inflow > outflow = negative (bearish)
                score = net_flow / total_flow  # Already -1 to 1

            await self.db.insert_sentiment_score(
                SentimentScore(
                    timestamp=timestamp,
                    coin=coin,
                    source=self.name,
                    score=max(-1.0, min(1.0, score)),
                    confidence=min(1.0, flows["transfers"] / 10),
                    sample_size=flows["transfers"],
                )
            )

            self.logger.info(
                f"{coin}: inflow=${flows['inflow']:,.0f} outflow=${flows['outflow']:,.0f} "
                f"-> score={score:.2f} ({flows['transfers']} txs)"
            )

        self.logger.info(f"Processed {len(transactions)} whale transactions")
