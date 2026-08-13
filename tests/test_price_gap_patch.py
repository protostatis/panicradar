"""Safety and integrity coverage for the reusable spec-driven price gap patch."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from crypto_sentiment_crawler.maintenance import price_gap_patch as patch
from crypto_sentiment_crawler.maintenance.price_gap_spec import (
    PriceGapSpec,
    PriceGapSpecError,
    parse_spec_json,
)

# The historical August 2026 incident spec, kept as the only legacy reference.
SPEC = patch.LEGACY_V1_SPEC


def _make_spec(
    *,
    incident_id: str = "dyn-alpha-20260801",
    start_hour: str = "2026-08-01T00:00:00+00:00",
    end_exclusive: str = "2026-08-01T02:00:00+00:00",
    coins: dict[str, str] | None = None,
) -> PriceGapSpec:
    coins = coins or {"BTC": "bitcoin", "ETH": "ethereum"}
    raw = {
        "schema_version": 1,
        "incident_id": incident_id,
        "provider": "coingecko",
        "source_tag": f"coingecko_gap_backfill:{incident_id}",
        "start_hour": start_hour,
        "end_exclusive": end_exclusive,
        "coins": coins,
    }
    return parse_spec_json(json.dumps(raw))


# Two dynamic specs with distinct, non-legacy candidate counts.
DYNAMIC_A = _make_spec()  # BTC + ETH, 2 hours -> 4 candidates
DYNAMIC_B = _make_spec(
    incident_id="dyn-beta-20260802",
    start_hour="2026-08-02T00:00:00+00:00",
    end_exclusive="2026-08-02T03:00:00+00:00",
    coins={"SOL": "solana"},
)  # SOL, 3 hours -> 3 candidates


def _payload(spec: PriceGapSpec, *, jitter_ms: int = 0) -> dict[str, list[list[float]]]:
    prices = []
    caps = []
    volumes = []
    for index, epoch in enumerate(spec.expected_hour_epochs):
        timestamp_ms = epoch * 1000 + jitter_ms
        prices.append([timestamp_ms, 100.0 + index])
        caps.append([timestamp_ms, 1_000_000.0 + index])
        volumes.append([timestamp_ms, 10_000.0 + index])
    return {"prices": prices, "market_caps": caps, "total_volumes": volumes}


def _attempts(spec: PriceGapSpec = SPEC) -> dict[str, list[patch.FetchAttempt]]:
    payload = _payload(spec, jitter_ms=30_000)
    return {
        coin: [patch.make_fixture_attempt(coin, payload, spec=spec)]
        for coin in spec.coin_mapping
    }


def _create_artifact(tmp_path: Path, spec: PriceGapSpec = SPEC) -> tuple[Path, dict]:
    artifact = (tmp_path / f"price-gap-{spec.incident_id}.sqlite").resolve()
    report = patch.create_patch_artifact(artifact, _attempts(spec), spec=spec)
    return artifact, report


def _create_target(path: Path, *, journal_mode: str | None = None) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE price_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                coin VARCHAR(10) NOT NULL,
                price_usd FLOAT NOT NULL,
                volume_24h FLOAT,
                market_cap FLOAT,
                source VARCHAR(50) DEFAULT 'coingecko'
            )
            """
        )
        connection.execute("CREATE INDEX idx_price_data_time ON price_data(timestamp, coin)")
        if journal_mode is not None:
            if journal_mode.casefold() in {"off", "memory"}:
                connection.execute(
                    "INSERT INTO price_data "
                    "(timestamp, coin, price_usd, volume_24h, market_cap, source) "
                    "VALUES ('2000-01-01T00:00:00+00:00', 'BTC', 1, 1, 1, 'fixture')"
                )
            connection.execute(f"PRAGMA journal_mode = {journal_mode}")
        connection.commit()
    finally:
        connection.close()


def _add_orphan_baseline(target: Path) -> None:
    connection = sqlite3.connect(target)
    try:
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
        )
        connection.executemany(
            "INSERT INTO child (id, parent_id) VALUES (?, ?)", [(1, 9001), (2, 9002)]
        )
        connection.commit()
    finally:
        connection.close()


def _apply(
    artifact: Path,
    target: Path,
    backup: Path,
    digest: str,
    spec: PriceGapSpec = SPEC,
) -> dict:
    return patch.apply_patch(
        artifact,
        target,
        backup,
        spec=spec,
        expected_artifact_sha256=digest,
        confirm_spec_sha256=spec.sha256,
        confirm_candidates=spec.candidate_count,
        confirm_incident=spec.incident_id,
        confirm_target=str(target.resolve()),
        writers_paused=True,
    )


