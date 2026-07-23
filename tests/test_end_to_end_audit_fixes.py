"""End-to-end integration tests for Phase 1 audit fixes.

Tests cover:
1. Source-hour aggregation + neutral deadband in compute_source_accuracy
2. Fail-closed contrarian classification with credible intervals
3. Deterministic rebuild in update_belief_priors
4. Confidence-aware weights via compute_weight_from_belief
5. SourceBelief updater fields roundtrip (to_dict / from_dict)
6. _get_eligible_sources filtering by status / probe time
7. Empty inputs return empty outputs
8. Full pipeline smoke test (DB → accuracy → beliefs)
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from crypto_sentiment_crawler.analysis.belief_updater import (
    compute_source_accuracy,
    update_belief_priors,
)
from crypto_sentiment_crawler.analysis.source_weights import (
    compute_weight_from_belief,
)
from crypto_sentiment_crawler.bayesian.bandit import CrawlBandit
from crypto_sentiment_crawler.bayesian.beliefs import SourceBelief, SourceBeliefStore
from crypto_sentiment_crawler.storage.db import Database


# ====================================================================
#  Fixtures
# ====================================================================


@pytest.fixture
async def tmp_db():
    """Create a temporary SQLite database and clean it up after the test."""
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test.db"
    db = Database(db_path)
    await db.connect()
    yield db
    await db.close()
    shutil.rmtree(tmp_dir)


# ====================================================================
#  Test helpers
# ====================================================================


async def _insert_user_profile(db, user_id: int, username: str, source: str) -> None:
    await db.conn.execute(
        "INSERT INTO user_profiles (user_id, username, source) VALUES (?, ?, ?)",
        (user_id, username, source),
    )


async def _insert_sentiment_score(
    db, score_id: int, user_id: int, timestamp: str, final_score: float
) -> None:
    await db.conn.execute(
        "INSERT INTO user_sentiment_scores (id, user_id, timestamp, final_score) "
        "VALUES (?, ?, ?, ?)",
        (score_id, user_id, timestamp, final_score),
    )


async def _insert_price(db, timestamp: str, price_usd: float) -> None:
    await db.conn.execute(
        "INSERT INTO price_data (timestamp, coin, price_usd) VALUES (?, 'BTC', ?)",
        (timestamp, price_usd),
    )


# ====================================================================
#  Test 1: Source-hour aggregation + neutral deadband
# ====================================================================


class TestSourceHourAggregation:
    """compute_source_accuracy aggregates by (source, hour) and treats
    near-zero scores as abstentions."""

    BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)

    async def _populate(self, db) -> None:
        """Insert 3 sources with multiple posts per hour and price data."""

        # Prices at hours 0..7 so that hour+4 comparisons work
        prices: list[float] = [50000, 50100, 49900, 50200, 51000, 49500, 49000, 50500]
        for i, p in enumerate(prices):
            await _insert_price(db, (self.BASE + timedelta(hours=i)).isoformat(), p)

        # Price changes from hour h to h+4:
        #   0→4: +2.0%   (positive)
        #   1→5: -1.2%   (negative)
        #   2→6: -1.8%   (negative)
        #   3→7: +0.6%   (positive)

        # ── source_a: 2 non-neutral source-hours ─────────────────
        await _insert_user_profile(db, 1, "a1", "source_a")
        await _insert_user_profile(db, 2, "a2", "source_a")
        await _insert_user_profile(db, 3, "a3", "source_a")
        await _insert_sentiment_score(db, 1, 1, (self.BASE + timedelta(hours=0)).isoformat(), 0.30)
        await _insert_sentiment_score(db, 2, 2, (self.BASE + timedelta(hours=0)).isoformat(), 0.50)
        await _insert_sentiment_score(db, 3, 3, (self.BASE + timedelta(hours=1)).isoformat(), -0.20)
        await _insert_sentiment_score(db, 4, 1, (self.BASE + timedelta(hours=1)).isoformat(), -0.40)
        await _insert_sentiment_score(db, 5, 2, (self.BASE + timedelta(hours=1)).isoformat(), -0.30)

        # ── source_b: 1 non-neutral + 1 neutral source-hour ──────
        await _insert_user_profile(db, 4, "b1", "source_b")
        await _insert_user_profile(db, 5, "b2", "source_b")
        await _insert_sentiment_score(db, 6, 4, (self.BASE + timedelta(hours=0)).isoformat(), 0.80)
        await _insert_sentiment_score(db, 7, 4, (self.BASE + timedelta(hours=2)).isoformat(), 0.04)
        await _insert_sentiment_score(db, 8, 5, (self.BASE + timedelta(hours=2)).isoformat(), 0.02)

        # ── source_c: all neutral (one source-hour) ──────────────
        await _insert_user_profile(db, 6, "c1", "source_c")
        await _insert_user_profile(db, 7, "c2", "source_c")
        await _insert_sentiment_score(db, 9, 6, (self.BASE + timedelta(hours=1)).isoformat(), 0.03)
        await _insert_sentiment_score(db, 10, 7, (self.BASE + timedelta(hours=1)).isoformat(), 0.01)

        await db.conn.commit()

    async def test_aggregates_by_source_hour(self, tmp_db, monkeypatch):
        """Multiple posts in the same source+hour produce ONE observation."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.analysis.belief_updater.MIN_SAMPLES", 0
        )
        await self._populate(tmp_db)
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)

        # source_a: 5 posts → 2 aggregated source-hours
        assert "source_a" in results, "source_a should appear in results"
        d = results["source_a"]
        assert d["total"] == 2, f"Expected 2 source-hours, got {d['total']}"
        # hour 0: mean=0.40 (pos) × +2.0% → correct
        # hour 1: mean=-0.30 (neg) × -1.2% → correct
        assert d["correct"] == 2
        assert d["incorrect"] == 0
        assert d["abstained"] == 0

    async def test_neutral_deadband_excluded(self, tmp_db, monkeypatch):
        """Scores with |mean| < 0.05 are abstentions, excluded from accuracy."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.analysis.belief_updater.MIN_SAMPLES", 0
        )
        await self._populate(tmp_db)
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)

        # source_b: hour 0 (score 0.80, non-neutral, correct),
        #           hour 2 (mean=0.03, neutral → abstention)
        assert "source_b" in results
        d = results["source_b"]
        assert d["total"] == 2
        assert d["abstained"] == 1, f"Expected 1 abstention, got {d['abstained']}"
        assert d["correct"] == 1
        assert d["incorrect"] == 0
        assert d["effective_n"] == 1  # only non-abstained count

        # source_c: hour 1 (mean=0.02, neutral) → all abstained
        assert "source_c" in results
        d = results["source_c"]
        assert d["total"] == 1
        assert d["abstained"] == 1
        assert d["effective_n"] == 0
        assert d["accuracy"] == 0.5  # fallback when no non-abstained obs


# ====================================================================
#  Test 2: Fail-closed contrarian classification
# ====================================================================


class TestFailClosedContrarian:
    """Classification uses effective_n threshold and credible intervals."""

    BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)
    N_HOURS = 250  # enough for contrarian (200) + momentum (200) + insufficient (50)

    async def _populate(self, db) -> None:
        """Create 3 sources with predetermined correct/incorrect counts.

        Price directions are deterministic (130 up, 70 down for 200 periods).
        contrarian_src always predicts negative → correct when price drops.
        momentum_src always predicts positive → correct when price rises.
        insufficient_src has only 50 observations.
        """
        # ── Build price directions ───────────────────────────────
        rng = np.random.RandomState(42)
        directions = [1] * 130 + [-1] * 70          # 200 periods
        rng.shuffle(directions)
        extra = [1] * 30 + [-1] * 20                 # 50 more periods
        rng.shuffle(extra)
        all_dirs = directions + extra                # length 250

        # Generate prices deterministically from directions.
        # price[h+4] = price[h] * 1.01  (up)   or  * 0.99 (down)
        prices: list[float] = [50000.0, 50100.0, 49900.0, 50200.0]
        for d in all_dirs:
            prices.append(prices[-4] * (1.01 if d == 1 else 0.99))

        # Insert all price records (hours 0 .. N_HOURS+3, 4 initial + 250 directional)
        for i in range(self.N_HOURS + 4):
            ts = self.BASE + timedelta(hours=i)
            await _insert_price(db, ts.isoformat(), prices[i])
        await db.conn.commit()

        # ── Insert sentiment data ────────────────────────────────
        sid = 1
        uid = 1

        # contrarian_src (200 obs): always predicts negative
        await _insert_user_profile(db, uid, "con_user", "contrarian_src")
        con_uid = uid
        uid += 1
        for i in range(200):
            await _insert_sentiment_score(db, sid, con_uid,
                                          (self.BASE + timedelta(hours=i)).isoformat(), -0.30)
            sid += 1

        # momentum_src (200 obs): always predicts positive
        await _insert_user_profile(db, uid, "mom_user", "momentum_src")
        mom_uid = uid
        uid += 1
        for i in range(200):
            await _insert_sentiment_score(db, sid, mom_uid,
                                          (self.BASE + timedelta(hours=i)).isoformat(), 0.30)
            sid += 1

        # insufficient_src (50 obs): always predicts negative
        await _insert_user_profile(db, uid, "insuf_user", "insufficient_src")
        ins_uid = uid
        uid += 1
        for i in range(200, 250):
            await _insert_sentiment_score(db, sid, ins_uid,
                                          (self.BASE + timedelta(hours=i)).isoformat(), -0.25)
            sid += 1

        await db.conn.commit()

    async def test_contrarian_classification(self, tmp_db):
        """Source with 200 obs at ~35% accuracy → contrarian, ci_upper < 0.50."""
        await self._populate(tmp_db)
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)

        assert "contrarian_src" in results
        d = results["contrarian_src"]
        assert d["effective_n"] == 200
        # 70 downs (correct when predicting neg) out of 200
        assert d["correct"] == 70
        assert d["incorrect"] == 130
        assert d["is_contrarian"] is True
        assert d["type_label"] == "contrarian"
        assert d["credible_interval_upper"] < 0.50, (
            f"ci_upper={d['credible_interval_upper']} should be < 0.50 for contrarian"
        )

        # Cross-check with scipy directly
        expected_upper = float(stats.beta.ppf(0.975, 1 + 70, 1 + 130))
        assert d["credible_interval_upper"] == pytest.approx(expected_upper, rel=1e-4)

    async def test_insufficient_data(self, tmp_db):
        """Source with < 100 observations → insufficient_data, weight 0.01."""
        await self._populate(tmp_db)
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)

        assert "insufficient_src" in results
        d = results["insufficient_src"]
        assert d["effective_n"] == 50
        assert d["effective_n"] < 100
        assert d["is_contrarian"] is False
        assert d["type_label"] == "insufficient_data"

    async def test_momentum_classification(self, tmp_db):
        """Source with 200 obs at ~65% accuracy → momentum, ci_lower > 0.50."""
        await self._populate(tmp_db)
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)

        assert "momentum_src" in results
        d = results["momentum_src"]
        assert d["effective_n"] == 200
        # 130 ups (correct when predicting pos) out of 200
        assert d["correct"] == 130
        assert d["incorrect"] == 70
        assert d["is_contrarian"] is False
        assert d["type_label"] == "momentum"
        assert d["credible_interval_lower"] > 0.50, (
            f"ci_lower={d['credible_interval_lower']} should be > 0.50 for momentum"
        )

        # Cross-check with scipy
        expected_lower = float(stats.beta.ppf(0.025, 1 + 130, 1 + 70))
        assert d["credible_interval_lower"] == pytest.approx(expected_lower, rel=1e-4)


# ====================================================================
#  Test 3: Deterministic rebuild
# ====================================================================


class TestDeterministicRebuild:
    """update_belief_priors produces identical alpha/beta on repeated calls."""

    def test_identical_outputs(self):
        """Two calls with same data produce the same alpha and beta."""
        current_beliefs = {
            "src_a": {"source": "src_a", "alpha": 5.0, "beta": 5.0,
                       "total_crawls": 10},
            "src_b": {"source": "src_b", "alpha": 3.0, "beta": 1.0,
                       "total_crawls": 4},
        }
        source_accuracy = {
            "src_a": {
                "accuracy": 0.65, "correct": 30, "incorrect": 20,
                "abstained": 2, "total": 52, "correlation": 0.12,
                "coverage": 0.96, "is_contrarian": False,
                "type_label": "momentum",
                "credible_interval_lower": 0.55,
                "credible_interval_upper": 0.75,
                "effective_n": 50,
            },
            "src_b": {
                "accuracy": 0.35, "correct": 7, "incorrect": 13,
                "abstained": 5, "total": 25, "correlation": -0.08,
                "coverage": 0.80, "is_contrarian": False,
                "type_label": "insufficient_data",
                "credible_interval_lower": 0.20,
                "credible_interval_upper": 0.52,
                "effective_n": 20,
            },
        }

        first = update_belief_priors(current_beliefs, source_accuracy)
        second = update_belief_priors(current_beliefs, source_accuracy)

        # Alpha and beta must match exactly (deterministic from neutral prior)
        for src in ("src_a", "src_b"):
            assert first[src]["alpha"] == second[src]["alpha"], (
                f"{src} alpha differs between runs"
            )
            assert first[src]["beta"] == second[src]["beta"], (
                f"{src} beta differs between runs"
            )

    def test_rebuild_from_neutral_prior(self):
        """Alpha/beta are computed from neutral prior (1,1), ignoring previous."""
        prior = {"src": {"source": "src", "alpha": 999.0, "beta": 999.0,
                          "total_crawls": 1000}}
        acc = {
            "src": {
                "accuracy": 0.6, "correct": 5, "incorrect": 5,
                "abstained": 0, "total": 10, "correlation": 0.0,
                "coverage": 1.0, "is_contrarian": False,
                "type_label": "neutral",
                "credible_interval_lower": 0.30,
                "credible_interval_upper": 0.70,
                "effective_n": 10,
            },
        }
        result = update_belief_priors(prior, acc)
        # alpha = 1 + correct, beta = 1 + incorrect
        assert result["src"]["alpha"] == 6  # 1 + 5
        assert result["src"]["beta"] == 6   # 1 + 5
        assert result["src"]["alpha"] != 999.0  # not from prior


# ====================================================================
#  Test 4: Confidence-aware weights
# ====================================================================


class TestConfidenceAwareWeights:
    """compute_weight_from_belief respects type_label and credible intervals."""

    def test_insufficient_data_weight(self):
        """insufficient_data → weight 0.01 regardless of other fields."""
        belief = {
            "type_label": "insufficient_data",
            "accuracy": 0.80,
            "effective_n": 50,
            "credible_interval_lower": 0.60,
            "credible_interval_upper": 0.90,
        }
        weight, invert = compute_weight_from_belief(belief)
        assert weight == 0.01
        assert invert is False

    def test_uninitialized_weight(self):
        """uninitialized → weight 0.01."""
        belief = {
            "type_label": "uninitialized",
            "accuracy": None,
            "effective_n": 0,
        }
        weight, invert = compute_weight_from_belief(belief)
        assert weight == 0.01

    def test_momentum_uses_ci_lower_for_edge(self):
        """Momentum uses ci_lower as conservative accuracy estimate."""
        # ci_lower = 0.55 → conservative_accuracy = 0.55
        # distance = max(0, 0.55 - 0.5) = 0.05
        belief = {
            "type_label": "momentum",
            "is_contrarian": False,
            "accuracy": 0.65,
            "effective_n": 200,
            "credible_interval_lower": 0.55,
            "credible_interval_upper": 0.75,
        }
        weight, invert = compute_weight_from_belief(belief)
        assert weight > 0.01, "Momentum with ci_lower=0.55 should have weight > 0.01"
        assert invert is False

        # Verify the weight uses ci_lower distance, not accuracy distance
        # If it used accuracy (0.65), distance = 0.15, weight ~0.01+0.15*2*0.29 ≈ 0.097
        # If it uses ci_lower (0.55), distance = 0.05, weight ~0.01+0.05*2*0.29 ≈ 0.039
        accuracy_based_weight = 0.01 + (0.15 * 2 * min(1.0, 200 / 200) * 0.29)
        ci_lower_based_weight = 0.01 + (0.05 * 2 * min(1.0, 200 / 200) * 0.29)
        assert weight < accuracy_based_weight, (
            f"Weight {weight} should use ci_lower, not accuracy"
        )
        assert weight == pytest.approx(ci_lower_based_weight, rel=0.1)

    def test_contrarian_uses_one_minus_ci_upper(self):
        """Contrarian uses 1.0 - ci_upper as conservative accuracy."""
        # ci_upper = 0.45 → 1 - 0.45 = 0.55 conservative accuracy
        # distance = max(0, 0.55 - 0.5) = 0.05
        belief = {
            "type_label": "contrarian",
            "is_contrarian": True,
            "accuracy": 0.35,
            "effective_n": 200,
            "credible_interval_lower": 0.25,
            "credible_interval_upper": 0.45,
        }
        weight, invert = compute_weight_from_belief(belief)
        assert weight > 0.01, "Contrarian with edge should have weight > 0.01"
        assert invert is True

        # Verify weight uses 1 - ci_upper
        # 1 - ci_upper = 0.55, distance = 0.05
        expected_weight = 0.01 + (0.05 * 2 * min(1.0, 200 / 200) * 0.29)
        assert weight == pytest.approx(expected_weight, rel=0.1)

    def test_no_ci_fallback_to_accuracy(self):
        """Without credible intervals, fall back to point accuracy."""
        belief = {
            "type_label": "momentum",
            "is_contrarian": False,
            "accuracy": 0.65,
            "effective_n": 200,
            # No credible_interval keys
        }
        weight, invert = compute_weight_from_belief(belief)
        assert weight > 0.01


# ====================================================================
#  Test 5: SourceBelief updater fields roundtrip
# ====================================================================


class TestSourceBeliefUpdaterFieldsRoundtrip:
    """SourceBelief.to_dict() → from_dict() preserves all updater metadata."""

    def test_all_updater_fields_survive(self):
        """Set all updater fields, roundtrip, assert they survive."""
        belief = SourceBelief(
            source="reddit_crypto",
            alpha=10.0,
            beta=5.0,
            total_crawls=50,
            accuracy=0.72,
            correlation=0.31,
            is_contrarian=False,
            type_label="momentum",
            credible_interval_lower=0.61,
            credible_interval_upper=0.82,
            effective_n=120,
            coverage=0.93,
        )
        d = belief.to_dict()
        restored = SourceBelief.from_dict(d)

        assert restored.accuracy == 0.72
        assert restored.correlation == 0.31
        assert restored.is_contrarian is False
        assert restored.type_label == "momentum"
        assert restored.credible_interval_lower == 0.61
        assert restored.credible_interval_upper == 0.82
        assert restored.effective_n == 120
        assert restored.coverage == 0.93
        # Core fields preserved too
        assert restored.source == "reddit_crypto"
        assert restored.alpha == 10.0
        assert restored.beta == 5.0

    def test_contrarian_roundtrip(self):
        """Contrarian flags survive roundtrip."""
        belief = SourceBelief(
            source="4chan_biz",
            accuracy=0.32,
            is_contrarian=True,
            type_label="contrarian",
            credible_interval_lower=0.22,
            credible_interval_upper=0.42,
            effective_n=200,
            coverage=0.88,
        )
        restored = SourceBelief.from_dict(belief.to_dict())
        assert restored.is_contrarian is True
        assert restored.type_label == "contrarian"

    def test_none_fields_roundtrip(self):
        """Optional None fields survive as None."""
        belief = SourceBelief(
            source="test_src",
            accuracy=None,
            correlation=None,
            credible_interval_lower=None,
            credible_interval_upper=None,
            coverage=None,
        )
        restored = SourceBelief.from_dict(belief.to_dict())
        assert restored.accuracy is None
        assert restored.correlation is None
        assert restored.credible_interval_lower is None
        assert restored.credible_interval_upper is None
        assert restored.coverage is None

    def test_defaults_when_missing(self):
        """from_dict provides defaults for updater fields not in old data."""
        d = {
            "source": "old_src",
            "alpha": 5.0,
            "beta": 3.0,
            "total_crawls": 8,
            "last_updated": "2025-01-01T00:00:00+00:00",
        }
        restored = SourceBelief.from_dict(d)
        assert restored.accuracy is None
        assert restored.is_contrarian is False
        assert restored.type_label == "uninitialized"
        assert restored.effective_n == 0
        assert restored.coverage is None


# ====================================================================
#  Test 6: _get_eligible_sources filtering
# ====================================================================


class TestGetEligibleSources:
    """CrawlBandit._get_eligible_sources filters by status and probe time."""

    def _make_bandit(self, beliefs: dict[str, dict]) -> CrawlBandit:
        """Create a CrawlBandit with preset beliefs."""
        store = SourceBeliefStore()
        for name, kwargs in beliefs.items():
            b = store.get(name)
            for k, v in kwargs.items():
                setattr(b, k, v)
        return CrawlBandit(store, empty_crawl_cooldown=10)

    def test_active_included(self):
        """Active sources are eligible."""
        bandit = self._make_bandit({
            "active_src": {"status": "active", "consecutive_empty_crawls": 0},
        })
        eligible = bandit._get_eligible_sources(["active_src"])
        assert "active_src" in eligible

    def test_archived_excluded(self):
        """Archived sources are excluded."""
        bandit = self._make_bandit({
            "archived_src": {"status": "archived", "consecutive_empty_crawls": 0},
        })
        eligible = bandit._get_eligible_sources(["archived_src"])
        assert "archived_src" not in eligible

    def test_archived_excluded_even_with_active(self):
        """Archived sources excluded while active ones pass."""
        bandit = self._make_bandit({
            "good": {"status": "active", "consecutive_empty_crawls": 0},
            "bad": {"status": "archived", "consecutive_empty_crawls": 0},
        })
        eligible = bandit._get_eligible_sources(["good", "bad"])
        assert "good" in eligible
        assert "bad" not in eligible

    def test_inactive_future_probe_excluded(self):
        """Inactive source with future probe time is excluded."""
        future = datetime.now(timezone.utc) + timedelta(days=30)
        bandit = self._make_bandit({
            "probe_future": {
                "status": "inactive",
                "next_probe_at": future,
                "consecutive_empty_crawls": 0,
            },
        })
        eligible = bandit._get_eligible_sources(["probe_future"])
        assert "probe_future" not in eligible

    def test_inactive_past_probe_included(self):
        """Inactive source with past probe time is included."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        bandit = self._make_bandit({
            "probe_past": {
                "status": "inactive",
                "next_probe_at": past,
                "consecutive_empty_crawls": 0,
            },
        })
        eligible = bandit._get_eligible_sources(["probe_past"])
        assert "probe_past" in eligible


