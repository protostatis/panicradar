"""Database queries for dashboard data."""

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def get_db_connection(db_path: str = "data/sentiment.db") -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_sentiment(conn: sqlite3.Connection) -> dict:
    """Get the latest aggregated sentiment metrics from user_sentiment_scores, weighted by learned beliefs.

    Panic/FOMO indices are calculated as:
    - Percentage of posts with non-zero fear/euphoria signals
    - Weighted by the intensity of those signals
    This makes the indices more dynamic and meaningful than simple averaging.

    Uses rolling windows with fallback: 4 hours -> 24 hours -> 7 days
    """
    # Try progressively longer windows until we find data
    for hours in [4, 24, 168]:  # 4h, 24h, 7 days
        cursor = conn.execute(
            f"""
            WITH source_averages AS (
                SELECT
                    sr.source,
                    AVG(uss.final_score) as avg_score,
                    -- Calculate percentage of posts with fear signals, weighted by intensity
                    SUM(CASE WHEN uss.fear_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as fear_pct,
                    AVG(CASE WHEN uss.fear_index > 0 THEN uss.fear_index ELSE NULL END) as fear_intensity,
                    -- Calculate percentage of posts with euphoria signals, weighted by intensity
                    SUM(CASE WHEN uss.euphoria_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as euphoria_pct,
                    AVG(CASE WHEN uss.euphoria_index > 0 THEN uss.euphoria_index ELSE NULL END) as euphoria_intensity,
                    AVG(uss.activity_level) as avg_activity,
                    COUNT(*) as sample_count,
                    MAX(uss.timestamp) as latest_timestamp
                FROM user_sentiment_scores uss
                JOIN sentiment_raw sr ON uss.raw_id = sr.id
                WHERE uss.timestamp >= datetime('now', '-{hours} hours')
                  AND uss.final_score IS NOT NULL
                GROUP BY sr.source
            )
            SELECT
                SUM(
                    CASE WHEN COALESCE(sw.is_contrarian, 0) = 1
                         THEN -sa.avg_score
                         ELSE sa.avg_score
                    END * COALESCE(sw.weight, 0.01) * sa.sample_count
                ) / NULLIF(SUM(COALESCE(sw.weight, 0.01) * sa.sample_count), 0) as sentiment_score,
                -- Combine percentage and intensity: sqrt(pct * intensity) gives balanced signal
                AVG(sa.fear_pct * COALESCE(sa.fear_intensity, 0.5)) as fear_index,
                AVG(sa.euphoria_pct * COALESCE(sa.euphoria_intensity, 0.5)) as euphoria_index,
                -- Also provide raw percentages for display
                AVG(sa.fear_pct) as fear_pct,
                AVG(sa.euphoria_pct) as euphoria_pct,
                AVG(sa.avg_activity) as activity_level,
                MAX(sa.latest_timestamp) as latest_timestamp,
                SUM(sa.sample_count) as sample_count
            FROM source_averages sa
            LEFT JOIN source_weights sw ON sa.source = sw.source
            """
        )
        row = cursor.fetchone()

        if row and row["sentiment_score"] is not None:
            # Use percentage-based calculation for more dynamic indices
            fear_pct = row["fear_pct"] or 0.0
            euphoria_pct = row["euphoria_pct"] or 0.0

            return {
                "sentiment_score": row["sentiment_score"],
                # Show percentage of posts with fear/euphoria signals (more intuitive)
                "fear_index": fear_pct,
                "euphoria_index": euphoria_pct,
                "activity_level": row["activity_level"] or 0.0,
                "timestamp": row["latest_timestamp"],
                "sample_count": row["sample_count"] or 0,
            }

    return {
        "sentiment_score": 0.0,
        "fear_index": 0.0,
        "euphoria_index": 0.0,
        "activity_level": 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": 0,
    }