def _counts(target: Path) -> tuple[int, int, int]:
    connection = sqlite3.connect(target)
    try:
        counts = []
        for table in ("price_data", "price_gap_patch_runs", "price_gap_patch_rows"):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            count = (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if exists
                else 0
            )
            counts.append(count)
        return tuple(counts)  # type: ignore[return-value]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Historical / preserved safety tests (adapted to pass specs)
# ---------------------------------------------------------------------------


def test_derives_exact_canonical_product_and_rejects_missing_metric() -> None:
    candidates = patch.derive_candidates(
        "BTC", json.dumps(_payload(SPEC, jitter_ms=60_000)).encode(), spec=SPEC
    )

    assert len(candidates) == SPEC.hours
    assert candidates[0].hour_epoch == SPEC.expected_hour_epochs[0]
    assert candidates[-1].hour_epoch == SPEC.expected_hour_epochs[-1]
    assert candidates[0].timestamp == "2026-08-11T02:00:00+00:00"
    assert candidates[-1].timestamp == "2026-08-13T13:00:00+00:00"

    malformed = _payload(SPEC)
    malformed["prices"].pop()
    with pytest.raises(patch.ArtifactValidationError, match="prices is missing 1 expected"):
        patch.derive_candidates("BTC", json.dumps(malformed).encode(), spec=SPEC)


def test_artifact_is_sealed_validated_and_sidecars_are_authoritative(tmp_path: Path) -> None:
    artifact, report = _create_artifact(tmp_path)

    assert report["candidates"] == SPEC.candidate_count
    assert report["status"] == "valid"
    assert (artifact.stat().st_mode & 0o777) == 0o444
    assert Path(f"{artifact}.sha256").is_file()
    raw_file = next(path for path in Path(f"{artifact}.raw").iterdir() if path.suffix == ".json")
    os.chmod(raw_file, 0o600)
    raw_file.write_bytes(b"tampered")
    with pytest.raises(patch.ArtifactValidationError, match="sidecar mismatch"):
        patch.validate_artifact(artifact, spec=SPEC)


def test_artifact_validation_rejects_wrong_raw_response_linkage(tmp_path: Path) -> None:
    artifact, _ = _create_artifact(tmp_path)
    receipt = Path(f"{artifact}.sha256")
    os.chmod(artifact, 0o600)
    with sqlite3.connect(artifact) as connection:
        first_id, second_id = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM raw_responses WHERE successful = 1 ORDER BY id LIMIT 2"
            ).fetchall()
        ]
        connection.execute(
            "UPDATE candidates SET raw_response_id = ? WHERE raw_response_id = ?",
            (second_id, first_id),
        )
    digest = patch._sha256_file(artifact)
    os.chmod(receipt, 0o600)
    receipt.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")

    with pytest.raises(patch.ArtifactValidationError, match="linkage mismatch"):
        patch.validate_artifact(artifact, spec=SPEC)


def test_validated_snapshot_resists_source_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, report = _create_artifact(tmp_path)
    replacement = tmp_path / "replacement.sqlite"
    original_validate = patch.validate_artifact

    def replace_after_validation(*args, **kwargs):
        validated = original_validate(*args, **kwargs)
        replacement.write_bytes(b"not a database")
        os.replace(replacement, artifact)
        return validated

    monkeypatch.setattr(patch, "validate_artifact", replace_after_validation)
    snapshot_report, candidates = patch._validated_artifact_snapshot(
        artifact,
        expected_digest=report["artifact_sha256"],
        spec=SPEC,
    )

    assert snapshot_report["artifact_sha256"] == report["artifact_sha256"]
    assert len(candidates) == SPEC.candidate_count


@pytest.mark.parametrize("fail_after", [1, 300, 599])
def test_apply_failure_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after: int
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / f"target-{fail_after}.db").resolve()
    backup = (tmp_path / f"target-{fail_after}.backup.db").resolve()
    _create_target(target)
    original_verify = patch._verify_applied_run

    def fail_before_commit(connection: sqlite3.Connection, run: sqlite3.Row) -> None:
        connection.execute(
            "DELETE FROM price_gap_patch_rows WHERE rowid IN "
            "(SELECT rowid FROM price_gap_patch_rows WHERE run_id = ? LIMIT ?)",
            (run["run_id"], SPEC.candidate_count - fail_after),
        )
        raise RuntimeError("injected apply failure")

    monkeypatch.setattr(patch, "_verify_applied_run", fail_before_commit)
    with pytest.raises(RuntimeError, match="injected apply failure"):
        _apply(artifact, target, backup, artifact_report["artifact_sha256"])
    monkeypatch.setattr(patch, "_verify_applied_run", original_verify)

    assert _counts(target) == (0, 0, 0)
    assert backup.is_file()
    with sqlite3.connect(backup) as backup_connection:
        assert backup_connection.execute("SELECT COUNT(*) FROM price_data").fetchone()[0] == 0


