"""Content processing pipeline: crawl → parse → analyze → store."""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..source_names import reddit_source_key
from .fetcher import Fetcher, FetchResult
from .parser import Parser, ParseResult
from .unbrowser_reddit import ACCESS_DENIAL_ERRORS


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
    """Processed content from a crawl.

    Note: sentiment_score is None during crawling. Actual scoring happens
    in user_sentiment backfill using FinBERT/sentence-transformers.
    """

    url: str
    source: str
    title: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    crawled_at: datetime
    coins_mentioned: list[str]
    sentiment_score: float | None  # Populated by user_sentiment backfill
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

        # Sentiment scoring deferred to user_sentiment backfill (uses FinBERT)
        sentiment_details = {}
        sentiment_score = None

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
        """Analyze text without fetching (for already-fetched content).

        Note: Sentiment scoring is deferred to user_sentiment backfill (uses FinBERT).
        """
        coins = detect_coins(text)

        return {
            "coins": coins,
            "sentiment_score": None,
            "sentiment_details": {},
        }


@dataclass
class RedditComment:
    """A Reddit comment with metadata."""

    author: str | None
    body: str
    score: int
    created_utc: float | None
    published_at: datetime | None
    depth: int = 0


@dataclass
class RedditThread:
    """Full Reddit thread with post body and comments."""

    url: str
    title: str | None
    selftext: str | None  # Post body for text posts
    author: str | None
    score: int
    num_comments: int
    created_utc: float | None
    published_at: datetime | None
    subreddit: str
    comments: list[RedditComment]
    crawled_at: datetime


