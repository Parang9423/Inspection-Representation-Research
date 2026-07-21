from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

_DB_TIMEOUT_SECONDS = 60.0
_BUSY_TIMEOUT_MS = 60_000
_MAX_LOCK_RETRIES = 7
_WRITE_LOCK = threading.RLock()
_WRITE_PREFIXES = {
    "ALTER",
    "BEGIN",
    "CREATE",
    "DELETE",
    "DROP",
    "INSERT",
    "REINDEX",
    "REPLACE",
    "UPDATE",
    "VACUUM",
}


def _is_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and (
        "database is locked" in str(exc).lower()
        or "database table is locked" in str(exc).lower()
    )


def _is_write_sql(sql: str) -> bool:
    normalized = sql.lstrip()
    while normalized.startswith("--"):
        _, _, normalized = normalized.partition("\n")
        normalized = normalized.lstrip()
    if not normalized:
        return False
    token = normalized.split(None, 1)[0].upper()
    if token in _WRITE_PREFIXES:
        return True
    if token == "PRAGMA":
        lowered = normalized.lower()
        return "journal_mode" in lowered or "wal_checkpoint" in lowered
    return False


class ResilientConnection(sqlite3.Connection):
    """SQLite connection with process-wide writer serialization and lock retry."""

    _writer_lock_held: bool = False

    def _acquire_writer(self, sql: str) -> None:
        if _is_write_sql(sql) and not self._writer_lock_held:
            _WRITE_LOCK.acquire()
            self._writer_lock_held = True

    def _release_writer(self) -> None:
        if self._writer_lock_held:
            self._writer_lock_held = False
            _WRITE_LOCK.release()

    def _retry(self, operation):
        for attempt in range(_MAX_LOCK_RETRIES):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                if not _is_locked_error(exc) or attempt == _MAX_LOCK_RETRIES - 1:
                    raise
                time.sleep(min(0.1 * (2**attempt), 3.0))
        raise RuntimeError("unreachable")

    def execute(self, sql: str, parameters: Iterable[Any] = (), /):
        self._acquire_writer(sql)
        try:
            return self._retry(
                lambda: super(ResilientConnection, self).execute(sql, parameters)
            )
        except Exception:
            if not self.in_transaction:
                self._release_writer()
            raise

    def executemany(self, sql: str, seq_of_parameters, /):
        self._acquire_writer(sql)
        try:
            return self._retry(
                lambda: super(ResilientConnection, self).executemany(
                    sql, seq_of_parameters
                )
            )
        except Exception:
            if not self.in_transaction:
                self._release_writer()
            raise

    def executescript(self, sql_script: str, /):
        if any(_is_write_sql(statement) for statement in sql_script.split(";")):
            self._acquire_writer("BEGIN")
        try:
            return self._retry(
                lambda: super(ResilientConnection, self).executescript(sql_script)
            )
        except Exception:
            if not self.in_transaction:
                self._release_writer()
            raise

    def commit(self) -> None:
        try:
            self._retry(lambda: super(ResilientConnection, self).commit())
        finally:
            self._release_writer()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_writer()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_writer()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self._release_writer()


def connect_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=_DB_TIMEOUT_SECONDS,
        factory=ResilientConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
