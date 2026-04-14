"""Webcam detection using face detection + frame differencing."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.utils.console import get_console
from app.webcam_types import WebcamDetectionResult, WebcamRegion
from app.config import AppConfig

console = get_console()


class _OpenCV:
    """Lazy OpenCV + cascade load (import only when detect_webcam runs)."""

    cv2: Any = None
    np: Any = None
    face_cascades: list[Any] | None = None


def _ensure_opencv() -> bool:
    if _OpenCV.cv2 is not None:
        return True
    try:
        import cv2
        import numpy as np
    except ImportError:
        console.print("[yellow]opencv-python-headless is not installed; skipping webcam detection[/yellow]")
        return False
    _OpenCV.cv2 = cv2
    _OpenCV.np = np
    paths = [
        cv2.data.haarcascades + "haarcascade_frontalface_alt.xml",
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
        cv2.data.haarcascades + "haarcascade_profileface.xml",
    ]
    cascades = []
    for cp in paths:
        if os.path.exists(cp):
            cascade_path = _cascade_path_for_opencv(cp)
            cascade = cv2.CascadeClassifier(cascade_path)
            if not cascade.empty():
                cascades.append(cascade)
    _OpenCV.face_cascades = cascades
    return True


def _cascade_path_for_opencv(path: str) -> str:
    """Give OpenCV an ASCII path when site-packages lives under a Cyrillic user dir."""
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        pass

    cache_root = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp" / "streamcuter_cv2"
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        cached = cache_root / Path(path).name
        if not cached.exists():
            shutil.copy2(path, cached)
        return str(cached)
    except OSError:
        return path


def _extract_frames(video_path: str, num_frames: int = 10, max_time_sec: float = 300.0) -> list[Any]:
    cv2 = _OpenCV.cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        console.print("[yellow]Could not open video for frame extraction[/yellow]")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    max_frame = min(int(max_time_sec * fps), total_frames)
    if max_frame <= 0:
        max_frame = max(1, total_frames)

    frames = []
    step = max(1, max_frame // num_frames)
    for i in range(0, min(num_frames * step, max_frame), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(i, total_frames - 1))
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)

    cap.release()
    console.print(f"[dim]Extracted {len(frames)} frames for analysis[/dim]")
    return frames


def _detect_face_boxes(frames: list[Any]) -> list[tuple[int, int, int, int]]:
    mediapipe_boxes = _detect_face_boxes_mediapipe(frames)
    haar_boxes = _detect_face_boxes_haar(frames)
    if mediapipe_boxes:
        # MediaPipe is more stable for small streamer webcam panels; Haar stays
        # as an additional fallback/evidence source when it is available.
        return _dedupe_boxes(mediapipe_boxes + haar_boxes)
    return _dedupe_boxes(haar_boxes)


def _detect_face_boxes_haar(frames: list[Any]) -> list[tuple[int, int, int, int]]:
    cv2 = _OpenCV.cv2
    face_cascades = _OpenCV.face_cascades or []
    face_boxes: list[tuple[int, int, int, int]] = []

    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        for cascade in face_cascades:
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
            for (fx, fy, fw, fh) in faces:
                face_boxes.append((int(fx), int(fy), int(fw), int(fh)))

    return face_boxes


def _detect_face_boxes_mediapipe(frames: list[Any]) -> list[tuple[int, int, int, int]]:
    cv2 = _OpenCV.cv2
    try:
        import mediapipe as mp  # type: ignore
    except ImportError:
        return []

    face_boxes: list[tuple[int, int, int, int]] = []
    try:
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.35,
        ) as detector:
            for frame in frames:
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.process(rgb)
                detections = getattr(result, "detections", None) or []
                for detection in detections:
                    rel = detection.location_data.relative_bounding_box
                    x = int(rel.xmin * w)
                    y = int(rel.ymin * h)
                    bw = int(rel.width * w)
                    bh = int(rel.height * h)
                    if bw >= 20 and bh >= 20:
                        face_boxes.append(_clamp_even_roi((x, y, bw, bh), w, h))
    except Exception as e:
        console.print(f"[dim]MediaPipe face detector unavailable, using OpenCV fallback: {e}[/dim]")
        return []

    return face_boxes


def _dedupe_boxes(
    boxes: list[tuple[int, int, int, int]],
    iou_threshold: float = 0.68,
) -> list[tuple[int, int, int, int]]:
    deduped: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if any(_rect_iou(box, existing) >= iou_threshold for existing in deduped):
            continue
        deduped.append(box)
    return deduped


def _rect_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax + aw, bx + bw)
    iy2 = min(ay + ah, by + bh)
    if ix1 >= ix2 or iy1 >= iy2:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    return inter / float(max(1, aw * ah + bw * bh - inter))


def _find_stable_regions(frames: list[Any]) -> dict[tuple[int, int, int, int], float]:
    np = _OpenCV.np
    if len(frames) < 2:
        return {}

    h, w = frames[0].shape[:2]
    cell_size = 64
    stable_scores: dict[tuple[int, int, int, int], float] = {}

    for y in range(0, h - cell_size, cell_size):
        for x in range(0, w - cell_size, cell_size):
            patches = []
            for frame in frames:
                patch = frame[y : y + cell_size, x : x + cell_size]
                patches.append(patch)

            arr = np.array(patches, dtype=np.float32)
            variance = float(np.mean(np.var(arr, axis=0)))

            if variance < 500:
                stable_scores[(x, y, cell_size, cell_size)] = 1.0 - min(variance / 500, 1.0)

    return stable_scores


def detect_webcam(video_path: str, config: AppConfig | None = None) -> WebcamDetectionResult:
    if not _ensure_opencv():
        return WebcamDetectionResult(has_webcam=False)

    console.print("[cyan]Analyzing webcam presence...[/cyan]")

    frames = _extract_frames(video_path, num_frames=15)
    if len(frames) < 3:
        console.print("[yellow]Too few frames extracted, assuming no webcam[/yellow]")
        return WebcamDetectionResult(has_webcam=False)

    h, w = frames[0].shape[:2]
    if h == 0 or w == 0:
        console.print("[yellow]Invalid frame dimensions, assuming no webcam[/yellow]")
        return WebcamDetectionResult(has_webcam=False)

    manual_crop = _manual_crop_from_config(config, "manual_webcam_crop", w, h)
    if manual_crop is not None:
        rx, ry, rw, rh = manual_crop
        console.print(f"[green]Webcam manual override: ({rx},{ry}) {rw}x{rh}[/green]")
        return WebcamDetectionResult(
            has_webcam=True,
            region=WebcamRegion(x=rx, y=ry, w=rw, h=rh, confidence=1.0),
            confidence=1.0,
        )

    face_boxes = _detect_face_boxes(frames)
    stable_regions = _find_stable_regions(frames)
    edge_scores = _compute_edge_density_scores(frames)

    best_score = 0.0
    best_region = None
    best_face_count = 0

    edge_margin_ratio = float(getattr(config, "webcam_edge_margin_ratio", 0.15) or 0.15)
    webcam_candidates = _generate_webcam_candidates(w, h, edge_margin_ratio=edge_margin_ratio)

    for roi in webcam_candidates:
        rx, ry, rw, rh = roi
        score, reasons, face_count = _score_webcam_candidate(
            frames,
            roi,
            face_boxes,
            stable_regions,
            edge_scores,
            w,
            h,
            edge_margin_ratio,
        )

        if score > best_score:
            best_score = score
            best_region = roi
            best_face_count = face_count
            console.print(f"[dim]  Candidate ROI: ({rx},{ry}) {rw}x{rh}, score={score:.2f} [{', '.join(reasons)}][/dim]")

    confidence = min(best_score / 1.35, 1.0)
    has_webcam = confidence > 0.55 and best_face_count > 0

    if has_webcam and best_region is not None:
        refined_region = _refine_webcam_region(
            frames,
            best_region,
            face_boxes,
            w,
            h,
            edge_margin_ratio,
        )
        if refined_region != best_region:
            console.print(
                f"[cyan]Webcam refined: {best_region} -> {refined_region}[/cyan]"
            )
        rx, ry, rw, rh = refined_region
        console.print(f"[green]Webcam detected: ({rx},{ry}) {rw}x{rh}, confidence={confidence:.2f}[/green]")
        return WebcamDetectionResult(
            has_webcam=True,
            region=WebcamRegion(x=rx, y=ry, w=rw, h=rh, confidence=confidence),
            confidence=confidence,
        )

    console.print(f"[yellow]No webcam overlay detected (best score: {best_score:.2f})[/yellow]")
    return WebcamDetectionResult(has_webcam=False, confidence=confidence)


def _score_webcam_candidate(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    stable_regions: dict[tuple[int, int, int, int], float],
    edge_scores: Any,
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float,
) -> tuple[float, list[str], int]:
    rx, ry, rw, rh = roi
    score = 0.0
    reasons: list[str] = []

    face_count = _count_faces_in_roi(roi, face_boxes, frame_w, frame_h, edge_margin_ratio)
    if face_count > 0:
        face_score = min(0.90, 0.42 + face_count / 6.0)
        score += face_score
        reasons.append(f"faces={face_count}")
        face_position_score, face_position_reason = _face_position_score(
            roi, face_boxes, frame_w, frame_h, edge_margin_ratio
        )
        score += face_position_score
        if face_position_reason:
            reasons.append(face_position_reason)
    else:
        score -= 0.45
        reasons.append("no_face")

    side_score, side_reason = _left_right_side_score(roi, frame_w, frame_h, edge_margin_ratio)
    score += side_score
    reasons.append(side_reason)

    contrast_score = _webcam_boundary_contrast_score(frames, roi, frame_w, edge_margin_ratio)
    if contrast_score > 0:
        score += contrast_score * 0.26
        reasons.append(f"boundary_contrast={contrast_score:.2f}")

    stab_score = _get_stability_in_roi(roi, stable_regions)
    if stab_score > 0:
        score += stab_score * 0.24
        reasons.append(f"stability={stab_score:.2f}")

    edge_score = _get_edge_score_in_roi(roi, edge_scores)
    if edge_score > 0:
        score += edge_score * 0.14
        reasons.append(f"edges={edge_score:.2f}")

    area_ratio = (rw * rh) / max(1, frame_w * frame_h)
    if 0.015 <= area_ratio <= 0.22:
        score += 0.10
        reasons.append(f"size_ok(area_ratio={area_ratio:.2f})")
    else:
        score -= 0.15
        reasons.append(f"size_weak(area_ratio={area_ratio:.2f})")

    aspect = rw / max(1, rh)
    if 1.45 <= aspect <= 2.15:
        score += 0.18
        reasons.append("webcam_aspect_wide")
    elif 1.15 <= aspect < 1.45:
        score += 0.08
        reasons.append("webcam_aspect_4_3")
    elif 0.80 <= aspect < 1.15:
        score += 0.02
        reasons.append("webcam_aspect_square_ok")
    else:
        score -= 0.12
        reasons.append("webcam_aspect_weak")

    width_ratio = rw / max(1, frame_w)
    if width_ratio > 0.38:
        score -= 0.28
        reasons.append("too_wide_overlay_penalty")
    elif 0.16 <= width_ratio <= 0.32:
        score += 0.08
        reasons.append("webcam_width_ok")

    if rx == 0 or rx + rw == frame_w:
        score += 0.10
        reasons.append("side_edge_contact")

    return score, reasons, face_count


def _left_right_side_score(
    roi: tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float,
) -> tuple[float, str]:
    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.30, edge_margin_ratio))
    side_depth = frame_w * 0.34
    left_side = rx <= side_depth
    right_side = rx + rw >= frame_w - side_depth
    if left_side and right_side:
        return -0.45, "too_wide_for_side_webcam"
    if not (left_side or right_side):
        return -0.38, "not_left_or_right_side"

    score = 0.24
    reason = "left_side_scan" if left_side else "right_side_scan"
    if rx <= margin_x or rx + rw >= frame_w - margin_x:
        score += 0.10
        reason += "_near_edge"

    center_y = ry + rh / 2
    if 0 <= center_y <= frame_h:
        score += 0.04
    return score, reason


def _webcam_boundary_contrast_score(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    frame_w: int,
    edge_margin_ratio: float,
) -> float:
    cv2, np = _opencv_modules()
    if cv2 is None or np is None or not frames:
        return 0.0

    frame = frames[min(len(frames) // 2, len(frames) - 1)]
    rx, ry, rw, rh = roi
    h, w = frame.shape[:2]
    if rx < 0 or ry < 0 or rx + rw > w or ry + rh > h:
        return 0.0

    side_margin = frame_w * max(0.0, min(0.30, edge_margin_ratio))
    near_left = rx <= side_margin or rx < frame_w * 0.18
    near_right = rx + rw >= frame_w - side_margin or rx + rw > frame_w * 0.82
    band = max(6, int(min(rw, rh) * 0.06))

    inner = frame[ry : ry + rh, rx : rx + rw]
    if near_left and rx + rw + band <= w:
        outside = frame[ry : ry + rh, rx + rw : rx + rw + band]
        inside_edge = inner[:, max(0, rw - band) : rw]
    elif near_right and rx - band >= 0:
        outside = frame[ry : ry + rh, rx - band : rx]
        inside_edge = inner[:, 0 : min(band, rw)]
    else:
        return 0.0

    if outside.size == 0 or inside_edge.size == 0:
        return 0.0

    color_distance = float(
        np.linalg.norm(
            inside_edge.reshape(-1, 3).mean(axis=0)
            - outside.reshape(-1, 3).mean(axis=0)
        )
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if near_left and rx + rw < w:
        boundary_edge = float(np.mean(np.abs(gray[ry : ry + rh, rx + rw - 1].astype(np.float32) - gray[ry : ry + rh, rx + rw].astype(np.float32))))
    elif near_right and rx > 0:
        boundary_edge = float(np.mean(np.abs(gray[ry : ry + rh, rx].astype(np.float32) - gray[ry : ry + rh, rx - 1].astype(np.float32))))
    else:
        boundary_edge = 0.0

    return min(1.0, color_distance / 85.0 + boundary_edge / 120.0)


def _refine_webcam_region(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float = 0.15,
) -> tuple[int, int, int, int]:
    """Trim obvious non-webcam strips from the chosen edge overlay."""
    if not frames:
        return roi

    refined = _trim_webcam_inner_side_strip(
        frames, roi, face_boxes, frame_w, frame_h, edge_margin_ratio
    )
    refined = _trim_webcam_bottom_ui_strip(
        frames, refined, face_boxes, frame_w, frame_h, edge_margin_ratio
    )
    refined = _trim_webcam_bottom_inner_corner_intrusion(
        frames, refined, face_boxes, frame_w, frame_h, edge_margin_ratio
    )
    return _clamp_even_roi(refined, frame_w, frame_h)


def _trim_webcam_inner_side_strip(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float,
) -> tuple[int, int, int, int]:
    cv2, np = _opencv_modules()
    if cv2 is None or np is None:
        return roi

    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    if near_left == near_right or rw < 120 or rh < 80:
        return roi

    panel = _median_roi_image(frames, roi)
    if panel is None:
        return roi

    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    y1 = int(rh * 0.08)
    y2 = int(rh * 0.88)
    band = max(4, int(rw * 0.015))
    face_limit = _face_side_limit(roi, face_boxes, near_left=near_left)

    best: tuple[float, int] | None = None
    if near_left:
        start, stop = int(rw * 0.78), int(rw * 0.985)
        for boundary in range(start, max(start, stop)):
            if boundary <= face_limit + max(8, int(rw * 0.04)):
                continue
            score = _vertical_boundary_score(np, gray, hsv, panel, boundary, y1, y2, band)
            if best is None or score > best[0]:
                best = (score, boundary)
        if best is not None and best[0] >= 45.0 and best[1] <= rw - max(8, int(rw * 0.03)):
            return rx, ry, best[1], rh
        return roi

    start, stop = int(rw * 0.015), int(rw * 0.22)
    for boundary in range(start, max(start, stop)):
        if boundary >= face_limit - max(8, int(rw * 0.04)):
            continue
        score = _vertical_boundary_score(np, gray, hsv, panel, boundary, y1, y2, band)
        if best is None or score > best[0]:
            best = (score, boundary)

    if best is not None and best[0] >= 45.0 and best[1] >= max(8, int(rw * 0.03)):
        new_x = rx + best[1]
        new_w = rw - best[1]
        return new_x, ry, new_w, rh
    return roi


def _trim_webcam_bottom_ui_strip(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float,
) -> tuple[int, int, int, int]:
    cv2, np = _opencv_modules()
    if cv2 is None or np is None:
        return roi

    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    if not (near_left or near_right) or rw < 120 or rh < 80:
        return roi

    panel = _median_roi_image(frames, roi)
    if panel is None:
        return roi

    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
    x1 = int(rw * 0.08)
    x2 = int(rw * 0.92)
    band = max(6, int(rh * 0.035))
    min_bottom = _face_bottom_limit(roi, face_boxes) + max(8, int(rh * 0.04))
    min_bottom = max(min_bottom, int(rh * 0.70))

    best: tuple[float, int] | None = None
    for boundary in range(min_bottom, int(rh * 0.97)):
        above = panel[max(0, boundary - band) : boundary, x1:x2]
        below = panel[boundary : min(rh, boundary + band), x1:x2]
        if above.size == 0 or below.size == 0:
            continue

        above_mean = above.reshape(-1, 3).mean(axis=0)
        below_mean = below.reshape(-1, 3).mean(axis=0)
        color_distance = float(np.linalg.norm(above_mean - below_mean))
        if boundary > 0:
            edge = float(
                np.mean(
                    np.abs(
                        gray[boundary, x1:x2].astype(np.float32)
                        - gray[boundary - 1, x1:x2].astype(np.float32)
                    )
                )
            )
        else:
            edge = 0.0
        below_dark_bonus = max(0.0, 70.0 - float(np.mean(gray[boundary : min(rh, boundary + band), x1:x2])))
        score = color_distance + edge * 0.6 + below_dark_bonus * 0.4
        if best is None or score > best[0]:
            best = (score, boundary)

    if best is not None and best[0] >= 50.0 and best[1] <= rh - max(8, int(rh * 0.03)):
        return rx, ry, rw, best[1]
    return roi


def _trim_webcam_bottom_inner_corner_intrusion(
    frames: list[Any],
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float,
) -> tuple[int, int, int, int]:
    cv2, np = _opencv_modules()
    if cv2 is None or np is None:
        return roi

    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    if near_left == near_right or rw < 120 or rh < 80:
        return roi

    panel = _median_roi_image(frames, roi)
    if panel is None:
        return roi

    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    if near_left:
        x1, x2 = int(rw * 0.84), rw
    else:
        x1, x2 = 0, int(rw * 0.16)
    if x2 <= x1:
        return roi

    min_bottom = _face_bottom_limit(roi, face_boxes) + max(8, int(rh * 0.04))
    start = max(min_bottom, int(rh * 0.82))
    stop = max(start, int(rh * 0.995))
    row_band = max(2, int(rh * 0.01))
    history: list[float] = []

    for boundary in range(start, stop):
        band = hsv[boundary : min(rh, boundary + row_band), x1:x2]
        if band.size == 0:
            continue
        sat = band[:, :, 1]
        val = band[:, :, 2]
        high_sat_ratio = float(np.mean((sat > 90) & (val > 60)))
        previous_ratio = float(np.mean(history[-8:])) if history else 0.0
        history.append(high_sat_ratio)
        if (
            high_sat_ratio >= 0.20
            and high_sat_ratio >= previous_ratio + 0.18
            and boundary <= rh - max(3, row_band)
        ):
            return rx, ry, rw, boundary

    return roi


def _vertical_boundary_score(
    np: Any,
    gray: Any,
    hsv: Any,
    panel: Any,
    boundary: int,
    y1: int,
    y2: int,
    band: int,
) -> float:
    left = panel[y1:y2, max(0, boundary - band) : boundary]
    right = panel[y1:y2, boundary : min(panel.shape[1], boundary + band)]
    if left.size == 0 or right.size == 0:
        return 0.0

    color_distance = float(
        np.linalg.norm(left.reshape(-1, 3).mean(axis=0) - right.reshape(-1, 3).mean(axis=0))
    )
    if boundary > 0:
        edge = float(
            np.mean(
                np.abs(
                    gray[y1:y2, boundary].astype(np.float32)
                    - gray[y1:y2, boundary - 1].astype(np.float32)
                )
            )
        )
    else:
        edge = 0.0
    sat_left = float(hsv[y1:y2, max(0, boundary - band) : boundary, 1].mean())
    sat_right = float(hsv[y1:y2, boundary : min(panel.shape[1], boundary + band), 1].mean())
    return color_distance + edge * 0.7 + abs(sat_left - sat_right) * 0.2


def _face_side_limit(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    *,
    near_left: bool,
) -> int:
    rx, ry, rw, rh = roi
    matches = _matching_face_boxes(roi, face_boxes)
    if not matches:
        return int(rw * (0.35 if near_left else 0.65))
    if near_left:
        return max(fx + fw - rx for fx, _, fw, _ in matches)
    return min(fx - rx for fx, _, _, _ in matches)


def _face_bottom_limit(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
) -> int:
    rx, ry, rw, rh = roi
    matches = _matching_face_boxes(roi, face_boxes)
    if not matches:
        return int(rh * 0.45)
    return max(fy + fh - ry for _, fy, _, fh in matches)


def _matching_face_boxes(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    rx, ry, rw, rh = roi
    matches: list[tuple[int, int, int, int]] = []
    for face_x, face_y, face_w, face_h in face_boxes:
        face_area = max(1, face_w * face_h)
        ix1 = max(rx, face_x)
        iy1 = max(ry, face_y)
        ix2 = min(rx + rw, face_x + face_w)
        iy2 = min(ry + rh, face_y + face_h)
        if ix1 >= ix2 or iy1 >= iy2:
            continue
        overlap_ratio = ((ix2 - ix1) * (iy2 - iy1)) / face_area
        face_cx = face_x + face_w / 2
        face_cy = face_y + face_h / 2
        if overlap_ratio >= 0.55 and rx <= face_cx <= rx + rw and ry <= face_cy <= ry + rh:
            matches.append((face_x, face_y, face_w, face_h))
    return matches


def _median_roi_image(
    frames: list[Any],
    roi: tuple[int, int, int, int],
) -> Any | None:
    _, np = _opencv_modules()
    if np is None:
        return None
    rx, ry, rw, rh = roi
    patches = []
    for frame in frames[:8]:
        if frame is None or frame.shape[0] < ry + rh or frame.shape[1] < rx + rw:
            continue
        patch = frame[ry : ry + rh, rx : rx + rw]
        if patch.shape[:2] == (rh, rw):
            patches.append(patch)
    if not patches:
        return None
    if len(patches) == 1:
        return patches[0]
    return np.median(np.stack(patches, axis=0), axis=0).astype(np.uint8)


def _opencv_modules() -> tuple[Any | None, Any | None]:
    if _OpenCV.cv2 is not None and _OpenCV.np is not None:
        return _OpenCV.cv2, _OpenCV.np
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, None
    return cv2, np


def _manual_crop_from_config(
    config: AppConfig | None,
    field_name: str,
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    if config is None:
        return None
    raw = getattr(config, field_name, None)
    if not raw:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        console.print(f"[yellow]Ignoring invalid {field_name}; expected [x, y, w, h][/yellow]")
        return None
    try:
        x, y, w, h = (int(v) for v in raw)
    except (TypeError, ValueError):
        console.print(f"[yellow]Ignoring invalid {field_name}; crop values must be integers[/yellow]")
        return None
    return _clamp_even_roi((x, y, w, h), frame_w, frame_h)


def _clamp_even_roi(
    roi: tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int]:
    x, y, w, h = roi
    w = max(2, min(int(w), frame_w))
    h = max(2, min(int(h), frame_h))
    w -= w % 2
    h -= h % 2
    x = max(0, min(int(x), frame_w - w))
    y = max(0, min(int(y), frame_h - h))
    return x, y, w, h


def _generate_webcam_candidates(
    w: int,
    h: int,
    edge_margin_ratio: float = 0.15,
) -> list[tuple[int, int, int, int]]:
    """Generate webcam candidates across the full left/right overlay rails."""
    edge_margin_ratio = max(0.0, min(0.30, float(edge_margin_ratio)))
    margin_x = int(w * edge_margin_ratio)
    margin_y = int(h * edge_margin_ratio)

    candidates: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()

    widths = [
        int(w * r)
        for r in (0.16, 0.18, 0.20, 0.22, 0.25, 0.27, 0.30, 0.32, 0.36)
    ]
    aspects = [16 / 9, 4 / 3, 1.0]
    sizes: list[tuple[int, int]] = []
    for pw in widths:
        for aspect in aspects:
            ph = int(pw / aspect)
            if w * 0.10 <= pw <= w * 0.40 and h * 0.08 <= ph <= h * 0.45:
                sizes.append((pw, ph))

    def add(x: int, y: int, pw: int, ph: int) -> None:
        if pw <= 0 or ph <= 0 or pw >= w or ph >= h:
            return
        x = max(0, min(int(x), w - pw))
        y = max(0, min(int(y), h - ph))
        roi = (x, y, pw, ph)
        if roi not in seen:
            seen.add(roi)
            candidates.append(roi)

    for pw, ph in sizes:
        step_x = max(24, int(w * 0.035))
        step_y = max(18, int(h * 0.035))
        side_depth = max(margin_x, int(w * 0.24))
        left_x_scan = list(range(0, max(1, min(side_depth, w - pw) + 1), step_x))
        right_start = max(0, w - pw - side_depth)
        right_x_scan = list(range(right_start, max(right_start + 1, w - pw + 1), step_x))
        y_scan = list(range(0, max(1, h - ph + 1), step_y))
        if 0 not in left_x_scan:
            left_x_scan.insert(0, 0)
        if margin_x <= w - pw:
            left_x_scan.append(margin_x)
        if w - pw - margin_x >= 0:
            right_x_scan.append(w - pw - margin_x)
        right_x_scan.append(w - pw)
        if not y_scan or y_scan[-1] != h - ph:
            y_scan.append(h - ph)

        y_positions = [
            0,
            margin_y,
            (h - ph) // 2,
            h - ph - margin_y,
            h - ph,
        ]

        for y in y_scan + y_positions:
            for x in left_x_scan + right_x_scan:
                add(x, y, pw, ph)

    return candidates


def _edge_proximity_score(
    roi: tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float = 0.15,
) -> tuple[float, str]:
    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    margin_y = frame_h * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    near_top = ry <= margin_y
    near_bottom = ry + rh >= frame_h - margin_y
    edge_count = sum((near_left, near_right, near_top, near_bottom))

    if edge_count >= 2:
        return 0.25, "edge_corner"
    if edge_count == 1:
        return 0.16, "edge_inset"
    return -0.20, "interior_penalty"


def _count_faces_in_roi(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float = 0.15,
) -> int:
    return len(_matching_face_centers(roi, face_boxes, frame_w, frame_h, edge_margin_ratio))


def _face_position_score(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float = 0.15,
) -> tuple[float, str]:
    centers = _matching_face_centers(roi, face_boxes, frame_w, frame_h, edge_margin_ratio)
    if not centers:
        return 0.0, ""

    rx, ry, rw, rh = roi
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    margin_y = frame_h * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    near_top = ry <= margin_y
    near_bottom = ry + rh >= frame_h - margin_y
    rel_x = sorted((cx - rx) / max(1, rw) for cx, _ in centers)[len(centers) // 2]
    rel_y = sorted((cy - ry) / max(1, rh) for _, cy in centers)[len(centers) // 2]

    if near_left or near_right:
        if rel_y < 0.08 or rel_y > 0.92:
            return -0.18, f"face_near_panel_edge(rel_y={rel_y:.2f})"
        if 0.22 <= rel_y <= 0.82:
            return 0.16, f"face_valid_y(rel_y={rel_y:.2f})"
        return 0.04, f"face_edge_y_ok(rel_y={rel_y:.2f})"

    if near_top or near_bottom:
        if rel_x < 0.12 or rel_x > 0.88:
            return -0.22, f"face_near_panel_edge(rel_x={rel_x:.2f})"
        if 0.20 <= rel_x <= 0.80:
            return 0.12, f"face_centered_x(rel_x={rel_x:.2f})"

    return 0.0, ""


def _matching_face_centers(
    roi: tuple[int, int, int, int],
    face_boxes: list[tuple[int, int, int, int]],
    frame_w: int,
    frame_h: int,
    edge_margin_ratio: float = 0.15,
) -> list[tuple[float, float]]:
    rx, ry, rw, rh = roi
    centers: list[tuple[float, float]] = []
    margin_x = frame_w * max(0.0, min(0.25, edge_margin_ratio))
    margin_y = frame_h * max(0.0, min(0.25, edge_margin_ratio))
    near_left = rx <= margin_x
    near_right = rx + rw >= frame_w - margin_x
    near_top = ry <= margin_y
    near_bottom = ry + rh >= frame_h - margin_y

    for face_x, face_y, face_w, face_h in face_boxes:
        face_area = max(1, face_w * face_h)
        ix1 = max(rx, face_x)
        iy1 = max(ry, face_y)
        ix2 = min(rx + rw, face_x + face_w)
        iy2 = min(ry + rh, face_y + face_h)
        if ix1 >= ix2 or iy1 >= iy2:
            continue
        overlap_ratio = ((ix2 - ix1) * (iy2 - iy1)) / face_area
        face_cx = face_x + face_w / 2
        face_cy = face_y + face_h / 2
        center_inside = rx <= face_cx <= rx + rw and ry <= face_cy <= ry + rh
        if near_left and not near_right and face_cx > rx + rw * 0.90:
            continue
        if near_right and not near_left and face_cx < rx + rw * 0.10:
            continue
        if near_top and not near_bottom and not (near_left or near_right) and face_cy > ry + rh * 0.78:
            continue
        if near_bottom and not near_top and not (near_left or near_right) and face_cy < ry + rh * 0.22:
            continue
        if center_inside and overlap_ratio >= 0.55:
            centers.append((face_cx, face_cy))

    return centers


def _get_stability_in_roi(
    roi: tuple[int, int, int, int],
    stable_regions: dict[tuple[int, int, int, int], float],
) -> float:
    rx, ry, rw, rh = roi
    total = 0.0
    count = 0

    for (sx, sy, sw, sh), stab in stable_regions.items():
        if rx <= sx < rx + rw and ry <= sy < ry + rh:
            total += stab
            count += 1

    return total / max(count, 1)


def _compute_edge_density_scores(frames: list[Any]):
    cv2 = _OpenCV.cv2
    np = _OpenCV.np
    if not frames:
        ret = np.array([])
        return ret

    h, w = frames[0].shape[:2]
    cell_size = 64
    grid_h = h // cell_size
    grid_w = w // cell_size

    edge_map = np.zeros((grid_h, grid_w), dtype=np.float32)

    for frame in frames[:5]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        for gy in range(grid_h):
            for gx in range(grid_w):
                y1, y2 = gy * cell_size, (gy + 1) * cell_size
                x1, x2 = gx * cell_size, (gx + 1) * cell_size
                edge_map[gy, gx] += np.mean(edges[y1:y2, x1:x2])

    max_val = np.max(edge_map)
    if max_val > 0:
        edge_map /= max_val

    return edge_map


def _get_edge_score_in_roi(
    roi: tuple[int, int, int, int],
    edge_map,
) -> float:
    _, np = _opencv_modules()
    if np is None:
        return 0.0
    if edge_map.size == 0:
        return 0.0

    rx, ry, rw, rh = roi
    cell_size = 64
    h_cells, w_cells = edge_map.shape

    cells = []
    for gy in range(h_cells):
        for gx in range(w_cells):
            cx = gx * cell_size
            cy = gy * cell_size
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                cells.append(edge_map[gy, gx])

    if not cells:
        return 0.0

    mean_edge = float(np.mean(cells))
    std_edge = float(np.std(cells))

    return float(std_edge / max(mean_edge, 0.01)) if mean_edge > 0 else 0.0