def get_latest_confounders(conn: sqlite3.Connection) -> dict:
    """Get the latest confounder data (fear & greed, volatility)."""
    cursor = conn.execute(
        """
        SELECT
            fear_greed_index,
            volatility_24h,
            timestamp
        FROM confounders
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()

    if row:
        return {
            "fear_greed_index": row["fear_greed_index"],
            "volatility_24h": row["volatility_24h"],
            "timestamp": row["timestamp"],
        }

    return {
        "fear_greed_index": None,
        "volatility_24h": None,
        "timestamp": None,
    }


def get_latest_price(conn: sqlite3.Connection, coin: str = "BTC") -> dict:
    """Get the latest price data for a coin."""
    cursor = conn.execute(
        """
        SELECT
            price_usd,
            timestamp
        FROM price_data
        WHERE coin = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (coin,),
    )
    row = cursor.fetchone()

    if row:
        return {
            "price": row["price_usd"],
            "timestamp": row["timestamp"],
        }

    return {"price": None, "timestamp": None}


def get_price_change(
    conn: sqlite3.Connection, coin: str = "BTC", hours: int = 24
) -> Optional[float]:
    """Calculate price change over the specified hours."""
    cursor = conn.execute(
        """
        SELECT price_usd, timestamp
        FROM price_data
        WHERE coin = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (coin,),
    )
    latest = cursor.fetchone()

    if not latest:
        return None

    # Get price from N hours ago
    cursor = conn.execute(
        """
        SELECT price_usd
        FROM price_data
        WHERE coin = ?
          AND timestamp <= datetime(?, '-' || ? || ' hours')
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (coin, latest["timestamp"], hours),
    )
    old = cursor.fetchone()

    if not old or old["price_usd"] == 0:
        return None

    return ((latest["price_usd"] - old["price_usd"]) / old["price_usd"]) * 100


def get_sentiment_history(
    conn: sqlite3.Connection, days: int = 30
) -> list[dict]:
    """Get sentiment history with rolling 4-hour windows for smooth, continuous values.

    Uses hourly buckets with rolling 4-hour aggregation to avoid midnight UTC resets.
    Each data point represents the aggregated sentiment from the previous 4 hours.
    """
    # First get hourly aggregates
    cursor = conn.execute(
        """
        SELECT
            strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
            AVG(final_score) as sentiment_score,
            SUM(CASE WHEN fear_index > 0 THEN 1.0 ELSE 0 END) as fear_posts,
            SUM(CASE WHEN euphoria_index > 0 THEN 1.0 ELSE 0 END) as euphoria_posts,
            SUM(activity_level) as total_activity,
            COUNT(*) as sample_count
        FROM user_sentiment_scores
        WHERE timestamp >= datetime('now', '-' || ? || ' days')
          AND final_score IS NOT NULL
        GROUP BY strftime('%Y-%m-%d %H', timestamp)
        ORDER BY hour ASC
        """,
        (days,),
    )

    hourly_data = [dict(row) for row in cursor.fetchall()]

    if not hourly_data:
        return []

    # Calculate rolling 4-hour aggregates
    results = []
    for i, row in enumerate(hourly_data):
        # Look back 4 hours (current hour + 3 previous)
        window_start = max(0, i - 3)
        window = hourly_data[window_start : i + 1]

        total_posts = sum(w["sample_count"] for w in window)
        if total_posts > 0:
            # Weighted average for sentiment score
            sentiment = (
                sum(w["sentiment_score"] * w["sample_count"] for w in window)
                / total_posts
            )
            # Percentage of posts with fear/euphoria signals across the window
            fear_pct = sum(w["fear_posts"] for w in window) / total_posts
            euphoria_pct = sum(w["euphoria_posts"] for w in window) / total_posts
            activity = sum(w["total_activity"] for w in window) / total_posts
        else:
            sentiment = fear_pct = euphoria_pct = activity = 0.0

        results.append({
            "date": row["hour"][:10],  # YYYY-MM-DD
            "timestamp": row["hour"].replace(" ", "T") + "Z",
            "sentiment_score": sentiment,
            "fear_index": fear_pct,
            "euphoria_index": euphoria_pct,
            "activity_level": activity,
            "sample_count": total_posts,
        })

    return results


