"""Tests for shared SQLite runtime settings."""

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crypto_sentiment_crawler.processing.user_sentiment import (
    PostScore,
    SegmentScore,
    UserSentimentScorer,
)
from crypto_sentiment_crawler.sqlite_utils import (
    SQLITE_BUSY_TIMEOUT_MS,
    connect_sqlite,
    sqlite_transaction,
)
from crypto_sentiment_crawler.storage.db import SCHEMA, Database
from crypto_sentiment_crawler.storage.models import PriceData


def test_sync_connection_sets_busy_timeout(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "sync.db")
    try:
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        connection.close()

    assert timeout == SQLITE_BUSY_TIMEOUT_MS


def test_waiting_sync_writer_succeeds_after_lock_release(tmp_path: Path) -> None:
    db_path = tmp_path / "wait.db"
    with sqlite_transaction(db_path) as connection:
        connection.execute("CREATE TABLE events (value INTEGER)")

    blocker = connect_sqlite(db_path)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO events VALUES (1)")
    started = threading.Event()
    errors: list[Exception] = []

    def write_from_thread() -> None:
        started.set()
        try:
            with sqlite_transaction(db_path) as connection:
                connection.execute("INSERT INTO events VALUES (2)")
        except Exception as exc:  # pragma: no cover - asserted through errors
            errors.append(exc)

    worker = threading.Thread(target=write_from_thread)
    worker.start()
    assert started.wait(timeout=1)
    time.sleep(0.05)
    assert worker.is_alive()
    blocker.commit()
    blocker.close()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert errors == []
    connection = connect_sqlite(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    finally:
        connection.close()


def test_sync_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback.db"
    with sqlite_transaction(db_path) as connection:
        connection.execute("CREATE TABLE events (value INTEGER)")

    with pytest.raises(RuntimeError, match="abort"):
        with sqlite_transaction(db_path) as connection:
            connection.execute("INSERT INTO events VALUES (1)")
            raise RuntimeError("abort")

    connection = connect_sqlite(db_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        connection.close()


def test_user_score_writes_commit_through_safe_transactions(tmp_path: Path) -> None:
    db_path = tmp_path / "user-score.db"
    with sqlite_transaction(db_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT INTO sentiment_raw (id, timestamp, source, raw_data)
            VALUES (1, '2026-08-14T12:00:00+00:00', 'reddit_bitcoin', '{}')
            """
        )

    scorer = object.__new__(UserSentimentScorer)
    scorer.db_path = str(db_path)
    post_score = PostScore(
        raw_id=1,
        timestamp="2026-08-14T12:00:00+00:00",
        coin="BTC",
        username="alice",
        source="reddit_bitcoin",
        title="Bitcoin outlook",
        title_score=0.5,
        body_score=0.25,
        segment_scores=[SegmentScore("Bullish momentum", 0.25, 16)],
        final_score=0.3,
        aggregation_method="title_weighted",
        pos_count=2,
        neg_count=0,
        neu_count=0,
        segments_total=1,
        segments_scored=1,
    )

    score_id = scorer.save_post_score(post_score)
    assert score_id > 0
    assert scorer.save_post_score(post_score) == -1
    user_id = scorer.get_or_create_user(
        post_score.username,
        post_score.source,
        post_score.timestamp,
    )
    scorer.update_user_profile(user_id)

    connection = connect_sqlite(db_path)
    try:
        row = connection.execute(
            "SELECT total_posts, avg_sentiment FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row == (1, 0.3)


@pytest.mark.asyncio
async def test_async_database_sets_busy_timeout(tmp_path: Path) -> None:
    database = Database(tmp_path / "async.db")
    await database.connect()
    try:
        cursor = await database.conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
    finally:
        await database.close()

    assert row[0] == SQLITE_BUSY_TIMEOUT_MS


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_before_next_write(tmp_path: Path) -> None:
    db_path = tmp_path / "locked.db"
    database = Database(db_path)
    await database.connect()
    blocker = sqlite3.connect(db_path)

    try:
        blocker.execute("BEGIN")
        blocker.execute("SELECT * FROM price_data").fetchall()
        await database.conn.execute("PRAGMA busy_timeout = 25")

        price = PriceData(
            timestamp=datetime.now(timezone.utc),
            coin="BTC",
            price_usd=100.0,
        )
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            await database.insert_price_data(price)

        assert not database.conn.in_transaction

        blocker.rollback()
        await database.insert_price_data(price)
        cursor = await database.conn.execute("SELECT COUNT(*) FROM price_data")
        assert (await cursor.fetchone())[0] == 1
    finally:
        blocker.close()
        await database.close()
