"""Regression tests for window filters on ISO-8601 timestamps.

Timestamps are stored with ``datetime.isoformat()`` (``2026-11-10T00:39:07+00:00``),
but SQLite's ``datetime('now', ...)`` returns a space-separated string
(``2026-11-10 14:05:00``). Lexicographically ``'T'`` (0x54) sorts after ``' '``
(0x20), so a cutoff in the second format admits every row on the cutoff *date*
that sorts after the ``T`` — silently widening a 24 h window to as much as ~38 h.

These tests pin the behaviour of the fix (``iso_cutoff_sql``) at the level users
observe: the Reddit panic score's ``total_posts`` for the last 24 hours.
"""

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crypto_sentiment_crawler.dashboard.queries import get_reddit_panic_score
from crypto_sentiment_crawler.sqlite_utils import connect_sqlite, iso_cutoff_sql
from crypto_sentiment_crawler.storage.db import SCHEMA

MOD_24_HOURS = "'-24 hours'"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect_sqlite(tmp_path / "test.db")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    yield connection
    connection.close()


def _insert_post(conn: sqlite3.Connection, raw_id: int, published: datetime) -> None:
    """Insert one Reddit post and its score at a given instant."""
    conn.execute(
        "INSERT INTO sentiment_raw (id, timestamp, source, coin, raw_data, content_hash) "
        "VALUES (?, ?, 'reddit_bitcoin', 'BTC', '{}', ?)",
        (raw_id, published.isoformat(), f"hash-{raw_id}"),
    )
    conn.execute(
        "INSERT INTO user_sentiment_scores "
        "(raw_id, timestamp, coin, final_score, fear_index, euphoria_index, activity_level) "
        "VALUES (?, ?, 'BTC', -0.4, 0.0, 0.0, 0.0)",
        (raw_id, published.isoformat()),
    )
    conn.commit()


class TestIsoCutoffSql:
    def test_cutoff_is_iso_t_without_timezone_gap(self, conn):
        cutoff = conn.execute(f"SELECT {iso_cutoff_sql(MOD_24_HOURS)}").fetchone()[0]

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", cutoff)
        # A space-separated cutoff is exactly the bug this guards against.
        assert " " not in cutoff

    def test_cutoff_sorts_between_same_day_rows(self, conn):
        """Early-morning rows on the cutoff date must sort before the cutoff."""
        conn.execute("CREATE TEMP TABLE probe (ts TEXT)")
        conn.executemany(
            "INSERT INTO probe (ts) VALUES (?)",
            [
                ("2026-11-10T00:39:07+00:00",),
                ("2026-11-10T13:40:36+00:00",),
            ],
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM probe WHERE ts >= '2026-11-10T13:40:36'"
        ).fetchone()[0]
        assert count == 1


class TestPanicScoreWindow:
    def test_excludes_post_older_than_24_hours(self, conn):
        """A post from 00:00 UTC yesterday is 24-48 h old and must be excluded.

        This is the exact shape the space-separated cutoff let through: the row
        sorts after ``' '`` because of the ``T``, so it was counted as part of
        "the last 24 hours" for the whole day.
        """
        now = datetime.now(timezone.utc)
        yesterday_midnight = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=1, microsecond=0
        )
        assert (now - yesterday_midnight) > timedelta(hours=24)

        _insert_post(conn, 1, yesterday_midnight)

        assert get_reddit_panic_score(conn)["total_posts"] == 0

    def test_includes_post_within_24_hours(self, conn):
        """Positive control — the filter still finds real window content."""
        now = datetime.now(timezone.utc)
        _insert_post(conn, 1, now - timedelta(hours=2))

        assert get_reddit_panic_score(conn)["total_posts"] == 1

    def test_mixed_window_counts_only_fresh_posts(self, conn):
        now = datetime.now(timezone.utc)
        yesterday_midnight = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=1, microsecond=0
        )
        _insert_post(conn, 1, now - timedelta(hours=1))
        _insert_post(conn, 2, now - timedelta(hours=23))
        _insert_post(conn, 3, yesterday_midnight)
        _insert_post(conn, 4, now - timedelta(hours=48))

        assert get_reddit_panic_score(conn)["total_posts"] == 2