def get_price_history(
    conn: sqlite3.Connection, coin: str = "BTC", days: int = 30
) -> list[dict]:
    """Get daily price history for charts."""
    cursor = conn.execute(
        """
        SELECT
            date(timestamp) as date,
            AVG(price_usd) as price
        FROM price_data
        WHERE coin = ?
          AND timestamp >= datetime('now', '-' || ? || ' days')
        GROUP BY date(timestamp)
        ORDER BY date ASC
        """,
        (coin, days),
    )

    return [
        {
            "date": row["date"],
            "price": row["price"],
        }
        for row in cursor.fetchall()
    ]


def get_fear_greed_history(conn: sqlite3.Connection, days: int = 30) -> list[dict]:
    """Get daily fear & greed index history."""
    cursor = conn.execute(
        """
        SELECT
            date(timestamp) as date,
            AVG(fear_greed_index) as fear_greed_index
        FROM confounders
        WHERE timestamp >= datetime('now', '-' || ? || ' days')
          AND fear_greed_index IS NOT NULL
        GROUP BY date(timestamp)
        ORDER BY date ASC
        """,
        (days,),
    )

    return [
        {
            "date": row["date"],
            "fear_greed_index": int(row["fear_greed_index"])
            if row["fear_greed_index"]
            else None,
        }
        for row in cursor.fetchall()
    ]


def get_source_weights(conn: sqlite3.Connection) -> list[dict]:
    """Get source accuracy rankings from source_weights table."""
    cursor = conn.execute(
        """
        SELECT
            source,
            weight,
            accuracy,
            is_contrarian,
            sample_size,
            last_updated
        FROM source_weights
        ORDER BY weight DESC
        """
    )

    sources = []
    last_updated = None

    for row in cursor.fetchall():
        sources.append(
            {
                "source": row["source"],
                "weight": row["weight"],
                "accuracy": row["accuracy"],
                "is_contrarian": bool(row["is_contrarian"]),
                "sample_size": int(row["sample_size"]) if row["sample_size"] else 0,
            }
        )
        if row["last_updated"]:
            last_updated = row["last_updated"]

    return {"sources": sources, "last_updated": last_updated}


def merge_history_data(
    sentiment: list[dict],
    prices: list[dict],
    fear_greed: list[dict],
) -> list[dict]:
    """Merge sentiment (hourly), price (daily), and fear/greed (daily) data.

    Sentiment data is hourly with rolling 4-hour windows.
    Price and fear/greed are matched by date to each hourly sentiment point.
    """
    # Create lookup dicts by date for daily data
    price_by_date = {p["date"]: p["price"] for p in prices}
    fg_by_date = {f["date"]: f["fear_greed_index"] for f in fear_greed}

    merged = []
    for s in sentiment:
        date = s["date"]  # YYYY-MM-DD extracted from hourly timestamp
        merged.append(
            {
                "date": date,
                "timestamp": s["timestamp"],  # Preserve hourly timestamp
                "sentiment_score": s["sentiment_score"],
                "btc_price": price_by_date.get(date),
                "fear_greed_index": fg_by_date.get(date),
                # Rolling 4-hour indices
                "fear_index": s.get("fear_index", 0),
                "euphoria_index": s.get("euphoria_index", 0),
                "activity_level": s.get("activity_level", 0),
            }
        )

    return merged


def load_bayesian_beliefs(state_path: str = "data/orchestrator_state.json") -> dict:
    """Load Bayesian beliefs from orchestrator state file."""
    path = Path(state_path)
    if not path.exists():
        return {
            "beliefs": {},
            "baseline_informativeness": 0.5,
            "total_crawls": 0,
            "last_belief_update": None,
        }

    with open(path) as f:
        state = json.load(f)

    return state


def compute_beta_std(alpha: float, beta: float) -> float:
    """Compute standard deviation of Beta distribution."""
    ab = alpha + beta
    if ab <= 0:
        return 0.0
    variance = (alpha * beta) / (ab * ab * (ab + 1))
    return math.sqrt(variance)


