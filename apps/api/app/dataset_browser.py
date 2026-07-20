from __future__ import annotations

import re

from fastapi import APIRouter, Query

from .collaboration import connect, ensure_collaboration_schema, serialize

router = APIRouter(prefix="/api/collaboration", tags=["dataset-browser"])


def hotkey_sort_key(item: dict) -> tuple[int, str]:
    try:
        return int(item["key"]), item["label"].lower()
    except (TypeError, ValueError):
        return 10**9, item["label"].lower()


@router.get("/folders")
def list_folders() -> dict:
    """Return source folders and image counts without loading image rows."""
    ensure_collaboration_schema()
    with connect() as conn:
        rows = conn.execute(
            """SELECT source_label AS folder_name,
                      COUNT(*) AS image_count,
                      SUM(CASE WHEN review_status='reviewed' THEN 1 ELSE 0 END) AS reviewed_count,
                      SUM(CASE WHEN review_status='reviewing' THEN 1 ELSE 0 END) AS reviewing_count
               FROM images
               GROUP BY source_label
               ORDER BY source_label COLLATE NOCASE"""
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/hotkeys")
def list_hotkeys() -> dict:
    """Build stable class hotkeys from every original class stored in the DB.

    An explicit numeric prefix is preserved. Labels without a prefix receive the
    next available positive integer so legacy databases still expose hotkeys.
    """
    ensure_collaboration_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source_label FROM images ORDER BY source_label COLLATE NOCASE"
        ).fetchall()

    labels = [str(row["source_label"] or "").strip() for row in rows]
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
) -> dict:
    """Load only images belonging to the selected original source folder."""
    ensure_collaboration_schema()
    where = ["source_label=?"]
    params: list[object] = [source_label]
    if search:
        where.append("(filename LIKE ? OR label LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term])
    clause = " AND ".join(where)
    offset = (page - 1) * page_size
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM images WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM images WHERE {clause} ORDER BY filename COLLATE NOCASE LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "source_label": source_label,
    }
