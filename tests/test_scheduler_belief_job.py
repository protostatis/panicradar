"""Tests for the belief update scheduler job."""

import asyncio
from unittest.mock import AsyncMock, patch

from crypto_sentiment_crawler.scheduler import CrawlerScheduler


def test_belief_update_job_success():
    """Job increments belief_updates on success."""
    s = CrawlerScheduler()
    with patch(
        "crypto_sentiment_crawler.analysis.belief_updater.update_orchestrator_beliefs",
        new_callable=AsyncMock,
        return_value={},
    ):
        asyncio.run(s._job_belief_update())
    assert s._stats["belief_updates"] == 1
    assert s._stats["errors"] == 0


def test_belief_update_job_handles_error():
    """Job increments errors and doesn't crash on failure."""
    s = CrawlerScheduler()
    with patch(
        "crypto_sentiment_crawler.analysis.belief_updater.update_orchestrator_beliefs",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db down"),
    ):
        asyncio.run(s._job_belief_update())
    assert s._stats["belief_updates"] == 0
    assert s._stats["errors"] == 1


def test_belief_update_job_registered():
    """Belief update job is registered in _setup_jobs."""
    s = CrawlerScheduler()
    s._setup_jobs()
    job = s.scheduler.get_job("belief_update")
    assert job is not None
    assert job.name == "Belief Update & Weights Sync"
