"""Reddit collector for crypto sentiment from subreddits."""

import re
from datetime import datetime, timezone

import asyncpraw

from ..config import settings
from ..processing.sentiment import sentiment_analyzer
from ..storage.db import Database
from ..storage.models import SentimentRaw, SentimentScore
from .base import BaseCollector

# Subreddits to monitor
SUBREDDITS = [
    "cryptocurrency",
    "bitcoin",
    "ethereum",
    "solana",
    "altcoin",
]

# Patterns to detect coin mentions
COIN_PATTERNS = {
    "BTC": [r"\bBTC\b", r"\b[Bb]itcoin\b"],
    "ETH": [r"\bETH\b", r"\b[Ee]thereum\b"],
    "SOL": [r"\bSOL\b", r"\b[Ss]olana\b"],
    "BNB": [r"\bBNB\b", r"\b[Bb]inance\s*[Cc]oin\b"],
    "XRP": [r"\bXRP\b", r"\b[Rr]ipple\b"],
    "ADA": [r"\bADA\b", r"\b[Cc]ardano\b"],
    "DOGE": [r"\bDOGE\b", r"\b[Dd]oge\s*[Cc]oin\b"],
    "AVAX": [r"\bAVAX\b", r"\b[Aa]valanche\b"],
    "DOT": [r"\bDOT\b", r"\b[Pp]olkadot\b"],
    "MATIC": [r"\bMATIC\b", r"\b[Pp]olygon\b"],
    "LINK": [r"\bLINK\b", r"\b[Cc]hainlink\b"],
}

# Compile patterns for efficiency
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


class RedditCollector(BaseCollector):
    """Collector for Reddit crypto sentiment."""

    name = "reddit"

    def __init__(self, db: Database, limit_per_sub: int = 25):
        super().__init__(db)
        self.limit_per_sub = limit_per_sub
        self.reddit: asyncpraw.Reddit | None = None

    async def _init_reddit(self) -> None:
        """Initialize Reddit client."""
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            raise ValueError(
                "Reddit API credentials not configured. "
                "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
            )

        self.reddit = asyncpraw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )

    async def close(self) -> None:
        """Close the Reddit client."""
        if self.reddit:
            await self.reddit.close()

    async def collect(self) -> None:
        """Fetch posts from crypto subreddits and analyze sentiment."""
        await self._init_reddit()
        if not self.reddit:
            return

        timestamp = datetime.now(timezone.utc)
        all_posts = []

        # Collect posts from each subreddit
        for sub_name in SUBREDDITS:
            try:
                subreddit = await self.reddit.subreddit(sub_name)

                # Get hot posts
                async for post in subreddit.hot(limit=self.limit_per_sub):
                    post_data = await self._process_post(post, sub_name)
                    if post_data:
                        all_posts.append(post_data)

            except Exception as e:
                self.logger.warning(f"Error fetching r/{sub_name}: {e}")
                continue

        if not all_posts:
            self.logger.warning("No posts collected")
            return

        # Store raw data
        raw = SentimentRaw(
            timestamp=timestamp,
            source=self.name,
            coin=None,
            raw_data={"posts": all_posts, "subreddits": SUBREDDITS},
        )
        await self.db.insert_sentiment_raw(raw)

        # Aggregate sentiment by coin
        await self._aggregate_by_coin(all_posts, timestamp)

        self.logger.info(f"Processed {len(all_posts)} posts from {len(SUBREDDITS)} subreddits")

    async def _process_post(self, post, subreddit: str) -> dict | None:
        """Process a single post and extract relevant data."""
        try:
            # Combine title and selftext for analysis
            text = f"{post.title} {post.selftext or ''}"
            coins = detect_coins(text)

            # Skip if no coins detected (unless it's a general crypto sub)
            if not coins and subreddit not in ["cryptocurrency", "altcoin"]:
                # For coin-specific subs, assign the main coin
                coin_map = {
                    "bitcoin": "BTC",
                    "ethereum": "ETH",
                    "solana": "SOL",
                }
                if subreddit in coin_map:
                    coins = [coin_map[subreddit]]
                else:
                    return None

            # Analyze sentiment
            sentiment_score = sentiment_analyzer.get_score(text)

            # Calculate engagement weight (log scale to prevent outliers)
            import math

            engagement = post.score + post.num_comments
            weight = math.log1p(engagement)  # log(1 + engagement)

            return {
                "id": post.id,
                "subreddit": subreddit,
                "title": post.title,
                "score": post.score,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "coins": coins,
                "sentiment": sentiment_score,
                "weight": weight,
            }

        except Exception as e:
            self.logger.debug(f"Error processing post: {e}")
            return None

    async def _aggregate_by_coin(self, posts: list[dict], timestamp: datetime) -> None:
        """Aggregate sentiment scores by coin."""
        # Group posts by coin
        coin_data: dict[str, list[tuple[float, float]]] = {}  # coin -> [(score, weight)]

        for post in posts:
            for coin in post.get("coins", []):
                if coin not in coin_data:
                    coin_data[coin] = []
                coin_data[coin].append((post["sentiment"], post["weight"]))

        # Also calculate market-wide sentiment
        all_scores = [(p["sentiment"], p["weight"]) for p in posts]
        if all_scores:
            scores, weights = zip(*all_scores)
            market_score = sentiment_analyzer.aggregate_scores(list(scores), list(weights))

            await self.db.insert_sentiment_score(
                SentimentScore(
                    timestamp=timestamp,
                    coin="MARKET",
                    source=self.name,
                    score=max(-1.0, min(1.0, market_score)),
                    confidence=min(1.0, len(posts) / 100),  # More posts = higher confidence
                    sample_size=len(posts),
                )
            )
            self.logger.info(f"MARKET sentiment: {market_score:.3f} (n={len(posts)})")

        # Store per-coin sentiment
        for coin, data in coin_data.items():
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
            self.logger.info(f"{coin} sentiment: {coin_score:.3f} (n={len(data)})")
