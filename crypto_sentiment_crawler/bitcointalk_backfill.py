"""
Bitcointalk.org backfill for crypto sentiment data.

Bitcointalk is the original crypto forum started by Satoshi.
Scrapes the most active boards for crypto discussion.

No API - uses HTML scraping.
"""

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .crawler.fetcher import Fetcher
from .logging_config import logger
from .processing.sentiment import sentiment_analyzer
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# Bitcointalk board URLs (most active crypto boards)
BOARDS = [
    # Main crypto boards
    {"id": 1, "name": "Bitcoin Discussion", "url": "https://bitcointalk.org/index.php?board=1.0", "pages": 5},
    {"id": 7, "name": "Bitcoin Technical", "url": "https://bitcointalk.org/index.php?board=7.0", "pages": 3},
    {"id": 8, "name": "Marketplace", "url": "https://bitcointalk.org/index.php?board=8.0", "pages": 2},
    {"id": 14, "name": "Altcoin Discussion", "url": "https://bitcointalk.org/index.php?board=14.0", "pages": 5},
    {"id": 159, "name": "Altcoin Announcements", "url": "https://bitcointalk.org/index.php?board=159.0", "pages": 3},
    {"id": 67, "name": "Speculation", "url": "https://bitcointalk.org/index.php?board=67.0", "pages": 5},
    {"id": 77, "name": "Trading Discussion", "url": "https://bitcointalk.org/index.php?board=77.0", "pages": 3},
    # Localized but active
    {"id": 238, "name": "DeFi", "url": "https://bitcointalk.org/index.php?board=238.0", "pages": 2},
]

# Coin detection patterns
COIN_PATTERNS = {
    "BTC": [r"\bBTC\b", r"\b[Bb]itcoin\b"],
    "ETH": [r"\bETH\b", r"\b[Ee]thereum\b"],
    "SOL": [r"\bSOL\b", r"\b[Ss]olana\b"],
    "XRP": [r"\bXRP\b", r"\b[Rr]ipple\b"],
    "ADA": [r"\bADA\b", r"\b[Cc]ardano\b"],
    "DOGE": [r"\bDOGE\b", r"\b[Dd]oge(?:coin)?\b"],
    "LTC": [r"\bLTC\b", r"\b[Ll]itecoin\b"],
    "BNB": [r"\bBNB\b"],
    "LINK": [r"\bLINK\b", r"\b[Cc]hainlink\b"],
    "DOT": [r"\bDOT\b", r"\b[Pp]olkadot\b"],
}

COMPILED_PATTERNS = {
    coin: [re.compile(p) for p in patterns]
    for coin, patterns in COIN_PATTERNS.items()
}

# Rate limiting - be polite to Bitcointalk
RATE_LIMIT_DELAY = 3.0
POSTS_PER_PAGE = 20


def detect_coins(text: str) -> list[str]:
    """Detect which coins are mentioned in text."""
    mentioned = []
    for coin, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                mentioned.append(coin)
                break
    return mentioned


