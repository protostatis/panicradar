"""
Dynamic source weights based on Bayesian beliefs.

Converts learned accuracy/contrarian status into inference weights.
Stores weights in database for use by inference module.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ..logging_config import logger
from ..sqlite_utils import connect_sqlite
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
            belief_version INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.conn.execute("""
        CREATE TABLE IF NOT EXISTS source_weight_snapshots (
            belief_version INTEGER NOT NULL,
            source VARCHAR(50) NOT NULL,
            weight FLOAT NOT NULL,
            accuracy FLOAT,
            is_contrarian BOOLEAN DEFAULT FALSE,
            alpha FLOAT,
            beta FLOAT,
            sample_size INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (belief_version, source)
        )
    """)
    await db.conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_weights_source
        ON source_weights(source)
    """)
    await db.conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_source_weight_snapshots_version
        ON source_weight_snapshots(belief_version)
    """)
    await db.conn.execute("""
        CREATE TABLE IF NOT EXISTS belief_publications (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            belief_version INTEGER NOT NULL,
            published_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.conn.execute("""
        CREATE VIEW IF NOT EXISTS active_source_weights AS
        SELECT sw.*
        FROM source_weight_snapshots sw
        JOIN belief_publications bp ON bp.belief_version = sw.belief_version
    """)
    await db.conn.commit()
    logger.info("Created source_weights table")


def compute_weight_from_belief(belief: dict, min_samples: int = 20) -> tuple[float, bool]:
    """
    Compute inference weight from Bayesian belief.

    Returns (weight, should_invert).

    Uses the lower bound of the credible interval as the conservative
    accuracy estimate for weight calculation. Sources with insufficient
    data get very low weight and are never treated as contrarian.

    Weight is based on:
    - Accuracy (distance from 0.5)
    - Effective sample size (more observations = more confident)
    - Contrarian status (inverted signal)
    """
    # Change 7: Fail-closed for insufficient data
    type_label = belief.get("type_label", "")
    if type_label in ("insufficient_data", "uninitialized"):
        return 0.01, False

    # Use credible intervals to compute conservative edge over 50%
    ci_lower = belief.get("credible_interval_lower")
    ci_upper = belief.get("credible_interval_upper")
    is_contrarian = belief.get("is_contrarian", False)

    if ci_lower is not None and ci_upper is not None:
        if is_contrarian:
            # Conservative inverted accuracy: 1 - ci_upper (the best-case wrongness)
            conservative_accuracy = 1.0 - ci_upper
        else:
            # Conservative accuracy: ci_lower (the worst-case correctness)
            conservative_accuracy = ci_lower
        # Distance from 0.5 — only count evidence OUTSIDE the null
        distance = max(0.0, conservative_accuracy - 0.5)
    else:
        # Fallback to point accuracy if no CIs
        accuracy = belief.get("accuracy")
        if accuracy is None:
            return 0.01, False
        if is_contrarian:
            distance = max(0.0, (1.0 - accuracy) - 0.5)  # Inverted edge
        else:
            distance = max(0.0, accuracy - 0.5)

    # Use effective_n for confidence
    effective_n = belief.get("effective_n", 0)
    if effective_n < min_samples:
        return 0.01, False

    # Base weight from predictive power
    # Max distance is 0.5, so scale to 0-1
    predictive_power = distance * 2  # 0 to 1

    # Confidence factor from effective sample size
    # More samples = more confident in the weight
    confidence = min(1.0, effective_n / 200)  # Cap at 200 samples

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
            "sample_size": belief.get(
                "effective_n", belief.get("alpha", 1) + belief.get("beta", 1)
            ),
        }

    # Normalize weights to sum to 1.0
    total_weight = sum(w["weight"] for w in weights.values())
    if total_weight > 0:
        for source in weights:
            weights[source]["weight_normalized"] = weights[source]["weight"] / total_weight

    return weights


async def save_weights_to_db(
    db: Database,
    weights: dict,
    *,
    belief_version: int | None = None,
    publish: bool = True,
):
    """Write weights through an isolated SQLite connection and transaction."""
    writer = Database(Path(db.db_path))
    await writer.connect()
    try:
        await _save_weights_to_db(
            writer,
            weights,
            belief_version=belief_version,
            publish=publish,
        )
    finally:
        await writer.close()


