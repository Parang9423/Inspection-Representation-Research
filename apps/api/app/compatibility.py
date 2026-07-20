from __future__ import annotations

from .data_model import connect


def ensure_compatibility_triggers() -> None:
    """Migrate legacy history and mirror normalized state during the transition."""
    with connect() as conn:
        legacy_history = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='label_history'"
        ).fetchone()
        if legacy_history:
            conn.execute(
                """INSERT INTO annotation_history(
                       image_id,previous_label,new_label,changed_by,changed_at,
                       previous_version,new_version)
                   SELECT lh.image_id,lh.previous_label,lh.new_label,lh.changed_by,lh.changed_at,
                          lh.previous_version,lh.new_version
                   FROM label_history lh
                   WHERE NOT EXISTS (
                       SELECT 1 FROM annotation_history ah
                       WHERE ah.image_id=lh.image_id
                         AND ah.changed_at=lh.changed_at
                         AND ah.previous_version=lh.previous_version
                         AND ah.new_version=lh.new_version
                   )"""
            )

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
