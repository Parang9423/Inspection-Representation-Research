from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .main import DATA_ROOT, DB_PATH, EXPORT_ROOT, IMAGE_EXTENSIONS

router = APIRouter(tags=["normalized-dataset"])


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def image_key(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()


def ensure_normalized_schema() -> None:
    """Create normalized tables and migrate the legacy images table once."""
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS folders (
                folder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_name TEXT NOT NULL UNIQUE,
                absolute_path TEXT NOT NULL,
                image_count INTEGER NOT NULL DEFAULT 0,
                reviewed_count INTEGER NOT NULL DEFAULT 0,
                reviewing_count INTEGER NOT NULL DEFAULT 0,
                last_scanned_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS image_annotations (
                image_id TEXT PRIMARY KEY,
                current_label TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'unreviewed',
                assigned_to TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                locked_by TEXT,
                locked_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS split_assignments (
                image_id TEXT PRIMARY KEY,
                split_set TEXT NOT NULL DEFAULT 'unassigned',
                assigned_by TEXT,
                assigned_at TEXT,
                split_version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS annotation_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT NOT NULL,
                previous_label TEXT,
                new_label TEXT,
                changed_by TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                previous_version INTEGER NOT NULL,
                new_version INTEGER NOT NULL,
                FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS split_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT NOT NULL,
                previous_split TEXT,
                new_split TEXT,
                changed_by TEXT,
                changed_at TEXT NOT NULL,
                FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS dataset_versions (
                dataset_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_name TEXT NOT NULL,
                version_name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'completed',
                export_mode TEXT NOT NULL,
                output_path TEXT NOT NULL,
                created_by TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dataset_version_items (
                dataset_version_id INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                label_snapshot TEXT NOT NULL,
                split_snapshot TEXT NOT NULL,
                source_path_snapshot TEXT NOT NULL,
                export_path TEXT,
                PRIMARY KEY(dataset_version_id, image_id),
                FOREIGN KEY(dataset_version_id) REFERENCES dataset_versions(dataset_version_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_folders_name ON folders(folder_name);
            CREATE INDEX IF NOT EXISTS idx_annotations_label ON image_annotations(current_label);
            CREATE INDEX IF NOT EXISTS idx_annotations_review ON image_annotations(review_status);
            CREATE INDEX IF NOT EXISTS idx_split_set ON split_assignments(split_set);
            CREATE INDEX IF NOT EXISTS idx_annotation_history_image ON annotation_history(image_id);
            """
        )

        image_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone()
        if not image_table:
            return

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
        if "folder_id" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN folder_id INTEGER")
        if "original_label" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN original_label TEXT")
        if "is_active" not in columns:
            conn.execute("ALTER TABLE images ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

        now = iso_now()
        rows = conn.execute("SELECT * FROM images").fetchall()
        for row in rows:
            source_label = str(row["source_label"] or "미분류")
            folder_path = str(Path(row["path"]).parent)
            conn.execute(
                """INSERT INTO folders(folder_name,absolute_path,created_at,updated_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(folder_name) DO UPDATE SET absolute_path=excluded.absolute_path,updated_at=excluded.updated_at""",
                (source_label, folder_path, now, now),
            )
            folder_id = conn.execute(
                "SELECT folder_id FROM folders WHERE folder_name=?", (source_label,)
            ).fetchone()[0]
            conn.execute(
                "UPDATE images SET folder_id=?, original_label=COALESCE(original_label,source_label), is_active=1 WHERE image_id=?",
                (folder_id, row["image_id"]),
            )
            label = row["label"] if "label" in row.keys() else source_label
            split = row["split"] if "split" in row.keys() else "unassigned"
            version = row["version"] if "version" in row.keys() else 1
            review_status = row["review_status"] if "review_status" in row.keys() else "unreviewed"
            conn.execute(
                """INSERT OR IGNORE INTO image_annotations(
                       image_id,current_label,review_status,assigned_to,reviewed_by,reviewed_at,
                       version,locked_by,locked_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["image_id"], label, review_status,
                    row["assigned_to"] if "assigned_to" in row.keys() else None,
                    row["reviewed_by"] if "reviewed_by" in row.keys() else None,
                    row["reviewed_at"] if "reviewed_at" in row.keys() else None,
                    version,
                    row["locked_by"] if "locked_by" in row.keys() else None,
                    row["locked_at"] if "locked_at" in row.keys() else None,
                    now,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO split_assignments(image_id,split_set,assigned_at) VALUES(?,?,?)",
                (row["image_id"], split, now),
            )
        refresh_folder_counts(conn)


def refresh_folder_counts(conn: sqlite3.Connection) -> None:
    conn.execute(
        """UPDATE folders SET
             image_count=(SELECT COUNT(*) FROM images i WHERE i.folder_id=folders.folder_id AND i.is_active=1),
             reviewed_count=(SELECT COUNT(*) FROM images i JOIN image_annotations a ON a.image_id=i.image_id
                             WHERE i.folder_id=folders.folder_id AND i.is_active=1 AND a.review_status='reviewed'),
             reviewing_count=(SELECT COUNT(*) FROM images i JOIN image_annotations a ON a.image_id=i.image_id
                              WHERE i.folder_id=folders.folder_id AND i.is_active=1 AND a.review_status='reviewing'),
             updated_at=?""",
        (iso_now(),),
    )


def catalog_select() -> str:
    return """
        SELECT i.*, f.folder_name AS source_label,
               COALESCE(i.original_label,f.folder_name) AS original_label,
               COALESCE(a.current_label,COALESCE(i.original_label,f.folder_name)) AS label,
               COALESCE(s.split_set,'unassigned') AS split,
               COALESCE(a.review_status,'unreviewed') AS review_status,
               a.assigned_to,a.reviewed_by,a.reviewed_at,
               COALESCE(a.version,1) AS version,a.locked_by,a.locked_at
        FROM images i
        JOIN folders f ON f.folder_id=i.folder_id
        LEFT JOIN image_annotations a ON a.image_id=i.image_id
        LEFT JOIN split_assignments s ON s.image_id=i.image_id
    """


def scan_catalog() -> dict:
    ensure_normalized_schema()
    now = iso_now()
    discovered: set[str] = set()
    added = 0
    updated = 0
    with connect() as conn:
        for folder in sorted((p for p in DATA_ROOT.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            conn.execute(
                """INSERT INTO folders(folder_name,absolute_path,last_scanned_at,created_at,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(folder_name) DO UPDATE SET absolute_path=excluded.absolute_path,
                     last_scanned_at=excluded.last_scanned_at,updated_at=excluded.updated_at""",
                (folder.name, str(folder.resolve()), now, now, now),
            )
            folder_id = conn.execute("SELECT folder_id FROM folders WHERE folder_name=?", (folder.name,)).fetchone()[0]
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                resolved = str(path.resolve())
                discovered.add(resolved)
                stat = path.stat()
                row = conn.execute("SELECT image_id FROM images WHERE path=?", (resolved,)).fetchone()
                if row:
                    conn.execute(
                        """UPDATE images SET folder_id=?,filename=?,size_bytes=?,modified_at=?,
                           original_label=?,is_active=1,updated_at=? WHERE path=?""",
                        (folder_id, path.name, stat.st_size, stat.st_mtime, folder.name, now, resolved),
                    )
                    updated += 1
                    image_id = row["image_id"]
                else:
                    image_id = image_key(path)
                    conn.execute(
                        """INSERT INTO images(image_id,path,filename,source_label,label,split,status,note,
                           size_bytes,modified_at,created_at,updated_at,folder_id,original_label,is_active)
                           VALUES(?,?,?,?,?,'unassigned','included','',?,?,?,?,?,?,1)""",
                        (image_id, resolved, path.name, folder.name, folder.name, stat.st_size, stat.st_mtime, now, now, folder_id, folder.name),
                    )
                    conn.execute(
                        "INSERT INTO image_annotations(image_id,current_label,updated_at) VALUES(?,?,?)",
                        (image_id, folder.name, now),
                    )
                    conn.execute(
                        "INSERT INTO split_assignments(image_id,split_set,assigned_at) VALUES(?,'unassigned',?)",
                        (image_id, now),
                    )
                    added += 1
        if discovered:
            placeholders = ",".join("?" for _ in discovered)
            conn.execute(f"UPDATE images SET is_active=0 WHERE path NOT IN ({placeholders})", tuple(discovered))
        else:
            conn.execute("UPDATE images SET is_active=0")
        refresh_folder_counts(conn)
    return {"count": len(discovered), "added": added, "updated": updated}


class AutoSplitRequest(BaseModel):
    train_ratio: int = Field(80, ge=0, le=100)
    valid_ratio: int = Field(10, ge=0, le=100)
    test_ratio: int = Field(10, ge=0, le=100)
    seed: int = 42
    only_unassigned: bool = True
    actor: str | None = None


class ExportRequest(BaseModel):
    dataset_name: str = "aoi_dataset"
    mode: str = "copy"
    actor: str | None = None


def next_version(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "aoi_dataset"
    versions = [int(p.name.rsplit("_v", 1)[-1]) for p in EXPORT_ROOT.glob(f"{safe}_v*") if p.name.rsplit("_v", 1)[-1].isdigit()]
    return f"{safe}_v{max(versions, default=0) + 1:03d}"


@router.post("/api/scan")
def scan_route() -> dict:
    return scan_catalog()


@router.post("/api/splits/auto")
def auto_split(request: AutoSplitRequest) -> dict:
    if request.train_ratio + request.valid_ratio + request.test_ratio != 100:
        raise HTTPException(400, "분할 비율의 합은 100이어야 합니다.")
    ensure_normalized_schema()
    now = iso_now()
    with connect() as conn:
        query = catalog_select() + " WHERE i.is_active=1"
        if request.only_unassigned:
            query += " AND COALESCE(s.split_set,'unassigned')='unassigned'"
        rows = conn.execute(query).fetchall()
        groups: dict[str, list[str]] = {}
        for row in rows:
            groups.setdefault(row["label"], []).append(row["image_id"])
        rng = random.Random(request.seed)
        assignments: list[tuple[str, str]] = []
        for ids in groups.values():
            rng.shuffle(ids)
            train_end = int(len(ids) * request.train_ratio / 100)
            valid_end = train_end + int(len(ids) * request.valid_ratio / 100)
            assignments += [(value, "train") for value in ids[:train_end]]
            assignments += [(value, "valid") for value in ids[train_end:valid_end]]
            assignments += [(value, "test") for value in ids[valid_end:]]
        for image_id, split_set in assignments:
            previous = conn.execute("SELECT split_set FROM split_assignments WHERE image_id=?", (image_id,)).fetchone()
            previous_split = previous[0] if previous else "unassigned"
            conn.execute(
                """INSERT INTO split_assignments(image_id,split_set,assigned_by,assigned_at)
                   VALUES(?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET
                   split_set=excluded.split_set,assigned_by=excluded.assigned_by,
                   assigned_at=excluded.assigned_at,split_version=split_version+1""",
                (image_id, split_set, request.actor, now),
            )
            if previous_split != split_set:
                conn.execute(
                    "INSERT INTO split_history(image_id,previous_split,new_split,changed_by,changed_at) VALUES(?,?,?,?,?)",
                    (image_id, previous_split, split_set, request.actor, now),
                )
    return {"updated": len(assignments)}


@router.post("/api/exports")
def export_dataset(request: ExportRequest) -> dict:
    if request.mode not in {"copy", "hardlink", "manifest"}:
        raise HTTPException(400, "지원하지 않는 내보내기 방식입니다.")
    ensure_normalized_schema()
    version_name = next_version(request.dataset_name)
    output = EXPORT_ROOT / version_name
    output.mkdir(parents=True, exist_ok=False)
    created_at = iso_now()
    with connect() as conn:
        rows = conn.execute(
            catalog_select() + " WHERE i.is_active=1 AND COALESCE(s.split_set,'unassigned') IN ('train','valid','test')"
        ).fetchall()
        cursor = conn.execute(
            """INSERT INTO dataset_versions(dataset_name,version_name,export_mode,output_path,created_by,created_at)
               VALUES(?,?,?,?,?,?)""",
            (request.dataset_name, version_name, request.mode, str(output.resolve()), request.actor, created_at),
        )
        version_id = cursor.lastrowid
        manifest: list[dict] = []
        labels = sorted({row["label"] for row in rows})
        for row in rows:
            src = Path(row["path"])
            if not src.exists():
                continue
            dst = output / row["split"] / row["label"] / src.name
            export_path = ""
            if request.mode != "manifest":
                dst.parent.mkdir(parents=True, exist_ok=True)
                if request.mode == "hardlink":
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                else:
                    shutil.copy2(src, dst)
                export_path = str(dst.resolve())
            conn.execute(
                """INSERT INTO dataset_version_items(dataset_version_id,image_id,label_snapshot,
                   split_snapshot,source_path_snapshot,export_path) VALUES(?,?,?,?,?,?)""",
                (version_id, row["image_id"], row["label"], row["split"], str(src.resolve()), export_path),
            )
            manifest.append({
                "image_id": row["image_id"], "source_path": str(src.resolve()),
                "label": row["label"], "split": row["split"], "export_path": export_path,
            })
    if manifest:
        import csv
        with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=manifest[0].keys())
            writer.writeheader(); writer.writerows(manifest)
    yaml_lines = [f"path: {output.resolve().as_posix()}", "train: train", "val: valid", "test: test", "", "names:"] + [f"  {i}: {json.dumps(label, ensure_ascii=False)}" for i, label in enumerate(labels)]
    (output / "dataset.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    stats = {"dataset_version": version_name, "created_at": created_at, "total_images": len(manifest), "split_counts": {s: sum(item["split"] == s for item in manifest) for s in ["train", "valid", "test"]}}
    (output / "statistics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"version": version_name, "path": str(output.resolve()), "count": len(manifest)}
