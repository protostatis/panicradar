"""Strict immutable specifications for offline CoinGecko outage patches."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC = timezone.utc
SPEC_SCHEMA_VERSION = 1
MAX_HOURS = 7 * 24
MAX_COINS = 25
MAX_CANDIDATES = 2_000
EXPECTED_KEYS = {
    "schema_version",
    "incident_id",
    "provider",
    "source_tag",
    "start_hour",
    "end_exclusive",
    "coins",
}
INCIDENT_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")
SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{2,10}")
PROVIDER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,99}")


class PriceGapSpecError(ValueError):
    """A patch specification is malformed or outside the safety envelope."""


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PriceGapSpecError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_full_utc_hour(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise PriceGapSpecError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PriceGapSpecError(f"{field} is not a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PriceGapSpecError(f"{field} must use UTC")
    parsed = parsed.astimezone(UTC)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise PriceGapSpecError(f"{field} must be a full UTC hour")
    return parsed


@dataclass(frozen=True)
class PriceGapSpec:
    """Validated immutable description of one bounded CoinGecko outage."""

    schema_version: int
    incident_id: str
    provider: str
    source_tag: str
    start_hour: datetime
    end_exclusive: datetime
    coins: tuple[tuple[str, str], ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PriceGapSpec:
        if set(raw) != EXPECTED_KEYS:
            missing = sorted(EXPECTED_KEYS - set(raw))
            unknown = sorted(set(raw) - EXPECTED_KEYS)
            raise PriceGapSpecError(
                f"Spec keys do not match schema; missing={missing}, unknown={unknown}"
            )
        schema_version = raw["schema_version"]
        if type(schema_version) is not int or schema_version != SPEC_SCHEMA_VERSION:
            raise PriceGapSpecError(f"schema_version must equal {SPEC_SCHEMA_VERSION}")

        incident_id = raw["incident_id"]
        if not isinstance(incident_id, str) or not INCIDENT_PATTERN.fullmatch(incident_id):
            raise PriceGapSpecError("incident_id must be a safe lowercase identifier")
        provider = raw["provider"]
        if provider != "coingecko":
            raise PriceGapSpecError("provider must equal coingecko")
        expected_source = f"{provider}_gap_backfill:{incident_id}"
        source_tag = raw["source_tag"]
        if source_tag != expected_source:
            raise PriceGapSpecError(f"source_tag must equal {expected_source}")
        if len(source_tag) > 50:
            raise PriceGapSpecError("source_tag exceeds the price_data source limit")

        start_hour = _parse_full_utc_hour(raw["start_hour"], "start_hour")
        end_exclusive = _parse_full_utc_hour(raw["end_exclusive"], "end_exclusive")
        hours = int((end_exclusive - start_hour).total_seconds() // 3600)
        if hours <= 0:
            raise PriceGapSpecError("end_exclusive must be after start_hour")
        if hours > MAX_HOURS:
            raise PriceGapSpecError(f"Spec exceeds the {MAX_HOURS}-hour safety limit")

        raw_coins = raw["coins"]
        if not isinstance(raw_coins, Mapping):
            raise PriceGapSpecError("coins must be a JSON object")
        if not 1 <= len(raw_coins) <= MAX_COINS:
            raise PriceGapSpecError(f"coins must contain between 1 and {MAX_COINS} entries")
        coins: list[tuple[str, str]] = []
        provider_ids: set[str] = set()
        for symbol, provider_id in raw_coins.items():
            if not isinstance(symbol, str) or not SYMBOL_PATTERN.fullmatch(symbol):
                raise PriceGapSpecError(f"Invalid uppercase coin symbol: {symbol!r}")
            if not isinstance(provider_id, str) or not PROVIDER_ID_PATTERN.fullmatch(provider_id):
                raise PriceGapSpecError(f"Invalid CoinGecko provider ID for {symbol}")
            if provider_id in provider_ids:
                raise PriceGapSpecError(f"Duplicate CoinGecko provider ID: {provider_id}")
            provider_ids.add(provider_id)
            coins.append((symbol, provider_id))
        coins.sort()
        if len(coins) * hours > MAX_CANDIDATES:
            raise PriceGapSpecError(
                f"Spec exceeds the {MAX_CANDIDATES}-candidate safety limit"
            )
        return cls(
            schema_version=schema_version,
            incident_id=incident_id,
            provider=provider,
            source_tag=source_tag,
            start_hour=start_hour,
            end_exclusive=end_exclusive,
            coins=tuple(coins),
        )

    @property
    def coin_mapping(self) -> dict[str, str]:
        return dict(self.coins)

    @property
    def expected_hour_epochs(self) -> tuple[int, ...]:
        return tuple(
            int((self.start_hour + timedelta(hours=offset)).timestamp())
            for offset in range(self.hours)
        )

    @property
    def expected_hour_set(self) -> frozenset[int]:
        return frozenset(self.expected_hour_epochs)

    @property
    def hours(self) -> int:
        return int((self.end_exclusive - self.start_hour).total_seconds() // 3600)

    @property
    def candidate_count(self) -> int:
        return len(self.coins) * self.hours

    @property
    def fetch_start(self) -> datetime:
        return self.start_hour - timedelta(hours=1)

    @property
    def fetch_end(self) -> datetime:
        return self.end_exclusive + timedelta(hours=1)

    def canonical_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "incident_id": self.incident_id,
            "provider": self.provider,
            "source_tag": self.source_tag,
            "start_hour": self.start_hour.isoformat(),
            "end_exclusive": self.end_exclusive.isoformat(),
            "coins": dict(self.coins),
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def ensure_collectable(self, *, now: datetime | None = None) -> None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        current_hour = current.replace(minute=0, second=0, microsecond=0)
        if self.end_exclusive > current_hour:
            raise PriceGapSpecError(
                "end_exclusive must not be later than the current full UTC hour"
            )


def parse_spec_json(raw: str | bytes) -> PriceGapSpec:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except PriceGapSpecError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PriceGapSpecError("Spec is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise PriceGapSpecError("Spec root must be a JSON object")
    return PriceGapSpec.from_mapping(payload)


def load_spec(path: Path) -> PriceGapSpec:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Spec not found: {path}")
    return parse_spec_json(path.read_bytes())
