from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from . import data_model
from .main import APP_DIR

router = APIRouter(tags=["thumbnail-cache"])
THUMB_ROOT = Path(os.getenv("AOI_THUMB_ROOT", APP_DIR / "data" / "thumbnail_cache"))
THUMB_SIZE = (256, 256)


def _cache_path(image_id: str, modified_at: float) -> Path:
    version = str(int(modified_at or 0))
    return THUMB_ROOT / image_id[:2] / f"{image_id}_{version}.jpg"


def _build_thumbnail(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.jpg")
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", THUMB_SIZE, "black")
            x = (THUMB_SIZE[0] - image.width) // 2
            y = (THUMB_SIZE[1] - image.height) // 2
            canvas.paste(image, (x, y))
            canvas.save(temporary, format="JPEG", quality=82, optimize=True)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


@router.get("/api/images/{image_id}/thumbnail")
def get_thumbnail(image_id: str):
    with data_model.connect() as conn:
        row = conn.execute(
            "SELECT path,modified_at FROM images WHERE image_id=? AND COALESCE(is_active,1)=1",
            (image_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")

    source = Path(row["path"])
    if not source.exists():
        raise HTTPException(404, "원본 이미지 파일이 없습니다.")

    target = _cache_path(image_id, float(row["modified_at"] or 0))
    if not target.exists():
        try:
            _build_thumbnail(source, target)
        except Exception as exc:
            raise HTTPException(422, f"썸네일을 생성할 수 없습니다: {exc}") from exc
    return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})
