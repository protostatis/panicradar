#!/usr/bin/env python3
"""
One-time migration script to deduplicate case-variant source names.

Merges mixed-case source keys into their lowercase equivalents in:
  A. orchestrator_state.json beliefs
  B. Database tables (sentiment_raw, user_profiles, source_weights)

Also removes stale sources that should not be in beliefs:
  - coindesk, cointelegraph (disabled news sources, never crawled)
  - reddit_cryptocurrencymeta (0 total crawls, never returns content)

Usage:
  # Dry run (default) - shows what would change
  python scripts/deduplicate_sources.py

  # Apply changes to state file only
  python scripts/deduplicate_sources.py --apply-state

  # Apply changes to database only (run on EC2)
  python scripts/deduplicate_sources.py --apply-db

  # Apply both
  python scripts/deduplicate_sources.py --apply-state --apply-db
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_PATH = Path("data/orchestrator_state.json")
DB_PATH = Path("data/sentiment.db")

# Sources to remove entirely from beliefs
STALE_SOURCES = {"coindesk", "cointelegraph", "reddit_cryptocurrencymeta"}


def find_duplicate_pairs(beliefs: dict) -> list[tuple[str, str]]:
    """Find pairs where lowercase key and mixed-case key both exist."""
    keys_by_lower = {}
    for key in beliefs:
        lower = key.lower()
        keys_by_lower.setdefault(lower, []).append(key)

    pairs = []
    for lower, variants in keys_by_lower.items():
        if len(variants) > 1:
            # Find the lowercase one and the mixed-case one
            lc = lower
            mixed = [v for v in variants if v != lower]
            if lc in variants and mixed:
                for m in mixed:
                    pairs.append((lc, m))
    return pairs


def merge_beliefs(lower_entry: dict, mixed_entry: dict) -> dict:
    """Merge mixed-case belief into lowercase belief.

    Merge rule:
    - Sum alphas and betas (additive — both represent accumulated observations)
    - Keep the higher total_crawls
    - Reset consecutive_empty_crawls to 0
    - Use latest last_updated
    - Keep other fields from whichever has more total_crawls
    """
    merged = dict(lower_entry)  # Start with lowercase as base
    merged["source"] = lower_entry["source"].lower()

    # Sum alpha/beta (the Bayesian observations are additive)
    merged["alpha"] = lower_entry["alpha"] + mixed_entry.get("alpha", 1.0) - 1.0  # subtract prior
    merged["beta"] = lower_entry["beta"] + mixed_entry.get("beta", 1.0) - 1.0  # subtract prior

    # Keep higher total_crawls
    merged["total_crawls"] = max(
        lower_entry.get("total_crawls", 0),
        mixed_entry.get("total_crawls", 0),
    )

    # Reset consecutive empty
    merged["consecutive_empty_crawls"] = 0

    # Use latest last_updated
    lower_ts = lower_entry.get("last_updated", "")
    mixed_ts = mixed_entry.get("last_updated", "")
    merged["last_updated"] = max(lower_ts, mixed_ts) if lower_ts and mixed_ts else lower_ts or mixed_ts

    return merged


def migrate_state(dry_run: bool = True) -> None:
    """Deduplicate beliefs in orchestrator_state.json."""
    if not STATE_PATH.exists():
        print(f"State file not found: {STATE_PATH}")
        return

    with open(STATE_PATH) as f:
        state = json.load(f)

    beliefs = state.get("beliefs", {})
    print(f"\nCurrent belief count: {len(beliefs)}")

    # Find duplicate pairs
    pairs = find_duplicate_pairs(beliefs)
    if pairs:
        print(f"\nDuplicate pairs found ({len(pairs)}):")
        for lc, mc in pairs:
            print(f"  {lc} <-> {mc}")
            print(f"    lowercase:  alpha={beliefs[lc]['alpha']:.2f}, beta={beliefs[lc]['beta']:.2f}, crawls={beliefs[lc].get('total_crawls', 0)}")
            print(f"    mixed-case: alpha={beliefs[mc]['alpha']:.2f}, beta={beliefs[mc]['beta']:.2f}, crawls={beliefs[mc].get('total_crawls', 0)}")
    else:
        print("\nNo duplicate pairs found.")

    # Merge duplicates
    for lc, mc in pairs:
        merged = merge_beliefs(beliefs[lc], beliefs[mc])
        print(f"\n  Merged {lc}: alpha={merged['alpha']:.2f}, beta={merged['beta']:.2f}, crawls={merged['total_crawls']}")
        beliefs[lc] = merged
        del beliefs[mc]

    # Rename any remaining solo mixed-case keys to lowercase
    renamed = []
    for key in list(beliefs.keys()):
        if key != key.lower() and key.lower() not in beliefs:
            beliefs[key.lower()] = beliefs.pop(key)
            beliefs[key.lower()]["source"] = key.lower()
            renamed.append(f"{key} -> {key.lower()}")

    if renamed:
        print(f"\nRenamed solo mixed-case keys:")
        for r in renamed:
            print(f"  {r}")

    # Remove stale sources
    removed = []
    for source in list(beliefs.keys()):
        if source in STALE_SOURCES:
            removed.append(source)
            del beliefs[source]

    if removed:
        print(f"\nRemoved stale sources: {removed}")

    state["beliefs"] = beliefs
    print(f"\nFinal belief count: {len(beliefs)}")

    if dry_run:
        print("\n[DRY RUN] No changes written. Use --apply-state to write.")
    else:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=4)
        print(f"\nWrote updated state to {STATE_PATH}")


def migrate_db(dry_run: bool = True) -> None:
    """Normalize source names to lowercase in database tables."""
    if not DB_PATH.exists():
        print(f"\nDatabase not found: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # sentiment_raw: simple lowercasing (no unique constraint on source)
    try:
        cursor.execute(
            "SELECT source, COUNT(*) FROM sentiment_raw WHERE source != LOWER(source) GROUP BY source"
        )
        rows = cursor.fetchall()
        if rows:
            total = sum(r[1] for r in rows)
            print(f"\nsentiment_raw: {total} rows with mixed-case source names:")
            for source, count in rows:
                print(f"  {source}: {count} rows -> {source.lower()}")

            if not dry_run:
                cursor.execute(
                    "UPDATE sentiment_raw SET source = LOWER(source) WHERE source != LOWER(source)"
                )
                print(f"  Updated {cursor.rowcount} rows")
        else:
            print(f"\nsentiment_raw: all sources already lowercase")
    except sqlite3.OperationalError as e:
        print(f"\nsentiment_raw: table not found or error: {e}")

    # user_profiles: has UNIQUE(username, source) — delete mixed-case dupes first
    try:
        cursor.execute(
            "SELECT source, COUNT(*) FROM user_profiles WHERE source != LOWER(source) GROUP BY source"
        )
        rows = cursor.fetchall()
        if rows:
            total = sum(r[1] for r in rows)
            print(f"\nuser_profiles: {total} rows with mixed-case source names:")
            for source, count in rows:
                print(f"  {source}: {count} rows -> {source.lower()}")

            if not dry_run:
                # Delete mixed-case rows where a lowercase row already exists for the same user
                cursor.execute(
                    """DELETE FROM user_profiles
                       WHERE source != LOWER(source)
                         AND EXISTS (
                           SELECT 1 FROM user_profiles AS lc
                           WHERE lc.username = user_profiles.username
                             AND lc.source = LOWER(user_profiles.source)
                         )"""
                )
                deleted = cursor.rowcount
                if deleted:
                    print(f"  Deleted {deleted} duplicate rows (lowercase version exists)")

                # Now safely lowercase the remaining mixed-case rows
                cursor.execute(
                    "UPDATE user_profiles SET source = LOWER(source) WHERE source != LOWER(source)"
                )
                print(f"  Updated {cursor.rowcount} rows")
        else:
            print(f"\nuser_profiles: all sources already lowercase")
    except sqlite3.OperationalError as e:
        print(f"\nuser_profiles: table not found or error: {e}")

    # source_weights: delete mixed-case rows (they'll be recomputed)
    try:
        cursor.execute(
            "SELECT source, COUNT(*) FROM source_weights WHERE source != LOWER(source) GROUP BY source"
        )
        rows = cursor.fetchall()
        if rows:
            total = sum(r[1] for r in rows)
            print(f"\nsource_weights: {total} mixed-case rows to delete:")
            for source, count in rows:
                print(f"  {source}: {count} rows (will be recomputed)")

            if not dry_run:
                cursor.execute(
                    "DELETE FROM source_weights WHERE source != LOWER(source)"
                )
                print(f"  Deleted {cursor.rowcount} rows")
        else:
            print(f"\nsource_weights: all sources already lowercase")
    except sqlite3.OperationalError as e:
        print(f"\nsource_weights: table not found or error: {e}")

    if dry_run:
        print("\n[DRY RUN] No DB changes applied. Use --apply-db to apply.")
    else:
        conn.commit()
        print("\nDatabase changes committed.")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Deduplicate case-variant source names")
    parser.add_argument("--apply-state", action="store_true", help="Apply changes to orchestrator_state.json")
    parser.add_argument("--apply-db", action="store_true", help="Apply changes to database")
    args = parser.parse_args()

    print("=" * 60)
    print("Source Name Deduplication")
    print("=" * 60)

    migrate_state(dry_run=not args.apply_state)
    migrate_db(dry_run=not args.apply_db)

    print("\nDone.")


if __name__ == "__main__":
    main()
