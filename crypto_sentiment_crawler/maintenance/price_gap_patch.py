"""Build and apply offline CoinGecko price-gap patches from a strict spec.

Collection never accepts a production database path. It writes a sealed SQLite
artifact containing the raw CoinGecko responses and exactly the missing full
UTC-hour candidates described by the supplied :class:`PriceGapSpec`. Applying
the artifact is a separate, guarded operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import httpx

from .price_gap_spec import PriceGapSpec, PriceGapSpecError, load_spec, parse_spec_json

UTC = timezone.utc
ARTIFACT_SCHEMA_VERSION = 2
TARGET_MANIFEST_SCHEMA_VERSION_V1 = 1
TARGET_MANIFEST_SCHEMA_VERSION_V2 = 2
ALIGNMENT_TOLERANCE_MS = 5 * 60 * 1000
ROLLBACK_DELETE_CHUNK = 500
MAX_RESPONSE_BYTES = 20 * 1024 * 1024

# The only remaining hardcoded historical reference: the August 2026 incident
# whose v1 artifact/manifest predates this reusable spec-driven tooling.
# LEGACY_V1_SPEC is used solely to read (validate/inspect/rollback) the
# already-produced v1 artifact and v1 manifest, never to drive new collection.
LEGACY_V1_SPEC = load_spec(Path(__file__).resolve().parent / "specs" / "vpn-dns-20260811.json")
LEGACY_V1_SPEC_SHA256 = "b1e93aba50a2d7c5dc8ed3f3cf4c86043188a361dbb88d2dd83d2f695121ef57"
if LEGACY_V1_SPEC.sha256 != LEGACY_V1_SPEC_SHA256:
    raise RuntimeError("The checked-in legacy price-gap spec changed unexpectedly")

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
SAFE_RESPONSE_HEADERS = {
    "content-type",
    "date",
    "etag",
    "last-modified",
    "retry-after",
    "cf-cache-status",
    "cf-ray",
}
REQUIRED_PRICE_COLUMNS = {
    "id",
    "timestamp",
    "coin",
    "price_usd",
    "volume_24h",
    "market_cap",
    "source",
}

ARTIFACT_SCHEMA = """
CREATE TABLE patch_metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE coins (
    symbol TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL UNIQUE
);

CREATE TABLE raw_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL REFERENCES coins(symbol),
    attempt INTEGER NOT NULL,
    request_url TEXT NOT NULL,
    request_params_json TEXT NOT NULL,
    http_status INTEGER,
    retrieved_at TEXT NOT NULL,
    response_headers_json TEXT NOT NULL,
    response_body BLOB NOT NULL,
    body_sha256 TEXT NOT NULL,
    error TEXT,
    successful INTEGER NOT NULL CHECK (successful IN (0, 1)),
    UNIQUE(coin, attempt)
);

CREATE TABLE candidates (
    coin TEXT NOT NULL REFERENCES coins(symbol),
    hour_epoch INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    price_usd REAL NOT NULL CHECK (price_usd > 0),
    volume_24h REAL NOT NULL CHECK (volume_24h >= 0),
    market_cap REAL NOT NULL CHECK (market_cap > 0),
    price_provider_timestamp_ms INTEGER NOT NULL,
    volume_provider_timestamp_ms INTEGER NOT NULL,
    market_cap_provider_timestamp_ms INTEGER NOT NULL,
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    PRIMARY KEY (coin, hour_epoch)
);
"""

_MANIFEST_RUN_STATE_CHECK = """CHECK (
        (state = 'applied'
         AND rollback_backup_path IS NULL
         AND rollback_backup_sha256 IS NULL
         AND rolled_back_count IS NULL
         AND rolled_back_at IS NULL)
        OR
        (state = 'rolled_back'
         AND rollback_backup_path IS NOT NULL
         AND rollback_backup_sha256 IS NOT NULL
         AND length(rollback_backup_sha256) = 64
         AND rolled_back_count = inserted_count
         AND rolled_back_at IS NOT NULL)
    )"""

_MANIFEST_ROWS_SQL = """
CREATE TABLE price_gap_patch_rows (
    run_id TEXT NOT NULL REFERENCES price_gap_patch_runs(run_id),
    candidate_coin TEXT NOT NULL,
    candidate_hour_epoch INTEGER NOT NULL,
    price_data_id INTEGER NOT NULL,
    expected_timestamp TEXT NOT NULL,
    expected_price REAL NOT NULL,
    expected_volume REAL NOT NULL,
    expected_market_cap REAL NOT NULL,
    expected_source TEXT NOT NULL,
    PRIMARY KEY (run_id, candidate_coin, candidate_hour_epoch),
    UNIQUE (run_id, price_data_id)
)
"""

# Schema v1 is the exact manifest already present in production for the August
# 2026 run: a fixed 600-row CHECK and no spec columns. Its SQL text must stay
# semantically identical so read-only inspection/rollback recognize production exactly.
TARGET_MANIFEST_TABLE_SQL_V1 = {
    "price_gap_patch_schema": f"""
CREATE TABLE price_gap_patch_schema (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = {TARGET_MANIFEST_SCHEMA_VERSION_V1})
)
""",
    "price_gap_patch_runs": f"""
CREATE TABLE price_gap_patch_runs (
    run_id TEXT NOT NULL PRIMARY KEY,
    incident_id TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    candidate_sha256 TEXT NOT NULL,
    source_tag TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('applied', 'rolled_back')),
    inserted_count INTEGER NOT NULL,
    backup_path TEXT NOT NULL,
    backup_sha256 TEXT NOT NULL,
    rollback_backup_path TEXT,
    rollback_backup_sha256 TEXT,
    rolled_back_count INTEGER,
    rolled_back_at TEXT,
    CHECK (length(artifact_sha256) = 64),
    CHECK (length(candidate_sha256) = 64),
    CHECK (length(backup_sha256) = 64),
    CHECK (inserted_count = 600),
    {_MANIFEST_RUN_STATE_CHECK}
)
""",
    "price_gap_patch_rows": _MANIFEST_ROWS_SQL,
}

# Schema v2 supports variable candidate counts and records the canonical spec
# JSON and its sha256 for each run. spec_json/spec_sha256 are nullable so rows
# migrated from a v1 manifest can keep NULL until they are rolled back.
TARGET_MANIFEST_TABLE_SQL_V2 = {
    "price_gap_patch_schema": f"""
CREATE TABLE price_gap_patch_schema (
    singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = {TARGET_MANIFEST_SCHEMA_VERSION_V2})
)
""",
    "price_gap_patch_runs": f"""
