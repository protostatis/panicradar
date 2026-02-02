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
    """
    # Join user_sentiment_scores with sentiment_raw to get source, then apply source weights
    # Contrarian sources have their sentiment inverted
    cursor = conn.execute(
        """
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
            WHERE uss.timestamp >= datetime('now', '-4 hours')
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
    """Get daily sentiment history for charts including bull/bear indices.

    Uses percentage-based calculation for fear/euphoria to show more dynamic values.
    """
    cursor = conn.execute(
        """
        SELECT
            date(timestamp) as date,
            AVG(final_score) as sentiment_score,
            -- Percentage of posts with fear/euphoria signals (more meaningful than avg)
            SUM(CASE WHEN fear_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as fear_index,
            SUM(CASE WHEN euphoria_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as euphoria_index,
            AVG(activity_level) as activity_level,
            COUNT(*) as sample_count
        FROM user_sentiment_scores
        WHERE timestamp >= datetime('now', '-' || ? || ' days')
          AND final_score IS NOT NULL
        GROUP BY date(timestamp)
        ORDER BY date ASC
        """,
        (days,),
    )

    return [
        {
            "date": row["date"],
            "sentiment_score": row["sentiment_score"],
            "fear_index": row["fear_index"] or 0,
            "euphoria_index": row["euphoria_index"] or 0,
            "activity_level": row["activity_level"] or 0,
            "sample_count": row["sample_count"] or 0,
        }
        for row in cursor.fetchall()
    ]


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
    """Merge sentiment, price, and fear/greed data by date."""
    # Create lookup dicts
    price_by_date = {p["date"]: p["price"] for p in prices}
    fg_by_date = {f["date"]: f["fear_greed_index"] for f in fear_greed}

    merged = []
    for s in sentiment:
        date = s["date"]
        merged.append(
            {
                "date": date,
                "timestamp": f"{date}T00:00:00Z",
                "sentiment_score": s["sentiment_score"],
                "btc_price": price_by_date.get(date),
                "fear_greed_index": fg_by_date.get(date),
                # Bull vs Bear indices
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
    """Get daily sentiment history for a specific source including bull/bear indices.

    Uses percentage-based calculation for fear/euphoria.
    """
    # Query from user_sentiment_scores joined with sentiment_raw to get source-specific data
    cursor = conn.execute(
        """
        SELECT
            date(uss.timestamp) as date,
            AVG(uss.final_score) as sentiment_score,
            -- Percentage of posts with fear/euphoria signals
            SUM(CASE WHEN uss.fear_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as fear_index,
            SUM(CASE WHEN uss.euphoria_index > 0 THEN 1.0 ELSE 0 END) / COUNT(*) as euphoria_index,
            AVG(uss.activity_level) as activity_level,
            COUNT(*) as sample_size
        FROM user_sentiment_scores uss
        JOIN sentiment_raw sr ON uss.raw_id = sr.id
        WHERE sr.source = ?
          AND uss.timestamp >= datetime('now', '-' || ? || ' days')
          AND uss.final_score IS NOT NULL
        GROUP BY date(uss.timestamp)
        ORDER BY date ASC
        """,
        (source, days),
    )

    results = cursor.fetchall()

    return [
        {
            "date": row["date"],
            "timestamp": f"{row['date']}T00:00:00Z",
            "sentiment_score": row["sentiment_score"] or 0,
            "fear_index": row["fear_index"] or 0,
            "euphoria_index": row["euphoria_index"] or 0,
            "activity_level": row["activity_level"] or 0,
            "sample_size": row["sample_size"] or 0,
        }
        for row in results
    ]


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
