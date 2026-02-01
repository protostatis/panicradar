"""Dashboard API routes."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from .affiliates import get_affiliates_for_context
from .queries import (
    compute_beta_std,
    get_all_sources_sentiment_history,
    get_available_sources,
    get_db_connection,
    get_fear_greed_history,
    get_latest_confounders,
    get_latest_price,
    get_latest_sentiment,
    get_price_change,
    get_price_history,
    get_sentiment_history,
    get_source_sentiment_history,
    get_source_type_label as get_source_type_label_query,
    get_source_weights,
    load_bayesian_beliefs,
    merge_history_data,
)
from .schemas import (
    AffiliateLink,
    AffiliateResponse,
    AllSourcesHistory,
    BeliefsResponse,
    CoinPrice,
    DashboardHistory,
    DashboardSummary,
    HistoryPoint,
    SourceBelief,
    SourceRanking,
    SourceRankings,
    SourceSentimentHistory,
    SourceSentimentPoint,
)

router = APIRouter(prefix="/api", tags=["dashboard"])

DB_PATH = os.environ.get("DB_PATH", "data/sentiment.db")
STATE_PATH = os.environ.get("STATE_PATH", "data/orchestrator_state.json")


def get_sentiment_state(score: float) -> str:
    """Convert sentiment score to human-readable state."""
    if score > 0.2:
        return "Bullish"
    elif score < -0.2:
        return "Bearish"
    return "Neutral"


def get_fear_greed_label(index: int | None) -> str:
    """Convert fear & greed index to human-readable label."""
    if index is None:
        return "Unknown"
    if index <= 20:
        return "Extreme Fear"
    elif index <= 40:
        return "Fear"
    elif index <= 60:
        return "Neutral"
    elif index <= 80:
        return "Greed"
    return "Extreme Greed"


def get_volatility_state(volatility: float | None) -> str:
    """Convert volatility percentage to human-readable state."""
    if volatility is None:
        return "Unknown"
    if volatility < 2:
        return "Low"
    elif volatility < 4:
        return "Moderate"
    elif volatility < 6:
        return "High"
    return "Extreme"


def get_source_type_label(accuracy: float | None, is_contrarian: bool) -> str:
    """Get source type label based on accuracy and contrarian status."""
    if is_contrarian:
        return "Contrarian"
    if accuracy is not None and accuracy > 0.5:
        return "Momentum"
    return "Neutral"


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def get_dashboard_summary():
    """
    Get current dashboard summary metrics.

    Returns current sentiment score, fear & greed index, volatility,
    and multi-dimensional crowd psychology indicators.
    """
    conn = get_db_connection(DB_PATH)
    try:
        # Get latest data from each source
        sentiment = get_latest_sentiment(conn)
        confounders = get_latest_confounders(conn)
        price = get_latest_price(conn, "BTC")
        change_24h = get_price_change(conn, "BTC", 24)
        change_7d = get_price_change(conn, "BTC", 168)  # 7 * 24 hours

        sentiment_score = sentiment["sentiment_score"]
        fear_greed = confounders["fear_greed_index"]
        volatility = confounders["volatility_24h"]

        return DashboardSummary(
            timestamp=datetime.now(timezone.utc).isoformat(),
            sentiment_score=round(sentiment_score, 3),
            sentiment_state=get_sentiment_state(sentiment_score),
            fear_greed_index=fear_greed,
            fear_greed_label=get_fear_greed_label(fear_greed),
            volatility_24h=volatility,
            volatility_state=get_volatility_state(volatility),
            btc_price=price["price"],
            btc_change_24h=round(change_24h, 2) if change_24h else None,
            btc_change_7d=round(change_7d, 2) if change_7d else None,
            fear_index=round(sentiment["fear_index"], 3),
            euphoria_index=round(sentiment["euphoria_index"], 3),
            activity_level=round(sentiment["activity_level"], 3),
        )
    finally:
        conn.close()


@router.get("/dashboard/history", response_model=DashboardHistory)
async def get_dashboard_history(
    days: int = Query(30, ge=1, le=90, description="Number of days of history"),
):
    """
    Get historical time series data for charts.

    Returns daily sentiment scores, BTC prices, and fear & greed index
    for the specified number of days.
    """
    conn = get_db_connection(DB_PATH)
    try:
        sentiment = get_sentiment_history(conn, days)
        prices = get_price_history(conn, "BTC", days)
        fear_greed = get_fear_greed_history(conn, days)

        merged = merge_history_data(sentiment, prices, fear_greed)

        history_points = [
            HistoryPoint(
                timestamp=point["timestamp"],
                date=point["date"],
                sentiment_score=round(point["sentiment_score"], 3),
                btc_price=point["btc_price"],
                fear_greed_index=point["fear_greed_index"],
                fear_index=round(point.get("fear_index", 0), 4),
                euphoria_index=round(point.get("euphoria_index", 0), 4),
                activity_level=round(point.get("activity_level", 0), 4),
            )
            for point in merged
        ]

        return DashboardHistory(days=days, data=history_points)
    finally:
        conn.close()


@router.get("/dashboard/sources", response_model=SourceRankings)
async def get_source_rankings():
    """
    Get source accuracy rankings.

    Returns sources ranked by their predictive weight, including
    accuracy, contrarian status, and sample size.
    """
    conn = get_db_connection(DB_PATH)
    try:
        result = get_source_weights(conn)

        rankings = [
            SourceRanking(
                source=s["source"],
                weight=round(s["weight"], 4),
                accuracy=round(s["accuracy"], 3) if s["accuracy"] else None,
                is_contrarian=s["is_contrarian"],
                sample_size=s["sample_size"],
                type_label=get_source_type_label(s["accuracy"], s["is_contrarian"]),
            )
            for s in result["sources"]
        ]

        return SourceRankings(
            sources=rankings,
            last_updated=result["last_updated"],
        )
    finally:
        conn.close()


@router.get("/affiliates", response_model=AffiliateResponse)
async def get_affiliates():
    """
    Get contextual affiliate recommendations.

    Returns affiliate links appropriate for the current market volatility.
    High volatility shows trading/security partners, low volatility shows
    general tools and services.
    """
    conn = get_db_connection(DB_PATH)
    try:
        confounders = get_latest_confounders(conn)
        volatility_state = get_volatility_state(confounders["volatility_24h"])

        context, affiliates = get_affiliates_for_context(volatility_state)

        return AffiliateResponse(
            context=context,
            recommendations=[AffiliateLink(**a) for a in affiliates],
        )
    finally:
        conn.close()


@router.get("/dashboard/beliefs", response_model=BeliefsResponse)
async def get_bayesian_beliefs():
    """
    Get current Bayesian beliefs from the model.

    Returns all source beliefs with alpha/beta parameters, accuracy,
    correlation, and contrarian status. Beliefs are updated daily
    based on observed prediction accuracy.
    """
    state = load_bayesian_beliefs(STATE_PATH)

    beliefs = []
    for source, belief in state.get("beliefs", {}).items():
        alpha = belief.get("alpha", 1.0)
        beta = belief.get("beta", 1.0)
        accuracy = belief.get("accuracy")
        is_contrarian = belief.get("is_contrarian", False)

        beliefs.append(
            SourceBelief(
                source=source,
                alpha=round(alpha, 2),
                beta=round(beta, 2),
                accuracy=round(accuracy, 4) if accuracy is not None else None,
                correlation=round(belief.get("correlation", 0), 4)
                if belief.get("correlation") is not None
                else None,
                is_contrarian=is_contrarian,
                total_crawls=belief.get("total_crawls", 0),
                last_updated=belief.get("last_updated"),
                belief_mean=round(alpha / (alpha + beta), 4) if (alpha + beta) > 0 else 0.5,
                belief_std=round(compute_beta_std(alpha, beta), 4),
                type_label=get_source_type_label_query(accuracy, is_contrarian),
            )
        )

    # Sort by total_crawls descending (most active sources first)
    beliefs.sort(key=lambda b: b.total_crawls, reverse=True)

    return BeliefsResponse(
        beliefs=beliefs,
        baseline_informativeness=state.get("baseline_informativeness", 0.5),
        total_crawls=state.get("total_crawls", 0),
        last_belief_update=state.get("last_belief_update"),
    )


@router.get("/dashboard/sources/{source}/history", response_model=SourceSentimentHistory)
async def get_source_history(
    source: str,
    days: int = Query(30, ge=1, le=90, description="Number of days of history"),
):
    """
    Get sentiment history for a specific source/subreddit.

    Returns daily sentiment scores and sample sizes for the specified
    source over the given time period.
    """
    conn = get_db_connection(DB_PATH)
    try:
        history = get_source_sentiment_history(conn, source, days)

        return SourceSentimentHistory(
            source=source,
            days=days,
            data=[
                SourceSentimentPoint(
                    timestamp=point["timestamp"],
                    date=point["date"],
                    sentiment_score=round(point["sentiment_score"], 3),
                    fear_index=round(point.get("fear_index", 0), 4),
                    euphoria_index=round(point.get("euphoria_index", 0), 4),
                    activity_level=round(point.get("activity_level", 0), 4),
                    sample_size=point["sample_size"],
                )
                for point in history
            ],
        )
    finally:
        conn.close()


@router.get("/dashboard/sources/history/all", response_model=AllSourcesHistory)
async def get_all_sources_history(
    days: int = Query(30, ge=1, le=90, description="Number of days of history"),
):
    """
    Get sentiment history for all active sources.

    Returns daily sentiment data for all sources with sufficient data,
    useful for comparison charts.
    """
    conn = get_db_connection(DB_PATH)
    try:
        all_history = get_all_sources_sentiment_history(conn, days)

        formatted = {}
        for source, history in all_history.items():
            formatted[source] = [
                SourceSentimentPoint(
                    timestamp=point["timestamp"],
                    date=point["date"],
                    sentiment_score=round(point["sentiment_score"], 3),
                    fear_index=round(point.get("fear_index", 0), 4),
                    euphoria_index=round(point.get("euphoria_index", 0), 4),
                    activity_level=round(point.get("activity_level", 0), 4),
                    sample_size=point["sample_size"],
                )
                for point in history
            ]

        return AllSourcesHistory(days=days, sources=formatted)
    finally:
        conn.close()


@router.get("/dashboard/sources/list")
async def get_sources_list():
    """
    Get list of all available sources with sentiment data.

    Returns source names that can be used with the source history endpoint.
    """
    conn = get_db_connection(DB_PATH)
    try:
        sources = get_available_sources(conn)
        return {"sources": sources, "count": len(sources)}
    finally:
        conn.close()


@router.get("/dashboard/coins")
async def get_coins_list():
    """
    Get list of all available coins with price data.
    """
    conn = get_db_connection(DB_PATH)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT coin FROM price_data ORDER BY coin"
        )
        coins = [row["coin"] for row in cursor.fetchall()]
        return {"coins": coins, "count": len(coins)}
    finally:
        conn.close()


@router.get("/dashboard/coins/{coin}", response_model=CoinPrice)
async def get_coin_price(coin: str):
    """
    Get price data for a specific coin including 24h, 7d, and 30d changes.
    """
    conn = get_db_connection(DB_PATH)
    try:
        price = get_latest_price(conn, coin.upper())
        change_24h = get_price_change(conn, coin.upper(), 24)
        change_7d = get_price_change(conn, coin.upper(), 168)  # 7 * 24
        change_30d = get_price_change(conn, coin.upper(), 720)  # 30 * 24

        return CoinPrice(
            coin=coin.upper(),
            price=price["price"],
            change_24h=round(change_24h, 2) if change_24h else None,
            change_7d=round(change_7d, 2) if change_7d else None,
            change_30d=round(change_30d, 2) if change_30d else None,
        )
    finally:
        conn.close()


@router.get("/dashboard/coins/{coin}/history")
async def get_coin_price_history(
    coin: str,
    days: int = Query(30, ge=1, le=90, description="Number of days of history"),
):
    """
    Get price history for a specific coin.
    """
    conn = get_db_connection(DB_PATH)
    try:
        prices = get_price_history(conn, coin.upper(), days)
        return {
            "coin": coin.upper(),
            "days": days,
            "data": [
                {
                    "date": p["date"],
                    "timestamp": f"{p['date']}T00:00:00Z",
                    "price": p["price"],
                }
                for p in prices
            ],
        }
    finally:
        conn.close()