async def _save_weights_to_db(
    db: Database,
    weights: dict,
    *,
    belief_version: int | None = None,
    publish: bool = True,
):
    """Stage a versioned weight snapshot and optionally publish current rows."""
    await create_weights_table(db)

    try:
        if not weights:
            raise ValueError("Refusing to stage or publish an empty source-weight snapshot")
        if belief_version is not None and (
            type(belief_version) is not int or belief_version < 0
        ):
            raise ValueError("belief_version must be a non-negative integer")

        # Serialize publishers before inspecting the currently accepted version.
        # The JSON state file is published separately, so equal-version retries
        # must be idempotent while stale writers must never prune newer rows.
        await db.conn.execute("BEGIN IMMEDIATE")
        publication = await (
            await db.conn.execute(
                "SELECT belief_version FROM belief_publications WHERE id = 1"
            )
        ).fetchone()
        published_version = int(publication[0]) if publication is not None else None
        if (
            belief_version is not None
            and published_version is not None
            and belief_version < published_version
        ):
            raise ValueError(
                f"Refusing stale source-weight version {belief_version}; "
                f"published version is {published_version}"
            )

        if belief_version is not None:
            newer_current = await (
                await db.conn.execute(
                    "SELECT COUNT(*) FROM source_weights "
                    "WHERE belief_version IS NOT NULL AND belief_version > ?",
                    (belief_version,),
                )
            ).fetchone()
            if int(newer_current[0]):
                raise RuntimeError(
                    "source_weights contains rows newer than the requested publication"
                )

        if belief_version is not None:
            await db.conn.execute(
                "DELETE FROM source_weight_snapshots WHERE belief_version = ?",
                (belief_version,),
            )
            for source, data in weights.items():
                await db.conn.execute("""
                    INSERT INTO source_weight_snapshots
                    (belief_version, source, weight, accuracy, is_contrarian,
                     alpha, beta, sample_size, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    belief_version,
                    source,
                    data["weight"],
                    data.get("accuracy"),
                    data.get("is_contrarian", False),
                    data.get("alpha"),
                    data.get("beta"),
                    data.get("sample_size"),
                    datetime.now(timezone.utc).isoformat(),
                ))

            staged = await (
                await db.conn.execute(
                    "SELECT COUNT(*) FROM source_weight_snapshots WHERE belief_version = ?",
                    (belief_version,),
                )
            ).fetchone()
            if int(staged[0]) != len(weights):
                raise RuntimeError("Staged source-weight snapshot is incomplete")

        if publish:
            for source, data in weights.items():
                await db.conn.execute("""
                    INSERT INTO source_weights
                    (source, weight, accuracy, is_contrarian, alpha, beta,
                     sample_size, belief_version, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                        weight = excluded.weight,
                        accuracy = excluded.accuracy,
                        is_contrarian = excluded.is_contrarian,
                        alpha = excluded.alpha,
                        beta = excluded.beta,
                        sample_size = excluded.sample_size,
                        belief_version = excluded.belief_version,
                        last_updated = excluded.last_updated
                    WHERE source_weights.belief_version IS NULL
                       OR (
                           excluded.belief_version IS NOT NULL
                           AND excluded.belief_version >= source_weights.belief_version
                       )
                """, (
                    source,
                    data["weight"],
                    data.get("accuracy"),
                    data.get("is_contrarian", False),
                    data.get("alpha"),
                    data.get("beta"),
                    data.get("sample_size"),
                    belief_version,
                    datetime.now(timezone.utc).isoformat(),
                ))
            if belief_version is not None:
                # `source_weights` is the compatibility/current mirror. Remove
                # sources absent from the complete accepted snapshot in the same
                # transaction as the upserts and publication pointer update.
                # Historical versions remain available in the snapshot table.
                await db.conn.execute(
                    """
                    DELETE FROM source_weights
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM source_weight_snapshots snapshot
                        WHERE snapshot.belief_version = ?
                          AND snapshot.source = source_weights.source
                    )
                    """,
                    (belief_version,),
                )

                mirror = await (
                    await db.conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM source_weights current
                        JOIN source_weight_snapshots snapshot
                          ON snapshot.belief_version = ?
                         AND snapshot.source = current.source
                        WHERE current.belief_version = ?
                          AND current.weight = snapshot.weight
                          AND current.accuracy IS snapshot.accuracy
                          AND current.is_contrarian = snapshot.is_contrarian
                          AND current.alpha IS snapshot.alpha
                          AND current.beta IS snapshot.beta
                          AND current.sample_size IS snapshot.sample_size
                        """,
                        (belief_version, belief_version),
                    )
                ).fetchone()
                if int(mirror[0]) != len(weights):
                    raise RuntimeError(
                        "source_weights does not exactly mirror the staged snapshot"
                    )

                await db.conn.execute("""
                    INSERT INTO belief_publications (id, belief_version, published_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        belief_version = excluded.belief_version,
                        published_at = excluded.published_at
                    WHERE excluded.belief_version >= belief_publications.belief_version
                """, (belief_version, datetime.now(timezone.utc).isoformat()))
        await db.conn.commit()
    except Exception:
        await db.conn.rollback()
        raise
    logger.info(f"Saved {len(weights)} source weights to database")


