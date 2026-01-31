"""
Source manager: Orchestrate discovery, evaluation, and source list management.

Responsibilities:
1. Run periodic discovery of new sources
2. Evaluate candidates and update source list
3. Persist discovered/rejected sources
4. Integrate with crawler orchestrator
"""

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..crawler.fetcher import Fetcher
from ..crawler.sources import SourceConfig
from ..logging_config import logger
from .evaluator import EvaluationResult, SourceEvaluator
from .reddit_discovery import SEED_SUBREDDITS, DiscoveredSubreddit, RedditDiscovery


@dataclass
class ManagedSource:
    """A source being managed by the discovery system."""

    name: str
    source_type: str  # "reddit", "news", etc.
    status: str  # "active", "monitoring", "rejected", "pending"
    added_at: datetime
    last_evaluated: datetime | None = None
    evaluation_score: float = 0.0
    crawl_count: int = 0
    error_count: int = 0
    notes: str = ""


@dataclass
class DiscoveryState:
    """Persistent state for source discovery."""

    sources: dict[str, dict] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    last_discovery: str | None = None
    discovery_count: int = 0

    def to_dict(self) -> dict:
        return {
            "sources": self.sources,
            "rejected": self.rejected,
            "last_discovery": self.last_discovery,
            "discovery_count": self.discovery_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveryState":
        return cls(
            sources=data.get("sources", {}),
            rejected=data.get("rejected", []),
            last_discovery=data.get("last_discovery"),
            discovery_count=data.get("discovery_count", 0),
        )


class SourceManager:
    """
    Manage source discovery and lifecycle.

    Workflow:
    1. discover() - Find new candidate sources
    2. evaluate() - Assess candidates
    3. promote() - Add good sources to active crawler
    4. demote() - Remove underperforming sources
    """

    def __init__(
        self,
        state_path: str = "data/discovery_state.json",
        fetcher: Fetcher | None = None,
    ):
        self.state_path = Path(state_path)
        self.fetcher = fetcher
        self._owns_fetcher = fetcher is None

        self.state = DiscoveryState()
        self.discovery: RedditDiscovery | None = None
        self.evaluator: SourceEvaluator | None = None

        # Initialize with seed sources
        self._init_seeds()

    def _init_seeds(self) -> None:
        """Initialize seed sources as active."""
        for seed in SEED_SUBREDDITS:
            key = f"reddit_{seed}"
            if key not in self.state.sources:
                self.state.sources[key] = {
                    "name": key,
                    "source_type": "reddit",
                    "subreddit": seed,
                    "status": "active",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "evaluation_score": 0.5,  # Default score
                    "notes": "seed source",
                }

    async def __aenter__(self):
        if self._owns_fetcher:
            self.fetcher = Fetcher()
            await self.fetcher.start()

        self.discovery = RedditDiscovery(self.fetcher)
        self.evaluator = SourceEvaluator(self.fetcher)

        await self._load_state()
        return self

    async def __aexit__(self, *args):
        await self._save_state()
        if self._owns_fetcher and self.fetcher:
            await self.fetcher.close()

    async def _load_state(self) -> None:
        """Load state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    data = json.load(f)
                self.state = DiscoveryState.from_dict(data)
                # Restore rejected list to discovery
                for name in self.state.rejected:
                    self.discovery.rejected.add(name)
                logger.info(f"Loaded discovery state: {len(self.state.sources)} sources")
            except Exception as e:
                logger.warning(f"Could not load discovery state: {e}")

    async def _save_state(self) -> None:
        """Save state to disk."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)
        logger.debug("Discovery state saved")

    async def run_discovery(self) -> list[DiscoveredSubreddit]:
        """
        Run full discovery process to find new sources.
        """
        logger.info("Starting source discovery...")

        # Run discovery
        found = await self.discovery.discover_all()

        self.state.last_discovery = datetime.now(timezone.utc).isoformat()
        self.state.discovery_count += 1

        await self._save_state()

        logger.info(f"Discovery complete: found {len(found)} new candidates")
        return found

    async def evaluate_candidates(
        self,
        limit: int = 20,
    ) -> list[tuple[DiscoveredSubreddit, EvaluationResult]]:
        """
        Evaluate discovered candidates.

        Returns list of (candidate, evaluation) tuples sorted by score.
        """
        candidates = self.discovery.get_candidates(min_relevance=0.2)[:limit]

        if not candidates:
            logger.info("No candidates to evaluate")
            return []

        logger.info(f"Evaluating {len(candidates)} candidates...")

        results = []
        for candidate in candidates:
            eval_result = await self.evaluator.evaluate(candidate.name)
            if eval_result:
                candidate.evaluated = True
                candidate.activity_score = eval_result.overall_score
                results.append((candidate, eval_result))

            await asyncio.sleep(1)  # Rate limit

        # Sort by overall score
        results.sort(key=lambda x: x[1].overall_score, reverse=True)

        return results

    async def process_evaluations(
        self,
        results: list[tuple[DiscoveredSubreddit, EvaluationResult]],
    ) -> dict[str, list[str]]:
        """
        Process evaluation results and update source lists.

        Returns dict with lists of added, monitoring, and rejected sources.
        """
        added = []
        monitoring = []
        rejected = []

        for candidate, eval_result in results:
            key = f"reddit_{candidate.name}"

            if eval_result.recommendation == "add":
                self.state.sources[key] = {
                    "name": key,
                    "source_type": "reddit",
                    "subreddit": candidate.name,
                    "status": "active",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "last_evaluated": datetime.now(timezone.utc).isoformat(),
                    "evaluation_score": eval_result.overall_score,
                    "notes": eval_result.reason,
                }
                added.append(candidate.name)
                logger.info(f"Added r/{candidate.name} as active source")

            elif eval_result.recommendation == "monitor":
                self.state.sources[key] = {
                    "name": key,
                    "source_type": "reddit",
                    "subreddit": candidate.name,
                    "status": "monitoring",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "last_evaluated": datetime.now(timezone.utc).isoformat(),
                    "evaluation_score": eval_result.overall_score,
                    "notes": eval_result.reason,
                }
                monitoring.append(candidate.name)
                logger.info(f"Added r/{candidate.name} to monitoring")

            else:  # reject
                self.state.rejected.append(candidate.name)
                self.discovery.reject(candidate.name)
                rejected.append(candidate.name)
                logger.debug(f"Rejected r/{candidate.name}: {eval_result.reason}")

        await self._save_state()

        return {
            "added": added,
            "monitoring": monitoring,
            "rejected": rejected,
        }

    def get_active_sources(self) -> dict[str, SourceConfig]:
        """
        Get active sources as SourceConfig objects for the crawler.
        """
        sources = {}

        for key, data in self.state.sources.items():
            if data.get("status") != "active":
                continue

            if data.get("source_type") == "reddit":
                subreddit = data.get("subreddit", key.replace("reddit_", ""))
                sources[key] = SourceConfig(
                    name=key,
                    source_type="reddit",
                    base_url=f"https://old.reddit.com/r/{subreddit}",
                    rate_limit=1.0,
                )

        return sources

    def get_monitoring_sources(self) -> list[str]:
        """Get list of sources being monitored."""
        return [
            data.get("subreddit", key.replace("reddit_", ""))
            for key, data in self.state.sources.items()
            if data.get("status") == "monitoring"
        ]

    async def promote_source(self, name: str) -> bool:
        """Promote a monitoring source to active."""
        key = f"reddit_{name}" if not name.startswith("reddit_") else name

        if key not in self.state.sources:
            return False

        self.state.sources[key]["status"] = "active"
        self.state.sources[key]["notes"] = "promoted from monitoring"
        await self._save_state()
        logger.info(f"Promoted {key} to active")
        return True

    async def demote_source(self, name: str) -> bool:
        """Demote an active source to monitoring."""
        key = f"reddit_{name}" if not name.startswith("reddit_") else name

        if key not in self.state.sources:
            return False

        self.state.sources[key]["status"] = "monitoring"
        self.state.sources[key]["notes"] = "demoted due to low performance"
        await self._save_state()
        logger.info(f"Demoted {key} to monitoring")
        return True

    def get_statistics(self) -> dict:
        """Get discovery statistics."""
        statuses = {}
        for data in self.state.sources.values():
            status = data.get("status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1

        return {
            "total_sources": len(self.state.sources),
            "by_status": statuses,
            "rejected_count": len(self.state.rejected),
            "discovery_runs": self.state.discovery_count,
            "last_discovery": self.state.last_discovery,
        }

    def print_summary(self) -> None:
        """Print a summary of managed sources."""
        print("\n" + "=" * 60)
        print("SOURCE DISCOVERY SUMMARY")
        print("=" * 60)

        stats = self.get_statistics()
        print(f"\nTotal sources: {stats['total_sources']}")
        print(f"Discovery runs: {stats['discovery_runs']}")

        print("\nBy status:")
        for status, count in stats["by_status"].items():
            print(f"  {status}: {count}")

        print(f"\nRejected: {stats['rejected_count']}")

        print("\nActive sources:")
        for key, data in self.state.sources.items():
            if data.get("status") == "active":
                score = data.get("evaluation_score", 0)
                print(f"  {key}: score={score:.2f}")

        print("\nMonitoring:")
        for key, data in self.state.sources.items():
            if data.get("status") == "monitoring":
                score = data.get("evaluation_score", 0)
                reason = data.get("notes", "")[:40]
                print(f"  {key}: score={score:.2f} ({reason})")

        print("=" * 60)


async def run_discovery_cycle() -> dict:
    """
    Run a full discovery cycle.

    Returns summary of discovered/added/rejected sources.
    """
    async with SourceManager() as manager:
        # Discover new candidates
        await manager.run_discovery()

        # Evaluate candidates
        results = await manager.evaluate_candidates(limit=30)

        # Process and categorize
        summary = await manager.process_evaluations(results)

        # Print summary
        manager.print_summary()

        return {
            "added": summary["added"],
            "monitoring": summary["monitoring"],
            "rejected": summary["rejected"],
            "statistics": manager.get_statistics(),
        }


if __name__ == "__main__":
    asyncio.run(run_discovery_cycle())
