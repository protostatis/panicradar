"""Fail-closed checks used by the supervised production deployment."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

DEFAULT_HEARTBEAT_COMPONENTS = ("price", "crawl", "belief_update")


class DeploymentCheckError(RuntimeError):
    """Raised when a deployment safety invariant is not satisfied."""


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def create_verified_backup(source: Path, destination: Path) -> dict[str, Any]:
    """Create and validate an online SQLite backup.

    SQLite's backup API takes a transactionally consistent snapshot while the
    crawler remains online. A failed or corrupt destination is removed.
    """

    if not source.is_file():
        raise DeploymentCheckError(f"SQLite source does not exist: {source}")
    if destination.exists():
        raise DeploymentCheckError(f"Backup destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{source.resolve()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True, timeout=30.0)
    destination_connection: sqlite3.Connection | None = None
    verified = False

    try:
        source_connection.execute("PRAGMA busy_timeout = 30000")
        destination_connection = sqlite3.connect(destination, timeout=30.0)
        source_connection.backup(destination_connection)
        destination_connection.commit()

        result = destination_connection.execute("PRAGMA quick_check").fetchall()
        if result != [("ok",)]:
            raise DeploymentCheckError(f"Backup quick_check failed: {result!r}")
        verified = True
    finally:
        if destination_connection is not None:
            destination_connection.close()
        source_connection.close()
        if not verified:
            destination.unlink(missing_ok=True)

    return {
        "backup": str(destination),
        "bytes": destination.stat().st_size,
        "quick_check": "ok",
    }


def _open_read_transaction(db_path: Path) -> sqlite3.Connection:
    """Open a query-only transaction with a stable SQLite read snapshot."""

    if not db_path.is_file():
        raise DeploymentCheckError(f"SQLite database does not exist: {db_path}")

    source_uri = f"file:{db_path.resolve()}?mode=ro"
    connection = sqlite3.connect(source_uri, uri=True, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
    except Exception:
        connection.close()
        raise
    return connection


def _check_integrity(connection: sqlite3.Connection, *, label: str) -> None:
    rows = connection.execute("PRAGMA quick_check").fetchall()
    results = [row[0] for row in rows]
    if results != ["ok"]:
        raise DeploymentCheckError(f"{label} quick_check failed: {results!r}")


def _read_state_version(state_path: Path) -> int:
    if not state_path.is_file():
        raise DeploymentCheckError(f"Orchestrator state does not exist: {state_path}")
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentCheckError(f"Invalid orchestrator state: {exc}") from exc
    if not isinstance(state, dict):
        raise DeploymentCheckError("Orchestrator state root is not an object")
    state_version = state.get("belief_version")
    if type(state_version) is not int:
        raise DeploymentCheckError("State belief_version is not an integer")
    return state_version


def _check_publication(
    connection: sqlite3.Connection,
    *,
    state_path: Path,
) -> dict[str, Any]:
    """Validate published source weights against one state snapshot."""

    publication = connection.execute(
        "SELECT belief_version FROM belief_publications WHERE id = 1"
    ).fetchone()
    if publication is None:
        raise DeploymentCheckError("No published source-weight version")
    belief_version = int(publication["belief_version"])

    current_count = int(
        connection.execute("SELECT COUNT(*) FROM source_weights").fetchone()[0]
    )
    snapshot_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM source_weight_snapshots WHERE belief_version = ?",
            (belief_version,),
        ).fetchone()[0]
    )
    extra_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM source_weights current
            WHERE NOT EXISTS (
                SELECT 1 FROM source_weight_snapshots snapshot
                WHERE snapshot.belief_version = ?
                  AND snapshot.source = current.source
            )
            """,
            (belief_version,),
        ).fetchone()[0]
    )
    missing_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM source_weight_snapshots snapshot
            WHERE snapshot.belief_version = ?
              AND NOT EXISTS (
                  SELECT 1 FROM source_weights current
                  WHERE current.source = snapshot.source
              )
            """,
            (belief_version,),
        ).fetchone()[0]
    )
    mismatch_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM source_weights current
            JOIN source_weight_snapshots snapshot
              ON snapshot.belief_version = ?
             AND snapshot.source = current.source
            WHERE current.belief_version IS NOT snapshot.belief_version
               OR current.weight IS NOT snapshot.weight
               OR current.accuracy IS NOT snapshot.accuracy
               OR current.is_contrarian IS NOT snapshot.is_contrarian
               OR current.alpha IS NOT snapshot.alpha
               OR current.beta IS NOT snapshot.beta
               OR current.sample_size IS NOT snapshot.sample_size
            """,
            (belief_version,),
        ).fetchone()[0]
    )

    state_version = _read_state_version(state_path)
    if state_version != belief_version:
        raise DeploymentCheckError(
            f"State version {state_version} != published version {belief_version}"
        )
    if current_count <= 0:
        raise DeploymentCheckError("Published source-weight mirror is empty")
    if current_count != snapshot_count or extra_count or missing_count or mismatch_count:
        raise DeploymentCheckError(
            "Source-weight mirror mismatch: "
            f"current={current_count}, snapshot={snapshot_count}, extra={extra_count}, "
            f"missing={missing_count}, values={mismatch_count}"
        )

    return {
        "belief_version": belief_version,
        "source_weights": current_count,
        "mirror_exact": True,
    }


