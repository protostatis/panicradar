"""Tests for ghost source filtering in the belief updater.

Ghost sources are non-Reddit sources that have entries in source_weights
and/or orchestrator_state.json but zero rows in sentiment_raw. These are
artifacts migrated from an older system that were never populated.
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crypto_sentiment_crawler.analysis.belief_updater import (
    _find_ghost_sources,
    compute_source_accuracy,
    update_belief_priors,
)
from crypto_sentiment_crawler.storage.db import Database


# ====================================================================
#  Fixtures
# ====================================================================


@pytest.fixture
async def tmp_db():
    """Create a temporary SQLite database and clean it up after the test."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test.db"
    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()
    shutil.rmtree(tmp_dir)


# ====================================================================
#  Test helpers
# ====================================================================


async def _insert_sentiment_raw(db, raw_id: int, source: str, timestamp: str) -> None:
    await db.conn.execute(
        "INSERT INTO sentiment_raw (id, timestamp, source, coin, raw_data) "
        "VALUES (?, ?, ?, 'BTC', '{}')",
        (raw_id, timestamp, source),
    )


async def _insert_user_profile(db, user_id: int, username: str, source: str) -> None:
    await db.conn.execute(
        "INSERT INTO user_profiles (user_id, username, source) VALUES (?, ?, ?)",
        (user_id, username, source),
    )


async def _insert_sentiment_score(
    db, score_id: int, user_id: int, timestamp: str, final_score: float
) -> None:
    await db.conn.execute(
        "INSERT INTO user_sentiment_scores (id, user_id, timestamp, final_score) "
        "VALUES (?, ?, ?, ?)",
        (score_id, user_id, timestamp, final_score),
    )


async def _insert_price(db, timestamp: str, price_usd: float) -> None:
    await db.conn.execute(
        "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', ?)",
        (timestamp, price_usd),
    )


# ====================================================================
#  Tests
# ====================================================================


class TestFindGhostSources:
    """_find_ghost_sources identifies non-Reddit sources with zero sentiment_raw."""

    BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)

    async def test_identifies_ghost_source(self, tmp_db):
        """A non-Reddit source with zero sentiment_raw rows is identified as ghost."""
        beliefs = {
            "4chan_biz": {"alpha": 1.0, "beta": 1.0, "total_crawls": 0},
            "reddit_crypto": {"alpha": 5.0, "beta": 3.0, "total_crawls": 10},
        }
        # Insert sentiment_raw for reddit_crypto only
        await _insert_sentiment_raw(
            tmp_db, 1, "reddit_crypto", self.BASE.isoformat()
        )
        await tmp_db.conn.commit()

        ghosts = await _find_ghost_sources(tmp_db, beliefs)
        assert "4chan_biz" in ghosts
        assert "reddit_crypto" not in ghosts

    async def test_reddit_sources_are_never_ghosts(self, tmp_db):
        """Reddit sources are never flagged as ghosts, even with zero rows."""
        beliefs = {
            "reddit_crypto": {"alpha": 1.0, "beta": 1.0, "total_crawls": 0},
            "reddit_ethtrader": {"alpha": 1.0, "beta": 1.0, "total_crawls": 0},
        }
        ghosts = await _find_ghost_sources(tmp_db, beliefs)
        assert ghosts == []

    async def test_active_non_reddit_not_ghost(self, tmp_db):
        """A non-Reddit source WITH sentiment_raw is NOT a ghost."""
        beliefs = {
            "twitter": {"alpha": 3.0, "beta": 2.0, "total_crawls": 5},
        }
        await _insert_sentiment_raw(
            tmp_db, 1, "twitter", self.BASE.isoformat()
        )
        await tmp_db.conn.commit()

        ghosts = await _find_ghost_sources(tmp_db, beliefs)
        assert ghosts == []

    async def test_empty_beliefs_returns_empty(self, tmp_db):
        """Empty beliefs dict returns empty ghost list."""
        ghosts = await _find_ghost_sources(tmp_db, {})
        assert ghosts == []


class TestBeliefUpdaterFiltersGhosts:
    """The belief update pipeline removes ghost sources from results."""

    BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)

    async def test_ghost_source_excluded_from_beliefs(self, tmp_db, monkeypatch):
        """Ghost source is not present after update_belief_priors with ghost filtering."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.analysis.belief_updater.MIN_SAMPLES", 1
        )

        # ── Price data (hour 0..5) ────────────────────────────────
        prices = [50000.0, 50100.0, 50200.0, 50300.0, 50400.0, 50500.0]
        for i, p in enumerate(prices):
            await _insert_price(
                tmp_db, (self.BASE + timedelta(hours=i)).isoformat(), p
            )

        # ── Active source: reddit_crypto has data ─────────────────
        await _insert_user_profile(tmp_db, 1, "user1", "reddit_crypto")
        await _insert_sentiment_score(
            tmp_db, 1, 1, (self.BASE + timedelta(hours=0)).isoformat(), 0.30
        )
        await _insert_sentiment_raw(
            tmp_db, 1, "reddit_crypto", self.BASE.isoformat()
        )

        await tmp_db.conn.commit()

        # ── Run compute_source_accuracy ───────────────────────────
        source_accuracy = await compute_source_accuracy(
            tmp_db, lookback_days=100000
        )
        # Only reddit_crypto should have accuracy data
        assert "reddit_crypto" in source_accuracy

        # ── Simulate the full flow: beliefs before ghost filter ───
        current_beliefs = {
            "reddit_crypto": {
                "source": "reddit_crypto",
                "alpha": 1.0,
                "beta": 1.0,
                "total_crawls": 0,
            },
            "4chan_biz": {
                "source": "4chan_biz",
                "alpha": 10.0,
                "beta": 15.0,
                "total_crawls": 25,
            },
        }

        # ── Find and remove ghosts (same logic as update_orchestrator_beliefs) ──
        ghosts = await _find_ghost_sources(tmp_db, current_beliefs)
        for src in ghosts:
            current_beliefs.pop(src, None)

        assert "4chan_biz" not in current_beliefs, (
            "4chan_biz should have been removed as a ghost source"
        )
        assert "reddit_crypto" in current_beliefs

        # ── update_belief_priors with filtered beliefs ────────────
        updated = update_belief_priors(current_beliefs, source_accuracy)
        assert "reddit_crypto" in updated
        assert "4chan_biz" not in updated, (
            "4chan_biz should not appear in updated beliefs after ghost filtering"
        )
