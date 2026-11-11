"""Shared SQLite connection settings for concurrent runtime services."""

import sqlite3
from contextlib import contextmanager
from os import PathLike
from typing import Any, Iterator

SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)

# Timestamps are stored as ISO-8601 (``2026-11-11T13:57:48+00:00``) via
# ``datetime.isoformat()``. SQLite's ``datetime('now', ...)`` returns a
# space-separated string (``2026-11-11 13:57:48``) which sorts *before* every
# ISO-T value on the same date, because ``'T'`` (0x54) > ``' '`` (0x20).
# Comparing the two formats silently widens every window filter by up to a day.
ISO_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def iso_cutoff_sql(modifier: str) -> str:
    """SQL expression for a UTC ISO-8601 cutoff comparable to stored timestamps.

    ``modifier`` is the SQLite date modifier, either a literal (``"'-24 hours'"``)
    or a bound-parameter expression (``"'-' || ? || ' days'"``).
    """

    return f"strftime('{ISO_TS_FORMAT}', 'now', {modifier})"


def connect_sqlite(
    database: str | bytes | PathLike[str] | PathLike[bytes],
    **kwargs: Any,
) -> sqlite3.Connection:
    """Open SQLite with a consistent bounded wait for concurrent writers."""

    timeout_seconds = float(kwargs.setdefault("timeout", SQLITE_BUSY_TIMEOUT_SECONDS))
    connection = sqlite3.connect(database, **kwargs)
    connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
    return connection


@contextmanager
def sqlite_transaction(
    database: str | bytes | PathLike[str] | PathLike[bytes],
    **kwargs: Any,
) -> Iterator[sqlite3.Connection]:
    """Open a short write transaction that always rolls back and closes safely."""

    connection = connect_sqlite(database, **kwargs)
    try:
        yield connection
        connection.commit()
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()
