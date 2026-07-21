from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter

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


def _ensure_checkpoint_schema() -> None:
    with data_model.connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS scan_checkpoints(
                   folder_name TEXT PRIMARY KEY,
                   mode TEXT NOT NULL,
                   status TEXT NOT NULL,
                   last_path TEXT,
                   processed INTEGER NOT NULL DEFAULT 0,
                   added INTEGER NOT NULL DEFAULT 0,
                   updated_at TEXT NOT NULL
               )"""
        )
        conn.commit()


def _top_folders() -> list[os.DirEntry[str]]:
    if not DATA_ROOT.exists():
        return []
    with os.scandir(DATA_ROOT) as entries:
        return sorted(
            [entry for entry in entries if entry.is_dir(follow_symlinks=False)],
            key=lambda entry: entry.name.lower(),
        )


def _iter_folder_images(top: os.DirEntry[str], resume_after: str | None = None) -> Iterator[tuple[str, str, str, int, float]]:
    stack = [top.path]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda entry: entry.name.lower())
        except OSError:
            continue
        directories: list[str] = []
        for entry in ordered:
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if Path(entry.name).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                absolute_path = os.path.abspath(entry.path)
                if resume_after and absolute_path <= resume_after:
                    continue
                stat = entry.stat(follow_symlinks=False)
                yield top.name, absolute_path, entry.name, int(stat.st_size), float(stat.st_mtime)
            except OSError:
                continue
        stack.extend(reversed(directories))


def _checkpoint(folder_name: str, status: str, last_path: str | None, processed: int, added: int) -> None:
    with data_model.connect() as conn:
        conn.execute(
            """INSERT INTO scan_checkpoints(folder_name,mode,status,last_path,processed,added,updated_at)
               VALUES(?,'quick',?,?,?,?,?)
               ON CONFLICT(folder_name) DO UPDATE SET mode='quick',status=excluded.status,
               last_path=excluded.last_path,processed=excluded.processed,added=excluded.added,
               updated_at=excluded.updated_at""",
            (folder_name, status, last_path, processed, added, _now()),
        )
        conn.commit()


def _load_checkpoint(folder_name: str) -> dict[str, Any] | None:
    with data_model.connect() as conn:
        row = conn.execute(
            "SELECT status,last_path,processed,added FROM scan_checkpoints WHERE folder_name=? AND mode='quick'",
            (folder_name,),
        ).fetchone()
    return dict(row) if row else None


def _reset_checkpoints() -> None:
    with data_model.connect() as conn:
        conn.execute("DELETE FROM scan_checkpoints WHERE mode='quick'")
        conn.commit()


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


def _run_quick_scan(resume: bool = False) -> dict[str, Any]:
    _set_state(
        status="running", phase="quick-resume" if resume else "quick", current_folder=None,
        discovered=0, processed=0, total=0, added=0, updated=0,
        unchanged=0, deactivated=0, started_at=_now(), finished_at=None, error=None,
    )
    current_folder: str | None = None
    folder_processed = folder_added = 0
    last_path: str | None = None
    try:
        data_model.ensure_normalized_schema()
        _ensure_checkpoint_schema()
        if not resume:
            _reset_checkpoints()
        folder_ids: dict[str, int] = {}
        discovered = processed = added = 0
        now = _now()

        for top in _top_folders():
            current_folder = top.name
            checkpoint = _load_checkpoint(top.name) if resume else None
            if checkpoint and checkpoint["status"] == "completed":
                processed += int(checkpoint["processed"] or 0)
                added += int(checkpoint["added"] or 0)
                continue
            resume_after = str(checkpoint["last_path"]) if checkpoint and checkpoint.get("last_path") else None
            folder_processed = int(checkpoint["processed"] or 0) if checkpoint else 0
            folder_added = int(checkpoint["added"] or 0) if checkpoint else 0
            last_path = resume_after
            _set_state(current_folder=top.name)
            _checkpoint(top.name, "running", last_path, folder_processed, folder_added)
            batch: list[tuple[str, str, str, int, float]] = []

            for record in _iter_folder_images(top, resume_after=resume_after):
                batch.append(record)
                discovered += 1
                last_path = record[1]
                if discovered % 100 == 0:
                    _set_state(discovered=discovered)
                if len(batch) < _BATCH_SIZE:
                    continue
                new_count = _flush_new(batch, folder_ids, now)
                added += new_count
                processed += len(batch)
                folder_added += new_count
                folder_processed += len(batch)
                _checkpoint(top.name, "running", last_path, folder_processed, folder_added)
                batch.clear()
                _set_state(discovered=discovered, processed=processed, added=added, unchanged=processed - added)

            if batch:
                new_count = _flush_new(batch, folder_ids, now)
                added += new_count
                processed += len(batch)
                folder_added += new_count
                folder_processed += len(batch)
                batch.clear()
            _checkpoint(top.name, "completed", last_path, folder_processed, folder_added)

        _set_state(
            status="finished", phase="finished", current_folder=None,
            discovered=discovered, processed=processed, total=processed,
            added=added, unchanged=processed - added, finished_at=_now(), error=None,
        )
        return {"count": processed, "added": added, "skipped": processed - added, "mode": "quick", "resumed": resume}
    except Exception as exc:
        if current_folder:
            _checkpoint(current_folder, "failed", last_path, folder_processed, folder_added)
        _set_state(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", finished_at=_now())
        raise


@router.post("/api/scan/quick")
def quick_scan() -> dict[str, Any]:
    current = get_scan_status()
    if current["running"]:
        return {**current, "accepted": False}
    resume = current.get("status") == "failed"
    _set_state(status="queued", phase="resume-queued" if resume else "queued", current_folder=None, error=None)
    task = worker.submit("quick-scan", lambda: _run_quick_scan(resume=resume), dedupe_key="dataset-scan")
    _set_state(task_id=task["task_id"])
    return {**get_scan_status(), "accepted": True, "mode": "quick", "resume": resume}


@router.post("/api/scan/full")
def full_scan_alias() -> dict[str, Any]:
    from .scan_manager import start_background_scan
    return {**start_background_scan(), "mode": "full"}
