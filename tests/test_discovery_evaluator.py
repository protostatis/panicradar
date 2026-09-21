"""Tests for discovery evaluation of subreddit-level access denials."""

import pytest

from crypto_sentiment_crawler.crawler.fetcher import FetchResult
from crypto_sentiment_crawler.discovery.evaluator import SourceEvaluator


class FakeFetcher:
    def __init__(self, result: FetchResult):
        self.result = result

    async def fetch(self, _url: str, rate_limit: float | None = None) -> FetchResult:
        return self.result


def _failed_fetch(error: str, status_code: int = 403) -> FetchResult:
    return FetchResult(
        url="https://old.reddit.com/r/cryptotech/new",
        status_code=status_code,
        content="",
        headers={},
        elapsed_seconds=0.0,
        success=False,
        error=error,
    )


@pytest.mark.parametrize(
    "error",
    [
        "Reddit subreddit is private",
        "Reddit subreddit is banned",
        "Reddit subreddit is quarantined",
    ],
)
async def test_evaluator_rejects_access_denied_subreddits(error: str) -> None:
    evaluator = SourceEvaluator(FakeFetcher(_failed_fetch(error)))

    result = await evaluator.evaluate("cryptotech")

    assert result is not None
    assert result.recommendation == "reject"
    assert result.reason == error


async def test_evaluator_leaves_transient_failures_unevaluated() -> None:
    evaluator = SourceEvaluator(
        FakeFetcher(_failed_fetch("Reddit response remained unusable after cookie refresh"))
    )

    assert await evaluator.evaluate("cryptotech") is None
