"""Database migrations that run once after deploy.

Each migration has a unique ID and is tracked in the migrations table.
Migrations are idempotent - they only run if not already applied.
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

from ..processing.user_sentiment import MIN_HUMAN_COMMENTS, count_human_comments

logger = logging.getLogger("crypto_sentiment")


async def ensure_migrations_table(conn: "aiosqlite.Connection") -> None:
    """Create migrations tracking table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS applied_migrations (
            id TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def is_migration_applied(conn: "aiosqlite.Connection", migration_id: str) -> bool:
    """Check if a migration has already been applied."""
    cursor = await conn.execute(
        "SELECT 1 FROM applied_migrations WHERE id = ?",
        (migration_id,)
    )
    return await cursor.fetchone() is not None


async def mark_migration_applied(conn: "aiosqlite.Connection", migration_id: str) -> None:
    """Mark a migration as applied."""
    await conn.execute(
        "INSERT INTO applied_migrations (id) VALUES (?)",
        (migration_id,)
    )
    await conn.commit()


async def cleanup_low_engagement_posts(conn: "aiosqlite.Connection") -> int:
    """Delete raw posts with < MIN_HUMAN_COMMENTS that have no score.

    Returns number of deleted rows.
    """
    migration_id = "001_cleanup_low_engagement_posts"

    await ensure_migrations_table(conn)

    if await is_migration_applied(conn, migration_id):
        logger.debug(f"Migration {migration_id} already applied, skipping")
        return 0

    logger.info(f"Running migration: {migration_id}")

    # Find unscored posts
    cursor = await conn.execute("""
        SELECT sr.id, sr.raw_data
        FROM sentiment_raw sr
        LEFT JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
        WHERE uss.id IS NULL
    """)
    rows = await cursor.fetchall()

    # Filter by comment count and collect IDs to delete
    ids_to_delete = []
    for row in rows:
        raw_id = row[0]
        try:
            raw_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            metadata = raw_data.get("metadata", {})
            human_comments = count_human_comments(metadata)

            if human_comments < MIN_HUMAN_COMMENTS:
                ids_to_delete.append(raw_id)
        except (json.JSONDecodeError, TypeError):
            # Can't parse, skip
            continue

    # Delete in batches
    deleted = 0
    batch_size = 500
    for i in range(0, len(ids_to_delete), batch_size):
        batch = ids_to_delete[i:i + batch_size]
        placeholders = ",".join("?" * len(batch))
        await conn.execute(
            f"DELETE FROM sentiment_raw WHERE id IN ({placeholders})",
            batch
        )
        await conn.commit()
        deleted += len(batch)

    await mark_migration_applied(conn, migration_id)
    logger.info(f"Migration {migration_id} complete: deleted {deleted} low-engagement posts")

    return deleted


async def fix_timestamps_from_metadata(conn: "aiosqlite.Connection") -> int:
    """Update sentiment_raw timestamps to use post creation time instead of crawl time.

    The timestamp should be when the post was created, not when we crawled it.
    The correct timestamp is stored in raw_data.metadata.created_utc (Unix timestamp).

    Returns number of updated rows.
    """
    from datetime import datetime, timezone

    migration_id = "002_fix_timestamps_from_metadata"

    await ensure_migrations_table(conn)

    if await is_migration_applied(conn, migration_id):
        logger.debug(f"Migration {migration_id} already applied, skipping")
        return 0

    logger.info(f"Running migration: {migration_id}")

    # Get all rows with metadata containing created_utc
    cursor = await conn.execute("""
        SELECT id, raw_data, timestamp
        FROM sentiment_raw
    """)
    rows = await cursor.fetchall()

    updated = 0
    batch_updates = []

    for row in rows:
        raw_id = row[0]
        try:
            raw_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            metadata = raw_data.get("metadata", {})
            created_utc = metadata.get("created_utc")

            if created_utc:
                # Convert Unix timestamp to ISO format
                post_time = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                batch_updates.append((post_time.isoformat(), raw_id))

        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    # Update in batches
    batch_size = 500
    for i in range(0, len(batch_updates), batch_size):
        batch = batch_updates[i:i + batch_size]
        await conn.executemany(
            "UPDATE sentiment_raw SET timestamp = ? WHERE id = ?",
            batch
        )
        await conn.commit()
        updated += len(batch)

    # Also update user_sentiment_scores timestamps to match
    await conn.execute("""
        UPDATE user_sentiment_scores
        SET timestamp = (
            SELECT sr.timestamp
            FROM sentiment_raw sr
            WHERE sr.id = user_sentiment_scores.raw_id
        )
        WHERE raw_id IS NOT NULL
    """)
    await conn.commit()

    await mark_migration_applied(conn, migration_id)
    logger.info(f"Migration {migration_id} complete: updated {updated} timestamps")

    return updated


async def run_all_migrations(conn: "aiosqlite.Connection") -> None:
    """Run all pending migrations."""
    await cleanup_low_engagement_posts(conn)
    await fix_timestamps_from_metadata(conn)
