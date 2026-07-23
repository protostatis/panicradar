"""Tests for persisted scheduler heartbeats."""

from pathlib import Path

from crypto_sentiment_crawler.storage.db import Database


async def test_records_and_reads_latest_heartbeat(tmp_path: Path):
    db = Database(tmp_path / "heartbeats.db")
    await db.connect()
    try:
        await db.record_heartbeat("crawl", metadata={"posts": 3})

        latest = await db.get_latest_heartbeat("crawl")

        assert latest is not None
        assert latest["component"] == "crawl"
        assert latest["last_success_at"] is not None
        assert latest["last_error_at"] is None
        assert latest["freshness_seconds"] == 0.0
        assert latest["metadata"] == '{"posts": 3}'
    finally:
        await db.close()


async def test_failed_heartbeat_preserves_last_success(tmp_path: Path):
    db = Database(tmp_path / "heartbeats.db")
    await db.connect()
    try:
        await db.record_heartbeat("price")
        success = await db.get_latest_heartbeat("price")

        await db.record_heartbeat("price", success=False, error_message="timeout")
        latest = await db.get_latest_heartbeat("price")

        assert latest is not None
        assert latest["last_success_at"] == success["last_success_at"]
        assert latest["last_error_at"] is not None
        assert latest["last_error_message"] == "timeout"
        assert latest["freshness_seconds"] is not None
    finally:
        await db.close()


async def test_lists_latest_heartbeat_for_each_component(tmp_path: Path):
    db = Database(tmp_path / "heartbeats.db")
    await db.connect()
    try:
        await db.record_heartbeat("crawl")
        await db.record_heartbeat("price")
        await db.record_heartbeat("crawl", success=False, error_message="temporary")

        heartbeats = await db.get_all_heartbeats()

        assert set(heartbeats) == {"crawl", "price"}
        assert heartbeats["crawl"]["last_error_message"] == "temporary"
        assert heartbeats["price"]["last_error_at"] is None
    finally:
        await db.close()
