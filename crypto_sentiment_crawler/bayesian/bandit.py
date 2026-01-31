"""Thompson Sampling bandit for source selection."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from .beliefs import SourceBelief, SourceBeliefStore


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
    ):
        """
        Args:
            belief_store: Store of source beliefs
            exploration_decay: Decay rate for exploration bonus per selection
            initial_exploration: Initial exploration weight
            min_exploration: Minimum exploration weight
            causal_bonus: Multiplier for sources with causal evidence
        """
        self.belief_store = belief_store
        self.exploration_weight = initial_exploration
        self.exploration_decay = exploration_decay
        self.min_exploration = min_exploration
        self.causal_bonus = causal_bonus

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

        best_source = None
        best_score = -np.inf
        best_result = None

        for source in available_sources:
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
