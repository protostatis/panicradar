"""Pydantic schemas for the news/trending API endpoint."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class TrendingSignal(BaseModel):
    headline: str
    source: str
    discovered_via: Optional[str] = None
    surprise_score: str  # "high" | "medium" | "low"
    why_interesting: str
    content_hook: Optional[str] = None
    video_hook: Optional[str] = None
    engagement: Optional[dict] = None

    model_config = ConfigDict(extra="allow")


class DefiSignal(BaseModel):
    headline: str
    source: str
    why_interesting: str


class TrendingCoin(BaseModel):
    name: str
    symbol: str
    rank: int
    price_change_24h: str
    volume: str
    note: Optional[str] = None


class MarketContext(BaseModel):
    btc_price_direction: Optional[str] = None
    btc_price: Optional[str] = None
    market_cap: Optional[str] = None
    market_cap_change: Optional[str] = None
    volume_24h: Optional[str] = None
    btc_dominance: Optional[str] = None
    eth_dominance: Optional[str] = None
    dominant_sentiment: Optional[str] = None
    liquidations_24h: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class TrendingResponse(BaseModel):
    date: str
    generated_at: str
    sources_browsed: int
    pages_visited: int
    signals: list[TrendingSignal]
    defi_signals: list[DefiSignal] = []
    trending_coins: list[TrendingCoin] = []
    top_losers: list[TrendingCoin] = []
    market_context: MarketContext
    top_3_hooks: list[str] = []
    summary: str
    errors: list[str] = []
