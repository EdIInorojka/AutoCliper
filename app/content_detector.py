"""Main content / slot crop detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import AppConfig
from app.probe import VideoInfo
from app.utils.console import get_console
from app.webcam_types import WebcamDetectionResult

console = get_console()

_REFERENCE_LAYOUT_PROFILES = [
    {
        "name": "ref_stake_left_overlay",
        "webcam": (0.000, 0.449, 0.265, 0.281),
        "slot": (0.241, 0.112, 0.742, 0.781),
    },
    {
        "name": "ref_fixa_small_top_right",
        "webcam": (0.815, 0.003, 0.185, 0.229),
        "slot": (0.170, 0.181, 0.751, 0.786),
    },
    {
        "name": "ref_vavada_bottom_right",
        "webcam": (0.694, 0.648, 0.306, 0.325),
        "slot": (0.008, 0.090, 0.733, 0.775),
    },
    {
        "name": "ref_right_rail_top_webcam",
        "webcam": (0.666, 0.032, 0.324, 0.322),
        "slot": (0.048, 0.118, 0.624, 0.625),
    },
    {
        "name": "ref_ezugi_top_right",
        "webcam": (0.683, 0.073, 0.289, 0.285),
        "slot": (0.064, 0.239, 0.676, 0.626),
    },
    {
        "name": "ref_chat_right_bottom_webcam",
        "webcam": (0.761, 0.647, 0.239, 0.353),
        "slot": (0.027, 0.104, 0.704, 0.699),
    },
    {
        "name": "ref_bottom_left_webcam",
        "webcam": (0.002, 0.714, 0.243, 0.284),
        "slot": (0.169, 0.077, 0.809, 0.808),
    },
    {
        "name": "ref_mendigo_bottom_overlay",
        "webcam": (0.594, 0.612, 0.269, 0.385),
        "slot": (0.141, 0.066, 0.666, 0.731),
    },
]


@dataclass
class ContentDetectionResult:
    has_content: bool
    crop: tuple[int, int, int, int]
    confidence: float = 0.0
    reason: str = "fallback"


def detect_content_area(
    video_path: str,
    video_info: VideoInfo,
    webcam_result: WebcamDetectionResult,
    config: AppConfig,
) -> ContentDetectionResult:
    """
    Detect the main slot/game/content crop.

    The detector is conservative: it prefers a centered, wide crop and keeps
    the full slot/game area even when a webcam overlay overlaps it. OpenCV
    activity scoring improves the crop when available, but the fallback is
    deterministic and safe.
    """
    src_w = int(video_info.width)
    src_h = int(video_info.height)
    webcam_crop = _webcam_crop(webcam_result)
    fallback_crop, fallback_reason = _fallback_content_crop(src_w, src_h)
    if webcam_crop is None:
        console.print(
            f"[cyan]Content crop: {fallback_crop}, confidence=0.50, reason={fallback_reason}[/cyan]"
        )
        return ContentDetectionResult(True, fallback_crop, 0.50, fallback_reason)

    try:
        import cv2
        import numpy as np
    except ImportError:
        console.print("[yellow]opencv-python-headless is not installed; using centered content crop[/yellow]")
        return ContentDetectionResult(True, fallback_crop, 0.35, fallback_reason)

    frames = _extract_frames(cv2, video_path, num_frames=10)
    if len(frames) < 2:
        return ContentDetectionResult(True, fallback_crop, 0.35, fallback_reason)

    activity = _activity_map(cv2, np, frames)
    candidates = _content_candidates(src_w, src_h, webcam_crop)
    if not candidates:
        return ContentDetectionResult(True, fallback_crop, 0.35, fallback_reason)

    best_crop = fallback_crop
    best_score = -1.0
    best_reason = fallback_reason
    for raw_crop, reason in candidates:
        crop = raw_crop
        score = _score_crop(np, activity, crop, src_w, src_h)
        if reason.startswith("profile_ref_"):
            score += 0.18
        elif reason.startswith("profile_"):
            score += 0.10
        if score > best_score:
            best_score = score
            best_crop = crop
            best_reason = reason

    confidence = max(0.35, min(1.0, best_score))
    console.print(
        f"[cyan]Content crop: {best_crop}, confidence={confidence:.2f}, reason={best_reason}[/cyan]"
    )
    return ContentDetectionResult(True, best_crop, confidence, best_reason)


def centered_content_crop(src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Centered wide crop used when no webcam exists."""
    # Keep most horizontal stream information; vertical output uses blurred fill.
    margin_x = int(src_w * 0.02)
    margin_y = int(src_h * 0.04)
    return _clamp_even_crop(margin_x, margin_y, src_w - 2 * margin_x, src_h - 2 * margin_y, src_w, src_h)


