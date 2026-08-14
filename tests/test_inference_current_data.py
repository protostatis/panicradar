"""Regression tests for the experimental inference data source."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from crypto_sentiment_crawler.inference import PricePredictor, SentimentAnalyzer
from crypto_sentiment_crawler.sqlite_utils import connect_sqlite
from crypto_sentiment_crawler.storage.db import SCHEMA


def create_inference_database(path: Path, *, sentiment_age_hours: int | None) -> None:
    now = datetime.now(timezone.utc)
    connection = connect_sqlite(path)
    connection.executescript(SCHEMA)
    connection.execute(
        """
        CREATE TABLE sentiment_scores (
            source TEXT, coin TEXT, score REAL, confidence REAL,
            sample_size INTEGER, timestamp TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO sentiment_scores VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy_source", "BTC", 0.99, 1.0, 1, now.isoformat()),
    )
    connection.execute(
        "INSERT INTO confounders (timestamp, fear_greed_index) VALUES (?, ?)",
        ((now - timedelta(minutes=5)).isoformat(), 20),
    )
    connection.executemany(
        """
        INSERT INTO price_data (timestamp, coin, price_usd, volume_24h)
        VALUES (?, 'BTC', ?, 1000)
        """,
        [
            ((now - timedelta(hours=2)).isoformat(), 100.0),
            ((now - timedelta(minutes=1)).isoformat(), 101.0),
        ],
    )

    if sentiment_age_hours is not None:
        cursor = connection.execute(
            """
            INSERT INTO user_profiles (username, source, first_seen, last_seen)
            VALUES ('alice', 'reddit_bitcoin', ?, ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO user_sentiment_scores (
                user_id, timestamp, coin, title_score, final_score, segments_scored
            ) VALUES (?, ?, 'BTC', 0.6, 0.6, 4)
            """,
            (
                cursor.lastrowid,
                (now - timedelta(hours=sentiment_age_hours)).isoformat(),
            ),
        )

    connection.commit()
    connection.close()


def test_inference_reads_current_tables_and_ignores_legacy_scores(tmp_path: Path) -> None:
    db_path = tmp_path / "sentiment.db"
    create_inference_database(db_path, sentiment_age_hours=1)

    analyzer = SentimentAnalyzer(str(db_path))
    frame = analyzer.get_recent_sentiment(hours=4, coin="BTC")

    assert set(frame["source"]) == {"reddit_bitcoin", "fear_greed"}
    assert "legacy_source" not in set(frame["source"])
    assert frame.loc[frame["source"] == "reddit_bitcoin", "score"].iloc[0] == 0.6
    assert frame.loc[frame["source"] == "fear_greed", "score"].iloc[0] == -0.6
    assert analyzer.compute_aggregate_sentiment(hours=4, coin="BTC")["n_social_sources"] == 1


def test_direction_is_suppressed_without_fresh_user_sentiment(tmp_path: Path) -> None:
    db_path = tmp_path / "sentiment.db"
    create_inference_database(db_path, sentiment_age_hours=48)

    prediction = PricePredictor(str(db_path)).predict(coin="BTC", lookback_hours=4)

    assert prediction.predicted_direction == "neutral"
    assert prediction.confidence == 0.0
    assert prediction.signals["sentiment"]["n_social_sources"] == 0
    assert "suppressed" in prediction.reasoning
