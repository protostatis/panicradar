#!/usr/bin/env python3
"""
Rescore all sentiment data using transformer model and compare with VADER scores.

Creates a new table `sentiment_scores_transformer` and rescores all raw data.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from ..logging_config import logger
from ..storage.db import Database
from ..processing.sentiment import CryptoSentimentAnalyzer


async def create_transformer_table(db: Database):
    """Create the transformer scores table."""
    await db.conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_scores_transformer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            coin VARCHAR(10) NOT NULL,
            source VARCHAR(50) NOT NULL,
            score FLOAT NOT NULL,
            confidence FLOAT,
            sample_size INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sentiment_transformer_time
        ON sentiment_scores_transformer(timestamp, coin)
    """)
    await db.conn.commit()
    logger.info("Created sentiment_scores_transformer table")


async def get_raw_data_count(db: Database) -> int:
    """Get total count of raw sentiment data."""
    cursor = await db.conn.execute("SELECT COUNT(*) FROM sentiment_raw")
    row = await cursor.fetchone()
    return row[0] if row else 0


async def rescore_with_transformer(
    db: Database,
    analyzer: CryptoSentimentAnalyzer,
    batch_size: int = 100,
    verbose: bool = True
):
    """Rescore all raw sentiment data using transformer."""
    total = await get_raw_data_count(db)

    if verbose:
        print(f"\n📊 Total raw records to rescore: {total:,}")
        print(f"   Using batch size: {batch_size}")
        print(f"   Estimated batches: {(total + batch_size - 1) // batch_size}")
        print()

    processed = 0
    scored = 0
    errors = 0
    offset = 0

    while True:
        # Fetch batch of raw data
        cursor = await db.conn.execute("""
            SELECT id, timestamp, source, coin, raw_data
            FROM sentiment_raw
            ORDER BY id
            LIMIT ? OFFSET ?
        """, (batch_size, offset))

        rows = await cursor.fetchall()
        if not rows:
            break

        batch_scores = []

        for row in rows:
            raw_id, timestamp, source, coin, raw_data_json = row
            processed += 1

            try:
                raw_data = json.loads(raw_data_json) if isinstance(raw_data_json, str) else raw_data_json

                # Extract text content
                text = ""
                if "title" in raw_data and raw_data["title"]:
                    text = raw_data["title"]
                if "content" in raw_data and raw_data["content"]:
                    text = f"{text} {raw_data['content']}" if text else raw_data["content"]
                if "text" in raw_data and raw_data["text"]:
                    text = f"{text} {raw_data['text']}" if text else raw_data["text"]
                if "body" in raw_data and raw_data["body"]:
                    text = f"{text} {raw_data['body']}" if text else raw_data["body"]
                if "message" in raw_data and raw_data["message"]:
                    text = f"{text} {raw_data['message']}" if text else raw_data["message"]

                if not text or len(text.strip()) < 5:
                    continue

                # Analyze with transformer
                result = analyzer.analyze(text[:1000])  # Limit text length
                score = result["compound"]

                # Determine coin if not set
                if not coin:
                    coin = "BTC"  # Default

                batch_scores.append((timestamp, coin, source, score, 1.0, 1))
                scored += 1

            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"Error scoring record {raw_id}: {e}")

        # Insert batch
        if batch_scores:
            await db.conn.executemany("""
                INSERT INTO sentiment_scores_transformer
                (timestamp, coin, source, score, confidence, sample_size)
                VALUES (?, ?, ?, ?, ?, ?)
            """, batch_scores)
            await db.conn.commit()

        offset += batch_size

        if verbose and processed % 1000 == 0:
            pct = (processed / total) * 100
            print(f"   Progress: {processed:,}/{total:,} ({pct:.1f}%) - Scored: {scored:,}")

    if verbose:
        print(f"\n✅ Rescoring complete!")
        print(f"   Processed: {processed:,}")
        print(f"   Scored: {scored:,}")
        print(f"   Errors: {errors:,}")

    return {"processed": processed, "scored": scored, "errors": errors}