def test_apply_rollback_reapply_preserves_audit_history(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    _create_target(target)

    first = _apply(
        artifact,
        target,
        (tmp_path / "pre-apply-1.db").resolve(),
        artifact_report["artifact_sha256"],
    )
    assert first["inserted"] == SPEC.candidate_count
    assert _counts(target) == (SPEC.candidate_count, 1, SPEC.candidate_count)
    assert _apply(
        artifact,
        target,
        (tmp_path / "unused-existing-apply.db").resolve(),
        artifact_report["artifact_sha256"],
    )["status"] == "already_applied"
    assert not (tmp_path / "unused-existing-apply.db").exists()

    first_rollback_backup = (tmp_path / "pre-rollback-1.db").resolve()
    rolled_back = patch.rollback_patch(
        target,
        first_rollback_backup,
        run_id=first["run_id"],
        confirm_run_id=first["run_id"],
        confirm_incident=SPEC.incident_id,
        confirm_target=str(target),
        writers_paused=True,
    )
    assert rolled_back["deleted"] == SPEC.candidate_count
    assert _counts(target) == (0, 1, SPEC.candidate_count)

    second = _apply(
        artifact,
        target,
        (tmp_path / "pre-apply-2.db").resolve(),
        artifact_report["artifact_sha256"],
    )
    assert second["status"] == "applied"
    assert second["run_id"] != first["run_id"]
    assert _counts(target) == (SPEC.candidate_count, 2, SPEC.candidate_count * 2)

    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        first_run = connection.execute(
            "SELECT * FROM price_gap_patch_runs WHERE run_id = ?", (first["run_id"],)
        ).fetchone()
        assert first_run["state"] == "rolled_back"
        assert first_run["rollback_backup_path"] == str(first_rollback_backup)
        assert first_run["rollback_backup_sha256"] == rolled_back["backup_sha256"]
        assert first_run["rolled_back_count"] == SPEC.candidate_count
    finally:
        connection.close()


def test_apply_and_rollback_preserve_preexisting_foreign_key_baseline(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target-with-orphans.db").resolve()
    _create_target(target)
    _add_orphan_baseline(target)
    with patch._readonly_connection(target) as connection:
        baseline = patch._foreign_key_violations(connection)

    applied = _apply(
        artifact,
        target,
        (tmp_path / "pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
    )
    assert applied["foreign_key_baseline_count"] == 2
    assert applied["foreign_key_baseline_sha256"] == patch._foreign_key_baseline_digest(baseline)
    with patch._readonly_connection(target) as connection:
        assert patch._foreign_key_violations(connection) == baseline

    rolled_back = patch.rollback_patch(
        target,
        (tmp_path / "pre-rollback.db").resolve(),
        run_id=applied["run_id"],
        confirm_run_id=applied["run_id"],
        confirm_incident=SPEC.incident_id,
        confirm_target=str(target),
        writers_paused=True,
    )
    assert rolled_back["foreign_key_baseline_count"] == 2
    assert rolled_back["foreign_key_baseline_sha256"] == patch._foreign_key_baseline_digest(
        baseline
    )
    with patch._readonly_connection(target) as connection:
        assert patch._foreign_key_violations(connection) == baseline


@pytest.mark.parametrize("change", ["add", "remove"])
def test_changed_foreign_key_baseline_aborts_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / f"target-{change}.db").resolve()
    backup = (tmp_path / f"target-{change}.backup.db").resolve()
    _create_target(target)
    _add_orphan_baseline(target)
    original_verify = patch._verify_applied_run

    def alter_baseline(connection: sqlite3.Connection, run: sqlite3.Row) -> None:
        original_verify(connection, run)
        if change == "add":
            connection.execute("PRAGMA defer_foreign_keys = ON")
            connection.execute("INSERT INTO child (id, parent_id) VALUES (3, 9003)")
        else:
            connection.execute("DELETE FROM child WHERE id = 1")

    monkeypatch.setattr(patch, "_verify_applied_run", alter_baseline)
    with pytest.raises(patch.ArtifactValidationError, match="foreign-key baseline changed"):
        _apply(artifact, target, backup, artifact_report["artifact_sha256"])

    assert _counts(target) == (0, 0, 0)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 2


def test_target_rejects_foreign_key_referencing_price_data(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    _create_target(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "CREATE TABLE price_reference "
            "(id INTEGER PRIMARY KEY, price_id INTEGER REFERENCES price_data(id))"
        )

    with pytest.raises(patch.ArtifactValidationError, match="referencing price_data"):
        _apply(
            artifact,
            target,
            (tmp_path / "backup.db").resolve(),
            artifact_report["artifact_sha256"],
        )
    assert _counts(target) == (0, 0, 0)


def test_apply_backup_contains_committed_wal_state_and_no_patch_rows(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "wal-target.db").resolve()
    _create_target(target)
    wal_connection = sqlite3.connect(target)
    try:
        assert wal_connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        wal_connection.execute("PRAGMA wal_autocheckpoint = 0")
        wal_connection.execute(
            """
            INSERT INTO price_data
                (timestamp, coin, price_usd, volume_24h, market_cap, source)
            VALUES ('2026-08-10T00:00:00+00:00', 'BTC', 1, 1, 1, 'preexisting')
            """
        )
        wal_connection.commit()
        assert Path(f"{target}-wal").exists()

        backup = (tmp_path / "wal-pre-apply.db").resolve()
        result = _apply(artifact, target, backup, artifact_report["artifact_sha256"])
        assert result["inserted"] == SPEC.candidate_count
        with sqlite3.connect(backup) as backup_connection:
            assert backup_connection.execute("SELECT COUNT(*) FROM price_data").fetchone()[0] == 1
            assert backup_connection.execute(
                "SELECT source FROM price_data"
            ).fetchone()[0] == "preexisting"
    finally:
        wal_connection.close()


def test_write_lock_is_held_during_backup_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "locked-target.db").resolve()
    _create_target(target)
    backup = (tmp_path / "locked-target.backup.db").resolve()
    backup_started = threading.Event()
    writer_finished = threading.Event()
    writer_result: list[str] = []
    original_backup = patch._backup_database

    def competing_writer() -> None:
        backup_started.wait(timeout=5)
        connection = sqlite3.connect(target, timeout=0.05)
        try:
            connection.execute(
                """
                INSERT INTO price_data
                    (timestamp, coin, price_usd, volume_24h, market_cap, source)
                VALUES ('2026-08-11T02:00:00+00:00', 'BTC', 1, 1, 1, 'racer')
                """
            )
            connection.commit()
            writer_result.append("inserted")
        except sqlite3.OperationalError as error:
            writer_result.append(str(error))
        finally:
            connection.close()
            writer_finished.set()

    def slow_backup(source: Path, destination: Path) -> str:
        backup_started.set()
        assert writer_finished.wait(timeout=5)
        time.sleep(0.01)
        return original_backup(source, destination)

    writer = threading.Thread(target=competing_writer)
    writer.start()
    monkeypatch.setattr(patch, "_backup_database", slow_backup)
    try:
        result = _apply(artifact, target, backup, artifact_report["artifact_sha256"])
    finally:
        writer.join(timeout=5)

    assert result["inserted"] == SPEC.candidate_count
    assert writer_result and "locked" in writer_result[0].casefold()
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM price_data WHERE source = 'racer'"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-11T02:00:00Z",
        "2026-08-11T02:17:00",
        "2026-08-10T22:30:00-04:00",
    ],
)
def test_inspect_detects_any_parseable_row_in_candidate_utc_bucket(
    tmp_path: Path, timestamp: str
) -> None:
    artifact, _ = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    _create_target(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            """
            INSERT INTO price_data
                (timestamp, coin, price_usd, volume_24h, market_cap, source)
            VALUES (?, ' btc ', 1, 1, 1, 'existing')
            """,
            (timestamp,),
        )

    report = patch.inspect_target(artifact, target, spec=SPEC)
    assert report["target_status"] == "conflict"
    assert report["conflict_count"] == 1


