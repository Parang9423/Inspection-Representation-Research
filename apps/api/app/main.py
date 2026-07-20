from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("AOI_DATA_ROOT", APP_DIR / "data" / "split_image"))
CAM_ROOT = Path(os.getenv("AOI_CAM_ROOT", APP_DIR / "data" / "cam_image"))
BACKUP_ROOT = Path(os.getenv("AOI_BACKUP_ROOT", APP_DIR / "data" / "backup_image"))
EXPORT_ROOT = Path(os.getenv("AOI_EXPORT_ROOT", APP_DIR / "data" / "exports"))
DB_PATH = Path(os.getenv("AOI_DB_PATH", APP_DIR / "data" / "dataset_manager.db"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SplitCode = Literal["unassigned", "train", "valid", "test"]
StatusCode = Literal["included", "review", "excluded"]
RULE_COLUMNS = ["rule_shape", "rule_brightness", "rule_position", "rule_topology", "rule_size", "rule_texture", "rule_boundary", "rule_context"]


class BulkUpdateRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1)
    label: str | None = None
    split: SplitCode | None = None
    status: StatusCode | None = None
    note: str | None = None
    rules: dict[str, str] = Field(default_factory=dict)


class DeleteRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1)


class AutoSplitRequest(BaseModel):
    train_ratio: int = Field(80, ge=0, le=100)
    valid_ratio: int = Field(10, ge=0, le=100)
    test_ratio: int = Field(10, ge=0, le=100)
    seed: int = 42
    only_unassigned: bool = True


class ExportRequest(BaseModel):
    dataset_name: str = "aoi_dataset"
    mode: Literal["copy", "hardlink", "manifest"] = "copy"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    for path in (DATA_ROOT, CAM_ROOT, BACKUP_ROOT, EXPORT_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
            source_label TEXT NOT NULL, label TEXT NOT NULL, split TEXT NOT NULL DEFAULT 'unassigned',
            status TEXT NOT NULL DEFAULT 'included', note TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0, height INTEGER NOT NULL DEFAULT 0,
            size_bytes INTEGER NOT NULL DEFAULT 0, modified_at REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            rule_shape TEXT NOT NULL DEFAULT '미지정', rule_brightness TEXT NOT NULL DEFAULT '미지정',
            rule_position TEXT NOT NULL DEFAULT '미지정', rule_topology TEXT NOT NULL DEFAULT '미지정',
            rule_size TEXT NOT NULL DEFAULT '미지정', rule_texture TEXT NOT NULL DEFAULT '미지정',
            rule_boundary TEXT NOT NULL DEFAULT '미지정', rule_context TEXT NOT NULL DEFAULT '미지정')""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_label ON images(label)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_split ON images(split)")


def image_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()


