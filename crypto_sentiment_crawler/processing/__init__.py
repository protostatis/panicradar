"""Sentiment processing and aggregation."""

# Lazy imports to avoid requiring all dependencies
# Use: from crypto_sentiment_crawler.processing.sentiment import sentiment_analyzer
# Or:  from crypto_sentiment_crawler.processing.user_sentiment import UserSentimentScorer

__all__ = ["CryptoSentimentAnalyzer", "sentiment_analyzer", "UserSentimentScorer", "SemanticSentimentAnalyzer"]


def __getattr__(name):
    """Lazy import to avoid requiring VADER when only using semantic sentiment."""
    if name in ("CryptoSentimentAnalyzer", "sentiment_analyzer"):
        from .sentiment import CryptoSentimentAnalyzer, sentiment_analyzer
        return CryptoSentimentAnalyzer if name == "CryptoSentimentAnalyzer" else sentiment_analyzer
    elif name == "UserSentimentScorer":
        from .user_sentiment import UserSentimentScorer
        return UserSentimentScorer
    elif name == "SemanticSentimentAnalyzer":
        from .semantic_sentiment import SemanticSentimentAnalyzer
        return SemanticSentimentAnalyzer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
