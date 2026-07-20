from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .main import BACKUP_ROOT, DATA_ROOT, DB_PATH

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])
LOCK_TTL_SECONDS = 600


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)


class UpdateRequest(BaseModel):
    image_id: str
    actor: str = Field(min_length=1, max_length=100)
    expected_version: int
    label: str | None = None
    split: str | None = None


class DeleteRequest(BaseModel):
    image_id: str
    actor: str = Field(min_length=1, max_length=100)
    expected_version: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_collaboration_schema() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if not table:
            return
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        additions = {
            "version": "INTEGER NOT NULL DEFAULT 1",
            "assigned_to": "TEXT",
            "review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
            "reviewed_by": "TEXT",
            "reviewed_at": "TEXT",
            "locked_by": "TEXT",
            "locked_at": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE images ADD COLUMN {name} {ddl}")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS label_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT NOT NULL,
                previous_label TEXT,
                new_label TEXT,
                changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                previous_version INTEGER NOT NULL,
                new_version INTEGER NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_locked_by ON images(locked_by)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_image ON label_history(image_id)")


def lock_expired(row: sqlite3.Row) -> bool:
    if not row["locked_by"] or not row["locked_at"]:
        return True
    try:
        locked_at = datetime.fromisoformat(row["locked_at"])
        return utc_now() - locked_at > timedelta(seconds=LOCK_TTL_SECONDS)
    except (TypeError, ValueError):
        return True


def serialize(row: sqlite3.Row) -> dict:
    item = dict(row)
    if item.get("locked_by") and lock_expired(row):
        item["locked_by"] = None
        item["locked_at"] = None
    item["image_url"] = f"/api/images/{row['image_id']}/file"
    item["cam_url"] = f"/api/images/{row['image_id']}/cam"
    return item


def editable_or_raise(row: sqlite3.Row, actor: str, expected_version: int) -> None:
    if row["locked_by"] and not lock_expired(row) and row["locked_by"] != actor:
        raise HTTPException(
            status_code=423,
            detail={
                "code": "locked",
                "message": f"{row['locked_by']}님이 검수 중입니다.",
                "item": serialize(row),
            },
        )
    if row["version"] != expected_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "version_conflict",
                "message": "다른 작업자가 이미 수정했습니다.",
                "item": serialize(row),
            },
        )


@router.get("/images/{image_id}")
def get_image(image_id: str) -> dict:
    ensure_collaboration_schema()
    with connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return serialize(row)


@router.get("/images/{image_id}/history")
def get_history(image_id: str) -> dict:
    ensure_collaboration_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM label_history WHERE image_id=? ORDER BY history_id DESC LIMIT 100",
            (image_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/images/{image_id}/lock")
def acquire_lock(image_id: str, request: ActorRequest) -> dict:
    ensure_collaboration_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        if row["locked_by"] and not lock_expired(row) and row["locked_by"] != request.actor:
            raise HTTPException(
                423,
                {
                    "code": "locked",
                    "message": f"{row['locked_by']}님이 검수 중입니다.",
                    "item": serialize(row),
                },
            )
        conn.execute(
            """UPDATE images
               SET locked_by=?, locked_at=?, assigned_to=?, review_status='reviewing'
               WHERE image_id=?""",
            (request.actor, now, request.actor, image_id),
        )
        updated = conn.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
    return serialize(updated)


@router.post("/images/{image_id}/unlock")
def release_lock(image_id: str, request: ActorRequest) -> dict:
    ensure_collaboration_schema()
    with connect() as conn:
        conn.execute(
            """UPDATE images
               SET locked_by=NULL, locked_at=NULL,
                   review_status=CASE WHEN review_status='reviewing' THEN 'unreviewed' ELSE review_status END
               WHERE image_id=? AND locked_by=?""",
            (image_id, request.actor),
        )
    return {"released": True}


@router.post("/images/{image_id}/heartbeat")
def heartbeat(image_id: str, request: ActorRequest) -> dict:
    ensure_collaboration_schema()
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE images SET locked_at=? WHERE image_id=? AND locked_by=?",
            (iso_now(), image_id, request.actor),
        )
    return {"renewed": cursor.rowcount == 1}


@router.patch("/images/update")
def update_image(request: UpdateRequest) -> dict:
    ensure_collaboration_schema()
    if request.label is None and request.split is None:
        raise HTTPException(400, "변경할 값이 없습니다.")
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM images WHERE image_id=?", (request.image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        editable_or_raise(row, request.actor, request.expected_version)
        previous_label = row["label"]
        new_version = row["version"] + 1
        fields = [
            "updated_at=?",
            "version=?",
            "reviewed_by=?",
            "reviewed_at=?",
            "review_status='reviewed'",
            "assigned_to=?",
            "locked_by=NULL",
            "locked_at=NULL",
        ]
        values: list[object] = [now, new_version, request.actor, now, request.actor]
        if request.label is not None:
            fields.insert(0, "label=?")
            values.insert(0, request.label)
        if request.split is not None:
            fields.insert(0, "split=?")
            values.insert(0, request.split)
        values.append(request.image_id)
        conn.execute(f"UPDATE images SET {', '.join(fields)} WHERE image_id=?", values)
        if request.label is not None and request.label != previous_label:
            conn.execute(
                """INSERT INTO label_history (
                    image_id,previous_label,new_label,changed_by,changed_at,
                    previous_version,new_version
                ) VALUES (?,?,?,?,?,?,?)""",
                (
                    request.image_id,
                    previous_label,
                    request.label,
                    request.actor,
                    now,
                    row["version"],
                    new_version,
                ),
            )
        updated = conn.execute("SELECT * FROM images WHERE image_id=?", (request.image_id,)).fetchone()
    return serialize(updated)


@router.post("/images/backup-delete")
def backup_delete(request: DeleteRequest) -> dict:
    ensure_collaboration_schema()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM images WHERE image_id=?", (request.image_id,)).fetchone()
        if not row:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        editable_or_raise(row, request.actor, request.expected_version)
        source = Path(row["path"])
        if source.exists():
            try:
                relative = source.relative_to(DATA_ROOT)
            except ValueError:
                relative = Path(row["source_label"]) / source.name
            target = BACKUP_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d%H%M%S}{target.suffix}")
            shutil.move(str(source), str(target))
        conn.execute("DELETE FROM images WHERE image_id=?", (request.image_id,))
    return {"moved": 1}
