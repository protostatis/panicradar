"""Regression tests for Reddit crawl rate-limit recovery.

Covers:
- ``permalink_key`` normalizing stored URLs and listing permalinks
- ``RedditFetchError`` distinguishing a transport failure from a quiet source
- Thread-fetch deduplication, cap, and comment-first ordering
- ``last_crawl_at`` driving cooldown decay instead of ``last_updated``
- Stored-URL index used for deduplication
- Orchestrator skipping the empty-crawl penalty on a transport failure
- Zero-yield ticks counting as empty crawls until the source cools down
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from crypto_sentiment_crawler.bayesian.bandit import CrawlBandit
from crypto_sentiment_crawler.bayesian.beliefs import SourceBelief, SourceBeliefStore
from crypto_sentiment_crawler.crawler.fetcher import FetchResult
from crypto_sentiment_crawler.crawler.pipeline import (
    CrawledContent,
    RedditComment,
    RedditFetchError,
    RedditPipeline,
    RedditThread,
    permalink_key,
)
from crypto_sentiment_crawler.orchestrator import CrawlerOrchestrator
from crypto_sentiment_crawler.storage.db import Database
from crypto_sentiment_crawler.storage.models import SentimentRaw


class FakeFetcher:
    """Fetcher stub returning a preset listing response."""

    def __init__(
        self,
        content: str = "",
        *,
        success: bool = True,
        status_code: int = 200,
        error: str | None = None,
    ):
        self.content = content
        self.success = success
        self.status_code = status_code
        self.error = error
        self.urls: list[str] = []

    async def fetch(self, url: str, rate_limit: float | None = None) -> FetchResult:
        self.urls.append(url)
        return FetchResult(
            url=url,
            status_code=self.status_code,
            content=self.content if self.success else "",
            headers={},
            elapsed_seconds=0.0,
            success=self.success,
            error=self.error,
        )


def _listing_html(posts: list[tuple[str, int]]) -> str:
    """Build an old.reddit listing with (slug, comment_count) posts."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    items = []
    for index, (slug, comments) in enumerate(posts, start=1):
        items.append(
            f'<div class="thing link" '
            f'data-permalink="/r/test/comments/{slug}/post_{index}/" '
            f'data-url="https://example.com/{slug}" '
            f'data-timestamp="{now_ms}">'
            f'<a class="title">Post {slug}</a>'
            f'<div class="score unvoted">{index * 10}</div>'
            f'<a class="comments">{comments} comments</a>'
            f'<a class="author">user{index}</a>'
            f"</div>"
        )
    return f"<html><body>{''.join(items)}</body></html>"


def _install_fake_threads(pipeline: RedditPipeline, calls: list[str]) -> None:
    """Replace thread fetching with a stub that records permalinks."""

    async def fetch_thread(permalink: str, max_comments: int = 20):
        calls.append(permalink)
        return RedditThread(
            url=f"https://old.reddit.com{permalink}",
            title=f"Thread {permalink}",
            selftext="thread body",
            author="author",
            score=99,
            num_comments=5,
            created_utc=None,
            published_at=datetime.now(timezone.utc),
            subreddit="test",
            comments=[
                RedditComment(
                    author=f"commenter{i}",
                    body="comment",
                    score=1,
                    created_utc=None,
                    published_at=None,
                    depth=0,
                )
                for i in range(5)
            ],
            crawled_at=datetime.now(timezone.utc),
        )

    pipeline.fetch_thread = fetch_thread


# ── permalink_key ───────────────────────────────────────────────────────────


def test_permalink_key_normalizes_stored_url_forms():
    expected = "/r/bitcoin/comments/abc"

    assert permalink_key("https://reddit.com/r/bitcoin/comments/abc/title/") == expected
    assert permalink_key("https://old.reddit.com/r/bitcoin/comments/abc/title") == expected
    assert permalink_key("/r/bitcoin/comments/abc/title/?utm_source=x") == expected


def test_permalink_key_ignores_title_slug_changes():
    before = permalink_key("https://reddit.com/r/bitcoin/comments/abc/old_title/")
    after = permalink_key("https://reddit.com/r/bitcoin/comments/abc/new_title/")

    assert before == after == "/r/bitcoin/comments/abc"