def get_source_type_label(accuracy: Optional[float], is_contrarian: bool) -> str:
    """Get source type label based on accuracy and contrarian status."""
    if is_contrarian:
        return "Contrarian"
    if accuracy is not None and accuracy > 0.52:
        return "Momentum"
    return "Neutral"


def get_source_sentiment_history(
    conn: sqlite3.Connection, source: str, days: int = 30
) -> list[dict]:
    """Get sentiment history for a specific source with rolling 4-hour windows.

    Uses hourly buckets with rolling 4-hour aggregation for smooth values.
    """
    # Get hourly aggregates for this source
    cursor = conn.execute(
        """
        SELECT
            strftime('%Y-%m-%d %H:00:00', uss.timestamp) as hour,
            AVG(uss.final_score) as sentiment_score,
            SUM(CASE WHEN uss.fear_index > 0 THEN 1.0 ELSE 0 END) as fear_posts,
            SUM(CASE WHEN uss.euphoria_index > 0 THEN 1.0 ELSE 0 END) as euphoria_posts,
            SUM(uss.activity_level) as total_activity,
            COUNT(*) as sample_size
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE sr.source = ?
          AND uss.timestamp >= datetime('now', '-' || ? || ' days')
          AND uss.final_score IS NOT NULL
        GROUP BY strftime('%Y-%m-%d %H', uss.timestamp)
        ORDER BY hour ASC
        """,
        (source, days),
    )

    hourly_data = [dict(row) for row in cursor.fetchall()]

    if not hourly_data:
        return []

    # Calculate rolling 4-hour aggregates
    results = []
    for i, row in enumerate(hourly_data):
        window_start = max(0, i - 3)
        window = hourly_data[window_start : i + 1]

        total_posts = sum(w["sample_size"] for w in window)
        if total_posts > 0:
            sentiment = (
                sum(w["sentiment_score"] * w["sample_size"] for w in window)
                / total_posts
            )
            fear_pct = sum(w["fear_posts"] for w in window) / total_posts
            euphoria_pct = sum(w["euphoria_posts"] for w in window) / total_posts
            activity = sum(w["total_activity"] for w in window) / total_posts
        else:
            sentiment = fear_pct = euphoria_pct = activity = 0.0

        results.append({
            "date": row["hour"][:10],
            "timestamp": row["hour"].replace(" ", "T") + "Z",
            "sentiment_score": sentiment,
            "fear_index": fear_pct,
            "euphoria_index": euphoria_pct,
            "activity_level": activity,
            "sample_size": total_posts,
        })

    return results


def get_all_sources_sentiment_history(
    conn: sqlite3.Connection, days: int = 30, min_samples: int = 10
) -> dict[str, list[dict]]:
    """Get daily sentiment history for all sources with sufficient data (user-based scoring only)."""
    # Get all sources with user_sentiment_scores data
    cursor = conn.execute(
        """
        SELECT DISTINCT sr.source
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE uss.timestamp >= datetime('now', '-' || ? || ' days')
          AND uss.final_score IS NOT NULL
        GROUP BY sr.source
        HAVING COUNT(*) >= ?
        """,
        (days, min_samples),
    )

    sources = [row["source"] for row in cursor.fetchall()]

    result = {}
    for source in sources:
        history = get_source_sentiment_history(conn, source, days)
        if history:
            result[source] = history

    return result


def get_available_sources(conn: sqlite3.Connection) -> list[str]:
    """Get list of all available sources with user-based sentiment data."""
    cursor = conn.execute(
        """
        SELECT DISTINCT sr.source, COUNT(*) as count
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE uss.timestamp >= datetime('now', '-30 days')
          AND uss.final_score IS NOT NULL
        GROUP BY sr.source
        ORDER BY count DESC
        """
    )

    return [row["source"] for row in cursor.fetchall()]


