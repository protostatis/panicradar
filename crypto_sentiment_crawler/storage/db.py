"""Database operations using aiosqlite."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..config import settings
from ..logging_config import logger
from .migrations import run_all_migrations
from .models import OnChainMetric, PriceData, SentimentRaw

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    source VARCHAR(50) NOT NULL,
    coin VARCHAR(10),
    raw_data JSON NOT NULL,
    content_hash VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    coin VARCHAR(10) NOT NULL,
    price_usd FLOAT NOT NULL,
    volume_24h FLOAT,
    market_cap FLOAT,
    source VARCHAR(50) DEFAULT 'coingecko'
);

CREATE TABLE IF NOT EXISTS on_chain_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    coin VARCHAR(10) NOT NULL,
    metric_type VARCHAR(50) NOT NULL,
    value FLOAT NOT NULL,
    metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_price_data_time ON price_data(timestamp, coin);
CREATE INDEX IF NOT EXISTS idx_on_chain_time ON on_chain_metrics(timestamp, coin);
CREATE INDEX IF NOT EXISTS idx_sentiment_raw_time ON sentiment_raw(timestamp, source);

-- User-centric sentiment scoring with multi-dimensional signals
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL,
    total_posts INTEGER DEFAULT 0,
    avg_sentiment FLOAT,
    sentiment_stddev FLOAT,
    bullish_pct FLOAT,
    bearish_pct FLOAT,
    tendency VARCHAR(30),
    accuracy_score FLOAT,
    credibility_weight FLOAT DEFAULT 1.0,
    first_seen DATETIME,
    last_seen DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(username, source)
);

CREATE TABLE IF NOT EXISTS user_sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES user_profiles(user_id),
    raw_id INTEGER REFERENCES sentiment_raw(id),
    timestamp DATETIME,
    coin TEXT,
    title_score REAL,
    body_score REAL,
    segment_scores TEXT,
    final_score REAL,
    aggregation_method TEXT DEFAULT 'title_weighted',
    pos_count INTEGER DEFAULT 0,
    neg_count INTEGER DEFAULT 0,
    neu_count INTEGER DEFAULT 0,
    activity_level REAL DEFAULT 0,
    fear_index REAL DEFAULT 0,
    euphoria_index REAL DEFAULT 0,
    segments_filtered INTEGER DEFAULT 0,
    segments_scored INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_source ON user_profiles(source);
CREATE INDEX IF NOT EXISTS idx_user_scores_user ON user_sentiment_scores(user_id);
CREATE INDEX IF NOT EXISTS idx_user_scores_timestamp ON user_sentiment_scores(timestamp);
CREATE INDEX IF NOT EXISTS idx_user_scores_raw ON user_sentiment_scores(raw_id);
CREATE INDEX IF NOT EXISTS idx_user_scores_final ON user_sentiment_scores(final_score);

-- Source weights for Bayesian inference
CREATE TABLE IF NOT EXISTS source_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source VARCHAR(50) NOT NULL UNIQUE,
    weight FLOAT NOT NULL,
    accuracy FLOAT,
    is_contrarian BOOLEAN DEFAULT FALSE,
    alpha FLOAT,
    beta FLOAT,
    sample_size INTEGER,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_source_weights_source ON source_weights(source);

-- Confounders (Fear & Greed, VIX, etc.)
CREATE TABLE IF NOT EXISTS confounders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    fear_greed_index INTEGER,
    fear_greed_label VARCHAR(20),
    vix FLOAT,
    news_sentiment FLOAT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_confounders_timestamp ON confounders(timestamp);

-- Pipeline job status used by the operational health endpoint.
CREATE TABLE IF NOT EXISTS pipeline_heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    last_success_at TIMESTAMP,
    last_error_at TIMESTAMP,
    last_error_message TEXT,
    freshness_seconds REAL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_heartbeats_component_id
ON pipeline_heartbeats(component, id DESC);

-- Persistent prediction outcome ledger for auditable evaluation
CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    signal_timestamp TIMESTAMP NOT NULL,
    target_timestamp TIMESTAMP NOT NULL,
    calibrated_score REAL,
    price_before REAL,
    price_after REAL,
    price_before_timestamp TIMESTAMP,
    price_after_timestamp TIMESTAMP,
    direction TEXT,
    correct BOOLEAN,
    abstained BOOLEAN DEFAULT FALSE,
    price_gap_seconds REAL,
    evaluated_at TIMESTAMP,
    evaluator_version TEXT,
    UNIQUE(source, signal_timestamp, evaluator_version)
);
"""