def scan_images() -> int:
    now = datetime.now().isoformat(timespec="seconds")
    count = 0
    with connect() as conn:
        for path in DATA_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            count += 1
            stat = path.stat()
            source_label = path.parent.name.strip() or "미분류"
            resolved = str(path.resolve())
            row = conn.execute("SELECT image_id FROM images WHERE path=?", (resolved,)).fetchone()
            if row:
                conn.execute("UPDATE images SET filename=?,source_label=?,size_bytes=?,modified_at=?,updated_at=? WHERE path=?", (path.name, source_label, stat.st_size, stat.st_mtime, now, resolved))
            else:
                conn.execute("INSERT INTO images (image_id,path,filename,source_label,label,size_bytes,modified_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (image_id(path), resolved, path.name, source_label, source_label, stat.st_size, stat.st_mtime, now, now))
    return count


def serialize(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["image_url"] = f"/api/images/{row['image_id']}/file"
    item["cam_url"] = f"/api/images/{row['image_id']}/cam"
    return item


def label_hotkeys() -> list[dict]:
    mappings: list[dict] = []
    for folder in sorted((p for p in DATA_ROOT.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        match = re.match(r"^\s*(\d+)\s*[_\-. ]*", folder.name)
        if not match:
            continue
        mappings.append({"key": match.group(1), "label": folder.name})
    return mappings


app = FastAPI(title="AOI Dataset Manager API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    init_db()
    scan_images()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "data_root": str(DATA_ROOT), "backup_root": str(BACKUP_ROOT)}


@app.post("/api/scan")
def scan() -> dict:
    return {"count": scan_images()}


@app.get("/api/labels/hotkeys")
def hotkeys() -> dict:
    return {"items": label_hotkeys()}


@app.get("/api/images")
def list_images(page: int = Query(1, ge=1), page_size: int = Query(48, ge=1, le=200), label: str | None = None, split: SplitCode | None = None, status: StatusCode | None = None, search: str | None = None) -> dict:
    where: list[str] = []
    params: list[object] = []
    if label:
        where.append("label=?"); params.append(label)
    if split:
        where.append("split=?"); params.append(split)
    if status:
        where.append("status=?"); params.append(status)
    if search:
        where.append("(filename LIKE ? OR label LIKE ? OR source_label LIKE ?)")
        term = f"%{search}%"; params.extend([term, term, term])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    offset = (page - 1) * page_size
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM images {clause}", params).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM images {clause} ORDER BY label,filename LIMIT ? OFFSET ?", [*params, page_size, offset]).fetchall()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@app.get("/api/summary")
def summary() -> dict:
    with connect() as conn:
        totals = conn.execute("SELECT COUNT(*) total,SUM(status='included') included,SUM(status='review') review,SUM(status='excluded') excluded,SUM(split!='unassigned') assigned,SUM(status='included' AND split='unassigned') unassigned FROM images").fetchone()
        classes = conn.execute("SELECT label,SUM(split='train' AND status='included') train,SUM(split='valid' AND status='included') valid,SUM(split='test' AND status='included') test,SUM(split='unassigned' AND status='included') unassigned,COUNT(*) total FROM images GROUP BY label ORDER BY total DESC").fetchall()
    return {"totals": dict(totals), "classes": [dict(row) for row in classes]}


@app.patch("/api/images/bulk")
def bulk_update(request: BulkUpdateRequest) -> dict:
    fields: list[str] = []
    values: list[object] = []
    for key in ["label", "split", "status", "note"]:
        value = getattr(request, key)
        if value is not None:
            fields.append(f"{key}=?"); values.append(value)
    for key, value in request.rules.items():
        if key not in RULE_COLUMNS:
            raise HTTPException(400, f"지원하지 않는 Rule: {key}")
        fields.append(f"{key}=?"); values.append(value)
    if not fields:
        return {"updated": 0}
    fields.append("updated_at=?"); values.append(datetime.now().isoformat(timespec="seconds"))
    placeholders = ",".join("?" for _ in request.image_ids)
    with connect() as conn:
        cursor = conn.execute(f"UPDATE images SET {', '.join(fields)} WHERE image_id IN ({placeholders})", [*values, *request.image_ids])
    return {"updated": cursor.rowcount}


@app.post("/api/images/backup-delete")
def backup_delete(request: DeleteRequest) -> dict:
    moved = 0
    errors: list[str] = []
    with connect() as conn:
        placeholders = ",".join("?" for _ in request.image_ids)
        rows = conn.execute(f"SELECT image_id,path FROM images WHERE image_id IN ({placeholders})", request.image_ids).fetchall()
        for row in rows:
            source = Path(row["path"])
            if not source.exists():
                conn.execute("DELETE FROM images WHERE image_id=?", (row["image_id"],))
                continue
            try:
                relative = source.relative_to(DATA_ROOT)
                target = BACKUP_ROOT / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target = target.with_name(f"{target.stem}_{datetime.now():%Y%m%d%H%M%S}{target.suffix}")
                shutil.move(str(source), str(target))
                conn.execute("DELETE FROM images WHERE image_id=?", (row["image_id"],))
                moved += 1
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
    if errors:
        raise HTTPException(500, {"moved": moved, "errors": errors})
    return {"moved": moved}


@app.post("/api/splits/auto")
def auto_split(request: AutoSplitRequest) -> dict:
    if request.train_ratio + request.valid_ratio + request.test_ratio != 100:
        raise HTTPException(400, "분할 비율의 합은 100이어야 합니다.")
    with connect() as conn:
        query = "SELECT image_id,label FROM images WHERE status='included'" + (" AND split='unassigned'" if request.only_unassigned else "")
        rows = conn.execute(query).fetchall(); groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(row["label"], []).append(row["image_id"])
        rng = random.Random(request.seed); assignments: list[tuple[str, str, str]] = []; now = datetime.now().isoformat(timespec="seconds")
        for ids in groups.values():
            rng.shuffle(ids); train_end = int(len(ids) * request.train_ratio / 100); valid_end = train_end + int(len(ids) * request.valid_ratio / 100)
            assignments.extend(("train", now, value) for value in ids[:train_end])
            assignments.extend(("valid", now, value) for value in ids[train_end:valid_end])
            assignments.extend(("test", now, value) for value in ids[valid_end:])
        conn.executemany("UPDATE images SET split=?,updated_at=? WHERE image_id=?", assignments)
    return {"updated": len(assignments)}


def next_version(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "aoi_dataset"
    versions = [int(p.name.rsplit("_v", 1)[-1]) for p in EXPORT_ROOT.glob(f"{safe}_v*") if p.name.rsplit("_v", 1)[-1].isdigit()]
    return f"{safe}_v{max(versions, default=0) + 1:03d}"


@app.post("/api/exports")
def export(request: ExportRequest) -> dict:
    version = next_version(request.dataset_name); output = EXPORT_ROOT / version; output.mkdir(parents=True, exist_ok=False)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM images WHERE status='included' AND split IN ('train','valid','test')").fetchall()
    manifest: list[dict] = []; labels = sorted({row["label"] for row in rows})
    for row in rows:
        src = Path(row["path"])
        if not src.exists():
            continue
        dst = output / row["split"] / row["label"] / src.name
        if request.mode != "manifest":
            dst.parent.mkdir(parents=True, exist_ok=True)
            if request.mode == "hardlink":
                try: os.link(src, dst)
                except OSError: shutil.copy2(src, dst)
            else:
                shutil.copy2(src, dst)
        item = dict(row); item["export_path"] = "" if request.mode == "manifest" else str(dst.resolve()); manifest.append(item)
    if manifest:
        with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=manifest[0].keys()); writer.writeheader(); writer.writerows(manifest)
    yaml_lines = [f"path: {output.resolve().as_posix()}", "train: train", "val: valid", "test: test", "", "names:"] + [f"  {i}: {json.dumps(label, ensure_ascii=False)}" for i, label in enumerate(labels)]
    (output / "dataset.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    stats = {"dataset_version": version, "created_at": datetime.now().isoformat(timespec="seconds"), "total_images": len(manifest), "split_counts": {s: sum(row["split"] == s for row in rows) for s in ["train", "valid", "test"]}}
    (output / "statistics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"version": version, "path": str(output.resolve()), "count": len(manifest)}


@app.get("/api/images/{value}/file")
def image_file(value: str) -> FileResponse:
    with connect() as conn:
        row = conn.execute("SELECT path FROM images WHERE image_id=?", (value,)).fetchone()
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    return FileResponse(row["path"])


@app.get("/api/images/{value}/cam")
def cam_file(value: str) -> FileResponse:
    with connect() as conn:
        row = conn.execute("SELECT path FROM images WHERE image_id=?", (value,)).fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")
    source = Path(row["path"]); candidates = [CAM_ROOT / source.name]
    try:
        candidates.insert(0, CAM_ROOT / source.relative_to(DATA_ROOT))
    except ValueError:
        pass
    for candidate in candidates:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(404, "CAM 이미지가 없습니다.")