CREATE TABLE price_gap_patch_runs (
    run_id TEXT NOT NULL PRIMARY KEY,
    incident_id TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    candidate_sha256 TEXT NOT NULL,
    source_tag TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('applied', 'rolled_back')),
    inserted_count INTEGER NOT NULL CHECK (inserted_count > 0),
    backup_path TEXT NOT NULL,
    backup_sha256 TEXT NOT NULL,
    rollback_backup_path TEXT,
    rollback_backup_sha256 TEXT,
    rolled_back_count INTEGER,
    rolled_back_at TEXT,
    spec_json TEXT,
    spec_sha256 TEXT,
    CHECK (length(artifact_sha256) = 64),
    CHECK (length(candidate_sha256) = 64),
    CHECK (length(backup_sha256) = 64),
    CHECK (spec_sha256 IS NULL OR length(spec_sha256) = 64),
    {_MANIFEST_RUN_STATE_CHECK}
)
""",
    "price_gap_patch_rows": _MANIFEST_ROWS_SQL,
}

TARGET_MANIFEST_TABLES = frozenset(TARGET_MANIFEST_TABLE_SQL_V2)
TARGET_MANIFEST_TABLE_NAMES = (
    "price_gap_patch_schema",
    "price_gap_patch_runs",
    "price_gap_patch_rows",
)


class PriceGapPatchError(RuntimeError):
    """Base error for patch collection, validation, or application."""


class ArtifactValidationError(PriceGapPatchError):
    """The offline artifact failed an integrity or content check."""


class TargetConflictError(PriceGapPatchError):
    """The target contains data in one or more candidate hour buckets."""


class ConfirmationError(PriceGapPatchError):
    """A destructive command is missing an exact confirmation."""


@dataclass(frozen=True)
class FetchAttempt:
    """One HTTP attempt retained in the offline patch artifact."""

    coin: str
    attempt: int
    request_url: str
    request_params: dict[str, Any]
    http_status: int | None
    retrieved_at: str
    response_headers: dict[str, str]
    response_body: bytes
    error: str | None
    successful: bool

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.response_body).hexdigest()


@dataclass(frozen=True)
class Candidate:
    """One canonical hourly price row proposed by the patch."""

    coin: str
    hour_epoch: int
    timestamp: str
    price_usd: float
    volume_24h: float
    market_cap: float
    price_provider_timestamp_ms: int
    volume_provider_timestamp_ms: int
    market_cap_provider_timestamp_ms: int
    raw_response_id: int = 0


@dataclass(frozen=True)
class TargetClassification:
    """Read-only classification of an artifact against a target database."""

    status: str
    conflicts: tuple[dict[str, Any], ...] = ()
    run_id: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical_timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt_path(artifact_path: Path) -> Path:
    return Path(f"{artifact_path}.sha256")


def _raw_dir_path(artifact_path: Path) -> Path:
    return Path(f"{artifact_path}.raw")


def _readonly_connection(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _readwrite_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=rw"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise ArtifactValidationError("Target connection could not enable foreign keys")
    return connection


def _parse_utc_timestamp(raw: str) -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _candidate_payload(candidates: Iterable[Candidate]) -> list[dict[str, Any]]:
    payload = []
    for candidate in sorted(candidates, key=lambda row: (row.coin, row.hour_epoch)):
        row = asdict(candidate)
        row.pop("raw_response_id", None)
        payload.append(row)
    return payload


def _candidate_digest(candidates: Iterable[Candidate]) -> str:
    return hashlib.sha256(_json_bytes(_candidate_payload(candidates))).hexdigest()


def _nearest_hour_epoch(timestamp_ms: float) -> tuple[int, int]:
    nearest_ms = int((timestamp_ms + 30 * 60 * 1000) // (60 * 60 * 1000))
    nearest_ms *= 60 * 60 * 1000
    return nearest_ms // 1000, nearest_ms


def _normalize_metric(
    points: Any,
    *,
    metric_name: str,
    require_positive: bool,
    spec: PriceGapSpec,
) -> dict[int, tuple[float, int]]:
    if not isinstance(points, list):
        raise ArtifactValidationError(f"CoinGecko response is missing {metric_name}")

    normalized: dict[int, tuple[float, int]] = {}
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ArtifactValidationError(f"Malformed {metric_name} point: {point!r}")
        timestamp_ms, value = point
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, (int, float))
            or not math.isfinite(timestamp_ms)
        ):
            raise ArtifactValidationError(f"Invalid {metric_name} timestamp: {timestamp_ms!r}")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ArtifactValidationError(f"Invalid {metric_name} value: {value!r}")
        if require_positive and value <= 0:
            raise ArtifactValidationError(f"Non-positive {metric_name} value: {value!r}")
        if not require_positive and value < 0:
            raise ArtifactValidationError(f"Negative {metric_name} value: {value!r}")

        hour_epoch, nearest_ms = _nearest_hour_epoch(float(timestamp_ms))
        if hour_epoch not in spec.expected_hour_set:
            continue
        if abs(float(timestamp_ms) - nearest_ms) > ALIGNMENT_TOLERANCE_MS:
            continue
        if hour_epoch in normalized:
            raise ArtifactValidationError(
                f"Multiple {metric_name} points map to {_canonical_timestamp(hour_epoch)}"
            )
        normalized[hour_epoch] = (float(value), int(timestamp_ms))

    missing = sorted(spec.expected_hour_set - normalized.keys())
    if missing:
        preview = ", ".join(_canonical_timestamp(epoch) for epoch in missing[:3])
        raise ArtifactValidationError(
            f"{metric_name} is missing {len(missing)} expected hour(s): {preview}"
        )
    return normalized


def derive_candidates(
    coin: str, response_body: bytes, *, spec: PriceGapSpec, raw_response_id: int = 0
) -> list[Candidate]:
    """Derive the spec's exact hourly candidates from one raw response."""
    if coin not in spec.coin_mapping:
        raise ArtifactValidationError(f"Unexpected coin: {coin}")
    try:
        payload = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(f"Invalid JSON response for {coin}") from error
    if not isinstance(payload, dict):
        raise ArtifactValidationError(f"Unexpected CoinGecko payload for {coin}")

    prices = _normalize_metric(
        payload.get("prices"), metric_name="prices", require_positive=True, spec=spec
    )
    caps = _normalize_metric(
        payload.get("market_caps"), metric_name="market_caps", require_positive=True, spec=spec
    )
    volumes = _normalize_metric(
        payload.get("total_volumes"), metric_name="total_volumes", require_positive=False, spec=spec
    )

    candidates = []
    for hour_epoch in spec.expected_hour_epochs:
        price, price_ms = prices[hour_epoch]
        market_cap, cap_ms = caps[hour_epoch]
        volume, volume_ms = volumes[hour_epoch]
        provider_times = (price_ms, cap_ms, volume_ms)
        if max(provider_times) - min(provider_times) > ALIGNMENT_TOLERANCE_MS:
            raise ArtifactValidationError(
                f"Metric timestamps diverge for {coin} at {_canonical_timestamp(hour_epoch)}"
            )
        candidates.append(
            Candidate(
                coin=coin,
                hour_epoch=hour_epoch,
                timestamp=_canonical_timestamp(hour_epoch),
                price_usd=price,
                volume_24h=volume,
                market_cap=market_cap,
                price_provider_timestamp_ms=price_ms,
                volume_provider_timestamp_ms=volume_ms,
                market_cap_provider_timestamp_ms=cap_ms,
                raw_response_id=raw_response_id,
            )
        )
    return candidates


def make_fixture_attempt(
    coin: str,
    payload: Mapping[str, Any],
    *,
    spec: PriceGapSpec,
    attempt: int = 1,
    retrieved_at: str = "2026-08-13T17:00:00+00:00",
) -> FetchAttempt:
    """Create a successful attempt for deterministic tests and offline fixtures."""
    params = {
        "vs_currency": "usd",
        "from": int(spec.fetch_start.timestamp()),
        "to": int(spec.fetch_end.timestamp()),
    }
    return FetchAttempt(
        coin=coin,
        attempt=attempt,
        request_url=COINGECKO_URL.format(coin_id=spec.coin_mapping[coin]),
        request_params=params,
        http_status=200,
        retrieved_at=retrieved_at,
        response_headers={"content-type": "application/json"},
        response_body=_json_bytes(payload),
        error=None,
        successful=True,
    )


def _retry_delay(attempt: FetchAttempt, attempt_number: int) -> float:
    retry_after = attempt.response_headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 120.0)
        except ValueError:
            pass
    return min(15.0 * (2 ** (attempt_number - 1)), 120.0)


def fetch_coin_attempts(
    client: httpx.Client,
    coin: str,
    *,
    spec: PriceGapSpec,
    max_attempts: int = 6,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[FetchAttempt]:
    """Fetch one coin with bounded retries while retaining every response."""
    params = {
        "vs_currency": "usd",
        "from": int(spec.fetch_start.timestamp()),
        "to": int(spec.fetch_end.timestamp()),
    }
    url = COINGECKO_URL.format(coin_id=spec.coin_mapping[coin])
    attempts: list[FetchAttempt] = []

    for attempt_number in range(1, max_attempts + 1):
        retrieved_at = _utc_now().isoformat()
        try:
            response = client.get(url, params=params)
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise PriceGapPatchError(
                    f"CoinGecko response exceeds {MAX_RESPONSE_BYTES} bytes for {coin}"
                )
            headers = {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in SAFE_RESPONSE_HEADERS
            }
            successful = response.status_code == 200
            attempt = FetchAttempt(
                coin=coin,
                attempt=attempt_number,
                request_url=url,
                request_params=params,
                http_status=response.status_code,
                retrieved_at=retrieved_at,
                response_headers=headers,
                response_body=response.content,
                error=None if successful else f"HTTP {response.status_code}",
                successful=successful,
            )
        except httpx.HTTPError as error:
            attempt = FetchAttempt(
                coin=coin,
                attempt=attempt_number,
                request_url=url,
                request_params=params,
                http_status=None,
                retrieved_at=retrieved_at,
                response_headers={},
                response_body=b"",
                error=type(error).__name__,
                successful=False,
            )
        attempts.append(attempt)

        if attempt.successful:
            derive_candidates(coin, attempt.response_body, spec=spec)
            return attempts
        retryable = attempt.http_status in {429, 500, 502, 503, 504} or attempt.http_status is None
        if not retryable or attempt_number == max_attempts:
            break
        sleep_fn(_retry_delay(attempt, attempt_number))

    last_error = attempts[-1].error if attempts else "no response"
    raise PriceGapPatchError(f"CoinGecko collection failed for {coin}: {last_error}")


def fetch_all_attempts(
    *,
    spec: PriceGapSpec,
    max_attempts: int = 6,
    request_delay: float = 7.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    client: httpx.Client | None = None,
) -> dict[str, list[FetchAttempt]]:
    """Fetch all spec responses without accepting any database path."""
    coins = spec.coin_mapping
    owned_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": "panicradar-offline-gap-patch/1.0"},
        )
    attempts_by_coin: dict[str, list[FetchAttempt]] = {}
    try:
        for index, coin in enumerate(coins):
            attempts_by_coin[coin] = fetch_coin_attempts(
                client,
                coin,
                spec=spec,
                max_attempts=max_attempts,
                sleep_fn=sleep_fn,
            )
            if request_delay > 0 and index < len(coins) - 1:
                sleep_fn(request_delay)
    finally:
        if owned_client:
            client.close()
    return attempts_by_coin


