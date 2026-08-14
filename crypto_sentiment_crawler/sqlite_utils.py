"""Shared SQLite connection settings for concurrent runtime services."""

import sqlite3
from contextlib import contextmanager
from os import PathLike
from typing import Any, Iterator

SQLITE_BUSY_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)


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
