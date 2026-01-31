"""
Reddit source discovery: Find crypto-related subreddits.

Discovery methods:
1. Search Reddit for crypto keywords
2. Parse related subreddits from sidebar
3. Find subreddits mentioned in posts
4. Check cross-posts and user activity
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..crawler.fetcher import Fetcher
from ..logging_config import logger


@dataclass
class DiscoveredSubreddit:
    """A discovered subreddit candidate."""

    name: str
    subscribers: int | None = None
    description: str | None = None
    discovered_from: str = ""  # How we found it
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    relevance_score: float = 0.0
    activity_score: float = 0.0
    evaluated: bool = False


# Seed subreddits known to be crypto-related
SEED_SUBREDDITS = [
    "bitcoin",
    "ethereum",
    "cryptocurrency",
    "cryptomarkets",
    "solana",
    "altcoin",
    "defi",
    "nft",
]

# Keywords that indicate crypto relevance
CRYPTO_KEYWORDS = [
    r"\bcrypto\b",
    r"\bbitcoin\b",
    r"\bbtc\b",
    r"\bethereum\b",
    r"\beth\b",
    r"\bblockchain\b",
    r"\bdefi\b",
    r"\bnft\b",
    r"\btoken\b",
    r"\bcoin\b",
    r"\bwallet\b",
    r"\bhodl\b",
    r"\bmoon\b",
    r"\bsatoshi\b",
    r"\bstaking\b",
    r"\byield\b",
    r"\bdex\b",
    r"\bswap\b",
]

CRYPTO_PATTERNS = [re.compile(p, re.IGNORECASE) for p in CRYPTO_KEYWORDS]


class RedditDiscovery:
    """Discover crypto-related subreddits."""

    def __init__(self, fetcher: Fetcher | None = None):
        self.fetcher = fetcher
        self._owns_fetcher = fetcher is None
        self.discovered: dict[str, DiscoveredSubreddit] = {}
        self.rejected: set[str] = set()  # Subreddits we've evaluated and rejected

    async def __aenter__(self):
        if self._owns_fetcher:
            self.fetcher = Fetcher()
            await self.fetcher.start()
        return self

    async def __aexit__(self, *args):
        if self._owns_fetcher and self.fetcher:
            await self.fetcher.close()

    async def discover_from_search(self, query: str = "crypto") -> list[DiscoveredSubreddit]:
        """
        Search Reddit for subreddits matching a query.
        Uses old.reddit.com/subreddits/search
        """
        url = f"https://old.reddit.com/subreddits/search?q={query}"

        result = await self.fetcher.fetch(url, rate_limit=1.0)
        if not result.success:
            logger.error(f"Failed to search subreddits: {result.error}")
            return []

        soup = BeautifulSoup(result.content, "lxml")
        found = []

        for entry in soup.select("div.search-result-subreddit"):
            try:
                # Extract subreddit name
                link = entry.select_one("a.search-subreddit-link")
                if not link:
                    continue

                href = link.get("href", "")
                match = re.search(r"/r/(\w+)", href)
                if not match:
                    continue

                name = match.group(1).lower()

                # Skip already known
                if name in self.discovered or name in self.rejected:
                    continue

                # Extract subscriber count
                subscribers = None
                sub_info = entry.select_one("span.search-subscribers")
                if sub_info:
                    sub_text = sub_info.get_text()
                    sub_match = re.search(r"([\d,]+)", sub_text)
                    if sub_match:
                        subscribers = int(sub_match.group(1).replace(",", ""))

                # Extract description
                description = None
                desc_elem = entry.select_one("p.search-result-meta-item")
                if desc_elem:
                    description = desc_elem.get_text().strip()

                sub = DiscoveredSubreddit(
                    name=name,
                    subscribers=subscribers,
                    description=description,
                    discovered_from=f"search:{query}",
                )

                self.discovered[name] = sub
                found.append(sub)
                logger.info(f"Discovered r/{name} ({subscribers} subscribers) from search")

            except Exception as e:
                logger.debug(f"Error parsing search result: {e}")
                continue

        return found

    async def discover_from_sidebar(self, subreddit: str) -> list[DiscoveredSubreddit]:
        """
        Find related subreddits from a subreddit's sidebar.
        """
        url = f"https://old.reddit.com/r/{subreddit}"

        result = await self.fetcher.fetch(url, rate_limit=1.0)
        if not result.success:
            return []

        soup = BeautifulSoup(result.content, "lxml")
        found = []

        # Look for subreddit links in sidebar
        sidebar = soup.select_one("div.side")
        if not sidebar:
            return found

        for link in sidebar.select("a[href*='/r/']"):
            href = link.get("href", "")
            match = re.search(r"/r/(\w+)", href)
            if not match:
                continue

            name = match.group(1).lower()

            # Skip already known, self-references, and common non-crypto subs
            if name in self.discovered or name in self.rejected:
                continue
            if name == subreddit.lower():
                continue
            if name in {"all", "popular", "random", "mods", "announcements"}:
                continue

            sub = DiscoveredSubreddit(
                name=name,
                discovered_from=f"sidebar:{subreddit}",
            )

            self.discovered[name] = sub
            found.append(sub)

        if found:
            logger.info(f"Discovered {len(found)} subreddits from r/{subreddit} sidebar")

        return found

    async def discover_from_posts(self, subreddit: str, limit: int = 25) -> list[DiscoveredSubreddit]:
        """
        Find subreddits mentioned in posts (crossposted or mentioned).
        """
        url = f"https://old.reddit.com/r/{subreddit}/new"

        result = await self.fetcher.fetch(url, rate_limit=1.0)
        if not result.success:
            return []

        soup = BeautifulSoup(result.content, "lxml")
        found = []
        seen = set()

        # Look for subreddit mentions in post content
        for thing in soup.select("div.thing.link")[:limit]:
            # Check for crosspost
            crosspost = thing.get("data-crosspost-root-subreddit")
            if crosspost and crosspost.lower() not in seen:
                seen.add(crosspost.lower())

            # Check title for r/subreddit mentions
            title = thing.select_one("a.title")
            if title:
                text = title.get_text()
                for match in re.finditer(r"r/(\w+)", text, re.IGNORECASE):
                    name = match.group(1).lower()
                    if name not in seen:
                        seen.add(name)

        # Create discovered objects
        for name in seen:
            if name in self.discovered or name in self.rejected:
                continue
            if name == subreddit.lower():
                continue

            sub = DiscoveredSubreddit(
                name=name,
                discovered_from=f"mentioned:{subreddit}",
            )
            self.discovered[name] = sub
            found.append(sub)

        if found:
            logger.info(f"Discovered {len(found)} subreddits mentioned in r/{subreddit}")

        return found

    async def discover_all(self) -> list[DiscoveredSubreddit]:
        """
        Run full discovery from seed subreddits.
        """
        all_found = []

        # Search for crypto-related terms
        search_terms = ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "trading crypto"]
        for term in search_terms:
            found = await self.discover_from_search(term)
            all_found.extend(found)
            await asyncio.sleep(2)  # Rate limit

        # Discover from seed subreddit sidebars and posts
        for seed in SEED_SUBREDDITS:
            found = await self.discover_from_sidebar(seed)
            all_found.extend(found)
            await asyncio.sleep(1)

            found = await self.discover_from_posts(seed)
            all_found.extend(found)
            await asyncio.sleep(1)

        logger.info(f"Discovery complete: {len(self.discovered)} total subreddits found")
        return all_found

    def compute_relevance(self, subreddit: DiscoveredSubreddit) -> float:
        """
        Compute relevance score based on name and description.
        Returns 0.0-1.0
        """
        score = 0.0
        text = f"{subreddit.name} {subreddit.description or ''}"

        # Check for crypto keywords
        matches = sum(1 for p in CRYPTO_PATTERNS if p.search(text))
        score += min(matches * 0.15, 0.6)

        # Bonus for explicit crypto in name
        if any(kw in subreddit.name.lower() for kw in ["crypto", "bitcoin", "eth", "defi", "coin"]):
            score += 0.3

        # Bonus for being discovered from trusted sources
        if "sidebar:" in subreddit.discovered_from:
            score += 0.1

        return min(score, 1.0)

    def get_candidates(self, min_relevance: float = 0.3) -> list[DiscoveredSubreddit]:
        """Get candidates with minimum relevance score."""
        candidates = []
        for sub in self.discovered.values():
            if not sub.evaluated:
                sub.relevance_score = self.compute_relevance(sub)
            if sub.relevance_score >= min_relevance:
                candidates.append(sub)

        # Sort by relevance
        candidates.sort(key=lambda s: s.relevance_score, reverse=True)
        return candidates

    def reject(self, name: str) -> None:
        """Mark a subreddit as rejected (not suitable)."""
        self.rejected.add(name.lower())
        if name.lower() in self.discovered:
            del self.discovered[name.lower()]
