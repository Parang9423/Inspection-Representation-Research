from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .data_model import ExportRequest, catalog_select, connect, ensure_normalized_schema, iso_now, next_version
from .main import EXPORT_ROOT
from .task_worker import worker

router = APIRouter(tags=["dataset-export"])


def _export_dataset(request_data: dict[str, Any]) -> dict[str, Any]:
    request = ExportRequest(**request_data)
    ensure_normalized_schema()
    version_name = next_version(request.dataset_name)
    output = EXPORT_ROOT / version_name
    output.mkdir(parents=True, exist_ok=False)
    created_at = iso_now()

    with connect() as conn:
        rows = conn.execute(
            catalog_select()
            + " WHERE i.is_active=1 AND COALESCE(s.split_set,'unassigned') IN ('train','valid','test')"
        ).fetchall()
        cursor = conn.execute(
            """INSERT INTO dataset_versions(dataset_name,version_name,status,export_mode,output_path,created_by,created_at)
               VALUES(?,?, 'running', ?,?,?,?)""",
            (request.dataset_name, version_name, request.mode, str(output.resolve()), request.actor, created_at),
        )
        version_id = cursor.lastrowid
        manifest: list[dict[str, str]] = []
        labels = sorted({row["label"] for row in rows})

        try:
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
                    "image_id": row["image_id"],
                    "source_path": str(src.resolve()),
                    "label": row["label"],
                    "split": row["split"],
                    "export_path": export_path,
                })

            if manifest:
                with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
                    writer = csv.DictWriter(file, fieldnames=manifest[0].keys())
                    writer.writeheader()
                    writer.writerows(manifest)

            yaml_lines = [
                f"path: {output.resolve().as_posix()}",
                "train: train",
                "val: valid",
                "test: test",
                "",
                "names:",
            ] + [f"  {index}: {json.dumps(label, ensure_ascii=False)}" for index, label in enumerate(labels)]
            (output / "dataset.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

            stats = {
                "dataset_version": version_name,
                "created_at": created_at,
                "total_images": len(manifest),
                "split_counts": {
                    split: sum(item["split"] == split for item in manifest)
                    for split in ["train", "valid", "test"]
                },
            }
            (output / "statistics.json").write_text(
                json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            conn.execute(
                "UPDATE dataset_versions SET status='completed' WHERE dataset_version_id=?",
                (version_id,),
            )
            conn.commit()
        except Exception:
            conn.execute(
                "UPDATE dataset_versions SET status='failed' WHERE dataset_version_id=?",
                (version_id,),
            )
            conn.commit()
            raise

    return {"version": version_name, "path": str(output.resolve()), "count": len(manifest)}


@router.post("/api/exports")
def queue_export(request: ExportRequest) -> dict[str, Any]:
    if request.mode not in {"copy", "hardlink", "manifest"}:
        raise HTTPException(400, "지원하지 않는 내보내기 방식입니다.")
    task = worker.submit(
        "export",
        _export_dataset,
        request.model_dump(),
    )
    return {
        "accepted": True,
        "version": "작업 대기 중",
        "count": 0,
        **task,
    }


@router.get("/api/exports/tasks/latest")
def latest_export_task() -> dict[str, Any]:
    return worker.latest("export") or {"status": "idle"}


@router.get("/api/exports/tasks/{task_id}")
def export_task_status(task_id: str) -> dict[str, Any]:
    task = worker.get(task_id)
    if not task or task.get("task_type") != "export":
        raise HTTPException(404, "내보내기 작업을 찾을 수 없습니다.")
    return task
