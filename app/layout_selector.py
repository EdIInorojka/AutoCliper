"""Small Tkinter preview UI for manual layout crop selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import AppConfig
from app.probe import VideoInfo
from app.utils.console import get_console

console = get_console()

Crop = tuple[int, int, int, int]


@dataclass
class LayoutSelection:
    webcam_crop: Optional[Crop]
    slot_crop: Optional[Crop]
    source_size: tuple[int, int]
    preview_time_sec: float


def select_layout_crops(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
) -> Optional[LayoutSelection]:
    """
    Open a minimal preview window and return selected webcam/slot crops.

    The preview frame is taken from the middle of the video because stream
    layouts are usually settled there, after intros and loading screens.
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Layout preview needs tkinter, Pillow and OpenCV. "
            "Install dependencies with pip install -r requirements.txt."
        ) from exc

    frame_bgr, preview_time_sec = _read_middle_frame(cv2, video_path, video_info)
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    source_h, source_w = frame_rgb.shape[:2]

    root = tk.Tk()
    root.title("StreamCuter layout preview")

    screen_w = max(800, int(root.winfo_screenwidth() * 0.92))
    screen_h = max(520, int(root.winfo_screenheight() * 0.82))
    max_image_h = max(360, screen_h - 90)
    scale = min(screen_w / source_w, max_image_h / source_h, 1.0)
    display_w = max(2, int(source_w * scale))
    display_h = max(2, int(source_h * scale))

    image = Image.fromarray(frame_rgb)
    if (display_w, display_h) != (source_w, source_h):
        image = image.resize((display_w, display_h), Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(image)

    state = {
        "mode": "webcam",
        "webcam": None,
        "slot": None,
        "drag_start": None,
        "drag_rect": None,
        "result": None,
    }

    toolbar = tk.Frame(root)
    toolbar.pack(fill=tk.X, padx=8, pady=6)

    canvas = tk.Canvas(root, width=display_w, height=display_h, highlightthickness=0, cursor="crosshair")
    canvas.pack(padx=8, pady=(0, 8))
    canvas.create_image(0, 0, anchor=tk.NW, image=photo)

    status = tk.StringVar(value="Select webcam, drag on the frame, then Apply.")
    status_label = tk.Label(root, textvariable=status, anchor="w")
    status_label.pack(fill=tk.X, padx=8, pady=(0, 8))

    def set_mode(mode: str) -> None:
        state["mode"] = mode
        label = "webcam" if mode == "webcam" else "slot"
        status.set(f"Select {label}: drag a rectangle on the stream frame.")

    def current_color() -> str:
        return "#00d15d" if state["mode"] == "webcam" else "#ff4d5f"

    def clamp_display(x: int, y: int) -> tuple[int, int]:
        return max(0, min(display_w, x)), max(0, min(display_h, y))

    def display_to_source(rect: tuple[int, int, int, int]) -> Crop:
        x1, y1, x2, y2 = rect
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        x = int(round(x1 / scale))
        y = int(round(y1 / scale))
        w = int(round((x2 - x1) / scale))
        h = int(round((y2 - y1) / scale))
        return _clamp_even_crop(x, y, w, h, source_w, source_h)

    def source_to_display(crop: Crop) -> tuple[int, int, int, int]:
        x, y, w, h = crop
        return (
            int(round(x * scale)),
            int(round(y * scale)),
            int(round((x + w) * scale)),
            int(round((y + h) * scale)),
        )

    def redraw() -> None:
        canvas.delete("selection")
        if state["slot"] is not None:
            canvas.create_rectangle(*source_to_display(state["slot"]), outline="#ff4d5f", width=3, tags="selection")
        if state["webcam"] is not None:
            canvas.create_rectangle(*source_to_display(state["webcam"]), outline="#00d15d", width=3, tags="selection")
        if state["drag_rect"] is not None:
            canvas.create_rectangle(*state["drag_rect"], outline=current_color(), width=2, dash=(8, 4), tags="selection")

    def on_press(event) -> None:
        x, y = clamp_display(event.x, event.y)
        state["drag_start"] = (x, y)
        state["drag_rect"] = (x, y, x, y)
        redraw()

    def on_drag(event) -> None:
        if state["drag_start"] is None:
            return
        x0, y0 = state["drag_start"]
        x1, y1 = clamp_display(event.x, event.y)
        state["drag_rect"] = (x0, y0, x1, y1)
        redraw()

    def on_release(event) -> None:
        if state["drag_start"] is None:
            return
        x0, y0 = state["drag_start"]
        x1, y1 = clamp_display(event.x, event.y)
        state["drag_start"] = None
        state["drag_rect"] = None
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            redraw()
            return
        crop = display_to_source((x0, y0, x1, y1))
        if state["mode"] == "webcam":
            state["webcam"] = crop
            status.set(f"Webcam selected: {crop}. You can select slot or Apply.")
        else:
            state["slot"] = crop
            status.set(f"Slot selected: {crop}. You can select webcam or Apply.")
        redraw()

    def on_apply() -> None:
        if state["webcam"] is None and state["slot"] is None:
            status.set("Select webcam or slot first.")
            return
        state["result"] = LayoutSelection(
            webcam_crop=state["webcam"],
            slot_crop=state["slot"],
            source_size=(source_w, source_h),
            preview_time_sec=preview_time_sec,
        )
        root.destroy()

    tk.Button(toolbar, text="Select webcam", command=lambda: set_mode("webcam"), width=18).pack(side=tk.LEFT, padx=(0, 6))
    tk.Button(toolbar, text="Select slot", command=lambda: set_mode("slot"), width=18).pack(side=tk.LEFT, padx=(0, 6))
    tk.Button(toolbar, text="Apply", command=on_apply, width=14).pack(side=tk.RIGHT)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    return state["result"]


def apply_layout_selection(config: AppConfig, selection: LayoutSelection) -> str:
    """
    Apply preview crops to config.

    If only one area is selected, it becomes the single no-webcam content crop:
    centered vertical composition, blurred sides, and top-safe subtitles.
    """
    has_webcam = selection.webcam_crop is not None
    has_slot = selection.slot_crop is not None

    if has_webcam and has_slot:
        config.manual_webcam_crop = list(selection.webcam_crop or ())
        config.manual_slot_crop = list(selection.slot_crop or ())
        config.webcam_detection = "auto"
        return "manual_split"

    crop = selection.slot_crop or selection.webcam_crop
    if crop is None:
        return "none"

    config.manual_webcam_crop = None
    config.manual_slot_crop = list(crop)
    config.webcam_detection = "off"
    config.subtitles_position = "slot_top"
    return "single_crop_no_webcam"


def save_layout_selection(
    config: AppConfig,
    selection: LayoutSelection,
    mode: str,
) -> Optional[Path]:
    out_name = config.layout_preview_save_path or "layout_selection.json"
    out_path = Path(out_name)
    if not out_path.is_absolute():
        out_path = Path(config.output_dir) / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "source_size": list(selection.source_size),
        "preview_time_sec": selection.preview_time_sec,
        "manual_webcam_crop": list(selection.webcam_crop) if selection.webcam_crop else None,
        "manual_slot_crop": list(selection.slot_crop) if selection.slot_crop else None,
        "effective_manual_webcam_crop": config.manual_webcam_crop,
        "effective_manual_slot_crop": config.manual_slot_crop,
        "webcam_detection": config.webcam_detection,
        "subtitles_position": config.subtitles_position,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _read_middle_frame(cv2, video_path: str, video_info: VideoInfo):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for layout preview: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or video_info.fps or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames > 0:
        target_frame = max(0, min(total_frames - 1, total_frames // 2))
        preview_time_sec = target_frame / max(fps, 1.0)
    else:
        preview_time_sec = max(0.0, float(video_info.duration_sec) * 0.5)
        target_frame = int(preview_time_sec * max(fps, 1.0))

    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.set(cv2.CAP_PROP_POS_MSEC, preview_time_sec * 1000.0)
        ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        raise RuntimeError("Could not read middle frame for layout preview.")
    return frame, preview_time_sec


def _clamp_even_crop(
    x: int,
    y: int,
    w: int,
    h: int,
    src_w: int,
    src_h: int,
) -> Crop:
    w = max(2, min(int(w), src_w))
    h = max(2, min(int(h), src_h))
    w -= w % 2
    h -= h % 2
    x = max(0, min(int(x), src_w - w))
    y = max(0, min(int(y), src_h - h))
    return x, y, w, h
