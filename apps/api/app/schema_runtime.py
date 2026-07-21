from __future__ import annotations

import threading

from . import data_model

_SCHEMA_VERSION = "normalized_v4"
_lock = threading.Lock()
_initialized = False
_original_ensure = data_model.ensure_normalized_schema


# Columns retained temporarily on the legacy images table so older endpoints and
# compatibility triggers continue to work while normalized tables are the source
# of truth.
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

# Intermediate project versions may already have created these tables with only
# some columns. CREATE TABLE IF NOT EXISTS does not repair such tables, so every
# required column is checked explicitly before indexes and triggers are created.
_NORMALIZED_TABLES: dict[str, tuple[str, dict[str, str]]] = {
    "folders": (
        """CREATE TABLE IF NOT EXISTS folders (
               folder_id INTEGER PRIMARY KEY AUTOINCREMENT,
               folder_name TEXT NOT NULL UNIQUE,
               absolute_path TEXT NOT NULL,
               image_count INTEGER NOT NULL DEFAULT 0,
               reviewed_count INTEGER NOT NULL DEFAULT 0,
               reviewing_count INTEGER NOT NULL DEFAULT 0,
               last_scanned_at TEXT,
               created_at TEXT NOT NULL DEFAULT '',
               updated_at TEXT NOT NULL DEFAULT ''
           )""",
        {
            "absolute_path": "TEXT NOT NULL DEFAULT ''",
            "image_count": "INTEGER NOT NULL DEFAULT 0",
            "reviewed_count": "INTEGER NOT NULL DEFAULT 0",
            "reviewing_count": "INTEGER NOT NULL DEFAULT 0",
            "last_scanned_at": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    ),
    "image_annotations": (
        """CREATE TABLE IF NOT EXISTS image_annotations (
               image_id TEXT PRIMARY KEY,
               current_label TEXT NOT NULL DEFAULT '',
               review_status TEXT NOT NULL DEFAULT 'unreviewed',
               assigned_to TEXT,
               reviewed_by TEXT,
               reviewed_at TEXT,
               version INTEGER NOT NULL DEFAULT 1,
               locked_by TEXT,
               locked_at TEXT,
               updated_at TEXT NOT NULL DEFAULT ''
           )""",
        {
            "current_label": "TEXT NOT NULL DEFAULT ''",
            "review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
            "assigned_to": "TEXT",
            "reviewed_by": "TEXT",
            "reviewed_at": "TEXT",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "locked_by": "TEXT",
            "locked_at": "TEXT",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    ),
    "split_assignments": (
        """CREATE TABLE IF NOT EXISTS split_assignments (
               image_id TEXT PRIMARY KEY,
               split_set TEXT NOT NULL DEFAULT 'unassigned',
               assigned_by TEXT,
               assigned_at TEXT,
               split_version INTEGER NOT NULL DEFAULT 1
           )""",
        {
            "split_set": "TEXT NOT NULL DEFAULT 'unassigned'",
            "assigned_by": "TEXT",
            "assigned_at": "TEXT",
            "split_version": "INTEGER NOT NULL DEFAULT 1",
        },
    ),
    "dataset_versions": (
        """CREATE TABLE IF NOT EXISTS dataset_versions (
               dataset_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
               dataset_name TEXT NOT NULL DEFAULT 'aoi_dataset',
               version_name TEXT NOT NULL UNIQUE,
               status TEXT NOT NULL DEFAULT 'completed',
               export_mode TEXT NOT NULL DEFAULT 'copy',
               output_path TEXT NOT NULL DEFAULT '',
               created_by TEXT,
               created_at TEXT NOT NULL DEFAULT ''
           )""",
        {
            "dataset_name": "TEXT NOT NULL DEFAULT 'aoi_dataset'",
            "status": "TEXT NOT NULL DEFAULT 'completed'",
            "export_mode": "TEXT NOT NULL DEFAULT 'copy'",
            "output_path": "TEXT NOT NULL DEFAULT ''",
            "created_by": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''",
        },
    ),
}


def _table_columns(conn, table_name: str) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def _ensure_legacy_image_columns() -> None:
    """Repair partially migrated legacy image columns without deleting data."""
    with data_model.connect() as conn:
        image_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if not image_table:
            return

        existing = _table_columns(conn, "images")
        for column_name, definition in _LEGACY_IMAGE_COLUMNS.items():
            if column_name not in existing:
                conn.execute(
                    f'ALTER TABLE images ADD COLUMN "{column_name}" {definition}'
                )

        conn.execute(
            "UPDATE images SET review_status=COALESCE(review_status,'unreviewed')"
        )
        conn.execute("UPDATE images SET version=COALESCE(version,1)")
        conn.execute("UPDATE images SET is_active=COALESCE(is_active,1)")
        conn.commit()


def _ensure_normalized_table_columns() -> None:
    """Create or repair normalized tables before indexes reference columns."""
    with data_model.connect() as conn:
        for table_name, (create_sql, required_columns) in _NORMALIZED_TABLES.items():
            conn.execute(create_sql)
            existing = _table_columns(conn, table_name)
            for column_name, definition in required_columns.items():
                if column_name not in existing:
                    conn.execute(
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN "{column_name}" {definition}'
                    )

        conn.execute(
            "UPDATE image_annotations SET "
            "review_status=COALESCE(review_status,'unreviewed'), "
            "version=COALESCE(version,1), "
            "updated_at=COALESCE(updated_at,'')"
        )
        conn.execute(
            "UPDATE split_assignments SET "
            "split_set=COALESCE(split_set,'unassigned'), "
            "split_version=COALESCE(split_version,1)"
        )
        conn.commit()


def ensure_schema_ready() -> None:
    """Apply migrations exactly once per API process.

    Schema repair performs write statements and must never run on every normal API
    request. Repeating it while the streaming scanner is committing batches causes
    SQLite writer contention and `database is locked` failures.
    """
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return

        _ensure_legacy_image_columns()
        _ensure_normalized_table_columns()

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
            conn.commit()

        if not marker or marker["value"] != _SCHEMA_VERSION:
            _original_ensure()
            _ensure_legacy_image_columns()
            _ensure_normalized_table_columns()
            with data_model.connect() as conn:
                conn.execute(
                    """INSERT INTO app_metadata(key,value,updated_at)
                       VALUES('schema_version',?,?)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value,
                         updated_at=excluded.updated_at""",
                    (_SCHEMA_VERSION, data_model.iso_now()),
                )
                conn.commit()

        _initialized = True


def install_schema_guard() -> None:
    """Replace repeated schema checks with the process-cached guard."""
    data_model.ensure_normalized_schema = ensure_schema_ready
