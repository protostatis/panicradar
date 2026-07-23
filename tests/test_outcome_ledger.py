"""
Tests for the persistent prediction outcome ledger.

Covers:
- Outcome write creates row with correct timestamps
- Idempotent writes (UNIQUE constraint enforcement)
- claim_pending_outcomes atomically claims and filters correctly
- Evaluation updates price_after, correct, evaluated_at
- Restart safety (outcomes survive DB disconnect/reconnect)
- get_source_performance accuracy calculation
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest

from crypto_sentiment_crawler.analysis.outcomes import (
    EVALUATOR_VERSION,
    claim_pending_outcomes,
    evaluate_outcome,
    get_source_performance,
    write_outcome,
)
from crypto_sentiment_crawler.storage.db import Database


@pytest.fixture
async def db():
    """Create a temp-file SQLite database for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    database = Database(db_path=db_path)
    await database.connect()
    yield database
    await database.close()
    # Clean up temp file
    db_path.unlink(missing_ok=True)

    # Also remove WAL/SHM files if they exist
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        p.unlink(missing_ok=True)


# ── Outcome write ──────────────────────────────────────────────────────────


class TestWriteOutcome:
    async def test_creates_row_with_correct_timestamps(self, db):
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)

        row_id = await write_outcome(
            db=db,
            source="reddit_bitcoin",
            signal_timestamp=now,
            target_timestamp=target,
            calibrated_score=0.75,
            price_before=50000.0,
            price_before_timestamp=now,
        )
        assert row_id > 0

        # Verify stored data
        cursor = await db.conn.execute(
            "SELECT * FROM prediction_outcomes WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["source"] == "reddit_bitcoin"
        assert row["calibrated_score"] == 0.75
        assert row["price_before"] == 50000.0
        assert row["evaluator_version"] == EVALUATOR_VERSION
        assert row["price_after"] is None  # Not evaluated yet

    async def test_idempotent_same_source_timestamp_version(self, db):
        """Writing the same (source, signal_ts, version) twice updates, no dup."""
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)

        row_id_1 = await write_outcome(
            db=db,
            source="reddit_ethereum",
            signal_timestamp=now,
            target_timestamp=target,
            calibrated_score=0.6,
            price_before=3000.0,
        )
        assert row_id_1 > 0

        # Write again with different score — should update, not insert new
        row_id_2 = await write_outcome(
            db=db,
            source="reddit_ethereum",
            signal_timestamp=now,
            target_timestamp=target,
            calibrated_score=0.8,  # Updated score
            price_before=3100.0,  # Updated price
        )
        assert row_id_2 == row_id_1  # Same row ID

        # Verify only one row and updated values
        cursor = await db.conn.execute(
            "SELECT * FROM prediction_outcomes WHERE source = ?",
            ("reddit_ethereum",),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["calibrated_score"] == 0.8
        assert rows[0]["price_before"] == 3100.0

    async def test_different_sources_independent(self, db):
        """Different sources can share the same timestamp."""
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)

        id_a = await write_outcome(
            db=db, source="reddit_a", signal_timestamp=now,
            target_timestamp=target, calibrated_score=0.5, price_before=100.0,
        )
        id_b = await write_outcome(
            db=db, source="reddit_b", signal_timestamp=now,
            target_timestamp=target, calibrated_score=-0.3, price_before=100.0,
        )
        assert id_a != id_b

        cursor = await db.conn.execute(
            "SELECT COUNT(*) as cnt FROM prediction_outcomes"
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2

    async def test_different_versions_independent(self, db):
        """Different evaluator versions can share same source+timestamp."""
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)

        id_v1 = await write_outcome(
            db=db, source="reddit_test", signal_timestamp=now,
            target_timestamp=target, calibrated_score=0.5,
            price_before=100.0, evaluator_version="1.0",
        )
        id_v2 = await write_outcome(
            db=db, source="reddit_test", signal_timestamp=now,
            target_timestamp=target, calibrated_score=0.5,
            price_before=100.0, evaluator_version="2.0",
        )
        assert id_v1 != id_v2

        cursor = await db.conn.execute(
            "SELECT COUNT(*) as cnt FROM prediction_outcomes"
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2


# ── Pending outcomes ───────────────────────────────────────────────────────


class TestClaimPendingOutcomes:
    async def test_returns_rows_with_elapsed_target_and_no_evaluation(self, db):
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=1)  # Target already elapsed
        future_target = now + timedelta(hours=4)  # Not yet elapsed

        # Row with elapsed target, not evaluated → should be pending
        await write_outcome(
            db=db, source="reddit_elapsed", signal_timestamp=now - timedelta(hours=5),
            target_timestamp=past_target, calibrated_score=0.5, price_before=100.0,
        )
        # Row with future target → not pending yet
        await write_outcome(
            db=db, source="reddit_future", signal_timestamp=now,
            target_timestamp=future_target, calibrated_score=-0.3, price_before=100.0,
        )

        pending = await claim_pending_outcomes(db, now=now)
        assert len(pending) == 1
        assert pending[0]["source"] == "reddit_elapsed"

    async def test_excludes_already_evaluated_rows(self, db):
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        row_id = await write_outcome(
            db=db, source="reddit_eval", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=0.5, price_before=100.0,
        )

        # Evaluate it
        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=105.0,
            price_after_timestamp=now, correct=True, direction="up",
        )

        pending = await claim_pending_outcomes(db, now=now)
        assert len(pending) == 0  # Evaluated, not pending

    async def test_empty_when_no_matching_rows(self, db):
        pending = await claim_pending_outcomes(db)
        assert pending == []

    async def test_respects_abstained_flag(self, db):
        """Rows marked as abstained should not appear as pending."""
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        row_id = await write_outcome(
            db=db, source="reddit_abstain", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=0.5, price_before=100.0,
        )

        # Manually set abstained
        await db.conn.execute(
            "UPDATE prediction_outcomes SET abstained = 1 WHERE id = ?",
            (row_id,),
        )
        await db.conn.commit()

        pending = await claim_pending_outcomes(db, now=now)
        assert len(pending) == 0


