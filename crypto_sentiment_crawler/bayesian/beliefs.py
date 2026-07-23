"""Source belief model using Beta distribution."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from scipy import stats
from scipy.special import ndtri as norm_ppf
from scipy.stats import norm


@dataclass
class SourceBelief:
    """
    Bayesian belief about a source's informativeness.

    Uses Beta(α, β) distribution to model probability that
    a source will provide informative content.

    Posterior mean: E[θ] = α / (α + β)
    Posterior variance: Var[θ] = αβ / [(α+β)²(α+β+1)]
    """

    source: str
    alpha: float = 1.0  # Pseudo-count of informative crawls
    beta: float = 1.0   # Pseudo-count of non-informative crawls

    # Causal metrics (updated weekly)
    granger_pvalue: float | None = None
    lead_time_hours: float | None = None

    # Tracking
    total_crawls: int = 0
    consecutive_empty_crawls: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Source status tracking
    last_success_at: datetime | None = None
    first_empty_at: datetime | None = None
    status: str = "active"  # "active", "inactive", "archived"
    next_probe_at: datetime | None = None

    # Updater metadata (populated by belief_updater)
    accuracy: float | None = None
    correlation: float | None = None
    is_contrarian: bool = False
    type_label: str = "uninitialized"  # momentum, neutral, contrarian, insufficient_data
    credible_interval_lower: float | None = None
    credible_interval_upper: float | None = None
    effective_n: int = 0
    coverage: float | None = None

    @property
    def mean(self) -> float:
        """Posterior mean: expected probability of being informative."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def variance(self) -> float:
        """Posterior variance: uncertainty in our belief."""
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def std(self) -> float:
        """Posterior standard deviation."""
        return np.sqrt(self.variance)

    @property
    def is_causal(self) -> bool:
        """Whether source Granger-causes price (p < 0.05)."""
        return self.granger_pvalue is not None and self.granger_pvalue < 0.05

    def sample(self) -> float:
        """Sample from posterior Beta distribution (for Thompson Sampling)."""
        return np.random.beta(self.alpha, self.beta)

    def update(self, was_informative: bool) -> None:
        """Update belief after observing outcome."""
        if was_informative:
            self.alpha += 1
        else:
            self.beta += 1
        self.total_crawls += 1
        self.consecutive_empty_crawls = 0  # Reset on any real outcome
        self.last_updated = datetime.now(timezone.utc)

    def record_successful_crawl(self) -> None:
        """Record a successful crawl (content was returned).

        Resets empty-crawl tracking and marks source as active.
        """
        self.consecutive_empty_crawls = 0
        self.last_success_at = datetime.now(timezone.utc)
        self.first_empty_at = None
        if self.status == "inactive":
            self.status = "active"
        self.last_updated = datetime.now(timezone.utc)

    def record_empty_crawl(self, penalty: float = 0.3) -> None:
        """Record an empty crawl (no posts returned).

        Applies a soft beta penalty so inflated accuracy gradually decays.
        Penalty is smaller than a full negative outcome (1.0) to reflect
        that empty != bad content, just no content.
        """
        self.consecutive_empty_crawls += 1
        if self.consecutive_empty_crawls == 1:
            self.first_empty_at = datetime.now(timezone.utc)
        self.beta += penalty
        self.last_updated = datetime.now(timezone.utc)

    def update_with_utility(self, utility: float, threshold: float = 0.5) -> None:
        """Update belief based on utility score."""
        self.update(was_informative=(utility > threshold))

    def to_gaussian_moments(self) -> tuple[float, float]:
        """Convert Beta -> Gaussian in probit space via moment matching.

        Returns:
            (mu, sigma2) where mu = Phi^-1(mean) and
            sigma2 = 1 / (phi(mu)^2 * (alpha + beta + 1))
        """
        p = np.clip(self.mean, 0.01, 0.99)
        mu = norm_ppf(p)
        phi_val = norm.pdf(mu)
        if phi_val > 1e-10:
            sigma2 = 1.0 / (phi_val ** 2 * (self.alpha + self.beta + 1))
        else:
            sigma2 = 100.0
        return mu, sigma2

    def confidence_interval(self, confidence: float = 0.95) -> tuple[float, float]:
        """Compute credible interval for the informativeness probability."""
        lower = (1 - confidence) / 2
        upper = 1 - lower
        return (
            stats.beta.ppf(lower, self.alpha, self.beta),
            stats.beta.ppf(upper, self.alpha, self.beta),
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary for storage."""
        return {
            "source": self.source,
            "alpha": self.alpha,
            "beta": self.beta,
            "granger_pvalue": self.granger_pvalue,
            "lead_time_hours": self.lead_time_hours,
            "total_crawls": self.total_crawls,
            "consecutive_empty_crawls": self.consecutive_empty_crawls,
            "last_updated": self.last_updated.isoformat(),
            "last_success_at": self.last_success_at.isoformat()
            if self.last_success_at else None,
            "first_empty_at": self.first_empty_at.isoformat()
            if self.first_empty_at else None,
            "status": self.status,
            "next_probe_at": self.next_probe_at.isoformat()
            if self.next_probe_at else None,
            # Updater metadata
            "accuracy": self.accuracy,
            "correlation": self.correlation,
            "is_contrarian": self.is_contrarian,
            "type_label": self.type_label,
            "credible_interval_lower": self.credible_interval_lower,
            "credible_interval_upper": self.credible_interval_upper,
            "effective_n": self.effective_n,
            "coverage": self.coverage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceBelief":
        """Deserialize from dictionary."""
        return cls(
            source=data["source"],
            alpha=data["alpha"],
            beta=data["beta"],
            granger_pvalue=data.get("granger_pvalue"),
            lead_time_hours=data.get("lead_time_hours"),
            total_crawls=data.get("total_crawls", 0),
            consecutive_empty_crawls=data.get("consecutive_empty_crawls", 0),
            last_updated=datetime.fromisoformat(data["last_updated"])
            if "last_updated" in data
            else datetime.now(timezone.utc),
            last_success_at=datetime.fromisoformat(data["last_success_at"])
            if data.get("last_success_at")
            else None,
            first_empty_at=datetime.fromisoformat(data["first_empty_at"])
            if data.get("first_empty_at")
            else None,
            status=data.get("status", "active"),
            next_probe_at=datetime.fromisoformat(data["next_probe_at"])
            if data.get("next_probe_at")
            else None,
            # Updater metadata
            accuracy=data.get("accuracy"),
            correlation=data.get("correlation"),
            is_contrarian=data.get("is_contrarian", False),
            type_label=data.get("type_label", "uninitialized"),
            credible_interval_lower=data.get("credible_interval_lower"),
            credible_interval_upper=data.get("credible_interval_upper"),
            effective_n=data.get("effective_n", 0),
            coverage=data.get("coverage"),
        )


class SourceBeliefStore:
    """Manage beliefs for multiple sources."""

    def __init__(self, default_alpha: float = 1.0, default_beta: float = 1.0):
        self.beliefs: dict[str, SourceBelief] = {}
        self.default_alpha = default_alpha
        self.default_beta = default_beta

    def get(self, source: str) -> SourceBelief:
        """Get belief for source, creating with default prior if needed."""
        if source not in self.beliefs:
            self.beliefs[source] = SourceBelief(
                source=source,
                alpha=self.default_alpha,
                beta=self.default_beta,
            )
        return self.beliefs[source]

    def update(self, source: str, utility: float, threshold: float = 0.5) -> None:
        """Update belief for a source after crawl."""
        belief = self.get(source)
        belief.update_with_utility(utility, threshold)

    def all_sources(self) -> list[str]:
        """Get all tracked sources."""
        return list(self.beliefs.keys())

    def rank_by_mean(self) -> list[tuple[str, float]]:
        """Rank sources by posterior mean (exploitation ranking)."""
        return sorted(
            [(s, b.mean) for s, b in self.beliefs.items()],
            key=lambda x: x[1],
            reverse=True,
        )

    def rank_by_uncertainty(self) -> list[tuple[str, float]]:
        """Rank sources by uncertainty (exploration ranking)."""
        return sorted(
            [(s, b.std) for s, b in self.beliefs.items()],
            key=lambda x: x[1],
            reverse=True,
        )

    def to_dict(self) -> dict:
        """Serialize all beliefs."""
        return {source: belief.to_dict() for source, belief in self.beliefs.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "SourceBeliefStore":
        """Deserialize from dictionary."""
        store = cls()
        for source, belief_data in data.items():
            store.beliefs[source] = SourceBelief.from_dict(belief_data)
        return store
