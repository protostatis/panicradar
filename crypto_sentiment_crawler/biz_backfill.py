"""
4chan /biz/ backfill for crypto sentiment data.

Uses 4chan's public JSON API:
- Catalog: https://a.4cdn.org/biz/catalog.json
- Thread: https://a.4cdn.org/biz/thread/{id}.json

No authentication required. Be polite with rate limits.
"""

import asyncio
import html
import json
import re
from datetime import datetime, timezone
from typing import Optional

from .crawler.fetcher import Fetcher
from .logging_config import logger
from .processing.sentiment import sentiment_analyzer
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# 4chan API endpoints
CATALOG_URL = "https://a.4cdn.org/biz/catalog.json"
THREAD_URL = "https://a.4cdn.org/biz/thread/{thread_id}.json"

# Crypto-related keywords to filter threads
CRYPTO_KEYWORDS = [
    # Major coins
    r"\bbitcoin\b", r"\bbtc\b", r"\bethereum\b", r"\beth\b",
    r"\bsolana\b", r"\bsol\b", r"\bxrp\b", r"\bripple\b",
    r"\bcardano\b", r"\bada\b", r"\bdogecoin\b", r"\bdoge\b",
    r"\blitecoin\b", r"\bltc\b", r"\bpolkadot\b", r"\bdot\b",
    r"\bavax\b", r"\bmatic\b", r"\bpolygon\b", r"\blink\b",
    r"\bchainlink\b", r"\bbnb\b", r"\bpepe\b", r"\bshib\b",
    # General crypto terms
    r"\bcrypto\b", r"\bcryptocurrency\b", r"\baltcoin\b",
    r"\bdefi\b", r"\bnft\b", r"\bhodl\b", r"\bwagmi\b",
    r"\bngmi\b", r"\bgm\b", r"\bbull\s*run\b", r"\bbear\s*market\b",
    r"\bmoon\b", r"\bpump\b", r"\bdump\b", r"\brug\b",
    r"\bstaking\b", r"\byield\b", r"\bairdrop\b",
    r"\bbinance\b", r"\bcoinbase\b", r"\bkraken\b",
    r"\bmetamask\b", r"\bledger\b", r"\bwallet\b",
    r"\bblockchain\b", r"\bweb3\b", r"\bl1\b", r"\bl2\b",
    # Memecoins and trends
    r"\bmemecoin\b", r"\bshitcoin\b", r"\b100x\b", r"\b1000x\b",
]

CRYPTO_PATTERN = re.compile("|".join(CRYPTO_KEYWORDS), re.IGNORECASE)

# Coin detection patterns (same as other collectors)
COIN_PATTERNS = {
    "BTC": [r"\bBTC\b", r"\b[Bb]itcoin\b"],
    "ETH": [r"\bETH\b", r"\b[Ee]thereum\b"],
    "SOL": [r"\bSOL\b", r"\b[Ss]olana\b"],
    "BNB": [r"\bBNB\b"],
    "XRP": [r"\bXRP\b", r"\b[Rr]ipple\b"],
    "ADA": [r"\bADA\b", r"\b[Cc]ardano\b"],
    "DOGE": [r"\bDOGE\b", r"\b[Dd]oge(?:coin)?\b"],
    "AVAX": [r"\bAVAX\b", r"\b[Aa]valanche\b"],
    "DOT": [r"\bDOT\b", r"\b[Pp]olkadot\b"],
    "MATIC": [r"\bMATIC\b", r"\b[Pp]olygon\b"],
    "LINK": [r"\bLINK\b", r"\b[Cc]hainlink\b"],
    "LTC": [r"\bLTC\b", r"\b[Ll]itecoin\b"],
    "PEPE": [r"\bPEPE\b"],
    "SHIB": [r"\bSHIB\b", r"\b[Ss]hiba\b"],
}

COMPILED_COIN_PATTERNS = {
    coin: [re.compile(p) for p in patterns]
    for coin, patterns in COIN_PATTERNS.items()
}

# Rate limiting - 4chan asks for 1 request per second
RATE_LIMIT_DELAY = 1.5
MAX_THREADS_PER_RUN = 100  # Limit threads per backfill run


def detect_coins(text: str) -> list[str]:
    """Detect which coins are mentioned in text."""
    mentioned = []
    for coin, patterns in COMPILED_COIN_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                mentioned.append(coin)
                break
    return mentioned


def clean_4chan_text(text: str) -> str:
    """Clean 4chan post text (HTML entities, quotes, etc.)."""
    if not text:
        return ""

    # Decode HTML entities
    text = html.unescape(text)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Remove greentext arrows but keep the text
    text = re.sub(r"^>+", "", text, flags=re.MULTILINE)

    # Remove post references (>>12345678)
    text = re.sub(r">>(\d+)", "", text)

    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def is_crypto_thread(thread: dict) -> bool:
    """Check if a thread is crypto-related."""
    # Check subject (title)
    subject = thread.get("sub", "")
    if CRYPTO_PATTERN.search(subject):
        return True

    # Check OP comment
    comment = thread.get("com", "")
    if CRYPTO_PATTERN.search(comment):
        return True

    return False