# ====================================================================
#  Test 7: Empty inputs return empty outputs
# ====================================================================


class TestEmptyInputs:
    """Empty inputs should produce empty outputs without errors."""

    def test_empty_available_sources(self):
        """_get_eligible_sources([]) returns []."""
        store = SourceBeliefStore()
        bandit = CrawlBandit(store)
        eligible = bandit._get_eligible_sources([])
        assert eligible == []

    async def test_empty_beliefs_accuracy(self, tmp_db, monkeypatch):
        """compute_source_accuracy with no data returns {}."""
        monkeypatch.setattr(
            "crypto_sentiment_crawler.analysis.belief_updater.MIN_SAMPLES", 0
        )
        results = await compute_source_accuracy(tmp_db, lookback_days=100000)
        assert results == {}

    def test_empty_belief_priors(self):
        """update_belief_priors with empty inputs returns {}."""
        result = update_belief_priors({}, {})
        assert result == {}

    def test_empty_beliefs_nonempty_accuracy(self):
        """Empty current beliefs with accuracy data should add sources."""
        acc = {
            "new_src": {
                "accuracy": 0.6, "correct": 5, "incorrect": 5,
                "abstained": 0, "total": 10, "correlation": 0.0,
                "coverage": 1.0, "is_contrarian": False,
                "type_label": "neutral",
                "credible_interval_lower": 0.30,
                "credible_interval_upper": 0.70,
                "effective_n": 10,
            },
        }
        result = update_belief_priors({}, acc)
        assert "new_src" in result
        assert result["new_src"]["alpha"] == 6  # 1 + 5


