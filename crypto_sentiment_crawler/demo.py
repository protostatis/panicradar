"""Demo script to test Bayesian + Crawler integration."""

import asyncio

from .bayesian import CrawlBandit, SourceBeliefStore, UtilityScorer, compute_baseline_informativeness
from .bayesian.cold_start import initialize_source_belief
from .crawler import ContentPipeline
from .crawler.pipeline import RedditPipeline
from .crawler.sources import DEFAULT_SOURCES
from .logging_config import logger


async def demo_crawler():
    """Test the crawler by fetching from Reddit."""
    logger.info("=== Testing Crawler ===")

    async with RedditPipeline() as pipeline:
        # Crawl r/cryptocurrency
        posts = await pipeline.crawl_subreddit("cryptocurrency", limit=10)

        logger.info(f"Crawled {len(posts)} posts from r/cryptocurrency")

        for post in posts[:5]:
            logger.info(
                f"  [{post.sentiment_score:+.2f}] {post.title[:60]}..."
                f" (coins: {post.coins_mentioned}, score: {post.metadata.get('score', 0)})"
            )

    return posts


def demo_bayesian():
    """Test the Bayesian decision system."""
    logger.info("\n=== Testing Bayesian System ===")

    # Initialize belief store
    store = SourceBeliefStore()

    # Add sources with different priors based on type
    sources = [
        ("reddit_cryptocurrency", "social"),
        ("reddit_bitcoin", "social"),
        ("coindesk", "news"),
        ("cointelegraph", "news"),
        ("bitcointalk", "forum"),
    ]

    # Simulate baseline from price (normally computed from real data)
    baseline = 0.6  # Assume moderate unpredictability

    for source_name, source_type in sources:
        belief = initialize_source_belief(source_name, baseline, source_type)
        store.beliefs[source_name] = belief
        logger.info(
            f"  {source_name}: α={belief.alpha:.2f}, β={belief.beta:.2f}, "
            f"mean={belief.mean:.3f}"
        )

    # Create bandit
    bandit = CrawlBandit(store)

    # Simulate source selection
    logger.info("\n--- Thompson Sampling Selections ---")
    for i in range(10):
        result = bandit.select_source()
        logger.info(
            f"  Selection {i+1}: {result.source} "
            f"(sampled={result.sampled_value:.3f}, final={result.final_score:.3f})"
        )

        # Simulate outcome
        utility = 0.3 + 0.4 * (i % 2)  # Alternating outcomes
        bandit.update_from_outcome(result.source, utility)

    # Show final rankings
    logger.info("\n--- Final Rankings ---")
    for source, mean in bandit.get_exploitation_ranking():
        belief = store.get(source)
        logger.info(f"  {source}: mean={mean:.3f} (α={belief.alpha:.1f}, β={belief.beta:.1f})")


def demo_utility():
    """Test utility scoring."""
    logger.info("\n=== Testing Utility Scorer ===")

    scorer = UtilityScorer()

    # Test accuracy
    acc1 = scorer.compute_accuracy(sentiment_score=0.5, price_before=100, price_after=105)
    acc2 = scorer.compute_accuracy(sentiment_score=0.5, price_before=100, price_after=95)
    acc3 = scorer.compute_accuracy(sentiment_score=-0.5, price_before=100, price_after=95)

    logger.info(f"  Accuracy (bullish + up): {acc1}")
    logger.info(f"  Accuracy (bullish + down): {acc2}")
    logger.info(f"  Accuracy (bearish + down): {acc3}")

    # Test novelty
    texts = [
        "Bitcoin reaches new all-time high amid institutional buying",
        "Bitcoin price surges to record levels as institutions buy",
        "Ethereum network upgrade scheduled for next month",
    ]

    for i, text in enumerate(texts):
        novelty = scorer.compute_novelty_only(text)
        logger.info(f"  Novelty for text {i+1}: {novelty:.3f}")


async def run_demo():
    """Run all demos."""
    logger.info("Starting Crypto Sentiment Crawler Demo\n")

    # Bayesian system
    demo_bayesian()

    # Utility scoring
    demo_utility()

    # Crawler
    posts = await demo_crawler()

    logger.info("\n=== Demo Complete ===")
    return posts


def main():
    """Entry point for demo."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
