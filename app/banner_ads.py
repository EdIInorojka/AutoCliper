"""Cinema banner asset selection and pink-screen cleanup helpers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.utils.console import get_console

console = get_console()


@dataclass(frozen=True)
class BannerAsset:
    path: str
    crop: tuple[int, int, int, int]
    key_hex: str
    start_sec: float = 0.0
    duration_sec: float = 0.0


def find_banner_files(folder: str) -> list[str]:
    """Find supported banner video files."""
    path = Path(folder)
    if not path.exists() and not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / folder
    if not path.exists():
        return []
    files: list[Path] = []
    for pattern in ("*.mp4", "*.mov", "*.webm", "*.mkv"):
        files.extend(path.glob(pattern))
    return [str(file.resolve()) for file in sorted(files)]


def pick_banner_asset(config: AppConfig) -> Optional[BannerAsset]:
    """Pick and probe one banner asset from the configured folder."""
    banner = getattr(config, "banner", None)
    if banner is None or not bool(getattr(banner, "enabled", False)):
        return None

    selected_file = getattr(banner, "selected_file", None)
    if selected_file:
        selected_path = Path(str(selected_file))
        if not selected_path.is_absolute():
            selected_path = (Path(__file__).resolve().parent.parent / selected_path).resolve()
        if selected_path.exists():
            return probe_banner_asset(str(selected_path))

    files = find_banner_files(str(getattr(banner, "folder", "Banners") or "Banners"))
    if not files:
        console.print("[yellow]Cinema banner: no files found in Banners/[/yellow]")
        return None

    if getattr(config, "variation", None) is not None and getattr(
        config.variation, "bgm_random_pick", False
    ):
        chosen = random.choice(files)
    else:
        chosen = files[0]
    return probe_banner_asset(chosen)


@lru_cache(maxsize=32)
def probe_banner_asset(path: str) -> BannerAsset:
    """Probe banner crop and chroma key color from the first valid frame."""
    probed = _read_probe_frame(path)
    duration_sec = _probe_banner_duration(path)
    if probed is None:
        return BannerAsset(
            path=path,
            crop=(0, 0, 1080, 1920),
            key_hex="0xFF00FF",
            duration_sec=duration_sec,
        )
    frame, key_rgb, crop, start_sec = probed
    height, width = frame.shape[:2]
    if crop is None:
        crop = (0, 0, width, height)
    return BannerAsset(
        path=path,
        crop=crop,
        key_hex=f"0x{key_rgb[0]:02X}{key_rgb[1]:02X}{key_rgb[2]:02X}",
        start_sec=start_sec,
        duration_sec=duration_sec,
    )


def load_banner_preview_rgba(
    asset: BannerAsset,
    time_sec: float,
    similarity: float = 0.18,
):
    """Load a cleaned RGBA banner frame for preview placement."""
    try:
        import cv2  # type: ignore
        import numpy as np
    except Exception:
        return None

    capture = cv2.VideoCapture(asset.path)
    if not capture.isOpened():
        return None
    try:
        actual_time = banner_time_for_preview(asset, time_sec)
        capture.set(cv2.CAP_PROP_POS_MSEC, actual_time * 1000.0)
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        x, y, w, h = asset.crop
        crop = rgb[y : y + h, x : x + w]
        if crop.size == 0:
            return None

        key_rgb = _parse_key_hex(asset.key_hex)
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        key_hsv = cv2.cvtColor(
            np.array([[[key_rgb[0], key_rgb[1], key_rgb[2]]]], dtype=np.uint8),
            cv2.COLOR_RGB2HSV,
        )[0, 0]
        hue_delta = cv2.absdiff(hsv[:, :, 0], np.full(hsv.shape[:2], key_hsv[0], dtype=np.uint8))
        hue_delta = np.minimum(hue_delta, 180 - hue_delta)
        hue_threshold = int(max(6, min(18, round(6 + float(similarity) * 40))))
        sat_floor = max(72, int(key_hsv[1] * 0.55))
        val_floor = max(72, int(key_hsv[2] * 0.45))
        mask_key = (
            (hue_delta <= hue_threshold)
            & (hsv[:, :, 1] >= sat_floor)
            & (hsv[:, :, 2] >= val_floor)
        )
        mask = (~mask_key).astype(np.uint8) * 255

        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        alpha = np.where(mask >= 128, 255, 0).astype(np.uint8)

        rgba = np.dstack((crop, alpha))
        return rgba
    finally:
        capture.release()


def banner_time_for_preview(asset: BannerAsset, requested_sec: float) -> float:
    """Clamp or wrap a requested preview time to the banner duration."""
    duration = max(0.0, float(getattr(asset, "duration_sec", 0.0) or 0.0))
    if duration <= 0.05:
        return max(0.0, float(requested_sec))
    requested = max(0.0, float(requested_sec))
    if requested < duration:
        return requested
    return requested % duration


def _read_probe_frame(path: str):
    try:
        import cv2  # type: ignore
    except Exception:
        return None

    capture = cv2.VideoCapture(path)
    try:
        best = None
        best_area = -1
        for t_ms in (0, 300, 600, 1000, 1500, 2000, 4000, 8000):
            capture.set(cv2.CAP_PROP_POS_MSEC, t_ms)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            key_rgb = _sample_key_color(rgb)
            crop = _detect_banner_bounds_from_frame(rgb, key_rgb)
            if crop is None:
                if best is None:
                    best = (rgb, key_rgb, None, 0.0)
                continue
            area = crop[2] * crop[3]
            if area > best_area:
                best = (rgb, key_rgb, crop, float(t_ms) / 1000.0)
                best_area = area
        return best
    finally:
        capture.release()


def _probe_banner_duration(path: str) -> float:
    try:
        import cv2  # type: ignore
    except Exception:
        return 0.0

    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        return 0.0
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        if fps > 0.0 and frames > 0.0:
            return max(0.0, frames / fps)
        return max(0.0, float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0)
    finally:
        capture.release()


def _sample_key_color(frame) -> tuple[int, int, int]:
    """Estimate the chroma key color from the four corners of a frame."""
    import numpy as np

    height, width = frame.shape[:2]
    patch_h = max(8, min(48, height // 10))
    patch_w = max(8, min(48, width // 10))
    patches = [
        frame[:patch_h, :patch_w],
        frame[:patch_h, width - patch_w : width],
        frame[height - patch_h : height, :patch_w],
        frame[height - patch_h : height, width - patch_w : width],
    ]
    stacked = np.concatenate([patch.reshape(-1, 3) for patch in patches], axis=0)
    rgb = stacked.mean(axis=0)
    return tuple(int(max(0, min(255, round(v)))) for v in rgb)


def _parse_key_hex(key_hex: str) -> tuple[int, int, int]:
    raw = str(key_hex or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    raw = raw.lstrip("#")
    if len(raw) != 6:
        return (255, 0, 255)
    try:
        return tuple(int(raw[idx : idx + 2], 16) for idx in (0, 2, 4))
    except ValueError:
        return (255, 0, 255)


def _detect_banner_bounds_from_frame(
    frame,
    key_rgb: tuple[int, int, int],
) -> Optional[tuple[int, int, int, int]]:
    """Find the non-keyed banner bounds inside a pink-screen banner frame."""
    import numpy as np

    target = np.array(key_rgb, dtype=np.int32).reshape(1, 1, 3)
    diff = np.abs(frame.astype(np.int32) - target)
    distance = np.sqrt((diff * diff).sum(axis=2))
    mask = distance > 42.0
    row_density = mask.mean(axis=1)
    col_density = mask.mean(axis=0)
    row_threshold = max(0.02, float(row_density.max()) * 0.35)
    col_threshold = max(0.02, float(col_density.max()) * 0.35)
    row_indices = np.where(row_density > row_threshold)[0]
    col_indices = np.where(col_density > col_threshold)[0]
    if len(row_indices) == 0 or len(col_indices) == 0:
        return None

    x1 = int(col_indices.min())
    x2 = int(col_indices.max()) + 1
    y1 = int(row_indices.min())
    y2 = int(row_indices.max()) + 1
    height, width = frame.shape[:2]
    pad_x = max(2, int((x2 - x1) * 0.02))
    pad_y = max(2, int((y2 - y1) * 0.03))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)

    inner = distance[y1:y2, x1:x2]
    if inner.size:
        inner_row_mean = inner.mean(axis=1)
        inner_col_mean = inner.mean(axis=0)
        row_mean_threshold = max(10.0, float(inner_row_mean.max()) * 0.18)
        col_mean_threshold = max(10.0, float(inner_col_mean.max()) * 0.18)
        inner_rows = np.where(inner_row_mean > row_mean_threshold)[0]
        inner_cols = np.where(inner_col_mean > col_mean_threshold)[0]
        if len(inner_rows) > 0 and len(inner_cols) > 0:
            base_y1 = y1
            base_x1 = x1
            y1 = base_y1 + int(inner_rows.min())
            y2 = base_y1 + int(inner_rows.max() + 1)
            x1 = base_x1 + int(inner_cols.min())
            x2 = base_x1 + int(inner_cols.max() + 1)

    crop_w = max(2, x2 - x1)
    crop_h = max(2, y2 - y1)
    if crop_w < 32 or crop_h < 24:
        return None
    if crop_w >= width * 0.92 and crop_h >= height * 0.92:
        return None
    return x1, y1, crop_w, crop_h