def _write_metadata(connection: sqlite3.Connection, metadata: Mapping[str, Any]) -> None:
    connection.executemany(
        "INSERT INTO patch_metadata (key, value_json) VALUES (?, ?)",
        [(key, _json_bytes(value).decode("utf-8")) for key, value in metadata.items()],
    )


def _read_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute("SELECT key, value_json FROM patch_metadata").fetchall()
    return {row["key"]: json.loads(row["value_json"]) for row in rows}


def _write_raw_sidecars(
    raw_dir: Path, attempts_by_coin: Mapping[str, Sequence[FetchAttempt]]
) -> None:
    if raw_dir.exists():
        raise FileExistsError(f"Raw response directory already exists: {raw_dir}")
    raw_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{raw_dir.name}.", dir=raw_dir.parent))
    try:
        index_rows = []
        for coin, attempts in attempts_by_coin.items():
            for attempt in attempts:
                suffix = "json" if attempt.response_body.lstrip()[:1] in {b"{", b"["} else "bin"
                name = (
                    f"{coin.lower()}-attempt-{attempt.attempt}-"
                    f"http-{attempt.http_status}.{suffix}"
                )
                response_path = temporary / name
                response_path.write_bytes(attempt.response_body)
                os.chmod(response_path, 0o400)
                index_rows.append(
                    {
                        "coin": coin,
                        "attempt": attempt.attempt,
                        "http_status": attempt.http_status,
                        "file": name,
                        "body_sha256": attempt.body_sha256,
                        "successful": attempt.successful,
                    }
                )
        index_rows.sort(key=lambda row: (row["coin"], row["attempt"]))
        index_path = temporary / "index.json"
        index_path.write_bytes(_json_bytes(index_rows) + b"\n")
        os.chmod(index_path, 0o400)
        temporary.rename(raw_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def create_patch_artifact(
    artifact_path: Path,
    attempts_by_coin: Mapping[str, Sequence[FetchAttempt]],
    *,
    spec: PriceGapSpec,
) -> dict[str, Any]:
    """Build, validate, seal, and atomically publish an offline patch artifact."""
    artifact_path = artifact_path.expanduser().resolve()
    raw_dir = _raw_dir_path(artifact_path)
    receipt_path = _receipt_path(artifact_path)
    for output in (artifact_path, raw_dir, receipt_path):
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    if set(attempts_by_coin) != set(spec.coin_mapping):
        raise ArtifactValidationError("Attempts do not cover the exact expected coin set")

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{artifact_path.name}.", suffix=".tmp", dir=artifact_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    temporary_path.unlink()

    all_candidates: list[Candidate] = []
    published_outputs: list[Path] = []
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.executescript(ARTIFACT_SCHEMA)
        connection.executemany(
            "INSERT INTO coins (symbol, provider_id) VALUES (?, ?)", spec.coins
        )

        for coin in spec.coin_mapping:
            attempts = list(attempts_by_coin[coin])
            successful_attempts = [attempt for attempt in attempts if attempt.successful]
            if len(successful_attempts) != 1:
                raise ArtifactValidationError(
                    f"Expected exactly one successful response for {coin}, "
                    f"got {len(successful_attempts)}"
                )
            successful_raw_id = None
            for attempt in attempts:
                cursor = connection.execute(
                    """
                    INSERT INTO raw_responses (
                        coin, attempt, request_url, request_params_json, http_status,
                        retrieved_at, response_headers_json, response_body, body_sha256,
                        error, successful
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        coin,
                        attempt.attempt,
                        attempt.request_url,
                        _json_bytes(attempt.request_params).decode("utf-8"),
                        attempt.http_status,
                        attempt.retrieved_at,
                        _json_bytes(attempt.response_headers).decode("utf-8"),
                        attempt.response_body,
                        attempt.body_sha256,
                        attempt.error,
                        int(attempt.successful),
                    ),
                )
                if attempt.successful:
                    successful_raw_id = int(cursor.lastrowid)

            assert successful_raw_id is not None
            candidates = derive_candidates(
                coin,
                successful_attempts[0].response_body,
                spec=spec,
                raw_response_id=successful_raw_id,
            )
            all_candidates.extend(candidates)
            connection.executemany(
                """
                INSERT INTO candidates (
                    coin, hour_epoch, timestamp, price_usd, volume_24h, market_cap,
                    price_provider_timestamp_ms, volume_provider_timestamp_ms,
                    market_cap_provider_timestamp_ms, raw_response_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.coin,
                        row.hour_epoch,
                        row.timestamp,
                        row.price_usd,
                        row.volume_24h,
                        row.market_cap,
                        row.price_provider_timestamp_ms,
                        row.volume_provider_timestamp_ms,
                        row.market_cap_provider_timestamp_ms,
                        row.raw_response_id,
                    )
                    for row in candidates
                ],
            )

        if len(all_candidates) != spec.candidate_count:
            raise ArtifactValidationError(
                f"Expected {spec.candidate_count} candidates, got {len(all_candidates)}"
            )
        candidate_sha256 = _candidate_digest(all_candidates)
        collected_at = max(
            attempt.retrieved_at
            for attempts in attempts_by_coin.values()
            for attempt in attempts
        )
        _write_metadata(
            connection,
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "status": "SEALED",
                "incident_id": spec.incident_id,
                "provider": spec.provider,
                "source_tag": spec.source_tag,
                "start_hour": spec.start_hour.isoformat(),
                "end_exclusive": spec.end_exclusive.isoformat(),
                "fetch_start": spec.fetch_start.isoformat(),
                "fetch_end": spec.fetch_end.isoformat(),
                "expected_hours": spec.hours,
                "expected_coins": len(spec.coins),
                "expected_candidates": spec.candidate_count,
                "alignment_tolerance_ms": ALIGNMENT_TOLERANCE_MS,
                "spec_json": spec.canonical_json(),
                "spec_sha256": spec.sha256,
                "collected_at": collected_at,
                "candidate_sha256": candidate_sha256,
                "volume_semantics": "CoinGecko historical total_volumes (rolling 24h)",
                "timestamp_semantics": "provider point aligned to nearest full UTC hour",
            },
        )
        connection.commit()
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise ArtifactValidationError(f"Artifact quick_check failed: {quick_check}")
        connection.close()
        connection = None

        _write_raw_sidecars(raw_dir, attempts_by_coin)
        published_outputs.append(raw_dir)
        os.chmod(temporary_path, 0o444)
        artifact_sha256 = _sha256_file(temporary_path)
        # Publish the already-sealed database before creating its exclusive receipt.
        os.link(temporary_path, artifact_path)
        published_outputs.append(artifact_path)
        receipt_descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        published_outputs.append(receipt_path)
        with os.fdopen(receipt_descriptor, "w", encoding="utf-8") as receipt:
            receipt.write(f"{artifact_sha256}  {artifact_path.name}\n")
            receipt.flush()
            os.fsync(receipt.fileno())
        temporary_path.unlink()
        _sync_directory(artifact_path.parent)

        report = validate_artifact(artifact_path, expected_digest=artifact_sha256, spec=spec)
        report.update({"raw_dir": str(raw_dir), "receipt": str(receipt_path)})
        return report
    except Exception:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)
        for output in reversed(published_outputs):
            if output.is_dir():
                shutil.rmtree(output, ignore_errors=True)
            else:
                output.unlink(missing_ok=True)
        raise


def _read_receipt(artifact_path: Path) -> str:
    receipt_path = _receipt_path(artifact_path)
    if not receipt_path.is_file():
        raise ArtifactValidationError(f"Artifact receipt is missing: {receipt_path}")
    parts = receipt_path.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1] != artifact_path.name or len(parts[0]) != 64:
        raise ArtifactValidationError(f"Malformed artifact receipt: {receipt_path}")
    return parts[0].lower()


def _load_candidates(connection: sqlite3.Connection) -> list[Candidate]:
    rows = connection.execute(
        """
        SELECT coin, hour_epoch, timestamp, price_usd, volume_24h, market_cap,
               price_provider_timestamp_ms, volume_provider_timestamp_ms,
               market_cap_provider_timestamp_ms, raw_response_id
        FROM candidates
        ORDER BY coin, hour_epoch
        """
    ).fetchall()
    return [Candidate(**dict(row)) for row in rows]


