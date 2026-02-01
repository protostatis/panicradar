"""
Twitter/X backfill for crypto sentiment data.

Uses multiple approaches to collect tweets:
1. Twitter API v2 (if bearer token configured)
2. Nitter instances (public Twitter frontend mirrors)
3. Syndication feeds

Set TWITTER_BEARER_TOKEN in .env for reliable API access.
Runs separately from the live crawler.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

from .config import settings
from .crawler.fetcher import Fetcher
from .logging_config import logger
from .processing.sentiment import sentiment_analyzer
from .storage.db import Database
from .storage.models import SentimentRaw, SentimentScore


# Search queries for crypto content
SEARCH_QUERIES = [
    # Hashtags
    "#Bitcoin",
    "#BTC",
    "#Ethereum",
    "#ETH",
    "#Crypto",
    "#Solana",
    "#XRP",
    "#Cardano",
    "#Dogecoin",
    "#DeFi",
    "#Altcoins",
    "#CryptoTwitter",
    # Cashtags
    "$BTC",
    "$ETH",
    "$SOL",
    "$XRP",
    "$ADA",
    "$DOGE",
    # Phrases
    "Bitcoin price",
    "crypto market",
    "bitcoin bull",
    "bitcoin bear",
    "ethereum upgrade",
    "crypto crash",
    "bitcoin ATH",
    "altcoin season",
]

# Influential crypto accounts to track
CRYPTO_ACCOUNTS = [
    "VitalikButerin",
    "saboredox",
    "APompliano",
    "CryptoHayes",
    "CryptoCobain",
    "loomdart",
    "inversebrah",
    "coaboredex",
    "WClementeIII",
    "100trillionUSD",
    "woonomic",
    "TheCryptoLark",
    "scottmelker",
    "CryptoWendyO",
    "AltcoinDailyio",
]

# Nitter instances to try (some may be down)
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.net",
    "https://nitter.woodland.cafe",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.unixfox.eu",
    "https://nitter.fdn.fr",
    "https://nitter.it",
    "https://nitter.namazso.eu",
]

# Coin detection patterns
COIN_PATTERNS = {
    "BTC": [r"\bBTC\b", r"\$BTC\b", r"\b[Bb]itcoin\b"],
    "ETH": [r"\bETH\b", r"\$ETH\b", r"\b[Ee]thereum\b"],
    "SOL": [r"\bSOL\b", r"\$SOL\b", r"\b[Ss]olana\b"],
    "BNB": [r"\bBNB\b", r"\$BNB\b"],
    "XRP": [r"\bXRP\b", r"\$XRP\b", r"\b[Rr]ipple\b"],
    "ADA": [r"\bADA\b", r"\$ADA\b", r"\b[Cc]ardano\b"],
    "DOGE": [r"\bDOGE\b", r"\$DOGE\b", r"\b[Dd]oge(?:coin)?\b"],
    "AVAX": [r"\bAVAX\b", r"\$AVAX\b", r"\b[Aa]valanche\b"],
    "DOT": [r"\bDOT\b", r"\$DOT\b", r"\b[Pp]olkadot\b"],
    "MATIC": [r"\bMATIC\b", r"\$MATIC\b", r"\b[Pp]olygon\b"],
    "LINK": [r"\bLINK\b", r"\$LINK\b", r"\b[Cc]hainlink\b"],
    "LTC": [r"\bLTC\b", r"\$LTC\b", r"\b[Ll]itecoin\b"],
}

COMPILED_PATTERNS = {
    coin: [re.compile(p) for p in patterns] for coin, patterns in COIN_PATTERNS.items()
}

# Rate limiting
RATE_LIMIT_DELAY = 3.0  # Seconds between requests
RATE_LIMIT_BACKOFF = 60  # Seconds on 429/403
MAX_RETRIES = 3


def detect_coins(text: str) -> list[str]:
    """Detect which coins are mentioned in text."""
    mentioned = []
    for coin, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                mentioned.append(coin)
                break
    return mentioned


class TwitterBackfiller:
    """Backfill Twitter/X data for crypto sentiment."""

    def __init__(self, db: Database):
        self.db = db
        self.fetcher: Fetcher | None = None
        self.working_instance: str | None = None
        self.use_api = bool(settings.twitter_bearer_token)
        self.stats = {
            "tweets_fetched": 0,
            "tweets_stored": 0,
            "accounts_scraped": 0,
            "queries_scraped": 0,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize fetcher."""
        self.fetcher = Fetcher(
            default_rate_limit=0.5,  # Slow for Twitter
            timeout=30.0,
            randomize_delay=True,
            delay_range=(2.0, 5.0),
        )
        await self.fetcher.start()

        if self.use_api:
            logger.info("Twitter backfiller initialized (using API)")
        else:
            logger.info("Twitter backfiller initialized (using Nitter fallback)")
            logger.info("Set TWITTER_BEARER_TOKEN in .env for reliable API access")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        if self.fetcher:
            await self.fetcher.close()
        logger.info("Twitter backfiller shutdown complete")

    async def find_working_instance(self) -> str | None:
        """Find a working Nitter instance."""
        if self.working_instance:
            # Verify it still works
            result = await self.fetcher.fetch(
                f"{self.working_instance}/search?q=bitcoin",
                rate_limit=RATE_LIMIT_DELAY,
            )
            if result.success:
                return self.working_instance

        logger.info("Searching for working Nitter instance...")

        for instance in NITTER_INSTANCES:
            try:
                result = await self.fetcher.fetch(
                    f"{instance}/search?q=bitcoin",
                    rate_limit=1.0,
                )
                if result.success and "timeline" in result.content.lower():
                    logger.info(f"Found working instance: {instance}")
                    self.working_instance = instance
                    return instance
                else:
                    logger.debug(f"Instance {instance}: status={result.status_code}")
            except Exception as e:
                logger.debug(f"Instance {instance} failed: {e}")
                continue

        logger.warning("No working Nitter instance found")
        return None

    async def search_via_api(self, query: str, max_tweets: int = 100) -> list[dict]:
        """Search tweets using Twitter API v2."""
        if not settings.twitter_bearer_token:
            return []

        tweets = []
        encoded_query = quote(f"{query} -is:retweet lang:en")
        url = (
            f"https://api.twitter.com/2/tweets/search/recent"
            f"?query={encoded_query}"
            f"&max_results={min(max_tweets, 100)}"
            f"&tweet.fields=created_at,public_metrics,author_id"
            f"&expansions=author_id"
            f"&user.fields=username,name"
        )

        headers = {"Authorization": f"Bearer {settings.twitter_bearer_token}"}

        for attempt in range(MAX_RETRIES):
            result = await self.fetcher.fetch(url, rate_limit=1.0, extra_headers=headers)

            if result.success:
                try:
                    data = json.loads(result.content)

                    # Build user lookup
                    users = {}
                    if "includes" in data and "users" in data["includes"]:
                        for user in data["includes"]["users"]:
                            users[user["id"]] = {
                                "username": user["username"],
                                "name": user.get("name", user["username"]),
                            }

                    # Parse tweets
                    for tweet in data.get("data", []):
                        author_id = tweet.get("author_id", "")
                        user_info = users.get(author_id, {"username": "unknown", "name": "Unknown"})
                        metrics = tweet.get("public_metrics", {})

                        # Parse timestamp
                        timestamp = datetime.now(timezone.utc)
                        if "created_at" in tweet:
                            try:
                                timestamp = datetime.fromisoformat(
                                    tweet["created_at"].replace("Z", "+00:00")
                                )
                            except ValueError:
                                pass

                        tweets.append({
                            "text": tweet.get("text", ""),
                            "username": user_info["username"],
                            "fullname": user_info["name"],
                            "timestamp": timestamp,
                            "retweets": metrics.get("retweet_count", 0),
                            "likes": metrics.get("like_count", 0),
                            "replies": metrics.get("reply_count", 0),
                            "quotes": metrics.get("quote_count", 0),
                            "url": f"https://twitter.com/{user_info['username']}/status/{tweet['id']}",
                            "source_query": query,
                        })

                    logger.debug(f"API returned {len(tweets)} tweets for '{query}'")
                    return tweets

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse API response: {e}")
                    return []

            elif result.status_code == 429:
                # Rate limited - wait and retry
                wait_time = 60 * (attempt + 1)
                logger.warning(f"API rate limited, waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"API error: {result.status_code} - {result.error}")
                return []

        return tweets

    async def scrape_search(self, query: str, max_tweets: int = 50) -> list[dict]:
        """Scrape tweets from a search query via Nitter."""
        if not self.working_instance:
            self.working_instance = await self.find_working_instance()
            if not self.working_instance:
                return []

        tweets = []
        encoded_query = quote(query)
        url = f"{self.working_instance}/search?q={encoded_query}&f=tweets"

        for attempt in range(MAX_RETRIES):
            result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

            if result.success:
                break
            elif result.status_code in (429, 403):
                logger.warning(f"Rate limited on search '{query}', waiting {RATE_LIMIT_BACKOFF}s...")
                await asyncio.sleep(RATE_LIMIT_BACKOFF)
                # Try a different instance
                self.working_instance = None
                self.working_instance = await self.find_working_instance()
                if not self.working_instance:
                    return []
            else:
                logger.debug(f"Search failed for '{query}': {result.error}")
                return []

        if not result.success:
            return []

        tweets = self._parse_nitter_timeline(result.content, query)
        return tweets[:max_tweets]

    async def scrape_account(self, username: str, max_tweets: int = 30) -> list[dict]:
        """Scrape tweets from a specific account via Nitter."""
        if not self.working_instance:
            self.working_instance = await self.find_working_instance()
            if not self.working_instance:
                return []

        url = f"{self.working_instance}/{username}"

        for attempt in range(MAX_RETRIES):
            result = await self.fetcher.fetch(url, rate_limit=RATE_LIMIT_DELAY)

            if result.success:
                break
            elif result.status_code in (429, 403):
                logger.warning(f"Rate limited on @{username}, waiting...")
                await asyncio.sleep(RATE_LIMIT_BACKOFF)
                self.working_instance = None
                self.working_instance = await self.find_working_instance()
                if not self.working_instance:
                    return []
            else:
                logger.debug(f"Account scrape failed for @{username}: {result.error}")
                return []

        if not result.success:
            return []

        tweets = self._parse_nitter_timeline(result.content, f"@{username}")
        return tweets[:max_tweets]

    def _parse_nitter_timeline(self, html: str, source: str) -> list[dict]:
        """Parse tweets from Nitter HTML."""
        tweets = []
        soup = BeautifulSoup(html, "lxml")

        # Find tweet containers (Nitter uses .timeline-item)
        for item in soup.select(".timeline-item"):
            try:
                # Skip retweets for cleaner data
                if item.select_one(".retweet-header"):
                    continue

                # Extract tweet content
                content_elem = item.select_one(".tweet-content, .tweet-body")
                if not content_elem:
                    continue

                text = content_elem.get_text(strip=True)
                if not text or len(text) < 10:
                    continue

                # Extract username
                username_elem = item.select_one(".username")
                username = username_elem.get_text(strip=True) if username_elem else "unknown"

                # Extract fullname
                fullname_elem = item.select_one(".fullname")
                fullname = fullname_elem.get_text(strip=True) if fullname_elem else username

                # Extract engagement stats
                stats = {}
                for stat in item.select(".tweet-stat"):
                    stat_text = stat.get_text(strip=True).lower()
                    if "comment" in stat_text or "repl" in stat_text:
                        stats["replies"] = self._parse_number(stat_text)
                    elif "retweet" in stat_text or "rt" in stat_text:
                        stats["retweets"] = self._parse_number(stat_text)
                    elif "like" in stat_text or "heart" in stat_text:
                        stats["likes"] = self._parse_number(stat_text)
                    elif "quote" in stat_text:
                        stats["quotes"] = self._parse_number(stat_text)

                # Extract timestamp
                timestamp = datetime.now(timezone.utc)
                time_elem = item.select_one(".tweet-date a")
                if time_elem:
                    title = time_elem.get("title", "")
                    if title:
                        try:
                            # Format: "Jan 31, 2026 · 7:30 PM UTC"
                            timestamp = datetime.strptime(
                                title.replace(" UTC", ""),
                                "%b %d, %Y · %I:%M %p"
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass

                # Extract tweet link
                link_elem = item.select_one(".tweet-link")
                tweet_url = ""
                if link_elem:
                    href = link_elem.get("href", "")
                    if href:
                        tweet_url = f"https://twitter.com{href}"

                tweets.append({
                    "text": text,
                    "username": username.lstrip("@"),
                    "fullname": fullname,
                    "timestamp": timestamp,
                    "retweets": stats.get("retweets", 0),
                    "likes": stats.get("likes", 0),
                    "replies": stats.get("replies", 0),
                    "quotes": stats.get("quotes", 0),
                    "url": tweet_url,
                    "source_query": source,
                })

            except Exception as e:
                logger.debug(f"Error parsing tweet: {e}")
                continue

        return tweets

    def _parse_number(self, text: str) -> int:
        """Parse numbers like '1.2K', '5M', or '500'."""
        text = text.lower().replace(",", "")
        match = re.search(r"([\d.]+)\s*([km])?", text)
        if not match:
            return 0

        num = float(match.group(1))
        suffix = match.group(2)

        if suffix == "k":
            return int(num * 1000)
        elif suffix == "m":
            return int(num * 1000000)
        return int(num)

    async def store_tweet(self, tweet: dict) -> None:
        """Store a tweet to the database."""
        coins = detect_coins(tweet["text"])
        sentiment = sentiment_analyzer.analyze(tweet["text"])

        # Store raw
        raw = SentimentRaw(
            timestamp=tweet["timestamp"],
            source="twitter",
            coin=coins[0] if coins else None,
            raw_data={
                "url": tweet.get("url", ""),
                "text": tweet["text"][:1000],
                "username": tweet["username"],
                "fullname": tweet.get("fullname", ""),
                "retweets": tweet.get("retweets", 0),
                "likes": tweet.get("likes", 0),
                "replies": tweet.get("replies", 0),
                "source_query": tweet.get("source_query", ""),
                "backfill": True,
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment scores
        for coin in coins or ["MARKET"]:
            # Weight by engagement
            engagement = tweet.get("retweets", 0) + tweet.get("likes", 0)
            import math
            confidence = min(0.9, 0.5 + math.log1p(engagement) / 20)

            score = SentimentScore(
                timestamp=tweet["timestamp"],
                coin=coin,
                source="twitter",
                score=sentiment["compound"],
                confidence=confidence,
                sample_size=1,
            )
            await self.db.insert_sentiment_score(score)

        self.stats["tweets_stored"] += 1

    async def backfill_searches(self) -> int:
        """Backfill from search queries."""
        logger.info(f"Backfilling {len(SEARCH_QUERIES)} search queries...")
        total = 0

        for i, query in enumerate(SEARCH_QUERIES):
            try:
                logger.info(f"[{i+1}/{len(SEARCH_QUERIES)}] Searching: {query}")

                # Use API if available, otherwise fall back to Nitter
                if self.use_api:
                    tweets = await self.search_via_api(query, max_tweets=100)
                else:
                    tweets = await self.scrape_search(query, max_tweets=50)

                for tweet in tweets:
                    await self.store_tweet(tweet)
                    total += 1

                self.stats["queries_scraped"] += 1
                self.stats["tweets_fetched"] += len(tweets)

                if tweets:
                    logger.info(f"  Found {len(tweets)} tweets")

                # Pause between queries (shorter for API)
                await asyncio.sleep(2 if self.use_api else 5)

            except Exception as e:
                logger.error(f"Error on query '{query}': {e}")
                self.stats["errors"] += 1

        return total

    async def backfill_accounts(self) -> int:
        """Backfill from crypto influencer accounts."""
        logger.info(f"Backfilling {len(CRYPTO_ACCOUNTS)} accounts...")
        total = 0

        for i, username in enumerate(CRYPTO_ACCOUNTS):
            try:
                logger.info(f"[{i+1}/{len(CRYPTO_ACCOUNTS)}] Scraping: @{username}")
                tweets = await self.scrape_account(username, max_tweets=30)

                for tweet in tweets:
                    await self.store_tweet(tweet)
                    total += 1

                self.stats["accounts_scraped"] += 1
                self.stats["tweets_fetched"] += len(tweets)

                if tweets:
                    logger.info(f"  Found {len(tweets)} tweets")

                # Pause between accounts
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error on @{username}: {e}")
                self.stats["errors"] += 1

        return total

    async def run_full_backfill(self) -> dict:
        """Run complete Twitter backfill."""
        logger.info("=" * 60)
        logger.info("STARTING TWITTER BACKFILL")
        if self.use_api:
            logger.info("Mode: Twitter API v2")
        else:
            logger.info("Mode: Nitter scraping (set TWITTER_BEARER_TOKEN for API)")
        logger.info("=" * 60)

        start_time = datetime.now(timezone.utc)

        # For Nitter mode, find working instance first
        if not self.use_api:
            instance = await self.find_working_instance()
            if not instance:
                logger.error("No working Nitter instance available.")
                logger.info("")
                logger.info("To use Twitter/X, set TWITTER_BEARER_TOKEN in .env")
                logger.info("Get a free API key at: https://developer.twitter.com/")
                logger.info("")
                return self.stats

        # Backfill searches
        await self.backfill_searches()

        # Backfill accounts (only for Nitter mode - API requires user lookup)
        if not self.use_api:
            await self.backfill_accounts()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("TWITTER BACKFILL COMPLETE")
        logger.info(f"  Tweets fetched: {self.stats['tweets_fetched']}")
        logger.info(f"  Tweets stored: {self.stats['tweets_stored']}")
        logger.info(f"  Queries scraped: {self.stats['queries_scraped']}")
        logger.info(f"  Accounts scraped: {self.stats['accounts_scraped']}")
        logger.info(f"  Errors: {self.stats['errors']}")
        logger.info(f"  Time elapsed: {elapsed:.1f}s")
        logger.info("=" * 60)

        return self.stats


async def run_twitter_backfill() -> dict:
    """Main entry point for Twitter backfill."""
    db = Database()
    await db.connect()

    backfiller = TwitterBackfiller(db)

    try:
        await backfiller.initialize()
        stats = await backfiller.run_full_backfill()
        return stats
    finally:
        await backfiller.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_twitter_backfill())
