from __future__ import annotations

import threading

from . import data_model

_SCHEMA_VERSION = "normalized_v2"
_lock = threading.Lock()
_initialized = False
_original_ensure = data_model.ensure_normalized_schema


def ensure_schema_ready() -> None:
    """Run the expensive legacy migration only once per database.

    Normal API requests only verify the migration marker, avoiding a full scan
    of the legacy images table on every request and every server restart.
    """
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return
        with data_model.connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS app_metadata(
                       key TEXT PRIMARY KEY,
                       value TEXT NOT NULL,
                       updated_at TEXT NOT NULL
                   )"""
            )
            marker = conn.execute(
                "SELECT value FROM app_metadata WHERE key='schema_version'"
            ).fetchone()

        if not marker or marker["value"] != _SCHEMA_VERSION:
            _original_ensure()
            with data_model.connect() as conn:
                conn.execute(
                    """INSERT INTO app_metadata(key,value,updated_at) VALUES('schema_version',?,?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                    (_SCHEMA_VERSION, data_model.iso_now()),
                )
        _initialized = True


def install_schema_guard() -> None:
    """Replace repeated schema checks with the cached guard."""
    data_model.ensure_normalized_schema = ensure_schema_ready