# ====================================================================
#  Test 8: Full pipeline smoke test
# ====================================================================


class TestFullPipelineSmoke:
    """Minimal end-to-end run through DB → compute_source_accuracy → update_belief_priors."""

    BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)

    async def test_pipeline_returns_structured_output(self, tmp_db):
        """Full pipeline produces well-formed belief dicts with all expected keys."""
        # ── Seed minimal data ────────────────────────────────────
        # Need prices at hours 0..23 since future_hour = hour+4 can be up to 23
        for i in range(24):
            await _insert_price(
                tmp_db,
                (self.BASE + timedelta(hours=i)).isoformat(),
                50000.0 + 10 * i,
            )
        await _insert_user_profile(tmp_db, 1, "user1", "smoke_src")
        for i in range(20):
            await _insert_sentiment_score(
                tmp_db, i + 1, 1,
                (self.BASE + timedelta(hours=i)).isoformat(),
                0.20 if i % 2 == 0 else -0.20,
            )
        await tmp_db.conn.commit()

        # ── Run compute_source_accuracy ──────────────────────────
        accuracy = await compute_source_accuracy(tmp_db, lookback_days=100000)
        # With 20 source-hours and MIN_SAMPLES=20, source should be included
        # only if effective_n >= 20.  Each hour has 1 post → 20 source-hours.
        # Non-neutral (abs > 0.05): all 20 have |0.2| > 0.05
        # Price change at each hour h: (50000 + 10*(h+4) - (50000 + 10*h)) / (50000 + 10*h)
        # = (40) / (50000 + 10*h) → always positive (since price increases)
        # Scores: even hours = +0.20 (positive), odd hours = -0.20 (negative)
        # Even hours: pos × pos price → correct
        # Odd hours: neg × pos price → incorrect
        # So: 10 correct, 10 incorrect, effective_n = 20
        assert "smoke_src" in accuracy
        d = accuracy["smoke_src"]
        assert d["effective_n"] >= 20, f"Expected >=20 effective_n, got {d['effective_n']}"
        assert d["correct"] + d["incorrect"] == d["effective_n"]

        # ── Run update_belief_priors ─────────────────────────────
        current_beliefs = {
            "smoke_src": {"source": "smoke_src", "alpha": 1.0, "beta": 1.0,
                           "total_crawls": 0},
        }
        beliefs = update_belief_priors(current_beliefs, accuracy)

        assert "smoke_src" in beliefs
        b = beliefs["smoke_src"]

        # Required fields for inference
        assert "alpha" in b
        assert "beta" in b
        assert "accuracy" in b
        assert "correlation" in b
        assert "is_contrarian" in b
        assert "type_label" in b
        assert "credible_interval_lower" in b
        assert "credible_interval_upper" in b
        assert "effective_n" in b
        assert "coverage" in b
        assert "last_updated" in b

        # Alpha/beta from neutral prior + observed counts
        expected_alpha = 1 + d["correct"]
        expected_beta = 1 + d["incorrect"]
        assert b["alpha"] == pytest.approx(expected_alpha, abs=0.01)
        assert b["beta"] == pytest.approx(expected_beta, abs=0.01)
