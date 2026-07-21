from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from . import data_model
from .main import DATA_ROOT, IMAGE_EXTENSIONS
from .scan_manager import _set_state, get_scan_status
from .task_worker import worker

router = APIRouter(tags=["incremental-scan"])
_BATCH_SIZE = 500


def _now() -> str:
    return data_model.iso_now()


def _image_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()


def _iter_images():
    if not DATA_ROOT.exists():
        return
    for top in sorted((entry for entry in os.scandir(DATA_ROOT) if entry.is_dir(follow_symlinks=False)), key=lambda entry: entry.name.lower()):
        _set_state(current_folder=top.name)
        stack = [top.path]
        while stack:
            directory = stack.pop()
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        if Path(entry.name).suffix.lower() not in IMAGE_EXTENSIONS:
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        yield top.name, os.path.abspath(entry.path), entry.name, int(stat.st_size), float(stat.st_mtime)
                    except OSError:
                        continue


def _flush_new(batch: list[tuple[str, str, str, int, float]], folder_ids: dict[str, int], now: str) -> int:
    if not batch:
        return 0
    with data_model.connect() as conn:
        paths = [row[1] for row in batch]
        placeholders = ",".join("?" for _ in paths)
        existing = {
            row["path"]
            for row in conn.execute(
                f"SELECT path FROM images WHERE path IN ({placeholders})", paths
            ).fetchall()
        }
        image_rows: list[tuple[Any, ...]] = []
        annotation_rows: list[tuple[str, str, str]] = []
        split_rows: list[tuple[str, str]] = []
        touched: set[int] = set()

        for folder_name, absolute_path, filename, size_bytes, modified_at in batch:
            if absolute_path in existing:
                continue
            folder_id = folder_ids.get(folder_name)
            if folder_id is None:
                conn.execute(
                    """INSERT INTO folders(folder_name,absolute_path,last_scanned_at,created_at,updated_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(folder_name) DO UPDATE SET
                       absolute_path=excluded.absolute_path,last_scanned_at=excluded.last_scanned_at,updated_at=excluded.updated_at""",
                    (folder_name, str((DATA_ROOT / folder_name).resolve()), now, now, now),
                )
                folder_id = int(conn.execute("SELECT folder_id FROM folders WHERE folder_name=?", (folder_name,)).fetchone()[0])
                folder_ids[folder_name] = folder_id
            touched.add(folder_id)
            image_id = _image_id(absolute_path)
            image_rows.append((
                image_id, absolute_path, filename, folder_name, folder_name,
                size_bytes, modified_at, now, now, folder_id, folder_name,
            ))
            annotation_rows.append((image_id, folder_name, now))
            split_rows.append((image_id, now))

        if image_rows:
            conn.executemany(
                """INSERT OR IGNORE INTO images(
                       image_id,path,filename,source_label,label,split,status,note,
                       size_bytes,modified_at,created_at,updated_at,folder_id,original_label,is_active)
                   VALUES(?,?,?,?,?,'unassigned','included','',?,?,?,?,?,?,1)""",
                image_rows,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO image_annotations(image_id,current_label,updated_at) VALUES(?,?,?)",
                annotation_rows,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO split_assignments(image_id,split_set,assigned_at) VALUES(?,'unassigned',?)",
                split_rows,
            )
            for folder_id in touched:
                conn.execute(
                    """UPDATE folders SET image_count=(SELECT COUNT(*) FROM images WHERE folder_id=? AND is_active=1),updated_at=? WHERE folder_id=?""",
                    (folder_id, now, folder_id),
                )
            conn.commit()
        return len(image_rows)


def _run_quick_scan() -> dict[str, Any]:
    _set_state(
        status="running", phase="quick", current_folder=None,
        discovered=0, processed=0, total=0, added=0, updated=0,
        unchanged=0, deactivated=0, started_at=_now(), finished_at=None, error=None,
    )
    try:
        data_model.ensure_normalized_schema()
        folder_ids: dict[str, int] = {}
        batch: list[tuple[str, str, str, int, float]] = []
        discovered = processed = added = 0
        now = _now()
        for record in _iter_images():
            batch.append(record)
            discovered += 1
            if discovered % 100 == 0:
                _set_state(discovered=discovered)
            if len(batch) < _BATCH_SIZE:
                continue
            added += _flush_new(batch, folder_ids, now)
            processed += len(batch)
            batch.clear()
            _set_state(discovered=discovered, processed=processed, added=added, unchanged=processed - added)
        if batch:
            added += _flush_new(batch, folder_ids, now)
            processed += len(batch)
            batch.clear()
        _set_state(
            status="finished", phase="finished", current_folder=None,
            discovered=discovered, processed=processed, total=processed,
            added=added, unchanged=processed - added, finished_at=_now(), error=None,
        )
        return {"count": processed, "added": added, "skipped": processed - added, "mode": "quick"}
    except Exception as exc:
        _set_state(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", finished_at=_now())
        raise


@router.post("/api/scan/quick")
def quick_scan() -> dict[str, Any]:
    current = get_scan_status()
    if current["running"]:
        return {**current, "accepted": False}
    _set_state(status="queued", phase="queued", current_folder=None, error=None)
    task = worker.submit("quick-scan", _run_quick_scan, dedupe_key="dataset-scan")
    _set_state(task_id=task["task_id"])
    return {**get_scan_status(), "accepted": True, "mode": "quick"}


@router.post("/api/scan/full")
def full_scan_alias() -> dict[str, Any]:
    from .scan_manager import start_background_scan
    return {**start_background_scan(), "mode": "full"}
