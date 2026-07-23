"""Tests for GPBandit."""

import json
import numpy as np
import pytest

from crypto_sentiment_crawler.bayesian.bandit import GPBandit, SelectionResult
from crypto_sentiment_crawler.bayesian.beliefs import SourceBelief, SourceBeliefStore
from crypto_sentiment_crawler.bayesian.gp_model import GPSourceModel, SourceFeatures


def _make_belief_store(n: int = 10, total_crawls: int = 20) -> SourceBeliefStore:
    """Create a belief store with n sources."""
    store = SourceBeliefStore()
    for i in range(n):
        belief = SourceBelief(
            source=f"source_{i}",
            alpha=5.0,
            beta=5.0,
            total_crawls=total_crawls,
        )
        store.beliefs[f"source_{i}"] = belief
    return store


def _make_features(n: int = 10) -> dict[str, SourceFeatures]:
    """Create standardized features for n sources."""
    rng = np.random.RandomState(42)
    features = {}
    for i in range(n):
        features[f"source_{i}"] = SourceFeatures(
            source=f"source_{i}",
            features=rng.randn(7),
            source_type="social",
        )
    return features


class TestGPBanditSelection:
    def test_gp_eligible_sources_use_correlated_samples(self):
        """Sources with enough crawls should use GP correlated samples."""
        store = _make_belief_store(10, total_crawls=20)
        features = _make_features(10)

        bandit = GPBandit(store)
        success = bandit.update_gp(features)
        assert success
        assert bandit.is_gp_active

        result = bandit.select_source()
        assert isinstance(result, SelectionResult)
        assert result.source.startswith("source_")

        # Check that GP was used (logged in history)
        last_entry = bandit.selection_history[-1]
        assert last_entry["gp_active"] is True
        assert last_entry["gp_sources_count"] == 10

    def test_cold_start_uses_independent_beta(self):
        """Sources with < MIN_OBSERVATIONS should use independent Beta."""
        store = SourceBeliefStore()
        # 5 established sources
        for i in range(5):
            store.beliefs[f"gp_{i}"] = SourceBelief(
                source=f"gp_{i}", alpha=10, beta=5, total_crawls=20
            )
        # 5 cold-start sources
        for i in range(5):
            store.beliefs[f"cold_{i}"] = SourceBelief(
                source=f"cold_{i}", alpha=1.5, beta=1.5, total_crawls=3
            )

        rng = np.random.RandomState(42)
        features = {}
        for i in range(5):
            features[f"gp_{i}"] = SourceFeatures(
                source=f"gp_{i}", features=rng.randn(7), source_type="social"
            )
        for i in range(5):
            features[f"cold_{i}"] = SourceFeatures(
                source=f"cold_{i}", features=rng.randn(7), source_type="social"
            )

        bandit = GPBandit(store)
        bandit.update_gp(features)

        # Select many times and verify cold_start sources can still be selected
        all_sources = list(store.beliefs.keys())
        selected = set()
        for _ in range(100):
            result = bandit.select_source(all_sources)
            selected.add(result.source)

        # Both GP and cold sources should appear
        gp_selected = [s for s in selected if s.startswith("gp_")]
        cold_selected = [s for s in selected if s.startswith("cold_")]
        assert len(gp_selected) > 0
        assert len(cold_selected) > 0

    def test_cooldown_still_works(self):
        """Sources with too many empty crawls should be filtered."""
        store = _make_belief_store(5, total_crawls=20)
        features = _make_features(5)

        # Put 4 sources on cooldown
        for i in range(4):
            store.beliefs[f"source_{i}"].consecutive_empty_crawls = 10

        bandit = GPBandit(store, empty_crawl_cooldown=3)
        bandit.update_gp(features)

        # Only source_4 should be selected (others on cooldown)
        result = bandit.select_source()
        assert result.source == "source_4"

    def test_cooldown_deadlock_prevention(self):
        """If all sources are filtered out, raises ValueError (no fallback)."""
        store = _make_belief_store(5, total_crawls=20)
        features = _make_features(5)

        for i in range(5):
            store.beliefs[f"source_{i}"].consecutive_empty_crawls = 10

        bandit = GPBandit(store, empty_crawl_cooldown=3)
        bandit.update_gp(features)

        # Should raise — no fallback to all sources
        with pytest.raises(ValueError, match="No eligible sources"):
            bandit.select_source()


