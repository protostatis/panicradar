"""
Orchestrator: Integrates Bayesian selection → Crawler → Belief updates.

This is the main loop that ties the decision layer to the execution layer.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bayesian import CrawlBandit, GPBandit, SourceBeliefStore, UtilityScorer
from .bayesian.cold_start import compute_baseline_informativeness, initialize_source_belief
from .bayesian.feature_extraction import SourceFeatureExtractor
from .bayesian.gp_model import GPSourceModel
from .causal import GrangerAnalyzer
from .crawler import ContentPipeline, Fetcher
from .crawler.pipeline import CrawledContent, RedditPipeline
from .crawler.sources import DEFAULT_SOURCES, SourceConfig, get_all_sources
from .logging_config import logger
from .processing.user_sentiment import MIN_HUMAN_COMMENTS, UserSentimentScorer, count_human_comments
from .storage.db import Database
from .storage.models import PriceData, SentimentRaw


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
    last_belief_update: str | None = None
    total_crawls: int = 0

    # GP state
    gp_hyperparameters: dict | None = None
    gp_scaler_params: dict | None = None
    last_gp_fit: str | None = None

    def to_dict(self) -> dict:
        d = {
            "beliefs": self.beliefs,
            "baseline_informativeness": self.baseline_informativeness,
            "last_causal_update": self.last_causal_update,
            "last_belief_update": self.last_belief_update,
            "total_crawls": self.total_crawls,
        }
        if self.gp_hyperparameters is not None:
            d["gp_state"] = {
                "hyperparameters": self.gp_hyperparameters,
                "scaler_params": self.gp_scaler_params,
                "last_gp_fit": self.last_gp_fit,
            }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "OrchestratorState":
        gp = data.get("gp_state", {})
        return cls(
            beliefs=data.get("beliefs", {}),
            baseline_informativeness=data.get("baseline_informativeness", 0.5),
            last_causal_update=data.get("last_causal_update"),
            last_belief_update=data.get("last_belief_update"),
            total_crawls=data.get("total_crawls", 0),
            gp_hyperparameters=gp.get("hyperparameters"),
            gp_scaler_params=gp.get("scaler_params"),
            last_gp_fit=gp.get("last_gp_fit"),
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
        # Load discovered sources if none provided
        self.sources = sources or get_all_sources(include_discovered=True)
        self.state_path = Path(state_path)
        self.eval_lag_hours = eval_lag_hours

        # Log which sources are loaded
        logger.info(f"Orchestrator initialized with {len(self.sources)} sources:")
        for source_name in sorted(self.sources.keys()):
            logger.info(f"  - {source_name}")

        # Components
        self.belief_store = SourceBeliefStore()
        self.bandit: CrawlBandit | None = None
        self.utility_scorer = UtilityScorer()
        self.granger = GrangerAnalyzer()

        # GP components
        self.gp_model: GPSourceModel | None = None
        self.feature_extractor = SourceFeatureExtractor(db_path=str(db.db_path))
        self._gp_eval_counter = 0
        self._belief_lock = asyncio.Lock()  # Guards belief_store modifications

        # Crawlers
        self.fetcher = Fetcher()
        self.pipeline: ContentPipeline | None = None
        self.reddit_pipeline: RedditPipeline | None = None

        # User sentiment scorer for multi-dimensional scoring
        self.user_scorer = UserSentimentScorer(db_path=str(db.db_path))

        # State
        self.state = OrchestratorState()
        self.pending_outcomes: list[CrawlOutcome] = []

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing orchestrator...")

        # Load or create state
        await self._load_state()

        # Initialize beliefs for all sources
        await self._initialize_beliefs()

        # Try to set up GP-enhanced bandit
        bandit = await self._try_init_gp_bandit()
        self.bandit = bandit or CrawlBandit(self.belief_store)

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

                # Restore GP hyperparameters if present
                if self.state.gp_hyperparameters:
                    self.gp_model = GPSourceModel(
                        **self.state.gp_hyperparameters
                    )
                    if self.state.gp_scaler_params:
                        self.feature_extractor.scaler_params = self.state.gp_scaler_params
                    logger.info("Restored GP hyperparameters from state")

                logger.info(f"Loaded state: {self.state.total_crawls} total crawls")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")

    async def _save_state(self) -> None:
        """Save state to disk."""
        self.state.beliefs = self.belief_store.to_dict()

        # Save GP state if available
        if self.gp_model is not None:
            gp_dict = self.gp_model.to_dict()
            self.state.gp_hyperparameters = gp_dict.get("hyperparameters")
            self.state.gp_scaler_params = self.feature_extractor.scaler_params

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

    async def apply_belief_snapshot(self, belief_data: dict) -> None:
        """Atomically apply a belief snapshot from the scheduled batch updater.

        Args:
            belief_data: Dict of source -> belief-serialized dict, as produced
                         by the scheduled belief updater.
        """
        async with self._belief_lock:
            # Preserve source status fields that only the orchestrator manages
            for source, new_data in belief_data.items():
                existing = self.belief_store.beliefs.get(source)
                if existing:
                    new_data["status"] = existing.status
                    new_data["last_success_at"] = (
                        existing.last_success_at.isoformat()
                        if existing.last_success_at else None
                    )
                    new_data["first_empty_at"] = (
                        existing.first_empty_at.isoformat()
                        if existing.first_empty_at else None
                    )
                    new_data["next_probe_at"] = (
                        existing.next_probe_at.isoformat()
                        if existing.next_probe_at else None
                    )
                    new_data["consecutive_empty_crawls"] = existing.consecutive_empty_crawls

            new_store = SourceBeliefStore.from_dict(belief_data)
            self.belief_store.beliefs = new_store.beliefs
            self.state.beliefs = belief_data
            self.state.last_belief_update = datetime.now(timezone.utc).isoformat()

            if isinstance(self.bandit, GPBandit):
                await self._refit_gp()

            logger.info(
                f"Applied belief snapshot: {len(belief_data)} sources"
            )

    async def _try_init_gp_bandit(self) -> GPBandit | None:
        """Try to initialize a GPBandit. Returns None if not enough data."""
        try:
            raw_features = await self.feature_extractor.extract_features(self.db)
            if len(raw_features) < GPBandit.MIN_GP_ELIGIBLE:
                logger.info(
                    f"Only {len(raw_features)} sources with features, "
                    f"need {GPBandit.MIN_GP_ELIGIBLE} for GP. Using independent Beta."
                )
                return None

            features = self.feature_extractor.standardize_features(raw_features)

            if self.gp_model is None:
                self.gp_model = GPSourceModel()

            bandit = GPBandit(
                self.belief_store,
                gp_model=self.gp_model,
                features=features,
            )

            if bandit.update_gp(features):
                self.state.last_gp_fit = datetime.now(timezone.utc).isoformat()
                logger.info(
                    f"GP bandit active with {len(features)} sources"
                )
                return bandit

            logger.info("GP fit failed, using independent Beta")
            return None

        except Exception as e:
            logger.warning(f"Could not initialize GP bandit: {e}")
            return None

    async def _refit_gp(self) -> None:
        """Refit GP model with current beliefs and fresh features."""
        if not isinstance(self.bandit, GPBandit):
            return

        try:
            raw_features = await self.feature_extractor.extract_features(self.db)
            if len(raw_features) < GPBandit.MIN_GP_ELIGIBLE:
                return

            features = self.feature_extractor.standardize_features(raw_features)

            # Optimize hyperparameters
            eligible = []
            alphas = []
            betas = []
            for source, sf in features.items():
                belief = self.belief_store.get(source)
                if belief.total_crawls >= GPBandit.MIN_OBSERVATIONS:
                    eligible.append(sf)
                    alphas.append(belief.alpha)
                    betas.append(belief.beta)

            if len(eligible) >= GPBandit.MIN_GP_ELIGIBLE:
                import numpy as np
                result = self.gp_model.optimize_hyperparameters(
                    eligible, np.array(alphas), np.array(betas)
                )
                if result.get("converged"):
                    logger.info(
                        f"GP hyperparameters optimized: "
                        f"l={self.gp_model.length_scale:.3f}, "
                        f"sf={self.gp_model.signal_variance:.3f}"
                    )

            self.bandit.update_gp(features)
            self.state.last_gp_fit = datetime.now(timezone.utc).isoformat()
            logger.info("GP model refitted")
        except Exception as e:
            logger.warning(f"GP refit failed: {e}")

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

    async def _get_current_price(self, coin: str = "BTC") -> PriceData | None:
        """Get current price for a coin, always fetching from DB.

        Returns:
            PriceData record with timestamp, or None if unavailable.
            Logs a warning if price is older than 10 minutes.
        """
        prices = await self.db.get_latest_prices(coin, limit=1)
        if prices:
            price_data = prices[0]
            age_seconds = (datetime.now(timezone.utc) - price_data.timestamp).total_seconds()
            if age_seconds > 600:  # 10 minutes
                logger.warning(
                    f"Stale price for {coin}: {age_seconds / 60:.1f} minutes old"
                )
            return price_data
        return None

    async def select_and_crawl(self) -> list[CrawledContent]:
        """
        Main loop iteration:
        1. Select source using Thompson Sampling
        2. Crawl the selected source
        3. Store ALL content and queue for evaluation

        Returns list of all crawled content.
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

        # Crawl based on source type - get ALL posts
        contents = await self._crawl_source_batch(source_name, source_config)

        if not contents:
            # Penalize empty crawl so the bandit learns to avoid dry sources
            belief = self.belief_store.get(source_name)
            was_probe = (belief.status == "inactive")
            belief.record_empty_crawl(penalty=0.3)
            logger.info(
                f"Empty crawl from {source_name} "
                f"(consecutive={belief.consecutive_empty_crawls}, "
                f"mean={belief.mean:.3f}{', probe' if was_probe else ''})"
            )
            # Mark source inactive after 24h of continuous empty crawls
            if (belief.status == "active"
                    and belief.first_empty_at is not None
                    and belief.consecutive_empty_crawls >= 6):
                hours_empty = (
                    datetime.now(timezone.utc) - belief.first_empty_at
                ).total_seconds() / 3600
                if hours_empty >= 24:
                    belief.status = "inactive"
                    belief.next_probe_at = (
                        datetime.now(timezone.utc) + timedelta(hours=24)
                    )
                    logger.warning(
                        f"Source {source_name} marked inactive after "
                        f"{belief.consecutive_empty_crawls} empty crawls over "
                        f"{hours_empty:.1f}h. Next probe at {belief.next_probe_at}."
                    )
            # Reschedule probe after failed inactive-source probe
            elif was_probe:
                belief.next_probe_at = (
                    datetime.now(timezone.utc) + timedelta(hours=24)
                )
                logger.info(
                    f"Probe of inactive source {source_name} was empty. "
                    f"Next probe at {belief.next_probe_at}."
                )
            return []

        # Successful crawl — reset empty counter via dedicated method
        belief = self.belief_store.get(source_name)
        belief.record_successful_crawl()

        # Get current price for later evaluation
        price_data = await self._get_current_price("BTC")
        price = price_data.price_usd if price_data else 0.0
        stored_count = 0

        for content in contents:
            # Store to database (returns 0 if filtered or duplicate)
            raw_id = await self._store_content(content)

            if raw_id > 0:
                stored_count += 1
                self.state.total_crawls += 1

                # Queue first stored post for belief evaluation
                if stored_count == 1:
                    outcome = CrawlOutcome(
                        content=content,
                        price_at_crawl=price,
                        timestamp=datetime.now(timezone.utc),
                    )
                    self.pending_outcomes.append(outcome)

            # Compute immediate novelty (for all crawled content)
            text = content.content or content.title or ""
            self.utility_scorer.compute_novelty_only(text, add_to_recent=True)

        # Log summary
        if contents:
            logger.info(f"Stored {stored_count}/{len(contents)} posts from {source_name}")

        return contents

    async def _crawl_source_batch(
        self,
        source_name: str,
        source_config: SourceConfig,
        mode: str = "inference",
    ) -> list[CrawledContent]:
        """
        Crawl a specific source and return ALL posts.

        Args:
            source_name: Source identifier
            source_config: Source configuration
            mode: "inference" for fresh posts (last 24 hours), "training" for all posts

        Returns:
            List of all crawled content
        """
        try:
            if source_name.startswith("reddit_"):
                # Reddit crawling
                subreddit = source_name.replace("reddit_", "")

                # Inference mode: recent posts, sorted by new
                # Training mode: all posts, sorted by hot for engagement
                if mode == "inference":
                    posts = await self.reddit_pipeline.crawl_subreddit(
                        subreddit,
                        sort="new",
                        limit=25,  # Fetch more posts
                        max_age_hours=24.0,  # Posts from last 24 hours (was 4)
                        fetch_content=True,  # Fetch full thread + comments
                        max_comments=10,
                    )
                    if posts:
                        # Sort by timestamp (most recent first)
                        posts.sort(
                            key=lambda p: (
                                p.published_at or p.crawled_at,
                                p.metadata.get("score", 0),
                            ),
                            reverse=True,
                        )
                        return posts  # Return ALL posts
                    else:
                        logger.warning(f"No fresh posts (<24h old) found in r/{subreddit}")
                        return []
                else:
                    # Training mode: get popular historical posts
                    posts = await self.reddit_pipeline.crawl_subreddit(
                        subreddit,
                        sort="hot",
                        limit=25,
                        max_age_hours=None,  # No age filter
                        fetch_content=True,
                        max_comments=15,
                    )
                    return posts or []

            else:
                # Generic web crawling - returns single item as list
                url = source_config.get_url()
                selectors = source_config.get_selectors()
                result = await self.pipeline.process_url(
                    url,
                    source_name,
                    selectors,
                    source_config.rate_limit,
                )
                return [result] if result else []

        except Exception as e:
            logger.error(f"Crawl failed for {source_name}: {e}")
            return []

    async def _crawl_source(
        self,
        source_name: str,
        source_config: SourceConfig,
        mode: str = "inference",
    ) -> CrawledContent | None:
        """Legacy single-post crawl (for backward compatibility)."""
        posts = await self._crawl_source_batch(source_name, source_config, mode)
        return posts[0] if posts else None

    async def _store_content(self, content: CrawledContent) -> int:
        """Store crawled content to database and compute user-based sentiment score.

        Returns the raw_id (0 if duplicate or skipped due to low engagement).
        """
        metadata = content.metadata or {}

        # Skip posts with insufficient human comments (don't save to raw)
        human_comments = count_human_comments(metadata)
        if human_comments < MIN_HUMAN_COMMENTS:
            logger.debug(
                f"Skipping {content.source}: only {human_comments} human comments "
                f"(min: {MIN_HUMAN_COMMENTS})"
            )
            return 0

        # Store raw
        raw_data = {
            "url": content.url,
            "title": content.title,
            "content": (content.content or "")[:1000] if content.content else None,
            "author": content.author,
            "metadata": metadata,
        }
        raw = SentimentRaw(
            timestamp=content.published_at or content.crawled_at,
            source=content.source,
            coin=content.coins_mentioned[0] if content.coins_mentioned else None,
            raw_data=raw_data,
        )
        raw_id = await self.db.insert_sentiment_raw(raw)

        # Skip if duplicate (raw_id=0)
        if raw_id == 0:
            return 0

        # Score with user-based sentiment scorer (multi-dimensional)
        coin = content.coins_mentioned[0] if content.coins_mentioned else None
        post_timestamp = content.published_at or content.crawled_at
        try:
            post_score = self.user_scorer.score_post(
                raw_data=raw_data,
                raw_id=raw_id,
                timestamp=post_timestamp.isoformat(),
                source=content.source,
                coin=coin,
            )
            if post_score:
                score_id = self.user_scorer.save_post_score(post_score)
                # Write score back to content for later belief evaluation
                content.sentiment_score = post_score.final_score
                if score_id > 0:
                    # Update user profile
                    user_id = self.user_scorer.get_or_create_user(
                        post_score.username, post_score.source, post_score.timestamp
                    )
                    self.user_scorer.update_user_profile(user_id)
                    logger.debug(
                        f"User scored: {content.source} final={post_score.final_score:.3f} "
                        f"fear={post_score.fear_index:.2f} euphoria={post_score.euphoria_index:.2f}"
                    )
        except Exception as e:
            logger.warning(f"User scoring failed for {content.source}: {e}")

        return raw_id

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
        price_data = await self._get_current_price("BTC")
        current_price = price_data.price_usd if price_data else 0.0

        for outcome in self.pending_outcomes:
            if outcome.evaluated:
                continue

            # Check if enough time has passed
            hours_elapsed = (now - outcome.timestamp).total_seconds() / 3600
            if hours_elapsed < self.eval_lag_hours:
                continue

            # Skip if sentiment was never scored (e.g. scoring failed)
            if outcome.content.sentiment_score is None:
                outcome.evaluated = True
                continue

            # Compute utility (for monitoring/diagnostics only — does NOT modify beliefs)
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

        # Refit GP periodically
        if evaluated_count > 0:
            self._gp_eval_counter += evaluated_count
            if self._gp_eval_counter >= 50:
                await self._refit_gp()
                self._gp_eval_counter = 0

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
        delay_seconds: float = 15.0,
    ) -> None:
        """
        Run the main crawl loop.

        Args:
            iterations: Number of crawl iterations (0 for infinite)
            delay_seconds: Delay between iterations (default 15s)
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


async def run_orchestrator(iterations: int = 10, delay: float = 15.0) -> None:
    """
    Main entry point for running the orchestrator.

    Args:
        iterations: Number of crawl iterations (0 for infinite)
        delay: Delay between iterations in seconds (default 15s)
    """
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
