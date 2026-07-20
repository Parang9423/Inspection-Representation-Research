from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException

from . import data_model
from .main import DATA_ROOT, IMAGE_EXTENSIONS

router = APIRouter(tags=["dataset-scan"])
_BATCH_SIZE = 500
_state_lock = threading.Lock()
_scan_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "status": "idle",
    "phase": "idle",
    "current_folder": None,
    "discovered": 0,
    "processed": 0,
    "total": 0,
    "added": 0,
    "updated": 0,
    "unchanged": 0,
    "deactivated": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set_state(**values: Any) -> None:
    with _state_lock:
        _state.update(values)


def get_scan_status() -> dict[str, Any]:
    with _state_lock:
        result = dict(_state)
    total = int(result.get("total") or 0)
    processed = int(result.get("processed") or 0)
    result["percent"] = round(processed * 100 / total, 1) if total else 0.0
    result["running"] = result.get("status") in {"discovering", "running"}
    return result


def _iter_images(root: Path) -> Iterator[tuple[str, str, str, int, float]]:
    """Yield top-level folder, absolute path, filename, size and mtime."""
    if not root.exists():
        return
    try:
        top_entries = sorted(
            (entry for entry in os.scandir(root) if entry.is_dir(follow_symlinks=False)),
            key=lambda entry: entry.name.lower(),
        )
    except OSError:
        return

    for top in top_entries:
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
                        yield (
                            top.name,
                            os.path.abspath(entry.path),
                            entry.name,
                            int(stat.st_size),
                            float(stat.st_mtime),
                        )
                    except OSError:
                        continue


def _image_id(absolute_path: str) -> str:
    return hashlib.sha1(absolute_path.encode("utf-8")).hexdigest()


def _chunks(items: list[Any], size: int = _BATCH_SIZE) -> Iterator[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _run_scan() -> None:
    _set_state(
        status="discovering",
        phase="discovering",
        current_folder=None,
        discovered=0,
        processed=0,
        total=0,
        added=0,
        updated=0,
        unchanged=0,
        deactivated=0,
        started_at=_now(),
        finished_at=None,
        error=None,
    )

    try:
        records: list[tuple[str, str, str, int, float]] = []
        for record in _iter_images(DATA_ROOT):
            records.append(record)
            if len(records) % 250 == 0:
                _set_state(discovered=len(records))
        _set_state(status="running", phase="indexing", discovered=len(records), total=len(records), processed=0)

        data_model.ensure_normalized_schema()
        now = _now()
        folder_names = sorted({record[0] for record in records}, key=str.lower)

        with data_model.connect() as conn:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS scan_seen(path TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM scan_seen")
            for folder_name in folder_names:
                absolute_path = str((DATA_ROOT / folder_name).resolve())
                conn.execute(
                    """INSERT INTO folders(folder_name,absolute_path,last_scanned_at,created_at,updated_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(folder_name) DO UPDATE SET absolute_path=excluded.absolute_path,
                       last_scanned_at=excluded.last_scanned_at,updated_at=excluded.updated_at""",
                    (folder_name, absolute_path, now, now, now),
                )
            folder_ids = {
                row["folder_name"]: row["folder_id"]
                for row in conn.execute("SELECT folder_id,folder_name FROM folders").fetchall()
            }
            existing = {
                row["path"]: (row["image_id"], int(row["size_bytes"]), float(row["modified_at"]), int(row["is_active"] or 0))
                for row in conn.execute("SELECT image_id,path,size_bytes,modified_at,is_active FROM images").fetchall()
            }

            added = updated = unchanged = processed = 0
            for batch in _chunks(records):
                insert_rows: list[tuple[Any, ...]] = []
                update_rows: list[tuple[Any, ...]] = []
                annotation_rows: list[tuple[Any, ...]] = []
                split_rows: list[tuple[Any, ...]] = []
                seen_rows: list[tuple[str]] = []

                for folder_name, absolute_path, filename, size_bytes, modified_at in batch:
                    seen_rows.append((absolute_path,))
                    folder_id = folder_ids[folder_name]
                    current = existing.get(absolute_path)
                    if current is None:
                        image_id = _image_id(absolute_path)
                        insert_rows.append((
                            image_id, absolute_path, filename, folder_name, folder_name,
                            size_bytes, modified_at, now, now, folder_id, folder_name,
                        ))
                        annotation_rows.append((image_id, folder_name, now))
                        split_rows.append((image_id, now))
                        added += 1
                    else:
                        _image, old_size, old_mtime, old_active = current
                        if old_size != size_bytes or old_mtime != modified_at or old_active != 1:
                            update_rows.append((
                                folder_id, filename, size_bytes, modified_at,
                                folder_name, now, absolute_path,
                            ))
                            updated += 1
                        else:
                            unchanged += 1

                if insert_rows:
                    conn.executemany(
                        """INSERT INTO images(
                               image_id,path,filename,source_label,label,split,status,note,
                               size_bytes,modified_at,created_at,updated_at,folder_id,original_label,is_active)
                           VALUES(?,?,?,?,?,'unassigned','included','',?,?,?,?,?,?,1)""",
                        insert_rows,
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO image_annotations(image_id,current_label,updated_at) VALUES(?,?,?)",
                        annotation_rows,
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO split_assignments(image_id,split_set,assigned_at) VALUES(?,'unassigned',?)",
                        split_rows,
                    )
                if update_rows:
                    conn.executemany(
                        """UPDATE images SET folder_id=?,filename=?,size_bytes=?,modified_at=?,
                           original_label=?,is_active=1,updated_at=? WHERE path=?""",
                        update_rows,
                    )
                conn.executemany("INSERT OR IGNORE INTO scan_seen(path) VALUES(?)", seen_rows)
                conn.commit()
                processed += len(batch)
                _set_state(processed=processed, added=added, updated=updated, unchanged=unchanged)

            cursor = conn.execute(
                """UPDATE images SET is_active=0,updated_at=?
                   WHERE is_active=1 AND NOT EXISTS(
                       SELECT 1 FROM scan_seen WHERE scan_seen.path=images.path
                   )""",
                (now,),
            )
            deactivated = max(cursor.rowcount, 0)
            data_model.refresh_folder_counts(conn)
            conn.commit()

        _set_state(
            status="finished",
            phase="finished",
            current_folder=None,
            processed=len(records),
            total=len(records),
            added=added,
            updated=updated,
            unchanged=unchanged,
            deactivated=deactivated,
            finished_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001
        _set_state(status="failed", phase="failed", error=f"{type(exc).__name__}: {exc}", finished_at=_now())


def start_background_scan() -> dict[str, Any]:
    global _scan_thread
    should_start = False
    with _state_lock:
        if _scan_thread is None or not _scan_thread.is_alive():
            _scan_thread = threading.Thread(target=_run_scan, name="aoi-dataset-scan", daemon=True)
            should_start = True
    if should_start:
        _scan_thread.start()
    return get_scan_status()


@router.post("/api/scan")
def start_scan_route() -> dict[str, Any]:
    status = start_background_scan()
    return {**status, "accepted": True, "count": int(status.get("total") or status.get("discovered") or 0)}


@router.post("/api/scan/start")
def start_scan_alias() -> dict[str, Any]:
    return start_scan_route()


@router.get("/api/scan/status")
def scan_status_route() -> dict[str, Any]:
    return get_scan_status()


@router.post("/api/scan/retry")
def retry_scan_route() -> dict[str, Any]:
    status = get_scan_status()
    if status["running"]:
        raise HTTPException(409, "이미 스캔이 실행 중입니다.")
    return start_scan_route()