class BitcointalkBackfiller:
    """Backfill Bitcointalk forum data for crypto sentiment."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.stats = {
            "threads_fetched": 0,
            "posts_fetched": 0,
            "posts_stored": 0,
            "boards_scraped": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher."""
        self.fetcher = Fetcher(
            default_rate_limit=0.3,  # Very slow for forum
            timeout=30.0,
            randomize_delay=True,
            delay_range=(2.0, 5.0),
        )
        await self.fetcher.start()
        logger.info("Bitcointalk backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("Bitcointalk backfiller shutdown complete")

    async def fetch_board_page(self, board_url: str, page: int = 0) -> list[dict]:
        """Fetch a page of threads from a board."""
        # Bitcointalk uses offset pagination (20 topics per page)
        offset = page * POSTS_PER_PAGE
        url = board_url.replace(".0", f".{offset}")

        result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            logger.warning(f"Failed to fetch board page: {result.error}")
            return []

        threads = []
        soup = BeautifulSoup(result.content, "lxml")

        # Find thread rows in the table
        for row in soup.select("table.bordercolor tr"):
            try:
                # Skip header rows
                cells = row.select("td")
                if len(cells) < 4:
                    continue

                # Find thread link
                link = row.select_one("td:nth-of-type(3) a, td:nth-of-type(2) a")
                if not link:
                    continue

                href = link.get("href", "")
                if "topic=" not in href:
                    continue

                title = link.get_text(strip=True)
                if not title:
                    continue

                # Extract topic ID
                topic_match = re.search(r"topic=(\d+)", href)
                if not topic_match:
                    continue

                topic_id = topic_match.group(1)

                # Get reply count
                replies = 0
                reply_cell = row.select_one("td:nth-of-type(4)")
                if reply_cell:
                    try:
                        replies = int(reply_cell.get_text(strip=True).replace(",", ""))
                    except ValueError:
                        pass

                # Get last post date
                last_post = row.select_one("td:last-of-type")
                last_post_text = last_post.get_text(strip=True) if last_post else ""

                threads.append({
                    "topic_id": topic_id,
                    "title": title,
                    "url": urljoin("https://bitcointalk.org/", href),
                    "replies": replies,
                    "last_post": last_post_text,
                })

            except Exception as e:
                logger.debug(f"Error parsing thread row: {e}")
                continue

        return threads

    async def fetch_thread(self, thread: dict) -> list[dict]:
        """Fetch posts from a thread."""
        result = await self.fetcher.fetch(thread["url"], rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            logger.debug(f"Failed to fetch thread: {result.error}")
            return []

        posts = []
        soup = BeautifulSoup(result.content, "lxml")

        self.stats["threads_fetched"] += 1

        # Find post containers
        for post_div in soup.select("div.post"):
            try:
                # Get post content
                content_div = post_div.select_one("div.inner")
                if not content_div:
                    continue

                # Clean up quotes
                for quote in content_div.select("div.quote, div.quoteheader"):
                    quote.decompose()

                text = content_div.get_text(strip=True)
                if not text or len(text) < 20:
                    continue

                # Get author
                author_link = post_div.find_previous("td", class_="poster_info")
                author = "anonymous"
                if author_link:
                    author_elem = author_link.select_one("a")
                    if author_elem:
                        author = author_elem.get_text(strip=True)

                # Get post ID from anchor
                anchor = post_div.select_one("a[name]")
                post_id = anchor.get("name", "") if anchor else ""

                # Get timestamp - look for the smalltext with "Today at" or date
                date_elem = post_div.find_previous("td", class_="td_headerandpost")
                timestamp = datetime.now(timezone.utc)
                if date_elem:
                    date_text = date_elem.select_one("div.smalltext")
                    if date_text:
                        # Parse date like "Today at 10:30:00 AM" or "January 31, 2026, 10:30:00 AM"
                        date_str = date_text.get_text(strip=True)
                        try:
                            if "Today" in date_str:
                                timestamp = datetime.now(timezone.utc)
                            else:
                                # Try to parse the date
                                timestamp = datetime.strptime(
                                    date_str.split(" on ")[-1][:30],
                                    "%B %d, %Y, %I:%M:%S %p"
                                ).replace(tzinfo=timezone.utc)
                        except (ValueError, IndexError):
                            pass

                posts.append({
                    "post_id": post_id,
                    "text": text[:3000],
                    "author": author,
                    "timestamp": timestamp,
                    "thread_title": thread["title"],
                    "thread_url": thread["url"],
                    "topic_id": thread["topic_id"],
                })

                self.stats["posts_fetched"] += 1

            except Exception as e:
                logger.debug(f"Error parsing post: {e}")
                continue

        return posts

    async def store_post(self, post: dict, board_name: str) -> None:
        """Store a Bitcointalk post to the database."""
        text = post["text"]
        coins = detect_coins(text)
        sentiment = sentiment_analyzer.analyze(text)

        # Build URL for deduplication
        post_url = f"{post['thread_url']}#msg{post['post_id']}"

        # Store raw
        raw = SentimentRaw(
            timestamp=post["timestamp"],
            source="bitcointalk",
            coin=coins[0] if coins else None,
            raw_data={
                "url": post_url,
                "title": post["thread_title"][:200],
                "text": text[:2000],
                "author": post["author"],
                "board": board_name,
                "topic_id": post["topic_id"],
                "backfill": True,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment scores
        for coin in coins or ["MARKET"]:
            score = SentimentScore(
                timestamp=post["timestamp"],
                coin=coin,
                source="bitcointalk",
                score=sentiment["compound"],
                confidence=0.6,  # Forum posts are moderate confidence
                sample_size=1,
            )
            await self.db.insert_sentiment_score(score)

        self.stats["posts_stored"] += 1

    async def backfill_board(self, board: dict) -> int:
        """Backfill a single board."""
        board_name = board["name"]
        board_url = board["url"]
        pages = board["pages"]

        logger.info(f"Scraping {board_name} ({pages} pages)...")
        total = 0

        for page in range(pages):
            try:
                threads = await self.fetch_board_page(board_url, page)
                logger.info(f"  Page {page+1}: {len(threads)} threads")

                for thread in threads[:10]:  # Limit threads per page
                    posts = await self.fetch_thread(thread)

                    for post in posts[:5]:  # Limit posts per thread
                        try:
                            await self.store_post(post, board_name)
                            total += 1
                        except Exception as e:
                            logger.debug(f"Error storing post: {e}")
                            self.stats["errors"] += 1

                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Error on page {page}: {e}")
                self.stats["errors"] += 1

        self.stats["boards_scraped"] += 1
        logger.info(f"  {board_name}: {total} posts stored")
        return total

    async def run_full_backfill(self) -> dict:
        """Run complete Bitcointalk backfill."""
        logger.info("=" * 60)
        logger.info("STARTING BITCOINTALK BACKFILL")
        logger.info(f"Boards to scrape: {len(BOARDS)}")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        for board in BOARDS:
            try:
                await self.backfill_board(board)
                await asyncio.sleep(5)  # Pause between boards
            except Exception as e:
                logger.error(f"Error on board {board['name']}: {e}")
                self.stats["errors"] += 1

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("BITCOINTALK BACKFILL COMPLETE")
        logger.info(f"  Boards scraped: {self.stats['boards_scraped']}")
        logger.info(f"  Threads fetched: {self.stats['threads_fetched']}")
        logger.info(f"  Posts fetched: {self.stats['posts_fetched']}")
        logger.info(f"  Posts stored: {self.stats['posts_stored']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_bitcointalk_backfill() -> dict:
    """Main entry point for Bitcointalk backfill."""
    db = Database()
    await db.connect()

    backfiller = BitcointalkBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_bitcointalk_backfill())
