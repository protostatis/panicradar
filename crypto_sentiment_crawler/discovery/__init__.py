"""Source discovery module for finding new data sources."""

from .reddit_discovery import RedditDiscovery
from .evaluator import SourceEvaluator
from .manager import SourceManager

__all__ = ["RedditDiscovery", "SourceEvaluator", "SourceManager"]
