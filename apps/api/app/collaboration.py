from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .main import BACKUP_ROOT, DATA_ROOT
from .data_model import catalog_select, connect, ensure_normalized_schema, iso_now, refresh_folder_counts

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


def ensure_collaboration_schema() -> None:
    ensure_normalized_schema()


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
    item["thumbnail_url"] = f"/api/images/{row['image_id']}/thumbnail"
    item["cam_url"] = f"/api/images/{row['image_id']}/cam"
    return item


def fetch_image(conn: sqlite3.Connection, image_id: str) -> sqlite3.Row | None:
    return conn.execute(
        catalog_select() + " WHERE i.image_id=? AND i.is_active=1", (image_id,)
    ).fetchone()


def editable_or_raise(row: sqlite3.Row, actor: str, expected_version: int) -> None:
    if row["locked_by"] and not lock_expired(row) and row["locked_by"] != actor:
        raise HTTPException(423, {"code": "locked", "message": f"{row['locked_by']}님이 검수 중입니다.", "item": serialize(row)})
    if row["version"] != expected_version:
        raise HTTPException(409, {"code": "version_conflict", "message": "다른 작업자가 이미 수정했습니다.", "item": serialize(row)})


@router.get("/images/{image_id}")
def get_image(image_id: str) -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        row = fetch_image(conn, image_id)
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return serialize(row)


@router.get("/images/{image_id}/history")
def get_history(image_id: str) -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM annotation_history WHERE image_id=? ORDER BY history_id DESC LIMIT 100",
            (image_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/images/{image_id}/lock")
def acquire_lock(image_id: str, request: ActorRequest) -> dict:
    ensure_normalized_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = fetch_image(conn, image_id)
        if not row:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        if row["locked_by"] and not lock_expired(row) and row["locked_by"] != request.actor:
            raise HTTPException(423, {"code": "locked", "message": f"{row['locked_by']}님이 검수 중입니다.", "item": serialize(row)})
        conn.execute(
            """INSERT INTO image_annotations(image_id,current_label,review_status,assigned_to,version,locked_by,locked_at,updated_at)
               VALUES(?,?,'reviewing',?,1,?,?,?)
               ON CONFLICT(image_id) DO UPDATE SET assigned_to=excluded.assigned_to,
               review_status='reviewing',locked_by=excluded.locked_by,locked_at=excluded.locked_at,updated_at=excluded.updated_at""",
            (image_id, row["label"], request.actor, request.actor, now, now),
        )
        conn.execute(
            "UPDATE images SET assigned_to=?,review_status='reviewing',locked_by=?,locked_at=? WHERE image_id=?",
            (request.actor, request.actor, now, image_id),
        )
        refresh_folder_counts(conn)
        updated = fetch_image(conn, image_id)
    return serialize(updated)


@router.post("/images/{image_id}/unlock")
def release_lock(image_id: str, request: ActorRequest) -> dict:
    ensure_normalized_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute(
            """UPDATE image_annotations SET locked_by=NULL,locked_at=NULL,
               review_status=CASE WHEN review_status='reviewing' THEN 'unreviewed' ELSE review_status END,
               updated_at=? WHERE image_id=? AND locked_by=?""",
            (now, image_id, request.actor),
        )
        conn.execute(
            """UPDATE images SET locked_by=NULL,locked_at=NULL,
               review_status=CASE WHEN review_status='reviewing' THEN 'unreviewed' ELSE review_status END
               WHERE image_id=? AND locked_by=?""",
            (image_id, request.actor),
        )
        refresh_folder_counts(conn)
    return {"released": True}


@router.post("/images/{image_id}/heartbeat")
def heartbeat(image_id: str, request: ActorRequest) -> dict:
    ensure_normalized_schema()
    now = iso_now()
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE image_annotations SET locked_at=?,updated_at=? WHERE image_id=? AND locked_by=?",
            (now, now, image_id, request.actor),
        )
        conn.execute(
            "UPDATE images SET locked_at=? WHERE image_id=? AND locked_by=?",
            (now, image_id, request.actor),
        )
    return {"renewed": cursor.rowcount == 1}


