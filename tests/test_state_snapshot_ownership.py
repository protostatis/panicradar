"""Tests for single-writer orchestrator belief snapshots."""

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from crypto_sentiment_crawler.analysis.belief_updater import (
    update_orchestrator_beliefs,
)
from crypto_sentiment_crawler.analysis.source_weights import (
    load_weights_from_db_sync,
    save_weights_to_db,
)
from crypto_sentiment_crawler.bayesian.beliefs import SourceBelief
from crypto_sentiment_crawler.orchestrator import CrawlerOrchestrator, OrchestratorState
from crypto_sentiment_crawler.scheduler import CrawlerScheduler
from crypto_sentiment_crawler.storage.db import Database


def test_legacy_state_defaults_belief_version_to_zero():
    state = OrchestratorState.from_dict(
        {
            "beliefs": {},
            "baseline_informativeness": 0.5,
            "total_crawls": 4,
        }
    )

    assert state.belief_version == 0
    assert state.belief_revision == 0
    assert OrchestratorState.from_dict(state.to_dict()).belief_version == 0
    assert OrchestratorState.from_dict({"belief_version": 4}).belief_revision == 4


async def test_uninitialized_shutdown_does_not_write_state(tmp_path: Path):
    state_path = tmp_path / "state.json"
    orchestrator = CrawlerOrchestrator(
        Database(tmp_path / "sentiment.db"),
        sources={},
        state_path=str(state_path),
    )

    await orchestrator.shutdown()

    assert not state_path.exists()


async def test_shutdown_is_idempotent_after_releasing_state_ownership(tmp_path: Path):
    state_path = tmp_path / "state.json"
    orchestrator = CrawlerOrchestrator(
        Database(tmp_path / "sentiment.db"),
        sources={},
        state_path=str(state_path),
    )
    orchestrator._initialized = True
    orchestrator.fetcher = None
    orchestrator._state_file_lock.acquire(blocking=False)

    await orchestrator.shutdown()
    first_state = state_path.read_text()
    orchestrator.state.belief_version = 99
    await orchestrator.shutdown()

    assert not orchestrator._state_file_lock.is_held
    assert state_path.read_text() == first_state


async def test_compute_only_updater_never_writes_state_file(tmp_path: Path):
    state_path = tmp_path / "orchestrator_state.json"
    original_state = '{"sentinel": true}'
    state_path.write_text(original_state)
    db_path = tmp_path / "sentiment.db"

    base_beliefs = {
        "reddit_bitcoin": {
            "source": "reddit_bitcoin",
            "alpha": 1.0,
            "beta": 1.0,
        }
    }
    updated_beliefs = {
        "reddit_bitcoin": {
            "source": "reddit_bitcoin",
            "alpha": 3.0,
            "beta": 2.0,
            "accuracy": 0.6,
        }
    }

    with (
        patch(
            "crypto_sentiment_crawler.analysis.belief_updater.compute_source_accuracy",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "crypto_sentiment_crawler.analysis.belief_updater.update_belief_priors",
            return_value=updated_beliefs,
        ),
        patch(
            "crypto_sentiment_crawler.analysis.source_weights.save_weights_to_db",
            new=AsyncMock(),
        ) as save_weights,
    ):
        result = await update_orchestrator_beliefs(
            state_path=str(state_path),
            db_path=str(db_path),
            base_beliefs=base_beliefs,
            persist_state=False,
        )

    assert result == updated_beliefs
    assert state_path.read_text() == original_state
    save_weights.assert_not_awaited()


