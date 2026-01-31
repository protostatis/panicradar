"""General-purpose web crawler with httpx + BeautifulSoup."""

from .fetcher import Fetcher, RateLimiter
from .parser import Parser, ParseResult
from .pipeline import ContentPipeline, CrawledContent
from .sources import SourceConfig, load_source_config

__all__ = [
    "Fetcher",
    "RateLimiter",
    "Parser",
    "ParseResult",
    "ContentPipeline",
    "CrawledContent",
    "SourceConfig",
    "load_source_config",
]