def load_weights_from_db_sync(
    db_path: str = "data/sentiment.db",
    state_path: str | None = None,
) -> dict:
    """
    Load weights from database (synchronous version for inference).

    Returns weights matching the persisted belief version when available.
    """
    import sqlite3

    resolved_state_path = Path(state_path) if state_path else Path(db_path).with_name(
        "orchestrator_state.json"
    )

    def read_belief_version() -> int | None:
        if not resolved_state_path.exists():
            return None
        try:
            with open(resolved_state_path) as f:
                return json.load(f).get("belief_version", 0)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read belief version from %s", resolved_state_path)
            return None

    conn = connect_sqlite(db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_weights)")}
        has_belief_version = "belief_version" in columns
        snapshot_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(source_weight_snapshots)")
        }
        has_snapshots = "belief_version" in snapshot_columns

        for _ in range(2):
            expected_version = read_belief_version()
            if expected_version is not None and has_snapshots:
                cursor = conn.execute("""
                    SELECT source, weight, accuracy, is_contrarian, sample_size
                    FROM source_weight_snapshots
                    WHERE belief_version = ?
                    ORDER BY weight DESC
                """, (expected_version,))
            elif expected_version is None or not has_belief_version:
                cursor = conn.execute("""
                    SELECT source, weight, accuracy, is_contrarian, sample_size
                    FROM source_weights
                    ORDER BY weight DESC
                """)
            else:
                cursor = conn.execute("""
                    SELECT source, weight, accuracy, is_contrarian, sample_size
                    FROM source_weights
                    WHERE belief_version = ?
                    ORDER BY weight DESC
                """, (expected_version,))

            weights = {}
            contrarian_sources = set()
            for row in cursor:
                weights[row["source"]] = row["weight"]
                if row["is_contrarian"]:
                    contrarian_sources.add(row["source"])

            if read_belief_version() == expected_version:
                return {
                    "weights": weights,
                    "contrarian_sources": contrarian_sources,
                    "belief_version": expected_version,
                }
    finally:
        conn.close()

    return {
        "weights": {},
        "contrarian_sources": set(),
        "belief_version": read_belief_version(),
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
    belief_version = state.get("belief_version", 0)

    # Compute weights
    weights = compute_weights_from_beliefs(beliefs, min_samples)

    # Save to database
    db = Database(Path(db_path))
    await db.connect()

    try:
        await save_weights_to_db(db, weights, belief_version=belief_version)
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

    print(
        f"\n{'Source':<30} {'Weight':<10} {'Norm':<10} "
        f"{'Accuracy':<10} {'Type':<12} {'Samples':<10}"
    )
    print("-" * 80)

    for source, data in sorted_weights:
        accuracy = data.get("accuracy")
        acc_str = f"{accuracy:.1%}" if accuracy else "N/A"
        type_str = (
            "CONTRARIAN"
            if data.get("is_contrarian")
            else "MOMENTUM"
            if accuracy and accuracy > 0.5
            else "NEUTRAL"
        )
        norm = data.get("weight_normalized", 0)
        samples = data.get("sample_size", 0)

        print(
            f"{source:<30} {data['weight']:<10.4f} {norm:<10.4f} "
            f"{acc_str:<10} {type_str:<12} {samples:<10.0f}"
        )

    print("=" * 80)
