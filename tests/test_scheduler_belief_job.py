"""Tests for the belief update scheduler job."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from crypto_sentiment_crawler.scheduler import JOB_STAGGER_SECONDS, CrawlerScheduler


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


def test_interval_jobs_use_one_staggered_anchor():
    """Recurring writers receive deterministic offsets from one anchor."""
    scheduler = CrawlerScheduler()
    scheduler._setup_jobs()

    intervals = {
        "crawl": scheduler.crawl_interval,
        "price": scheduler.price_interval,
        "evaluate": scheduler.eval_interval,
        "fear_greed": scheduler.fear_greed_interval,
        "confounders": scheduler.confounder_interval,
        "onchain": scheduler.onchain_interval,
        "belief_update": 1800,
        "stats": 600,
    }
    inferred_anchors = {
        scheduler.scheduler.get_job(job_id).trigger.start_date
        - timedelta(seconds=interval + JOB_STAGGER_SECONDS[job_id])
        for job_id, interval in intervals.items()
    }

    assert len(inferred_anchors) == 1
    starts = {
        scheduler.scheduler.get_job(job_id).trigger.start_date
        for job_id in intervals
    }
    assert len(starts) == len(intervals)

    anchor = inferred_anchors.pop()
    scheduled_writes = {}
    for job_id, interval in intervals.items():
        if job_id == "stats":
            continue
        fire_time = scheduler.scheduler.get_job(job_id).trigger.start_date
        while fire_time <= anchor + timedelta(hours=8):
            assert fire_time not in scheduled_writes, (
                f"{job_id} collides with {scheduled_writes.get(fire_time)}"
            )
            scheduled_writes[fire_time] = job_id
            fire_time += timedelta(seconds=interval)
