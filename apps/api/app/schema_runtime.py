from __future__ import annotations

import threading

from . import data_model

_SCHEMA_VERSION = "normalized_v3"
_lock = threading.Lock()
_initialized = False
_original_ensure = data_model.ensure_normalized_schema


# Columns retained temporarily on the legacy images table so older endpoints and
# compatibility triggers continue to work while normalized tables are the source
# of truth. ALTER TABLE is only executed for columns that are actually missing.
_LEGACY_IMAGE_COLUMNS: dict[str, str] = {
    "folder_id": "INTEGER",
    "original_label": "TEXT",
    "is_active": "INTEGER NOT NULL DEFAULT 1",
    "review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
    "assigned_to": "TEXT",
    "reviewed_by": "TEXT",
    "reviewed_at": "TEXT",
    "version": "INTEGER NOT NULL DEFAULT 1",
    "locked_by": "TEXT",
    "locked_at": "TEXT",
}


def _ensure_legacy_image_columns() -> None:
    """Repair partially migrated databases without deleting existing data."""
    with data_model.connect() as conn:
        image_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if not image_table:
            return

        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()
        }
        for column_name, definition in _LEGACY_IMAGE_COLUMNS.items():
            if column_name not in existing:
                conn.execute(
                    f'ALTER TABLE images ADD COLUMN "{column_name}" {definition}'
                )

        # Normalize null values left by older schemas before NOT NULL-compatible
        # triggers begin mirroring normalized state back to the legacy table.
        conn.execute(
            "UPDATE images SET review_status=COALESCE(review_status,'unreviewed')"
        )
        conn.execute("UPDATE images SET version=COALESCE(version,1)")
        conn.execute("UPDATE images SET is_active=COALESCE(is_active,1)")
        conn.commit()


def ensure_schema_ready() -> None:
    """Apply versioned migrations once, with a lightweight repair on startup.

    The migration marker prevents the expensive legacy-row migration from being
    repeated on every API request. The column repair is idempotent and protects
    databases that were created by an intermediate project version.
    """
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return

        # Repair columns before creating triggers that reference them.
        _ensure_legacy_image_columns()

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
            # The original migration may create or alter the legacy table, so run
            # the repair again before compatibility triggers are installed.
            _ensure_legacy_image_columns()
            with data_model.connect() as conn:
                conn.execute(
                    """INSERT INTO app_metadata(key,value,updated_at)
                       VALUES('schema_version',?,?)
                       ON CONFLICT(key) DO UPDATE SET
                           value=excluded.value,updated_at=excluded.updated_at""",
                    (_SCHEMA_VERSION, data_model.iso_now()),
                )
                conn.commit()

        _initialized = True


def install_schema_guard() -> None:
    """Replace repeated schema checks with the cached guard."""
    data_model.ensure_normalized_schema = ensure_schema_ready
