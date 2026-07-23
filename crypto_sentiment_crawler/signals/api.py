"""REST API for the Contrarian Signal Service."""

import os
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .service import SignalService
from .subscriptions import SubscriptionManager, SubscriptionTier, TIERS
from ..dashboard import router as dashboard_router
from ..storage.db import SCHEMA


def init_database_schema(db_path: str) -> None:
    """Initialize database schema on startup."""
    from pathlib import Path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database schema initialized: {db_path}")


# Initialize services
db_path = os.environ.get("DATABASE_PATH", os.environ.get("DB_PATH", "data/sentiment.db"))

# Initialize database schema before starting
init_database_schema(db_path)

signal_service = SignalService(db_path=db_path)
subscription_manager = SubscriptionManager()

# Initialize FastAPI app
app = FastAPI(
    title="Crypto Contrarian Signals API",
    description="""
    API for detecting sentiment-price divergences in cryptocurrency markets.

    ## Signal Types

    - **BULLISH_DIVERGENCE**: Extreme fear + stable/rising price
    - **BEARISH_DIVERGENCE**: Extreme greed + stable/falling price
    - **CAPITULATION**: Extreme panic (often marks bottoms)
    - **EUPHORIA**: Extreme greed (often marks tops)

    ## Multi-Dimensional Signals

    Beyond simple sentiment scores, the API provides segment-level analysis:

    - **activity_level**: Proportion of scam/warning content (high = active market)
    - **fear_index**: Proportion of loss/panic mentions (high = contrarian BUY)
    - **euphoria_index**: Proportion of moon/FOMO mentions (high = contrarian SELL)

    These are derived from categorizing individual sentences/paragraphs in posts.

    ## Pricing

    - **Free**: 3 signals/week, BTC only
    - **Pro** ($9.99/mo): Unlimited signals, all coins
    - **Enterprise** ($49.99/mo): API access, priority support
    """,
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include dashboard routes
app.include_router(dashboard_router)


# Response models
class MarketSummary(BaseModel):
    """Current market sentiment summary with multi-dimensional signals."""

    coin: str
    timestamp: str
    current_price: float
    price_change_24h: float
    price_change_7d: float
    sentiment_score: float
    sentiment_zscore: float
    sentiment_state: str
    divergence_score: float
    # Multi-dimensional signals from segment categorization
    # Deprecated aliases — kept for one release
    activity_level: float = 0.0
    fear_index: float = 0.0
    euphoria_index: float = 0.0
    # New honest names
    warning_scam_phrase_rate: float = 0.0
    explicit_fear_phrase_rate: float = 0.0
    explicit_euphoria_phrase_rate: float = 0.0


class SignalResponse(BaseModel):
    """A detected signal."""

    timestamp: str
    signal_type: str
    strength: str
    coin: str
    sentiment_score: float
    sentiment_zscore: float
    price_change_24h: float
    price_change_7d: float
    divergence_score: float
    description: str
    confidence: float


class TierInfo(BaseModel):
    """Subscription tier information."""

    name: str
    price: str
    signals: str
    coins: str
    priority: str
    api: str


class SubscribeRequest(BaseModel):
    """Request to subscribe."""

    email: str
    tier: str = "pro"


class SubscribeResponse(BaseModel):
    """Response with checkout URL."""

    checkout_url: str


# Endpoints
@app.get("/")
async def root():
    """API root - returns service info."""
    return {
        "name": "Crypto Contrarian Signals API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "market": "/market/{coin}",
            "signals": "/signals",
            "pricing": "/pricing",
            "docs": "/docs",
        },
    }


@app.get("/market/{coin}", response_model=MarketSummary)
async def get_market_summary(coin: str = "BTC"):
    """
    Get current market sentiment summary for a coin.

    - **coin**: Cryptocurrency symbol (e.g., BTC, ETH)
    """
    try:
        summary = await signal_service.get_market_summary()
        if "error" in summary:
            raise HTTPException(status_code=503, detail=summary["error"])
        return MarketSummary(**summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals")
async def get_signals(
    coin: str = Query("BTC", description="Coin to check"),
    api_key: Optional[str] = Query(None, description="API key for Enterprise tier"),
):
    """
    Check for current contrarian signals.

    Returns any active signals or indicates no signal detected.
    """
    # Check API key for enterprise access
    # TODO: Implement API key validation

    try:
        signal = await signal_service.check_signals()

        if signal is None:
            return {
                "signal_detected": False,
                "message": "No signal at this time. Conditions are within normal ranges.",
                "checked_at": datetime.now().isoformat(),
            }

        return {
            "signal_detected": True,
            "signal": SignalResponse(**signal.to_dict()),
            "checked_at": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals/history")
async def get_signal_history(
    limit: int = Query(10, ge=1, le=100, description="Number of signals to return"),
    api_key: Optional[str] = Query(None, description="API key for Enterprise tier"),
):
    """
    Get recent signal history.

    Requires Enterprise API access.
    """
    # TODO: Implement API key validation
    signals = signal_service.alert_manager.get_signal_history(limit)

    return {
        "count": len(signals),
        "signals": [SignalResponse(**s.to_dict()) for s in signals],
    }


@app.get("/pricing", response_model=list[TierInfo])
async def get_pricing():
    """Get subscription tier pricing information."""
    return [
        TierInfo(**subscription_manager.get_tier_info(tier))
        for tier in [
            SubscriptionTier.FREE,
            SubscriptionTier.PRO,
            SubscriptionTier.ENTERPRISE,
        ]
    ]


@app.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(request: SubscribeRequest):
    """
    Start subscription checkout.

    Returns a Stripe checkout URL for payment.
    """
    tier = SubscriptionTier.PRO if request.tier == "pro" else SubscriptionTier.ENTERPRISE

    # Generate a user ID from email (in production, use proper auth)
    user_id = f"user_{hash(request.email) % 1000000}"

    checkout_url = await subscription_manager.upgrade_to_pro(user_id, request.email)
    if not checkout_url:
        raise HTTPException(
            status_code=503,
            detail="Payment processing not configured. Contact support.",
        )

    return SubscribeResponse(checkout_url=checkout_url)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


def run_api(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_api()
