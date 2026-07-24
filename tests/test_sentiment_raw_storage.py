"""Regression coverage for raw sentiment persistence."""

from datetime import datetime, timezone

from crypto_sentiment_crawler.storage.db import Database
from crypto_sentiment_crawler.storage.models import SentimentRaw


async def test_inserts_raw_sentiment_and_skips_duplicate(tmp_path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    raw = SentimentRaw(
        timestamp=datetime(2026, 7, 24, tzinfo=timezone.utc),
        source="Reddit_Bitcoin",
        coin="BTC",
        raw_data={"url": "https://www.reddit.com/r/Bitcoin/comments/example", "title": "Test"},
    )

    try:
        raw_id = await db.insert_sentiment_raw(raw)

        assert raw_id > 0
        cursor = await db.conn.execute(
            "SELECT source, content_hash FROM sentiment_raw WHERE id = ?", (raw_id,)
        )
        row = await cursor.fetchone()
        assert row["source"] == "reddit_bitcoin"
        assert row["content_hash"]
        assert await db.insert_sentiment_raw(raw) == 0
    finally:
        await db.close()
