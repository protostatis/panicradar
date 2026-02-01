"""
Scheduled data collector for continuous sentiment gathering.

Runs multiple backfills on different schedules:
- 4chan /biz/: Every 2 hours (threads expire quickly)
- Stocktwits: Every 4 hours
- Reddit: Every 6 hours
- Bitcointalk: Every 12 hours
- Backtest analysis: Every 24 hours
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .logging_config import logger
from .storage.db import Database


class ScheduledCollector:
    """Manages scheduled data collection jobs."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.db: Database | None = None
        self.stats = {
            "biz_runs": 0,
            "stocktwits_runs": 0,
            "reddit_runs": 0,
            "bitcointalk_runs": 0,
            "backtest_runs": 0,
            "belief_updates": 0,
            "last_run": {},
            "errors": 0,
        }

    async def start(self):
        """Start the scheduler."""
        # Initialize database
        self.db = Database()
        await self.db.connect()

        # Schedule jobs
        self.scheduler.add_job(
            self.run_biz_backfill,
            IntervalTrigger(hours=2),
            id="biz_backfill",
            name="4chan /biz/ backfill",
            next_run_time=datetime.now(timezone.utc),  # Run immediately
        )

        self.scheduler.add_job(
            self.run_stocktwits_backfill,
            IntervalTrigger(hours=4),
            id="stocktwits_backfill",
            name="Stocktwits backfill",
            next_run_time=datetime.now(timezone.utc),
        )

        self.scheduler.add_job(
            self.run_reddit_backfill,
            IntervalTrigger(hours=6),
            id="reddit_backfill",
            name="Reddit backfill",
            # Don't run immediately - let others go first
        )

        self.scheduler.add_job(
            self.run_bitcointalk_backfill,
            IntervalTrigger(hours=12),
            id="bitcointalk_backfill",
            name="Bitcointalk backfill",
        )

        self.scheduler.add_job(
            self.run_backtest,
            IntervalTrigger(hours=24),
            id="daily_backtest",
            name="Daily backtest analysis",
        )

        self.scheduler.add_job(
            self.run_belief_update,
            IntervalTrigger(hours=6),
            id="belief_update",
            name="Bayesian belief update",
        )

        self.scheduler.add_job(
            self.log_status,
            IntervalTrigger(hours=1),
            id="status_log",
            name="Status logger",
        )

        self.scheduler.start()

        logger.info("=" * 60)
        logger.info("SCHEDULED COLLECTOR STARTED")
        logger.info("=" * 60)
        logger.info("Jobs scheduled:")
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name}: {job.trigger}")
        logger.info("=" * 60)

    async def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        if self.db:
            await self.db.close()
        logger.info("Scheduled collector stopped")

    async def run_biz_backfill(self):
        """Run /biz/ backfill."""
        logger.info("[Scheduled] Starting /biz/ backfill...")
        try:
            from .biz_backfill import BizBackfiller

            backfiller = BizBackfiller(self.db)
            await backfiller.initialize()
            stats = await backfiller.run_full_backfill()
            await backfiller.shutdown()

            self.stats["biz_runs"] += 1
            self.stats["last_run"]["biz"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[Scheduled] /biz/ complete: {stats['posts_stored']} posts")

        except Exception as e:
            logger.error(f"[Scheduled] /biz/ error: {e}")
            self.stats["errors"] += 1

    async def run_stocktwits_backfill(self):
        """Run Stocktwits backfill."""
        logger.info("[Scheduled] Starting Stocktwits backfill...")
        try:
            from .stocktwits_backfill import StocktwitsBackfiller

            backfiller = StocktwitsBackfiller(self.db)
            await backfiller.initialize()
            stats = await backfiller.run_full_backfill()
            await backfiller.shutdown()

            self.stats["stocktwits_runs"] += 1
            self.stats["last_run"]["stocktwits"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[Scheduled] Stocktwits complete: {stats['messages_stored']} messages")

        except Exception as e:
            logger.error(f"[Scheduled] Stocktwits error: {e}")
            self.stats["errors"] += 1

    async def run_reddit_backfill(self):
        """Run Reddit backfill (recent posts only)."""
        logger.info("[Scheduled] Starting Reddit backfill...")
        try:
            from .backfill import HistoricalBackfiller

            backfiller = HistoricalBackfiller(self.db)
            await backfiller.initialize()

            # Only fetch recent (week) from top subreddits
            subreddits = ["bitcoin", "cryptocurrency", "ethereum", "solana", "CryptoMarkets"]
            for sub in subreddits:
                await backfiller.backfill_subreddit(sub, pages=2, sort="new", time_filter="week")

            await backfiller.shutdown()

            self.stats["reddit_runs"] += 1
            self.stats["last_run"]["reddit"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[Scheduled] Reddit complete: {backfiller.stats['posts_stored']} posts")

        except Exception as e:
            logger.error(f"[Scheduled] Reddit error: {e}")
            self.stats["errors"] += 1

    async def run_bitcointalk_backfill(self):
        """Run Bitcointalk backfill."""
        logger.info("[Scheduled] Starting Bitcointalk backfill...")
        try:
            from .bitcointalk_backfill import BitcointalkBackfiller

            backfiller = BitcointalkBackfiller(self.db)
            await backfiller.initialize()
            stats = await backfiller.run_full_backfill()
            await backfiller.shutdown()

            self.stats["bitcointalk_runs"] += 1
            self.stats["last_run"]["bitcointalk"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[Scheduled] Bitcointalk complete: {stats['posts_stored']} posts")

        except Exception as e:
            logger.error(f"[Scheduled] Bitcointalk error: {e}")
            self.stats["errors"] += 1

    async def run_backtest(self):
        """Run daily backtest analysis."""
        logger.info("[Scheduled] Running daily backtest...")
        try:
            from .analysis.backtest_analysis import SentimentPriceAnalyzer, print_analysis_report

            analyzer = SentimentPriceAnalyzer()
            results = await analyzer.run_full_analysis()

            # Log summary
            best_corr = max(results["correlations"], key=lambda x: abs(x.correlation))
            logger.info(f"[Backtest] Best correlation: r={best_corr.correlation:+.4f} at {best_corr.lag_hours}h lag")

            # Check for significant findings
            significant = [c for c in results["correlations"] if c.is_significant]
            if significant:
                logger.info(f"[Backtest] {len(significant)} significant correlations found!")

            self.stats["backtest_runs"] += 1
            self.stats["last_run"]["backtest"] = datetime.now(timezone.utc).isoformat()

            # Save results to file
            results_file = Path("data/backtest_results.log")
            with open(results_file, "a") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"Backtest Run: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"Best correlation: r={best_corr.correlation:+.4f} at {best_corr.lag_hours}h lag\n")
                f.write(f"Significant: {len(significant)}\n")
                f.write(f"{'=' * 60}\n")

        except Exception as e:
            logger.error(f"[Scheduled] Backtest error: {e}")
            self.stats["errors"] += 1

    async def run_belief_update(self):
        """Update Bayesian beliefs based on observed performance."""
        logger.info("[Scheduled] Updating Bayesian beliefs...")
        try:
            from .analysis.belief_updater import update_orchestrator_beliefs

            updated = await update_orchestrator_beliefs()

            self.stats["belief_updates"] += 1
            self.stats["last_run"]["belief_update"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"[Scheduled] Beliefs updated: {len(updated)} sources")

            # Log top sources
            sorted_beliefs = sorted(
                [(s, b) for s, b in updated.items() if 'accuracy' in b],
                key=lambda x: x[1].get('accuracy', 0),
                reverse=True
            )
            for source, belief in sorted_beliefs[:3]:
                logger.info(
                    f"  Top: {source} - accuracy={belief['accuracy']:.1%}, "
                    f"contrarian={belief.get('is_contrarian', False)}"
                )

        except Exception as e:
            logger.error(f"[Scheduled] Belief update error: {e}")
            self.stats["errors"] += 1

    async def log_status(self):
        """Log current status."""
        # Get database counts
        cursor = await self.db.conn.execute("SELECT COUNT(*) FROM sentiment_raw")
        raw_count = (await cursor.fetchone())[0]

        cursor = await self.db.conn.execute("SELECT COUNT(*) FROM sentiment_scores")
        score_count = (await cursor.fetchone())[0]

        logger.info(
            f"[Status] Posts: {raw_count:,} | Scores: {score_count:,} | "
            f"Runs - biz:{self.stats['biz_runs']} stocktwits:{self.stats['stocktwits_runs']} "
            f"reddit:{self.stats['reddit_runs']} | Errors: {self.stats['errors']}"
        )


async def run_scheduled_collector():
    """Main entry point."""
    collector = ScheduledCollector()

    try:
        await collector.start()

        # Keep running
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await collector.stop()


if __name__ == "__main__":
    asyncio.run(run_scheduled_collector())