def check_publication_database(
    *,
    db_path: Path,
    state_path: Path,
) -> dict[str, Any]:
    """Verify a database/state backup pair is coherent and restorable."""

    connection = _open_read_transaction(db_path)
    try:
        _check_integrity(connection, label="Backup")
        publication = _check_publication(connection, state_path=state_path)
    finally:
        connection.close()
    return {"quick_check": "ok", **publication}


def get_heartbeat_watermark(db_path: Path) -> dict[str, int]:
    """Return the highest heartbeat row ID before candidate startup."""

    connection = _open_read_transaction(db_path)
    try:
        row = connection.execute(
            "SELECT COALESCE(MAX(id), 0) AS heartbeat_id FROM pipeline_heartbeats"
        ).fetchone()
        heartbeat_id = int(row["heartbeat_id"])
    finally:
        connection.close()
    return {"heartbeat_id": heartbeat_id}


def check_openrouter(
    *,
    expected_model: str,
    expected_dimensions: int,
) -> dict[str, Any]:
    """Make one uncached embedding request using the candidate image config."""

    import numpy as np

    from ..config import settings
    from ..processing.embedding_providers import OpenRouterEmbeddingProvider

    backend = (settings.embedding_backend or "").strip().lower()
    model = (settings.embedding_model or "").strip()
    if backend != "openrouter":
        raise DeploymentCheckError(
            f"Expected EMBEDDING_BACKEND=openrouter, got {backend or '<empty>'}"
        )
    if model != expected_model:
        raise DeploymentCheckError(
            f"Expected EMBEDDING_MODEL={expected_model}, got {model or '<empty>'}"
        )
    if not settings.openrouter_api_key:
        raise DeploymentCheckError("OPENROUTER_API_KEY is empty")

    provider = OpenRouterEmbeddingProvider(
        model=model,
        api_key=settings.openrouter_api_key,
        cache_path=None,
        max_retries=1,
    )
    vectors = provider.encode(
        [f"panicradar deployment canary {time.time_ns()}"],
        normalize=True,
    )
    expected_shape = (1, expected_dimensions)
    if vectors.shape != expected_shape:
        raise DeploymentCheckError(
            f"Expected embedding shape {expected_shape}, got {vectors.shape}"
        )
    if not np.all(np.isfinite(vectors)):
        raise DeploymentCheckError("OpenRouter returned a non-finite embedding")
    norm = float(np.linalg.norm(vectors[0]))
    if not np.isclose(norm, 1.0, atol=1e-5):
        raise DeploymentCheckError(f"Embedding is not normalized (norm={norm})")

    return {
        "backend": backend,
        "model": model,
        "shape": list(vectors.shape),
        "normalized": True,
    }


