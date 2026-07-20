import sqlite3

from fastapi import APIRouter

from .main import DB_PATH
from .collaboration import ensure_collaboration_schema

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


@router.get("/summary")
def collaboration_summary() -> dict:
    ensure_collaboration_schema()
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        totals = conn.execute(
            """SELECT COUNT(*) total,
               SUM(status='included') included,
               SUM(status='review') review,
               SUM(status='excluded') excluded,
               SUM(split!='unassigned') assigned,
               SUM(status='included' AND split='unassigned') unassigned,
               SUM(review_status='reviewed') reviewed,
               SUM(review_status='reviewing') reviewing
               FROM images"""
        ).fetchone()
        classes = conn.execute(
            """SELECT label,
               SUM(split='train' AND status='included') train,
               SUM(split='valid' AND status='included') valid,
               SUM(split='test' AND status='included') test,
               SUM(split='unassigned' AND status='included') unassigned,
               COUNT(*) total
               FROM images GROUP BY label ORDER BY total DESC"""
        ).fetchall()
        return {"totals": dict(totals), "classes": [dict(row) for row in classes]}
    finally:
        conn.close()
