"""Tests for the pipeline health endpoint."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crypto_sentiment_crawler.dashboard.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


def _ts(minutes_ago: int = 0) -> str:
    """Build an ISO timestamp N minutes ago (timezone-aware)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def temp_db(tmp_path: Path) -> str:
    """Create a temporary database with required tables."""
    db_path = tmp_path / "test_sentiment.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            coin TEXT NOT NULL,
            price_usd REAL,
            volume_24h REAL,
            market_cap REAL,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS user_sentiment_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_id INTEGER,
            timestamp TEXT,
            final_score REAL,
            fear_index REAL,
            euphoria_index REAL,
            activity_level REAL,
            pos_count INTEGER,
            neg_count INTEGER,
            neu_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS sentiment_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            timestamp TEXT,
            raw_data TEXT,
            content_hash TEXT
        );
    """)
    conn.close()
    return str(db_path)


@pytest.fixture
def temp_state(tmp_path: Path) -> str:
    """Create a temporary orchestrator state file with a recent belief update."""
    state_path = tmp_path / "orchestrator_state.json"
    state = {
        "last_belief_update": _ts(2),  # 2 minutes ago
        "beliefs": {},
        "baseline_informativeness": 0.5,
        "total_crawls": 10,
    }
    state_path.write_text(json.dumps(state))
    return str(state_path)


@pytest.fixture
def temp_state_stale(tmp_path: Path) -> str:
    """Create a temporary orchestrator state file with an old belief update (3 hours ago → critical)."""
    state_path = tmp_path / "orchestrator_state.json"
    state = {
        "last_belief_update": _ts(180),  # 3 hours ago
        "beliefs": {},
        "baseline_informativeness": 0.5,
        "total_crawls": 10,
    }
    state_path.write_text(json.dumps(state))
    return str(state_path)


class TestHealthEndpoint:
    """Test the GET /api/ops/health endpoint."""

    def test_healthy_all_checks_pass(self, temp_db, temp_state, monkeypatch):
        """All checks pass with recent data."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state
        )

        conn = sqlite3.connect(temp_db)
        # Recent BTC price (2 min ago)
        conn.execute(
            "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', 50000)",
            (_ts(2),),
        )
        # Recent sentiment scores (1 min ago)
        conn.execute(
            "INSERT INTO user_sentiment_scores (timestamp, final_score) VALUES (?, 0.5)",
            (_ts(1),),
        )
        # Active source in last 24h
        conn.execute(
            "INSERT INTO sentiment_raw (source, timestamp, raw_data) VALUES ('reddit_crypto', ?, '{}')",
            (_ts(5),),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["checks"]["price_freshness"]["status"] == "ok"
        assert data["checks"]["sentiment_freshness"]["status"] == "ok"
        assert data["checks"]["belief_update"]["status"] == "ok"
        assert data["checks"]["active_sources"]["status"] == "ok"
        assert data["checks"]["active_sources"]["count"] == 1

    def test_degraded_stale_price(self, temp_db, temp_state, monkeypatch):
        """Price data older than 10 min but less than 30 min → degraded."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state
        )

        conn = sqlite3.connect(temp_db)
        # Stale BTC price (15 min ago → degraded)
        conn.execute(
            "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', 50000)",
            (_ts(15),),
        )
        # Fresh sentiment
        conn.execute(
            "INSERT INTO user_sentiment_scores (timestamp, final_score) VALUES (?, 0.5)",
            (_ts(1),),
        )
        conn.execute(
            "INSERT INTO sentiment_raw (source, timestamp, raw_data) VALUES ('reddit_crypto', ?, '{}')",
            (_ts(5),),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["price_freshness"]["status"] == "degraded"
        # Other checks should be ok
        assert data["checks"]["sentiment_freshness"]["status"] == "ok"
        assert data["checks"]["belief_update"]["status"] == "ok"

    def test_unhealthy_critical_price(self, temp_db, temp_state, monkeypatch):
        """Price data older than 30 min → unhealthy → 503."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state
        )

        conn = sqlite3.connect(temp_db)
        # Very stale BTC price (45 min ago → critical)
        conn.execute(
            "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', 50000)",
            (_ts(45),),
        )
        # Fresh everything else
        conn.execute(
            "INSERT INTO user_sentiment_scores (timestamp, final_score) VALUES (?, 0.5)",
            (_ts(1),),
        )
        conn.execute(
            "INSERT INTO sentiment_raw (source, timestamp, raw_data) VALUES ('reddit_crypto', ?, '{}')",
            (_ts(5),),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/ops/health")
        assert resp.status_code == 503
        # FastAPI wraps 503 detail
        detail = resp.json()["detail"]
        assert detail["status"] == "unhealthy"
        assert detail["checks"]["price_freshness"]["status"] == "critical"

    def test_unhealthy_stale_beliefs(self, temp_db, temp_state_stale, monkeypatch):
        """Belief update older than 2 hours → unhealthy → 503."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state_stale
        )

        conn = sqlite3.connect(temp_db)
        # Fresh data
        conn.execute(
            "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', 50000)",
            (_ts(2),),
        )
        conn.execute(
            "INSERT INTO user_sentiment_scores (timestamp, final_score) VALUES (?, 0.5)",
            (_ts(1),),
        )
        conn.execute(
            "INSERT INTO sentiment_raw (source, timestamp, raw_data) VALUES ('reddit_crypto', ?, '{}')",
            (_ts(5),),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/ops/health")
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["status"] == "unhealthy"
        assert detail["checks"]["belief_update"]["status"] == "critical"

    def test_no_active_sources(self, temp_db, temp_state, monkeypatch):
        """No sources active in 24h → degraded (not unhealthy)."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state
        )

        conn = sqlite3.connect(temp_db)
        conn.execute(
            "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', 50000)",
            (_ts(2),),
        )
        conn.execute(
            "INSERT INTO user_sentiment_scores (timestamp, final_score) VALUES (?, 0.5)",
            (_ts(1),),
        )
        # No sources inserted
        conn.commit()
        conn.close()

        resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["active_sources"]["status"] == "degraded"
        assert data["checks"]["active_sources"]["count"] == 0

    def test_empty_database_returns_unhealthy(self, temp_db, temp_state, monkeypatch):
        """Empty database → unhealthy → 503."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.DB_PATH", temp_db
        )
        monkeypatch.setattr(
            "crypto_sentiment_crawler.dashboard.routes.STATE_PATH", temp_state
        )
        # Empty DB — no data inserted
        resp = client.get("/api/ops/health")
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["status"] == "unhealthy"
        assert detail["checks"]["price_freshness"]["status"] == "critical"
        assert detail["checks"]["sentiment_freshness"]["status"] == "critical"
