"""Tests for source feature extraction."""

import numpy as np
import pytest

from crypto_sentiment_crawler.bayesian.feature_extraction import (
    SourceFeatureExtractor,
)
from crypto_sentiment_crawler.bayesian.gp_model import SourceFeatures


class TestGetSourceType:
    def test_reddit_is_social(self):
        assert SourceFeatureExtractor.get_source_type("reddit_bitcoin") == "social"

    def test_4chan_is_forum(self):
        assert SourceFeatureExtractor.get_source_type("4chan_biz") == "forum"

    def test_coindesk_is_news(self):
        assert SourceFeatureExtractor.get_source_type("coindesk_main") == "news"

    def test_google_trends_is_search(self):
        assert SourceFeatureExtractor.get_source_type("google_trends_btc") == "search"

    def test_unknown_defaults_to_social(self):
        assert SourceFeatureExtractor.get_source_type("some_random_source") == "social"


class TestStandardizeFeatures:
    def test_standardized_mean_zero(self):
        """After standardization, features should have mean ~0."""
        features = {
            f"source_{i}": SourceFeatures(
                source=f"source_{i}",
                features=np.random.randn(7) * 3 + 5,
                source_type="social",
            )
            for i in range(20)
        }

        extractor = SourceFeatureExtractor()
        standardized = extractor.standardize_features(features)

        X = np.array([f.features for f in standardized.values()])
        np.testing.assert_allclose(X.mean(axis=0), 0.0, atol=1e-10)

    def test_standardized_std_one(self):
        """After standardization, features should have std ~1."""
        rng = np.random.RandomState(42)
        features = {
            f"source_{i}": SourceFeatures(
                source=f"source_{i}",
                features=rng.randn(7) * 3 + 5,
                source_type="social",
            )
            for i in range(20)
        }

        extractor = SourceFeatureExtractor()
        standardized = extractor.standardize_features(features)

        X = np.array([f.features for f in standardized.values()])
        np.testing.assert_allclose(X.std(axis=0), 1.0, atol=1e-10)

    def test_scaler_params_stored(self):
        """Scaler params should be stored after standardization."""
        features = {
            f"source_{i}": SourceFeatures(
                source=f"source_{i}",
                features=np.random.randn(7),
                source_type="social",
            )
            for i in range(10)
        }

        extractor = SourceFeatureExtractor()
        extractor.standardize_features(features)

        assert extractor.scaler_params is not None
        assert "mean" in extractor.scaler_params
        assert "std" in extractor.scaler_params
        assert len(extractor.scaler_params["mean"]) == 7
        assert len(extractor.scaler_params["std"]) == 7

    def test_feature_dimensions(self):
        """Each feature vector should be 7D."""
        features = {
            "source_0": SourceFeatures(
                source="source_0",
                features=np.ones(7),
                source_type="social",
            )
        }

        extractor = SourceFeatureExtractor()
        standardized = extractor.standardize_features(features)

        for sf in standardized.values():
            assert sf.features.shape == (7,)

    def test_empty_features(self):
        """Empty input should return empty output."""
        extractor = SourceFeatureExtractor()
        result = extractor.standardize_features({})
        assert result == {}

    def test_preserves_source_type(self):
        """Standardization should preserve source_type."""
        features = {
            "reddit_btc": SourceFeatures(
                source="reddit_btc",
                features=np.ones(7),
                source_type="social",
            ),
            "coindesk": SourceFeatures(
                source="coindesk",
                features=np.zeros(7),
                source_type="news",
            ),
        }

        extractor = SourceFeatureExtractor()
        standardized = extractor.standardize_features(features)

        assert standardized["reddit_btc"].source_type == "social"
        assert standardized["coindesk"].source_type == "news"
