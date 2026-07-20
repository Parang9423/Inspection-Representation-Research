from __future__ import annotations

from .data_model import connect


def ensure_compatibility_triggers() -> None:
    """Mirror normalized state into legacy columns until all old endpoints are retired."""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS trg_annotations_insert_legacy
            AFTER INSERT ON image_annotations
            BEGIN
                UPDATE images SET
                    label=NEW.current_label,
                    review_status=NEW.review_status,
                    assigned_to=NEW.assigned_to,
                    reviewed_by=NEW.reviewed_by,
                    reviewed_at=NEW.reviewed_at,
                    version=NEW.version,
                    locked_by=NEW.locked_by,
                    locked_at=NEW.locked_at,
                    updated_at=NEW.updated_at
                WHERE image_id=NEW.image_id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_annotations_update_legacy
            AFTER UPDATE ON image_annotations
            BEGIN
                UPDATE images SET
                    label=NEW.current_label,
                    review_status=NEW.review_status,
                    assigned_to=NEW.assigned_to,
                    reviewed_by=NEW.reviewed_by,
                    reviewed_at=NEW.reviewed_at,
                    version=NEW.version,
                    locked_by=NEW.locked_by,
                    locked_at=NEW.locked_at,
                    updated_at=NEW.updated_at
                WHERE image_id=NEW.image_id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_split_insert_legacy
            AFTER INSERT ON split_assignments
            BEGIN
                UPDATE images SET split=NEW.split_set,updated_at=COALESCE(NEW.assigned_at,updated_at)
                WHERE image_id=NEW.image_id;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_split_update_legacy
            AFTER UPDATE ON split_assignments
            BEGIN
                UPDATE images SET split=NEW.split_set,updated_at=COALESCE(NEW.assigned_at,updated_at)
                WHERE image_id=NEW.image_id;
            END;
            """
        )
