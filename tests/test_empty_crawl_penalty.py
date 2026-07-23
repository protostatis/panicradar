"""Tests for empty crawl penalty and cooldown mechanism.

Covers:
- SourceBelief.record_empty_crawl() penalty + tracking
- Cooldown filtering in CrawlBandit.select_source()
- Recovery (counter reset) after successful crawl
- Serialization round-trip of new fields
- Deadlock prevention when all sources are on cooldown
"""

import numpy as np
import pytest

from crypto_sentiment_crawler.bayesian.beliefs import SourceBelief, SourceBeliefStore
from crypto_sentiment_crawler.bayesian.bandit import CrawlBandit


# ── SourceBelief.record_empty_crawl ──────────────────────────────────────────


class TestRecordEmptyCrawl:
    def test_increments_consecutive_counter(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        assert belief.consecutive_empty_crawls == 0

        belief.record_empty_crawl()
        assert belief.consecutive_empty_crawls == 1

        belief.record_empty_crawl()
        assert belief.consecutive_empty_crawls == 2

    def test_applies_beta_penalty(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        original_beta = belief.beta

        belief.record_empty_crawl(penalty=0.3)
        assert belief.beta == pytest.approx(original_beta + 0.3)

    def test_mean_decreases_with_penalty(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        original_mean = belief.mean

        belief.record_empty_crawl(penalty=0.3)
        assert belief.mean < original_mean

    def test_alpha_unchanged(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        original_alpha = belief.alpha

        belief.record_empty_crawl()
        assert belief.alpha == original_alpha

    def test_custom_penalty(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        belief.record_empty_crawl(penalty=1.0)
        assert belief.beta == pytest.approx(4.0)

    def test_updates_last_updated(self):
        belief = SourceBelief(source="reddit_test")
        original_ts = belief.last_updated

        # Tiny sleep not needed — just check it's set
        belief.record_empty_crawl()
        assert belief.last_updated >= original_ts


# ── Counter reset on real update ─────────────────────────────────────────────


class TestCounterReset:
    def test_update_resets_consecutive_counter(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)

        # Simulate 5 empty crawls
        for _ in range(5):
            belief.record_empty_crawl()
        assert belief.consecutive_empty_crawls == 5

        # Real outcome resets counter
        belief.update(was_informative=True)
        assert belief.consecutive_empty_crawls == 0

    def test_update_with_utility_resets_counter(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        for _ in range(3):
            belief.record_empty_crawl()

        belief.update_with_utility(0.8)
        assert belief.consecutive_empty_crawls == 0

    def test_negative_outcome_also_resets(self):
        """Even a bad crawl is better than empty — should still reset."""
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        for _ in range(3):
            belief.record_empty_crawl()

        belief.update(was_informative=False)
        assert belief.consecutive_empty_crawls == 0


# ── Serialization round-trip ─────────────────────────────────────────────────


class TestSerialization:
    def test_to_dict_includes_new_field(self):
        belief = SourceBelief(source="reddit_test", consecutive_empty_crawls=5)
        d = belief.to_dict()
        assert d["consecutive_empty_crawls"] == 5

    def test_from_dict_reads_new_field(self):
        d = {
            "source": "reddit_test",
            "alpha": 3.0,
            "beta": 7.0,
            "total_crawls": 10,
            "consecutive_empty_crawls": 4,
            "last_updated": "2025-01-01T00:00:00+00:00",
        }
        belief = SourceBelief.from_dict(d)
        assert belief.consecutive_empty_crawls == 4

    def test_from_dict_defaults_to_zero(self):
        """Backward compat: old state files won't have the field."""
        d = {
            "source": "reddit_test",
            "alpha": 3.0,
            "beta": 7.0,
            "total_crawls": 10,
            "last_updated": "2025-01-01T00:00:00+00:00",
        }
        belief = SourceBelief.from_dict(d)
        assert belief.consecutive_empty_crawls == 0

    def test_round_trip(self):
        belief = SourceBelief(source="reddit_test", alpha=5.0, beta=3.0)
        for _ in range(3):
            belief.record_empty_crawl()

        d = belief.to_dict()
        restored = SourceBelief.from_dict(d)

        assert restored.consecutive_empty_crawls == 3
        assert restored.alpha == belief.alpha
        assert restored.beta == pytest.approx(belief.beta)

    def test_store_round_trip(self):
        store = SourceBeliefStore()
        b = store.get("reddit_test")
        for _ in range(4):
            b.record_empty_crawl()

        serialized = store.to_dict()
        restored = SourceBeliefStore.from_dict(serialized)
        assert restored.get("reddit_test").consecutive_empty_crawls == 4


# ── CrawlBandit cooldown filtering ──────────────────────────────────────────


class TestBanditCooldown:
    def _make_store(self, sources_config: dict[str, int]) -> SourceBeliefStore:
        """Create a store with sources having specified empty crawl counts."""
        store = SourceBeliefStore()
        for name, empty_count in sources_config.items():
            belief = store.get(name)
            belief.alpha = 5.0
            belief.beta = 3.0
            belief.consecutive_empty_crawls = empty_count
        return store

    def test_cooldown_skips_sources(self):
        """Sources at or above cooldown threshold should be skipped."""
        store = self._make_store({
            "reddit_good": 0,      # Active
            "reddit_empty": 3,     # At threshold (default=3)
            "reddit_dead": 10,     # Way over
        })
        bandit = CrawlBandit(store, empty_crawl_cooldown=3)

        # Run many selections — reddit_empty and reddit_dead should never appear
        np.random.seed(42)
        selected = set()
        for _ in range(50):
            result = bandit.select_source(["reddit_good", "reddit_empty", "reddit_dead"])
            selected.add(result.source)

        assert "reddit_good" in selected
        assert "reddit_empty" not in selected
        assert "reddit_dead" not in selected

    def test_below_threshold_still_eligible(self):
        """Sources with fewer empties than threshold should still be selected."""
        store = self._make_store({
            "reddit_a": 1,
            "reddit_b": 2,
        })
        bandit = CrawlBandit(store, empty_crawl_cooldown=3)

        np.random.seed(42)
        selected = set()
        for _ in range(50):
            result = bandit.select_source(["reddit_a", "reddit_b"])
            selected.add(result.source)

        # Both should be eligible
        assert len(selected) == 2

    def test_deadlock_prevention(self):
        """When ALL sources are filtered out, raises ValueError (no fallback)."""
        store = self._make_store({
            "reddit_a": 5,
            "reddit_b": 10,
        })
        bandit = CrawlBandit(store, empty_crawl_cooldown=3)

        # Should raise — no fallback to all sources anymore
        with pytest.raises(ValueError, match="No eligible sources"):
            bandit.select_source(["reddit_a", "reddit_b"])

    def test_recovery_after_reset(self):
        """Source becomes eligible again after counter reset."""
        store = self._make_store({
            "reddit_a": 0,
            "reddit_cooldown": 5,
        })
        bandit = CrawlBandit(store, empty_crawl_cooldown=3)

        # Verify reddit_cooldown is excluded
        np.random.seed(42)
        for _ in range(20):
            result = bandit.select_source(["reddit_a", "reddit_cooldown"])
            assert result.source == "reddit_a"

        # Simulate successful crawl — reset counter
        store.get("reddit_cooldown").consecutive_empty_crawls = 0

        # Now both should be eligible
        selected = set()
        for _ in range(50):
            result = bandit.select_source(["reddit_a", "reddit_cooldown"])
            selected.add(result.source)

        assert "reddit_cooldown" in selected


# ── Gradual decay test ───────────────────────────────────────────────────────


class TestGradualDecay:
    def test_repeated_empty_crawls_decay_mean(self):
        """Mean should gradually decrease with repeated empty crawls."""
        belief = SourceBelief(source="reddit_ripple", alpha=10.0, beta=5.0)
        means = [belief.mean]

        for _ in range(20):
            belief.record_empty_crawl(penalty=0.3)
            means.append(belief.mean)

        # Should be monotonically decreasing
        for i in range(1, len(means)):
            assert means[i] < means[i - 1], f"Mean didn't decrease at step {i}"

        # After 20 empty crawls, mean should be significantly lower
        assert means[-1] < means[0] * 0.75

    def test_penalty_bounded(self):
        """Mean should stay above 0 even with extreme penalties."""
        belief = SourceBelief(source="reddit_test", alpha=2.0, beta=1.0)

        for _ in range(100):
            belief.record_empty_crawl(penalty=0.3)

        assert belief.mean > 0
        assert belief.mean < 0.1  # Should be very low but positive