async def compare_scores(db: Database, verbose: bool = True) -> dict:
    """Compare VADER and transformer scores."""

    # Get score comparison by source
    cursor = await db.conn.execute("""
        SELECT
            v.source,
            COUNT(*) as count,
            AVG(v.score) as vader_avg,
            AVG(t.score) as transformer_avg,
            AVG(ABS(v.score - t.score)) as avg_diff,
            AVG(CASE WHEN v.score * t.score > 0 THEN 1 ELSE 0 END) as agreement_rate
        FROM sentiment_scores v
        JOIN sentiment_scores_transformer t
            ON v.timestamp = t.timestamp AND v.source = t.source
        GROUP BY v.source
        ORDER BY count DESC
    """)

    by_source = await cursor.fetchall()

    # Get overall comparison
    cursor = await db.conn.execute("""
        SELECT
            COUNT(*) as total,
            AVG(v.score) as vader_avg,
            AVG(t.score) as transformer_avg,
            AVG(ABS(v.score - t.score)) as avg_diff,
            AVG(CASE WHEN v.score * t.score > 0 THEN 1.0 ELSE 0.0 END) as agreement_rate,
            AVG(CASE WHEN v.score > 0.1 AND t.score > 0.1 THEN 1.0
                     WHEN v.score < -0.1 AND t.score < -0.1 THEN 1.0
                     WHEN v.score BETWEEN -0.1 AND 0.1 AND t.score BETWEEN -0.1 AND 0.1 THEN 1.0
                     ELSE 0.0 END) as category_agreement
        FROM sentiment_scores v
        JOIN sentiment_scores_transformer t
            ON v.timestamp = t.timestamp AND v.source = t.source
    """)

    overall = await cursor.fetchone()

    # Get correlation
    cursor = await db.conn.execute("""
        SELECT
            (COUNT(*) * SUM(v.score * t.score) - SUM(v.score) * SUM(t.score)) /
            SQRT((COUNT(*) * SUM(v.score * v.score) - SUM(v.score) * SUM(v.score)) *
                 (COUNT(*) * SUM(t.score * t.score) - SUM(t.score) * SUM(t.score))) as correlation
        FROM sentiment_scores v
        JOIN sentiment_scores_transformer t
            ON v.timestamp = t.timestamp AND v.source = t.source
    """)

    corr_row = await cursor.fetchone()
    correlation = corr_row[0] if corr_row and corr_row[0] else 0

    # Get distribution comparison
    cursor = await db.conn.execute("""
        SELECT
            'VADER' as method,
            SUM(CASE WHEN score > 0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_positive,
            SUM(CASE WHEN score < -0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_negative,
            SUM(CASE WHEN score BETWEEN -0.1 AND 0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_neutral
        FROM sentiment_scores
        UNION ALL
        SELECT
            'Transformer' as method,
            SUM(CASE WHEN score > 0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_positive,
            SUM(CASE WHEN score < -0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_negative,
            SUM(CASE WHEN score BETWEEN -0.1 AND 0.1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct_neutral
        FROM sentiment_scores_transformer
    """)

    distribution = await cursor.fetchall()

    results = {
        "overall": {
            "total_compared": overall[0],
            "vader_avg": overall[1],
            "transformer_avg": overall[2],
            "avg_diff": overall[3],
            "sign_agreement": overall[4],
            "category_agreement": overall[5],
            "correlation": correlation,
        },
        "by_source": [
            {
                "source": row[0],
                "count": row[1],
                "vader_avg": row[2],
                "transformer_avg": row[3],
                "avg_diff": row[4],
                "agreement": row[5],
            }
            for row in by_source
        ],
        "distribution": [
            {
                "method": row[0],
                "pct_positive": row[1],
                "pct_negative": row[2],
                "pct_neutral": row[3],
            }
            for row in distribution
        ],
    }

    if verbose:
        print("\n" + "=" * 70)
        print("VADER vs TRANSFORMER COMPARISON")
        print("=" * 70)

        print(f"\n📊 Overall Statistics ({overall[0]:,} matched records)")
        print("-" * 50)
        print(f"  VADER avg score:       {overall[1]:+.4f}")
        print(f"  Transformer avg score: {overall[2]:+.4f}")
        print(f"  Average difference:    {overall[3]:.4f}")
        print(f"  Sign agreement:        {overall[4]*100:.1f}%")
        print(f"  Category agreement:    {overall[5]*100:.1f}%")
        print(f"  Correlation:           {correlation:.4f}")

        print(f"\n📈 Distribution Comparison")
        print("-" * 50)
        print(f"  {'Method':<12} {'Positive':<12} {'Negative':<12} {'Neutral':<12}")
        for row in distribution:
            print(f"  {row[0]:<12} {row[1]:>8.1f}%    {row[2]:>8.1f}%    {row[3]:>8.1f}%")

        print(f"\n📋 By Source (top 15)")
        print("-" * 70)
        print(f"  {'Source':<28} {'Count':<8} {'VADER':<10} {'Trans':<10} {'Agree':<8}")
        for row in by_source[:15]:
            print(f"  {row[0]:<28} {row[1]:<8} {row[2]:+.3f}     {row[3]:+.3f}     {row[5]*100:.0f}%")

        print("=" * 70)

    return results


async def run_full_rescore(db_path: str = "data/sentiment.db", verbose: bool = True):
    """Run the full rescoring process."""

    if verbose:
        print("\n" + "=" * 70)
        print("🧠 TRANSFORMER RESCORING")
        print("=" * 70)
        print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("  Loading FinBERT transformer model...")

    # Initialize transformer analyzer
    analyzer = CryptoSentimentAnalyzer(use_transformer=True)

    if not analyzer.use_transformer:
        print("❌ Failed to load transformer model!")
        return None

    if verbose:
        print(f"  ✅ Transformer loaded on {analyzer._device}")
        print("=" * 70)

    # Connect to database
    db = Database(Path(db_path))
    await db.connect()

    try:
        # Create transformer table
        await create_transformer_table(db)

        # Clear existing transformer scores for fresh rescore
        await db.conn.execute("DELETE FROM sentiment_scores_transformer")
        await db.conn.commit()

        # Rescore everything
        stats = await rescore_with_transformer(db, analyzer, batch_size=50, verbose=verbose)

        # Compare scores
        comparison = await compare_scores(db, verbose=verbose)

        return {
            "rescore_stats": stats,
            "comparison": comparison,
        }

    finally:
        await db.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Rescore sentiment with transformer")
    parser.add_argument("--db", default="data/sentiment.db", help="Database path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")

    args = parser.parse_args()

    result = asyncio.run(run_full_rescore(args.db, verbose=not args.quiet))

    if result:
        print("\n✅ Rescoring complete!")


if __name__ == "__main__":
    main()
