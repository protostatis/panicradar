"""
Backfill semantic sentiment scores for all raw sentiment data.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone

from .processing.semantic_sentiment import SemanticSentimentAnalyzer
from .logging_config import logger


def backfill_semantic_scores(batch_size: int = 100):
    """Backfill semantic sentiment scores from raw data."""

    logger.info("Initializing semantic sentiment analyzer...")
    analyzer = SemanticSentimentAnalyzer()

    conn = sqlite3.connect("data/sentiment.db")
    conn.row_factory = sqlite3.Row

    # Get all raw records that don't have semantic scores yet
    total = conn.execute("""
        SELECT COUNT(*) FROM sentiment_raw r
        WHERE NOT EXISTS (
            SELECT 1 FROM sentiment_scores_semantic s
            WHERE s.timestamp = r.timestamp AND s.source = r.source
        )
    """).fetchone()[0]

    logger.info(f"Found {total} records to process")

    if total == 0:
        logger.info("No records to process")
        conn.close()
        return

    processed = 0
    inserted = 0
    errors = 0

    while True:
        # Fetch batch of unprocessed records
        rows = conn.execute("""
            SELECT r.id, r.timestamp, r.source, r.coin,
                   json_extract(r.raw_data, '$.title') as title,
                   json_extract(r.raw_data, '$.selftext') as text,
                   json_extract(r.raw_data, '$.body') as body
            FROM sentiment_raw r
            WHERE NOT EXISTS (
                SELECT 1 FROM sentiment_scores_semantic s
                WHERE s.timestamp = r.timestamp AND s.source = r.source
            )
            LIMIT ?
        """, (batch_size,)).fetchall()

        if not rows:
            break

        batch_texts = []
        batch_meta = []

        for row in rows:
            # Combine title and text
            parts = []
            if row["title"]:
                parts.append(row["title"])
            if row["text"]:
                parts.append(row["text"][:500])  # Limit text length
            elif row["body"]:
                parts.append(row["body"][:500])

            content = " ".join(parts).strip()
            if not content:
                content = "empty"

            batch_texts.append(content)
            batch_meta.append({
                "timestamp": row["timestamp"],
                "source": row["source"],
                "coin": row["coin"] or "MARKET",
            })

        # Analyze batch
        try:
            results = analyzer.analyze_batch(batch_texts)

            for meta, result in zip(batch_meta, results):
                try:
                    conn.execute("""
                        INSERT INTO sentiment_scores_semantic
                        (timestamp, coin, source, score, confidence, bullish_sim, bearish_sim, neutral_sim)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        meta["timestamp"],
                        meta["coin"],
                        meta["source"],
                        result["score"],
                        result["confidence"],
                        result["bullish_sim"],
                        result["bearish_sim"],
                        result["neutral_sim"],
                    ))
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # Skip duplicates
                except Exception as e:
                    errors += 1
                    logger.debug(f"Insert error: {e}")

            conn.commit()

        except Exception as e:
            logger.error(f"Batch analysis error: {e}")
            errors += len(batch_texts)

        processed += len(rows)
        if processed % 500 == 0:
            logger.info(f"Progress: {processed}/{total} ({100*processed/total:.1f}%)")

    conn.close()

    logger.info("=" * 60)
    logger.info("SEMANTIC BACKFILL COMPLETE")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Inserted: {inserted}")
    logger.info(f"  Errors: {errors}")
    logger.info("=" * 60)


def compare_methods():
    """Compare all three sentiment methods on the data."""
    conn = sqlite3.connect("data/sentiment.db")

    print("\n" + "=" * 70)
    print("SENTIMENT METHOD COMPARISON")
    print("=" * 70)

    # Overall stats
    stats = conn.execute("""
        SELECT
            'VADER' as method,
            COUNT(*) as count,
            ROUND(AVG(score), 4) as avg_score,
            SUM(CASE WHEN score > 0.15 THEN 1 ELSE 0 END) as positive,
            SUM(CASE WHEN score < -0.15 THEN 1 ELSE 0 END) as negative,
            SUM(CASE WHEN score >= -0.15 AND score <= 0.15 THEN 1 ELSE 0 END) as neutral
        FROM sentiment_scores
        UNION ALL
        SELECT
            'FinBERT',
            COUNT(*),
            ROUND(AVG(score), 4),
            SUM(CASE WHEN score > 0.15 THEN 1 ELSE 0 END),
            SUM(CASE WHEN score < -0.15 THEN 1 ELSE 0 END),
            SUM(CASE WHEN score >= -0.15 AND score <= 0.15 THEN 1 ELSE 0 END)
        FROM sentiment_scores_transformer
        UNION ALL
        SELECT
            'Semantic',
            COUNT(*),
            ROUND(AVG(score), 4),
            SUM(CASE WHEN score > 0.15 THEN 1 ELSE 0 END),
            SUM(CASE WHEN score < -0.15 THEN 1 ELSE 0 END),
            SUM(CASE WHEN score >= -0.15 AND score <= 0.15 THEN 1 ELSE 0 END)
        FROM sentiment_scores_semantic
    """).fetchall()

    print(f"\n{'Method':<10} {'Count':>8} {'Avg':>8} {'Positive':>10} {'Negative':>10} {'Neutral':>10}")
    print("-" * 60)
    for method, count, avg, pos, neg, neu in stats:
        print(f"{method:<10} {count:>8} {avg:>+8.4f} {pos:>10} {neg:>10} {neu:>10}")

    # Correlation between methods
    print("\n\nMethod Correlations (on matching records):")
    print("-" * 40)

    corr = conn.execute("""
        SELECT
            ROUND(AVG(v.score), 4) as vader_avg,
            ROUND(AVG(t.score), 4) as finbert_avg,
            ROUND(AVG(s.score), 4) as semantic_avg,
            COUNT(*) as matched
        FROM sentiment_scores v
        JOIN sentiment_scores_transformer t
            ON v.timestamp = t.timestamp AND v.source = t.source AND v.coin = t.coin
        JOIN sentiment_scores_semantic s
            ON v.timestamp = s.timestamp AND v.source = s.source AND v.coin = s.coin
    """).fetchone()

    if corr[3] > 0:
        print(f"Matched records: {corr[3]}")
        print(f"VADER avg:    {corr[0]:+.4f}")
        print(f"FinBERT avg:  {corr[1]:+.4f}")
        print(f"Semantic avg: {corr[2]:+.4f}")

    conn.close()
    print("=" * 70)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        compare_methods()
    else:
        backfill_semantic_scores()
        compare_methods()