class TestGPBanditFallback:
    def test_too_few_gp_sources(self):
        """With < MIN_GP_ELIGIBLE GP-eligible sources, GP should be inactive."""
        store = SourceBeliefStore()
        for i in range(3):  # Only 3 sources
            store.beliefs[f"source_{i}"] = SourceBelief(
                source=f"source_{i}", alpha=5, beta=5, total_crawls=20
            )

        rng = np.random.RandomState(42)
        features = {
            f"source_{i}": SourceFeatures(
                source=f"source_{i}", features=rng.randn(7), source_type="social"
            )
            for i in range(3)
        }

        bandit = GPBandit(store)
        success = bandit.update_gp(features)
        assert not success
        assert not bandit.is_gp_active

        # Should still work via independent Beta fallback
        result = bandit.select_source()
        assert isinstance(result, SelectionResult)

    def test_no_features_falls_back(self):
        """Without features, selection should fall back to independent Beta."""
        store = _make_belief_store(10, total_crawls=20)
        bandit = GPBandit(store)
        # Don't call update_gp - no features

        result = bandit.select_source()
        assert isinstance(result, SelectionResult)
        assert not bandit.is_gp_active


class TestBackwardCompatibility:
    def test_state_without_gp_loads(self):
        """Old orchestrator state without gp_state should load fine."""
        from crypto_sentiment_crawler.orchestrator import OrchestratorState

        old_state_data = {
            "beliefs": {"source_a": {"source": "source_a", "alpha": 5, "beta": 3}},
            "baseline_informativeness": 0.6,
            "total_crawls": 100,
        }

        state = OrchestratorState.from_dict(old_state_data)
        assert state.gp_hyperparameters is None
        assert state.gp_scaler_params is None
        assert state.last_gp_fit is None
        assert state.total_crawls == 100

    def test_state_with_gp_loads(self):
        """State with gp_state key should load GP params."""
        from crypto_sentiment_crawler.orchestrator import OrchestratorState

        state_data = {
            "beliefs": {},
            "total_crawls": 200,
            "gp_state": {
                "hyperparameters": {
                    "length_scale": 2.0,
                    "signal_variance": 0.5,
                    "category_variance": 0.3,
                    "noise_variance": 0.1,
                },
                "scaler_params": {"mean": [0.0] * 7, "std": [1.0] * 7},
                "last_gp_fit": "2026-02-01T00:00:00+00:00",
            },
        }

        state = OrchestratorState.from_dict(state_data)
        assert state.gp_hyperparameters is not None
        assert state.gp_hyperparameters["length_scale"] == 2.0
        assert state.gp_scaler_params is not None
        assert state.last_gp_fit == "2026-02-01T00:00:00+00:00"

    def test_state_roundtrip_with_gp(self):
        """to_dict -> from_dict should preserve GP state."""
        from crypto_sentiment_crawler.orchestrator import OrchestratorState

        state = OrchestratorState(
            beliefs={"a": {"alpha": 1, "beta": 1}},
            total_crawls=50,
            gp_hyperparameters={
                "length_scale": 1.5,
                "signal_variance": 0.8,
                "category_variance": 0.4,
                "noise_variance": 0.15,
            },
            gp_scaler_params={"mean": [0.1] * 7, "std": [0.9] * 7},
            last_gp_fit="2026-02-05T12:00:00+00:00",
        )

        data = state.to_dict()
        restored = OrchestratorState.from_dict(data)

        assert restored.gp_hyperparameters == state.gp_hyperparameters
        assert restored.gp_scaler_params == state.gp_scaler_params
        assert restored.last_gp_fit == state.last_gp_fit

    def test_state_without_gp_serializes_clean(self):
        """State without GP should not include gp_state key."""
        from crypto_sentiment_crawler.orchestrator import OrchestratorState

        state = OrchestratorState(total_crawls=10)
        data = state.to_dict()
        assert "gp_state" not in data
