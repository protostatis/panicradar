#!/usr/bin/env python3
"""
Ghost Source Cleanup

Identifies and removes "ghost" sources — sources that have rows in
source_weights (and beliefs in orchestrator_state.json) but ZERO rows in
sentiment_raw. These are typically artifacts migrated from an older system.

Usage:
  python scripts/cleanup_ghost_sources.py --db data/sentiment.db --state data/orchestrator_state.json
  python scripts/cleanup_ghost_sources.py --dry-run   # preview without changes
  python scripts/cleanup_ghost_sources.py --force     # skip confirmation prompt
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ghost_cleanup")

DEFAULT_DB = Path("data/sentiment.db")
DEFAULT_STATE = Path("data/orchestrator_state.json")


def connect(db_path: Path) -> sqlite3.Connection:
    """Connect to the SQLite database (synchronous)."""
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def find_ghost_sources(conn: sqlite3.Connection) -> list[dict]:
    """
    Find sources that exist in source_weights but have zero rows in sentiment_raw.

    Returns list of dicts with source name, weight, accuracy, and is_contrarian.
    """
    cursor = conn.execute("""
        SELECT sw.source, sw.weight, sw.accuracy, sw.is_contrarian,
               COALESCE(sr.cnt, 0) AS raw_count
        FROM source_weights sw
        LEFT JOIN (
            SELECT LOWER(source) AS normalized_source, COUNT(*) AS cnt
            FROM sentiment_raw
            GROUP BY LOWER(source)
        ) sr ON LOWER(sw.source) = sr.normalized_source
        WHERE sr.cnt IS NULL OR sr.cnt = 0
        ORDER BY sw.source
    """)
    return [dict(row) for row in cursor.fetchall()]


def backup_state_file(state_path: Path) -> Path | None:
    """Create a timestamped backup of the orchestrator state file."""
    if not state_path.exists():
        logger.warning("State file not found, skipping backup")
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = state_path.with_name(
        f"orchestrator_state_{timestamp}.json.bak"
    )
    with open(state_path) as f_in:
        with open(backup_path, "w") as f_out:
            f_out.write(f_in.read())
    logger.info("Backup created: %s", backup_path)
    return backup_path


def remove_from_source_weights(conn: sqlite3.Connection, sources: list[str]) -> int:
    """Delete ghost source rows from the source_weights table."""
    if not sources:
        return 0

    placeholders = ",".join("?" * len(sources))
    cursor = conn.execute(
        f"DELETE FROM source_weights WHERE LOWER(source) IN ({placeholders})",
        [source.lower() for source in sources],
    )
    conn.commit()
    return cursor.rowcount


def remove_from_state(state_path: Path, sources: list[str]) -> int:
    """
    Remove ghost source beliefs from orchestrator_state.json.

    Returns the number of beliefs removed.
    """
    if not state_path.exists():
        logger.warning("State file not found, skipping belief removal")
        return 0

    with open(state_path) as f:
        state = json.load(f)

    beliefs = state.get("beliefs", {})
    normalized_sources = {source.lower() for source in sources}
    removed = 0
    for source in list(beliefs):
        if source.lower() in normalized_sources:
            del beliefs[source]
            removed += 1
            logger.info("Removed belief for ghost source: %s", source)

    if removed > 0:
        state["beliefs"] = beliefs
        state["last_ghost_cleanup"] = datetime.now(timezone.utc).isoformat()

        # Atomic write via temp file
        tmp_path = state_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=4)
        tmp_path.replace(state_path)

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up ghost sources with zero sentiment_raw rows",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help=f"Path to orchestrator state JSON (default: {DEFAULT_STATE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview ghost sources without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    # ── Connect to DB ────────────────────────────────────────────
    conn = connect(args.db)

    try:
        ghosts = find_ghost_sources(conn)
    finally:
        conn.close()

    if not ghosts:
        print("\nNo ghost sources found. All sources in source_weights "
              "have corresponding sentiment_raw rows.")
        return

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("GHOST SOURCE CLEANUP")
    print("=" * 70)
    print(f"\nFound {len(ghosts)} ghost source(s) with zero sentiment_raw rows:\n")
    print(f"  {'Source':<28} {'Weight':<10} {'Accuracy':<10} {'Contrarian':<12}")
    print(f"  {'-'*28} {'-'*10} {'-'*10} {'-'*12}")
    for g in ghosts:
        acc = f"{g['accuracy']:.4f}" if g['accuracy'] is not None else "N/A"
        con = "Yes" if g['is_contrarian'] else "No"
        print(f"  {g['source']:<28} {g['weight']:<10.4f} {acc:<10} {con:<12}")
    print()

    if args.dry_run:
        print("[DRY-RUN] No changes made. Run without --dry-run to clean up.")
        return

    # ── Confirmation ──────────────────────────────────────────────
    if not args.force:
        answer = input(
            f"Remove {len(ghosts)} ghost source(s) from source_weights "
            f"and orchestrator_state? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    ghost_names = [g["source"] for g in ghosts]

    # ── Backup state file ─────────────────────────────────────────
    backup_path = backup_state_file(args.state)

    # ── Remove from source_weights ───────────────────────────────
    conn = connect(args.db)
    try:
        deleted = remove_from_source_weights(conn, ghost_names)
        logger.info("Deleted %d row(s) from source_weights", deleted)
    finally:
        conn.close()

    # ── Remove from orchestrator_state.json ───────────────────────
    removed = remove_from_state(args.state, ghost_names)
    logger.info("Removed %d belief(s) from orchestrator_state.json", removed)

    # ── Done ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("CLEANUP COMPLETE")
    print("=" * 70)
    print(f"\n  Sources removed:        {len(ghosts)}")
    print(f"  source_weights rows:    {deleted}")
    print(f"  beliefs removed:        {removed}")
    if backup_path:
        print(f"  State backup:           {backup_path}")
    print()


if __name__ == "__main__":
    main()