def get_reddit_panic_score(conn: sqlite3.Connection) -> dict:
    """Calculate panic score from Reddit posts in the last 24 hours.

    Uses a 5-component formula designed for dynamic range:
    A. Absolute bearish base (0-25 pts) — percentage of bearish posts
    B. Relative sentiment shift (0-25 pts) — today vs 7-day rolling baseline
    C. Negative intensity (0-20 pts) — how negative the negative posts are
    D. Market fear context (0-25 pts) — inverted crypto Fear & Greed Index
    E. Fear keyword bonus (0-5 pts) — pattern-matched fear signals

    Returns a score from 0-100 where higher = more panic.
    """
    # 1. Get current 24h Reddit sentiment data
    cursor = conn.execute(
        """
        SELECT
            COUNT(*) as total_posts,
            SUM(CASE WHEN uss.final_score < -0.1 THEN 1 ELSE 0 END) as bearish_posts,
            SUM(CASE WHEN uss.final_score > 0.1 THEN 1 ELSE 0 END) as bullish_posts,
            SUM(CASE WHEN uss.fear_index > 0 THEN 1 ELSE 0 END) as explicit_fear_posts,
            AVG(uss.final_score) as avg_sentiment,
            AVG(CASE WHEN uss.final_score < 0 THEN uss.final_score ELSE NULL END) as avg_negative_sentiment,
            MIN(uss.final_score) as most_negative
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE uss.timestamp >= datetime('now', '-24 hours')
          AND uss.final_score IS NOT NULL
          AND sr.source LIKE 'reddit_%'
        """
    )
    row = cursor.fetchone()

    if not row or row["total_posts"] == 0:
        return {
            "panic_score": 0,
            "total_posts": 0,
            "bearish_posts": 0,
            "bullish_posts": 0,
            "avg_sentiment": 0,
            "sentiment_label": "No Data"
        }

    total = row["total_posts"]
    bearish_posts = row["bearish_posts"] or 0
    bullish_posts = row["bullish_posts"] or 0
    explicit_fear = row["explicit_fear_posts"] or 0
    avg_sentiment = row["avg_sentiment"] or 0
    avg_negative = row["avg_negative_sentiment"] or 0

    # 2. Get 7-day rolling baseline (excluding last 24h) for relative comparison
    baseline_row = conn.execute(
        """
        SELECT AVG(uss.final_score) as baseline_sentiment
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE uss.timestamp >= datetime('now', '-8 days')
          AND uss.timestamp < datetime('now', '-24 hours')
          AND uss.final_score IS NOT NULL
          AND sr.source LIKE 'reddit_%'
        """
    ).fetchone()
    baseline_sentiment = baseline_row["baseline_sentiment"] if baseline_row else None

    # 3. Get latest Fear & Greed Index from confounders
    fgi_row = conn.execute(
        """
        SELECT fear_greed_index
        FROM confounders
        WHERE fear_greed_index IS NOT NULL AND fear_greed_index > 0
        ORDER BY timestamp DESC
        LIMIT 1
        """
    ).fetchone()
    fear_greed_index = fgi_row["fear_greed_index"] if fgi_row else None

    # Calculate panic score (0-100) using 5 components
    bearish_pct = bearish_posts / total if total > 0 else 0

    # A. Absolute bearish base (0-25 points)
    # Percentage of posts with negative sentiment
    base_panic = bearish_pct * 25

    # B. Relative sentiment shift vs 7-day baseline (0-25 points)
    # Measures how much worse today is compared to recent history.
    # A delta of -0.1 (today is 0.1 more negative than baseline) = max 25 pts
    if baseline_sentiment is not None:
        sentiment_delta = baseline_sentiment - avg_sentiment  # positive = today is worse
        relative_panic = min(25, max(0, sentiment_delta / 0.1 * 25))
    else:
        # No baseline available — fall back to absolute sentiment shift
        relative_panic = max(0, min(25, -avg_sentiment * 50))

    # C. Negative intensity (0-20 points)
    # How negative are the negative posts? Rescaled divisor from 0.5 to 0.3
    # to match actual data range (avg_negative typically -0.19 to -0.27)
    intensity = min(1.0, abs(avg_negative) / 0.3) if avg_negative else 0
    intensity_panic = intensity * 20

    # D. Market fear context (0-25 points)
    # Inverted Fear & Greed Index: FGI=0 (extreme fear) → 25 pts, FGI=100 (greed) → 0 pts
    if fear_greed_index is not None:
        fgi_panic = (100 - fear_greed_index) / 100.0 * 25
    else:
        fgi_panic = 0

    # E. Fear keyword bonus (0-5 points)
    fear_bonus = min(5, (explicit_fear / total) * 20) if total > 0 else 0

    panic_score = min(100, max(0, base_panic + relative_panic + intensity_panic + fgi_panic + fear_bonus))

    # Determine label
    if panic_score >= 60:
        label = "High Panic"
    elif panic_score >= 40:
        label = "Elevated"
    elif panic_score >= 20:
        label = "Moderate"
    else:
        label = "Calm"

    return {
        "panic_score": round(panic_score, 1),
        "total_posts": total,
        "bearish_posts": bearish_posts,
        "bullish_posts": bullish_posts,
        "avg_sentiment": round(avg_sentiment, 3) if avg_sentiment else 0,
        "sentiment_label": label
    }


