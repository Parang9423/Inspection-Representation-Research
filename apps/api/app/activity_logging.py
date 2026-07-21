from __future__ import annotations

from .data_model import connect


def ensure_activity_logging_triggers() -> None:
    """Record image review events without coupling every API route to logging."""
    with connect() as conn:
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS trg_activity_label_change;
            DROP TRIGGER IF EXISTS trg_activity_image_reviewed;

            CREATE TRIGGER trg_activity_label_change
            AFTER INSERT ON annotation_history
            BEGIN
              INSERT INTO work_activity_logs(
                folder_id,folder_name,image_id,actor,action,detail,created_at
              )
              SELECT
                i.folder_id,
                f.folder_name,
                NEW.image_id,
                NEW.changed_by,
                'label_change',
                COALESCE(NEW.previous_label,'') || ' -> ' || COALESCE(NEW.new_label,''),
                NEW.changed_at
              FROM images i
              LEFT JOIN folders f ON f.folder_id=i.folder_id
              WHERE i.image_id=NEW.image_id;
            END;

            CREATE TRIGGER trg_activity_image_reviewed
            AFTER UPDATE OF review_status ON image_annotations
            WHEN NEW.review_status='reviewed'
              AND COALESCE(OLD.review_status,'unreviewed')!='reviewed'
            BEGIN
              INSERT INTO work_activity_logs(
                folder_id,folder_name,image_id,actor,action,detail,created_at
              )
              SELECT
                i.folder_id,
                f.folder_name,
                NEW.image_id,
                COALESCE(NEW.reviewed_by,NEW.assigned_to),
                'image_reviewed',
                COALESCE(NEW.current_label,''),
                COALESCE(NEW.reviewed_at,NEW.updated_at)
              FROM images i
              LEFT JOIN folders f ON f.folder_id=i.folder_id
              WHERE i.image_id=NEW.image_id;
            END;
            """
        )
        conn.commit()
