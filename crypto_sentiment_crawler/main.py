"""Main entry point for the crypto sentiment crawler."""

import argparse
import asyncio

from .collectors import FearGreedCollector, OnChainCollector, PriceCollector, RedditCollector
from .config import settings
from .logging_config import logger
from .orchestrator import CrawlerOrchestrator
from .scheduler import run_background_scheduler, view_live_stats
from .storage.db import Database


async def run_collectors_once() -> None:
    """Run API-based collectors once (legacy mode)."""
    logger.info("Running API collectors...")
    logger.info(f"Tracking coins: {settings.coins_list}")

    db = Database()
    await db.connect()

    collectors = [
        FearGreedCollector(db),
        PriceCollector(db),
    ]

    if settings.reddit_client_id and settings.reddit_client_secret:
        collectors.append(RedditCollector(db))
    else:
        logger.warning("Reddit API not configured")

    if settings.whale_alert_api_key:
        collectors.append(OnChainCollector(db))
    else:
        logger.warning("Whale Alert API not configured")

    try:
        for collector in collectors:
            try:
                await collector.run()
            except Exception as e:
                logger.error(f"Collector {collector.name} failed: {e}")
    finally:
        for collector in collectors:
            if hasattr(collector, "close"):
                await collector.close()
        await db.close()


async def run_bayesian_crawler(iterations: int, delay: float) -> None:
    """Run the Bayesian-guided crawler for a fixed number of iterations."""
    logger.info("Starting Bayesian Crawler...")

    db = Database()
    await db.connect()

    # First, collect price data for baseline calculation
    logger.info("Collecting initial price data...")
    price_collector = PriceCollector(db)
    try:
        await price_collector.run()
    finally:
        await price_collector.close()

    # Run orchestrator
    orchestrator = CrawlerOrchestrator(db)

    try:
        await orchestrator.initialize()
        await orchestrator.run_loop(iterations=iterations, delay_seconds=delay)

        # Show final statistics
        stats = orchestrator.get_statistics()
        logger.info("=== Final Statistics ===")
        logger.info(f"Total crawls: {stats['total_crawls']}")
        logger.info(f"Pending evaluations: {stats['pending_evaluations']}")
        logger.info("Source rankings:")
        for source, mean in stats["source_rankings"]:
            logger.info(f"  {source}: {mean:.3f}")

    finally:
        await orchestrator.shutdown()
        await db.close()


async def run_background(
    crawl_interval: int,
    price_interval: int,
    eval_interval: int,
) -> None:
    """Run the background scheduler (daemon mode)."""
    logger.info("=" * 60)
    logger.info("CRYPTO SENTIMENT CRAWLER - BACKGROUND MODE")
    logger.info("=" * 60)
    logger.info(f"Crawl interval: {crawl_interval}s")
    logger.info(f"Price interval: {price_interval}s")
    logger.info(f"Evaluation interval: {eval_interval}s")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    await run_background_scheduler(
        crawl_interval=crawl_interval,
        price_interval=price_interval,
        eval_interval=eval_interval,
    )


async def run_demo_mode() -> None:
    """Run demo to test all components."""
    from .demo import run_demo
    await run_demo()


async def show_stats() -> None:
    """Show current stats."""
    await view_live_stats()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Crypto Sentiment Crawler - Bayesian-guided web crawling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run crawler                    # Run background daemon (default)
  uv run crawler background         # Same as above
  uv run crawler bayesian -n 10     # Run 10 iterations then exit
  uv run crawler collectors         # Run API collectors once
  uv run crawler stats              # View current statistics
  uv run crawler demo               # Run demo mode
        """,
    )

    parser.add_argument(
        "mode",
        nargs="?",
        default="background",
        choices=["background", "bayesian", "collectors", "demo", "stats"],
        help="Run mode (default: background)",
    )

    parser.add_argument(
        "-n", "--iterations",
        type=int,
        default=0,
        help="Number of iterations (0=infinite, for bayesian mode)",
    )

    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=30.0,
        help="Delay between iterations in seconds (for bayesian mode)",
    )

    parser.add_argument(
        "--crawl-interval",
        type=int,
        default=120,
        help="Crawl interval in seconds (for background mode, default: 120)",
    )

    parser.add_argument(
        "--price-interval",
        type=int,
        default=300,
        help="Price collection interval in seconds (default: 300)",
    )

    parser.add_argument(
        "--eval-interval",
        type=int,
        default=900,
        help="Evaluation interval in seconds (default: 900)",
    )

    args = parser.parse_args()

    if args.mode == "background":
        asyncio.run(run_background(
            crawl_interval=args.crawl_interval,
            price_interval=args.price_interval,
            eval_interval=args.eval_interval,
        ))
    elif args.mode == "bayesian":
        asyncio.run(run_bayesian_crawler(args.iterations, args.delay))
    elif args.mode == "collectors":
        asyncio.run(run_collectors_once())
    elif args.mode == "stats":
        asyncio.run(show_stats())
    elif args.mode == "demo":
        asyncio.run(run_demo_mode())


if __name__ == "__main__":
    main()
