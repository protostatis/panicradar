"""Backfill user sentiment scores from existing raw data."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from crypto_sentiment_crawler.processing.user_sentiment import backfill_user_scores

if __name__ == "__main__":
    limit = None
    update_existing = False

    for arg in sys.argv[1:]:
        if arg == "--update":
            update_existing = True
        elif arg.isdigit():
            limit = int(arg)

    print(f"Starting user sentiment backfill...")
    print(f"  Limit: {limit or 'all'}")
    print(f"  Update existing: {update_existing}")

    processed, updated, skipped, errors = backfill_user_scores(
        limit=limit,
        update_existing=update_existing
    )

    print(f"\nBackfill complete!")
    print(f"  New: {processed}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")
