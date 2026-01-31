"""
Backfill historical Reddit threads for model training.

Fetches top/hot posts from crypto subreddits with full content and comments.
Runs separately from the live inference crawler.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from .crawler.fetcher import Fetcher
from .crawler.pipeline import RedditPipeline, CrawledContent
from .logging_config import logger
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# Subreddits to backfill with multiple time periods for more data
BACKFILL_SOURCES = [
    # High-volume subreddits - multiple time periods
    {"sub": "bitcoin", "pages": 4, "sort": "top", "time": "week"},
    {"sub": "bitcoin", "pages": 4, "sort": "top", "time": "month"},
    {"sub": "bitcoin", "pages": 4, "sort": "top", "time": "year"},
    {"sub": "cryptocurrency", "pages": 4, "sort": "top", "time": "week"},
    {"sub": "cryptocurrency", "pages": 4, "sort": "top", "time": "month"},
    {"sub": "cryptocurrency", "pages": 4, "sort": "top", "time": "year"},
    {"sub": "ethereum", "pages": 3, "sort": "top", "time": "week"},
    {"sub": "ethereum", "pages": 3, "sort": "top", "time": "month"},
    {"sub": "ethereum", "pages": 3, "sort": "top", "time": "year"},
    {"sub": "solana", "pages": 3, "sort": "top", "time": "week"},
    {"sub": "solana", "pages": 3, "sort": "top", "time": "month"},
    {"sub": "ethtrader", "pages": 3, "sort": "top", "time": "month"},
    {"sub": "ethtrader", "pages": 3, "sort": "top", "time": "year"},
    {"sub": "cryptomarkets", "pages": 3, "sort": "top", "time": "month"},
    {"sub": "bitcoinbeginners", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "defi", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "altcoin", "pages": 2, "sort": "top", "time": "month"},
    # Additional subreddits
    {"sub": "binance", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "coinbase", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "cardano", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "dogecoin", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "litecoin", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "ripple", "pages": 2, "sort": "top", "time": "month"},
    {"sub": "bitcoinmarkets", "pages": 3, "sort": "top", "time": "month"},
    {"sub": "satoshistreetbets", "pages": 2, "sort": "top", "time": "month"},
]

# Rate limit settings
RATE_LIMIT_DELAY = 2.0  # Seconds between requests
RATE_LIMIT_BACKOFF = 30  # Seconds to wait on 429 error
MAX_RETRIES = 3


class HistoricalBackfiller:
    """Backfill historical Reddit data for training."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.pipeline: RedditPipeline | None = None
        self.stats = {
            "posts_fetched": 0,
            "posts_stored": 0,
            "comments_total": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher and pipeline."""
        self.fetcher = Fetcher()
        await self.fetcher.start()
        self.pipeline = RedditPipeline(self.fetcher)
        logger.info("Backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("Backfiller shutdown complete")

    async def fetch_page(
        self,
        subreddit: str,
        sort: str = "top",
        time_filter: str = "month",
        after: str | None = None,
        limit: int = 25,
    ) -> tuple[list[CrawledContent], str | None]:
        """
        Fetch a page of posts from a subreddit.

        Returns (posts, next_after_token)
        """
        from bs4 import BeautifulSoup

        # Build URL with pagination
        url = f"https://old.reddit.com/r/{subreddit}/{sort}/?t={time_filter}"
        if after:
            url += f"&after={after}"

        # Retry with backoff on rate limit
        result = None
        for attempt in range(MAX_RETRIES):
            result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

            if result.success:
                break
            elif "429" in str(result.error):
                wait_time = RATE_LIMIT_BACKOFF * (attempt + 1)
                logger.warning(f"Rate limited on r/{subreddit}, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to fetch r/{subreddit}: {result.error}")
                return [], None

        if not result or not result.success:
            logger.error(f"Failed to fetch r/{subreddit} after {MAX_RETRIES} retries")
            return [], None

        soup = BeautifulSoup(result.content, "lxml")

        # Get next page token
        next_button = soup.select_one("span.next-button a")
        next_after = None
        if next_button:
            href = next_button.get("href", "")
            if "after=" in href:
                next_after = href.split("after=")[-1].split("&")[0]

        # Extract post permalinks
        posts = []
        for thing in soup.select("div.thing.link")[:limit]:
            permalink = thing.get("data-permalink")
            if not permalink:
                continue

            # Fetch full thread
            try:
                thread = await self.pipeline.fetch_thread(permalink, max_comments=15)
                if thread:
                    # Build CrawledContent from thread
                    content_parts = []
                    if thread.selftext:
                        content_parts.append(thread.selftext)
                    for c in thread.comments:
                        content_parts.append(c.body)

                    content = "\n\n".join(content_parts) if content_parts else None

                    comments_data = [
                        {
                            "author": c.author,
                            "body": c.body,
                            "score": c.score,
                            "created_utc": c.created_utc,
                            "depth": c.depth,
                        }
                        for c in thread.comments
                    ]

                    from .crawler.pipeline import detect_coins
                    from .processing.sentiment import sentiment_analyzer

                    full_text = " ".join(filter(None, [thread.title, content]))
                    coins = detect_coins(full_text)
                    sentiment = sentiment_analyzer.analyze(full_text)

                    post = CrawledContent(
                        url=thread.url,
                        source=f"reddit_{subreddit}",
                        title=thread.title,
                        content=content,
                        author=thread.author,
                        published_at=thread.published_at,
                        crawled_at=thread.crawled_at,
                        coins_mentioned=coins,
                        sentiment_score=sentiment["compound"],
                        sentiment_details=sentiment,
                        fetch_result=result,
                        parse_result=None,
                        metadata={
                            "score": thread.score,
                            "num_comments": thread.num_comments,
                            "subreddit": subreddit,
                            "created_utc": thread.created_utc,
                            "comments": comments_data,
                            "backfill": True,  # Mark as backfill data
                        },
                    )
                    posts.append(post)
                    self.stats["posts_fetched"] += 1
                    self.stats["comments_total"] += len(comments_data)

                    # Log progress
                    age_days = (datetime.now(timezone.utc) - thread.published_at).days if thread.published_at else "?"
                    logger.info(
                        f"Backfill r/{subreddit}: {thread.title[:40]}... "
                        f"(age={age_days}d, score={thread.score}, comments={len(comments_data)})"
                    )

            except Exception as e:
                logger.debug(f"Error fetching thread: {e}")
                self.stats["errors"] += 1
                continue

            # Rate limit between threads
            await asyncio.sleep(1.0)

        return posts, next_after

    async def store_post(self, post: CrawledContent) -> None:
        """Store a backfilled post to database."""
        # Store raw
        raw = SentimentRaw(
            timestamp=post.published_at or post.crawled_at,
            source=post.source,
            coin=post.coins_mentioned[0] if post.coins_mentioned else None,
            raw_data={
                "url": post.url,
                "title": post.title,
                "content": (post.content or "")[:2000],
                "author": post.author,
                "metadata": post.metadata,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment scores
        for coin in post.coins_mentioned or ["MARKET"]:
            score = SentimentScore(
                timestamp=post.published_at or post.crawled_at,
                coin=coin,
                source=post.source,
                score=post.sentiment_score,
                confidence=0.8,
                sample_size=1 + len(post.metadata.get("comments", [])),
            )
            await self.db.insert_sentiment_score(score)

        self.stats["posts_stored"] += 1

    async def backfill_subreddit(
        self,
        subreddit: str,
        pages: int = 3,
        sort: str = "top",
        time_filter: str = "month",
    ) -> int:
        """
        Backfill historical posts from a subreddit.

        Returns number of posts stored.
        """
        logger.info(f"Backfilling r/{subreddit} ({pages} pages, {sort}/{time_filter})...")

        after = None
        total_stored = 0

        for page in range(pages):
            posts, next_after = await self.fetch_page(
                subreddit,
                sort=sort,
                time_filter=time_filter,
                after=after,
            )

            for post in posts:
                await self.store_post(post)
                total_stored += 1

            if not next_after:
                logger.info(f"No more pages for r/{subreddit}")
                break

            after = next_after
            await asyncio.sleep(2)  # Rate limit between pages

        logger.info(f"Completed r/{subreddit}: {total_stored} posts")
        return total_stored

    async def run_full_backfill(self) -> dict:
        """Run backfill for all configured sources."""
        logger.info("=" * 60)
        logger.info("STARTING HISTORICAL BACKFILL")
        logger.info(f"Sources to crawl: {len(BACKFILL_SOURCES)}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        for i, config in enumerate(BACKFILL_SOURCES):
            subreddit = config["sub"]
            time_filter = config.get("time", "month")

            try:
                logger.info(f"[{i+1}/{len(BACKFILL_SOURCES)}] r/{subreddit} ({time_filter})")
                await self.backfill_subreddit(
                    subreddit,
                    pages=config.get("pages", 3),
                    sort=config.get("sort", "top"),
                    time_filter=time_filter,
                )
            except Exception as e:
                logger.error(f"Error backfilling r/{subreddit}: {e}")
                self.stats["errors"] += 1

            # Pause between subreddits to avoid rate limits
            await asyncio.sleep(5)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"  Posts fetched: {self.stats['posts_fetched']}")
        logger.info(f"  Posts stored: {self.stats['posts_stored']}")
        logger.info(f"  Comments total: {self.stats['comments_total']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_backfill() -> dict:
    """Main entry point for running backfill."""
    db = Database()
    await db.connect()

    backfiller = HistoricalBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_backfill())