def test_permalink_key_rejects_non_reddit_urls():
    assert permalink_key(None) is None
    assert permalink_key("") is None
    assert permalink_key("https://example.com/r/bitcoin/comments/abc/title/") is None
    assert permalink_key("https://example.com/article") is None


# ── listing transport failure ───────────────────────────────────────────────


async def test_listing_failure_raises_reddit_fetch_error():
    pipeline = RedditPipeline(
        fetcher=FakeFetcher(success=False, status_code=429, error="HTTP 429")
    )

    with pytest.raises(RedditFetchError) as exc:
        await pipeline.crawl_subreddit("test")

    assert exc.value.status_code == 429


async def test_successful_listing_with_no_posts_is_not_an_error():
    pipeline = RedditPipeline(fetcher=FakeFetcher(_listing_html([])))

    assert await pipeline.crawl_subreddit("test") == []


async def test_permanent_subreddit_denial_is_marked_unavailable():
    pipeline = RedditPipeline(
        fetcher=FakeFetcher(
            success=False,
            status_code=403,
            error="Reddit subreddit is private",
        )
    )

    with pytest.raises(RedditFetchError) as exc:
        await pipeline.crawl_subreddit("private_sub")

    assert exc.value.source_unavailable is True


async def test_rate_limit_failure_is_not_marked_unavailable():
    pipeline = RedditPipeline(
        fetcher=FakeFetcher(success=False, status_code=429, error="HTTP 429")
    )

    with pytest.raises(RedditFetchError) as exc:
        await pipeline.crawl_subreddit("test")

    assert exc.value.source_unavailable is False


async def test_missing_subreddit_404_is_marked_unavailable():
    pipeline = RedditPipeline(
        fetcher=FakeFetcher(success=False, status_code=404, error="HTTP 404")
    )

    with pytest.raises(RedditFetchError) as exc:
        await pipeline.crawl_subreddit("does_not_exist")

    assert exc.value.source_unavailable is True


# ── selective thread fetching ───────────────────────────────────────────────


async def test_thread_fetches_are_capped_and_comment_first():
    posts = [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]
    pipeline = RedditPipeline(fetcher=FakeFetcher(_listing_html(posts)))
    calls: list[str] = []
    _install_fake_threads(pipeline, calls)

    result = await pipeline.crawl_subreddit("test", max_thread_fetches=2)

    assert calls == [
        "/r/test/comments/e/post_5/",
        "/r/test/comments/d/post_4/",
    ]
    # Every listing post is still returned so a healthy source is never
    # mistaken for an empty one, but unfetched posts carry no comments.
    assert len(result) == 5
    by_url = {post.title: post for post in result}
    assert by_url["Post e"].metadata["comments"]
    assert by_url["Post d"].metadata["comments"]
    assert by_url["Post a"].metadata["comments"] == []


async def test_unstorable_threads_do_not_monopolise_the_cap():
    posts = [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]
    pipeline = RedditPipeline(fetcher=FakeFetcher(_listing_html(posts)))
    calls: list[str] = []
    _install_fake_threads(pipeline, calls)

    await pipeline.crawl_subreddit("test", max_thread_fetches=2)
    assert calls == [
        "/r/test/comments/e/post_5/",
        "/r/test/comments/d/post_4/",
    ]

    # The orchestrator stored none of those (too few human comments), so the
    # next crawl must move on instead of fetching the same two forever.
    calls.clear()
    await pipeline.crawl_subreddit("test", max_thread_fetches=2)
    assert calls == [
        "/r/test/comments/c/post_3/",
        "/r/test/comments/b/post_2/",
    ]


async def test_failed_thread_fetch_is_retried_on_next_crawl():
    pipeline = RedditPipeline(fetcher=FakeFetcher(_listing_html([("a", 1)])))
    calls: list[str] = []

    async def failing_thread(permalink: str, max_comments: int = 20):
        calls.append(permalink)
        return None

    pipeline.fetch_thread = failing_thread

    await pipeline.crawl_subreddit("test", max_thread_fetches=2)
    await pipeline.crawl_subreddit("test", max_thread_fetches=2)

    assert calls == ["/r/test/comments/a/post_1/"] * 2


