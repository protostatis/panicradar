"""
Background scheduler for continuous crawling and belief updates.

Runs the following jobs:
- Price collection: every 5 minutes
- Sentiment crawling: every 20 seconds (Bayesian selection, fetches full threads)
- Outcome evaluation: every 15 minutes
- Fear & Greed: every 4 hours
- Confounder collection: every 15 minutes (for causal inference)
- Belief update & source weights sync: every 30 minutes
- Source discovery: weekly (finds new crypto subreddits)
"""

import asyncio
import signal
import sys
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .collectors import FearGreedCollector, OnChainFreeCollector, PriceCollector
from .config import settings
from .confounders import ConfounderCollector
from .crawler.sources import get_all_sources
from .logging_config import logger
from .orchestrator import CrawlerOrchestrator
from .storage.db import Database


def _tracked_job(job):
    """Track a scheduler job so shutdown can drain it without cancellation."""

    @wraps(job)
    async def wrapped(self, *args, **kwargs):
        if self._shutting_down:
            return None

        task = asyncio.current_task()
        if task is not None:
            self._active_jobs.add(task)
            self._jobs_idle.clear()
        try:
            return await job(self, *args, **kwargs)
        finally:
            if task is not None:
                self._active_jobs.discard(task)
                if not self._active_jobs:
                    self._jobs_idle.set()

    return wrapped


