"""Regression coverage for discovery source lifecycle transitions."""

import json

from crypto_sentiment_crawler.discovery.evaluator import EvaluationResult
from crypto_sentiment_crawler.discovery.manager import SourceManager
from crypto_sentiment_crawler.discovery.reddit_discovery import DiscoveredSubreddit


def _evaluation(recommendation: str, score: float = 0.42) -> EvaluationResult:
    return EvaluationResult(
        subreddit="btc",
        posts_per_hour=1.0,
        avg_score=5.0,
        avg_comments=3.0,
        crypto_relevance=0.9,
        freshness_hours=1.0,
        newest_post_hours=1.0,
        overall_score=score,
        recommendation=recommendation,
        reason="synthetic evaluation",
    )


def _manager(tmp_path) -> SourceManager:
    return SourceManager(state_path=str(tmp_path / "discovery_state.json"))


async def test_active_source_is_not_demoted_by_monitor_recommendation(tmp_path):
    manager = _manager(tmp_path)
    original = {
        "name": "reddit_btc",
        "source_type": "reddit",
        "subreddit": "btc",
        "status": "active",
        "added_at": "2026-10-11T03:02:22+00:00",
        "evaluation_score": 0.63,
        "notes": "Active source with recent posts (1.6h old)",
    }
    manager.state.sources["reddit_btc"] = dict(original)

    summary = await manager.process_evaluations(
        [(DiscoveredSubreddit(name="btc"), _evaluation("monitor", score=0.31))]
    )

    source = manager.state.sources["reddit_btc"]
    assert source["status"] == "active"
    assert source["added_at"] == original["added_at"]
    assert source["notes"] == original["notes"]
    assert source["evaluation_score"] == 0.31
    assert "btc" in summary["kept_active"]
    assert summary["monitoring"] == []


async def test_active_source_stays_active_on_add_recommendation(tmp_path):
    manager = _manager(tmp_path)
    manager.state.sources["reddit_btc"] = {
        "name": "reddit_btc",
        "source_type": "reddit",
        "subreddit": "btc",
        "status": "active",
        "added_at": "2026-10-11T03:02:22+00:00",
        "notes": "Active source with recent posts (1.6h old)",
    }

    summary = await manager.process_evaluations(
        [(DiscoveredSubreddit(name="btc"), _evaluation("add", score=0.81))]
    )

    assert manager.state.sources["reddit_btc"]["status"] == "active"
    assert manager.state.sources["reddit_btc"]["added_at"] == "2026-10-11T03:02:22+00:00"
    assert "btc" in summary["kept_active"]
    assert summary["added"] == []


async def test_new_candidate_can_still_be_added_or_monitored(tmp_path):
    manager = _manager(tmp_path)

    await manager.process_evaluations(
        [(DiscoveredSubreddit(name="newalpha"), _evaluation("monitor", score=0.44))]
    )

    assert manager.state.sources["reddit_newalpha"]["status"] == "monitoring"

    persisted = json.loads((tmp_path / "discovery_state.json").read_text())
    assert persisted["sources"]["reddit_newalpha"]["status"] == "monitoring"