async def test_known_permalinks_skip_thread_fetch():
    posts = [("a", 1), ("b", 2), ("c", 3)]
    pipeline = RedditPipeline(fetcher=FakeFetcher(_listing_html(posts)))
    calls: list[str] = []
    _install_fake_threads(pipeline, calls)

    result = await pipeline.crawl_subreddit(
        "test",
        known_permalinks={permalink_key("/r/test/comments/b/post_2/")},
    )

    assert "/r/test/comments/b/post_2/" not in calls
    assert calls == [
        "/r/test/comments/c/post_3/",
        "/r/test/comments/a/post_1/",
    ]
    assert len(result) == 3


# ── stored URL index ────────────────────────────────────────────────────────


async def test_get_raw_urls_reads_only_matching_source(tmp_path):
    db = Database(tmp_path / "sentiment.db")
    await db.connect()
    try:
        await db.insert_sentiment_raw(SentimentRaw(
            timestamp=datetime(2026, 11, 6, 3, tzinfo=timezone.utc),
            source="reddit_bitcoin",
            coin="BTC",
            raw_data={"url": "https://reddit.com/r/bitcoin/comments/a/x/"},
        ))
        await db.insert_sentiment_raw(SentimentRaw(
            timestamp=datetime(2026, 11, 6, 3, tzinfo=timezone.utc),
            source="reddit_ethereum",
            coin="ETH",
            raw_data={"url": "https://reddit.com/r/ethereum/comments/b/y/"},
        ))

        assert await db.get_raw_urls("reddit_bitcoin") == {
            "https://reddit.com/r/bitcoin/comments/a/x/"
        }
        assert await db.get_raw_urls(
            "reddit_bitcoin",
            since=datetime(2026, 11, 7, tzinfo=timezone.utc),
        ) == set()
    finally:
        await db.close()


# ── cooldown decay clock ────────────────────────────────────────────────────


def test_crawl_outcomes_stamp_last_crawl_at():
    belief = SourceBelief(source="reddit_test")
    assert belief.last_crawl_at is None

    belief.record_empty_crawl()
    assert belief.last_crawl_at is not None
    empty_stamp = belief.last_crawl_at

    belief.record_successful_crawl()
    assert belief.last_crawl_at >= empty_stamp

    restored = SourceBelief.from_dict(belief.to_dict())
    assert restored.last_crawl_at == belief.last_crawl_at


def test_cooldown_decay_uses_last_crawl_at_not_last_updated():
    now = datetime.now(timezone.utc)
    store = SourceBeliefStore()

    stale = store.get("reddit_stale")
    stale.consecutive_empty_crawls = 10
    stale.last_crawl_at = now - timedelta(hours=2)
    stale.last_updated = now  # refreshed by the scheduled belief updater

    other = store.get("reddit_other")
    other.consecutive_empty_crawls = 0

    bandit = CrawlBandit(store, empty_crawl_cooldown=10, cooldown_decay_hours=1.0)

    assert "reddit_stale" in bandit._get_eligible_sources(["reddit_stale", "reddit_other"])

    # A recent crawl attempt keeps the cooldown in force even if last_updated
    # is old.
    store.get("reddit_stale").consecutive_empty_crawls = 10
    store.get("reddit_stale").last_crawl_at = now
    store.get("reddit_stale").last_updated = now - timedelta(hours=5)

    assert "reddit_stale" not in bandit._get_eligible_sources(
        ["reddit_stale", "reddit_other"]
    )


def test_seed_missing_crawl_clocks_recovers_stuck_source():
    now = datetime.now(timezone.utc)
    belief = SourceBelief(source="reddit_stuck", alpha=5.0, beta=8.0)
    belief.consecutive_empty_crawls = 10
    belief.first_empty_at = now - timedelta(hours=2)
    belief.last_updated = now  # refreshed by the scheduled belief updater
    data = belief.to_dict()
    data.pop("last_crawl_at")

    store = SourceBeliefStore.from_dict({"reddit_stuck": data})
    assert store.get("reddit_stuck").last_crawl_at is None

    assert store.seed_missing_crawl_clocks() == 1
    assert store.get("reddit_stuck").last_crawl_at == belief.first_empty_at

    bandit = CrawlBandit(store, empty_crawl_cooldown=10, cooldown_decay_hours=1.0)
    assert "reddit_stuck" in bandit._get_eligible_sources(["reddit_stuck"])


