#!/usr/bin/env python3
"""
Auto-updater for Bayesian beliefs.

Runs continuously and updates beliefs at regular intervals.

Usage:
    uv run python -m crypto_sentiment_crawler.analysis.belief_auto_updater
    uv run python -m crypto_sentiment_crawler.analysis.belief_auto_updater --interval 60
"""

import argparse
import asyncio
from datetime import datetime, timezone

from ..logging_config import logger
from .belief_updater import update_orchestrator_beliefs


async def run_auto_updater(interval_minutes: int = 30, verbose: bool = True):
    """Run belief auto-updater continuously."""
    update_count = 0

    if verbose:
        print("\n" + "=" * 60)
        print("🧠 BAYESIAN BELIEF AUTO-UPDATER")
        print("=" * 60)
        print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Update interval: {interval_minutes} minutes")
        print("=" * 60)
        print("\n  Press Ctrl+C to stop\n")

    while True:
        update_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if verbose:
            print(f"\n{'─' * 60}")
            print(f"[{timestamp}] Update #{update_count}")
            print(f"{'─' * 60}")

        try:
            updated = await update_orchestrator_beliefs()

            # Get top sources
            sorted_beliefs = sorted(
                [(s, b) for s, b in updated.items() if b.get('accuracy') is not None],
                key=lambda x: x[1].get('accuracy', 0),
                reverse=True
            )

            if verbose:
                print(f"  ✅ Updated {len(sorted_beliefs)} sources")

                # Show top 3 momentum and contrarian
                momentum = [(s, b) for s, b in sorted_beliefs if b.get('accuracy', 0) >= 0.5][:3]
                contrarian = [(s, b) for s, b in sorted_beliefs if b.get('accuracy', 0) < 0.45][:3]

                if momentum:
                    print(f"\n  📈 Top Momentum:")
                    for source, belief in momentum:
                        print(f"     {source}: {belief['accuracy']:.1%}")

                if contrarian:
                    print(f"\n  📉 Top Contrarian:")
                    for source, belief in contrarian:
                        print(f"     {source}: {belief['accuracy']:.1%} (inverse)")

            logger.info(f"Belief auto-update #{update_count}: {len(sorted_beliefs)} sources updated")

        except Exception as e:
            logger.error(f"Belief auto-update error: {e}")
            if verbose:
                print(f"  ❌ Error: {e}")

        if verbose:
            next_update = datetime.now().strftime("%H:%M:%S")
            print(f"\n  Next update in {interval_minutes} minutes...")

        await asyncio.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="Bayesian Belief Auto-Updater")
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=30,
        help="Update interval in minutes (default: 30)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Quiet mode (minimal output)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(run_auto_updater(
            interval_minutes=args.interval,
            verbose=not args.quiet
        ))
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("Belief auto-updater stopped.")
        print("=" * 60)


if __name__ == "__main__":
    main()
