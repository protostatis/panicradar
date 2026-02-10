#!/usr/bin/env python3
"""
Sentiment Score Accuracy Audit

Joins sentiment_raw with user_sentiment_scores to produce a comprehensive
report for manually reviewing how well final_score reflects actual post
sentiment.

Usage:
  # Run against local audit DB
  python scripts/audit_score_accuracy.py --db data/sentiment_audit.db --output data/audit_report.csv

  # Run against default dev DB
  python scripts/audit_score_accuracy.py
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path


DEFAULT_DB = Path("data/sentiment.db")
DEFAULT_OUTPUT = Path("data/audit_report.csv")

# How many posts to show in each extreme-score sample
SAMPLE_SIZE = 20
# Threshold for title vs body divergence flag
DIVERGENCE_THRESHOLD = 0.5
# Max content snippet length in CSV
SNIPPET_LEN = 300


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def extract_text(raw_data_json: str) -> tuple[str, str, int]:
    """Extract title, content snippet, and human comment count from raw_data JSON."""
    try:
        data = json.loads(raw_data_json)
    except (json.JSONDecodeError, TypeError):
        return "", "", 0

    title = data.get("title", "") or ""
    content = data.get("text") or data.get("selftext") or data.get("body") or ""

    metadata = data.get("metadata", {})
    comments = metadata.get("comments", [])
    human_comment_count = sum(
        1 for c in comments
        if (c.get("author") or "").lower() not in ("automoderator", "[deleted]", "bot")
        and not (c.get("author") or "").lower().endswith("bot")
    ) if comments else 0

    return title, content[:SNIPPET_LEN], human_comment_count


# ---------------------------------------------------------------------------
# Section A: Overview stats
# ---------------------------------------------------------------------------

def print_overview(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 70)
    print("SECTION A: OVERVIEW STATS")
    print("=" * 70)

    # Total scored posts
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM user_sentiment_scores"
    ).fetchone()
    total_scored = row["cnt"]

    row = conn.execute("SELECT COUNT(*) AS cnt FROM sentiment_raw").fetchone()
    total_raw = row["cnt"]

    # Unscored posts
    row = conn.execute(
        """SELECT COUNT(*) AS cnt FROM sentiment_raw sr
           WHERE NOT EXISTS (
               SELECT 1 FROM user_sentiment_scores uss WHERE uss.raw_id = sr.id
           )"""
    ).fetchone()
    unscored = row["cnt"]

    print(f"\nTotal raw posts:       {total_raw}")
    print(f"Total scored posts:    {total_scored}")
    print(f"Unscored posts:        {unscored}")

    # Score distribution
    stats = conn.execute(
        """SELECT
             AVG(final_score) AS mean,
             MIN(final_score) AS min_s,
             MAX(final_score) AS max_s,
             COUNT(*) AS cnt
           FROM user_sentiment_scores
           WHERE final_score IS NOT NULL"""
    ).fetchone()

    if stats["cnt"] > 0:
        # Compute median via window function
        median_row = conn.execute(
            """SELECT final_score FROM user_sentiment_scores
               WHERE final_score IS NOT NULL
               ORDER BY final_score
               LIMIT 1 OFFSET (
                   SELECT COUNT(*) / 2 FROM user_sentiment_scores WHERE final_score IS NOT NULL
               )"""
        ).fetchone()
        median = median_row["final_score"] if median_row else 0

        # Stddev (sqlite doesn't have native stddev, compute manually)
        mean = stats["mean"]
        var_row = conn.execute(
            """SELECT AVG((final_score - ?) * (final_score - ?)) AS variance
               FROM user_sentiment_scores WHERE final_score IS NOT NULL""",
            (mean, mean),
        ).fetchone()
        stddev = var_row["variance"] ** 0.5 if var_row["variance"] else 0

        print(f"\nScore statistics:")
        print(f"  Mean:   {mean:+.4f}")
        print(f"  Median: {median:+.4f}")
        print(f"  Stddev: {stddev:.4f}")
        print(f"  Range:  [{stats['min_s']:+.4f}, {stats['max_s']:+.4f}]")

    # Histogram (10 bins from -1 to 1)
    print(f"\nScore distribution histogram:")
    bins = [(-1.0 + i * 0.2, -1.0 + (i + 1) * 0.2) for i in range(10)]
    for lo, hi in bins:
        row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM user_sentiment_scores
               WHERE final_score >= ? AND final_score < ?""",
            (lo, hi if hi < 1.0 else 1.01),
        ).fetchone()
        bar = "#" * (row["cnt"] // max(1, total_scored // 60))
        print(f"  [{lo:+.1f}, {hi:+.1f}): {row['cnt']:>6}  {bar}")

    # By source
    print(f"\nBreakdown by source:")
    rows = conn.execute(
        """SELECT sr.source,
                  COUNT(uss.id) AS scored,
                  AVG(uss.final_score) AS avg_score
           FROM sentiment_raw sr
           LEFT JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           GROUP BY sr.source
           ORDER BY scored DESC"""
    ).fetchall()
    print(f"  {'Source':<30} {'Scored':>7} {'Avg Score':>10}")
    print(f"  {'-'*30} {'-'*7} {'-'*10}")
    for r in rows:
        avg = f"{r['avg_score']:+.4f}" if r["avg_score"] is not None else "N/A"
        print(f"  {r['source']:<30} {r['scored']:>7} {avg:>10}")


# ---------------------------------------------------------------------------
# Section B: Extreme score samples
# ---------------------------------------------------------------------------

def print_extreme_samples(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 70)
    print("SECTION B: EXTREME SCORE SAMPLES (for manual review)")
    print("=" * 70)

    for label, order, description in [
        ("MOST BULLISH", "DESC", "highest final_score"),
        ("MOST BEARISH", "ASC", "lowest final_score"),
    ]:
        print(f"\n--- Top {SAMPLE_SIZE} {label} posts ({description}) ---\n")
        rows = conn.execute(
            f"""SELECT sr.id, sr.source, sr.raw_data, sr.timestamp,
                       uss.final_score, uss.title_score, uss.body_score,
                       uss.fear_index, uss.euphoria_index
                FROM sentiment_raw sr
                JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
                WHERE uss.final_score IS NOT NULL
                ORDER BY uss.final_score {order}
                LIMIT ?""",
            (SAMPLE_SIZE,),
        ).fetchall()

        for r in rows:
            title, snippet, _ = extract_text(r["raw_data"])
            ts = f"{r['title_score']:+.3f}" if r["title_score"] is not None else "None"
            print(f"  [{r['final_score']:+.4f}] id={r['id']}  source={r['source']}")
            print(f"    title_score={ts}  body_score={r['body_score']:+.3f}  "
                  f"fear={r['fear_index']:.2f}  euphoria={r['euphoria_index']:.2f}")
            print(f"    Title: {title[:120]}")
            print(f"    Content: {snippet[:200]}")
            print()

    # Near-neutral sample
    print(f"\n--- {SAMPLE_SIZE} NEAR-NEUTRAL posts (score closest to 0) ---\n")
    rows = conn.execute(
        """SELECT sr.id, sr.source, sr.raw_data, sr.timestamp,
                  uss.final_score, uss.title_score, uss.body_score
           FROM sentiment_raw sr
           JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           WHERE uss.final_score IS NOT NULL
           ORDER BY ABS(uss.final_score) ASC
           LIMIT ?""",
        (SAMPLE_SIZE,),
    ).fetchall()

    for r in rows:
        title, snippet, _ = extract_text(r["raw_data"])
        ts = f"{r['title_score']:+.3f}" if r["title_score"] is not None else "None"
        print(f"  [{r['final_score']:+.4f}] id={r['id']}  source={r['source']}")
        print(f"    title_score={ts}  body_score={r['body_score']:+.3f}")
        print(f"    Title: {title[:120]}")
        print(f"    Content: {snippet[:200]}")
        print()


# ---------------------------------------------------------------------------
# Section C: Segment-level breakdown
# ---------------------------------------------------------------------------

def print_segment_breakdown(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 70)
    print("SECTION C: SEGMENT-LEVEL BREAKDOWN (sample of 10 posts)")
    print("=" * 70)

    # Pick 10 posts that have segment_scores populated and non-trivial segment counts
    rows = conn.execute(
        """SELECT sr.id, sr.source, sr.raw_data,
                  uss.final_score, uss.title_score, uss.body_score,
                  uss.segment_scores, uss.segments_filtered, uss.segments_scored,
                  uss.activity_level, uss.fear_index, uss.euphoria_index
           FROM sentiment_raw sr
           JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           WHERE uss.segment_scores IS NOT NULL
             AND uss.segments_scored > 0
             AND (uss.segments_filtered > 0 OR uss.fear_index > 0 OR uss.euphoria_index > 0)
           ORDER BY (uss.segments_filtered + uss.fear_index * 10 + uss.euphoria_index * 10) DESC
           LIMIT 10"""
    ).fetchall()

    if not rows:
        # Fallback: just pick any 10 posts with segment data
        rows = conn.execute(
            """SELECT sr.id, sr.source, sr.raw_data,
                      uss.final_score, uss.title_score, uss.body_score,
                      uss.segment_scores, uss.segments_filtered, uss.segments_scored,
                      uss.activity_level, uss.fear_index, uss.euphoria_index
               FROM sentiment_raw sr
               JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
               WHERE uss.segment_scores IS NOT NULL AND uss.segments_scored > 0
               LIMIT 10"""
        ).fetchall()

    for r in rows:
        title, _, _ = extract_text(r["raw_data"])
        print(f"\n  Post id={r['id']}  source={r['source']}")
        print(f"  Title: {title[:100]}")
        print(f"  final={r['final_score']:+.4f}  title={r['title_score']}  body={r['body_score']:+.4f}")
        print(f"  scored={r['segments_scored']}  filtered={r['segments_filtered']}  "
              f"activity={r['activity_level']:.2f}  fear={r['fear_index']:.2f}  euphoria={r['euphoria_index']:.2f}")

        try:
            segments = json.loads(r["segment_scores"])
        except (json.JSONDecodeError, TypeError):
            print("  (could not parse segment_scores)")
            continue

        for i, seg in enumerate(segments):
            cat = seg.get("category", "?")
            incl = "Y" if seg.get("included", True) else "N"
            score = seg.get("score", 0)
            text_preview = (seg.get("text", ""))[:80]
            print(f"    seg[{i}] score={score:+.3f}  cat={cat:<15}  incl={incl}  \"{text_preview}\"")


# ---------------------------------------------------------------------------
# Section D: Mismatch detection
# ---------------------------------------------------------------------------

def print_mismatches(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 70)
    print("SECTION D: SCORE vs CONTENT MISMATCH FLAGS")
    print("=" * 70)

    # Title vs body divergence
    print(f"\n--- Title/Body divergence (|title_score - body_score| > {DIVERGENCE_THRESHOLD}) ---\n")
    rows = conn.execute(
        """SELECT sr.id, sr.source, sr.raw_data,
                  uss.final_score, uss.title_score, uss.body_score,
                  uss.fear_index, uss.euphoria_index
           FROM sentiment_raw sr
           JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           WHERE uss.title_score IS NOT NULL
             AND ABS(uss.title_score - uss.body_score) > ?
           ORDER BY ABS(uss.title_score - uss.body_score) DESC
           LIMIT 30""",
        (DIVERGENCE_THRESHOLD,),
    ).fetchall()

    print(f"  Found {len(rows)} posts with title/body divergence > {DIVERGENCE_THRESHOLD}")
    for r in rows:
        title, snippet, _ = extract_text(r["raw_data"])
        diff = abs(r["title_score"] - r["body_score"])
        print(f"\n  [{r['final_score']:+.4f}] id={r['id']}  divergence={diff:.3f}")
        print(f"    title_score={r['title_score']:+.3f}  body_score={r['body_score']:+.3f}")
        print(f"    Title: {title[:120]}")
        print(f"    Content: {snippet[:150]}")

    # High fear/euphoria but neutral final score
    print(f"\n--- High fear/euphoria index but neutral final_score (|score| < 0.15) ---\n")
    rows = conn.execute(
        """SELECT sr.id, sr.source, sr.raw_data,
                  uss.final_score, uss.title_score, uss.body_score,
                  uss.fear_index, uss.euphoria_index, uss.activity_level
           FROM sentiment_raw sr
           JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           WHERE ABS(uss.final_score) < 0.15
             AND (uss.fear_index > 0.3 OR uss.euphoria_index > 0.3)
           ORDER BY (uss.fear_index + uss.euphoria_index) DESC
           LIMIT 20"""
    ).fetchall()

    print(f"  Found {len(rows)} posts with high signal indices but neutral score")
    for r in rows:
        title, snippet, _ = extract_text(r["raw_data"])
        print(f"\n  [{r['final_score']:+.4f}] id={r['id']}  fear={r['fear_index']:.2f}  euphoria={r['euphoria_index']:.2f}")
        print(f"    Title: {title[:120]}")
        print(f"    Content: {snippet[:150]}")


# ---------------------------------------------------------------------------
# Section E: CSV export
# ---------------------------------------------------------------------------

def export_csv(conn: sqlite3.Connection, output_path: Path) -> None:
    print("\n" + "=" * 70)
    print(f"SECTION E: CSV EXPORT -> {output_path}")
    print("=" * 70)

    rows = conn.execute(
        """SELECT sr.id AS raw_id, sr.source, sr.timestamp, sr.raw_data,
                  uss.final_score, uss.title_score, uss.body_score,
                  uss.activity_level, uss.fear_index, uss.euphoria_index,
                  uss.segments_scored, uss.segments_filtered,
                  uss.pos_count, uss.neg_count, uss.neu_count,
                  uss.aggregation_method
           FROM sentiment_raw sr
           LEFT JOIN user_sentiment_scores uss ON sr.id = uss.raw_id
           ORDER BY sr.timestamp DESC"""
    ).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "raw_id", "source", "timestamp", "title", "content_snippet",
        "final_score", "title_score", "body_score",
        "activity_level", "fear_index", "euphoria_index",
        "segment_count", "segments_filtered",
        "pos_count", "neg_count", "neu_count",
        "aggregation_method", "human_comment_count",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in rows:
            title, snippet, hcc = extract_text(r["raw_data"])
            writer.writerow({
                "raw_id": r["raw_id"],
                "source": r["source"],
                "timestamp": r["timestamp"],
                "title": title,
                "content_snippet": snippet,
                "final_score": r["final_score"],
                "title_score": r["title_score"],
                "body_score": r["body_score"],
                "activity_level": r["activity_level"],
                "fear_index": r["fear_index"],
                "euphoria_index": r["euphoria_index"],
                "segment_count": r["segments_scored"],
                "segments_filtered": r["segments_filtered"],
                "pos_count": r["pos_count"],
                "neg_count": r["neg_count"],
                "neu_count": r["neu_count"],
                "aggregation_method": r["aggregation_method"],
                "human_comment_count": hcc,
            })

    print(f"\n  Exported {len(rows)} rows to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit sentiment score accuracy against raw post content"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path for CSV export (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    conn = connect(args.db)

    try:
        print_overview(conn)
        print_extreme_samples(conn)
        print_segment_breakdown(conn)
        print_mismatches(conn)
        export_csv(conn, args.output)
    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("Audit complete. Review the terminal output above and the CSV export.")
    print("=" * 70)


if __name__ == "__main__":
    main()