async def test_load_state_seeds_legacy_crawl_clock(tmp_path):
    now = datetime.now(timezone.utc)
    belief = SourceBelief(source="reddit_stuck", alpha=5.0, beta=8.0)
    belief.consecutive_empty_crawls = 10
    belief.first_empty_at = now - timedelta(hours=2)
    belief.last_updated = now
    data = belief.to_dict()
    data.pop("last_crawl_at")

    state_path = tmp_path / "orchestrator_state.json"
    state_path.write_text(json.dumps({"beliefs": {"reddit_stuck": data}}))

    orchestrator = CrawlerOrchestrator.__new__(CrawlerOrchestrator)
    orchestrator.state_path = state_path
    orchestrator.gp_model = None
    orchestrator.feature_extractor = SimpleNamespace(scaler_params=None)
    orchestrator.belief_store = SourceBeliefStore()

    await orchestrator._load_state()

    assert orchestrator.belief_store.get("reddit_stuck").last_crawl_at == belief.first_empty_at


def test_stale_belief_without_last_crawl_at_falls_back_to_last_updated():
    now = datetime.now(timezone.utc)
    store = SourceBeliefStore()
    belief = store.get("reddit_legacy")
    belief.consecutive_empty_crawls = 10
    belief.last_crawl_at = None
    belief.last_updated = now - timedelta(hours=2)

    bandit = CrawlBandit(store, empty_crawl_cooldown=10, cooldown_decay_hours=1.0)

    assert "reddit_legacy" in bandit._get_eligible_sources(["reddit_legacy"])


def test_default_cooldown_rests_a_source_after_four_empty_crawls():
    store = SourceBeliefStore()
    belief = store.get("reddit_dry")

    for _ in range(3):
        belief.record_empty_crawl()
    bandit = CrawlBandit(store)
    assert bandit._get_eligible_sources(["reddit_dry"]) == ["reddit_dry"]

    belief.record_empty_crawl()
    assert bandit._get_eligible_sources(["reddit_dry"]) == []


# ── orchestrator behaviour ──────────────────────────────────────────────────


class _FakeSelection:
    def __init__(self, source: str, belief: SourceBelief):
        self.source = source
        self.sampled_value = 0.5
        self.belief = belief


class _FakeBandit:
    def __init__(self, source: str, belief: SourceBelief):
        self.source = source
        self.belief = belief

    def select_source(self, available_sources):
        return _FakeSelection(self.source, self.belief)


def _bare_orchestrator() -> CrawlerOrchestrator:
    orchestrator = CrawlerOrchestrator.__new__(CrawlerOrchestrator)
    orchestrator.belief_store = SourceBeliefStore()
    orchestrator._belief_lock = asyncio.Lock()
    orchestrator.state = SimpleNamespace(belief_revision=0)
    orchestrator.sources = {"reddit_bitcoin": object()}
    orchestrator.bandit = _FakeBandit(
        "reddit_bitcoin",
        orchestrator.belief_store.get("reddit_bitcoin"),
    )
    return orchestrator


async def test_transport_failure_does_not_penalize_source():
    orchestrator = _bare_orchestrator()

    async def fail(*args, **kwargs):
        raise RedditFetchError("Reddit listing fetch failed: HTTP 429", status_code=429)

    orchestrator._crawl_source_batch = fail

    assert await orchestrator.select_and_crawl() == []

    belief = orchestrator.belief_store.get("reddit_bitcoin")
    assert belief.consecutive_empty_crawls == 0
    assert belief.last_crawl_at is None


