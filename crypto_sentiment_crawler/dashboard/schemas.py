"""Pydantic schemas for dashboard API responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CoinPrice(BaseModel):
    """Price data for a specific coin."""

    coin: str
    price: Optional[float] = None
    change_24h: Optional[float] = None
    change_7d: Optional[float] = None
    change_30d: Optional[float] = None


class DashboardSummary(BaseModel):
    """Current dashboard summary metrics."""

    timestamp: str
    # Core metrics
    sentiment_score: float
    sentiment_state: str  # "Bullish", "Bearish", "Neutral"
    fear_greed_index: Optional[int] = None
    fear_greed_label: str = "Unknown"  # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    # Volatility
    volatility_24h: Optional[float] = None
    volatility_state: str = "Unknown"  # "Low", "Moderate", "High", "Extreme"
    # Price info
    btc_price: Optional[float] = None
    btc_change_24h: Optional[float] = None
    btc_change_7d: Optional[float] = None
    # Multi-dimensional signals
    fear_index: float = 0.0
    euphoria_index: float = 0.0
    activity_level: float = 0.0


class HistoryPoint(BaseModel):
    """A single point in time series data."""

    timestamp: str
    date: str  # Formatted date for display
    sentiment_score: float
    btc_price: Optional[float] = None
    fear_greed_index: Optional[int] = None
    # Bull vs Bear indices
    fear_index: float = 0.0  # Bearish/panic signals
    euphoria_index: float = 0.0  # Bullish/FOMO signals
    activity_level: float = 0.0  # Market activity indicator


class DashboardHistory(BaseModel):
    """Historical time series data for charts."""

    days: int
    data: list[HistoryPoint]


class SourceRanking(BaseModel):
    """Source accuracy ranking."""

    source: str
    weight: float
    accuracy: Optional[float] = None
    is_contrarian: bool = False
    sample_size: int = 0
    type_label: str = "Neutral"  # "Momentum", "Contrarian", "Neutral"


class SourceRankings(BaseModel):
    """All source rankings."""

    sources: list[SourceRanking]
    last_updated: Optional[str] = None


class AffiliateLink(BaseModel):
    """An affiliate link recommendation."""

    name: str
    description: str
    url: str
    category: str  # "exchange", "wallet", "tools", "tax"


class AffiliateResponse(BaseModel):
    """Contextual affiliate recommendations."""

    context: str  # "high_volatility", "general"
    recommendations: list[AffiliateLink]


class SourceBelief(BaseModel):
    """Bayesian belief for a single source."""

    source: str
    alpha: float
    beta: float
    accuracy: Optional[float] = None
    correlation: Optional[float] = None
    is_contrarian: bool = False
    total_crawls: int = 0
    last_updated: Optional[str] = None
    # Computed fields
    belief_mean: float  # alpha / (alpha + beta)
    belief_std: float  # Standard deviation of Beta distribution
    type_label: str = "Neutral"  # "Momentum", "Contrarian", "Neutral"


class BeliefsResponse(BaseModel):
    """All Bayesian beliefs from the model."""

    beliefs: list[SourceBelief]
    baseline_informativeness: float = 0.5
    total_crawls: int = 0
    last_belief_update: Optional[str] = None


class SourceSentimentPoint(BaseModel):
    """A single sentiment data point for a source."""

    timestamp: str
    date: str
    sentiment_score: float
    fear_index: float = 0.0
    euphoria_index: float = 0.0
    activity_level: float = 0.0
    sample_size: int = 0


class SourceSentimentHistory(BaseModel):
    """Sentiment history for a specific source."""

    source: str
    days: int
    data: list[SourceSentimentPoint]


class AllSourcesHistory(BaseModel):
    """Sentiment history for all sources (for comparison charts)."""

    days: int
    sources: dict[str, list[SourceSentimentPoint]]
