"""Persistent prediction outcome ledger for auditable evaluation.

Provides a thin wrapper over the prediction_outcomes table in the database.
Higher-level modules (orchestrator, dashboards) import these functions rather
than calling db methods directly so the outcome lifecycle is centralized.
"""

from datetime import datetime

from ..storage.db import Database

EVALUATOR_VERSION = "1.0"


async def write_outcome(
    db: Database,
    source: str,
    signal_timestamp: datetime,
    target_timestamp: datetime,
    calibrated_score: float | None = None,
    price_before: float | None = None,
    price_before_timestamp: datetime | None = None,
    evaluator_version: str = EVALUATOR_VERSION,
) -> int:
    """Insert or update an outcome row (idempotent via UNIQUE constraint).

    Returns the row id.
    """
    return await db.upsert_outcome(
        source=source,
        signal_timestamp=signal_timestamp,
        target_timestamp=target_timestamp,
        calibrated_score=calibrated_score,
        price_before=price_before,
        price_before_timestamp=price_before_timestamp,
        evaluator_version=evaluator_version,
    )


async def get_pending_outcomes(
    db: Database, now: datetime | None = None
) -> list[dict]:
    """Find signal_timestamps whose target has elapsed but haven't been evaluated.

    Returns rows where target_timestamp < now AND price_after IS NULL.
    """
    return await db.get_pending_outcomes(now=now)


async def get_source_performance(
    db: Database, source: str, days: int = 30
) -> dict:
    """Compute accuracy for a source from the outcome ledger."""
    return await db.get_source_performance(source=source, days=days)


async def evaluate_outcome(
    db: Database,
    outcome_id: int,
    price_after: float,
    price_after_timestamp: datetime,
    correct: bool,
    direction: str,
    price_gap_seconds: float | None = None,
) -> None:
    """Update an outcome row with evaluation results."""
    await db.mark_outcome_evaluated(
        outcome_id=outcome_id,
        price_after=price_after,
        price_after_timestamp=price_after_timestamp,
        correct=correct,
        direction=direction,
        price_gap_seconds=price_gap_seconds,
    )
