from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .data_model import connect, ensure_normalized_schema, iso_now

router = APIRouter(prefix="/api/folder-work", tags=["folder-work"])
FOLDER_HEARTBEAT_TTL_SECONDS = 180


class FolderWorkRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    force: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(value: str | None) -> bool:
    if not value:
        return True
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return _utc_now() - timestamp > timedelta(seconds=FOLDER_HEARTBEAT_TTL_SECONDS)
    except (TypeError, ValueError):
        return True


def ensure_folder_work_schema() -> None:
    ensure_normalized_schema()
    with connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(folders)").fetchall()}
        required = {
            "work_status": "TEXT NOT NULL DEFAULT 'idle'",
            "working_by": "TEXT",
            "working_at": "TEXT",
            "heartbeat_at": "TEXT",
            "completed_at": "TEXT",
        }
        for name, definition in required.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE folders ADD COLUMN "{name}" {definition}')
        conn.execute(
            """CREATE TABLE IF NOT EXISTS work_activity_logs(
                   log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   folder_id INTEGER,
                   folder_name TEXT,
                   image_id TEXT,
                   actor TEXT,
                   action TEXT NOT NULL,
                   detail TEXT,
                   created_at TEXT NOT NULL
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_logs_folder ON work_activity_logs(folder_name,created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_logs_actor ON work_activity_logs(actor,created_at)"
        )
        conn.commit()


def _log(conn, *, folder_id: int | None, folder_name: str, actor: str | None, action: str, detail: str = "") -> None:
    conn.execute(
        """INSERT INTO work_activity_logs(folder_id,folder_name,actor,action,detail,created_at)
           VALUES(?,?,?,?,?,?)""",
        (folder_id, folder_name, actor, action, detail, iso_now()),
    )


def _expire_stale_sessions(conn) -> int:
    rows = conn.execute(
        """SELECT folder_id,folder_name,working_by,heartbeat_at,working_at
           FROM folders WHERE work_status='working' OR working_by IS NOT NULL"""
    ).fetchall()
    expired = 0
    now = iso_now()
    for row in rows:
        heartbeat = row["heartbeat_at"] or row["working_at"]
        if not _is_expired(heartbeat):
            continue
        conn.execute(
            """UPDATE folders SET work_status='idle',working_by=NULL,working_at=NULL,
                      heartbeat_at=NULL,updated_at=? WHERE folder_id=?""",
            (now, row["folder_id"]),
        )
        _log(
            conn,
            folder_id=row["folder_id"],
            folder_name=row["folder_name"],
            actor=row["working_by"],
            action="auto_release",
            detail="heartbeat expired",
        )
        expired += 1
    return expired


def _effective_status(row) -> str:
    if row["image_count"] > 0 and row["reviewed_count"] >= row["image_count"]:
        return "completed"
    if row["working_by"] or row["reviewing_count"] > 0:
        return "working"
    return row["work_status"] or "idle"


@router.get("/folders")
def list_folder_work() -> dict:
    ensure_folder_work_schema()
    with connect() as conn:
        _expire_stale_sessions(conn)
        rows = conn.execute(
            """SELECT folder_id,folder_name,image_count,reviewed_count,reviewing_count,
                      last_scanned_at,updated_at,work_status,working_by,working_at,
                      heartbeat_at,completed_at
               FROM folders
               WHERE image_count > 0
               ORDER BY folder_name COLLATE NOCASE"""
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["work_status"] = _effective_status(row)
        item["progress"] = round(
            row["reviewed_count"] * 100 / row["image_count"], 1
        ) if row["image_count"] else 0.0
        items.append(item)
    return {"items": items, "heartbeat_ttl_seconds": FOLDER_HEARTBEAT_TTL_SECONDS}


@router.post("/folders/{folder_name}/start")
def start_folder(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _expire_stale_sessions(conn)
        row = conn.execute(
            "SELECT folder_id,working_by FROM folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        if row["working_by"] and row["working_by"] != request.actor and not request.force:
            raise HTTPException(
                423,
                {"message": f"{row['working_by']}님이 작업 중입니다.", "working_by": row["working_by"]},
            )
        conn.execute(
            """UPDATE folders SET work_status='working',working_by=?,working_at=?,
                      heartbeat_at=?,completed_at=NULL,updated_at=? WHERE folder_name=?""",
            (request.actor, now, now, now, folder_name),
        )
        _log(conn, folder_id=row["folder_id"], folder_name=folder_name, actor=request.actor, action="start")
    return {"folder_name": folder_name, "work_status": "working", "working_by": request.actor}


@router.post("/folders/{folder_name}/heartbeat")
def folder_heartbeat(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        cursor = conn.execute(
            """UPDATE folders SET heartbeat_at=?,updated_at=?
               WHERE folder_name=? AND working_by=? AND work_status='working'""",
            (now, now, folder_name, request.actor),
        )
    return {"renewed": cursor.rowcount == 1, "heartbeat_at": now}


@router.post("/folders/{folder_name}/release")
def release_folder(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT folder_id,working_by FROM folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        if row["working_by"] and row["working_by"] != request.actor and not request.force:
            raise HTTPException(423, {"message": f"{row['working_by']}님의 작업 상태입니다. 강제 해제가 필요합니다."})
        previous_actor = row["working_by"]
        conn.execute(
            """UPDATE folders SET work_status='idle',working_by=NULL,working_at=NULL,
                      heartbeat_at=NULL,updated_at=? WHERE folder_name=?""",
            (now, folder_name),
        )
        _log(
            conn,
            folder_id=row["folder_id"],
            folder_name=folder_name,
            actor=request.actor,
            action="force_release" if request.force and previous_actor != request.actor else "release",
            detail=f"previous_actor={previous_actor or ''}",
        )
    return {"folder_name": folder_name, "released": True}


@router.post("/folders/{folder_name}/complete")
def complete_folder(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT folder_id,working_by FROM folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        if row["working_by"] and row["working_by"] != request.actor and not request.force:
            raise HTTPException(423, {"message": f"{row['working_by']}님의 작업 상태입니다."})
        conn.execute(
            """UPDATE folders SET work_status='completed',working_by=NULL,working_at=NULL,
                      heartbeat_at=NULL,completed_at=?,updated_at=? WHERE folder_name=?""",
            (now, now, folder_name),
        )
        _log(conn, folder_id=row["folder_id"], folder_name=folder_name, actor=request.actor, action="complete")
    return {"folder_name": folder_name, "work_status": "completed"}


@router.get("/logs")
def list_work_logs(
    folder_name: str | None = None,
    actor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    ensure_folder_work_schema()
    where: list[str] = []
    params: list[object] = []
    if folder_name:
        where.append("folder_name=?")
        params.append(folder_name)
    if actor:
        where.append("actor=?")
        params.append(actor)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM work_activity_logs {clause} ORDER BY log_id DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
    return {"items": [dict(row) for row in rows]}