class CrawlerScheduler:
    """
    Background scheduler that orchestrates all crawling jobs.
    """

    def __init__(
        self,
        crawl_interval_seconds: int = 20,        # 20 seconds (fetching full threads is slower)
        price_interval_seconds: int = 300,       # 5 minutes
        eval_interval_seconds: int = 900,        # 15 minutes
        fear_greed_interval_seconds: int = 14400,  # 4 hours
        confounder_interval_seconds: int = 900,  # 15 minutes (for causal inference)
        onchain_interval_seconds: int = 900,     # 15 minutes (on-chain metrics)
    ):
        self.crawl_interval = crawl_interval_seconds
        self.price_interval = price_interval_seconds
        self.eval_interval = eval_interval_seconds
        self.fear_greed_interval = fear_greed_interval_seconds
        self.confounder_interval = confounder_interval_seconds
        self.onchain_interval = onchain_interval_seconds

        self.scheduler = AsyncIOScheduler()
        self.db: Database | None = None
        self.orchestrator: CrawlerOrchestrator | None = None
        self.price_collector: PriceCollector | None = None
        self.fear_greed_collector: FearGreedCollector | None = None
        self.confounder_collector: ConfounderCollector | None = None
        self.onchain_collector: OnChainFreeCollector | None = None

        self._running = False
        self._shutting_down = False
        self._crawl_job_lock = asyncio.Lock()
        self._evaluation_job_lock = asyncio.Lock()
        self._belief_update_lock = asyncio.Lock()
        self._active_jobs: set[asyncio.Task] = set()
        self._jobs_idle = asyncio.Event()
        self._jobs_idle.set()
        self._stats = {
            "crawls": 0,
            "price_updates": 0,
            "evaluations": 0,
            "confounder_snapshots": 0,
            "onchain_updates": 0,
            "discoveries": 0,
            "belief_updates": 0,
            "errors": 0,
            "started_at": None,
        }

    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing scheduler...")

        # Database
        self.db = Database()
        await self.db.connect()

        # Orchestrator
        self.orchestrator = CrawlerOrchestrator(self.db)
        await self.orchestrator.initialize()

        # Collectors
        self.price_collector = PriceCollector(self.db)
        self.fear_greed_collector = FearGreedCollector(self.db)
        self.confounder_collector = ConfounderCollector()
        await self.confounder_collector.start()
        self.onchain_collector = OnChainFreeCollector(self.db)

        logger.info("Scheduler initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Shutting down scheduler...")
        self._running = False
        self._shutting_down = True

        if self.scheduler.running:
            self.scheduler.pause()

        # Do not let AsyncIOScheduler cancel jobs while they hold the database
        # or an orchestrator lock; paused scheduling prevents new work.
        await self._jobs_idle.wait()

        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

        if self.orchestrator:
            await self.orchestrator.shutdown()

        if self.price_collector:
            await self.price_collector.close()

        if self.fear_greed_collector:
            await self.fear_greed_collector.close()

        if self.confounder_collector:
            await self.confounder_collector.close()

        if self.onchain_collector:
            await self.onchain_collector.close()

        if self.db:
            await self.db.close()

        logger.info("Scheduler shutdown complete")

    async def _record_heartbeat(
        self,
        component: str,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """Record a pipeline heartbeat in the database."""
        try:
            if self.db:
                await self.db.record_heartbeat(
                    component=component,
                    success=success,
                    error_message=error_message,
                )
        except Exception as e:
            logger.debug(f"Failed to record heartbeat for {component}: {e}")

    @_tracked_job
    async def _job_crawl(self) -> None:
        """Job: Crawl using Bayesian selection."""
        if self._shutting_down:
            return

        async with self._crawl_job_lock:
            if self._shutting_down:
                return
            await self._run_crawl_job()

    async def _run_crawl_job(self) -> None:
        """Run the serialized crawl job."""
        try:
            content = await self.orchestrator.select_and_crawl()
            if content:
                self._stats["crawls"] += 1
            await self._record_heartbeat("crawl", success=True)
        except Exception as e:
            logger.error(f"Crawl job error: {e}")
            self._stats["errors"] += 1
            await self._record_heartbeat("crawl", success=False, error_message=str(e))

    @_tracked_job
    async def _job_price(self) -> None:
        """Job: Collect price data."""
        try:
            await self.price_collector.run()
            self._stats["price_updates"] += 1
            await self._record_heartbeat("price", success=True)
        except Exception as e:
            logger.error(f"Price job error: {e}")
            self._stats["errors"] += 1
            await self._record_heartbeat("price", success=False, error_message=str(e))

    @_tracked_job
    async def _job_evaluate(self) -> None:
        """Job: Evaluate pending outcomes and update beliefs."""
        if self._shutting_down:
            return

        async with self._evaluation_job_lock:
            if self._shutting_down:
                return
            await self._run_evaluation_job()

    async def _run_evaluation_job(self) -> None:
        """Run the serialized outcome evaluation job."""
        try:
            evaluated = await self.orchestrator.evaluate_pending_outcomes()
            if evaluated > 0:
                self._stats["evaluations"] += evaluated
                logger.info(f"Evaluated {evaluated} outcomes, updated beliefs")

                # Save state with updated beliefs and timestamp
                self.orchestrator.state.last_belief_update = (
                    datetime.now(timezone.utc).isoformat()
                )
                await self.orchestrator._save_state()

                # Log current rankings
                rankings = self.orchestrator.bandit.get_exploitation_ranking()
                logger.info("Updated rankings:")
                for source, mean in rankings[:5]:
                    belief = self.orchestrator.belief_store.get(source)
                    logger.info(f"  {source}: {mean:.3f} (n={belief.total_crawls})")

            await self._record_heartbeat("eval", success=True)
        except Exception as e:
            logger.error(f"Evaluation job error: {e}")
            self._stats["errors"] += 1
            await self._record_heartbeat("eval", success=False, error_message=str(e))

    @_tracked_job
    async def _job_fear_greed(self) -> None:
        """Job: Collect Fear & Greed index."""
        try:
            await self.fear_greed_collector.run()
        except Exception as e:
            logger.error(f"Fear & Greed job error: {e}")
            self._stats["errors"] += 1

    @_tracked_job
    async def _job_confounders(self) -> None:
        """Job: Collect confounder variables for causal inference."""
        try:
            snapshot = await self.confounder_collector.collect_and_store()
            self._stats["confounder_snapshots"] += 1
            logger.debug(
                f"Confounder snapshot: FNG={snapshot.fear_greed_index}, "
                f"VIX={snapshot.vix_level}, errors={len(snapshot.collection_errors)}"
            )
        except Exception as e:
            logger.error(f"Confounder job error: {e}")
            self._stats["errors"] += 1

    @_tracked_job
    async def _job_onchain(self) -> None:
        """Job: Collect on-chain metrics from free APIs."""
        try:
            await self.onchain_collector.collect()
            self._stats["onchain_updates"] += 1
        except Exception as e:
            logger.error(f"On-chain job error: {e}")
            self._stats["errors"] += 1

    @_tracked_job
    async def _job_belief_update(self) -> None:
        """Job: Recompute source accuracy, sync source_weights, and reload live bandit."""
        if self._shutting_down:
            return

        async with self._belief_update_lock:
            if self._shutting_down:
                return
            await self._run_belief_update()

    async def _run_belief_update(self) -> None:
        """Run the serialized belief snapshot update."""
        try:
            from .analysis.belief_updater import update_orchestrator_beliefs

            if self.orchestrator:
                for attempt in range(3):
                    base_beliefs, revision = await self.orchestrator.snapshot_beliefs()
                    updated_beliefs = await update_orchestrator_beliefs(
                        db_path=str(self.orchestrator.db.db_path),
                        base_beliefs=base_beliefs,
                        persist_state=False,
                    )
                    applied_version = await self.orchestrator.apply_belief_snapshot(
                        updated_beliefs,
                        expected_revision=revision,
                    )
                    if applied_version is not None:
                        break
                    logger.info(
                        "Belief snapshot changed during update; retrying (%d/3)",
                        attempt + 1,
                    )
                else:
                    logger.warning("Skipped belief update after repeated concurrent changes")
                    return
            else:
                # Preserve standalone scheduler/CLI behavior for tests and
                # callers that do not own an initialized orchestrator.
                await update_orchestrator_beliefs()
            self._stats["belief_updates"] += 1
            logger.info("Belief update, source_weights sync, and bandit reload complete")
            await self._record_heartbeat("belief_update", success=True)
        except Exception as e:
            logger.error(f"Belief update job error: {e}")
            self._stats["errors"] += 1
            await self._record_heartbeat("belief_update", success=False, error_message=str(e))

    @_tracked_job
    async def _job_discovery(self) -> None:
        """Job: Discover new crypto subreddits (weekly)."""
        try:
            from .discovery.manager import SourceManager

            logger.info("Starting weekly source discovery...")

            async with SourceManager() as manager:
                # Run discovery
                await manager.run_discovery()

                # Evaluate candidates
                results = await manager.evaluate_candidates(limit=30)

                # Process and categorize
                summary = await manager.process_evaluations(results)

                added = len(summary.get("added", []))
                monitoring = len(summary.get("monitoring", []))
                rejected = len(summary.get("rejected", []))

                logger.info(
                    f"Discovery complete: {added} added, "
                    f"{monitoring} monitoring, {rejected} rejected"
                )

                # Reload sources in orchestrator if new ones were added
                if added > 0:
                    new_sources = get_all_sources(include_discovered=True)
                    # Add new sources to orchestrator
                    for name, config in new_sources.items():
                        if name not in self.orchestrator.sources:
                            self.orchestrator.sources[name] = config
                            logger.info(f"Added new source to orchestrator: {name}")

                self._stats["discoveries"] += 1

        except Exception as e:
            logger.error(f"Discovery job error: {e}")
            self._stats["errors"] += 1

    @_tracked_job
    async def _job_stats(self) -> None:
        """Job: Log statistics periodically."""
        uptime = datetime.now(timezone.utc) - self._stats["started_at"]
        hours = uptime.total_seconds() / 3600

        logger.info(
            f"Stats | uptime: {hours:.1f}h | "
            f"crawls: {self._stats['crawls']} | "
            f"prices: {self._stats['price_updates']} | "
            f"evals: {self._stats['evaluations']} | "
            f"discoveries: {self._stats['discoveries']} | "
            f"belief_updates: {self._stats['belief_updates']} | "
            f"errors: {self._stats['errors']}"
        )

    def _setup_jobs(self) -> None:
        """Configure scheduled jobs."""
        # Crawl job - most frequent
        self.scheduler.add_job(
            self._job_crawl,
            IntervalTrigger(seconds=self.crawl_interval),
            id="crawl",
            name="Bayesian Crawl",
            max_instances=1,
        )

        # Price job
        self.scheduler.add_job(
            self._job_price,
            IntervalTrigger(seconds=self.price_interval),
            id="price",
            name="Price Collection",
            max_instances=1,
        )

        # Evaluation job
        self.scheduler.add_job(
            self._job_evaluate,
            IntervalTrigger(seconds=self.eval_interval),
            id="evaluate",
            name="Outcome Evaluation",
            max_instances=1,
        )

        # Fear & Greed job
        self.scheduler.add_job(
            self._job_fear_greed,
            IntervalTrigger(seconds=self.fear_greed_interval),
            id="fear_greed",
            name="Fear & Greed",
            max_instances=1,
        )

        # Confounder collection job (for causal inference)
        self.scheduler.add_job(
            self._job_confounders,
            IntervalTrigger(seconds=self.confounder_interval),
            id="confounders",
            name="Confounder Collection",
            max_instances=1,
        )

        # On-chain metrics job
        self.scheduler.add_job(
            self._job_onchain,
            IntervalTrigger(seconds=self.onchain_interval),
            id="onchain",
            name="On-Chain Metrics",
            max_instances=1,
        )

        # Belief update + source_weights sync - every 30 minutes
        self.scheduler.add_job(
            self._job_belief_update,
            IntervalTrigger(seconds=1800),
            id="belief_update",
            name="Belief Update & Weights Sync",
            max_instances=1,
        )

        # Stats job - every 10 minutes
        self.scheduler.add_job(
            self._job_stats,
            IntervalTrigger(seconds=600),
            id="stats",
            name="Statistics",
            max_instances=1,
        )

        # Source discovery job - weekly on Sunday at 3 AM UTC
        self.scheduler.add_job(
            self._job_discovery,
            CronTrigger(day_of_week="sun", hour=3, minute=0),
            id="discovery",
            name="Source Discovery",
            max_instances=1,
        )

    async def run(self) -> None:
        """Run the scheduler (blocking)."""
        await self.initialize()

        self._setup_jobs()
        self._stats["started_at"] = datetime.now(timezone.utc)
        self._running = True

        # Run initial jobs immediately
        logger.info("Running initial collection...")
        await self._job_price()
        await self._job_fear_greed()
        await self._job_confounders()
        await self._job_onchain()
        await self._job_crawl()
        await self._job_belief_update()

        logger.info(
            f"Starting scheduler with intervals: "
            f"crawl={self.crawl_interval}s, "
            f"price={self.price_interval}s, "
            f"eval={self.eval_interval}s"
        )

        self.scheduler.start()

        # Keep running until interrupted
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        await self.shutdown()

    def get_stats(self) -> dict:
        """Get current statistics."""
        stats = dict(self._stats)
        if stats["started_at"]:
            uptime = datetime.now(timezone.utc) - stats["started_at"]
            stats["uptime_seconds"] = uptime.total_seconds()
            stats["started_at"] = stats["started_at"].isoformat()
        return stats


async def run_background_scheduler(
    crawl_interval: int = 20,
    price_interval: int = 300,
    eval_interval: int = 900,
) -> None:
    """
    Run the background scheduler.

    This function blocks and runs until interrupted (Ctrl+C).
    """
    scheduler = CrawlerScheduler(
        crawl_interval_seconds=crawl_interval,
        price_interval_seconds=price_interval,
        eval_interval_seconds=eval_interval,
    )

    # Handle signals for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        scheduler._running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await scheduler.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await scheduler.shutdown()


# Quick stats viewer
async def view_live_stats() -> None:
    """View current stats from the database."""
    import sqlite3
    import json

    db_path = Path("data/sentiment.db")
    state_path = Path("data/orchestrator_state.json")

    if not db_path.exists():
        print("No database found. Run the scheduler first.")
        return

    conn = sqlite3.connect(db_path)

    # Counts
    counts = {}
    for table in ["sentiment_raw", "user_sentiment_scores", "price_data"]:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    # Recent activity
    recent = conn.execute("""
        SELECT source, timestamp
        FROM sentiment_raw
        ORDER BY created_at DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    # State
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
    else:
        state = {}

    print("\n📊 LIVE STATS")
    print("=" * 50)
    print(f"Total crawls: {state.get('total_crawls', 0)}")
    print(f"Raw records: {counts['sentiment_raw']}")
    print(f"User scores: {counts['user_sentiment_scores']}")
    print(f"Prices: {counts['price_data']}")
    if recent:
        print(f"Last crawl: {recent[0]} at {recent[1][:19]}")
    print("=" * 50)


if __name__ == "__main__":
    # Run the scheduler when executed directly
    asyncio.run(run_background_scheduler())
