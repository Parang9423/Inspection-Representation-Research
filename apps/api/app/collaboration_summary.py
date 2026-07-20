from fastapi import APIRouter

from .data_model import catalog_select, connect, ensure_normalized_schema

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


@router.get("/summary")
def collaboration_summary() -> dict:
    ensure_normalized_schema()
    with connect() as conn:
        base = catalog_select() + " WHERE i.is_active=1"
        rows = conn.execute(base).fetchall()

    totals = {
        "total": len(rows),
        "included": sum(row["status"] == "included" for row in rows),
        "review": sum(row["status"] == "review" for row in rows),
        "excluded": sum(row["status"] == "excluded" for row in rows),
        "assigned": sum(row["split"] != "unassigned" for row in rows),
        "unassigned": sum(row["status"] == "included" and row["split"] == "unassigned" for row in rows),
        "reviewed": sum(row["review_status"] == "reviewed" for row in rows),
        "reviewing": sum(row["review_status"] == "reviewing" for row in rows),
    }
    grouped: dict[str, dict] = {}
    for row in rows:
        label = row["label"]
        item = grouped.setdefault(label, {"label": label, "train": 0, "valid": 0, "test": 0, "unassigned": 0, "total": 0})
        item["total"] += 1
        if row["status"] == "included":
            item[row["split"]] = item.get(row["split"], 0) + 1
    classes = sorted(grouped.values(), key=lambda item: item["total"], reverse=True)
    return {"totals": totals, "classes": classes}
