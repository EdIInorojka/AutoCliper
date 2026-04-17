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

THEME = {
    "bg": "#111827",
    "panel": "#172033",
    "panel_2": "#0b1220",
    "text": "#f8fafc",
    "muted": "#94a3b8",
    "webcam": "#22c55e",
    "webcam_active": "#16a34a",
    "slot": "#fb5068",
    "slot_active": "#e11d48",
    "cinema": "#38bdf8",
    "cinema_active": "#0284c7",
    "apply": "#facc15",
    "apply_active": "#eab308",
    "apply_text": "#111827",
    "line": "#334155",
}


@dataclass
class LayoutSelection:
    webcam_crop: Optional[Crop]
    slot_crop: Optional[Crop]
    source_size: tuple[int, int]
    preview_time_sec: float
    cinema_crop: Optional[Crop] = None
    apply_mode: str = "auto"


def select_layout_crops(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
    auto_webcam_result=None,
    auto_content_result=None,
) -> Optional[LayoutSelection]:
    """
    Open a minimal preview window and return selected webcam/slot crops.

    The preview starts at the configured time, or at the middle of the video
    because stream layouts are usually settled there after intros/loading.
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

    preview_time_sec = _initial_preview_time(video_info, config)
    frame_bgr, preview_time_sec = _read_frame_at_time(cv2, video_path, video_info, preview_time_sec)
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    source_h, source_w = frame_rgb.shape[:2]

    root = tk.Tk()
    root.title("StreamCuter Layout Preview")
    root.configure(bg=THEME["bg"])

    screen_w = max(800, int(root.winfo_screenwidth() * 0.92))
    screen_h = max(520, int(root.winfo_screenheight() * 0.82))
    max_image_h = max(360, screen_h - 130)
    scale = min(screen_w / source_w, max_image_h / source_h, 1.0)
    display_w = max(2, int(source_w * scale))
    display_h = max(2, int(source_h * scale))

    image = Image.fromarray(frame_rgb)
    if (display_w, display_h) != (source_w, source_h):
        image = image.resize((display_w, display_h), Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(image)
    duration_sec = max(0.1, float(video_info.duration_sec or 0.0))

    state = {
        "mode": "webcam",
        "webcam": _crop_from_webcam_result(auto_webcam_result),
        "slot": _crop_from_content_result(auto_content_result),
        "cinema": _manual_crop_from_config(config, "manual_cinema_crop", source_w, source_h),
        "apply_mode": "auto",
        "drag_start": None,
        "drag_rect": None,
        "drag_kind": None,
        "drag_offset": None,
        "result": None,
        "photo": photo,
        "preview_time_sec": preview_time_sec,
    }

    shell = tk.Frame(root, bg=THEME["bg"])
    shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

    header = tk.Frame(shell, bg=THEME["bg"])
    header.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        header,
        text="StreamCuter Layout Preview",
        bg=THEME["bg"],
        fg=THEME["text"],
        font=("Segoe UI", 16, "bold"),
        anchor="w",
    ).pack(side=tk.LEFT)
    mode_badge = tk.Label(
        header,
        text="WEBCAM",
        bg=THEME["webcam"],
        fg=THEME["panel_2"],
        font=("Segoe UI", 10, "bold"),
        padx=12,
        pady=4,
    )
    mode_badge.pack(side=tk.RIGHT)

    toolbar = tk.Frame(shell, bg=THEME["panel"])
    toolbar.pack(fill=tk.X, pady=(0, 8))

    canvas_shell = tk.Frame(shell, bg=THEME["line"], padx=2, pady=2)
    canvas_shell.pack(pady=(0, 8))
    canvas = tk.Canvas(
        canvas_shell,
        width=display_w,
        height=display_h,
        bg=THEME["panel_2"],
        highlightthickness=0,
        cursor="crosshair",
    )
    canvas.pack()
    image_item = canvas.create_image(0, 0, anchor=tk.NW, image=state["photo"])

    time_bar = tk.Frame(shell, bg=THEME["panel"])
    time_bar.pack(fill=tk.X, pady=(0, 8))
    time_label = tk.StringVar(
        value=f"Preview frame: {_fmt_timestamp(preview_time_sec)} / {_fmt_timestamp(duration_sec)}"
    )
    tk.Label(
        time_bar,
        textvariable=time_label,
        width=26,
        anchor="w",
        bg=THEME["panel"],
        fg=THEME["text"],
        font=("Segoe UI", 10, "bold"),
        padx=10,
    ).pack(side=tk.LEFT)
    time_scale = tk.Scale(
        time_bar,
        from_=0,
        to=duration_sec,
        orient=tk.HORIZONTAL,
        showvalue=False,
        resolution=0.5 if duration_sec <= 180 else 1.0,
        bg=THEME["panel"],
        fg=THEME["text"],
        activebackground=THEME["apply"],
        troughcolor=THEME["line"],
        highlightthickness=0,
        bd=0,
    )
    time_scale.set(preview_time_sec)
    time_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

    if state["webcam"] is not None or state["slot"] is not None:
        status_text = "Auto boxes are preselected. Fix them by dragging, or Apply."
    else:
        status_text = "Select webcam, drag on the frame, then Apply."
    status = tk.StringVar(value=status_text)
    status_label = tk.Label(
        shell,
        textvariable=status,
        anchor="w",
        bg=THEME["panel"],
        fg=THEME["muted"],
        font=("Segoe UI", 10),
        padx=12,
        pady=8,
    )
    status_label.pack(fill=tk.X)

    buttons: dict[str, object] = {}

    def styled_button(parent, text: str, bg: str, active_bg: str, command, width: int):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=bg,
            fg=THEME["panel_2"],
            activebackground=active_bg,
            activeforeground=THEME["panel_2"],
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )

    def refresh_button_styles() -> None:
        webcam_button = buttons.get("webcam")
        slot_button = buttons.get("slot")
        cinema_button = buttons.get("cinema_apply")
        if webcam_button is not None:
            webcam_button.configure(
                bg=THEME["webcam_active"] if state["mode"] == "webcam" else THEME["webcam"],
                fg=THEME["text"] if state["mode"] == "webcam" else THEME["panel_2"],
            )
        if slot_button is not None:
            slot_button.configure(
                bg=THEME["slot_active"] if state["mode"] == "slot" else THEME["slot"],
                fg=THEME["text"] if state["mode"] == "slot" else THEME["panel_2"],
            )
        if cinema_button is not None:
            cinema_button.configure(
                bg=THEME["cinema_active"] if state["mode"] == "cinema" else THEME["cinema"],
                fg=THEME["text"],
            )

    def set_mode(mode: str) -> None:
        state["mode"] = mode
        if mode != "cinema":
            state["apply_mode"] = "auto"
        label = "webcam" if mode == "webcam" else "slot" if mode == "slot" else "cinema"
        mode_badge.configure(
            text=label.upper(),
            bg=THEME["webcam"] if mode == "webcam" else THEME["slot"] if mode == "slot" else THEME["cinema"],
        )
        refresh_button_styles()
        if mode == "cinema":
            status.set("Cinema frame: drag to draw a focus box, or drag inside it to move.")
        else:
            status.set(f"Select {label}: drag a rectangle on the stream frame.")

    def update_time_label(value: float | None = None) -> None:
        shown = state["preview_time_sec"] if value is None else float(value)
        time_label.set(f"Preview frame: {_fmt_timestamp(shown)} / {_fmt_timestamp(duration_sec)}")

    def update_preview_frame(target_time_sec: float, clear_selection: bool = True) -> None:
        frame, actual_time = _read_frame_at_time(cv2, video_path, video_info, target_time_sec)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        next_image = Image.fromarray(rgb)
        if (display_w, display_h) != (source_w, source_h):
            next_image = next_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
        state["photo"] = ImageTk.PhotoImage(next_image)
        state["preview_time_sec"] = actual_time
        canvas.itemconfigure(image_item, image=state["photo"])
        time_scale.set(actual_time)
        update_time_label(actual_time)
        if clear_selection:
            if getattr(config, "layout_preview_autofill", True):
                state["webcam"] = _crop_from_webcam_result(auto_webcam_result)
                state["slot"] = _crop_from_content_result(auto_content_result)
            else:
                state["webcam"] = None
                state["slot"] = None
            state["cinema"] = _manual_crop_from_config(config, "manual_cinema_crop", source_w, source_h)
            state["drag_start"] = None
            state["drag_rect"] = None
            state["drag_kind"] = None
            state["drag_offset"] = None
            if state["webcam"] is not None or state["slot"] is not None:
                status.set(
                    f"Frame changed to {_fmt_timestamp(actual_time)}. "
                    "Auto boxes reapplied; fix them if needed."
                )
            else:
                status.set(
                    f"Frame changed to {_fmt_timestamp(actual_time)}. "
                    "Selections cleared; mark webcam or slot on this frame."
                )
        redraw()

    def on_time_preview(value: str) -> None:
        update_time_label(float(value))

    def on_time_release(_event) -> None:
        try:
            update_preview_frame(float(time_scale.get()), clear_selection=True)
        except RuntimeError as exc:
            status.set(str(exc))

    def current_color() -> str:
        if state["mode"] == "webcam":
            return THEME["webcam"]
        if state["mode"] == "slot":
            return THEME["slot"]
        return THEME["cinema"]

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
            canvas.create_rectangle(*source_to_display(state["slot"]), outline=THEME["slot"], width=4, tags="selection")
        if state["webcam"] is not None:
            canvas.create_rectangle(*source_to_display(state["webcam"]), outline=THEME["webcam"], width=4, tags="selection")
        if state["cinema"] is not None:
            canvas.create_rectangle(*source_to_display(state["cinema"]), outline=THEME["cinema"], width=4, tags="selection")
        if state["drag_rect"] is not None:
            canvas.create_rectangle(*state["drag_rect"], outline=current_color(), width=3, dash=(8, 4), tags="selection")

    def on_press(event) -> None:
        x, y = clamp_display(event.x, event.y)
        if state["mode"] == "cinema" and state["cinema"] is not None:
            cx1, cy1, cx2, cy2 = source_to_display(state["cinema"])
            if cx1 <= x <= cx2 and cy1 <= y <= cy2:
                state["drag_kind"] = "move"
                state["drag_offset"] = (x - cx1, y - cy1)
                state["drag_start"] = (cx1, cy1)
                state["drag_rect"] = (cx1, cy1, cx2, cy2)
                redraw()
                return
        state["drag_kind"] = "draw"
        state["drag_offset"] = None
        state["drag_start"] = (x, y)
        state["drag_rect"] = (x, y, x, y)
        redraw()

    def on_drag(event) -> None:
        if state["drag_start"] is None:
            return
        x1, y1 = clamp_display(event.x, event.y)
        if state["drag_kind"] == "move" and state["drag_rect"] is not None and state["drag_offset"] is not None:
            rect_w = state["drag_rect"][2] - state["drag_rect"][0]
            rect_h = state["drag_rect"][3] - state["drag_rect"][1]
            offset_x, offset_y = state["drag_offset"]
            nx1 = max(0, min(display_w - rect_w, x1 - offset_x))
            ny1 = max(0, min(display_h - rect_h, y1 - offset_y))
            state["drag_rect"] = (nx1, ny1, nx1 + rect_w, ny1 + rect_h)
        else:
            x0, y0 = state["drag_start"]
            state["drag_rect"] = (x0, y0, x1, y1)
        redraw()

    def on_release(event) -> None:
        if state["drag_start"] is None:
            return
        x0, y0 = state["drag_start"]
        x1, y1 = clamp_display(event.x, event.y)
        drag_kind = state["drag_kind"]
        drag_rect = state["drag_rect"]
        state["drag_start"] = None
        state["drag_rect"] = None
        state["drag_kind"] = None
        state["drag_offset"] = None
        if drag_rect is None:
            redraw()
            return
        if drag_kind == "move":
            crop = display_to_source(drag_rect)
            state["cinema"] = crop
            status.set(f"Cinema frame moved: {crop}. You can keep webcam or apply cinema.")
            redraw()
            return
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            redraw()
            return
        crop = display_to_source((x0, y0, x1, y1))
        if state["mode"] == "webcam":
            state["webcam"] = crop
            status.set(f"Webcam selected: {crop}. You can select slot or Apply.")
        elif state["mode"] == "cinema":
            state["cinema"] = crop
            status.set(f"Cinema frame selected: {crop}. You can keep webcam or apply cinema.")
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
            cinema_crop=state["cinema"],
            source_size=(source_w, source_h),
            preview_time_sec=state["preview_time_sec"],
            apply_mode="auto",
        )
        root.destroy()

    def on_apply_slot_only() -> None:
        crop = state["slot"] or state["webcam"]
        if crop is None:
            status.set("Select slot first, then apply slot-only mode.")
            return
        state["apply_mode"] = "slot_only"
        state["result"] = LayoutSelection(
            webcam_crop=None,
            slot_crop=crop,
            cinema_crop=None,
            source_size=(source_w, source_h),
            preview_time_sec=state["preview_time_sec"],
            apply_mode="slot_only",
        )
        root.destroy()

    def on_apply_cinema() -> None:
        if state["cinema"] is None:
            seed_crop = state["slot"] or state["webcam"]
            state["slot"] = None
            state["cinema"] = _default_cinema_crop(source_w, source_h, seed_crop)
            state["mode"] = "cinema"
            state["apply_mode"] = "cinema"
            mode_badge.configure(text="CINEMA", bg=THEME["cinema"])
            refresh_button_styles()
            status.set(
                "Cinema frame created. Drag inside it to move, or drag a new cinema box. "
                "Webcam is optional; apply cinema again when ready."
            )
            redraw()
            return
        state["apply_mode"] = "cinema"
        state["result"] = LayoutSelection(
            webcam_crop=state["webcam"],
            slot_crop=None,
            cinema_crop=state["cinema"],
            source_size=(source_w, source_h),
            preview_time_sec=state["preview_time_sec"],
            apply_mode="cinema",
        )
        root.destroy()

    webcam_button = styled_button(
        toolbar,
        "Select webcam",
        THEME["webcam"],
        THEME["webcam_active"],
        lambda: set_mode("webcam"),
        18,
    )
    webcam_button.pack(side=tk.LEFT, padx=(8, 6), pady=8)
    slot_button = styled_button(
        toolbar,
        "Select slot",
        THEME["slot"],
        THEME["slot_active"],
        lambda: set_mode("slot"),
        18,
    )
    slot_button.pack(side=tk.LEFT, padx=(0, 6), pady=8)
    apply_button = styled_button(
        toolbar,
        "Apply",
        THEME["apply"],
        THEME["apply_active"],
        on_apply,
        14,
    )
    apply_button.configure(fg=THEME["apply_text"], activeforeground=THEME["apply_text"])
    apply_button.pack(side=tk.RIGHT, padx=(6, 8), pady=8)
    slot_only_button = styled_button(
        toolbar,
        "Apply slot only",
        THEME["slot"],
        THEME["slot_active"],
        on_apply_slot_only,
        18,
    )
    slot_only_button.configure(fg=THEME["text"], activeforeground=THEME["text"])
    slot_only_button.pack(side=tk.RIGHT, padx=(0, 6), pady=8)
    cinema_button = styled_button(
        toolbar,
        "Apply cinema",
        THEME["cinema"],
        THEME["cinema_active"],
        on_apply_cinema,
        16,
    )
    cinema_button.configure(fg=THEME["text"], activeforeground=THEME["text"])
    cinema_button.pack(side=tk.RIGHT, padx=(0, 6), pady=8)
    buttons.update({"webcam": webcam_button, "slot": slot_button, "cinema_apply": cinema_button})
    if str(getattr(config, "layout_mode", "auto") or "auto").lower() == "cinema" and state["cinema"] is not None:
        set_mode("cinema")
    else:
        refresh_button_styles()
    time_scale.configure(command=on_time_preview)
    redraw()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    time_scale.bind("<ButtonRelease-1>", on_time_release)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    return state["result"]


def apply_layout_selection(config: AppConfig, selection: LayoutSelection) -> str:
    """
    Apply preview crops to config.

    If only one area is selected, it becomes the single no-webcam content crop:
    centered vertical composition, blurred sides, and top-safe subtitles.
    """
    apply_mode = str(getattr(selection, "apply_mode", "auto") or "auto")
    has_webcam = selection.webcam_crop is not None
    has_slot = selection.slot_crop is not None

    if apply_mode == "slot_only":
        crop = selection.slot_crop or selection.webcam_crop
        if crop is None:
            return "none"
        config.layout_mode = "slot_only"
        config.manual_webcam_crop = None
        config.manual_slot_crop = list(crop)
        config.manual_cinema_crop = None
        config.webcam_detection = "off"
        config.subtitles_position = "slot_top"
        return "slot_only_no_webcam"

    if apply_mode == "cinema":
        crop = selection.cinema_crop or selection.slot_crop or selection.webcam_crop
        config.layout_mode = "cinema"
        config.manual_webcam_crop = list(selection.webcam_crop) if selection.webcam_crop is not None else None
        config.manual_slot_crop = None
        config.manual_cinema_crop = list(crop) if crop is not None else None
        config.webcam_detection = "auto" if selection.webcam_crop is not None else "off"
        config.subtitles_position = (
            "between_webcam_and_game" if selection.webcam_crop is not None else "slot_top"
        )
        return "cinema_with_webcam" if selection.webcam_crop is not None else "cinema_no_webcam"

    if has_webcam and has_slot:
        config.layout_mode = "auto"
        config.manual_webcam_crop = list(selection.webcam_crop or ())
        config.manual_slot_crop = list(selection.slot_crop or ())
        config.manual_cinema_crop = None
        config.webcam_detection = "auto"
        if config.subtitles_position == "slot_top":
            config.subtitles_position = "between_webcam_and_game"
        return "manual_split"

    crop = selection.slot_crop or selection.webcam_crop
    if crop is None:
        return "none"

    config.layout_mode = "auto"
    config.manual_webcam_crop = None
    config.manual_slot_crop = list(crop)
    config.manual_cinema_crop = None
    config.webcam_detection = "off"
    config.subtitles_position = "slot_top"
    return "single_crop_no_webcam"


def save_layout_selection(
    config: AppConfig,
    selection: LayoutSelection,
    mode: str,
    video_path: str = "",
) -> Optional[Path]:
    out_name = config.layout_preview_save_path or "layout_selection.json"
    out_path = Path(out_name)
    if not out_path.is_absolute():
        out_path = Path(config.output_dir) / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "apply_mode": selection.apply_mode,
        "source_size": list(selection.source_size),
        "preview_time_sec": selection.preview_time_sec,
        "manual_webcam_crop": list(selection.webcam_crop) if selection.webcam_crop else None,
        "manual_slot_crop": list(selection.slot_crop) if selection.slot_crop else None,
        "manual_cinema_crop": list(selection.cinema_crop) if selection.cinema_crop else None,
        "effective_manual_webcam_crop": config.manual_webcam_crop,
        "effective_manual_slot_crop": config.manual_slot_crop,
        "effective_manual_cinema_crop": config.manual_cinema_crop,
        "effective_layout_mode": config.layout_mode,
        "webcam_detection": config.webcam_detection,
        "subtitles_position": config.subtitles_position,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        from app.layout_dataset import append_layout_annotation

        dataset_path = append_layout_annotation(
            config,
            mode=mode,
            source_size=selection.source_size,
            preview_time_sec=selection.preview_time_sec,
            webcam_crop=selection.webcam_crop,
            slot_crop=selection.slot_crop,
            video_path=video_path,
        )
        if dataset_path is not None:
            console.print(f"[dim]Layout annotation saved: {dataset_path}[/dim]")
    except Exception as exc:
        console.print(f"[yellow]Could not append layout annotation: {exc}[/yellow]")
    return out_path


def _crop_from_webcam_result(result) -> Optional[Crop]:
    if result is None or not getattr(result, "has_webcam", False):
        return None
    region = getattr(result, "region", None)
    if region is None:
        return None
    return int(region.x), int(region.y), int(region.w), int(region.h)


def _crop_from_content_result(result) -> Optional[Crop]:
    if result is None or not getattr(result, "has_content", False):
        return None
    crop = getattr(result, "crop", None)
    if not crop:
        return None
    x, y, w, h = crop
    return int(x), int(y), int(w), int(h)


def _manual_crop_from_config(config: AppConfig, field_name: str, src_w: int, src_h: int) -> Optional[Crop]:
    raw = getattr(config, field_name, None)
    if not raw or not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x, y, w, h = (int(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return _clamp_even_crop(x, y, w, h, src_w, src_h)


def _default_cinema_crop(src_w: int, src_h: int, seed_crop: Optional[Crop]) -> Crop:
    if seed_crop is not None:
        sx, sy, sw, sh = seed_crop
        cx = sx + sw / 2.0
        cy = sy + sh / 2.0
        grow = 1.12
        target_w = int(round(sw * grow))
        target_h = int(round(sh * grow))
        target_x = int(round(cx - target_w / 2.0))
        target_y = int(round(cy - target_h / 2.0))
        return _clamp_even_crop(target_x, target_y, target_w, target_h, src_w, src_h)
    crop_w = max(2, int(round(src_w * 0.72)))
    crop_h = max(2, int(round(src_h * 0.72)))
    crop_x = max(0, (src_w - crop_w) // 2)
    crop_y = max(0, (src_h - crop_h) // 2)
    return _clamp_even_crop(crop_x, crop_y, crop_w, crop_h, src_w, src_h)


def _initial_preview_time(video_info: VideoInfo, config: AppConfig) -> float:
    duration = max(0.0, float(video_info.duration_sec or 0.0))
    if config.layout_preview_time_sec is not None:
        return max(0.0, min(duration, float(config.layout_preview_time_sec)))
    return duration * 0.5


def _read_frame_at_time(cv2, video_path: str, video_info: VideoInfo, time_sec: float):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for layout preview: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or video_info.fps or 30.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = max(0.0, float(video_info.duration_sec or 0.0))
    preview_time_sec = max(0.0, min(duration_sec, float(time_sec)))
    if total_frames > 0:
        target_frame = max(0, min(total_frames - 1, int(round(preview_time_sec * max(fps, 1.0)))))
        preview_time_sec = target_frame / max(fps, 1.0)
    else:
        target_frame = int(preview_time_sec * max(fps, 1.0))

    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.set(cv2.CAP_PROP_POS_MSEC, preview_time_sec * 1000.0)
        ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame at {_fmt_timestamp(preview_time_sec)} for layout preview.")
    return frame, preview_time_sec


def _fmt_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


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