async def test_unavailable_source_still_records_empty_crawl():
    orchestrator = _bare_orchestrator()

    async def unavailable(*args, **kwargs):
        raise RedditFetchError(
            "Reddit listing fetch failed for r/private: Reddit subreddit is private",
            status_code=403,
            source_unavailable=True,
        )

    orchestrator._crawl_source_batch = unavailable

    assert await orchestrator.select_and_crawl() == []

    belief = orchestrator.belief_store.get("reddit_bitcoin")
    assert belief.consecutive_empty_crawls == 1
    assert belief.last_crawl_at is not None


def _content(comments: list[dict]) -> CrawledContent:
    now = datetime.now(timezone.utc)
    return CrawledContent(
        url="https://reddit.com/r/test/comments/abc/post/",
        source="reddit_bitcoin",
        title="Post",
        content="body",
        author="author",
        published_at=now,
        crawled_at=now,
        coins_mentioned=["BTC"],
        sentiment_score=None,
        sentiment_details={},
        fetch_result=None,
        parse_result=None,
        metadata={"comments": comments},
    )


async def _stubbed_orchestrator(contents: list[CrawledContent]) -> CrawlerOrchestrator:
    orchestrator = _bare_orchestrator()

    async def crawl(*args, **kwargs):
        return contents

    async def store(_content):
        return 0

    async def price(_coin):
        return None

    orchestrator._crawl_source_batch = crawl
    orchestrator._store_content = store
    orchestrator._get_current_price = price
    orchestrator.utility_scorer = SimpleNamespace(compute_novelty_only=lambda *a, **k: 0.0)
    orchestrator.eval_lag_hours = 1
    return orchestrator


async def test_threads_fetched_but_nothing_stored_penalizes_source():
    orchestrator = await _stubbed_orchestrator([_content([{"body": "hi"}])])

    await orchestrator.select_and_crawl()

    belief = orchestrator.belief_store.get("reddit_bitcoin")
    assert belief.consecutive_empty_crawls == 1


async def test_listing_only_zero_yield_counts_as_empty_crawl():
    orchestrator = await _stubbed_orchestrator([_content([])])

    await orchestrator.select_and_crawl()

    belief = orchestrator.belief_store.get("reddit_bitcoin")
    assert belief.consecutive_empty_crawls == 1
    assert belief.last_crawl_at is not None


async def test_repeated_zero_yield_crawls_reach_cooldown():
    orchestrator = await _stubbed_orchestrator([_content([])])
    orchestrator.bandit = CrawlBandit(
        orchestrator.belief_store,
        empty_crawl_cooldown=10,
        cooldown_decay_hours=1.0,
    )

    for _ in range(10):
        await orchestrator.select_and_crawl()

    belief = orchestrator.belief_store.get("reddit_bitcoin")
    assert belief.consecutive_empty_crawls == 10
    assert orchestrator.bandit._get_eligible_sources(["reddit_bitcoin"]) == []


async def test_stored_content_resets_empty_crawl_streak(monkeypatch):
    orchestrator = await _stubbed_orchestrator([_content([{"body": "hi"}])])
    orchestrator.db = object()
    orchestrator.state.total_crawls = 0
    belief = orchestrator.belief_store.get("reddit_bitcoin")
    belief.consecutive_empty_crawls = 3

    async def store(_content):
        return 7

    async def write_outcome(**kwargs):
        return None

    monkeypatch.setattr(
        "crypto_sentiment_crawler.orchestrator.write_outcome",
        write_outcome,
    )
    orchestrator._store_content = store

    await orchestrator.select_and_crawl()

    assert belief.consecutive_empty_crawls == 0


async def test_batch_crawl_propagates_transport_error():
    orchestrator = CrawlerOrchestrator.__new__(CrawlerOrchestrator)

    async def known_permalinks(_source_name):
        return set()

    orchestrator._known_reddit_permalinks = known_permalinks

    class FailingPipeline:
        async def crawl_subreddit(self, *args, **kwargs):
            raise RedditFetchError("Reddit listing fetch failed: HTTP 429", status_code=429)

    orchestrator.reddit_pipeline = FailingPipeline()

    with pytest.raises(RedditFetchError):
        await orchestrator._crawl_source_batch("reddit_test", object())