MIGRATIONS = [
    "ALTER TABLE sentiment_raw ADD COLUMN content_hash VARCHAR(64);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sentiment_raw_hash ON sentiment_raw(content_hash);",
    """
    CREATE TABLE IF NOT EXISTS pipeline_heartbeats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component TEXT NOT NULL,
        last_success_at TIMESTAMP,
        last_error_at TIMESTAMP,
        last_error_message TEXT,
        freshness_seconds REAL,
        metadata TEXT
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pipeline_heartbeats_component_id
    ON pipeline_heartbeats(component, id DESC);
    """,
]


class Database:
    """Async database wrapper for SQLite."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

        # Run schema migrations for existing databases
        for migration in MIGRATIONS:
            try:
                await self._connection.execute(migration)
                await self._connection.commit()
            except Exception:
                pass  # Column already exists

        # Run data migrations (one-time cleanups, etc.)
        await run_all_migrations(self._connection)

        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def record_heartbeat(
        self,
        component: str,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Append a status event for a scheduler component."""
        now = datetime.now(timezone.utc)
        previous_success = await self.conn.execute(
            """
            SELECT last_success_at
            FROM pipeline_heartbeats
            WHERE component = ? AND last_success_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (component,),
        )
        previous_row = await previous_success.fetchone()

        if success:
            last_success_at = now
            freshness_seconds = 0.0
            last_error_at = None
            last_error_message = None
        else:
            last_success_at = (
                datetime.fromisoformat(previous_row["last_success_at"])
                if previous_row and previous_row["last_success_at"]
                else None
            )
            if last_success_at is not None and last_success_at.tzinfo is None:
                last_success_at = last_success_at.replace(tzinfo=timezone.utc)
            freshness_seconds = (
                (now - last_success_at).total_seconds()
                if last_success_at is not None
                else None
            )
            last_error_at = now
            last_error_message = error_message

        await self.conn.execute(
            """
            INSERT INTO pipeline_heartbeats (
                component, last_success_at, last_error_at, last_error_message,
                freshness_seconds, metadata
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                component,
                last_success_at.isoformat() if last_success_at else None,
                last_error_at.isoformat() if last_error_at else None,
                last_error_message,
                freshness_seconds,
                json.dumps(metadata) if metadata is not None else None,
            ),
        )
        await self.conn.commit()

    async def get_latest_heartbeat(self, component: str) -> dict | None:
        """Return the most recent heartbeat for one component."""
        cursor = await self.conn.execute(
            """
            SELECT * FROM pipeline_heartbeats
            WHERE component = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (component,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_heartbeats(self) -> dict[str, dict]:
        """Return each component's most recent heartbeat."""
        cursor = await self.conn.execute(
            """
            SELECT heartbeat.*
            FROM pipeline_heartbeats heartbeat
            INNER JOIN (
                SELECT component, MAX(id) AS latest_id
                FROM pipeline_heartbeats
                GROUP BY component
            ) latest ON heartbeat.id = latest.latest_id
            """
        )
        rows = await cursor.fetchall()
        return {row["component"]: dict(row) for row in rows}

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection."""
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    def _compute_content_hash(self, source: str, raw_data: dict) -> str:
        """Compute a hash for deduplication based on source and URL/title."""
        # Use URL if available, otherwise use source + title
        url = raw_data.get("url", "")
        title = raw_data.get("title", "")
        unique_key = f"{source}:{url or title}"
        return hashlib.sha256(unique_key.encode()).hexdigest()

    async def insert_sentiment_raw(self, data: SentimentRaw) -> int:
        """Insert raw sentiment data, skipping duplicates."""
        content_hash = self._compute_content_hash(data.source, data.raw_data)

        # Check if already exists
        cursor = await self.conn.execute(
            "SELECT id FROM sentiment_raw WHERE content_hash = ?",
            (content_hash,),
        )
        existing = await cursor.fetchone()
        if existing:
            return 0  # Skip duplicate

        source = data.source.lower()
        cursor = await self.conn.execute(
            """
            INSERT INTO sentiment_raw (timestamp, source, coin, raw_data, content_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.timestamp.isoformat(),
                source,
                data.coin,
                json.dumps(data.raw_data),
                content_hash,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def insert_price_data(self, data: PriceData) -> int:
        """Insert price data."""
        cursor = await self.conn.execute(
            """
            INSERT INTO price_data (timestamp, coin, price_usd, volume_24h, market_cap, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.timestamp.isoformat(),
                data.coin,
                data.price_usd,
                data.volume_24h,
                data.market_cap,
                data.source,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def insert_on_chain_metric(self, data: OnChainMetric) -> int:
        """Insert on-chain metric."""
        cursor = await self.conn.execute(
            """
            INSERT INTO on_chain_metrics (timestamp, coin, metric_type, value, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.timestamp.isoformat(),
                data.coin,
                data.metric_type,
                data.value,
                json.dumps(data.metadata) if data.metadata else None,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def insert_sentiment_score(self, data) -> int:
        """Stub for deprecated sentiment_scores table.

        This method is kept for backwards compatibility with collectors
        that haven't been updated to use user_sentiment_scores yet.
        Data is not stored - use UserSentimentScorer for new scoring.
        """
        logger.debug(f"insert_sentiment_score called (deprecated) - data not stored")
        return 0

    async def get_latest_prices(self, coin: str, limit: int = 100) -> list[PriceData]:
        """Get latest prices for a coin."""
        cursor = await self.conn.execute(
            """
            SELECT timestamp, coin, price_usd, volume_24h, market_cap, source
            FROM price_data
            WHERE coin = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (coin, limit),
        )
        rows = await cursor.fetchall()
        return [
            PriceData(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                coin=row["coin"],
                price_usd=row["price_usd"],
                volume_24h=row["volume_24h"],
                market_cap=row["market_cap"],
                source=row["source"],
            )
            for row in rows
        ]

    # ── Prediction outcome ledger ──────────────────────────────────────────

    async def upsert_outcome(
        self,
        source: str,
        signal_timestamp: datetime,
        target_timestamp: datetime,
        calibrated_score: float | None = None,
        price_before: float | None = None,
        price_before_timestamp: datetime | None = None,
        evaluator_version: str = "1.0",
    ) -> int:
        """Insert or update an outcome row (idempotent via UNIQUE constraint).

        Returns the row id.
        """
        cursor = await self.conn.execute(
            """
            INSERT INTO prediction_outcomes
                (source, signal_timestamp, target_timestamp, calibrated_score,
                 price_before, price_before_timestamp, evaluator_version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, signal_timestamp, evaluator_version) DO UPDATE SET
                target_timestamp = excluded.target_timestamp,
                calibrated_score = excluded.calibrated_score,
                price_before = excluded.price_before,
                price_before_timestamp = excluded.price_before_timestamp
            """,
            (
                source.lower(),
                signal_timestamp.isoformat(),
                target_timestamp.isoformat(),
                calibrated_score,
                price_before,
                price_before_timestamp.isoformat() if price_before_timestamp else None,
                evaluator_version,
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def get_pending_outcomes(
        self, now: datetime | None = None
    ) -> list[dict]:
        """Find outcomes whose target_timestamp has elapsed but haven't been evaluated.

        Returns rows where target_timestamp < now AND price_after IS NULL.
        """
        now = now or datetime.now(timezone.utc)
        cursor = await self.conn.execute(
            """
            SELECT id, source, signal_timestamp, target_timestamp,
                   calibrated_score, price_before, price_before_timestamp
            FROM prediction_outcomes
            WHERE target_timestamp < ?
              AND price_after IS NULL
              AND abstained = FALSE
            ORDER BY signal_timestamp ASC
            """,
            (now.isoformat(),),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def mark_outcome_evaluated(
        self,
        outcome_id: int,
        price_after: float,
        price_after_timestamp: datetime,
        correct: bool,
        direction: str,
        price_gap_seconds: float | None = None,
    ) -> None:
        """Update an outcome row with evaluation results."""
        await self.conn.execute(
            """
            UPDATE prediction_outcomes
            SET price_after = ?,
                price_after_timestamp = ?,
                correct = ?,
                direction = ?,
                price_gap_seconds = ?,
                evaluated_at = ?
            WHERE id = ?
            """,
            (
                price_after,
                price_after_timestamp.isoformat(),
                1 if correct else 0,
                direction,
                price_gap_seconds,
                datetime.now(timezone.utc).isoformat(),
                outcome_id,
            ),
        )
        await self.conn.commit()

    async def get_source_performance(
        self, source: str, days: int = 30
    ) -> dict:
        """Compute accuracy and stats for a source from the outcome ledger.

        Returns dict with total_evaluated, correct, accuracy, avg_gap_seconds.
        """
        cursor = await self.conn.execute(
            """
            SELECT
                COUNT(*) as total_evaluated,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct,
                AVG(price_gap_seconds) as avg_gap_seconds
            FROM prediction_outcomes
            WHERE source = ?
              AND evaluated_at IS NOT NULL
              AND correct IS NOT NULL
              AND evaluated_at >= datetime('now', '-' || ? || ' days')
            """,
            (source.lower(), days),
        )
        row = await cursor.fetchone()
        if row is None or row["total_evaluated"] == 0:
            return {"source": source, "total_evaluated": 0, "correct": 0,
                    "accuracy": None, "avg_gap_seconds": None}
        total = row["total_evaluated"]
        correct = row["correct"]
        return {
            "source": source,
            "total_evaluated": total,
            "correct": correct,
            "accuracy": correct / total if total > 0 else None,
            "avg_gap_seconds": row["avg_gap_seconds"],
        }
