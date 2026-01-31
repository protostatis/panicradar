"""Async HTTP fetcher with rate limiting, retries, and UA rotation."""

import asyncio
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# Pool of realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]


@dataclass
class RateLimiter:
    """Token bucket rate limiter per domain."""

    requests_per_second: float = 1.0
    burst_size: int = 5

    # Internal state
    tokens: float = field(default=0.0, init=False)
    last_update: float = field(default_factory=time.monotonic, init=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self.tokens = float(self.burst_size)

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now

            # Add tokens based on elapsed time
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.requests_per_second,
            )

            if self.tokens < 1:
                # Wait for token to become available
                wait_time = (1 - self.tokens) / self.requests_per_second
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    url: str
    status_code: int
    content: str
    headers: dict
    elapsed_seconds: float
    success: bool
    error: str | None = None


class Fetcher:
    """
    Async HTTP fetcher with rate limiting, retries, and user-agent rotation.
    """

    def __init__(
        self,
        default_rate_limit: float = 1.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        randomize_delay: bool = True,
        delay_range: tuple[float, float] = (0.5, 2.0),
    ):
        self.default_rate_limit = default_rate_limit
        self.timeout = timeout
        self.max_retries = max_retries
        self.randomize_delay = randomize_delay
        self.delay_range = delay_range

        # Rate limiters per domain
        self.rate_limiters: dict[str, RateLimiter] = {}

        # HTTP client
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc

    def _get_rate_limiter(self, url: str, rate_limit: float | None = None) -> RateLimiter:
        """Get or create rate limiter for domain."""
        domain = self._get_domain(url)
        if domain not in self.rate_limiters:
            self.rate_limiters[domain] = RateLimiter(
                requests_per_second=rate_limit or self.default_rate_limit,
            )
        return self.rate_limiters[domain]

    def _get_headers(self, extra_headers: dict | None = None) -> dict:
        """Build request headers with random user agent."""
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _fetch_with_retry(
        self,
        url: str,
        headers: dict,
    ) -> httpx.Response:
        """Fetch URL with automatic retry on failure."""
        if not self.client:
            raise RuntimeError("Fetcher not started. Call start() first.")
        return await self.client.get(url, headers=headers)

    async def fetch(
        self,
        url: str,
        rate_limit: float | None = None,
        extra_headers: dict | None = None,
    ) -> FetchResult:
        """
        Fetch a URL with rate limiting and retries.

        Args:
            url: URL to fetch
            rate_limit: Override rate limit for this domain
            extra_headers: Additional headers to include

        Returns:
            FetchResult with content or error
        """
        # Rate limiting
        limiter = self._get_rate_limiter(url, rate_limit)
        await limiter.acquire()

        # Random delay for politeness
        if self.randomize_delay:
            delay = random.uniform(*self.delay_range)
            await asyncio.sleep(delay)

        headers = self._get_headers(extra_headers)
        start_time = time.monotonic()

        try:
            response = await self._fetch_with_retry(url, headers)
            elapsed = time.monotonic() - start_time

            return FetchResult(
                url=url,
                status_code=response.status_code,
                content=response.text,
                headers=dict(response.headers),
                elapsed_seconds=elapsed,
                success=response.status_code == 200,
                error=None if response.status_code == 200 else f"HTTP {response.status_code}",
            )

        except Exception as e:
            elapsed = time.monotonic() - start_time
            return FetchResult(
                url=url,
                status_code=0,
                content="",
                headers={},
                elapsed_seconds=elapsed,
                success=False,
                error=str(e),
            )

    async def fetch_many(
        self,
        urls: list[str],
        rate_limit: float | None = None,
        max_concurrent: int = 5,
    ) -> list[FetchResult]:
        """
        Fetch multiple URLs with concurrency control.

        Args:
            urls: List of URLs to fetch
            rate_limit: Rate limit per domain
            max_concurrent: Maximum concurrent requests

        Returns:
            List of FetchResults in same order as input URLs
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(url: str) -> FetchResult:
            async with semaphore:
                return await self.fetch(url, rate_limit)

        tasks = [fetch_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks)