# ── Outcome evaluation ─────────────────────────────────────────────────────


class TestEvaluateOutcome:
    async def test_updates_price_after_and_correct_fields(self, db):
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        row_id = await write_outcome(
            db=db, source="reddit_eval", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=0.8, price_before=100.0,
        )

        eval_time = datetime.now(timezone.utc)
        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=110.0,
            price_after_timestamp=eval_time, correct=True, direction="up",
            price_gap_seconds=14400.0,
        )

        cursor = await db.conn.execute(
            "SELECT * FROM prediction_outcomes WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        assert row["price_after"] == 110.0
        assert row["correct"] == 1
        assert row["direction"] == "up"
        assert row["price_gap_seconds"] == 14400.0
        assert row["evaluated_at"] is not None

    async def test_incorrect_prediction(self, db):
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        row_id = await write_outcome(
            db=db, source="reddit_wrong", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=-0.7, price_before=100.0,
        )

        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=110.0,
            price_after_timestamp=datetime.now(timezone.utc), correct=False, direction="down",
        )

        cursor = await db.conn.execute(
            "SELECT correct FROM prediction_outcomes WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        assert row["correct"] == 0

    async def test_multiple_outcomes_independent(self, db):
        """Evaluating one outcome doesn't affect others."""
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        id_a = await write_outcome(
            db=db, source="reddit_a", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=0.5, price_before=100.0,
        )
        id_b = await write_outcome(
            db=db, source="reddit_b", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=-0.5, price_before=100.0,
        )

        await evaluate_outcome(
            db=db, outcome_id=id_a, price_after=105.0,
            price_after_timestamp=datetime.now(timezone.utc), correct=True, direction="up",
        )

        # Row B should still be unevaluated
        cursor = await db.conn.execute(
            "SELECT price_after FROM prediction_outcomes WHERE id = ?", (id_b,)
        )
        row = await cursor.fetchone()
        assert row["price_after"] is None


# ── Restart safety ─────────────────────────────────────────────────────────


class TestRestartSafety:
    async def test_outcomes_survive_db_reconnect(self, db):
        """Outcomes written before a "restart" are still there after reconnect."""
        now = datetime.now(timezone.utc)
        target = now + timedelta(hours=4)

        await write_outcome(
            db=db, source="reddit_survive", signal_timestamp=now,
            target_timestamp=target, calibrated_score=0.6, price_before=100.0,
        )

        # Close and reopen (simulates restart)
        db_path = db.db_path
        await db.close()

        db2 = Database(db_path=db_path)
        await db2.connect()

        pending = await claim_pending_outcomes(db2, now=now + timedelta(hours=5))
        assert len(pending) == 1
        assert pending[0]["source"] == "reddit_survive"
        assert pending[0]["calibrated_score"] == 0.6

        await db2.close()

    async def test_evaluated_outcomes_survive_restart(self, db):
        """Evaluated outcomes remain in the ledger after restart."""
        now = datetime.now(timezone.utc)
        past_target = now - timedelta(hours=2)

        row_id = await write_outcome(
            db=db, source="reddit_persist", signal_timestamp=now - timedelta(hours=6),
            target_timestamp=past_target, calibrated_score=0.5, price_before=100.0,
        )

        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=105.0,
            price_after_timestamp=datetime.now(timezone.utc), correct=True, direction="up",
        )

        # Restart
        db_path = db.db_path
        await db.close()

        db2 = Database(db_path=db_path)
        await db2.connect()

        cursor = await db2.conn.execute(
            "SELECT * FROM prediction_outcomes WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["price_after"] == 105.0
        assert row["correct"] == 1
        assert row["direction"] == "up"
        assert row["evaluated_at"] is not None

        await db2.close()


# ── Source performance ─────────────────────────────────────────────────────


class TestSourcePerformance:
    async def test_accuracy_calculation(self, db):
        """get_source_performance computes correct accuracy."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=4)

        # 3 correct, 1 incorrect
        for i, (score, correct) in enumerate([
            (0.6, True),
            (-0.5, True),
            (0.3, False),
            (0.7, True),
        ]):
            row_id = await write_outcome(
                db=db, source="reddit_test",
                signal_timestamp=now - timedelta(hours=8 + i),
                target_timestamp=past - timedelta(hours=4 + i),
                calibrated_score=score, price_before=100.0,
            )
            await evaluate_outcome(
                db=db, outcome_id=row_id, price_after=105.0,
                price_after_timestamp=now, correct=correct,
                direction="up" if score > 0 else "down",
            )

        perf = await get_source_performance(db, source="reddit_test", days=30)
        assert perf["total_evaluated"] == 4
        assert perf["correct"] == 3
        assert perf["accuracy"] == pytest.approx(0.75)

    async def test_empty_source_returns_none_accuracy(self, db):
        """No evaluated outcomes → None accuracy."""
        perf = await get_source_performance(db, source="reddit_nonexistent")
        assert perf["total_evaluated"] == 0
        assert perf["accuracy"] is None

    async def test_respects_days_filter(self, db):
        """Only outcomes within the requested days window are counted."""
        now = datetime.now(timezone.utc)
        old_signal = now - timedelta(days=60)
        old_target = old_signal + timedelta(hours=4)

        row_id = await write_outcome(
            db=db, source="reddit_old",
            signal_timestamp=old_signal, target_timestamp=old_target,
            calibrated_score=0.5, price_before=100.0,
        )
        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=105.0,
            price_after_timestamp=old_target, correct=True, direction="up",
        )

        # 30-day window excludes the 60-day-old outcome
        perf = await get_source_performance(db, source="reddit_old", days=30)
        assert perf["total_evaluated"] == 0

        # 90-day window includes it
        perf = await get_source_performance(db, source="reddit_old", days=90)
        assert perf["total_evaluated"] == 1
        assert perf["correct"] == 1

    async def test_source_case_insensitive(self, db):
        """Source matching should be case-insensitive (stored lowercase)."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=4)

        row_id = await write_outcome(
            db=db, source="REDDIT_CASE", signal_timestamp=now - timedelta(hours=8),
            target_timestamp=past, calibrated_score=0.5, price_before=100.0,
        )
        await evaluate_outcome(
            db=db, outcome_id=row_id, price_after=105.0,
            price_after_timestamp=now, correct=True, direction="up",
        )

        # Query with different case should still find it
        perf = await get_source_performance(db, source="Reddit_Case", days=30)
        assert perf["total_evaluated"] == 1
