from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .resilient_db import connect_database


class DatabaseBackend(Protocol):
    name: str

    def connect(self): ...

    def health(self) -> dict: ...


@dataclass(frozen=True)
class SQLiteBackend:
    path: Path
    name: str = "sqlite"

    def connect(self):
        return connect_database(self.path)

    def health(self) -> dict:
        return {"backend": self.name, "path": str(self.path), "postgres_ready": True}


@dataclass(frozen=True)
class PostgreSQLBackendPlaceholder:
    url: str
    name: str = "postgresql"

    def connect(self):
        raise RuntimeError(
            "AOI_DATABASE_URL points to PostgreSQL, but the PostgreSQL driver/repository implementation "
            "is not enabled yet. Keep SQLite for the current PoC or complete the Phase 4 migration."
        )

    def health(self) -> dict:
        return {"backend": self.name, "configured": True, "enabled": False}


def create_backend(sqlite_path: Path) -> DatabaseBackend:
    database_url = os.getenv("AOI_DATABASE_URL", "").strip()
    if database_url.startswith(("postgres://", "postgresql://")):
        return PostgreSQLBackendPlaceholder(database_url)
    return SQLiteBackend(sqlite_path)