class BizBackfiller:
    """Backfill 4chan /biz/ data for crypto sentiment."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.stats = {
            "threads_fetched": 0,
            "posts_fetched": 0,
            "posts_stored": 0,
            "crypto_threads": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher."""
        self.fetcher = Fetcher(
            default_rate_limit=1.0,
            timeout=30.0,
            randomize_delay=True,
            delay_range=(1.0, 2.0),
        )
        await self.fetcher.start()
        logger.info("/biz/ backfiller initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("/biz/ backfiller shutdown complete")

    async def fetch_catalog(self) -> list[dict]:
        """Fetch the /biz/ catalog (list of all threads)."""
        result = await self.fetcher.fetch(CATALOG_URL, rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            logger.error(f"Failed to fetch catalog: {result.error}")
            return []

        try:
            catalog = json.loads(result.content)

            # Catalog is organized by pages, flatten to list of threads
            threads = []
            for page in catalog:
                for thread in page.get("threads", []):
                    threads.append(thread)

            logger.info(f"Fetched catalog: {len(threads)} total threads")
            return threads

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse catalog: {e}")
            return []

    async def fetch_thread(self, thread_id: int) -> Optional[dict]:
        """Fetch a single thread with all its posts."""
        url = THREAD_URL.format(thread_id=thread_id)
        result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

        if not result.success:
            if result.status_code == 404:
                # Thread was deleted/archived
                logger.debug(f"Thread {thread_id} not found (404)")
            else:
                logger.warning(f"Failed to fetch thread {thread_id}: {result.error}")
            return None

        try:
            data = json.loads(result.content)
            self.stats["threads_fetched"] += 1
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse thread {thread_id}: {e}")
            return None

    async def store_post(self, post: dict, thread_id: int, thread_subject: str) -> None:
        """Store a /biz/ post to the database."""
        text = clean_4chan_text(post.get("com", ""))
        if not text or len(text) < 10:
            return

        coins = detect_coins(text)
        sentiment = sentiment_analyzer.analyze(text)

        # Convert Unix timestamp to datetime
        timestamp = datetime.fromtimestamp(post.get("time", 0), tz=timezone.utc)

        # Build URL for deduplication
        post_id = post.get("no")
        post_url = f"https://boards.4chan.org/biz/thread/{thread_id}#p{post_id}"

        # Store raw
        raw = SentimentRaw(
            timestamp=timestamp,
            source="4chan_biz",
            coin=coins[0] if coins else None,
            raw_data={
                "url": post_url,
                "thread_id": thread_id,
                "post_id": post_id,
                "thread_subject": thread_subject[:200] if thread_subject else "",
                "text": text[:2000],
                "replies": post.get("replies", 0),
                "images": post.get("images", 0),
                "backfill": True,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment scores
        for coin in coins or ["MARKET"]:
            # Weight by engagement (replies indicate discussion)
            replies = post.get("replies", 0)
            confidence = min(0.8, 0.4 + (replies / 50))

            score = SentimentScore(
                timestamp=timestamp,
                coin=coin,
                source="4chan_biz",
                score=sentiment["compound"],
                confidence=confidence,
                sample_size=1,
            )
            await self.db.insert_sentiment_score(score)

        self.stats["posts_stored"] += 1

    async def process_thread(self, thread_id: int, thread_subject: str) -> int:
        """Process a single thread and store all its posts."""
        thread_data = await self.fetch_thread(thread_id)
        if not thread_data:
            return 0

        posts = thread_data.get("posts", [])
        stored = 0

        for post in posts:
            try:
                await self.store_post(post, thread_id, thread_subject)
                stored += 1
                self.stats["posts_fetched"] += 1
            except Exception as e:
                logger.debug(f"Error storing post: {e}")
                self.stats["errors"] += 1

        return stored

    async def run_full_backfill(self) -> dict:
        """Run complete /biz/ backfill."""
        logger.info("=" * 60)
        logger.info("STARTING 4CHAN /BIZ/ BACKFILL")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # Fetch catalog
        all_threads = await self.fetch_catalog()
        if not all_threads:
            logger.error("Failed to fetch catalog")
            return self.stats

        # Filter to crypto-related threads
        crypto_threads = [t for t in all_threads if is_crypto_thread(t)]
        self.stats["crypto_threads"] = len(crypto_threads)

        logger.info(f"Found {len(crypto_threads)} crypto-related threads out of {len(all_threads)}")

        # Limit threads per run
        threads_to_process = crypto_threads[:MAX_THREADS_PER_RUN]

        # Process each thread
        for i, thread in enumerate(threads_to_process):
            thread_id = thread.get("no")
            thread_subject = clean_4chan_text(thread.get("sub", ""))
            replies = thread.get("replies", 0)

            try:
                logger.info(
                    f"[{i+1}/{len(threads_to_process)}] Thread {thread_id}: "
                    f"{thread_subject[:40] if thread_subject else '(no subject)'}... "
                    f"({replies} replies)"
                )

                posts_stored = await self.process_thread(thread_id, thread_subject)

                if posts_stored > 0:
                    logger.info(f"  Stored {posts_stored} posts")

                # Small delay between threads
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error processing thread {thread_id}: {e}")
                self.stats["errors"] += 1

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("/BIZ/ BACKFILL COMPLETE")
        logger.info(f"  Crypto threads found: {self.stats['crypto_threads']}")
        logger.info(f"  Threads fetched: {self.stats['threads_fetched']}")
        logger.info(f"  Posts fetched: {self.stats['posts_fetched']}")
        logger.info(f"  Posts stored: {self.stats['posts_stored']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_biz_backfill() -> dict:
    """Main entry point for /biz/ backfill."""
    db = Database()
    await db.connect()

    backfiller = BizBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_biz_backfill())