def _fallback_content_crop(
    src_w: int,
    src_h: int,
) -> tuple[tuple[int, int, int, int], str]:
    crop = centered_content_crop(src_w, src_h)
    return crop, "centered"


def _webcam_crop(webcam_result: WebcamDetectionResult) -> Optional[tuple[int, int, int, int]]:
    if not webcam_result.has_webcam or webcam_result.region is None:
        return None
    wr = webcam_result.region
    return wr.x, wr.y, wr.w, wr.h


def _extract_frames(cv2: Any, video_path: str, num_frames: int = 10) -> list[Any]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    max_frame = min(total_frames, int(fps * 300))
    if max_frame <= 0:
        max_frame = total_frames
    step = max(1, max_frame // max(1, num_frames))
    frames = []
    for pos in range(0, min(max_frame, step * num_frames), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(pos, max(0, total_frames - 1)))
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def _activity_map(cv2: Any, np: Any, frames: list[Any]):
    h, w = frames[0].shape[:2]
    cell = 64
    grid_h = max(1, h // cell)
    grid_w = max(1, w // cell)
    activity = np.zeros((grid_h, grid_w), dtype=np.float32)

    previous_gray = None
    for frame in frames[:10]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 160)
        diff = None if previous_gray is None else cv2.absdiff(gray, previous_gray)
        previous_gray = gray

        for gy in range(grid_h):
            for gx in range(grid_w):
                y1, y2 = gy * cell, min(h, (gy + 1) * cell)
                x1, x2 = gx * cell, min(w, (gx + 1) * cell)
                edge_score = float(np.mean(edges[y1:y2, x1:x2])) / 255.0
                motion_score = 0.0 if diff is None else float(np.mean(diff[y1:y2, x1:x2])) / 255.0
                activity[gy, gx] += edge_score * 0.7 + motion_score * 0.3

    max_val = float(np.max(activity))
    if max_val > 0:
        activity /= max_val
    return activity


def _content_candidates(
    src_w: int,
    src_h: int,
    webcam_crop: Optional[tuple[int, int, int, int]],
) -> list[tuple[tuple[int, int, int, int], str]]:
    crops: list[tuple[tuple[int, int, int, int], str]] = []

    def add(x: float, y: float, w: float, h: float, reason: str) -> None:
        if w <= 0 or h <= 0:
            return
        crops.append((_clamp_even_crop(int(x), int(y), int(w), int(h), src_w, src_h), reason))

    add(src_w * 0.02, src_h * 0.04, src_w * 0.96, src_h * 0.92, "centered")
    add(src_w * 0.08, src_h * 0.08, src_w * 0.84, src_h * 0.78, "inner_stream")
    add(src_w * 0.15, src_h * 0.08, src_w * 0.78, src_h * 0.78, "center_right_slot")
    add(src_w * 0.22, src_h * 0.10, src_w * 0.74, src_h * 0.76, "sidebar_trim_slot")
    add(src_w * 0.05, src_h * 0.12, src_w * 0.90, src_h * 0.70, "wide_game")
    for crop, reason in _profile_content_candidates(src_w, src_h, webcam_crop):
        add(*crop, reason)

    if webcam_crop is not None:
        wx, wy, ww, wh = webcam_crop
        # Add edge-aware candidates on the opposite side of the webcam. These
        # are generic and work for left/right/top/bottom overlays.
        if wx + ww / 2 < src_w / 2:
            add(wx + ww + src_w * 0.015, src_h * 0.06, src_w - (wx + ww) - src_w * 0.035, src_h * 0.84, "right_of_webcam")
        else:
            add(src_w * 0.02, src_h * 0.06, wx - src_w * 0.035, src_h * 0.84, "left_of_webcam")
        if wy + wh / 2 < src_h / 2:
            add(src_w * 0.04, wy + wh + src_h * 0.015, src_w * 0.92, src_h - (wy + wh) - src_h * 0.04, "below_webcam")
        else:
            add(src_w * 0.04, src_h * 0.04, src_w * 0.92, wy - src_h * 0.035, "above_webcam")

    unique: list[tuple[tuple[int, int, int, int], str]] = []
    seen = set()
    for crop, reason in crops:
        if crop not in seen:
            seen.add(crop)
            unique.append((crop, reason))
    return unique


def _score_crop(np: Any, activity, crop: tuple[int, int, int, int], src_w: int, src_h: int) -> float:
    x, y, w, h = crop
    cell = 64
    gx1 = max(0, int(x // cell))
    gy1 = max(0, int(y // cell))
    gx2 = min(activity.shape[1], max(gx1 + 1, int((x + w) // cell)))
    gy2 = min(activity.shape[0], max(gy1 + 1, int((y + h) // cell)))
    region = activity[gy1:gy2, gx1:gx2]
    activity_score = float(np.mean(region)) if region.size else 0.0
    area_ratio = (w * h) / max(1, src_w * src_h)
    area_score = 1.0 - min(abs(area_ratio - 0.55) / 0.55, 1.0)
    center_x = x + w / 2
    center_y = y + h / 2
    center_penalty = (abs(center_x - src_w / 2) / src_w) + (abs(center_y - src_h / 2) / src_h) * 0.5
    return activity_score * 0.62 + area_score * 0.30 - center_penalty * 0.18


def _profile_content_candidates(
    src_w: int,
    src_h: int,
    webcam_crop: Optional[tuple[int, int, int, int]],
) -> list[tuple[tuple[float, float, float, float], str]]:
    """
    Region profiles learned from real casino-stream layouts.

    These are still only candidates: the activity scorer chooses the final crop.
    They cover common cases from the user's samples: left webcam overlay, small
    top-right webcam, large right rail, mid-right webcam, and bottom-right webcam.
    """
    base_crops: list[tuple[tuple[float, float, float, float], str]] = [
        ((src_w * 0.24, src_h * 0.10, src_w * 0.74, src_h * 0.76), "profile_stake_left_overlay"),
        ((src_w * 0.13, src_h * 0.09, src_w * 0.82, src_h * 0.84), "profile_fixa_top_right"),
        ((src_w * 0.04, src_h * 0.08, src_w * 0.64, src_h * 0.68), "profile_right_rail_main"),
        ((src_w * 0.17, src_h * 0.11, src_w * 0.70, src_h * 0.72), "profile_center_slot"),
        ((src_w * 0.00, src_h * 0.08, src_w * 0.74, src_h * 0.78), "profile_bottom_right_overlay"),
    ]
    if webcam_crop is None:
        return base_crops

    crops: list[tuple[tuple[float, float, float, float], str]] = []
    crops.extend(_reference_profile_candidates(src_w, src_h, webcam_crop))

    wx, wy, ww, wh = webcam_crop
    margin = max(src_w, src_h) * 0.015
    wc_center_x = wx + ww / 2
    wc_center_y = wy + wh / 2

    if wx <= src_w * 0.12 and src_h * 0.25 <= wc_center_y <= src_h * 0.78:
        left = max(src_w * 0.22, wx + ww + margin)
        crops.append(((left, src_h * 0.09, src_w - left - src_w * 0.02, src_h * 0.78), "profile_left_webcam_slot"))

    if wx + ww >= src_w * 0.80 and wy <= src_h * 0.16:
        if ww >= src_w * 0.26:
            crops.append(((src_w * 0.04, src_h * 0.08, max(src_w * 0.45, wx - src_w * 0.05), src_h * 0.70), "profile_large_top_right_rail"))
        else:
            crops.append(((src_w * 0.12, src_h * 0.08, src_w * 0.84, src_h * 0.84), "profile_small_top_right_overlay"))

    if wx + ww >= src_w * 0.85 and src_h * 0.20 < wc_center_y < src_h * 0.72:
        crops.append(((src_w * 0.16, src_h * 0.10, max(src_w * 0.45, wx - src_w * 0.18), src_h * 0.76), "profile_mid_right_overlay"))

    if wx + ww >= src_w * 0.85 and wy >= src_h * 0.55:
        crops.append(((0, src_h * 0.08, max(src_w * 0.55, wx - margin), src_h * 0.78), "profile_bottom_right_webcam_slot"))

    return crops


def _reference_profile_candidates(
    src_w: int,
    src_h: int,
    webcam_crop: tuple[int, int, int, int],
) -> list[tuple[tuple[float, float, float, float], str]]:
    wx, wy, ww, wh = webcam_crop
    webcam_rel = (wx / src_w, wy / src_h, ww / src_w, wh / src_h)
    crops: list[tuple[tuple[float, float, float, float], str]] = []

    for profile in _REFERENCE_LAYOUT_PROFILES:
        distance = _layout_profile_distance(webcam_rel, profile["webcam"])
        if distance > 0.26:
            continue
        sx, sy, sw, sh = profile["slot"]
        crops.append(
            (
                (src_w * sx, src_h * sy, src_w * sw, src_h * sh),
                f"profile_{profile['name']}",
            )
        )

    return crops


def _layout_profile_distance(
    current: tuple[float, float, float, float],
    reference: tuple[float, float, float, float],
) -> float:
    cx, cy, cw, ch = current
    rx, ry, rw, rh = reference
    current_center = (cx + cw / 2, cy + ch / 2)
    reference_center = (rx + rw / 2, ry + rh / 2)
    center_distance = abs(current_center[0] - reference_center[0]) + abs(
        current_center[1] - reference_center[1]
    )
    size_distance = abs(cw - rw) + abs(ch - rh)
    return center_distance + size_distance * 0.65


def _adjust_crop_for_webcam_overlap(
    crop: tuple[int, int, int, int],
    webcam_crop: Optional[tuple[int, int, int, int]],
    src_w: int,
    src_h: int,
    safe_margin: int | None = None,
) -> tuple[tuple[int, int, int, int], str]:
    if webcam_crop is None:
        return crop, ""

    x, y, w, h = crop
    wx, wy, ww, wh = webcam_crop
    ix1 = max(x, wx)
    iy1 = max(y, wy)
    ix2 = min(x + w, wx + ww)
    iy2 = min(y + h, wy + wh)
    if ix1 >= ix2 or iy1 >= iy2:
        return crop, ""

    margin = int(safe_margin if safe_margin is not None else max(src_w, src_h) * 0.015)
    min_w = max(160, int(src_w * 0.30))
    min_h = max(160, int(src_h * 0.30))
    candidates: list[tuple[int, tuple[int, int, int, int], str]] = []

    left_x = min(x + w - min_w, wx + ww + margin)
    if left_x > x:
        c = _clamp_even_crop(left_x, y, x + w - left_x, h, src_w, src_h)
        if c[2] >= min_w:
            candidates.append((c[2] * c[3], c, "trim_left_overlap"))

    right_w = max(0, wx - margin - x)
    if right_w >= min_w:
        c = _clamp_even_crop(x, y, right_w, h, src_w, src_h)
        candidates.append((c[2] * c[3], c, "trim_right_overlap"))

    top_y = min(y + h - min_h, wy + wh + margin)
    if top_y > y:
        c = _clamp_even_crop(x, top_y, w, y + h - top_y, src_w, src_h)
        if c[3] >= min_h:
            candidates.append((c[2] * c[3], c, "trim_top_overlap"))

    bottom_h = max(0, wy - margin - y)
    if bottom_h >= min_h:
        c = _clamp_even_crop(x, y, w, bottom_h, src_w, src_h)
        candidates.append((c[2] * c[3], c, "trim_bottom_overlap"))

    if not candidates:
        return crop, "overlap_kept"
    _, best_crop, reason = max(candidates, key=lambda item: item[0])
    return best_crop, reason


def _clamp_even_crop(
    x: int,
    y: int,
    w: int,
    h: int,
    src_w: int,
    src_h: int,
) -> tuple[int, int, int, int]:
    w = max(2, min(int(w), src_w))
    h = max(2, min(int(h), src_h))
    w -= w % 2
    h -= h % 2
    x = max(0, min(int(x), src_w - w))
    y = max(0, min(int(y), src_h - h))
    return x, y, w, h
