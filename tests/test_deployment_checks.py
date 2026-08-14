"""Tests for deployment backup and runtime acceptance checks."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from crypto_sentiment_crawler.maintenance.deployment_checks import (
    DeploymentCheckError,
    check_openrouter,
    check_publication_database,
    check_runtime_database,
    create_verified_backup,
    get_heartbeat_watermark,
)


def test_create_verified_backup_copies_a_consistent_database(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    connection = sqlite3.connect(source)
    assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    connection.execute("CREATE TABLE events (value TEXT)")
    connection.execute("INSERT INTO events VALUES ('ready')")
    connection.commit()
    connection.close()

    result = create_verified_backup(source, destination)

    backup = sqlite3.connect(destination)
    try:
        value = backup.execute("SELECT value FROM events").fetchone()[0]
    finally:
        backup.close()
    assert value == "ready"
    assert result["quick_check"] == "ok"
    assert result["bytes"] > 0
    source_connection = sqlite3.connect(source)
    try:
        assert source_connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        source_connection.close()


def _create_runtime_state(tmp_path: Path) -> tuple[Path, Path, datetime]:
    db_path = tmp_path / "sentiment.db"
    state_path = tmp_path / "orchestrator_state.json"
    since = datetime.now(timezone.utc) - timedelta(seconds=1)
    heartbeat_time = datetime.now(timezone.utc).isoformat()

    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE pipeline_heartbeats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT,
            last_success_at TEXT,
            last_error_at TEXT,
            last_error_message TEXT
        );
        CREATE TABLE belief_publications (
            id INTEGER PRIMARY KEY,
            belief_version INTEGER NOT NULL
        );
        CREATE TABLE source_weights (
            source TEXT PRIMARY KEY,
            weight REAL,
            accuracy REAL,
            is_contrarian INTEGER,
            alpha REAL,
            beta REAL,
            sample_size INTEGER,
            belief_version INTEGER
        );
        CREATE TABLE source_weight_snapshots (
            belief_version INTEGER,
            source TEXT,
            weight REAL,
            accuracy REAL,
            is_contrarian INTEGER,
            alpha REAL,
            beta REAL,
            sample_size INTEGER,
            PRIMARY KEY (belief_version, source)
        );
        """
    )
    connection.executemany(
        """
        INSERT INTO pipeline_heartbeats (
            component, last_success_at, last_error_at, last_error_message
        ) VALUES (?, ?, NULL, NULL)
        """,
        [(component, heartbeat_time) for component in ("price", "crawl", "belief_update")],
    )
    connection.execute("INSERT INTO belief_publications VALUES (1, 7)")
    values = ("reddit_bitcoin", 0.4, 0.6, 0, 3.0, 2.0, 5, 7)
    connection.execute("INSERT INTO source_weights VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
    connection.execute(
        "INSERT INTO source_weight_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (7, *values[:-1]),
    )
    connection.commit()
    connection.close()
    state_path.write_text(json.dumps({"belief_version": 7}))
    return db_path, state_path, since


def test_runtime_check_accepts_fresh_exact_publication(tmp_path: Path) -> None:
    db_path, state_path, since = _create_runtime_state(tmp_path)

    result = check_runtime_database(
        db_path=db_path,
        state_path=state_path,
        since=since,
        heartbeat_after_id=0,
    )

    assert result["belief_version"] == 7
    assert result["source_weights"] == 1
    assert result["mirror_exact"] is True
    assert set(result["heartbeats"]) == {"price", "crawl", "belief_update"}


def test_runtime_check_rejects_extra_current_weight(tmp_path: Path) -> None:
    db_path, state_path, since = _create_runtime_state(tmp_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO source_weights VALUES ('ghost', 0.9, NULL, 0, NULL, NULL, NULL, 7)"
    )
    connection.commit()
    connection.close()

    with pytest.raises(DeploymentCheckError, match="mirror mismatch"):
        check_runtime_database(
            db_path=db_path,
            state_path=state_path,
            since=since,
            heartbeat_after_id=0,
        )


def test_runtime_check_rejects_error_heartbeat(tmp_path: Path) -> None:
    db_path, state_path, since = _create_runtime_state(tmp_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        INSERT INTO pipeline_heartbeats (
            component, last_success_at, last_error_at, last_error_message
        ) VALUES ('crawl', ?, ?, 'database is locked')
        """,
        (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DeploymentCheckError, match="crawl heartbeat is an error"):
        check_runtime_database(
            db_path=db_path,
            state_path=state_path,
            since=since,
            heartbeat_after_id=0,
        )


def test_runtime_check_rejects_pre_cutover_heartbeats(tmp_path: Path) -> None:
    db_path, state_path, since = _create_runtime_state(tmp_path)
    watermark = get_heartbeat_watermark(db_path)["heartbeat_id"]

    with pytest.raises(DeploymentCheckError, match="did not come from the candidate"):
        check_runtime_database(
            db_path=db_path,
            state_path=state_path,
            since=since,
            heartbeat_after_id=watermark,
        )


def test_publication_check_rejects_mismatched_state_backup(tmp_path: Path) -> None:
    db_path, state_path, _ = _create_runtime_state(tmp_path)
    assert check_publication_database(
        db_path=db_path,
        state_path=state_path,
    )["belief_version"] == 7

    state_path.write_text(json.dumps({"belief_version": 8}))
    with pytest.raises(DeploymentCheckError, match="State version 8"):
        check_publication_database(db_path=db_path, state_path=state_path)


def test_publication_check_rejects_invalid_state_json(tmp_path: Path) -> None:
    db_path, state_path, _ = _create_runtime_state(tmp_path)
    state_path.write_text("{")

    with pytest.raises(DeploymentCheckError, match="Invalid orchestrator state"):
        check_publication_database(db_path=db_path, state_path=state_path)


def test_openrouter_check_uses_candidate_configuration(monkeypatch) -> None:
    from crypto_sentiment_crawler import config
    from crypto_sentiment_crawler.processing import embedding_providers

    configured = SimpleNamespace(
        embedding_backend="openrouter",
        embedding_model="qwen/qwen3-embedding-8b",
        openrouter_api_key="secret-test-value",
    )

    class FakeProvider:
        def __init__(self, **kwargs):
            assert kwargs["model"] == configured.embedding_model
            assert kwargs["api_key"] == configured.openrouter_api_key
            assert kwargs["cache_path"] is None

        def encode(self, texts, normalize=True):
            assert len(texts) == 1
            assert normalize is True
            return np.ones((1, 4), dtype=np.float32) / 2

    monkeypatch.setattr(config, "settings", configured)
    monkeypatch.setattr(embedding_providers, "OpenRouterEmbeddingProvider", FakeProvider)

    result = check_openrouter(
        expected_model="qwen/qwen3-embedding-8b",
        expected_dimensions=4,
    )

    assert result["shape"] == [1, 4]
    assert result["normalized"] is True


def test_openrouter_check_rejects_local_backend(monkeypatch) -> None:
    from crypto_sentiment_crawler import config

    monkeypatch.setattr(
        config,
        "settings",
        SimpleNamespace(
            embedding_backend="local",
            embedding_model="all-MiniLM-L6-v2",
            openrouter_api_key="",
        ),
    )

    with pytest.raises(DeploymentCheckError, match="EMBEDDING_BACKEND=openrouter"):
        check_openrouter(
            expected_model="qwen/qwen3-embedding-8b",
            expected_dimensions=4096,
        )
