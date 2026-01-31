"""
Data models for confounder variables.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConfounderSnapshot:
    """
    A point-in-time snapshot of all confounder variables.

    Used for backdoor adjustment in causal analysis.
    """
    timestamp: datetime

    # News proxies
    news_count_1h: int | None = None
    news_sentiment_avg: float | None = None  # -1 to 1
    news_has_btc: bool | None = None
    news_has_eth: bool | None = None
    news_categories: list[str] = field(default_factory=list)

    # Macro proxies
    vix_level: float | None = None
    dxy_value: float | None = None
    dxy_change_24h: float | None = None  # percent
    sp500_price: float | None = None
    sp500_change_1h: float | None = None  # percent
    fed_event_today: bool = False
    cpi_release_today: bool = False

    # Regime proxies
    fear_greed_index: int | None = None  # 0-100
    btc_dominance: float | None = None  # percent
    total_market_cap: float | None = None  # USD
    btc_trend_7d: float | None = None  # percent return
    volatility_24h: float | None = None  # realized vol
    funding_rate_btc: float | None = None  # perpetual funding
    funding_rate_eth: float | None = None

    # On-chain proxies (partial whale observation)
    exchange_inflow_btc: float | None = None
    exchange_outflow_btc: float | None = None
    large_tx_count: int | None = None

    # Social contagion proxies
    reddit_post_volume_1h: int | None = None
    reddit_unique_authors_1h: int | None = None
    reddit_avg_score: float | None = None

    # Metadata
    collection_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "news_count_1h": self.news_count_1h,
            "news_sentiment_avg": self.news_sentiment_avg,
            "news_has_btc": self.news_has_btc,
            "news_has_eth": self.news_has_eth,
            "news_categories": self.news_categories,
            "vix_level": self.vix_level,
            "dxy_value": self.dxy_value,
            "dxy_change_24h": self.dxy_change_24h,
            "sp500_price": self.sp500_price,
            "sp500_change_1h": self.sp500_change_1h,
            "fed_event_today": self.fed_event_today,
            "cpi_release_today": self.cpi_release_today,
            "fear_greed_index": self.fear_greed_index,
            "btc_dominance": self.btc_dominance,
            "total_market_cap": self.total_market_cap,
            "btc_trend_7d": self.btc_trend_7d,
            "volatility_24h": self.volatility_24h,
            "funding_rate_btc": self.funding_rate_btc,
            "funding_rate_eth": self.funding_rate_eth,
            "exchange_inflow_btc": self.exchange_inflow_btc,
            "exchange_outflow_btc": self.exchange_outflow_btc,
            "large_tx_count": self.large_tx_count,
            "reddit_post_volume_1h": self.reddit_post_volume_1h,
            "reddit_unique_authors_1h": self.reddit_unique_authors_1h,
            "reddit_avg_score": self.reddit_avg_score,
            "collection_errors": self.collection_errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfounderSnapshot":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            timestamp=timestamp,
            news_count_1h=data.get("news_count_1h"),
            news_sentiment_avg=data.get("news_sentiment_avg"),
            news_has_btc=data.get("news_has_btc"),
            news_has_eth=data.get("news_has_eth"),
            news_categories=data.get("news_categories", []),
            vix_level=data.get("vix_level"),
            dxy_value=data.get("dxy_value"),
            dxy_change_24h=data.get("dxy_change_24h"),
            sp500_price=data.get("sp500_price"),
            sp500_change_1h=data.get("sp500_change_1h"),
            fed_event_today=data.get("fed_event_today", False),
            cpi_release_today=data.get("cpi_release_today", False),
            fear_greed_index=data.get("fear_greed_index"),
            btc_dominance=data.get("btc_dominance"),
            total_market_cap=data.get("total_market_cap"),
            btc_trend_7d=data.get("btc_trend_7d"),
            volatility_24h=data.get("volatility_24h"),
            funding_rate_btc=data.get("funding_rate_btc"),
            funding_rate_eth=data.get("funding_rate_eth"),
            exchange_inflow_btc=data.get("exchange_inflow_btc"),
            exchange_outflow_btc=data.get("exchange_outflow_btc"),
            large_tx_count=data.get("large_tx_count"),
            reddit_post_volume_1h=data.get("reddit_post_volume_1h"),
            reddit_unique_authors_1h=data.get("reddit_unique_authors_1h"),
            reddit_avg_score=data.get("reddit_avg_score"),
            collection_errors=data.get("collection_errors", []),
        )
