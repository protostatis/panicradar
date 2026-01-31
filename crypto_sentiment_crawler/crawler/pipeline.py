"""Content processing pipeline: crawl → parse → analyze → store."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..processing.sentiment import sentiment_analyzer
from .fetcher import Fetcher, FetchResult
from .parser import Parser, ParseResult


# Coin detection patterns
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
    "UNI": [r"\bUNI\b", r"\b[Uu]niswap\b"],
    "ATOM": [r"\bATOM\b", r"\b[Cc]osmos\b"],
    "LTC": [r"\bLTC\b", r"\b[Ll]itecoin\b"],
}

COMPILED_PATTERNS = {
    coin: [re.compile(p) for p in patterns]
    for coin, patterns in COIN_PATTERNS.items()
}


@dataclass
class CrawledContent:
    """Processed content from a crawl."""

    url: str
    source: str
    title: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    crawled_at: datetime
    coins_mentioned: list[str]
    sentiment_score: float
    sentiment_details: dict
    fetch_result: FetchResult
    parse_result: ParseResult
    metadata: dict = field(default_factory=dict)


def detect_coins(text: str) -> list[str]:
    """Detect which coins are mentioned in text."""
    if not text:
        return []

    mentioned = []
    for coin, patterns in COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                mentioned.append(coin)
                break
    return mentioned


class ContentPipeline:
    """
    Pipeline for crawling, parsing, and analyzing content.
    """

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        parser: Parser | None = None,
    ):
        self.fetcher = fetcher or Fetcher()
        self.parser = parser or Parser()
        self._fetcher_owned = fetcher is None

    async def __aenter__(self):
        if self._fetcher_owned:
            await self.fetcher.start()
        return self

    async def __aexit__(self, *args):
        if self._fetcher_owned:
            await self.fetcher.close()

    async def process_url(
        self,
        url: str,
        source: str,
        selectors: dict | None = None,
        rate_limit: float | None = None,
    ) -> CrawledContent:
        """
        Full pipeline: fetch → parse → detect coins → analyze sentiment.

        Args:
            url: URL to crawl
            source: Source identifier (e.g., "coindesk", "reddit")
            selectors: CSS selectors for parsing
            rate_limit: Override rate limit

        Returns:
            CrawledContent with all extracted data
        """
        crawled_at = datetime.now(timezone.utc)

        # Fetch
        fetch_result = await self.fetcher.fetch(url, rate_limit)

        # Parse
        if fetch_result.success:
            parse_result = self.parser.parse(
                fetch_result.content,
                url,
                selectors,
            )
        else:
            parse_result = ParseResult(
                url=url,
                title=None,
                content=None,
                author=None,
                published_at=None,
                links=[],
                metadata={},
                success=False,
                error=fetch_result.error,
            )

        # Combine title and content for analysis
        full_text = " ".join(filter(None, [
            parse_result.title,
            parse_result.content,
        ]))

        # Detect coins
        coins = detect_coins(full_text)

        # Sentiment analysis
        if full_text:
            sentiment_details = sentiment_analyzer.analyze(full_text)
            sentiment_score = sentiment_details["compound"]
        else:
            sentiment_details = {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}
            sentiment_score = 0.0

        return CrawledContent(
            url=url,
            source=source,
            title=parse_result.title,
            content=parse_result.content,
            author=parse_result.author,
            published_at=parse_result.published_at,
            crawled_at=crawled_at,
            coins_mentioned=coins,
            sentiment_score=sentiment_score,
            sentiment_details=sentiment_details,
            fetch_result=fetch_result,
            parse_result=parse_result,
            metadata=parse_result.metadata,
        )

    async def process_urls(
        self,
        urls: list[str],
        source: str,
        selectors: dict | None = None,
        rate_limit: float | None = None,
    ) -> list[CrawledContent]:
        """Process multiple URLs."""
        results = []
        for url in urls:
            result = await self.process_url(url, source, selectors, rate_limit)
            results.append(result)
        return results

    def analyze_text(self, text: str) -> dict:
        """Analyze text without fetching (for already-fetched content)."""
        coins = detect_coins(text)
        sentiment = sentiment_analyzer.analyze(text)

        return {
            "coins": coins,
            "sentiment_score": sentiment["compound"],
            "sentiment_details": sentiment,
        }


class RedditPipeline(ContentPipeline):
    """Specialized pipeline for Reddit (old.reddit.com)."""

    SUBREDDIT_SELECTORS = {
        "post_list": "div.thing.link",
        "title": "a.title",
        "score": "div.score.unvoted",
        "comments": "a.comments",
        "author": "a.author",
        "timestamp": "time",
    }

    async def crawl_subreddit(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
    ) -> list[CrawledContent]:
        """
        Crawl posts from a subreddit using old.reddit.com.

        Args:
            subreddit: Subreddit name (without r/)
            sort: Sort method ('hot', 'new', 'rising', 'top')
            limit: Number of posts to fetch

        Returns:
            List of CrawledContent for each post
        """
        url = f"https://old.reddit.com/r/{subreddit}/{sort}/"

        fetch_result = await self.fetcher.fetch(url, rate_limit=0.5)

        if not fetch_result.success:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(fetch_result.content, "lxml")

        posts = []
        crawled_at = datetime.now(timezone.utc)

        for thing in soup.select("div.thing.link")[:limit]:
            try:
                # Extract post data
                title_elem = thing.select_one("a.title")
                title = title_elem.get_text() if title_elem else None

                score_elem = thing.select_one("div.score.unvoted")
                score_text = score_elem.get_text() if score_elem else "0"
                try:
                    score = int(score_text.replace("•", "0"))
                except ValueError:
                    score = 0

                comments_elem = thing.select_one("a.comments")
                comments_text = comments_elem.get_text() if comments_elem else "0"
                try:
                    num_comments = int(comments_text.split()[0])
                except (ValueError, IndexError):
                    num_comments = 0

                author_elem = thing.select_one("a.author")
                author = author_elem.get_text() if author_elem else None

                post_url = thing.get("data-url", "")
                permalink = thing.get("data-permalink", "")

                # Analyze
                coins = detect_coins(title or "")
                sentiment = sentiment_analyzer.analyze(title or "")

                posts.append(CrawledContent(
                    url=f"https://reddit.com{permalink}" if permalink else post_url,
                    source=f"reddit_{subreddit}",
                    title=title,
                    content=None,
                    author=author,
                    published_at=None,
                    crawled_at=crawled_at,
                    coins_mentioned=coins,
                    sentiment_score=sentiment["compound"],
                    sentiment_details=sentiment,
                    fetch_result=fetch_result,
                    parse_result=ParseResult(
                        url=url,
                        title=title,
                        content=None,
                        author=author,
                        published_at=None,
                        links=[],
                        metadata={},
                        success=True,
                    ),
                    metadata={
                        "score": score,
                        "num_comments": num_comments,
                        "subreddit": subreddit,
                    },
                ))

            except Exception:
                continue

        return posts
