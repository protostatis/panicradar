#!/usr/bin/env python3
"""
Re-score existing posts within a date range using the current pipeline.

Updates user_sentiment_scores rows in-place and refreshes user profiles.

Usage:
  # Re-score last 7 days
  uv run python scripts/retro_score.py --days 7

  # Re-score a specific date range
  uv run python scripts/retro_score.py --start 2026-02-02 --end 2026-02-10

  # Dry run (score but don't write)
  uv run python scripts/retro_score.py --days 7 --dry-run
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crypto_sentiment_crawler.processing.user_sentiment import UserSentimentScorer

logger = logging.getLogger("retro_score")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

DEFAULT_DB = "data/sentiment.db"


def main():
    parser = argparse.ArgumentParser(description="Re-score posts in a date range")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    parser.add_argument("--days", type=int, help="Re-score posts from the last N days")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD), inclusive")
    parser.add_argument("--end", help="End date (YYYY-MM-DD), exclusive")
    parser.add_argument("--dry-run", action="store_true", help="Score but don't write to DB")
    args = parser.parse_args()

    if args.days:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
    elif args.start and args.end:
        start_str = args.start
        end_str = args.end
    else:
        parser.error("Provide either --days or both --start and --end")
        return

    db_path = args.db
    logger.info(f"DB: {db_path}")
    logger.info(f"Date range: {start_str} to {end_str}")
    logger.info(f"Dry run: {args.dry_run}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Count posts in range
    total_raw = conn.execute(
        "SELECT COUNT(*) AS cnt FROM sentiment_raw WHERE timestamp >= ? AND timestamp < ?",
        (start_str, end_str),
    ).fetchone()["cnt"]

    total_scored = conn.execute(
        """SELECT COUNT(*) AS cnt FROM user_sentiment_scores uss
           JOIN sentiment_raw sr ON uss.raw_id = sr.id
           WHERE sr.timestamp >= ? AND sr.timestamp < ?""",
        (start_str, end_str),
    ).fetchone()["cnt"]

    logger.info(f"Posts in range: {total_raw} raw, {total_scored} scored")

    # Fetch all raw posts in range (not just previously scored ones)
    rows = conn.execute(
        """SELECT id, source, raw_data, timestamp, coin
           FROM sentiment_raw
           WHERE timestamp >= ? AND timestamp < ?
           ORDER BY id""",
        (start_str, end_str),
    ).fetchall()
    conn.close()

    logger.info(f"Loading scorer...")
    scorer = UserSentimentScorer(db_path=db_path)

    processed = 0
    updated = 0
    skipped = 0
    errors = 0
    user_ids = set()

    for i, row in enumerate(rows):
        try:
            raw_data = json.loads(row["raw_data"])
            if not raw_data:
                skipped += 1
                continue

            post_score = scorer.score_post(
                raw_data, row["id"], row["timestamp"], row["source"], row["coin"]
            )

            if post_score is None:
                skipped += 1
                continue

            if args.dry_run:
                processed += 1
            else:
                score_id = scorer.save_post_score(post_score, update_existing=True)
                if score_id > 0:
                    updated += 1
                    user_id = scorer.get_or_create_user(
                        post_score.username, post_score.source, row["timestamp"]
                    )
                    user_ids.add(user_id)
                else:
                    skipped += 1

            if (i + 1) % 200 == 0:
                logger.info(f"Progress: {i + 1}/{len(rows)} ({updated} updated, {skipped} skipped)")

        except Exception as e:
            errors += 1
            logger.error(f"Error on row {row['id']}: {e}")

    # Update user profiles
    if not args.dry_run and user_ids:
        logger.info(f"Updating {len(user_ids)} user profiles...")
        for user_id in user_ids:
            scorer.update_user_profile(user_id)

    logger.info(f"Done: {updated} updated, {processed} dry-run scored, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    main()