def validate_artifact(
    artifact_path: Path,
    *,
    expected_digest: str | None = None,
    spec: PriceGapSpec | None = None,
) -> dict[str, Any]:
    """Verify file, raw-response, candidate, and spec invariants.

    A v2 artifact embeds its canonical spec; the supplied ``spec`` must match it
    exactly. A v1 artifact (the historical August 2026 one) carries no embedded
    spec and is validated read-only against :data:`LEGACY_V1_SPEC`.
    """
    artifact_path = artifact_path.expanduser().resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    artifact_sha256 = _sha256_file(artifact_path)
    receipt_digest = _read_receipt(artifact_path)
    if artifact_sha256 != receipt_digest:
        raise ArtifactValidationError("Artifact file hash does not match its receipt")
    if expected_digest is not None and artifact_sha256 != expected_digest.lower():
        raise ArtifactValidationError("Artifact hash does not match the explicit confirmation")

    connection = _readonly_connection(artifact_path, immutable=True)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise ArtifactValidationError(f"Artifact quick_check failed: {quick_check}")
        metadata = _read_metadata(connection)
        schema_version = metadata.get("schema_version")
        if schema_version == ARTIFACT_SCHEMA_VERSION:
            if spec is None:
                raise ArtifactValidationError("A spec is required to validate a v2 artifact")
            spec_json = metadata.get("spec_json")
            spec_sha256 = metadata.get("spec_sha256")
            if not isinstance(spec_json, str) or not isinstance(spec_sha256, str):
                raise ArtifactValidationError("Artifact is missing embedded spec metadata")
            embedded = parse_spec_json(spec_json)
            if spec_json != embedded.canonical_json():
                raise ArtifactValidationError("Artifact embedded spec JSON is not canonical")
            if embedded.sha256 != spec_sha256:
                raise ArtifactValidationError(
                    "Artifact spec digest does not match its embedded spec"
                )
            if embedded.sha256 != spec.sha256:
                raise ArtifactValidationError(
                    "Supplied spec does not match the embedded artifact spec"
                )
            effective_spec = spec
        elif schema_version == 1:
            if spec is not None and spec.sha256 != LEGACY_V1_SPEC.sha256:
                raise ArtifactValidationError(
                    "Supplied spec does not match the legacy v1 artifact incident"
                )
            effective_spec = LEGACY_V1_SPEC
        else:
            raise ArtifactValidationError(f"Unsupported artifact schema version: {schema_version}")

        required_metadata = {
            "schema_version": schema_version,
            "status": "SEALED",
            "incident_id": effective_spec.incident_id,
            "provider": effective_spec.provider,
            "source_tag": effective_spec.source_tag,
            "start_hour": effective_spec.start_hour.isoformat(),
            "end_exclusive": effective_spec.end_exclusive.isoformat(),
            "expected_hours": effective_spec.hours,
            "expected_coins": len(effective_spec.coins),
            "expected_candidates": effective_spec.candidate_count,
            "alignment_tolerance_ms": ALIGNMENT_TOLERANCE_MS,
        }
        for key, expected in required_metadata.items():
            if metadata.get(key) != expected:
                raise ArtifactValidationError(
                    f"Artifact metadata mismatch for {key}: {metadata.get(key)!r} != {expected!r}"
                )

        coin_rows = connection.execute(
            "SELECT symbol, provider_id FROM coins ORDER BY symbol"
        ).fetchall()
        artifact_coins = {row["symbol"]: row["provider_id"] for row in coin_rows}
        if artifact_coins != effective_spec.coin_mapping:
            raise ArtifactValidationError(
                "Artifact coin mapping does not match the validated spec"
            )

        raw_rows = connection.execute(
            "SELECT * FROM raw_responses ORDER BY coin, attempt"
        ).fetchall()
        raw_success_counts = {coin: 0 for coin in effective_spec.coin_mapping}
        expected_attempt = {coin: 1 for coin in effective_spec.coin_mapping}
        for row in raw_rows:
            body = bytes(row["response_body"])
            coin = row["coin"]
            if coin not in effective_spec.coin_mapping:
                raise ArtifactValidationError(f"Raw response has an unexpected coin: {coin}")
            if row["attempt"] != expected_attempt[coin]:
                raise ArtifactValidationError(
                    f"Raw response attempts are not contiguous for {coin}"
                )
            expected_attempt[coin] += 1
            expected_url = COINGECKO_URL.format(
                coin_id=effective_spec.coin_mapping[coin]
            )
            expected_params = {
                "vs_currency": "usd",
                "from": int(effective_spec.fetch_start.timestamp()),
                "to": int(effective_spec.fetch_end.timestamp()),
            }
            try:
                request_params = json.loads(row["request_params_json"])
            except (TypeError, json.JSONDecodeError) as error:
                raise ArtifactValidationError(
                    "Raw response request parameters are invalid"
                ) from error
            if row["request_url"] != expected_url or request_params != expected_params:
                raise ArtifactValidationError(
                    f"Raw response request metadata mismatch for {coin} attempt {row['attempt']}"
                )
            successful = bool(row["successful"])
            if successful != (row["http_status"] == 200 and row["error"] is None):
                raise ArtifactValidationError(
                    f"Raw response status fields are inconsistent for {coin} "
                    f"attempt {row['attempt']}"
                )
            if len(body) > MAX_RESPONSE_BYTES:
                raise ArtifactValidationError("Raw response exceeds the artifact size limit")
            if hashlib.sha256(body).hexdigest() != row["body_sha256"]:
                raise ArtifactValidationError(
                    f"Raw response hash mismatch for {row['coin']} attempt {row['attempt']}"
                )
            if successful:
                raw_success_counts[coin] += 1
        if any(count != 1 for count in raw_success_counts.values()):
            raise ArtifactValidationError("Artifact does not have exactly one success per coin")

        raw_dir = _raw_dir_path(artifact_path)
        if not raw_dir.is_dir():
            raise ArtifactValidationError(f"Raw response directory is missing: {raw_dir}")
        try:
            sidecar_index = json.loads((raw_dir / "index.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtifactValidationError("Raw response sidecar index is unreadable") from error
        expected_sidecars = []
        for row in raw_rows:
            body = bytes(row["response_body"])
            suffix = "json" if body.lstrip()[:1] in {b"{", b"["} else "bin"
            name = (
                f"{str(row['coin']).lower()}-attempt-{row['attempt']}-"
                f"http-{row['http_status']}.{suffix}"
            )
            expected_sidecars.append(
                {
                    "coin": row["coin"],
                    "attempt": row["attempt"],
                    "http_status": row["http_status"],
                    "file": name,
                    "body_sha256": row["body_sha256"],
                    "successful": bool(row["successful"]),
                }
            )
            response_path = raw_dir / name
            response_stat = response_path.lstat()
            if (
                not stat.S_ISREG(response_stat.st_mode)
                or response_path.is_symlink()
                or _sha256_file(response_path) != row["body_sha256"]
            ):
                raise ArtifactValidationError(f"Raw response sidecar mismatch: {response_path}")
        expected_sidecars.sort(key=lambda row: (row["coin"], row["attempt"]))
        if sidecar_index != expected_sidecars:
            raise ArtifactValidationError("Raw response sidecar index does not match the artifact")
        expected_names = {row["file"] for row in expected_sidecars} | {"index.json"}
        actual_entries = list(raw_dir.iterdir())
        actual_names = {path.name for path in actual_entries}
        if actual_names != expected_names:
            raise ArtifactValidationError("Raw response directory contains unexpected files")
        if any(
            path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)
            for path in actual_entries
        ):
            raise ArtifactValidationError("Raw response directory has a non-regular entry")
        index_path = raw_dir / "index.json"
        if index_path.is_symlink() or not stat.S_ISREG(index_path.lstat().st_mode):
            raise ArtifactValidationError("Raw response index is not a regular file")

        candidates = _load_candidates(connection)
        if len(candidates) != effective_spec.candidate_count:
            raise ArtifactValidationError(
                f"Expected {effective_spec.candidate_count} candidates, got {len(candidates)}"
            )
        expected_product = {
            (coin, epoch)
            for coin in effective_spec.coin_mapping
            for epoch in effective_spec.expected_hour_epochs
        }
        actual_product = {(row.coin, row.hour_epoch) for row in candidates}
        if actual_product != expected_product:
            raise ArtifactValidationError("Candidates do not form the exact coin/hour product")

        successful_ids = {
            row["coin"]: row["id"]
            for row in connection.execute(
                "SELECT id, coin FROM raw_responses WHERE successful = 1"
            ).fetchall()
        }
        for candidate in candidates:
            if candidate.raw_response_id != successful_ids[candidate.coin]:
                raise ArtifactValidationError(
                    f"Candidate raw-response linkage mismatch for {candidate.coin}"
                )

        successful_rows = connection.execute(
            "SELECT id, coin, response_body FROM raw_responses WHERE successful = 1"
        ).fetchall()
        if len(successful_rows) != len(effective_spec.coin_mapping):
            raise ArtifactValidationError("Artifact does not have exactly one success per coin")
        rederived = []
        for row in successful_rows:
            rederived.extend(
                derive_candidates(
                    row["coin"],
                    bytes(row["response_body"]),
                    spec=effective_spec,
                    raw_response_id=row["id"],
                )
            )
        candidate_sha256 = _candidate_digest(candidates)
        if candidate_sha256 != metadata.get("candidate_sha256"):
            raise ArtifactValidationError("Candidate digest does not match artifact metadata")
        if _candidate_digest(rederived) != candidate_sha256:
            raise ArtifactValidationError("Candidates cannot be reproduced from raw responses")
        return {
            "artifact": str(artifact_path),
            "artifact_sha256": artifact_sha256,
            "schema_version": schema_version,
            "candidate_sha256": candidate_sha256,
            "spec_sha256": effective_spec.sha256,
            "incident_id": effective_spec.incident_id,
            "source_tag": effective_spec.source_tag,
            "coins": len(effective_spec.coins),
            "hours_per_coin": effective_spec.hours,
            "candidates": len(candidates),
            "start_hour": effective_spec.start_hour.isoformat(),
            "end_exclusive": effective_spec.end_exclusive.isoformat(),
            "status": "valid",
        }
    finally:
        connection.close()


def _validated_artifact_snapshot(
    artifact_path: Path,
    *,
    expected_digest: str | None,
    spec: PriceGapSpec,
) -> tuple[dict[str, Any], list[Candidate]]:
    """Validate and load candidates from one private, path-independent snapshot."""
    artifact_path = artifact_path.expanduser().resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix="price-gap-artifact-", suffix=".sqlite")
    os.close(descriptor)
    snapshot_path = Path(temporary_name)
    snapshot_receipt = _receipt_path(snapshot_path)
    snapshot_raw_dir = _raw_dir_path(snapshot_path)
    source_raw_dir = _raw_dir_path(artifact_path)
    try:
        shutil.copyfile(artifact_path, snapshot_path)
        shutil.copytree(source_raw_dir, snapshot_raw_dir, symlinks=True)
        digest = _sha256_file(snapshot_path)
        snapshot_receipt.write_text(f"{digest}  {snapshot_path.name}\n", encoding="utf-8")
        report = validate_artifact(
            snapshot_path,
            expected_digest=expected_digest,
            spec=spec,
        )
        with _readonly_connection(snapshot_path, immutable=True) as connection:
            candidates = _load_candidates(connection)
        report["artifact"] = str(artifact_path)
        return report, candidates
    finally:
        snapshot_path.unlink(missing_ok=True)
        snapshot_receipt.unlink(missing_ok=True)
        shutil.rmtree(snapshot_raw_dir, ignore_errors=True)