def check_runtime_database(
    *,
    db_path: Path,
    state_path: Path,
    since: datetime,
    heartbeat_after_id: int,
    components: Sequence[str] = DEFAULT_HEARTBEAT_COMPONENTS,
) -> dict[str, Any]:
    """Verify candidate heartbeats and exact source-weight publication state."""

    if heartbeat_after_id < 0:
        raise DeploymentCheckError("Heartbeat watermark must be non-negative")
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since = since.astimezone(timezone.utc)

    connection = _open_read_transaction(db_path)
    try:
        heartbeat_times: dict[str, str] = {}
        heartbeat_ids: dict[str, int] = {}
        for component in components:
            row = connection.execute(
                """
                SELECT id, last_success_at, last_error_at, last_error_message
                FROM pipeline_heartbeats
                WHERE component = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (component,),
            ).fetchone()
            if row is None:
                raise DeploymentCheckError(f"Missing heartbeat for {component}")
            heartbeat_id = int(row["id"])
            if heartbeat_id <= heartbeat_after_id:
                raise DeploymentCheckError(
                    f"Heartbeat for {component} did not come from the candidate "
                    f"(id={heartbeat_id}, watermark={heartbeat_after_id})"
                )
            if row["last_error_at"] is not None:
                raise DeploymentCheckError(
                    f"Latest {component} heartbeat is an error: "
                    f"{row['last_error_message'] or '<no message>'}"
                )
            if row["last_success_at"] is None:
                raise DeploymentCheckError(f"Heartbeat has no success time: {component}")
            success_at = _parse_timestamp(row["last_success_at"])
            if success_at <= since:
                raise DeploymentCheckError(
                    f"Heartbeat for {component} predates candidate startup: "
                    f"{success_at.isoformat()}"
                )
            heartbeat_times[component] = success_at.isoformat()
            heartbeat_ids[component] = heartbeat_id

        # Integrity can be expensive on the production database. Run it only
        # after the lightweight heartbeat gate proves candidate startup is done.
        _check_integrity(connection, label="Runtime")
        publication = _check_publication(connection, state_path=state_path)
    finally:
        connection.close()

    return {
        "quick_check": "ok",
        "heartbeats": heartbeat_times,
        "heartbeat_ids": heartbeat_ids,
        "heartbeat_watermark": heartbeat_after_id,
        **publication,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="Create a verified SQLite backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)

    publication = subparsers.add_parser(
        "publication", help="Check a database/state publication pair"
    )
    publication.add_argument("--db", type=Path, required=True)
    publication.add_argument("--state", type=Path, required=True)

    watermark = subparsers.add_parser(
        "heartbeat-watermark", help="Read the latest heartbeat row ID"
    )
    watermark.add_argument("--db", type=Path, required=True)

    openrouter = subparsers.add_parser("openrouter", help="Run an embedding canary")
    openrouter.add_argument("--expected-model", required=True)
    openrouter.add_argument("--expected-dimensions", type=int, required=True)

    runtime = subparsers.add_parser("runtime", help="Check post-start runtime state")
    runtime.add_argument("--db", type=Path, required=True)
    runtime.add_argument("--state", type=Path, required=True)
    runtime.add_argument("--since", required=True)
    runtime.add_argument("--after-heartbeat-id", type=int, required=True)
    runtime.add_argument(
        "--component",
        action="append",
        dest="components",
        help="Required fresh heartbeat component (repeatable)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "backup":
            result = create_verified_backup(args.source, args.destination)
        elif args.command == "publication":
            result = check_publication_database(
                db_path=args.db,
                state_path=args.state,
            )
        elif args.command == "heartbeat-watermark":
            result = get_heartbeat_watermark(args.db)
        elif args.command == "openrouter":
            result = check_openrouter(
                expected_model=args.expected_model,
                expected_dimensions=args.expected_dimensions,
            )
        else:
            result = check_runtime_database(
                db_path=args.db,
                state_path=args.state,
                since=_parse_timestamp(args.since),
                heartbeat_after_id=args.after_heartbeat_id,
                components=args.components or DEFAULT_HEARTBEAT_COMPONENTS,
            )
    except Exception as exc:
        print(f"DEPLOYMENT CHECK FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
