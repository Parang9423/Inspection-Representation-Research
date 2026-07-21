from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .data_model import connect, ensure_normalized_schema, iso_now

router = APIRouter(prefix="/api/folder-work", tags=["folder-work"])


class FolderWorkRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    force: bool = False


def ensure_folder_work_schema() -> None:
    ensure_normalized_schema()
    with connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(folders)").fetchall()}
        required = {
            "work_status": "TEXT NOT NULL DEFAULT 'idle'",
            "working_by": "TEXT",
            "working_at": "TEXT",
            "completed_at": "TEXT",
        }
        for name, definition in required.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE folders ADD COLUMN "{name}" {definition}')
        conn.commit()


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
        rows = conn.execute(
            """SELECT folder_id,folder_name,image_count,reviewed_count,reviewing_count,
                      last_scanned_at,updated_at,work_status,working_by,working_at,completed_at
               FROM folders
               WHERE image_count > 0
               ORDER BY folder_name COLLATE NOCASE"""
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["work_status"] = _effective_status(row)
        item["progress"] = round((row["reviewed_count"] * 100 / row["image_count"]), 1) if row["image_count"] else 0.0
        items.append(item)
    return {"items": items}


@router.post("/folders/{folder_name}/start")
def start_folder(folder_name: str, request: FolderWorkRequest) -> dict:
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
            raise HTTPException(423, {"message": f"{row['working_by']}님이 작업 중입니다.", "working_by": row["working_by"]})
        conn.execute(
            """UPDATE folders SET work_status='working',working_by=?,working_at=?,completed_at=NULL,updated_at=?
               WHERE folder_name=?""",
            (request.actor, now, now, folder_name),
        )
    return {"folder_name": folder_name, "work_status": "working", "working_by": request.actor}


@router.post("/folders/{folder_name}/release")
def release_folder(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT working_by FROM folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        if row["working_by"] and row["working_by"] != request.actor and not request.force:
            raise HTTPException(423, {"message": f"{row['working_by']}님의 작업 상태입니다. 강제 해제가 필요합니다."})
        conn.execute(
            """UPDATE folders SET work_status='idle',working_by=NULL,working_at=NULL,updated_at=?
               WHERE folder_name=?""",
            (now, folder_name),
        )
    return {"folder_name": folder_name, "released": True}


@router.post("/folders/{folder_name}/complete")
def complete_folder(folder_name: str, request: FolderWorkRequest) -> dict:
    ensure_folder_work_schema()
    now = iso_now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT working_by FROM folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "폴더를 찾을 수 없습니다.")
        if row["working_by"] and row["working_by"] != request.actor and not request.force:
            raise HTTPException(423, {"message": f"{row['working_by']}님의 작업 상태입니다."})
        conn.execute(
            """UPDATE folders SET work_status='completed',working_by=NULL,working_at=NULL,
                      completed_at=?,updated_at=? WHERE folder_name=?""",
            (now, now, folder_name),
        )
    return {"folder_name": folder_name, "work_status": "completed"}
