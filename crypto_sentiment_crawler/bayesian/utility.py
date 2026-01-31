"""Utility scoring: accuracy and novelty measurement."""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class UtilityScorer:
    """
    Compute utility of crawled content.

    Utility = 0.7 × accuracy + 0.3 × novelty

    - accuracy: Did sentiment correctly predict price direction?
    - novelty: How different is this content from recent content?
    """

    def __init__(
        self,
        accuracy_weight: float = 0.7,
        novelty_weight: float = 0.3,
        max_recent_docs: int = 100,
    ):
        self.accuracy_weight = accuracy_weight
        self.novelty_weight = novelty_weight
        self.max_recent_docs = max_recent_docs

        # TF-IDF vectorizer for novelty computation
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
        )

        # Recent documents for novelty comparison
        self.recent_docs: list[str] = []
        self.recent_vectors = None

    def compute_accuracy(
        self,
        sentiment_score: float,
        price_before: float,
        price_after: float,
    ) -> float:
        """
        Compute accuracy: did sentiment predict price direction?

        Args:
            sentiment_score: Sentiment from content (-1 to 1)
            price_before: Price at time of crawl
            price_after: Price after lag period

        Returns:
            1.0 if prediction correct, 0.0 otherwise
        """
        if price_before == 0:
            return 0.5  # Can't compute

        price_change = (price_after - price_before) / price_before

        # Sentiment and price should have same sign for accuracy
        sentiment_direction = np.sign(sentiment_score)
        price_direction = np.sign(price_change)

        # Handle neutral cases
        if sentiment_direction == 0 or price_direction == 0:
            return 0.5  # Neutral = half credit

        return 1.0 if sentiment_direction == price_direction else 0.0

    def compute_novelty(self, content: str) -> float:
        """
        Compute novelty: how different from recent content?

        Uses TF-IDF cosine similarity. Novelty = 1 - max_similarity.

        Args:
            content: Text content to evaluate

        Returns:
            Novelty score between 0 (duplicate) and 1 (completely new)
        """
        if not content or not content.strip():
            return 0.0

        if not self.recent_docs:
            # First document is fully novel
            return 1.0

        try:
            # Fit vectorizer on all docs including new one
            all_docs = self.recent_docs + [content]
            vectors = self.vectorizer.fit_transform(all_docs)

            # New content is last vector
            new_vector = vectors[-1]
            recent_vectors = vectors[:-1]

            # Compute similarity to all recent docs
            similarities = cosine_similarity(new_vector, recent_vectors).flatten()

            # Novelty = 1 - max similarity
            max_sim = similarities.max() if len(similarities) > 0 else 0.0
            novelty = 1.0 - max_sim

            return max(0.0, min(1.0, novelty))

        except Exception:
            return 0.5  # Default to neutral on error

    def add_to_recent(self, content: str) -> None:
        """Add content to recent documents for future novelty comparison."""
        if content and content.strip():
            self.recent_docs.append(content)

            # Keep only most recent
            if len(self.recent_docs) > self.max_recent_docs:
                self.recent_docs = self.recent_docs[-self.max_recent_docs:]

    def compute_utility(
        self,
        content: str,
        sentiment_score: float,
        price_before: float,
        price_after: float,
        add_to_recent: bool = True,
    ) -> dict:
        """
        Compute full utility score.

        Args:
            content: Text content
            sentiment_score: Sentiment score (-1 to 1)
            price_before: Price at crawl time
            price_after: Price after lag
            add_to_recent: Whether to add to recent docs

        Returns:
            Dictionary with accuracy, novelty, and combined utility
        """
        accuracy = self.compute_accuracy(sentiment_score, price_before, price_after)
        novelty = self.compute_novelty(content)

        utility = (
            self.accuracy_weight * accuracy +
            self.novelty_weight * novelty
        )

        if add_to_recent:
            self.add_to_recent(content)

        return {
            "accuracy": accuracy,
            "novelty": novelty,
            "utility": utility,
            "is_informative": utility > 0.5,
        }

    def compute_novelty_only(self, content: str, add_to_recent: bool = True) -> float:
        """
        Compute just novelty (before price outcome is known).

        Useful for immediate feedback on crawl value.
        """
        novelty = self.compute_novelty(content)

        if add_to_recent:
            self.add_to_recent(content)

        return novelty

    def clear_recent(self) -> None:
        """Clear recent documents (e.g., for new session)."""
        self.recent_docs = []
        self.recent_vectors = None


class BatchUtilityScorer:
    """Score utility for batches of content efficiently."""

    def __init__(self, accuracy_weight: float = 0.7, novelty_weight: float = 0.3):
        self.accuracy_weight = accuracy_weight
        self.novelty_weight = novelty_weight
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
        )

    def compute_batch_novelty(self, contents: list[str]) -> list[float]:
        """
        Compute novelty for a batch of contents.

        Each document's novelty is relative to documents that came before it.
        """
        if not contents:
            return []

        novelties = [1.0]  # First doc is fully novel

        if len(contents) == 1:
            return novelties

        for i in range(1, len(contents)):
            prior_docs = contents[:i]
            current_doc = contents[i]

            try:
                all_docs = prior_docs + [current_doc]
                vectors = self.vectorizer.fit_transform(all_docs)

                current_vector = vectors[-1]
                prior_vectors = vectors[:-1]

                similarities = cosine_similarity(current_vector, prior_vectors).flatten()
                max_sim = similarities.max() if len(similarities) > 0 else 0.0
                novelty = 1.0 - max_sim

                novelties.append(max(0.0, min(1.0, novelty)))

            except Exception:
                novelties.append(0.5)

        return novelties
