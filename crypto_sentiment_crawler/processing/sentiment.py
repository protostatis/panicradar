"""Sentiment analysis using VADER with crypto-specific lexicon."""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Crypto-specific terms to add to VADER's lexicon
CRYPTO_LEXICON = {
    # Bullish terms
    "moon": 3.0,
    "mooning": 3.5,
    "bullish": 2.5,
    "hodl": 2.0,
    "hodling": 2.0,
    "diamond hands": 2.5,
    "diamondhands": 2.5,
    "to the moon": 3.0,
    "ttm": 2.5,
    "ath": 1.5,  # All-time high
    "breakout": 2.0,
    "pumping": 2.0,
    "accumulate": 1.5,
    "accumulating": 1.5,
    "undervalued": 1.5,
    "bullrun": 3.0,
    "bull run": 3.0,
    "lambo": 2.0,
    "wagmi": 2.5,  # We're all gonna make it
    # Bearish terms
    "bearish": -2.5,
    "rekt": -3.0,
    "rug": -3.5,
    "rugpull": -4.0,
    "rug pull": -4.0,
    "rugged": -4.0,
    "dump": -2.5,
    "dumping": -2.5,
    "crashed": -3.0,
    "crash": -2.5,
    "scam": -4.0,
    "ponzi": -4.0,
    "paper hands": -1.5,
    "paperhands": -1.5,
    "sell off": -2.0,
    "selloff": -2.0,
    "bloodbath": -3.0,
    "capitulation": -3.0,
    "ngmi": -2.5,  # Not gonna make it
    # Neutral-ish but contextual
    "fud": -1.5,  # Fear, uncertainty, doubt (usually negative context)
    "fomo": 1.0,  # Fear of missing out (positive but irrational)
    "whale": 0.5,
    "dip": -0.5,
    "correction": -1.0,
    "consolidation": 0.0,
    "crab": 0.0,  # Sideways market
    "altseason": 2.0,
    "btfd": 1.5,  # Buy the f***ing dip
}


class CryptoSentimentAnalyzer:
    """Sentiment analyzer tuned for crypto text."""

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        # Add crypto-specific terms to the lexicon
        self.analyzer.lexicon.update(CRYPTO_LEXICON)

    def analyze(self, text: str) -> dict:
        """
        Analyze sentiment of text.

        Returns:
            dict with keys: 'neg', 'neu', 'pos', 'compound'
            compound is the overall score from -1 (negative) to 1 (positive)
        """
        return self.analyzer.polarity_scores(text)

    def get_score(self, text: str) -> float:
        """Get the compound sentiment score (-1 to 1)."""
        return self.analyze(text)["compound"]

    def analyze_batch(self, texts: list[str]) -> list[float]:
        """Analyze multiple texts and return compound scores."""
        return [self.get_score(text) for text in texts]

    def aggregate_scores(
        self, scores: list[float], weights: list[float] | None = None
    ) -> float:
        """
        Aggregate multiple sentiment scores into one.

        Args:
            scores: List of sentiment scores
            weights: Optional weights for each score (e.g., based on engagement)

        Returns:
            Weighted average score
        """
        if not scores:
            return 0.0

        if weights is None:
            return sum(scores) / len(scores)

        if len(weights) != len(scores):
            raise ValueError("Weights must match scores length")

        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0

        return sum(s * w for s, w in zip(scores, weights)) / total_weight


# Singleton instance
sentiment_analyzer = CryptoSentimentAnalyzer()