class RedditFetchError(RuntimeError):
    """A Reddit listing could not be fetched (transport or rate-limit failure).

    Callers use this to distinguish an infrastructure failure from a source
    that fetched successfully but had no fresh posts, so a rate limit does not
    get recorded as an "empty crawl" against the source's belief.

    ``source_unavailable`` marks permanent, source-level denials (private,
    banned, quarantined, missing subreddit) that are worth penalizing: no
    amount of retrying will make them produce content.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        *,
        source_unavailable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.source_unavailable = source_unavailable


_REDDIT_POST_PATH = re.compile(r"^/r/([^/]+)/comments/([^/]+)")


def permalink_key(url: str | None) -> str | None:
    """Return a stable identity key for a Reddit post.

    Stored rows contain both ``https://reddit.com/r/...`` (crawler) and
    ``https://old.reddit.com/r/...`` (backfill/thread) forms, and the title
    slug in the path can change when a post is edited. Keying on
    ``/r/<subreddit>/comments/<post id>`` makes deduplication independent of
    host, slug, query, and trailing slash. Returns None for non-Reddit URLs so
    they never match a listing post.
    """
    if not url:
        return None
    if "://" in url:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host != "reddit.com" and not host.endswith(".reddit.com"):
            return None
        path = parts.path
    else:
        path = url
    path = path.split("?", 1)[0].split("#", 1)[0]
    match = _REDDIT_POST_PATH.match(path)
    if not match:
        return None
    subreddit, post_id = match.groups()
    return f"/r/{subreddit.lower()}/comments/{post_id.lower()}"


@dataclass
class _ListingPost:
    """A post parsed from a subreddit listing, before its thread is fetched."""

    title: str | None
    score: int
    num_comments: int
    author: str | None
    post_url: str
    permalink: str
    created_utc: float | None
    published_at: datetime | None


class RedditPipeline(ContentPipeline):
    """Specialized pipeline for Reddit (old.reddit.com)."""

    # How long a successfully fetched thread is skipped when the orchestrator
    # did not store it (usually too few human comments). Without this, the
    # comment-first cap would keep re-fetching the same unstorable posts and
    # starve lower-ranked posts that would qualify.
    DEFAULT_THREAD_ATTEMPT_TTL_SECONDS = 6 * 3600

    def __init__(
        self,
        *args,
        thread_attempt_ttl_seconds: float = DEFAULT_THREAD_ATTEMPT_TTL_SECONDS,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.thread_attempt_ttl_seconds = thread_attempt_ttl_seconds
        self._thread_attempts: dict[str, float] = {}

    def _prune_thread_attempts(self, now: float) -> None:
        cutoff = now - self.thread_attempt_ttl_seconds
        self._thread_attempts = {
            key: stamp for key, stamp in self._thread_attempts.items()
            if stamp >= cutoff
        }

    SUBREDDIT_SELECTORS = {
        "post_list": "div.thing.link",
        "title": "a.title",
        "score": "div.score.unvoted",
        "comments": "a.comments",
        "author": "a.author",
        "timestamp": "time",
    }

    async def fetch_thread(
        self,
        permalink: str,
        max_comments: int = 20,
    ) -> RedditThread | None:
        """
        Fetch a full Reddit thread with post body and comments.

        Args:
            permalink: Reddit permalink (e.g., /r/bitcoin/comments/abc123/title/)
            max_comments: Maximum number of comments to extract

        Returns:
            RedditThread with full content, or None on failure
        """
        # Use old.reddit.com for static HTML
        if permalink.startswith("http"):
            url = permalink.replace("www.reddit.com", "old.reddit.com").replace("reddit.com", "old.reddit.com")
        else:
            url = f"https://old.reddit.com{permalink}"

        fetch_result = await self.fetcher.fetch(url, rate_limit=0.5)

        if not fetch_result.success:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(fetch_result.content, "lxml")
        crawled_at = datetime.now(timezone.utc)

        # Extract post info
        thing = soup.select_one("div.thing.link")
        if not thing:
            return None

        # Title
        title_elem = thing.select_one("a.title")
        title = title_elem.get_text() if title_elem else None

        # Author
        author_elem = thing.select_one("a.author")
        author = author_elem.get_text() if author_elem else None

        # Score
        score_elem = thing.select_one("div.score.unvoted")
        score_text = score_elem.get_text() if score_elem else "0"
        try:
            score = int(score_text.replace("•", "0"))
        except ValueError:
            score = 0

        # Timestamp
        timestamp_attr = thing.get("data-timestamp")
        if timestamp_attr:
            try:
                created_utc = int(timestamp_attr) / 1000
                published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                created_utc = None
                published_at = None
        else:
            created_utc = None
            published_at = None

        # Subreddit
        subreddit = thing.get("data-subreddit", "")

        # Self-text (post body)
        selftext = None
        usertext = soup.select_one("div.expando form.usertext div.md")
        if usertext:
            selftext = usertext.get_text(separator="\n").strip()

        # Comments
        comments = []
        comment_area = soup.select_one("div.commentarea")
        if comment_area:
            for comment_thing in comment_area.select("div.thing.comment")[:max_comments]:
                try:
                    # Skip deleted/removed
                    if "deleted" in comment_thing.get("class", []):
                        continue

                    # Author
                    c_author_elem = comment_thing.select_one("a.author")
                    c_author = c_author_elem.get_text() if c_author_elem else None

                    # Body
                    c_body_elem = comment_thing.select_one("div.md")
                    c_body = c_body_elem.get_text(separator="\n").strip() if c_body_elem else ""

                    if not c_body:
                        continue

                    # Score
                    c_score_elem = comment_thing.select_one("span.score.unvoted")
                    c_score_text = c_score_elem.get_text() if c_score_elem else "0"
                    try:
                        # Format: "X points"
                        c_score = int(c_score_text.split()[0])
                    except (ValueError, IndexError):
                        c_score = 0

                    # Timestamp
                    c_time_elem = comment_thing.select_one("time")
                    c_created_utc = None
                    c_published_at = None
                    if c_time_elem and c_time_elem.get("datetime"):
                        try:
                            c_published_at = datetime.fromisoformat(
                                c_time_elem["datetime"].replace("Z", "+00:00")
                            )
                            c_created_utc = c_published_at.timestamp()
                        except (ValueError, TypeError):
                            pass

                    # Depth (nesting level)
                    depth = len(comment_thing.find_parents("div", class_="thing"))

                    comments.append(RedditComment(
                        author=c_author,
                        body=c_body[:2000],  # Limit comment length
                        score=c_score,
                        created_utc=c_created_utc,
                        published_at=c_published_at,
                        depth=depth,
                    ))

                except Exception:
                    continue

        return RedditThread(
            url=url,
            title=title,
            selftext=selftext,
            author=author,
            score=score,
            num_comments=len(comments),
            created_utc=created_utc,
            published_at=published_at,
            subreddit=subreddit,
            comments=comments,
            crawled_at=crawled_at,
        )

    async def crawl_subreddit(
        self,
        subreddit: str,
        sort: str = "new",
        limit: int = 25,
        max_age_hours: float | None = None,
        fetch_content: bool = True,
        max_comments: int = 10,
        known_permalinks: set[str] | None = None,
        max_thread_fetches: int | None = None,
    ) -> list[CrawledContent]:
        """
        Crawl posts from a subreddit using old.reddit.com.

        Args:
            subreddit: Subreddit name (without r/)
            sort: Sort method ('hot', 'new', 'rising', 'top') - default 'new' for fresh content
            limit: Number of posts to fetch
            max_age_hours: Maximum post age in hours. Posts older than this are filtered out.
                          Use None for no filtering (training mode).
                          Use 2-4 hours for inference mode.
            fetch_content: If True, fetch full thread content and comments (slower but richer)
            max_comments: Maximum comments to fetch per thread
            known_permalinks: Normalized permalink keys (see ``permalink_key``) that are
                already stored. Matching posts are returned without refetching their thread.
            max_thread_fetches: Maximum number of thread pages to fetch for this listing.
                None means no cap. Posts left unfetched are still returned as metadata-only
                content so a healthy source is not mistaken for an empty one.

        Returns:
            List of CrawledContent for each post.

        Raises:
            RedditFetchError: The listing itself could not be fetched (transport or
                rate-limit failure). An empty list means the listing loaded but had no
                posts that passed the filters.
        """
        url = f"https://old.reddit.com/r/{subreddit}/{sort}/"

        fetch_result = await self.fetcher.fetch(url, rate_limit=0.5)

        if not fetch_result.success:
            error = fetch_result.error or "unknown error"
            # A 404 listing means the subreddit does not exist (or is gone);
            # 403 is ambiguous (block page vs. private subreddit), so only the
            # known access-denial messages make it permanent.
            source_unavailable = (
                fetch_result.status_code == 404
                or any(denial in error for denial in ACCESS_DENIAL_ERRORS)
            )
            raise RedditFetchError(
                f"Reddit listing fetch failed for r/{subreddit}: {error}",
                status_code=fetch_result.status_code,
                source_unavailable=source_unavailable,
            )

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(fetch_result.content, "lxml")

        crawled_at = datetime.now(timezone.utc)
        known = known_permalinks or set()
        candidates: list[_ListingPost] = []

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

                # Extract post timestamp (data-timestamp is in milliseconds)
                timestamp_attr = thing.get("data-timestamp")
                if timestamp_attr:
                    try:
                        created_utc = int(timestamp_attr) / 1000  # Convert ms to seconds
                        published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                    except (ValueError, TypeError, OSError):
                        created_utc = None
                        published_at = None
                else:
                    created_utc = None
                    published_at = None

                # Filter by age if max_age_hours is specified (inference mode)
                if max_age_hours is not None and published_at is not None:
                    age_hours = (crawled_at - published_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        continue  # Skip posts older than threshold

                candidates.append(_ListingPost(
                    title=title,
                    score=score,
                    num_comments=num_comments,
                    author=author,
                    post_url=post_url,
                    permalink=permalink,
                    created_utc=created_utc,
                    published_at=published_at,
                ))
            except Exception:
                continue

        # Thread pages are the expensive part of a crawl (Reddit charges roughly
        # a dozen rate-limit units per HTML page), so only fetch pages we still
        # need, most-commented first: those are the posts most likely to clear
        # the human-comment threshold used before storing.
        threads: dict[str, RedditThread | None] = {}
        if fetch_content:
            self._prune_thread_attempts(time.monotonic())
            pending = []
            for post in candidates:
                if not post.permalink:
                    continue
                key = permalink_key(post.permalink)
                if key and (key in known or key in self._thread_attempts):
                    continue
                pending.append(post)
            pending.sort(
                key=lambda post: (
                    post.num_comments,
                    post.published_at or crawled_at,
                ),
                reverse=True,
            )
            if max_thread_fetches is not None:
                pending = pending[:max(0, max_thread_fetches)]
            for post in pending:
                thread = await self.fetch_thread(
                    post.permalink,
                    max_comments=max_comments,
                )
                threads[post.permalink] = thread
                key = permalink_key(post.permalink)
                if thread is not None and key:
                    # Remember successful fetches so an unstorable post does
                    # not monopolise the cap on the next crawl. Failures are
                    # not remembered so a transport blip retries promptly.
                    self._thread_attempts[key] = time.monotonic()

        posts = []
        for candidate in candidates:
            title = candidate.title
            score = candidate.score
            permalink = candidate.permalink
            content = None
            comments_data = []

            thread = threads.get(permalink) if permalink else None
            if thread:
                # Use only selftext for content (don't include comments)
                # Comments are stored separately in metadata for optional analysis
                content = thread.selftext if thread.selftext else None

                # Store comment metadata
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

                # Update score from thread (more accurate)
                score = thread.score

            # Analyze full text (title + content)
            full_text = " ".join(filter(None, [title, content]))
            coins = detect_coins(full_text)
            # Sentiment scoring deferred to user_sentiment backfill (uses FinBERT)

            posts.append(CrawledContent(
                url=f"https://reddit.com{permalink}" if permalink else candidate.post_url,
                source=reddit_source_key(subreddit),
                title=title,
                content=content,
                author=candidate.author,
                published_at=candidate.published_at,
                crawled_at=crawled_at,
                coins_mentioned=coins,
                sentiment_score=None,
                sentiment_details={},
                fetch_result=fetch_result,
                parse_result=ParseResult(
                    url=url,
                    title=title,
                    content=content,
                    author=candidate.author,
                    published_at=candidate.published_at,
                    links=[],
                    metadata={},
                    success=True,
                ),
                metadata={
                    "score": score,
                    "num_comments": candidate.num_comments,
                    "subreddit": subreddit,
                    "created_utc": candidate.created_utc,
                    "comments": comments_data,
                },
            ))

        return posts
