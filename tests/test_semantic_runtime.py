"""Tests for fail-closed and batched semantic scoring."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from crypto_sentiment_crawler.processing.semantic_sentiment import (
    SemanticSentimentAnalyzer,
)
from crypto_sentiment_crawler.processing.user_sentiment import UserSentimentScorer


class DeterministicProvider:
    """Small deterministic provider used without downloading a model."""

    dim = 4

    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        values = np.array(
            [
                len(text) + 1,
                sum(ord(char) for char in text) % 97 + 1,
                text.lower().count("a") + 1,
                text.lower().count("e") + 1,
            ],
            dtype=np.float32,
        )
        return values / np.linalg.norm(values)

    def encode(self, texts: list[str] | str, normalize: bool = True) -> np.ndarray:
        values = [texts] if isinstance(texts, str) else texts
        self.batch_calls.append(list(values))
        return np.stack([self._vector(text) for text in values])

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        self.single_calls.append(text)
        return self._vector(text)


def test_configured_openrouter_never_falls_back_to_local() -> None:
    configured = SimpleNamespace(
        embedding_backend="openrouter",
        embedding_model="hosted/model",
        openrouter_api_key="",
    )

    with (
        patch("crypto_sentiment_crawler.config.settings", configured),
        patch(
            "crypto_sentiment_crawler.processing.embedding_providers."
            "OpenRouterEmbeddingProvider",
            side_effect=RuntimeError("missing key"),
        ),
        patch(
            "crypto_sentiment_crawler.processing.embedding_providers."
            "LocalSentenceTransformerProvider"
        ) as local_provider,
        pytest.raises(RuntimeError, match="missing key"),
    ):
        SemanticSentimentAnalyzer()

    local_provider.assert_not_called()


def test_unknown_configured_backend_is_rejected() -> None:
    configured = SimpleNamespace(
        embedding_backend="openruter",
        embedding_model="hosted/model",
        openrouter_api_key="",
    )

    with (
        patch("crypto_sentiment_crawler.config.settings", configured),
        patch(
            "crypto_sentiment_crawler.processing.embedding_providers."
            "LocalSentenceTransformerProvider"
        ) as local_provider,
        pytest.raises(ValueError, match="Unknown embedding backend"),
    ):
        SemanticSentimentAnalyzer()

    local_provider.assert_not_called()


@pytest.mark.parametrize("method", ["centroid", "top_k", "asymmetric"])
def test_batch_analysis_matches_individual_scoring(method: str) -> None:
    provider = DeterministicProvider()
    analyzer = SemanticSentimentAnalyzer(provider=provider)
    texts = ["Bitcoin looks strong", "The market may crash"]

    provider.batch_calls.clear()
    individual = [analyzer.analyze(text, method=method) for text in texts]
    provider.batch_calls.clear()
    batched = analyzer.analyze_batch(texts, method=method)

    assert batched == individual
    assert provider.batch_calls == [texts]


def test_user_scorer_batches_title_and_segments() -> None:
    analyzer = MagicMock()
    analyzer.analyze_batch.side_effect = lambda texts, method: [
        {"score": (index + 1) / 10} for index, _ in enumerate(texts)
    ]

    with patch(
        "crypto_sentiment_crawler.processing.semantic_sentiment."
        "SemanticSentimentAnalyzer",
        return_value=analyzer,
    ):
        scorer = UserSentimentScorer()

    raw_data = {
        "author": "alice",
        "title": "Bitcoin market outlook today",
        "content": "The market has strong momentum today.",
        "metadata": {
            "comments": [
                {"author": f"user-{index}", "body": f"Distinct human comment number {index}."}
                for index in range(4)
            ]
        },
    }
    score = scorer.score_post(
        raw_data,
        raw_id=1,
        timestamp="2026-08-14T12:00:00+00:00",
        source="reddit_bitcoin",
    )

    assert score is not None
    analyzer.analyze.assert_not_called()
    analyzer.analyze_batch.assert_called_once()
    texts, = analyzer.analyze_batch.call_args.args
    assert texts[0] == raw_data["title"]
    assert len(texts) == 6
    assert analyzer.analyze_batch.call_args.kwargs == {"method": "asymmetric"}