@router.patch("/images/update")
def update_image(request: UpdateRequest) -> dict:
    ensure_normalized_schema()
    if request.label is None and request.split is None:
        raise HTTPException(400, "변경할 값이 없습니다.")
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = fetch_image(conn, request.image_id)
        if not row:
            raise HTTPException(404, "이미지를 찾을 수 없습니다.")
        editable_or_raise(row, request.actor, request.expected_version)
        new_version = row["version"] + 1

        if request.label is not None:
            conn.execute(
                """INSERT INTO image_annotations(image_id,current_label,review_status,assigned_to,reviewed_by,
                   reviewed_at,version,locked_by,locked_at,updated_at)
                   VALUES(?,?,'reviewed',?,?,?,?,NULL,NULL,?)
                   ON CONFLICT(image_id) DO UPDATE SET current_label=excluded.current_label,
                   review_status='reviewed',assigned_to=excluded.assigned_to,reviewed_by=excluded.reviewed_by,
                   reviewed_at=excluded.reviewed_at,version=excluded.version,locked_by=NULL,locked_at=NULL,
                   updated_at=excluded.updated_at""",
                (request.image_id, request.label, request.actor, request.actor, now, new_version, now),
            )
            conn.execute(
                """UPDATE images SET label=?,review_status='reviewed',assigned_to=?,reviewed_by=?,
                   reviewed_at=?,version=?,locked_by=NULL,locked_at=NULL,updated_at=? WHERE image_id=?""",
                (request.label, request.actor, request.actor, now, new_version, now, request.image_id),
            )
            if request.label != row["label"]:
                conn.execute(
                    """INSERT INTO annotation_history(image_id,previous_label,new_label,changed_by,
                       changed_at,previous_version,new_version) VALUES(?,?,?,?,?,?,?)""",
                    (request.image_id, row["label"], request.label, request.actor, now, row["version"], new_version),
                )
        else:
            conn.execute(
                """UPDATE image_annotations SET review_status='reviewed',assigned_to=?,reviewed_by=?,
                   reviewed_at=?,version=?,locked_by=NULL,locked_at=NULL,updated_at=? WHERE image_id=?""",
                (request.actor, request.actor, now, new_version, now, request.image_id),
            )
            conn.execute(
                """UPDATE images SET review_status='reviewed',assigned_to=?,reviewed_by=?,reviewed_at=?,
                   version=?,locked_by=NULL,locked_at=NULL,updated_at=? WHERE image_id=?""",
                (request.actor, request.actor, now, new_version, now, request.image_id),
            )

        if request.split is not None:
            previous_split = row["split"]
            conn.execute(
                """INSERT INTO split_assignments(image_id,split_set,assigned_by,assigned_at)
                   VALUES(?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET split_set=excluded.split_set,
                   assigned_by=excluded.assigned_by,assigned_at=excluded.assigned_at,split_version=split_version+1""",
                (request.image_id, request.split, request.actor, now),
            )
            conn.execute("UPDATE images SET split=?,updated_at=? WHERE image_id=?", (request.split, now, request.image_id))
            if request.split != previous_split:
                conn.execute(
                    "INSERT INTO split_history(image_id,previous_split,new_split,changed_by,changed_at) VALUES(?,?,?,?,?)",
                    (request.image_id, previous_split, request.split, request.actor, now),
                )
        refresh_folder_counts(conn)
        updated = fetch_image(conn, request.image_id)
    return serialize(updated)


@router.post("/images/backup-delete")
def backup_delete(request: DeleteRequest) -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = fetch_image(conn, request.image_id)
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
        conn.execute("UPDATE images SET is_active=0,updated_at=? WHERE image_id=?", (iso_now(), request.image_id))
        refresh_folder_counts(conn)
    return {"moved": 1}