def _validate_target_schema(connection: sqlite3.Connection) -> None:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise ArtifactValidationError(f"Target quick_check failed: {quick_check}")
    table_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'price_data'"
    ).fetchone()
    if table_row is None or table_row["sql"] is None:
        raise ArtifactValidationError("Target has no price_data table")
    table_sql = " ".join(str(table_row["sql"]).upper().split())
    if not re.search(
        r"\bID\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        table_sql,
    ):
        raise ArtifactValidationError(
            "Target price_data.id must be INTEGER PRIMARY KEY AUTOINCREMENT"
        )
    table_info = connection.execute("PRAGMA table_info(price_data)").fetchall()
    columns = {row["name"] for row in table_info}
    missing = REQUIRED_PRICE_COLUMNS - columns
    if missing:
        raise ArtifactValidationError(f"Target price_data is missing columns: {sorted(missing)}")
    id_rows = [row for row in table_info if row["name"] == "id"]
    if len(id_rows) != 1 or str(id_rows[0]["type"]).upper() != "INTEGER" or id_rows[0]["pk"] != 1:
        raise ArtifactValidationError("Target price_data.id has incompatible primary-key semantics")
    triggers = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'price_data'"
    ).fetchall()
    if triggers:
        raise ArtifactValidationError(
            f"Target price_data has unexpected trigger(s): {[row['name'] for row in triggers]}"
        )
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    inbound_foreign_keys = []
    for table in tables:
        table_name = str(table["name"])
        quoted_name = table_name.replace('"', '""')
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{quoted_name}")'
        ).fetchall()
        inbound_foreign_keys.extend(
            (table_name, row["id"])
            for row in foreign_keys
            if row["table"] == "price_data"
        )
    if inbound_foreign_keys:
        raise ArtifactValidationError(
            f"Target has foreign keys referencing price_data: {inbound_foreign_keys}"
        )


def _manifest_tables_present(connection: sqlite3.Connection) -> set[str]:
    names = {
        row["name"]
        for row in connection.execute(
            f"""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name IN ({','.join('?' for _ in TARGET_MANIFEST_TABLES)})
            """,
            tuple(sorted(TARGET_MANIFEST_TABLES)),
        ).fetchall()
    }
    return names


def _manifest_tables_exist(connection: sqlite3.Connection) -> bool:
    present = _manifest_tables_present(connection)
    if present and present != TARGET_MANIFEST_TABLES:
        raise ArtifactValidationError(
            f"Target has an incomplete price gap manifest schema: {sorted(present)}"
        )
    return present == TARGET_MANIFEST_TABLES


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).casefold()


def _detect_manifest_version(connection: sqlite3.Connection) -> int | None:
    present = _manifest_tables_present(connection)
    if not present:
        return None
    if present != TARGET_MANIFEST_TABLES:
        raise ArtifactValidationError(
            f"Target has an incomplete price gap manifest schema: {sorted(present)}"
        )
    schema_rows = connection.execute(
        "SELECT singleton, schema_version FROM price_gap_patch_schema"
    ).fetchall()
    if len(schema_rows) != 1 or schema_rows[0]["singleton"] != 1:
        raise ArtifactValidationError("Target manifest schema singleton is invalid")
    return int(schema_rows[0]["schema_version"])


def _validate_manifest_schema(connection: sqlite3.Connection) -> int:
    version = _detect_manifest_version(connection)
    if version is None:
        raise ArtifactValidationError("Target has no price gap patch manifest tables")
    if version == TARGET_MANIFEST_SCHEMA_VERSION_V1:
        template = TARGET_MANIFEST_TABLE_SQL_V1
    elif version == TARGET_MANIFEST_SCHEMA_VERSION_V2:
        template = TARGET_MANIFEST_TABLE_SQL_V2
    else:
        raise ArtifactValidationError(f"Unsupported manifest schema version: {version}")
    for table, expected_sql in template.items():
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if row is None or row["sql"] is None or _normalize_sql(row["sql"]) != _normalize_sql(
            expected_sql
        ):
            raise ArtifactValidationError(
                f"Target manifest table {table} has an incompatible schema"
            )
    return version


