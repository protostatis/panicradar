"""
Dynamic source weights based on Bayesian beliefs.

Converts learned accuracy/contrarian status into inference weights.
Stores weights in database for use by inference module.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ..logging_config import logger
from ..storage.db import Database


async def create_weights_table(db: Database):
    """Create the source_weights table if it doesn't exist."""
    await db.conn.execute("""
        CREATE TABLE IF NOT EXISTS source_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source VARCHAR(50) NOT NULL UNIQUE,
            weight FLOAT NOT NULL,
            accuracy FLOAT,
            is_contrarian BOOLEAN DEFAULT FALSE,
            alpha FLOAT,
            beta FLOAT,
            sample_size INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_weights_source
        ON source_weights(source)
    """)
    await db.conn.commit()
    logger.info("Created source_weights table")


def compute_weight_from_belief(belief: dict, min_samples: int = 20) -> tuple[float, bool]:
    """
    Compute inference weight from Bayesian belief.

    Returns (weight, should_invert).

    Weight is based on:
    - Accuracy (distance from 0.5)
    - Sample size (more samples = more confident)
    - Contrarian status (inverted signal)

    A source with 60% accuracy gets higher weight than 50%.
    A source with 40% accuracy also gets higher weight (as contrarian).
    Sources near 50% get low weight (uninformative).
    """
    accuracy = belief.get("accuracy")
    alpha = belief.get("alpha", 1)
    beta = belief.get("beta", 1)
    sample_size = alpha + beta
    is_contrarian = belief.get("is_contrarian", False)

    if accuracy is None or sample_size < min_samples:
        # Not enough data - use minimal weight
        return 0.01, False

    # Distance from 0.5 (uninformative baseline)
    # Both 0.6 and 0.4 have distance 0.1
    distance = abs(accuracy - 0.5)

    # Base weight from predictive power
    # Max distance is 0.5, so scale to 0-1
    predictive_power = distance * 2  # 0 to 1

    # Confidence factor from sample size
    # More samples = more confident in the weight
    confidence = min(1.0, sample_size / 200)  # Cap at 200 samples

    # Combined weight (predictive power * confidence)
    # Scale to reasonable range (0.01 to 0.30)
    weight = 0.01 + (predictive_power * confidence * 0.29)

    return weight, is_contrarian


def compute_weights_from_beliefs(beliefs: dict, min_samples: int = 20) -> dict:
    """
    Compute all source weights from beliefs.

    Returns dict of {source: {"weight": float, "is_contrarian": bool, ...}}
    """
    weights = {}

    for source, belief in beliefs.items():
        weight, is_contrarian = compute_weight_from_belief(belief, min_samples)

        weights[source] = {
            "source": source,
            "weight": weight,
            "accuracy": belief.get("accuracy"),
            "is_contrarian": is_contrarian,
            "alpha": belief.get("alpha"),
            "beta": belief.get("beta"),
            "sample_size": belief.get("alpha", 1) + belief.get("beta", 1),
        }

    # Normalize weights to sum to 1.0
    total_weight = sum(w["weight"] for w in weights.values())
    if total_weight > 0:
        for source in weights:
            weights[source]["weight_normalized"] = weights[source]["weight"] / total_weight

    return weights


async def save_weights_to_db(db: Database, weights: dict):
    """Save computed weights to database."""
    await create_weights_table(db)

    for source, data in weights.items():
        await db.conn.execute("""
            INSERT INTO source_weights
            (source, weight, accuracy, is_contrarian, alpha, beta, sample_size, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                weight = excluded.weight,
                accuracy = excluded.accuracy,
                is_contrarian = excluded.is_contrarian,
                alpha = excluded.alpha,
                beta = excluded.beta,
                sample_size = excluded.sample_size,
                last_updated = excluded.last_updated
        """, (
            source,
            data["weight"],
            data.get("accuracy"),
            data.get("is_contrarian", False),
            data.get("alpha"),
            data.get("beta"),
            data.get("sample_size"),
            datetime.now(timezone.utc).isoformat(),
        ))

    await db.conn.commit()
    logger.info(f"Saved {len(weights)} source weights to database")


def load_weights_from_db_sync(db_path: str = "data/sentiment.db") -> dict:
    """
    Load weights from database (synchronous version for inference).

    Returns dict compatible with SentimentAnalyzer.SOURCE_WEIGHTS.
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT source, weight, accuracy, is_contrarian, sample_size
        FROM source_weights
        ORDER BY weight DESC
    """)

    weights = {}
    contrarian_sources = set()

    for row in cursor:
        weights[row["source"]] = row["weight"]
        if row["is_contrarian"]:
            contrarian_sources.add(row["source"])

    conn.close()

    return {
        "weights": weights,
        "contrarian_sources": contrarian_sources,
    }


async def update_weights_from_beliefs(
    state_path: str = "data/orchestrator_state.json",
    db_path: str = "data/sentiment.db",
    min_samples: int = 20,
) -> dict:
    """
    Update source weights from current beliefs.

    Called after belief updates to sync weights.
    """
    # Load beliefs
    path = Path(state_path)
    if not path.exists():
        logger.warning(f"State file not found: {state_path}")
        return {}

    with open(path) as f:
        state = json.load(f)

    beliefs = state.get("beliefs", {})

    # Compute weights
    weights = compute_weights_from_beliefs(beliefs, min_samples)

    # Save to database
    db = Database(Path(db_path))
    await db.connect()

    try:
        await save_weights_to_db(db, weights)
    finally:
        await db.close()

    return weights


def print_weights_table(weights: dict):
    """Print formatted weights table."""
    print("\n" + "=" * 80)
    print("SOURCE WEIGHTS (from Bayesian Beliefs)")
    print("=" * 80)

    sorted_weights = sorted(
        weights.items(),
        key=lambda x: x[1].get("weight", 0),
        reverse=True
    )

    print(f"\n{'Source':<30} {'Weight':<10} {'Norm':<10} {'Accuracy':<10} {'Type':<12} {'Samples':<10}")
    print("-" * 80)

    for source, data in sorted_weights:
        accuracy = data.get("accuracy")
        acc_str = f"{accuracy:.1%}" if accuracy else "N/A"
        type_str = "CONTRARIAN" if data.get("is_contrarian") else "MOMENTUM" if accuracy and accuracy > 0.5 else "NEUTRAL"
        norm = data.get("weight_normalized", 0)
        samples = data.get("sample_size", 0)

        print(f"{source:<30} {data['weight']:<10.4f} {norm:<10.4f} {acc_str:<10} {type_str:<12} {samples:<10.0f}")

    print("=" * 80)