def get_daily_sentiment_counts(
    conn: sqlite3.Connection, days: int = 30, source: Optional[str] = None
) -> list[dict]:
    """Get daily counts of bullish vs bearish posts.

    Returns raw counts per day for diverging bar chart visualization.
    Bull = posts with euphoria_index > 0
    Bear = posts with fear_index > 0
    Neutral = posts with neither
    """
    if source:
        cursor = conn.execute(
            """
            SELECT
                date(uss.timestamp) as date,
                SUM(CASE WHEN uss.euphoria_index > 0 AND uss.fear_index <= 0 THEN 1 ELSE 0 END) as bull_count,
                SUM(CASE WHEN uss.fear_index > 0 AND uss.euphoria_index <= 0 THEN 1 ELSE 0 END) as bear_count,
                SUM(CASE WHEN uss.euphoria_index > 0 AND uss.fear_index > 0 THEN 1 ELSE 0 END) as mixed_count,
                SUM(CASE WHEN uss.euphoria_index <= 0 AND uss.fear_index <= 0 THEN 1 ELSE 0 END) as neutral_count,
                COUNT(*) as total_count
            FROM user_sentiment_scores uss
            JOIN sentiment_raw sr ON uss.raw_id = sr.id
            WHERE uss.timestamp >= datetime('now', '-' || ? || ' days')
              AND uss.final_score IS NOT NULL
              AND sr.source = ?
            GROUP BY date(uss.timestamp)
            ORDER BY date ASC
            """,
            (days, source),
        )
    else:
        cursor = conn.execute(
            """
            SELECT
                date(uss.timestamp) as date,
                SUM(CASE WHEN uss.euphoria_index > 0 AND uss.fear_index <= 0 THEN 1 ELSE 0 END) as bull_count,
                SUM(CASE WHEN uss.fear_index > 0 AND uss.euphoria_index <= 0 THEN 1 ELSE 0 END) as bear_count,
                SUM(CASE WHEN uss.euphoria_index > 0 AND uss.fear_index > 0 THEN 1 ELSE 0 END) as mixed_count,
                SUM(CASE WHEN uss.euphoria_index <= 0 AND uss.fear_index <= 0 THEN 1 ELSE 0 END) as neutral_count,
                COUNT(*) as total_count
            FROM user_sentiment_scores uss
            WHERE uss.timestamp >= datetime('now', '-' || ? || ' days')
              AND uss.final_score IS NOT NULL
            GROUP BY date(uss.timestamp)
            ORDER BY date ASC
            """,
            (days,),
        )

    return [
        {
            "date": row["date"],
            "bull_count": row["bull_count"] or 0,
            "bear_count": row["bear_count"] or 0,
            "mixed_count": row["mixed_count"] or 0,
            "neutral_count": row["neutral_count"] or 0,
            "total_count": row["total_count"] or 0,
        }
        for row in cursor.fetchall()
    ]
