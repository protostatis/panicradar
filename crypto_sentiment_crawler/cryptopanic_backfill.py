"""
CryptoPanic backfill for crypto sentiment data.

CryptoPanic is a news aggregator with community voting (bullish/bearish).
Uses their free public API: https://cryptopanic.com/api/

No authentication required for basic access.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup

from .crawler.fetcher import Fetcher
from .logging_config import logger
from .processing.sentiment import sentiment_analyzer
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# CryptoPanic endpoints
# The API requires auth_token, but RSS feeds are public
RSS_URL = "https://cryptopanic.com/news/rss/"
NEWS_URL = "https://cryptopanic.com/api/v1/posts/"

# We'll scrape the public web pages instead
WEB_URL = "https://cryptopanic.com/news/"

# Filters to crawl (as URL paths)
FILTERS = ["", "bullish/", "bearish/", "important/", "hot/"]

# Coins to track
CURRENCIES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "LTC", "BNB", "MATIC"]

# Rate limiting
RATE_LIMIT_DELAY = 2.0
MAX_PAGES_PER_FILTER = 5


class CryptoPanicBackfiller:
    """Backfill CryptoPanic news data for crypto sentiment."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.stats = {
            "news_fetched": 0,
            "news_stored": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher."""
        self.fetcher = Fetcher(
            default_rate_limit=0.5,
            timeout=30.0,
            randomize_delay=True,
            delay_range=(1.0, 3.0),
        )
        await self.fetcher.start()
        logger.info("CryptoPanic backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("CryptoPanic backfiller shutdown complete")

    async def fetch_news(
        self,
        filter_type: str = "",
        currencies: Optional[list[str]] = None,
        page: int = 1,
    ) -> tuple[list[dict], Optional[str]]:
        """
        Fetch news from CryptoPanic by scraping the web page.

        Returns (news_items, next_page_url)
        """
        url = f"{WEB_URL}{filter_type}"
        if page > 1:
            url += f"?page={page}"

        result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            logger.warning(f"Failed to fetch CryptoPanic {filter_type}: {result.error}")
            return [], None

        news = []
        soup = BeautifulSoup(result.content, "lxml")

        # Find news items
        for item in soup.select("div.news-row, article.news-item, div[class*='news']"):
            try:
                # Find title/link
                link = item.select_one("a[href*='/news/']")
                if not link:
                    continue

                title = link.get_text(strip=True)
                href = link.get("href", "")
                if not title or len(title) < 10:
                    continue

                # Extract source
                source_elem = item.select_one("span.news-source, span[class*='source']")
                source = source_elem.get_text(strip=True) if source_elem else "unknown"

                # Extract votes/sentiment indicators
                votes = {"positive": 0, "negative": 0, "important": 0}

                # Look for vote counts
                for vote_elem in item.select("span[class*='vote'], span[class*='count']"):
                    vote_text = vote_elem.get_text(strip=True)
                    vote_class = vote_elem.get("class", [])

                    if isinstance(vote_class, list):
                        vote_class = " ".join(vote_class)

                    try:
                        count = int(re.search(r"\d+", vote_text).group()) if re.search(r"\d+", vote_text) else 0
                    except (AttributeError, ValueError):
                        count = 0

                    if "bull" in vote_class.lower() or "positive" in vote_class.lower():
                        votes["positive"] = count
                    elif "bear" in vote_class.lower() or "negative" in vote_class.lower():
                        votes["negative"] = count

                # Extract currencies mentioned
                currencies = []
                for curr_elem in item.select("a[href*='/news/'], span[class*='currency']"):
                    curr_text = curr_elem.get_text(strip=True).upper()
                    if curr_text in ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK"]:
                        currencies.append(curr_text)

                news.append({
                    "title": title,
                    "url": f"https://cryptopanic.com{href}" if href.startswith("/") else href,
                    "source": {"title": source},
                    "votes": votes,
                    "currencies": [{"code": c} for c in currencies],
                    "kind": "news",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                })

            except Exception as e:
                logger.debug(f"Error parsing news item: {e}")
                continue

        self.stats["news_fetched"] += len(news)

        # Check for next page
        next_page = None
        next_link = soup.select_one("a[href*='page=']")
        if next_link and page < MAX_PAGES_PER_FILTER:
            next_page = f"page_{page + 1}"

        return news, next_page

    async def store_news(self, news: dict) -> None:
        """Store a news item to the database."""
        # Extract data
        title = news.get("title", "")
        url = news.get("url", "")
        published = news.get("published_at", "")
        source_info = news.get("source", {})
        source_title = source_info.get("title", "unknown")

        # Parse votes for sentiment
        votes = news.get("votes", {})
        positive = votes.get("positive", 0)
        negative = votes.get("negative", 0)
        important = votes.get("important", 0)
        liked = votes.get("liked", 0)
        disliked = votes.get("disliked", 0)

        # Calculate sentiment from votes
        total_votes = positive + negative + 1  # +1 to avoid div by zero
        vote_sentiment = (positive - negative) / total_votes

        # Also analyze title text
        text_sentiment = sentiment_analyzer.analyze(title)

        # Combine vote and text sentiment (votes weighted higher as they're community signal)
        combined_score = (vote_sentiment * 0.7) + (text_sentiment["compound"] * 0.3)

        # Extract currencies mentioned
        currencies = [c.get("code", "") for c in news.get("currencies", [])]

        # Parse timestamp
        try:
            timestamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now(timezone.utc)

        # Store raw
        raw = SentimentRaw(
            timestamp=timestamp,
            source="cryptopanic",
            coin=currencies[0] if currencies else None,
            raw_data={
                "url": url,
                "title": title,
                "source": source_title,
                "votes": votes,
                "currencies": currencies,
                "kind": news.get("kind", "news"),
                "backfill": True,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment scores
        confidence = min(0.9, 0.3 + (total_votes / 100))

        for coin in currencies or ["MARKET"]:
            score = SentimentScore(
                timestamp=timestamp,
                coin=coin,
                source="cryptopanic",
                score=max(-1.0, min(1.0, combined_score)),
                confidence=confidence,
                sample_size=total_votes,
            )
            await self.db.insert_sentiment_score(score)

        self.stats["news_stored"] += 1

    async def backfill_filter(self, filter_type: str) -> int:
        """Backfill news for a specific filter."""
        logger.info(f"Fetching CryptoPanic {filter_type} news...")
        total = 0

        for page in range(MAX_PAGES_PER_FILTER):
            news_items, next_url = await self.fetch_news(filter_type=filter_type)

            for news in news_items:
                try:
                    await self.store_news(news)
                    total += 1
                except Exception as e:
                    logger.debug(f"Error storing news: {e}")
                    self.stats["errors"] += 1

            if not next_url:
                break

            await asyncio.sleep(1)

        logger.info(f"  {filter_type}: {total} items")
        return total

    async def run_full_backfill(self) -> dict:
        """Run complete CryptoPanic backfill."""
        logger.info("=" * 60)
        logger.info("STARTING CRYPTOPANIC BACKFILL")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Fetch each filter type
        for filter_type in FILTERS:
            try:
                await self.backfill_filter(filter_type)
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error on filter {filter_type}: {e}")
                self.stats["errors"] += 1

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("CRYPTOPANIC BACKFILL COMPLETE")
        logger.info(f"  News fetched: {self.stats['news_fetched']}")
        logger.info(f"  News stored: {self.stats['news_stored']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_cryptopanic_backfill() -> dict:
    """Main entry point for CryptoPanic backfill."""
    db = Database()
    await db.connect()

    backfiller = CryptoPanicBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_cryptopanic_backfill())
