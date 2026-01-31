"""
Background scheduler for continuous crawling and belief updates.

Runs the following jobs:
- Price collection: every 5 minutes
- Sentiment crawling: every 12 seconds (Bayesian selection)
- Outcome evaluation: every 15 minutes
- Fear & Greed: every 4 hours
- Causal discovery: weekly
"""

import asyncio
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .collectors import FearGreedCollector, PriceCollector
from .config import settings
from .logging_config import logger
from .orchestrator import CrawlerOrchestrator
from .storage.db import Database


class CrawlerScheduler:
    """
    Background scheduler that orchestrates all crawling jobs.
    """

    def __init__(
        self,
        crawl_interval_seconds: int = 12,        # 12 seconds (10x faster)
        price_interval_seconds: int = 300,       # 5 minutes
        eval_interval_seconds: int = 900,        # 15 minutes
        fear_greed_interval_seconds: int = 14400,  # 4 hours
    ):
        self.crawl_interval = crawl_interval_seconds
        self.price_interval = price_interval_seconds
        self.eval_interval = eval_interval_seconds
        self.fear_greed_interval = fear_greed_interval_seconds

        self.scheduler = AsyncIOScheduler()
        self.db: Database | None = None
        self.orchestrator: CrawlerOrchestrator | None = None
        self.price_collector: PriceCollector | None = None
        self.fear_greed_collector: FearGreedCollector | None = None

        self._running = False
        self._stats = {
            "crawls": 0,
            "price_updates": 0,
            "evaluations": 0,
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

        logger.info("Scheduler initialized")

    async def shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Shutting down scheduler...")
        self._running = False

        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

        if self.orchestrator:
            await self.orchestrator.shutdown()

        if self.price_collector:
            await self.price_collector.close()

        if self.fear_greed_collector:
            await self.fear_greed_collector.close()

        if self.db:
            await self.db.close()

        logger.info("Scheduler shutdown complete")

    async def _job_crawl(self) -> None:
        """Job: Crawl using Bayesian selection."""
        try:
            content = await self.orchestrator.select_and_crawl()
            if content:
                self._stats["crawls"] += 1
        except Exception as e:
            logger.error(f"Crawl job error: {e}")
            self._stats["errors"] += 1

    async def _job_price(self) -> None:
        """Job: Collect price data."""
        try:
            await self.price_collector.run()
            self._stats["price_updates"] += 1
        except Exception as e:
            logger.error(f"Price job error: {e}")
            self._stats["errors"] += 1

    async def _job_evaluate(self) -> None:
        """Job: Evaluate pending outcomes and update beliefs."""
        try:
            evaluated = await self.orchestrator.evaluate_pending_outcomes()
            if evaluated > 0:
                self._stats["evaluations"] += evaluated
                logger.info(f"Evaluated {evaluated} outcomes, updated beliefs")

                # Log current rankings
                rankings = self.orchestrator.bandit.get_exploitation_ranking()
                logger.info("Updated rankings:")
                for source, mean in rankings[:5]:
                    belief = self.orchestrator.belief_store.get(source)
                    logger.info(f"  {source}: {mean:.3f} (n={belief.total_crawls})")

        except Exception as e:
            logger.error(f"Evaluation job error: {e}")
            self._stats["errors"] += 1

    async def _job_fear_greed(self) -> None:
        """Job: Collect Fear & Greed index."""
        try:
            await self.fear_greed_collector.run()
        except Exception as e:
            logger.error(f"Fear & Greed job error: {e}")
            self._stats["errors"] += 1

    async def _job_stats(self) -> None:
        """Job: Log statistics periodically."""
        uptime = datetime.now(timezone.utc) - self._stats["started_at"]
        hours = uptime.total_seconds() / 3600

        logger.info(
            f"📊 Stats | uptime: {hours:.1f}h | "
            f"crawls: {self._stats['crawls']} | "
            f"prices: {self._stats['price_updates']} | "
            f"evals: {self._stats['evaluations']} | "
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

        # Stats job - every 10 minutes
        self.scheduler.add_job(
            self._job_stats,
            IntervalTrigger(seconds=600),
            id="stats",
            name="Statistics",
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
        await self._job_crawl()

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
    crawl_interval: int = 12,
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
    for table in ["sentiment_raw", "sentiment_scores", "price_data"]:
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
    print(f"Scores: {counts['sentiment_scores']}")
    print(f"Prices: {counts['price_data']}")
    if recent:
        print(f"Last crawl: {recent[0]} at {recent[1][:19]}")
    print("=" * 50)


if __name__ == "__main__":
    # Run the scheduler when executed directly
    asyncio.run(run_background_scheduler())
