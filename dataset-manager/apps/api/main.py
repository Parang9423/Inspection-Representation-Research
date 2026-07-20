from __future__ import annotations

import hashlib
import os
import random
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DATASET_ROOT = Path(os.getenv("DATASET_ROOT", APP_DIR.parents[2] / "data" / "split_image"))
CAM_ROOT = Path(os.getenv("CAM_ROOT", APP_DIR.parents[2] / "data" / "cam_image"))
DB_PATH = Path(os.getenv("DB_PATH", APP_DIR.parents[2] / "data" / "database" / "dataset_manager.db"))
EXPORT_ROOT = Path(os.getenv("EXPORT_ROOT", APP_DIR.parents[2] / "data" / "exports"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SplitCode = Literal["unassigned", "train", "valid", "test"]
StatusCode = Literal["included", "review", "excluded"]

app = FastAPI(title="AOI Dataset Manager API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BatchUpdate(BaseModel):
    image_ids: list[str] = Field(min_length=1)
    label: str | None = None
    split: SplitCode | None = None
    status: StatusCode | None = None
    note: str | None = None


class AutoSplitRequest(BaseModel):
    train_ratio: int = 80
    valid_ratio: int = 10
    test_ratio: int = 10
    seed: int = 42
    only_unassigned: bool = True


class ExportRequest(BaseModel):
    name: str = "aoi_dataset"
    mode: Literal["copy", "hardlink", "manifest"] = "copy"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            source_label TEXT NOT NULL,
            label TEXT NOT NULL,
            split TEXT NOT NULL DEFAULT 'unassigned',
            status TEXT NOT NULL DEFAULT 'included',
            note TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def image_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()


def scan() -> int:
    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    count = 0
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        for path in DATASET_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            count += 1
            stat = path.stat()
            item_id = image_id(path)
            label = path.parent.name or "미분류"
            conn.execute(
                """
                INSERT INTO images (
                    image_id, path, filename, source_label, label,
                    size_bytes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(image_id) DO UPDATE SET
                    path=excluded.path,
                    filename=excluded.filename,
                    source_label=excluded.source_label,
                    size_bytes=excluded.size_bytes,
                    updated_at=excluded.updated_at
                """,
                (item_id, str(path.resolve()), path.name, label, label, stat.st_size, now),
            )
        conn.commit()
    return count


def serialize(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["image_url"] = f"/api/images/{row['image_id']}/content"
    result["cam_url"] = f"/api/images/{row['image_id']}/cam"
    return result


@app.on_event("startup")
def startup() -> None:
    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    CAM_ROOT.mkdir(parents=True, exist_ok=True)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    scan()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/scan")
def rescan() -> dict:
    return {"count": scan()}


@app.get("/api/images")
def list_images(
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=200),
    label: str | None = None,
    split: SplitCode | None = None,
    status: StatusCode | None = None,
    search: str | None = None,
) -> dict:
    clauses, params = [], []
    for column, value in (("label", label), ("split", split), ("status", status)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if search:
        clauses.append("(filename LIKE ? OR path LIKE ? OR label LIKE ?)")
        token = f"%{search}%"
        params.extend([token, token, token])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    offset = (page - 1) * page_size
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM images {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM images {where} ORDER BY label, filename LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@app.get("/api/summary")
def summary() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT label, split, status, COUNT(*) AS count FROM images GROUP BY label, split, status"
        ).fetchall()
        totals = conn.execute(
            "SELECT COUNT(*) total, SUM(split != 'unassigned') assigned, SUM(status='included') included, SUM(status='review') review FROM images"
        ).fetchone()
    return {"totals": dict(totals), "groups": [dict(row) for row in rows]}


@app.patch("/api/images/batch")
def batch_update(payload: BatchUpdate) -> dict:
    updates, params = [], []
    for key in ("label", "split", "status", "note"):
        value = getattr(payload, key)
        if value is not None:
            updates.append(f"{key} = ?")
            params.append(value)
    if not updates:
        return {"updated": 0}
    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    placeholders = ",".join("?" for _ in payload.image_ids)
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE images SET {', '.join(updates)} WHERE image_id IN ({placeholders})",
            [*params, *payload.image_ids],
        )
        conn.commit()
    return {"updated": cur.rowcount}


@app.post("/api/splits/auto")
def auto_split(payload: AutoSplitRequest) -> dict:
    if payload.train_ratio + payload.valid_ratio + payload.test_ratio != 100:
        raise HTTPException(400, "분할 비율 합계는 100이어야 합니다.")
    with connect() as conn:
        query = "SELECT image_id, label FROM images WHERE status='included'"
        if payload.only_unassigned:
            query += " AND split='unassigned'"
        rows = conn.execute(query).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["label"], []).append(row["image_id"])
        rng = random.Random(payload.seed)
        assignments = []
        for ids in grouped.values():
            rng.shuffle(ids)
            n = len(ids)
            train_end = int(n * payload.train_ratio / 100)
            valid_end = train_end + int(n * payload.valid_ratio / 100)
            assignments.extend([("train", x) for x in ids[:train_end]])
            assignments.extend([("valid", x) for x in ids[train_end:valid_end]])
            assignments.extend([("test", x) for x in ids[valid_end:]])
        conn.executemany("UPDATE images SET split=? WHERE image_id=?", assignments)
        conn.commit()
    return {"updated": len(assignments)}


@app.get("/api/images/{item_id}/content")
def image_content(item_id: str):
    with connect() as conn:
        row = conn.execute("SELECT path FROM images WHERE image_id=?", (item_id,)).fetchone()
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return FileResponse(row["path"])


@app.get("/api/images/{item_id}/cam")
def cam_content(item_id: str):
    with connect() as conn:
        row = conn.execute("SELECT path FROM images WHERE image_id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    source = Path(row["path"])
    try:
        relative = source.relative_to(DATASET_ROOT)
    except ValueError:
        raise HTTPException(404, "CAM 이미지를 찾을 수 없습니다.")
    candidates = [CAM_ROOT / relative, CAM_ROOT / source.name]
    for candidate in candidates:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(404, "CAM 이미지를 찾을 수 없습니다.")


@app.post("/api/exports")
def export_dataset(payload: ExportRequest) -> dict:
    safe_name = "".join(c for c in payload.name if c.isalnum() or c in "-_") or "aoi_dataset"
    versions = [int(p.name.rsplit("_v", 1)[-1]) for p in EXPORT_ROOT.glob(f"{safe_name}_v*") if p.name.rsplit("_v", 1)[-1].isdigit()]
    output = EXPORT_ROOT / f"{safe_name}_v{max(versions, default=0)+1:03d}"
    output.mkdir(parents=True)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM images WHERE status='included' AND split IN ('train','valid','test')").fetchall()
    manifest = ["image_id,source_path,export_path,label,split"]
    for row in rows:
        src = Path(row["path"])
        target = output / row["split"] / row["label"] / src.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if payload.mode == "copy":
            shutil.copy2(src, target)
        elif payload.mode == "hardlink":
            try:
                os.link(src, target)
            except OSError:
                shutil.copy2(src, target)
        manifest.append(f"{row['image_id']},{src},{'' if payload.mode == 'manifest' else target},{row['label']},{row['split']}")
    (output / "manifest.csv").write_text("\n".join(manifest), encoding="utf-8-sig")
    return {"path": str(output.resolve()), "count": len(rows)}
