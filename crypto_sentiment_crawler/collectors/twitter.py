"""Twitter/X collector for crypto sentiment.

Uses web scraping approach since official API requires paid access.
Falls back to Nitter instances when available.
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..processing.sentiment import sentiment_analyzer
from ..storage.db import Database
from ..storage.models import SentimentRaw, SentimentScore
from .base import BaseCollector

# Crypto-related search queries
SEARCH_QUERIES = [
    "#Bitcoin",
    "#BTC",
    "#Ethereum",
    "#ETH",
    "#Crypto",
    "#Solana",
    "#Altcoins",
    "Bitcoin price",
    "crypto market",
]

# Nitter instances (public Twitter frontend mirrors)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.woodland.cafe",
]

# Patterns to detect coin mentions (same as Reddit)
COIN_PATTERNS = {
    "BTC": [r"\bBTC\b", r"\$BTC\b", r"\b[Bb]itcoin\b"],
    "ETH": [r"\bETH\b", r"\$ETH\b", r"\b[Ee]thereum\b"],
    "SOL": [r"\bSOL\b", r"\$SOL\b", r"\b[Ss]olana\b"],
    "BNB": [r"\bBNB\b", r"\$BNB\b"],
    "XRP": [r"\bXRP\b", r"\$XRP\b", r"\b[Rr]ipple\b"],
    "ADA": [r"\bADA\b", r"\$ADA\b", r"\b[Cc]ardano\b"],
    "DOGE": [r"\bDOGE\b", r"\$DOGE\b", r"\b[Dd]oge\b"],
    "AVAX": [r"\bAVAX\b", r"\$AVAX\b"],
    "DOT": [r"\bDOT\b", r"\$DOT\b", r"\b[Pp]olkadot\b"],
    "MATIC": [r"\bMATIC\b", r"\$MATIC\b", r"\b[Pp]olygon\b"],
    "LINK": [r"\bLINK\b", r"\$LINK\b", r"\b[Cc]hainlink\b"],
}

COMPILED_PATTERNS = {
    coin: [re.compile(p) for p in patterns] for coin, patterns in COIN_PATTERNS.items()
}


def detect_coins(text: str) -> list[str]:
    """Detect which coins are mentioned in text."""
    mentioned = []
    for coin, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                mentioned.append(coin)
                break
    return mentioned


class TwitterCollector(BaseCollector):
    """Collector for Twitter/X crypto sentiment using web scraping."""

    name = "twitter"

    def __init__(self, db: Database, tweets_per_query: int = 20):
        super().__init__(db)
        self.tweets_per_query = tweets_per_query
        self.working_instance: Optional[str] = None
        self.client: Optional[httpx.AsyncClient] = None

    async def _init_client(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def _find_working_instance(self) -> Optional[str]:
        """Find a working Nitter instance."""
        if not self.client:
            await self._init_client()

        for instance in NITTER_INSTANCES:
            try:
                resp = await self.client.get(f"{instance}/search?q=bitcoin", timeout=10.0)
                if resp.status_code == 200:
                    self.logger.info(f"Found working Nitter instance: {instance}")
                    return instance
            except Exception as e:
                self.logger.debug(f"Instance {instance} failed: {e}")
                continue

        return None

    async def _scrape_nitter(self, query: str) -> list[dict]:
        """Scrape tweets from Nitter instance."""
        if not self.working_instance:
            self.working_instance = await self._find_working_instance()
            if not self.working_instance:
                self.logger.warning("No working Nitter instance found")
                return []

        tweets = []
        encoded_query = quote(query)
        url = f"{self.working_instance}/search?q={encoded_query}&f=tweets"

        try:
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # Parse tweet elements (Nitter structure)
            for tweet_div in soup.select(".timeline-item"):
                try:
                    # Extract tweet content
                    content_elem = tweet_div.select_one(".tweet-content")
                    if not content_elem:
                        continue

                    text = content_elem.get_text(strip=True)
                    if not text:
                        continue

                    # Extract username
                    username_elem = tweet_div.select_one(".username")
                    username = username_elem.get_text(strip=True) if username_elem else "unknown"

                    # Extract stats
                    stats = tweet_div.select(".tweet-stat")
                    retweets = 0
                    likes = 0
                    for stat in stats:
                        stat_text = stat.get_text(strip=True)
                        if "retweet" in stat_text.lower():
                            retweets = self._parse_stat_number(stat_text)
                        elif "like" in stat_text.lower():
                            likes = self._parse_stat_number(stat_text)

                    # Extract timestamp
                    time_elem = tweet_div.select_one(".tweet-date a")
                    timestamp = None
                    if time_elem and time_elem.get("title"):
                        try:
                            timestamp = datetime.strptime(
                                time_elem["title"], "%b %d, %Y · %I:%M %p %Z"
                            )
                        except ValueError:
                            timestamp = datetime.now(timezone.utc)

                    tweets.append({
                        "text": text,
                        "username": username,
                        "retweets": retweets,
                        "likes": likes,
                        "timestamp": timestamp or datetime.now(timezone.utc),
                        "query": query,
                    })

                    if len(tweets) >= self.tweets_per_query:
                        break

                except Exception as e:
                    self.logger.debug(f"Error parsing tweet: {e}")
                    continue

        except Exception as e:
            self.logger.warning(f"Error scraping Nitter for '{query}': {e}")
            # Mark instance as failed
            self.working_instance = None

        return tweets

    def _parse_stat_number(self, text: str) -> int:
        """Parse numbers like '1.2K' or '500'."""
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

    async def collect(self) -> None:
        """Fetch tweets from Twitter/X and analyze sentiment."""
        await self._init_client()

        timestamp = datetime.now(timezone.utc)
        all_tweets = []

        for query in SEARCH_QUERIES:
            try:
                tweets = await self._scrape_nitter(query)
                all_tweets.extend(tweets)
                self.logger.debug(f"Collected {len(tweets)} tweets for '{query}'")

                # Rate limiting
                await asyncio.sleep(2)

            except Exception as e:
                self.logger.warning(f"Error collecting tweets for '{query}': {e}")
                continue

        if not all_tweets:
            self.logger.warning("No tweets collected")
            return

        # Deduplicate by text
        seen_texts = set()
        unique_tweets = []
        for tweet in all_tweets:
            text_hash = hash(tweet["text"][:100])
            if text_hash not in seen_texts:
                seen_texts.add(text_hash)
                unique_tweets.append(tweet)

        # Process tweets
        processed_tweets = []
        for tweet in unique_tweets:
            text = tweet["text"]
            coins = detect_coins(text)

            # Analyze sentiment
            sentiment_score = sentiment_analyzer.get_score(text)

            # Engagement weight
            import math
            engagement = tweet["retweets"] + tweet["likes"]
            weight = math.log1p(engagement)

            processed_tweets.append({
                "text": text[:500],  # Truncate for storage
                "username": tweet["username"],
                "coins": coins or ["MARKET"],
                "sentiment": sentiment_score,
                "weight": weight,
                "engagement": engagement,
                "timestamp": tweet["timestamp"].isoformat() if hasattr(tweet["timestamp"], "isoformat") else str(tweet["timestamp"]),
            })

        # Store raw data
        raw = SentimentRaw(
            timestamp=timestamp,
            source=self.name,
            coin=None,
            raw_data={"tweets": processed_tweets, "queries": SEARCH_QUERIES},
        )
        await self.db.insert_sentiment_raw(raw)

        # Aggregate sentiment
        await self._aggregate_by_coin(processed_tweets, timestamp)

        self.logger.info(f"Processed {len(processed_tweets)} unique tweets")

        if self.client:
            await self.client.aclose()

    async def _aggregate_by_coin(self, tweets: list[dict], timestamp: datetime) -> None:
        """Aggregate sentiment scores by coin."""
        coin_data: dict[str, list[tuple[float, float]]] = {}

        for tweet in tweets:
            for coin in tweet.get("coins", []):
                if coin not in coin_data:
                    coin_data[coin] = []
                coin_data[coin].append((tweet["sentiment"], tweet["weight"]))

        # Market-wide sentiment
        all_scores = [(t["sentiment"], t["weight"]) for t in tweets]
        if all_scores:
            scores, weights = zip(*all_scores)
            market_score = sentiment_analyzer.aggregate_scores(list(scores), list(weights))

            await self.db.insert_sentiment_score(
                SentimentScore(
                    timestamp=timestamp,
                    coin="MARKET",
                    source=self.name,
                    score=max(-1.0, min(1.0, market_score)),
                    confidence=min(1.0, len(tweets) / 100),
                    sample_size=len(tweets),
                )
            )
            self.logger.info(f"Twitter MARKET sentiment: {market_score:.3f} (n={len(tweets)})")

        # Per-coin sentiment
        for coin, data in coin_data.items():
            if coin == "MARKET":
                continue
            scores, weights = zip(*data)
            coin_score = sentiment_analyzer.aggregate_scores(list(scores), list(weights))

            await self.db.insert_sentiment_score(
                SentimentScore(
                    timestamp=timestamp,
                    coin=coin,
                    source=self.name,
                    score=max(-1.0, min(1.0, coin_score)),
                    confidence=min(1.0, len(data) / 20),
                    sample_size=len(data),
                )
            )
            self.logger.info(f"Twitter {coin} sentiment: {coin_score:.3f} (n={len(data)})")