def _migrate_manifest_to_v2(connection: sqlite3.Connection) -> None:
    """Migrate a v1 manifest to v2 inside the caller's active transaction.

    Uses only individual ``execute`` statements (never ``executescript``) so the
    surrounding ``BEGIN IMMEDIATE`` is never interrupted. Foreign keys stay ON.
    Legacy rows are copied through temporary tables, then the old tables are
    dropped child-first and the v2 tables are recreated under their final names.
    """
    if not connection.in_transaction:
        raise ArtifactValidationError("Manifest migration requires an active target transaction")
    if _validate_manifest_schema(connection) != TARGET_MANIFEST_SCHEMA_VERSION_V1:
        raise ArtifactValidationError("Only an exact manifest schema v1 can be migrated")

    legacy_runs = connection.execute(
        """
        SELECT run_id, incident_id, artifact_sha256, candidate_sha256, source_tag,
               applied_at, state, inserted_count, backup_path, backup_sha256,
               rollback_backup_path, rollback_backup_sha256, rolled_back_count, rolled_back_at
        FROM price_gap_patch_runs ORDER BY run_id
        """
    ).fetchall()
    legacy_rows = connection.execute(
        """
        SELECT run_id, candidate_coin, candidate_hour_epoch, price_data_id,
               expected_timestamp, expected_price, expected_volume,
               expected_market_cap, expected_source
        FROM price_gap_patch_rows ORDER BY run_id, candidate_coin, candidate_hour_epoch
        """
    ).fetchall()
    for run in legacy_runs:
        if run["state"] == "applied":
            _verify_applied_run(connection, run)
        elif run["state"] == "rolled_back":
            count = connection.execute(
                "SELECT COUNT(*) FROM price_gap_patch_rows WHERE run_id = ?",
                (run["run_id"],),
            ).fetchone()[0]
            if count != run["inserted_count"]:
                raise ArtifactValidationError("Legacy rolled-back run has an invalid manifest")
        else:
            raise ArtifactValidationError(f"Unsupported legacy run state: {run['state']}")

    # Rename the parent first (SQLite rewrites the child FK to the legacy name),
    # then rename the child out of the way so both final names are free.
    connection.execute(
        "ALTER TABLE price_gap_patch_runs RENAME TO price_gap_patch_runs_legacy"
    )
    _assert_transaction_active(connection, "during manifest runs rename")
    connection.execute(
        "ALTER TABLE price_gap_patch_rows RENAME TO price_gap_patch_rows_legacy"
    )
    _assert_transaction_active(connection, "during manifest rows rename")

    # Drop the old child first, then the old parent, and recreate final v2 tables.
    connection.execute("DROP TABLE price_gap_patch_rows_legacy")
    connection.execute("DROP TABLE price_gap_patch_runs_legacy")
    _assert_transaction_active(connection, "during manifest legacy table removal")

    connection.execute(TARGET_MANIFEST_TABLE_SQL_V2["price_gap_patch_runs"])
    connection.executemany(
        """
        INSERT INTO price_gap_patch_runs (
            run_id, incident_id, artifact_sha256, candidate_sha256, source_tag,
            applied_at, state, inserted_count, backup_path, backup_sha256,
            rollback_backup_path, rollback_backup_sha256, rolled_back_count, rolled_back_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [tuple(row) for row in legacy_runs],
    )
    connection.execute(TARGET_MANIFEST_TABLE_SQL_V2["price_gap_patch_rows"])
    connection.executemany(
        """
        INSERT INTO price_gap_patch_rows (
            run_id, candidate_coin, candidate_hour_epoch, price_data_id,
            expected_timestamp, expected_price, expected_volume,
            expected_market_cap, expected_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [tuple(row) for row in legacy_rows],
    )
    _assert_transaction_active(connection, "during manifest v2 data copy")

    # Recreate the schema singleton with the v2 version marker.
    connection.execute("DROP TABLE price_gap_patch_schema")
    connection.execute(TARGET_MANIFEST_TABLE_SQL_V2["price_gap_patch_schema"])
    connection.execute(
        "INSERT INTO price_gap_patch_schema (singleton, schema_version) VALUES (1, ?)",
        (TARGET_MANIFEST_SCHEMA_VERSION_V2,),
    )
    _assert_transaction_active(connection, "during manifest schema version update")

    if _validate_manifest_schema(connection) != TARGET_MANIFEST_SCHEMA_VERSION_V2:
        raise ArtifactValidationError("Manifest migration did not produce schema v2")


def _create_manifest_tables(connection: sqlite3.Connection) -> None:
    """Ensure a v2 manifest exists without allowing executescript to commit.

    Existing v1 manifests are migrated in-place (preserving legacy runs); fresh
    targets get schema v2 directly.
    """
    version = _detect_manifest_version(connection)
    if version is not None:
        if version == TARGET_MANIFEST_SCHEMA_VERSION_V1:
            _migrate_manifest_to_v2(connection)
        else:
            _validate_manifest_schema(connection)
        return

    if not connection.in_transaction:
        raise ArtifactValidationError("Manifest creation requires an active target transaction")
    for table in TARGET_MANIFEST_TABLE_NAMES:
        connection.execute(TARGET_MANIFEST_TABLE_SQL_V2[table])
        if not connection.in_transaction:
            raise ArtifactValidationError("Target transaction ended during manifest creation")
    connection.execute(
        "INSERT INTO price_gap_patch_schema (singleton, schema_version) VALUES (1, ?)",
        (TARGET_MANIFEST_SCHEMA_VERSION_V2,),
    )
    _validate_manifest_schema(connection)


def _value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and float(actual) == expected
    return actual == expected


def _verify_applied_run(connection: sqlite3.Connection, run: sqlite3.Row) -> None:
    manifest_rows = connection.execute(
        "SELECT * FROM price_gap_patch_rows WHERE run_id = ? ORDER BY price_data_id",
        (run["run_id"],),
    ).fetchall()
    if len(manifest_rows) != run["inserted_count"]:
        raise ArtifactValidationError(
            f"Applied run {run['run_id']} has {len(manifest_rows)} manifest rows, "
            f"expected {run['inserted_count']}"
        )
    for manifest in manifest_rows:
        actual = connection.execute(
            "SELECT * FROM price_data WHERE id = ?", (manifest["price_data_id"],)
        ).fetchone()
        if actual is None:
            raise ArtifactValidationError(
                f"Applied row {manifest['price_data_id']} is missing from price_data"
            )
        expected = {
            "timestamp": manifest["expected_timestamp"],
            "coin": manifest["candidate_coin"],
            "price_usd": manifest["expected_price"],
            "volume_24h": manifest["expected_volume"],
            "market_cap": manifest["expected_market_cap"],
            "source": manifest["expected_source"],
        }
        for key, value in expected.items():
            if not _value_matches(actual[key], value):
                raise ArtifactValidationError(
                    f"Applied row {actual['id']} no longer matches manifest field {key}"
                )

    manifest_ids = {row["price_data_id"] for row in manifest_rows}
    coins = {row["candidate_coin"] for row in manifest_rows}
    hour_set = {row["candidate_hour_epoch"] for row in manifest_rows}
    occupied = _existing_candidate_buckets(connection, coins=coins, hour_set=hour_set)
    for manifest in manifest_rows:
        key = (manifest["candidate_coin"], manifest["candidate_hour_epoch"])
        bucket_ids = {row["id"] for row in occupied.get(key, [])}
        if bucket_ids != {manifest["price_data_id"]}:
            extras = sorted(bucket_ids - manifest_ids)
            raise ArtifactValidationError(
                f"Applied run {run['run_id']} has unexpected row(s) in "
                f"{manifest['candidate_coin']} at {manifest['expected_timestamp']}: {extras}"
            )


def _existing_candidate_buckets(
    connection: sqlite3.Connection,
    *,
    coins: Iterable[str],
    hour_set: Iterable[int],
) -> dict[tuple[str, int], list[dict]]:
    coin_list = tuple(coins)
    hour_set = frozenset(hour_set)
    if not coin_list:
        return {}
    placeholders = ",".join("?" for _ in coin_list)
    rows = connection.execute(
        f"""
        SELECT id, timestamp, coin, price_usd, volume_24h, market_cap, source
        FROM price_data
        WHERE UPPER(TRIM(coin)) IN ({placeholders})
        """,
        coin_list,
    ).fetchall()
    buckets: dict[tuple[str, int], list[dict]] = {}
    for row in rows:
        try:
            timestamp = _parse_utc_timestamp(row["timestamp"])
        except (TypeError, ValueError):
            raise ArtifactValidationError(
                f"Target price row {row['id']} has an unparseable timestamp"
            ) from None
        epoch = int(timestamp.replace(minute=0, second=0, microsecond=0).timestamp())
        coin = row["coin"].strip().upper()
        key = (coin, epoch)
        if epoch in hour_set:
            buckets.setdefault(key, []).append(dict(row))
    return buckets


def classify_target(
    connection: sqlite3.Connection,
    *,
    spec: PriceGapSpec,
    artifact_sha256: str,
    candidates: Sequence[Candidate],
) -> TargetClassification:
    """Classify a target without mutating it."""
    _validate_target_schema(connection)
    if _manifest_tables_exist(connection):
        _validate_manifest_schema(connection)
        runs = connection.execute(
            """
            SELECT * FROM price_gap_patch_runs
            WHERE incident_id = ? AND artifact_sha256 = ? AND state = 'applied'
            ORDER BY applied_at
            """,
            (spec.incident_id, artifact_sha256),
        ).fetchall()
        if len(runs) > 1:
            raise ArtifactValidationError("Multiple applied runs exist for the same artifact")
        if runs:
            _verify_applied_run(connection, runs[0])
            return TargetClassification(status="already_applied", run_id=runs[0]["run_id"])

    existing = _existing_candidate_buckets(
        connection,
        coins=spec.coin_mapping,
        hour_set=spec.expected_hour_set,
    )
    conflicts = []
    for candidate in candidates:
        rows = existing.get((candidate.coin, candidate.hour_epoch), [])
        if rows:
            conflicts.append(
                {
                    "coin": candidate.coin,
                    "hour": candidate.timestamp,
                    "existing_rows": [row["id"] for row in rows],
                    "existing_sources": sorted({str(row["source"]) for row in rows}),
                }
            )
    if conflicts:
        return TargetClassification(status="conflict", conflicts=tuple(conflicts))
    return TargetClassification(status="ready")


def inspect_target(
    artifact_path: Path, target_path: Path, *, spec: PriceGapSpec
) -> dict[str, Any]:
    artifact_report, candidates = _validated_artifact_snapshot(
        artifact_path, expected_digest=None, spec=spec
    )
    target_path = target_path.expanduser().resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"Target database not found: {target_path}")
    with _readonly_connection(target_path) as target:
        target.execute("BEGIN")
        try:
            classification = classify_target(
                target,
                spec=spec,
                artifact_sha256=artifact_report["artifact_sha256"],
                candidates=candidates,
            )
        finally:
            target.rollback()
    return {
        **artifact_report,
        "target": str(target_path),
        "target_status": classification.status,
        "target_run_id": classification.run_id,
        "conflict_count": len(classification.conflicts),
        "conflicts": list(classification.conflicts),
    }


