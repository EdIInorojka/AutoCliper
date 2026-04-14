"""Manual layout annotation dataset used as a lightweight learned fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.utils.helpers import ensure_dir, project_root

Crop = tuple[int, int, int, int]


def append_layout_annotation(
    config: AppConfig,
    *,
    mode: str,
    source_size: tuple[int, int],
    preview_time_sec: float,
    webcam_crop: Optional[Crop],
    slot_crop: Optional[Crop],
    video_path: str = "",
) -> Optional[Path]:
    if not getattr(config, "layout_annotation_dataset_enabled", True):
        return None
    path = _dataset_path(config)
    ensure_dir(path.parent)
    record = {
        "video_path": video_path,
        "mode": mode,
        "source_size": list(source_size),
        "preview_time_sec": float(preview_time_sec),
        "webcam_crop": list(webcam_crop) if webcam_crop else None,
        "slot_crop": list(slot_crop) if slot_crop else None,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def load_scaled_layout_crops(
    config: AppConfig | None,
    src_w: int,
    src_h: int,
    *,
    max_items: int = 200,
) -> list[dict[str, Crop | str]]:
    if config is None or not getattr(config, "layout_annotation_dataset_enabled", True):
        return []
    path = _dataset_path(config)
    if not path.is_file():
        return []

    rows: list[dict[str, Crop | str]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []

    for raw in lines[-max_items:]:
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        source_size = item.get("source_size") or []
        if not isinstance(source_size, list) or len(source_size) != 2:
            continue
        try:
            base_w, base_h = int(source_size[0]), int(source_size[1])
        except (TypeError, ValueError):
            continue
        if base_w <= 0 or base_h <= 0:
            continue
        rows.append(
            {
                "mode": str(item.get("mode") or "manual"),
                "webcam_crop": _scale_crop(item.get("webcam_crop"), base_w, base_h, src_w, src_h),
                "slot_crop": _scale_crop(item.get("slot_crop"), base_w, base_h, src_w, src_h),
            }
        )
    return rows


def _scale_crop(raw, base_w: int, base_h: int, src_w: int, src_h: int) -> Optional[Crop]:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    sx = src_w / base_w
    sy = src_h / base_h
    return _clamp_even_crop(
        int(round(x * sx)),
        int(round(y * sy)),
        int(round(w * sx)),
        int(round(h * sy)),
        src_w,
        src_h,
    )


def _dataset_path(config: AppConfig) -> Path:
    raw = getattr(config, "layout_annotation_dataset_path", "") or "layout_dataset/annotations.jsonl"
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / path
    return path


def _clamp_even_crop(x: int, y: int, w: int, h: int, src_w: int, src_h: int) -> Crop:
    w = max(2, min(int(w), src_w))
    h = max(2, min(int(h), src_h))
    w -= w % 2
    h -= h % 2
    x = max(0, min(int(x), src_w - w))
    y = max(0, min(int(y), src_h - h))
    return x, y, w, h
