"""Database operations using aiosqlite."""

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from ..config import settings
from ..logging_config import logger
from .models import OnChainMetric, PriceData, SentimentRaw, SentimentScore

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    source VARCHAR(50) NOT NULL,
    coin VARCHAR(10),
    raw_data JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    coin VARCHAR(10) NOT NULL,
    source VARCHAR(50) NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT,
    sample_size INTEGER,
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

CREATE INDEX IF NOT EXISTS idx_sentiment_scores_time ON sentiment_scores(timestamp, coin);
CREATE INDEX IF NOT EXISTS idx_price_data_time ON price_data(timestamp, coin);
CREATE INDEX IF NOT EXISTS idx_on_chain_time ON on_chain_metrics(timestamp, coin);
CREATE INDEX IF NOT EXISTS idx_sentiment_raw_time ON sentiment_raw(timestamp, source);
"""


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
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection."""
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def insert_sentiment_raw(self, data: SentimentRaw) -> int:
        """Insert raw sentiment data."""
        cursor = await self.conn.execute(
            """
            INSERT INTO sentiment_raw (timestamp, source, coin, raw_data)
            VALUES (?, ?, ?, ?)
            """,
            (
                data.timestamp.isoformat(),
                data.source,
                data.coin,
                json.dumps(data.raw_data),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid or 0

    async def insert_sentiment_score(self, data: SentimentScore) -> int:
        """Insert a processed sentiment score."""
        cursor = await self.conn.execute(
            """
            INSERT INTO sentiment_scores (timestamp, coin, source, score, confidence, sample_size)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.timestamp.isoformat(),
                data.coin,
                data.source,
                data.score,
                data.confidence,
                data.sample_size,
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

    async def get_latest_sentiment_scores(
        self, coin: str, limit: int = 100
    ) -> list[SentimentScore]:
        """Get latest sentiment scores for a coin."""
        cursor = await self.conn.execute(
            """
            SELECT timestamp, coin, source, score, confidence, sample_size
            FROM sentiment_scores
            WHERE coin = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (coin, limit),
        )
        rows = await cursor.fetchall()
        return [
            SentimentScore(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                coin=row["coin"],
                source=row["source"],
                score=row["score"],
                confidence=row["confidence"],
                sample_size=row["sample_size"],
            )
            for row in rows
        ]

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