def inspect_run(target_path: Path, run_id: str) -> dict[str, Any]:
    """Read-only inspection of one applied manifest run, independent of artifacts."""
    target_path = target_path.expanduser().resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"Target database not found: {target_path}")
    with _readonly_connection(target_path) as target:
        target.execute("BEGIN")
        _validate_target_schema(target)
        if not _manifest_tables_exist(target):
            raise ArtifactValidationError("Target has no price gap patch manifest tables")
        _validate_manifest_schema(target)
        run = target.execute(
            "SELECT * FROM price_gap_patch_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ArtifactValidationError(f"Patch run not found: {run_id}")
        manifest_rows = target.execute(
            "SELECT price_data_id FROM price_gap_patch_rows WHERE run_id = ?", (run_id,)
        ).fetchall()
        row_count = len(manifest_rows)
        if row_count != run["inserted_count"]:
            raise ArtifactValidationError("Run manifest count does not match inserted_count")
        if run["state"] == "applied":
            _verify_applied_run(target, run)
            verification = "verified"
        elif run["state"] == "rolled_back":
            ids = [row["price_data_id"] for row in manifest_rows]
            present = 0
            for offset in range(0, len(ids), ROLLBACK_DELETE_CHUNK):
                chunk = ids[offset : offset + ROLLBACK_DELETE_CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                present += target.execute(
                    f"SELECT COUNT(*) FROM price_data WHERE id IN ({placeholders})", tuple(chunk)
                ).fetchone()[0]
            if present:
                raise ArtifactValidationError("Rolled-back run still has manifested price rows")
            verification = "verified_rolled_back"
        else:
            raise ArtifactValidationError(f"Unsupported patch run state: {run['state']}")
        report = {
            "target": str(target_path),
            "run_id": run["run_id"],
            "incident_id": run["incident_id"],
            "state": run["state"],
            "inserted_count": run["inserted_count"],
            "rolled_back_count": run["rolled_back_count"],
            "artifact_sha256": run["artifact_sha256"],
            "candidate_sha256": run["candidate_sha256"],
            "source_tag": run["source_tag"],
            "applied_at": run["applied_at"],
            "rolled_back_at": run["rolled_back_at"],
            "spec_sha256": run["spec_sha256"] if "spec_sha256" in run.keys() else None,
            "manifest_rows": row_count,
            "verification": verification,
        }
        target.rollback()
        return report


def _require_absolute_regular_file(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ConfirmationError(f"{label} path must be absolute: {path}")
    resolved = path.expanduser().resolve()
    try:
        mode = resolved.stat().st_mode
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} file not found: {resolved}") from None
    if not stat.S_ISREG(mode):
        raise ConfirmationError(f"{label} must be a regular file: {resolved}")
    return resolved


def _guard_mutation(
    *,
    target_path: Path,
    incident_id: str,
    confirm_incident: str,
    confirm_target: str,
    writers_paused: bool,
) -> Path:
    target_path = _require_absolute_regular_file(target_path, "Target")
    if confirm_incident != incident_id:
        raise ConfirmationError(f"--confirm-incident must equal {incident_id}")
    if confirm_target != str(target_path):
        raise ConfirmationError(
            "--confirm-target must exactly match the canonical target path emitted by inspect"
        )
    if not writers_paused:
        raise ConfirmationError("Confirm that crawler writers are paused before mutation")
    return target_path


def _validate_backup_path(backup_path: Path, *, forbidden: Sequence[Path]) -> Path:
    if not backup_path.is_absolute():
        raise ConfirmationError(f"Backup path must be absolute: {backup_path}")
    backup_path = backup_path.expanduser().resolve()
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {backup_path}")
    if not backup_path.parent.is_dir():
        raise FileNotFoundError(f"Backup parent does not exist: {backup_path.parent}")
    for path in forbidden:
        if backup_path == path:
            raise ConfirmationError("Backup path must differ from target and artifact")
    return backup_path


def _backup_database(source_path: Path, backup_path: Path) -> str:
    descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        source = _readonly_connection(source_path)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.commit()
            quick_check = destination.execute("PRAGMA quick_check").fetchone()[0]
            if quick_check != "ok":
                raise ArtifactValidationError(f"Backup quick_check failed: {quick_check}")
        finally:
            destination.close()
            source.close()
        os.chmod(backup_path, 0o400)
        with backup_path.open("rb") as handle:
            os.fsync(handle.fileno())
        _sync_directory(backup_path.parent)
        return _sha256_file(backup_path)
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


def _validate_target_storage(connection: sqlite3.Connection) -> None:
    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).casefold()
    if journal_mode in {"off", "memory"}:
        raise ArtifactValidationError(f"Unsafe target journal_mode: {journal_mode}")
    connection.execute("PRAGMA synchronous = FULL")


ForeignKeyViolation = tuple[str, int | None, str, int]


def _foreign_key_violations(connection: sqlite3.Connection) -> Counter[ForeignKeyViolation]:
    return Counter(
        (row["table"], row["rowid"], row["parent"], row["fkid"])
        for row in connection.execute("PRAGMA main.foreign_key_check").fetchall()
    )


def _foreign_key_baseline_digest(violations: Counter[ForeignKeyViolation]) -> str:
    payload = [
        [table, rowid, parent, foreign_key_id, count]
        for (table, rowid, parent, foreign_key_id), count in sorted(
            violations.items(), key=lambda item: tuple(str(value) for value in item[0])
        )
    ]
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _verify_foreign_key_baseline(
    connection: sqlite3.Connection,
    baseline: Counter[ForeignKeyViolation],
    operation: str,
) -> None:
    current = _foreign_key_violations(connection)
    if current != baseline:
        added = sum((current - baseline).values())
        removed = sum((baseline - current).values())
        raise ArtifactValidationError(
            f"Target foreign-key baseline changed during {operation}: "
            f"baseline={sum(baseline.values())}, current={sum(current.values())}, "
            f"added={added}, removed={removed}"
        )


def _assert_transaction_active(connection: sqlite3.Connection, operation: str) -> None:
    if not connection.in_transaction:
        raise ArtifactValidationError(f"Target transaction ended unexpectedly {operation}")


def apply_patch(
    artifact_path: Path,
    target_path: Path,
    backup_path: Path,
    *,
    spec: PriceGapSpec,
    expected_artifact_sha256: str,
    confirm_spec_sha256: str,
    confirm_candidates: int,
    confirm_incident: str,
    confirm_target: str,
    writers_paused: bool,
) -> dict[str, Any]:
    """Atomically apply the spec's candidates or make no target data changes."""
    if confirm_spec_sha256.lower() != spec.sha256:
        raise ConfirmationError("--confirm-spec-sha256 must equal the loaded spec digest")
    if confirm_candidates != spec.candidate_count:
        raise ConfirmationError(f"--confirm-candidates must equal {spec.candidate_count}")
    artifact_path = _require_absolute_regular_file(artifact_path, "Artifact")
    target_path = _guard_mutation(
        target_path=target_path,
        incident_id=spec.incident_id,
        confirm_incident=confirm_incident,
        confirm_target=confirm_target,
        writers_paused=writers_paused,
    )
    if artifact_path.samefile(target_path):
        raise ConfirmationError("Artifact and target database must be different files")
    artifact_report, candidates = _validated_artifact_snapshot(
        artifact_path,
        expected_digest=expected_artifact_sha256,
        spec=spec,
    )

    connection = _readwrite_connection(target_path)
    backup_created = False
    try:
        _validate_target_storage(connection)
        connection.execute("BEGIN IMMEDIATE")
        _assert_transaction_active(connection, "after acquiring the write lock")
        foreign_key_baseline = _foreign_key_violations(connection)
        foreign_key_baseline_count = sum(foreign_key_baseline.values())
        foreign_key_baseline_sha256 = _foreign_key_baseline_digest(foreign_key_baseline)
        classification = classify_target(
            connection,
            spec=spec,
            artifact_sha256=artifact_report["artifact_sha256"],
            candidates=candidates,
        )
        if classification.status == "already_applied":
            connection.rollback()
            return {
                "status": "already_applied",
                "run_id": classification.run_id,
                "inserted": 0,
                "foreign_key_baseline_count": foreign_key_baseline_count,
                "foreign_key_baseline_sha256": foreign_key_baseline_sha256,
            }
        if classification.status == "conflict":
            connection.rollback()
            raise TargetConflictError(
                f"Target has {len(classification.conflicts)} populated candidate bucket(s)"
            )

        backup_path = _validate_backup_path(
            backup_path, forbidden=(artifact_path, target_path)
        )
        backup_sha256 = _backup_database(target_path, backup_path)
        backup_created = True
        _assert_transaction_active(connection, "while creating the pre-apply backup")

        _create_manifest_tables(connection)
        _assert_transaction_active(connection, "while creating the manifest schema")
        run_id = str(uuid.uuid4())
        applied_at = _utc_now().isoformat()
        connection.execute(
            """
            INSERT INTO price_gap_patch_runs (
                run_id, incident_id, artifact_sha256, candidate_sha256, source_tag,
                applied_at, state, inserted_count, backup_path, backup_sha256,
                spec_json, spec_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, 'applied', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                spec.incident_id,
                artifact_report["artifact_sha256"],
                artifact_report["candidate_sha256"],
                spec.source_tag,
                applied_at,
                len(candidates),
                str(backup_path),
                backup_sha256,
                spec.canonical_json(),
                spec.sha256,
            ),
        )
        for candidate in candidates:
            cursor = connection.execute(
                """
                INSERT INTO price_data (
                    timestamp, coin, price_usd, volume_24h, market_cap, source
                ) VALUES (?, ?, ?, ?, ?, ?)
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
            price_data_id = int(cursor.lastrowid)
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
                    price_data_id,
                    candidate.timestamp,
                    candidate.price_usd,
                    candidate.volume_24h,
                    candidate.market_cap,
                    spec.source_tag,
                ),
            )

        manifest_count = connection.execute(
            "SELECT COUNT(*) FROM price_gap_patch_rows WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        if manifest_count != spec.candidate_count:
            raise ArtifactValidationError(
                f"Apply manifest has {manifest_count} rows before commit"
            )
        run = connection.execute(
            "SELECT * FROM price_gap_patch_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert run is not None
        _verify_applied_run(connection, run)
        _verify_foreign_key_baseline(connection, foreign_key_baseline, "apply")
        _assert_transaction_active(connection, "before the apply commit")
        connection.commit()
        if connection.in_transaction:
            raise ArtifactValidationError("Target transaction remained open after apply commit")
        return {
            "status": "applied",
            "run_id": run_id,
            "inserted": manifest_count,
            "backup": str(backup_path),
            "backup_sha256": backup_sha256,
            "source_tag": spec.source_tag,
            "spec_sha256": spec.sha256,
            "foreign_key_baseline_count": foreign_key_baseline_count,
            "foreign_key_baseline_sha256": foreign_key_baseline_sha256,
        }
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        if backup_created:
            print(
                f"Apply failed; verified pre-apply backup retained at {backup_path}",
                file=sys.stderr,
            )
        raise
    finally:
        connection.close()


def rollback_patch(
    target_path: Path,
    backup_path: Path,
    *,
    run_id: str,
    confirm_run_id: str,
    confirm_incident: str,
    confirm_target: str,
    writers_paused: bool,
) -> dict[str, Any]:
    """Delete only the unchanged price rows recorded by one applied manifest.

    Spec-independent: the run's own ``incident_id`` and ``inserted_count`` drive
    confirmation and verification, never a hardcoded or active spec.
    """
    if confirm_run_id != run_id:
        raise ConfirmationError("--confirm-run-id must exactly match --run-id")
    connection = _readwrite_connection(target_path)
    backup_created = False
    try:
        _validate_target_storage(connection)
        connection.execute("BEGIN IMMEDIATE")
        _assert_transaction_active(connection, "after acquiring the rollback write lock")
        foreign_key_baseline = _foreign_key_violations(connection)
        foreign_key_baseline_count = sum(foreign_key_baseline.values())
        foreign_key_baseline_sha256 = _foreign_key_baseline_digest(foreign_key_baseline)
        _validate_target_schema(connection)
        if not _manifest_tables_exist(connection):
            raise ArtifactValidationError("Target has no price gap patch manifest tables")
        _validate_manifest_schema(connection)
        run = connection.execute(
            "SELECT * FROM price_gap_patch_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ArtifactValidationError(f"Patch run not found: {run_id}")
        _guard_mutation(
            target_path=target_path,
            incident_id=run["incident_id"],
            confirm_incident=confirm_incident,
            confirm_target=confirm_target,
            writers_paused=writers_paused,
        )
        if run["state"] == "rolled_back":
            manifest_ids = [
                row["price_data_id"]
                for row in connection.execute(
                    "SELECT price_data_id FROM price_gap_patch_rows WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
            ]
            present = 0
            for offset in range(0, len(manifest_ids), ROLLBACK_DELETE_CHUNK):
                chunk = manifest_ids[offset : offset + ROLLBACK_DELETE_CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                present += connection.execute(
                    f"SELECT COUNT(*) FROM price_data WHERE id IN ({placeholders})", tuple(chunk)
                ).fetchone()[0]
            if present:
                raise ArtifactValidationError(
                    "Rolled-back run still has one or more manifested price rows"
                )
            connection.rollback()
            return {
                "status": "already_rolled_back",
                "run_id": run_id,
                "deleted": 0,
                "foreign_key_baseline_count": foreign_key_baseline_count,
                "foreign_key_baseline_sha256": foreign_key_baseline_sha256,
            }
        if run["state"] != "applied":
            raise ArtifactValidationError(f"Unsupported patch run state: {run['state']}")
        _verify_applied_run(connection, run)

        backup_path = _validate_backup_path(backup_path, forbidden=(target_path,))
        backup_sha256 = _backup_database(target_path, backup_path)
        backup_created = True
        _assert_transaction_active(connection, "while creating the pre-rollback backup")

        ids = [
            row["price_data_id"]
            for row in connection.execute(
                "SELECT price_data_id FROM price_gap_patch_rows WHERE run_id = ?", (run_id,)
            ).fetchall()
        ]
        deleted = 0
        for offset in range(0, len(ids), ROLLBACK_DELETE_CHUNK):
            chunk = ids[offset : offset + ROLLBACK_DELETE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            deleted += connection.execute(
                f"DELETE FROM price_data WHERE id IN ({placeholders})", tuple(chunk)
            ).rowcount
        if deleted != run["inserted_count"]:
            raise ArtifactValidationError(
                f"Rollback deleted {deleted} rows, expected {run['inserted_count']}"
            )
        connection.execute(
            """
            UPDATE price_gap_patch_runs
            SET state = 'rolled_back',
                rollback_backup_path = ?,
                rollback_backup_sha256 = ?,
                rolled_back_count = ?,
                rolled_back_at = ?
            WHERE run_id = ?
            """,
            (
                str(backup_path),
                backup_sha256,
                deleted,
                _utc_now().isoformat(),
                run_id,
            ),
        )
        _verify_foreign_key_baseline(connection, foreign_key_baseline, "rollback")
        _assert_transaction_active(connection, "before the rollback commit")
        connection.commit()
        if connection.in_transaction:
            raise ArtifactValidationError("Target transaction remained open after rollback commit")
        return {
            "status": "rolled_back",
            "run_id": run_id,
            "deleted": deleted,
            "backup": str(backup_path),
            "backup_sha256": backup_sha256,
            "foreign_key_baseline_count": foreign_key_baseline_count,
            "foreign_key_baseline_sha256": foreign_key_baseline_sha256,
        }
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        if backup_created:
            print(
                f"Rollback failed; verified pre-rollback backup retained at {backup_path}",
                file=sys.stderr,
            )
        raise
    finally:
        connection.close()


def _print_report(report: Mapping[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and apply reusable offline CoinGecko price-gap patches from a spec"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect into a new offline artifact")
    collect.add_argument("--spec", type=Path, required=True)
    collect.add_argument("--artifact", type=Path, required=True)
    collect.add_argument("--max-attempts", type=int, default=6)
    collect.add_argument("--request-delay", type=float, default=7.0)

    inspect = subparsers.add_parser("inspect", help="Validate an artifact and optional target")
    inspect.add_argument("--spec", type=Path, required=True)
    inspect.add_argument("--artifact", type=Path, required=True)
    inspect.add_argument("--target", type=Path)

    inspect_run = subparsers.add_parser(
        "inspect-run", help="Read-only inspection of one applied run (no artifact/spec)"
    )
    inspect_run.add_argument("--target", type=Path, required=True)
    inspect_run.add_argument("--run-id", required=True)

    apply = subparsers.add_parser("apply", help="Apply the sealed artifact transactionally")
    apply.add_argument("--spec", type=Path, required=True)
    apply.add_argument("--artifact", type=Path, required=True)
    apply.add_argument("--target", type=Path, required=True)
    apply.add_argument("--backup", type=Path, required=True)
    apply.add_argument("--artifact-sha256", required=True)
    apply.add_argument("--confirm-spec-sha256", required=True)
    apply.add_argument("--confirm-candidates", type=int, required=True)
    apply.add_argument("--confirm-incident", required=True)
    apply.add_argument("--confirm-target", required=True)
    apply.add_argument("--confirm-writers-paused", action="store_true")

    rollback = subparsers.add_parser("rollback", help="Delete one run's exact manifested rows")
    rollback.add_argument("--target", type=Path, required=True)
    rollback.add_argument("--backup", type=Path, required=True)
    rollback.add_argument("--run-id", required=True)
    rollback.add_argument("--confirm-run-id", required=True)
    rollback.add_argument("--confirm-incident", required=True)
    rollback.add_argument("--confirm-target", required=True)
    rollback.add_argument("--confirm-writers-paused", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            spec = load_spec(args.spec)
            spec.ensure_collectable()
            attempts = fetch_all_attempts(
                spec=spec,
                max_attempts=args.max_attempts,
                request_delay=args.request_delay,
            )
            report = create_patch_artifact(
                args.artifact,
                attempts,
                spec=spec,
            )
        elif args.command == "inspect":
            spec = load_spec(args.spec)
            report = (
                inspect_target(args.artifact, args.target, spec=spec)
                if args.target
                else validate_artifact(args.artifact, spec=spec)
            )
        elif args.command == "inspect-run":
            report = inspect_run(args.target, args.run_id)
        elif args.command == "apply":
            spec = load_spec(args.spec)
            report = apply_patch(
                args.artifact,
                args.target,
                args.backup,
                spec=spec,
                expected_artifact_sha256=args.artifact_sha256,
                confirm_spec_sha256=args.confirm_spec_sha256,
                confirm_candidates=args.confirm_candidates,
                confirm_incident=args.confirm_incident,
                confirm_target=args.confirm_target,
                writers_paused=args.confirm_writers_paused,
            )
        else:
            report = rollback_patch(
                args.target,
                args.backup,
                run_id=args.run_id,
                confirm_run_id=args.confirm_run_id,
                confirm_incident=args.confirm_incident,
                confirm_target=args.confirm_target,
                writers_paused=args.confirm_writers_paused,
            )
        _print_report(report)
        return 0
    except (
        OSError,
        sqlite3.Error,
        httpx.HTTPError,
        PriceGapPatchError,
        PriceGapSpecError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
