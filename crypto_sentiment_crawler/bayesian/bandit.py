"""Thompson Sampling bandit for source selection."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.special import ndtr as norm_cdf

from .beliefs import SourceBelief, SourceBeliefStore
from .gp_model import GPSourceModel, SourceFeatures


@dataclass
class SelectionResult:
    """Result of source selection."""

    source: str
    sampled_value: float
    exploration_bonus: float
    final_score: float
    belief: SourceBelief


class CrawlBandit:
    """
    Thompson Sampling bandit for intelligent source selection.

    Balances exploration (uncertain sources) vs exploitation (known good sources)
    using Bayesian posterior sampling.
    """

    def __init__(
        self,
        belief_store: SourceBeliefStore,
        exploration_decay: float = 0.995,
        initial_exploration: float = 1.0,
        min_exploration: float = 0.1,
        causal_bonus: float = 1.5,
        empty_crawl_cooldown: int = 3,
    ):
        """
        Args:
            belief_store: Store of source beliefs
            exploration_decay: Decay rate for exploration bonus per selection
            initial_exploration: Initial exploration weight
            min_exploration: Minimum exploration weight
            causal_bonus: Multiplier for sources with causal evidence
            empty_crawl_cooldown: Skip sources with this many consecutive empty crawls
        """
        self.belief_store = belief_store
        self.exploration_weight = initial_exploration
        self.exploration_decay = exploration_decay
        self.min_exploration = min_exploration
        self.causal_bonus = causal_bonus
        self.empty_crawl_cooldown = empty_crawl_cooldown

        # Tracking
        self.selection_count = 0
        self.selection_history: list[dict] = []

    def select_source(self, available_sources: list[str] | None = None) -> SelectionResult:
        """
        Select next source to crawl using Thompson Sampling.

        Args:
            available_sources: List of sources to choose from.
                              If None, uses all sources in belief store.

        Returns:
            SelectionResult with chosen source and metadata
        """
        if available_sources is None:
            available_sources = self.belief_store.all_sources()

        if not available_sources:
            raise ValueError("No sources available for selection")

        # Filter out sources on cooldown (too many consecutive empty crawls)
        active_sources = []
        for source in available_sources:
            belief = self.belief_store.get(source)
            if belief.consecutive_empty_crawls < self.empty_crawl_cooldown:
                active_sources.append(source)

        # If all sources are on cooldown, use all (prevent deadlock)
        if not active_sources:
            active_sources = list(available_sources)

        best_source = None
        best_score = -np.inf
        best_result = None

        for source in active_sources:
            belief = self.belief_store.get(source)

            # Thompson Sampling: sample from posterior
            sampled_value = belief.sample()

            # Exploration bonus based on uncertainty
            exploration_bonus = self.exploration_weight * belief.std

            # Causal bonus for sources with Granger causality
            causal_mult = self.causal_bonus if belief.is_causal else 1.0

            # Final score
            final_score = (sampled_value + exploration_bonus) * causal_mult

            if final_score > best_score:
                best_score = final_score
                best_source = source
                best_result = SelectionResult(
                    source=source,
                    sampled_value=sampled_value,
                    exploration_bonus=exploration_bonus,
                    final_score=final_score,
                    belief=belief,
                )

        # Decay exploration weight
        self.exploration_weight = max(
            self.min_exploration,
            self.exploration_weight * self.exploration_decay,
        )

        self.selection_count += 1

        # Log selection
        self.selection_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": best_source,
            "sampled_value": best_result.sampled_value,
            "exploration_bonus": best_result.exploration_bonus,
            "final_score": best_score,
            "exploration_weight": self.exploration_weight,
        })

        return best_result

    def select_batch(
        self,
        n: int,
        available_sources: list[str] | None = None,
        allow_repeats: bool = True,
    ) -> list[SelectionResult]:
        """
        Select multiple sources for parallel crawling.

        Args:
            n: Number of sources to select
            available_sources: Sources to choose from
            allow_repeats: Whether same source can be selected multiple times

        Returns:
            List of SelectionResults
        """
        if available_sources is None:
            available_sources = self.belief_store.all_sources()

        results = []
        remaining = list(available_sources)

        for _ in range(min(n, len(remaining) if not allow_repeats else n)):
            if not remaining:
                break

            result = self.select_source(remaining)
            results.append(result)

            if not allow_repeats:
                remaining.remove(result.source)

        return results

    def update_from_outcome(self, source: str, utility: float) -> None:
        """Update belief after observing crawl outcome."""
        self.belief_store.update(source, utility)

    def get_exploitation_ranking(self) -> list[tuple[str, float]]:
        """Rank sources by posterior mean (pure exploitation)."""
        return self.belief_store.rank_by_mean()

    def get_exploration_ranking(self) -> list[tuple[str, float]]:
        """Rank sources by uncertainty (pure exploration)."""
        return self.belief_store.rank_by_uncertainty()

    def get_statistics(self) -> dict:
        """Get bandit statistics."""
        return {
            "selection_count": self.selection_count,
            "exploration_weight": self.exploration_weight,
            "num_sources": len(self.belief_store.beliefs),
            "exploitation_ranking": self.get_exploitation_ranking()[:5],
            "exploration_ranking": self.get_exploration_ranking()[:5],
        }

    def compute_regret(self, selected: str, outcomes: dict[str, float]) -> float:
        """
        Compute regret for a selection.

        Regret = utility of best source - utility of selected source
        """
        if selected not in outcomes:
            return 0.0

        selected_utility = outcomes[selected]
        best_utility = max(outcomes.values())

        return best_utility - selected_utility


class GPBandit(CrawlBandit):
    """Thompson Sampling bandit with GP-correlated source selection.

    For GP-eligible sources (>= min_observations and features available),
    draws correlated Thompson samples via the GP posterior. Cold-start
    sources fall back to independent Beta sampling.
    """

    MIN_GP_ELIGIBLE = 5   # Minimum GP-eligible sources to use GP
    MIN_OBSERVATIONS = 10  # Minimum crawls before a source is GP-eligible

    def __init__(
        self,
        belief_store: SourceBeliefStore,
        gp_model: GPSourceModel | None = None,
        features: dict[str, SourceFeatures] | None = None,
        **kwargs,
    ):
        super().__init__(belief_store, **kwargs)
        self.gp_model = gp_model or GPSourceModel()
        self.features = features or {}
        self._gp_active = False

    def update_gp(self, features: dict[str, SourceFeatures]) -> bool:
        """Refit GP with current beliefs and features.

        Args:
            features: Dict of source -> SourceFeatures (standardized)

        Returns:
            True if GP was fitted successfully
        """
        self.features = features

        # Determine GP-eligible sources
        eligible = []
        alphas = []
        betas = []

        for source, sf in features.items():
            belief = self.belief_store.get(source)
            if belief.total_crawls >= self.MIN_OBSERVATIONS:
                eligible.append(sf)
                alphas.append(belief.alpha)
                betas.append(belief.beta)

        if len(eligible) < self.MIN_GP_ELIGIBLE:
            self._gp_active = False
            return False

        try:
            self.gp_model.fit(
                eligible,
                np.array(alphas),
                np.array(betas),
            )
            self._gp_active = True
            return True
        except (np.linalg.LinAlgError, ValueError):
            self._gp_active = False
            return False

    def select_source(self, available_sources: list[str] | None = None) -> SelectionResult:
        """Select source using GP-correlated Thompson Sampling when possible.

        GP-eligible sources get correlated samples. Cold-start sources
        use independent Beta sampling. Cooldown filtering still applies.
        """
        if available_sources is None:
            available_sources = self.belief_store.all_sources()

        if not available_sources:
            raise ValueError("No sources available for selection")

        # Filter out sources on cooldown
        active_sources = []
        for source in available_sources:
            belief = self.belief_store.get(source)
            if belief.consecutive_empty_crawls < self.empty_crawl_cooldown:
                active_sources.append(source)

        if not active_sources:
            active_sources = list(available_sources)

        # Split into GP-eligible and cold-start
        gp_sources = []
        cold_sources = []

        if self._gp_active and self.gp_model.sources:
            gp_source_set = set(self.gp_model.sources)
            for source in active_sources:
                belief = self.belief_store.get(source)
                if (source in gp_source_set
                        and belief.total_crawls >= self.MIN_OBSERVATIONS):
                    gp_sources.append(source)
                else:
                    cold_sources.append(source)
        else:
            cold_sources = active_sources

        # Draw GP-correlated samples for eligible sources
        gp_samples = {}
        if gp_sources and self._gp_active:
            try:
                theta = self.gp_model.sample_thompson(n_samples=1)[0]
                source_to_idx = {
                    s: i for i, s in enumerate(self.gp_model.sources)
                }
                for source in gp_sources:
                    idx = source_to_idx.get(source)
                    if idx is not None:
                        gp_samples[source] = theta[idx]
            except (np.linalg.LinAlgError, ValueError):
                # Fall back to independent sampling
                pass

        # Score all sources
        best_source = None
        best_score = -np.inf
        best_result = None

        for source in active_sources:
            belief = self.belief_store.get(source)

            if source in gp_samples:
                sampled_value = gp_samples[source]
            else:
                sampled_value = belief.sample()

            exploration_bonus = self.exploration_weight * belief.std
            causal_mult = self.causal_bonus if belief.is_causal else 1.0
            final_score = (sampled_value + exploration_bonus) * causal_mult

            if final_score > best_score:
                best_score = final_score
                best_source = source
                best_result = SelectionResult(
                    source=source,
                    sampled_value=sampled_value,
                    exploration_bonus=exploration_bonus,
                    final_score=final_score,
                    belief=belief,
                )

        # Decay exploration weight
        self.exploration_weight = max(
            self.min_exploration,
            self.exploration_weight * self.exploration_decay,
        )

        self.selection_count += 1

        self.selection_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": best_source,
            "sampled_value": best_result.sampled_value,
            "exploration_bonus": best_result.exploration_bonus,
            "final_score": best_score,
            "exploration_weight": self.exploration_weight,
            "gp_active": self._gp_active,
            "gp_sources_count": len(gp_sources),
        })

        return best_result

    @property
    def is_gp_active(self) -> bool:
        return self._gp_active


class UCBBandit:
    """
    Upper Confidence Bound bandit (alternative to Thompson Sampling).

    UCB is deterministic and provides theoretical regret bounds.
    """

    def __init__(
        self,
        belief_store: SourceBeliefStore,
        exploration_constant: float = 2.0,
    ):
        self.belief_store = belief_store
        self.exploration_constant = exploration_constant
        self.total_selections = 0

    def select_source(self, available_sources: list[str] | None = None) -> str:
        """Select source using UCB1 algorithm."""
        if available_sources is None:
            available_sources = self.belief_store.all_sources()

        if not available_sources:
            raise ValueError("No sources available")

        self.total_selections += 1

        best_source = None
        best_ucb = -np.inf

        for source in available_sources:
            belief = self.belief_store.get(source)

            if belief.total_crawls == 0:
                # Unvisited source gets infinite UCB (must explore)
                return source

            # UCB = mean + c * sqrt(ln(t) / n)
            mean = belief.mean
            exploration_term = self.exploration_constant * math.sqrt(
                math.log(self.total_selections) / belief.total_crawls
            )
            ucb = mean + exploration_term

            if ucb > best_ucb:
                best_ucb = ucb
                best_source = source

        return best_source
