from __future__ import annotations

import re

from fastapi import APIRouter, Query

from .collaboration import serialize
from .data_model import catalog_select, connect, ensure_normalized_schema

router = APIRouter(prefix="/api/collaboration", tags=["dataset-browser"])


def hotkey_sort_key(item: dict) -> tuple[int, str]:
    try:
        return int(item["key"]), item["label"].lower()
    except (TypeError, ValueError):
        return 10**9, item["label"].lower()


@router.get("/folders")
def list_folders() -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        rows = conn.execute(
            """SELECT folder_id,folder_name,image_count,reviewed_count,reviewing_count,
                      last_scanned_at,updated_at
               FROM folders
               WHERE image_count > 0
               ORDER BY folder_name COLLATE NOCASE"""
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/hotkeys")
def list_hotkeys() -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT folder_name FROM folders WHERE image_count>0 ORDER BY folder_name COLLATE NOCASE"
        ).fetchall()

    labels = [str(row["folder_name"] or "").strip() for row in rows]
    labels = [label for label in labels if label]
    items: list[dict[str, str]] = []
    pending_labels: list[str] = []
    used_keys: set[int] = set()

    for label in labels:
        match = re.match(r"^\s*(\d+)\s*[_\-. ]*", label)
        if not match:
            pending_labels.append(label)
            continue
        numeric_key = int(match.group(1))
        if numeric_key <= 0 or numeric_key in used_keys:
            pending_labels.append(label)
            continue
        used_keys.add(numeric_key)
        items.append({"key": str(numeric_key), "label": label})

    next_key = 1
    for label in pending_labels:
        while next_key in used_keys:
            next_key += 1
        used_keys.add(next_key)
        items.append({"key": str(next_key), "label": label})
        next_key += 1

    items.sort(key=hotkey_sort_key)
    return {"items": items}


@router.get("/folder-images")
def list_folder_images(
    source_label: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    search: str | None = None,
    review_status: str | None = Query(None, pattern="^(unreviewed|reviewing|reviewed)$"),
    actor: str | None = None,
    changed_only: bool = False,
) -> dict:
    """Load one page of image metadata using server-side review filters."""
    ensure_normalized_schema()
    where = ["i.is_active=1", "f.folder_name=?"]
    params: list[object] = [source_label]

    if search:
        where.append(
            "(i.filename LIKE ? OR COALESCE(a.current_label,i.original_label,f.folder_name) LIKE ?)"
        )
        term = f"%{search}%"
        params.extend([term, term])
    if review_status:
        where.append("COALESCE(a.review_status,'unreviewed')=?")
        params.append(review_status)
    if actor:
        where.append("(a.reviewed_by=? OR a.assigned_to=? OR a.locked_by=?)")
        params.extend([actor, actor, actor])
    if changed_only:
        where.append(
            "EXISTS(SELECT 1 FROM annotation_history h WHERE h.image_id=i.image_id)"
        )

    clause = " AND ".join(where)
    offset = (page - 1) * page_size

    with connect() as conn:
        total = conn.execute(
            """SELECT COUNT(*) FROM images i
               JOIN folders f ON f.folder_id=i.folder_id
               LEFT JOIN image_annotations a ON a.image_id=i.image_id
               WHERE """ + clause,
            params,
        ).fetchone()[0]
        rows = conn.execute(
            catalog_select()
            + f" WHERE {clause} ORDER BY i.filename COLLATE NOCASE LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()

    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "source_label": source_label,
        "filters": {
            "review_status": review_status,
            "actor": actor,
            "changed_only": changed_only,
        },
    }