def test_extra_row_prevents_already_applied_classification(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    _create_target(target)
    _apply(
        artifact,
        target,
        (tmp_path / "pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
    )
    with sqlite3.connect(target) as connection:
        connection.execute(
            """
            INSERT INTO price_data
                (timestamp, coin, price_usd, volume_24h, market_cap, source)
            VALUES ('2026-08-11T02:45:00+00:00', 'BTC', 1, 1, 1, 'extra')
            """
        )

    with pytest.raises(patch.ArtifactValidationError, match="unexpected row"):
        patch.inspect_target(artifact, target, spec=SPEC)


def test_rollback_refuses_changed_row_and_wrong_confirmation(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    _create_target(target)
    applied = _apply(
        artifact,
        target,
        (tmp_path / "pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
    )
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE price_data SET price_usd = price_usd + 1 WHERE id = 1"
        )

    rollback_backup = (tmp_path / "pre-rollback.db").resolve()
    with pytest.raises(patch.ConfirmationError, match="confirm-run-id"):
        patch.rollback_patch(
            target,
            rollback_backup,
            run_id=applied["run_id"],
            confirm_run_id="wrong",
            confirm_incident=SPEC.incident_id,
            confirm_target=str(target),
            writers_paused=True,
        )
    with pytest.raises(patch.ArtifactValidationError, match="no longer matches"):
        patch.rollback_patch(
            target,
            rollback_backup,
            run_id=applied["run_id"],
            confirm_run_id=applied["run_id"],
            confirm_incident=SPEC.incident_id,
            confirm_target=str(target),
            writers_paused=True,
        )
    assert not rollback_backup.exists()
    assert _counts(target) == (SPEC.candidate_count, 1, SPEC.candidate_count)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"confirm_incident": "wrong"}, "confirm-incident"),
        ({"confirm_target": "/wrong/target.db"}, "confirm-target"),
        ({"writers_paused": False}, "writers are paused"),
        ({"expected_artifact_sha256": "0" * 64}, "explicit confirmation"),
        ({"confirm_spec_sha256": "0" * 64}, "confirm-spec-sha256"),
        ({"confirm_candidates": SPEC.candidate_count + 1}, "confirm-candidates"),
    ],
)
def test_apply_rejects_each_bad_confirmation_without_mutation(
    tmp_path: Path, overrides: dict, message: str
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    backup = (tmp_path / "backup.db").resolve()
    _create_target(target)
    arguments = {
        "spec": SPEC,
        "expected_artifact_sha256": artifact_report["artifact_sha256"],
        "confirm_spec_sha256": SPEC.sha256,
        "confirm_candidates": SPEC.candidate_count,
        "confirm_incident": SPEC.incident_id,
        "confirm_target": str(target),
        "writers_paused": True,
    }
    arguments.update(overrides)

    with pytest.raises(patch.PriceGapPatchError, match=message):
        patch.apply_patch(artifact, target, backup, **arguments)
    assert _counts(target) == (0, 0, 0)
    assert not backup.exists()


def test_cli_reports_guard_failure_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    target = (tmp_path / "target.db").resolve()
    backup = (tmp_path / "backup.db").resolve()
    _create_target(target)

    exit_code = patch.main(
        [
            "apply",
            "--spec",
            str(Path(patch.__file__).parent / "specs" / "vpn-dns-20260811.json"),
            "--artifact",
            str(artifact),
            "--artifact-sha256",
            artifact_report["artifact_sha256"],
            "--confirm-spec-sha256",
            SPEC.sha256,
            "--confirm-candidates",
            str(SPEC.candidate_count),
            "--target",
            str(target),
            "--backup",
            str(backup),
            "--confirm-incident",
            SPEC.incident_id,
            "--confirm-target",
            str(target),
        ]
    )

    assert exit_code == 2
    assert "writers are paused" in capsys.readouterr().err
    assert _counts(target) == (0, 0, 0)
    assert not backup.exists()


def test_apply_rejects_unsafe_journal_and_incompatible_manifest(tmp_path: Path) -> None:
    artifact, artifact_report = _create_artifact(tmp_path)
    unsafe = (tmp_path / "unsafe.db").resolve()
    _create_target(unsafe)
    unsafe_connection = patch._readwrite_connection(unsafe)
    try:
        unsafe_connection.execute("PRAGMA journal_mode = MEMORY")
        with pytest.raises(patch.ArtifactValidationError, match="Unsafe target journal_mode"):
            patch._validate_target_storage(unsafe_connection)
    finally:
        unsafe_connection.close()

    incompatible = (tmp_path / "incompatible.db").resolve()
    _create_target(incompatible)
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE price_gap_patch_runs (run_id TEXT PRIMARY KEY)")
    with pytest.raises(patch.ArtifactValidationError, match="incomplete price gap manifest"):
        _apply(
            artifact,
            incompatible,
            (tmp_path / "incompatible-backup.db").resolve(),
            artifact_report["artifact_sha256"],
        )
    assert _counts(incompatible) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Strict spec parser coverage
# ---------------------------------------------------------------------------


def _raw_spec(**overrides: object) -> dict:
    raw: dict[str, object] = {
        "schema_version": 1,
        "incident_id": "spec-parser-01",
        "provider": "coingecko",
        "source_tag": "coingecko_gap_backfill:spec-parser-01",
        "start_hour": "2026-08-01T00:00:00+00:00",
        "end_exclusive": "2026-08-01T02:00:00+00:00",
        "coins": {"BTC": "bitcoin"},
    }
    raw.update(overrides)
    return raw


def test_spec_parser_rejects_duplicate_keys() -> None:
    raw = (
        '{"schema_version": 1, "schema_version": 1, '
        '"incident_id": "spec-parser-01", "provider": "coingecko", '
        '"source_tag": "coingecko_gap_backfill:spec-parser-01", '
        '"start_hour": "2026-08-01T00:00:00+00:00", '
        '"end_exclusive": "2026-08-01T02:00:00+00:00", '
        '"coins": {"BTC": "bitcoin"}}'
    )
    with pytest.raises(PriceGapSpecError, match="Duplicate JSON key"):
        parse_spec_json(raw)


def test_spec_parser_rejects_unknown_keys() -> None:
    raw = _raw_spec()
    raw["mystery"] = True
    with pytest.raises(PriceGapSpecError, match="unknown="):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_missing_key() -> None:
    raw = _raw_spec()
    del raw["coins"]
    with pytest.raises(PriceGapSpecError, match="missing="):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_excessive_hours() -> None:
    raw = _raw_spec(
        start_hour="2026-08-01T00:00:00+00:00",
        end_exclusive="2026-08-09T00:00:00+00:00",  # 8 days = 192 hours > 168
    )
    with pytest.raises(PriceGapSpecError, match="safety limit"):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_excessive_coins() -> None:
    coins = {f"COIN{i}": f"coin-{i}" for i in range(26)}
    raw = _raw_spec(coins=coins)
    with pytest.raises(PriceGapSpecError, match="between 1 and"):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_excessive_candidates() -> None:
    raw = _raw_spec(
        start_hour="2026-08-01T00:00:00+00:00",
        end_exclusive="2026-08-06T00:00:00+00:00",  # 120 hours
        coins={f"COIN{i}": f"coin-{i}" for i in range(20)},  # 120 * 20 = 2400 > 2000
    )
    with pytest.raises(PriceGapSpecError, match="candidate safety limit"):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_bad_source_tag() -> None:
    raw = _raw_spec(source_tag="coingecko_gap_backfill:other-incident")
    with pytest.raises(PriceGapSpecError, match="source_tag"):
        parse_spec_json(json.dumps(raw))


def test_spec_parser_rejects_end_before_start() -> None:
    raw = _raw_spec(
        start_hour="2026-08-01T04:00:00+00:00",
        end_exclusive="2026-08-01T02:00:00+00:00",
    )
    with pytest.raises(PriceGapSpecError, match="after start_hour"):
        parse_spec_json(json.dumps(raw))


def test_collection_rejects_future_end() -> None:
    spec = _make_spec(
        incident_id="future-end-01",
        start_hour="2099-01-01T00:00:00+00:00",
        end_exclusive="2099-01-01T02:00:00+00:00",
    )
    with pytest.raises(PriceGapSpecError, match="not be later than"):
        spec.ensure_collectable(now=__import__("datetime").datetime(2026, 8, 1, tzinfo=patch.UTC))


def test_spec_source_tag_is_deterministic_from_spec() -> None:
    assert SPEC.source_tag == f"{SPEC.provider}_gap_backfill:{SPEC.incident_id}"
    assert DYNAMIC_A.source_tag == f"{DYNAMIC_A.provider}_gap_backfill:{DYNAMIC_A.incident_id}"


# ---------------------------------------------------------------------------
# Artifact schema v2 / v1 adapter coverage
# ---------------------------------------------------------------------------


def test_validate_artifact_rejects_supplied_spec_mismatch(tmp_path: Path) -> None:
    artifact, _ = _create_artifact(tmp_path, spec=SPEC)
    with pytest.raises(patch.ArtifactValidationError, match="embedded artifact spec"):
        patch.validate_artifact(artifact, spec=DYNAMIC_A)


def test_validate_artifact_embeds_canonical_spec(tmp_path: Path) -> None:
    artifact, report = _create_artifact(tmp_path, spec=DYNAMIC_A)
    validated = patch.validate_artifact(artifact, spec=DYNAMIC_A)
    assert validated["schema_version"] == 2
    assert validated["spec_sha256"] == DYNAMIC_A.sha256
    assert report["spec_sha256"] == DYNAMIC_A.sha256


def _downgrade_artifact_to_v1(artifact: Path) -> None:
    """Strip v2 spec metadata and re-seal, simulating a historical v1 artifact."""
    artifact.chmod(0o600)
    connection = sqlite3.connect(artifact)
    try:
        connection.execute(
            "UPDATE patch_metadata SET value_json = '1' WHERE key = 'schema_version'"
        )
        connection.execute("DELETE FROM patch_metadata WHERE key IN ('spec_json', 'spec_sha256')")
        connection.commit()
    finally:
        connection.close()
    artifact.chmod(0o444)
    receipt = Path(f"{artifact}.sha256")
    receipt.chmod(0o600)
    receipt.write_text(f"{patch._sha256_file(artifact)}  {artifact.name}\n")
    receipt.chmod(0o444)


def test_v1_artifact_is_validated_against_legacy_spec_only(tmp_path: Path) -> None:
    artifact, _ = _create_artifact(tmp_path, spec=SPEC)
    _downgrade_artifact_to_v1(artifact)

    report = patch.validate_artifact(artifact, spec=SPEC)
    assert report["schema_version"] == 1
    assert report["incident_id"] == SPEC.incident_id

    with pytest.raises(patch.ArtifactValidationError, match="legacy v1 artifact"):
        patch.validate_artifact(artifact, spec=DYNAMIC_A)


# ---------------------------------------------------------------------------
# Manifest v1 inspect / rollback and v1 -> v2 migration
# ---------------------------------------------------------------------------


def _create_legacy_v1_manifest(target: Path, spec: PriceGapSpec = SPEC) -> str:
    """Create a production-equivalent v1 manifest with one fully applied run."""
    connection = sqlite3.connect(target)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        for table in patch.TARGET_MANIFEST_TABLE_NAMES:
            connection.execute(patch.TARGET_MANIFEST_TABLE_SQL_V1[table])
        connection.execute(
            "INSERT INTO price_gap_patch_schema (singleton, schema_version) VALUES (1, 1)"
        )
        payload = _payload(spec, jitter_ms=30_000)
        run_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO price_gap_patch_runs (
                run_id, incident_id, artifact_sha256, candidate_sha256, source_tag,
                applied_at, state, inserted_count, backup_path, backup_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?)
            """,
            (
                run_id,
                spec.incident_id,
                "a" * 64,
                "b" * 64,
                spec.source_tag,
                "2026-08-13T17:00:00+00:00",
                spec.candidate_count,
                "/absolute/legacy/pre-apply.db",
                "c" * 64,
            ),
        )
        for coin in spec.coin_mapping:
            attempt = patch.make_fixture_attempt(coin, payload, spec=spec)
            for candidate in patch.derive_candidates(
                coin, attempt.response_body, spec=spec
            ):
                cursor = connection.execute(
                    """
                    INSERT INTO price_data
                        (timestamp, coin, price_usd, volume_24h, market_cap, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.timestamp,
                        candidate.coin,
                        candidate.price_usd,
                        candidate.volume_24h,
                        candidate.market_cap,
                        spec.source_tag,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO price_gap_patch_rows (
                        run_id, candidate_coin, candidate_hour_epoch, price_data_id,
                        expected_timestamp, expected_price, expected_volume,
                        expected_market_cap, expected_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        candidate.coin,
                        candidate.hour_epoch,
                        int(cursor.lastrowid),
                        candidate.timestamp,
                        candidate.price_usd,
                        candidate.volume_24h,
                        candidate.market_cap,
                        spec.source_tag,
                    ),
                )
        connection.commit()
        return run_id
    finally:
        connection.close()


def test_v1_manifest_inspect_and_rollback_are_spec_free(tmp_path: Path) -> None:
    target = (tmp_path / "v1-target.db").resolve()
    _create_target(target)
    run_id = _create_legacy_v1_manifest(target)

    with patch._readonly_connection(target) as connection:
        assert patch._detect_manifest_version(connection) == 1

    report = patch.inspect_run(target, run_id)
    assert report["state"] == "applied"
    assert report["inserted_count"] == SPEC.candidate_count
    assert report["verification"] == "verified"
    assert report["spec_sha256"] is None  # v1 has no spec columns

    rolled_back = patch.rollback_patch(
        target,
        (tmp_path / "v1-pre-rollback.db").resolve(),
        run_id=run_id,
        confirm_run_id=run_id,
        confirm_incident=SPEC.incident_id,
        confirm_target=str(target),
        writers_paused=True,
    )
    assert rolled_back["deleted"] == SPEC.candidate_count
    assert _counts(target) == (0, 1, SPEC.candidate_count)


def test_v1_to_v2_migration_preserves_legacy_run(tmp_path: Path) -> None:
    target = (tmp_path / "migrate-target.db").resolve()
    _create_target(target)
    legacy_run_id = _create_legacy_v1_manifest(target)

    artifact, artifact_report = _create_artifact(tmp_path, spec=DYNAMIC_A)
    applied = _apply(
        artifact,
        target,
        (tmp_path / "migrate-pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
        spec=DYNAMIC_A,
    )
    assert applied["inserted"] == DYNAMIC_A.candidate_count

    with patch._readonly_connection(target) as connection:
        assert patch._detect_manifest_version(connection) == 2
        runs = connection.execute(
            "SELECT run_id, incident_id, inserted_count, spec_json, spec_sha256 "
            "FROM price_gap_patch_runs ORDER BY applied_at"
        ).fetchall()
        assert len(runs) == 2
        legacy = next(run for run in runs if run["run_id"] == legacy_run_id)
        fresh = next(run for run in runs if run["run_id"] == applied["run_id"])
        assert legacy["inserted_count"] == SPEC.candidate_count
        assert legacy["spec_json"] is None
        assert legacy["spec_sha256"] is None
        assert fresh["inserted_count"] == DYNAMIC_A.candidate_count
        assert fresh["spec_sha256"] == DYNAMIC_A.sha256

    # The migrated legacy run must remain intact and verifiable.
    assert patch.inspect_run(target, legacy_run_id)["verification"] == "verified"
    assert _counts(target) == (
        SPEC.candidate_count + DYNAMIC_A.candidate_count,
        2,
        SPEC.candidate_count + DYNAMIC_A.candidate_count,
    )


def test_v1_to_v2_migration_is_atomic_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = (tmp_path / "migrate-atomic.db").resolve()
    _create_target(target)
    _create_legacy_v1_manifest(target)

    artifact, artifact_report = _create_artifact(tmp_path, spec=DYNAMIC_A)

    def fail_migration(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE price_gap_patch_runs RENAME TO price_gap_patch_runs_legacy"
        )
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(patch, "_migrate_manifest_to_v2", fail_migration)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        _apply(
            artifact,
            target,
            (tmp_path / "migrate-atomic-backup.db").resolve(),
            artifact_report["artifact_sha256"],
            spec=DYNAMIC_A,
        )

    # The rollback must restore the v1 manifest exactly.
    with patch._readonly_connection(target) as connection:
        assert patch._detect_manifest_version(connection) == 1
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "price_gap_patch_runs_legacy" not in names
    assert _counts(target) == (SPEC.candidate_count, 1, SPEC.candidate_count)


# ---------------------------------------------------------------------------
# Dynamic count apply / rollback and inspect-run CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [DYNAMIC_A, DYNAMIC_B])
def test_dynamic_spec_collect_apply_rollback(tmp_path: Path, spec: PriceGapSpec) -> None:
    artifact, artifact_report = _create_artifact(tmp_path, spec=spec)
    assert artifact_report["candidates"] == spec.candidate_count
    assert artifact_report["schema_version"] == 2

    target = (tmp_path / f"target-{spec.incident_id}.db").resolve()
    _create_target(target)
    report = patch.inspect_target(artifact, target, spec=spec)
    assert report["target_status"] == "ready"

    applied = _apply(
        artifact,
        target,
        (tmp_path / f"pre-apply-{spec.incident_id}.db").resolve(),
        artifact_report["artifact_sha256"],
        spec=spec,
    )
    assert applied["inserted"] == spec.candidate_count
    assert applied["spec_sha256"] == spec.sha256
    assert _counts(target) == (spec.candidate_count, 1, spec.candidate_count)

    rolled_back = patch.rollback_patch(
        target,
        (tmp_path / f"pre-rollback-{spec.incident_id}.db").resolve(),
        run_id=applied["run_id"],
        confirm_run_id=applied["run_id"],
        confirm_incident=spec.incident_id,
        confirm_target=str(target),
        writers_paused=True,
    )
    assert rolled_back["deleted"] == spec.candidate_count
    assert _counts(target) == (0, 1, spec.candidate_count)


def test_inspect_run_cli_is_read_only_and_requires_target_and_run_id(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    artifact, artifact_report = _create_artifact(tmp_path, spec=DYNAMIC_A)
    target = (tmp_path / "inspect-run-target.db").resolve()
    _create_target(target)
    applied = _apply(
        artifact,
        target,
        (tmp_path / "pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
        spec=DYNAMIC_A,
    )

    exit_code = patch.main(
        ["inspect-run", "--target", str(target), "--run-id", applied["run_id"]]
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == applied["run_id"]
    assert output["state"] == "applied"
    assert output["verification"] == "verified"
    assert _counts(target) == (DYNAMIC_A.candidate_count, 1, DYNAMIC_A.candidate_count)

    with pytest.raises(patch.ArtifactValidationError, match="not found"):
        patch.inspect_run(target, "missing-run-id")


def test_inspect_run_requires_existing_manifest(tmp_path: Path) -> None:
    target = (tmp_path / "no-manifest.db").resolve()
    _create_target(target)
    with pytest.raises(patch.ArtifactValidationError, match="no price gap patch manifest"):
        patch.inspect_run(target, "whatever")


def test_rollback_chunks_deletes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, artifact_report = _create_artifact(tmp_path, spec=DYNAMIC_A)
    target = (tmp_path / "chunk-target.db").resolve()
    _create_target(target)
    applied = _apply(
        artifact,
        target,
        (tmp_path / "chunk-pre-apply.db").resolve(),
        artifact_report["artifact_sha256"],
        spec=DYNAMIC_A,
    )

    monkeypatch.setattr(patch, "ROLLBACK_DELETE_CHUNK", 3)
    rolled_back = patch.rollback_patch(
        target,
        (tmp_path / "chunk-pre-rollback.db").resolve(),
        run_id=applied["run_id"],
        confirm_run_id=applied["run_id"],
        confirm_incident=DYNAMIC_A.incident_id,
        confirm_target=str(target),
        writers_paused=True,
    )
    assert rolled_back["deleted"] == DYNAMIC_A.candidate_count
    assert _counts(target) == (0, 1, DYNAMIC_A.candidate_count)
