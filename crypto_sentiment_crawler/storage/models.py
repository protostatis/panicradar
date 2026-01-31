"""Database models using Pydantic for validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class SentimentRaw(BaseModel):
    """Raw collected data from any source."""

    timestamp: datetime
    source: str  # 'reddit', 'fear_greed', 'whale_alert'
    coin: str | None = None  # None for market-wide data
    raw_data: dict

    class Config:
        from_attributes = True


class SentimentScore(BaseModel):
    """Processed sentiment score."""

    timestamp: datetime
    coin: str
    source: str
    score: float = Field(ge=-1.0, le=1.0)  # Normalized -1 to 1
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sample_size: int | None = None


class PriceData(BaseModel):
    """Price data for a coin."""

    timestamp: datetime
    coin: str
    price_usd: float
    volume_24h: float | None = None
    market_cap: float | None = None
    source: str = "coingecko"


class OnChainMetric(BaseModel):
    """On-chain metrics like whale transfers."""

    timestamp: datetime
    coin: str
    metric_type: str  # 'whale_transfer', 'exchange_inflow', 'exchange_outflow'
    value: float
    metadata: dict | None = None
