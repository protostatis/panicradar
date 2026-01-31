"""
Orchestrator: Integrates Bayesian selection → Crawler → Belief updates.

This is the main loop that ties the decision layer to the execution layer.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .bayesian import CrawlBandit, SourceBeliefStore, UtilityScorer
from .bayesian.cold_start import compute_baseline_informativeness, initialize_source_belief
from .causal import GrangerAnalyzer
from .crawler import ContentPipeline, Fetcher
from .crawler.pipeline import CrawledContent, RedditPipeline
from .crawler.sources import DEFAULT_SOURCES, SourceConfig
from .logging_config import logger
from .storage.db import Database
from .storage.models import PriceData, SentimentRaw, SentimentScore


@dataclass
class CrawlOutcome:
    """Tracks a crawl for later utility evaluation."""

    content: CrawledContent
    price_at_crawl: float
    timestamp: datetime
    evaluated: bool = False
    utility: float | None = None


@dataclass
class OrchestratorState:
    """Persistent state for the orchestrator."""

    beliefs: dict = field(default_factory=dict)
    pending_outcomes: list = field(default_factory=list)
    baseline_informativeness: float = 0.5
    last_causal_update: str | None = None
    total_crawls: int = 0

    def to_dict(self) -> dict:
        return {
            "beliefs": self.beliefs,
            "baseline_informativeness": self.baseline_informativeness,
            "last_causal_update": self.last_causal_update,
            "total_crawls": self.total_crawls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrchestratorState":
        return cls(
            beliefs=data.get("beliefs", {}),
            baseline_informativeness=data.get("baseline_informativeness", 0.5),
            last_causal_update=data.get("last_causal_update"),
            total_crawls=data.get("total_crawls", 0),
        )


class CrawlerOrchestrator:
    """
    Main orchestrator that integrates:
    - Bayesian source selection
    - Crawler execution
    - Outcome evaluation and belief updates
    - Periodic causal discovery
    """

    def __init__(
        self,
        db: Database,
        sources: dict[str, SourceConfig] | None = None,
        state_path: str = "data/orchestrator_state.json",
        eval_lag_hours: int = 4,
    ):
        self.db = db
        self.sources = sources or DEFAULT_SOURCES
        self.state_path = Path(state_path)
        self.eval_lag_hours = eval_lag_hours

        # Components
        self.belief_store = SourceBeliefStore()
        self.bandit: CrawlBandit | None = None
        self.utility_scorer = UtilityScorer()
        self.granger = GrangerAnalyzer()

        # Crawlers
        self.fetcher = Fetcher()
        self.pipeline: ContentPipeline | None = None
        self.reddit_pipeline: RedditPipeline | None = None

        # State
        self.state = OrchestratorState()
        self.pending_outcomes: list[CrawlOutcome] = []

        # Current prices (for utility evaluation)
        self.current_prices: dict[str, float] = {}

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing orchestrator...")

        # Load or create state
        await self._load_state()

        # Initialize beliefs for all sources
        await self._initialize_beliefs()

        # Create bandit
        self.bandit = CrawlBandit(self.belief_store)

        # Start fetcher
        await self.fetcher.start()
        self.pipeline = ContentPipeline(self.fetcher)
        self.reddit_pipeline = RedditPipeline(self.fetcher)

        logger.info(f"Initialized with {len(self.sources)} sources")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        await self._save_state()
        if self.fetcher:
            await self.fetcher.close()
        logger.info("Orchestrator shutdown complete")

    async def _load_state(self) -> None:
        """Load state from disk."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    data = json.load(f)
                self.state = OrchestratorState.from_dict(data)
                self.belief_store = SourceBeliefStore.from_dict(self.state.beliefs)
                logger.info(f"Loaded state: {self.state.total_crawls} total crawls")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")

    async def _save_state(self) -> None:
        """Save state to disk."""
        self.state.beliefs = self.belief_store.to_dict()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)
        logger.debug("State saved")

    async def _initialize_beliefs(self) -> None:
        """Initialize beliefs for all sources."""
        # Compute baseline from price data if available
        baseline = await self._compute_baseline()
        self.state.baseline_informativeness = baseline

        # Initialize beliefs for sources not in store
        for source_name, source_config in self.sources.items():
            if source_name not in self.belief_store.beliefs:
                belief = initialize_source_belief(
                    source=source_name,
                    baseline=baseline,
                    source_type=source_config.source_type,
                )
                self.belief_store.beliefs[source_name] = belief
                logger.info(
                    f"Initialized {source_name}: α={belief.alpha:.2f}, "
                    f"β={belief.beta:.2f}, mean={belief.mean:.3f}"
                )

    async def _compute_baseline(self) -> float:
        """Compute baseline informativeness from price history."""
        try:
            # Get recent prices from database
            prices = await self.db.get_latest_prices("BTC", limit=500)
            if len(prices) < 100:
                logger.info("Insufficient price history, using default baseline")
                return 0.5

            import pandas as pd
            price_series = pd.Series(
                [p.price_usd for p in prices],
                index=[p.timestamp for p in prices],
            ).sort_index()

            baseline = compute_baseline_informativeness(price_series)
            logger.info(f"Computed baseline informativeness: {baseline:.3f}")
            return baseline

        except Exception as e:
            logger.warning(f"Could not compute baseline: {e}")
            return 0.5

    async def _get_current_price(self, coin: str = "BTC") -> float:
        """Get current price for a coin."""
        if coin in self.current_prices:
            return self.current_prices[coin]

        prices = await self.db.get_latest_prices(coin, limit=1)
        if prices:
            self.current_prices[coin] = prices[0].price_usd
            return prices[0].price_usd
        return 0.0

    async def select_and_crawl(self) -> CrawledContent | None:
        """
        Main loop iteration:
        1. Select source using Thompson Sampling
        2. Crawl the selected source
        3. Store content and queue for evaluation
        """
        if not self.bandit:
            raise RuntimeError("Orchestrator not initialized")

        # Select source
        available = list(self.sources.keys())
        selection = self.bandit.select_source(available)
        source_name = selection.source
        source_config = self.sources[source_name]

        logger.info(
            f"Selected: {source_name} "
            f"(sampled={selection.sampled_value:.3f}, "
            f"mean={selection.belief.mean:.3f})"
        )

        # Crawl based on source type
        content = await self._crawl_source(source_name, source_config)

        if content:
            # Get current price for later evaluation
            price = await self._get_current_price("BTC")

            # Queue for evaluation
            outcome = CrawlOutcome(
                content=content,
                price_at_crawl=price,
                timestamp=datetime.now(timezone.utc),
            )
            self.pending_outcomes.append(outcome)

            # Store to database
            await self._store_content(content)

            # Compute immediate novelty (before accuracy is known)
            text = content.content or content.title or ""
            novelty = self.utility_scorer.compute_novelty_only(text, add_to_recent=True)
            title_preview = (content.title or "No title")[:50]
            logger.info(f"Crawled: {title_preview}... (novelty={novelty:.3f})")

            self.state.total_crawls += 1

        return content

    async def _crawl_source(
        self,
        source_name: str,
        source_config: SourceConfig,
    ) -> CrawledContent | None:
        """Crawl a specific source based on its type."""
        try:
            if source_name.startswith("reddit_"):
                # Reddit crawling
                subreddit = source_name.replace("reddit_", "")
                posts = await self.reddit_pipeline.crawl_subreddit(
                    subreddit,
                    limit=10,
                )
                if posts:
                    # Return highest-engagement post
                    posts.sort(
                        key=lambda p: p.metadata.get("score", 0),
                        reverse=True,
                    )
                    return posts[0]

            else:
                # Generic web crawling
                url = source_config.get_url()
                selectors = source_config.get_selectors()
                return await self.pipeline.process_url(
                    url,
                    source_name,
                    selectors,
                    source_config.rate_limit,
                )

        except Exception as e:
            logger.error(f"Crawl failed for {source_name}: {e}")
            return None

    async def _store_content(self, content: CrawledContent) -> None:
        """Store crawled content to database."""
        # Store raw
        raw = SentimentRaw(
            timestamp=content.crawled_at,
            source=content.source,
            coin=content.coins_mentioned[0] if content.coins_mentioned else None,
            raw_data={
                "url": content.url,
                "title": content.title,
                "content": (content.content or "")[:1000] if content.content else None,
                "author": content.author,
                "metadata": content.metadata or {},
            },
        )
        await self.db.insert_sentiment_raw(raw)

        # Store sentiment score if coins detected
        for coin in content.coins_mentioned or ["MARKET"]:
            score = SentimentScore(
                timestamp=content.crawled_at,
                coin=coin,
                source=content.source,
                score=content.sentiment_score,
                confidence=0.8,  # TODO: compute from content quality
                sample_size=1,
            )
            await self.db.insert_sentiment_score(score)

    async def evaluate_pending_outcomes(self) -> int:
        """
        Evaluate pending outcomes against actual price movements.
        Returns number of outcomes evaluated.
        """
        if not self.pending_outcomes:
            return 0

        now = datetime.now(timezone.utc)
        evaluated_count = 0

        # Get current price
        current_price = await self._get_current_price("BTC")

        for outcome in self.pending_outcomes:
            if outcome.evaluated:
                continue

            # Check if enough time has passed
            hours_elapsed = (now - outcome.timestamp).total_seconds() / 3600
            if hours_elapsed < self.eval_lag_hours:
                continue

            # Compute utility
            content_text = outcome.content.content or outcome.content.title or ""
            result = self.utility_scorer.compute_utility(
                content=content_text,
                sentiment_score=outcome.content.sentiment_score,
                price_before=outcome.price_at_crawl,
                price_after=current_price,
                add_to_recent=False,  # Already added during crawl
            )

            outcome.utility = result["utility"]
            outcome.evaluated = True

            # Update belief
            self.bandit.update_from_outcome(
                outcome.content.source,
                result["utility"],
            )

            logger.info(
                f"Evaluated {outcome.content.source}: "
                f"utility={result['utility']:.3f} "
                f"(acc={result['accuracy']:.1f}, nov={result['novelty']:.3f})"
            )

            evaluated_count += 1

        # Remove old evaluated outcomes
        self.pending_outcomes = [
            o for o in self.pending_outcomes
            if not o.evaluated or (now - o.timestamp).total_seconds() < 86400
        ]

        return evaluated_count

    async def run_causal_discovery(self) -> dict:
        """Run weekly causal discovery to update source priors."""
        logger.info("Running causal discovery...")

        # Get sentiment and price data for each source
        # TODO: Implement proper data retrieval
        results = {}

        self.state.last_causal_update = datetime.now(timezone.utc).isoformat()
        await self._save_state()

        return results

    async def run_loop(
        self,
        iterations: int = 10,
        delay_seconds: float = 60.0,
    ) -> None:
        """
        Run the main crawl loop.

        Args:
            iterations: Number of crawl iterations (0 for infinite)
            delay_seconds: Delay between iterations
        """
        logger.info(f"Starting crawl loop: {iterations} iterations")

        count = 0
        while iterations == 0 or count < iterations:
            try:
                # Select and crawl
                await self.select_and_crawl()

                # Evaluate any pending outcomes
                evaluated = await self.evaluate_pending_outcomes()
                if evaluated:
                    logger.info(f"Evaluated {evaluated} pending outcomes")

                # Save state periodically
                if count % 10 == 0:
                    await self._save_state()

                count += 1

                # Show current rankings
                if count % 5 == 0:
                    self._log_rankings()

                # Delay
                if delay_seconds > 0 and (iterations == 0 or count < iterations):
                    await asyncio.sleep(delay_seconds)

            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in crawl loop: {e}")
                await asyncio.sleep(5)

        await self._save_state()

    def _log_rankings(self) -> None:
        """Log current source rankings."""
        rankings = self.bandit.get_exploitation_ranking()
        logger.info("Current rankings:")
        for source, mean in rankings[:5]:
            belief = self.belief_store.get(source)
            logger.info(
                f"  {source}: mean={mean:.3f} "
                f"(α={belief.alpha:.1f}, β={belief.beta:.1f}, "
                f"n={belief.total_crawls})"
            )

    def get_statistics(self) -> dict:
        """Get orchestrator statistics."""
        return {
            "total_crawls": self.state.total_crawls,
            "pending_evaluations": len([o for o in self.pending_outcomes if not o.evaluated]),
            "baseline_informativeness": self.state.baseline_informativeness,
            "bandit_stats": self.bandit.get_statistics() if self.bandit else {},
            "source_rankings": self.bandit.get_exploitation_ranking() if self.bandit else [],
        }


async def run_orchestrator(iterations: int = 10, delay: float = 30.0) -> None:
    """Main entry point for running the orchestrator."""
    from .storage.db import Database

    db = Database()
    await db.connect()

    orchestrator = CrawlerOrchestrator(db)

    try:
        await orchestrator.initialize()
        await orchestrator.run_loop(iterations=iterations, delay_seconds=delay)
    finally:
        await orchestrator.shutdown()
        await db.close()