async def test_scheduler_applies_compute_only_snapshot():
    scheduler = CrawlerScheduler()
    base_beliefs = {"reddit_bitcoin": {"source": "reddit_bitcoin"}}
    updated_beliefs = {"reddit_bitcoin": {"source": "reddit_bitcoin", "alpha": 2.0}}
    orchestrator = SimpleNamespace(
        db=SimpleNamespace(db_path=Path("/tmp/sentiment.db")),
        snapshot_beliefs=AsyncMock(return_value=(base_beliefs, 7)),
        apply_belief_snapshot=AsyncMock(return_value=1),
    )
    scheduler.orchestrator = orchestrator

    with patch(
        "crypto_sentiment_crawler.analysis.belief_updater.update_orchestrator_beliefs",
        new=AsyncMock(return_value=updated_beliefs),
    ) as updater:
        await scheduler._job_belief_update()

    updater.assert_awaited_once_with(
        db_path="/tmp/sentiment.db",
        base_beliefs=base_beliefs,
        persist_state=False,
    )
    orchestrator.apply_belief_snapshot.assert_awaited_once_with(
        updated_beliefs,
        expected_revision=7,
    )
    assert scheduler._stats["belief_updates"] == 1


async def test_scheduler_retries_a_stale_snapshot():
    scheduler = CrawlerScheduler()
    base_beliefs = {"reddit_bitcoin": {"source": "reddit_bitcoin"}}
    updated_beliefs = {"reddit_bitcoin": {"source": "reddit_bitcoin", "alpha": 2.0}}
    orchestrator = SimpleNamespace(
        db=SimpleNamespace(db_path=Path("/tmp/sentiment.db")),
        snapshot_beliefs=AsyncMock(side_effect=[(base_beliefs, 1), (base_beliefs, 2)]),
        apply_belief_snapshot=AsyncMock(side_effect=[None, 3]),
    )
    scheduler.orchestrator = orchestrator

    with patch(
        "crypto_sentiment_crawler.analysis.belief_updater.update_orchestrator_beliefs",
        new=AsyncMock(return_value=updated_beliefs),
    ) as updater:
        await scheduler._job_belief_update()

    assert updater.await_count == 2
    assert orchestrator.apply_belief_snapshot.await_args_list[0].kwargs == {
        "expected_revision": 1,
    }
    assert orchestrator.apply_belief_snapshot.await_args_list[1].kwargs == {
        "expected_revision": 2,
    }
    assert scheduler._stats["belief_updates"] == 1


async def test_shutdown_drains_running_crawl_before_closing_orchestrator():
    scheduler = CrawlerScheduler()
    crawl_started = asyncio.Event()
    finish_crawl = asyncio.Event()

    async def select_and_crawl():
        crawl_started.set()
        await finish_crawl.wait()
        return []

    orchestrator = SimpleNamespace(
        select_and_crawl=select_and_crawl,
        shutdown=AsyncMock(),
    )
    scheduler.orchestrator = orchestrator
    crawl_task = asyncio.create_task(scheduler._job_crawl())
    await crawl_started.wait()
    shutdown_task = asyncio.create_task(scheduler.shutdown())
    await asyncio.sleep(0)

    assert not shutdown_task.done()
    finish_crawl.set()
    await crawl_task
    await shutdown_task
    orchestrator.shutdown.assert_awaited_once()


async def test_snapshot_preserves_lifecycle_and_version(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    state_path = tmp_path / "orchestrator_state.json"
    orchestrator = CrawlerOrchestrator(db, sources={}, state_path=str(state_path))
    existing = SourceBelief(source="reddit_bitcoin", alpha=2.0, beta=3.0)
    existing.status = "inactive"
    existing.consecutive_empty_crawls = 7
    orchestrator.belief_store.beliefs[existing.source] = existing
    orchestrator.state.belief_version = 4
    orchestrator.state.belief_revision = 4

    with (
        patch.object(orchestrator, "_stage_source_weights", new=AsyncMock()) as stage,
        patch.object(orchestrator, "_sync_source_weights", new=AsyncMock()) as sync,
    ):
        version = await orchestrator.apply_belief_snapshot(
            {
                "reddit_bitcoin": {
                    "source": "reddit_bitcoin",
                    "alpha": 9.0,
                    "beta": 2.0,
                    "accuracy": 0.8,
                }
            },
            expected_revision=4,
        )

    persisted = json.loads(state_path.read_text())
    belief = persisted["beliefs"]["reddit_bitcoin"]
    assert version == 5
    assert persisted["belief_version"] == 5
    assert belief["alpha"] == 9.0
    assert belief["status"] == "inactive"
    assert belief["consecutive_empty_crawls"] == 7
    stage.assert_awaited_once()
    sync.assert_awaited_once()
    assert sync.await_args.args[1] == 5

    await orchestrator._save_state()
    persisted_after_save = json.loads(state_path.read_text())
    assert persisted_after_save["belief_version"] == 5


async def test_stale_snapshot_is_rejected_without_overwriting_live_belief(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    orchestrator = CrawlerOrchestrator(db, sources={}, state_path=str(tmp_path / "state.json"))
    live_belief = SourceBelief(source="reddit_bitcoin", alpha=2.0, beta=4.0)
    orchestrator.belief_store.beliefs[live_belief.source] = live_belief
    orchestrator.state.belief_version = 3
    orchestrator.state.belief_revision = 3

    result = await orchestrator.apply_belief_snapshot(
        {
            "reddit_bitcoin": {
                "source": "reddit_bitcoin",
                "alpha": 9.0,
                "beta": 1.0,
            }
        },
        expected_revision=2,
    )

    assert result is None
    assert orchestrator.belief_store.get("reddit_bitcoin").beta == 4.0


async def test_weight_stage_failure_does_not_publish_belief_state(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    state_path = tmp_path / "state.json"
    orchestrator = CrawlerOrchestrator(db, sources={}, state_path=str(state_path))
    orchestrator.belief_store.beliefs["reddit_bitcoin"] = SourceBelief(
        source="reddit_bitcoin",
        alpha=2.0,
        beta=3.0,
    )
    orchestrator.state.belief_version = 3
    orchestrator.state.belief_revision = 3

    with patch.object(
        orchestrator,
        "_stage_source_weights",
        new=AsyncMock(side_effect=RuntimeError("database unavailable")),
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await orchestrator.apply_belief_snapshot(
                {
                    "reddit_bitcoin": {
                        "source": "reddit_bitcoin",
                        "alpha": 9.0,
                        "beta": 1.0,
                    }
                },
                expected_revision=3,
            )

    assert orchestrator.state.belief_version == 3
    assert orchestrator.state.belief_revision == 3
    assert orchestrator.belief_store.get("reddit_bitcoin").alpha == 2.0
    assert not state_path.exists()


async def test_weight_publish_failure_keeps_staged_snapshot_readable(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    state_path = tmp_path / "orchestrator_state.json"
    try:
        orchestrator = CrawlerOrchestrator(db, sources={}, state_path=str(state_path))
        with patch.object(
            orchestrator,
            "_sync_source_weights",
            new=AsyncMock(side_effect=RuntimeError("current-weight publish failed")),
        ):
            with pytest.raises(RuntimeError, match="current-weight publish failed"):
                await orchestrator.apply_belief_snapshot(
                    {
                        "reddit_bitcoin": {
                            "source": "reddit_bitcoin",
                            "alpha": 3.0,
                            "beta": 2.0,
                            "type_label": "insufficient_data",
                        }
                    },
                    expected_revision=0,
                )
        loaded = load_weights_from_db_sync(str(db.db_path), str(state_path))
    finally:
        await db.close()

    assert json.loads(state_path.read_text())["belief_version"] == 1
    assert loaded["belief_version"] == 1
    assert loaded["weights"] == {"reddit_bitcoin": 0.01}


async def test_empty_crawl_increments_snapshot_revision(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    orchestrator = CrawlerOrchestrator(
        db,
        sources={"reddit_bitcoin": SimpleNamespace()},
        state_path=str(tmp_path / "state.json"),
    )
    belief = SourceBelief(source="reddit_bitcoin")
    orchestrator.bandit = SimpleNamespace(
        select_source=lambda _: SimpleNamespace(
            source="reddit_bitcoin",
            sampled_value=0.5,
            belief=belief,
        )
    )
    orchestrator._crawl_source_batch = AsyncMock(return_value=[])

    await orchestrator.select_and_crawl()

    _, revision = await orchestrator.snapshot_beliefs()
    assert revision == 1
    assert orchestrator.state.belief_version == 0
    assert orchestrator.belief_store.get("reddit_bitcoin").consecutive_empty_crawls == 1


async def test_accepted_snapshot_persists_matching_weight_version(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    try:
        orchestrator = CrawlerOrchestrator(
            db,
            sources={},
            state_path=str(tmp_path / "state.json"),
        )
        version = await orchestrator.apply_belief_snapshot(
            {
                "reddit_bitcoin": {
                    "source": "reddit_bitcoin",
                    "alpha": 3.0,
                    "beta": 2.0,
                    "type_label": "insufficient_data",
                }
            },
            expected_revision=0,
        )
        cursor = await db.conn.execute(
            "SELECT alpha, beta, belief_version FROM source_weights WHERE source = ?",
            ("reddit_bitcoin",),
        )
        row = await cursor.fetchone()
        cursor = await db.conn.execute(
            "SELECT belief_version FROM belief_publications WHERE id = 1"
        )
        publication = await cursor.fetchone()
    finally:
        await db.close()

    assert version == 1
    assert (row["alpha"], row["beta"], row["belief_version"]) == (3.0, 2.0, 1)
    assert publication["belief_version"] == 1


async def test_staged_weights_are_not_visible_to_published_queries(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    weights = {
        "reddit_bitcoin": {
            "weight": 0.2,
            "accuracy": 0.6,
            "is_contrarian": False,
            "alpha": 3.0,
            "beta": 2.0,
            "sample_size": 5,
        }
    }
    try:
        await save_weights_to_db(db, weights, belief_version=1, publish=False)
        cursor = await db.conn.execute("SELECT COUNT(*) FROM active_source_weights")
        staged_count = (await cursor.fetchone())[0]

        await save_weights_to_db(db, weights, belief_version=1)
        cursor = await db.conn.execute("SELECT COUNT(*) FROM active_source_weights")
        published_count = (await cursor.fetchone())[0]
    finally:
        await db.close()

    assert staged_count == 0
    assert published_count == 1


async def test_loaded_state_republishes_its_weight_snapshot(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    try:
        orchestrator = CrawlerOrchestrator(
            db,
            sources={},
            state_path=str(tmp_path / "orchestrator_state.json"),
        )
        orchestrator.state.belief_version = 4
        orchestrator.belief_store.beliefs["reddit_bitcoin"] = SourceBelief(
            source="reddit_bitcoin",
            alpha=3.0,
            beta=2.0,
            type_label="insufficient_data",
        )
        await orchestrator._republish_loaded_weights()
        cursor = await db.conn.execute(
            "SELECT belief_version FROM belief_publications WHERE id = 1"
        )
        publication = await cursor.fetchone()
    finally:
        await db.close()

    assert publication["belief_version"] == 4


async def test_weight_writer_uses_an_isolated_database_connection(tmp_path: Path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    weights = {
        "reddit_bitcoin": {
            "weight": 0.2,
            "accuracy": 0.6,
            "is_contrarian": False,
            "alpha": 3.0,
            "beta": 2.0,
            "sample_size": 5,
        }
    }
    try:
        with patch.object(
            db.conn,
            "execute",
            side_effect=AssertionError("shared connection should not be used"),
        ):
            await save_weights_to_db(db, weights, belief_version=1)
    finally:
        await db.close()


async def test_source_weights_store_their_belief_version(tmp_path: Path):
    db_path = tmp_path / "sentiment.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE source_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source VARCHAR(50) NOT NULL UNIQUE,
            weight FLOAT NOT NULL,
            accuracy FLOAT,
            is_contrarian BOOLEAN DEFAULT FALSE,
            alpha FLOAT,
            beta FLOAT,
            sample_size INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    await db.connect()
    try:
        await save_weights_to_db(
            db,
            {
                "reddit_bitcoin": {
                    "weight": 0.2,
                    "accuracy": 0.6,
                    "is_contrarian": False,
                    "alpha": 3.0,
                    "beta": 2.0,
                    "sample_size": 5,
                }
            },
            belief_version=8,
        )
        cursor = await db.conn.execute(
            "SELECT belief_version FROM source_weights WHERE source = ?",
            ("reddit_bitcoin",),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    assert row["belief_version"] == 8


async def test_legacy_weight_rows_remain_unpublished_until_resync(tmp_path: Path):
    db_path = tmp_path / "sentiment.db"
    (tmp_path / "orchestrator_state.json").write_text('{"belief_version": 6}')
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE source_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source VARCHAR(50) NOT NULL UNIQUE,
            weight FLOAT NOT NULL,
            accuracy FLOAT,
            is_contrarian BOOLEAN DEFAULT FALSE,
            alpha FLOAT,
            beta FLOAT,
            sample_size INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO source_weights (source, weight) VALUES (?, ?)",
        ("reddit_bitcoin", 0.2),
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    await db.connect()
    try:
        cursor = await db.conn.execute(
            "SELECT belief_version FROM source_weights WHERE source = ?",
            ("reddit_bitcoin",),
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    loaded = load_weights_from_db_sync(str(db_path), str(tmp_path / "orchestrator_state.json"))
    assert row["belief_version"] is None
    assert loaded["weights"] == {}


async def test_weight_loader_ignores_stale_snapshot_versions(tmp_path: Path):
    db_path = tmp_path / "sentiment.db"
    state_path = tmp_path / "orchestrator_state.json"
    state_path.write_text('{"belief_version": 2}')
    db = Database(db_path)
    await db.connect()
    try:
        await save_weights_to_db(
            db,
            {
                "stale_source": {
                    "weight": 0.9,
                    "accuracy": 0.9,
                    "is_contrarian": False,
                    "alpha": 9.0,
                    "beta": 1.0,
                    "sample_size": 10,
                }
            },
            belief_version=1,
        )
        await save_weights_to_db(
            db,
            {
                "current_source": {
                    "weight": 0.2,
                    "accuracy": 0.6,
                    "is_contrarian": False,
                    "alpha": 3.0,
                    "beta": 2.0,
                    "sample_size": 5,
                }
            },
            belief_version=2,
        )
        await save_weights_to_db(
            db,
            {
                "current_source": {
                    "weight": 0.8,
                    "accuracy": 0.8,
                    "is_contrarian": False,
                    "alpha": 8.0,
                    "beta": 2.0,
                    "sample_size": 10,
                }
            },
            belief_version=1,
        )
    finally:
        await db.close()

    loaded = load_weights_from_db_sync(str(db_path), str(state_path))
    assert loaded["belief_version"] == 2
    assert loaded["weights"] == {"current_source": 0.2}


async def test_weight_loader_retries_when_state_changes_during_read(tmp_path: Path):
    db_path = tmp_path / "sentiment.db"
    state_path = tmp_path / "orchestrator_state.json"
    state_path.write_text('{"belief_version": 1}')
    db = Database(db_path)
    await db.connect()
    try:
        for version, source in [(1, "old_source"), (2, "new_source")]:
            await save_weights_to_db(
                db,
                {
                    source: {
                        "weight": 0.2,
                        "accuracy": 0.6,
                        "is_contrarian": False,
                        "alpha": 3.0,
                        "beta": 2.0,
                        "sample_size": 5,
                    }
                },
                belief_version=version,
            )
    finally:
        await db.close()

    with patch(
        "crypto_sentiment_crawler.analysis.source_weights.json.load",
        side_effect=[
            {"belief_version": 1},
            {"belief_version": 2},
            {"belief_version": 2},
            {"belief_version": 2},
        ],
    ):
        loaded = load_weights_from_db_sync(str(db_path), str(state_path))

    assert loaded["belief_version"] == 2
    assert loaded["weights"] == {"new_source": 0.2}
