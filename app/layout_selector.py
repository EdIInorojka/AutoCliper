"""Small Tkinter preview UI for manual layout crop selection."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.banner_ads import banner_time_for_preview, load_banner_preview_rgba, pick_banner_asset
from app.config import AppConfig
from app.layout import compute_layout
from app.probe import VideoInfo
from app.utils.console import get_console
from app.webcam_types import WebcamDetectionResult, WebcamRegion

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
    "banner": "#f59e0b",
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
    banner_box: Optional[Crop] = None
    banner_start_sec: Optional[float] = None
    apply_mode: str = "auto"


def select_layout_crops(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
    auto_webcam_result=None,
    auto_content_result=None,
) -> Optional[LayoutSelection]:
    """
    Open a preview window and return selected webcam / slot / cinema crops.

    First screen is layout-only and exposes just two user modes:
    `slot_only` and `cinema`. When cinema + banner are enabled, Apply opens a
    second vertical banner editor window.
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

    _restore_saved_banner_state(config)

    preview_time_sec = _initial_preview_time(video_info, config)
    frame_bgr, preview_time_sec = _read_frame_at_time(cv2, video_path, video_info, preview_time_sec)
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    source_h, source_w = frame_rgb.shape[:2]
    out_w = int(getattr(getattr(config, "export", None), "width", 1080) or 1080)
    out_h = int(getattr(getattr(config, "export", None), "height", 1920) or 1920)

    root = tk.Tk()
    root.title("StreamCuter Layout Preview")
    root.configure(bg=THEME["bg"])

    screen_w = max(800, int(root.winfo_screenwidth() * 0.90))
    screen_h = max(520, int(root.winfo_screenheight() * 0.82))
    max_image_h = max(360, screen_h - 150)
    scale = min(screen_w / source_w, max_image_h / source_h, 1.0)
    display_w = max(2, int(source_w * scale))
    display_h = max(2, int(source_h * scale))

    full_image = Image.fromarray(frame_rgb)
    image = full_image.copy()
    if (display_w, display_h) != (source_w, source_h):
        image = image.resize((display_w, display_h), Image.Resampling.LANCZOS)
    photo = ImageTk.PhotoImage(image)
    duration_sec = max(0.1, float(video_info.duration_sec or 0.0))

    default_choice = "cinema" if str(getattr(config, "layout_mode", "auto") or "auto").lower() == "cinema" else "slot_only"
    state = {
        "layout_choice": default_choice,
        "mode": "cinema" if default_choice == "cinema" else "slot",
        "webcam": _manual_crop_from_config(config, "manual_webcam_crop", source_w, source_h)
        or _crop_from_webcam_result(auto_webcam_result),
        "slot": _manual_crop_from_config(config, "manual_slot_crop", source_w, source_h)
        or _crop_from_content_result(auto_content_result),
        "cinema": _manual_crop_from_config(config, "manual_cinema_crop", source_w, source_h),
        "drag_start": None,
        "drag_rect": None,
        "drag_kind": None,
        "drag_offset": None,
        "result": None,
        "photo": photo,
        "full_image": full_image,
        "preview_time_sec": preview_time_sec,
    }

    if state["cinema"] is None:
        seed_crop = state["slot"] or state["webcam"]
        state["cinema"] = _default_cinema_crop(source_w, source_h, seed_crop)

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
        text="CINEMA" if state["layout_choice"] == "cinema" else "SLOT",
        bg=THEME["cinema"] if state["layout_choice"] == "cinema" else THEME["slot"],
        fg=THEME["panel_2"],
        font=("Segoe UI", 10, "bold"),
        padx=12,
        pady=4,
    )
    mode_badge.pack(side=tk.RIGHT)

    toolbar = tk.Frame(shell, bg=THEME["panel"])
    toolbar.pack(fill=tk.X, pady=(0, 8))

    canvas_shell = tk.Frame(shell, bg=THEME["line"], padx=2, pady=2)
    canvas_shell.pack()
    tk.Label(
        shell,
        text="Source frame",
        bg=THEME["bg"],
        fg=THEME["muted"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(0, 6))
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
    time_bar.pack(fill=tk.X, pady=(8, 8))
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

    status = tk.StringVar(value=_status_for_choice(state["layout_choice"]))
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

    def active_target_key() -> str:
        if state["mode"] == "webcam":
            return "webcam"
        if state["layout_choice"] == "cinema":
            return "cinema"
        return "slot"

    def refresh_button_styles() -> None:
        slot_button = buttons["layout_slot"]
        cinema_button = buttons["layout_cinema"]
        target_button = buttons["target"]
        webcam_button = buttons["webcam"]

        slot_button.configure(
            bg=THEME["slot_active"] if state["layout_choice"] == "slot_only" else THEME["slot"],
            fg=THEME["text"] if state["layout_choice"] == "slot_only" else THEME["panel_2"],
        )
        cinema_button.configure(
            bg=THEME["cinema_active"] if state["layout_choice"] == "cinema" else THEME["cinema"],
            fg=THEME["text"],
        )
        webcam_button.configure(
            bg=THEME["webcam_active"] if state["mode"] == "webcam" else THEME["webcam"],
            fg=THEME["text"] if state["mode"] == "webcam" else THEME["panel_2"],
        )
        target_button.configure(
            text=_toolbar_target_label(state["layout_choice"]),
            bg=THEME["cinema_active"] if state["mode"] == "cinema" else THEME["slot_active"] if state["mode"] == "slot" else THEME["line"],
            fg=THEME["text"],
        )

    def set_layout_choice(choice: str) -> None:
        state["layout_choice"] = choice
        state["mode"] = "cinema" if choice == "cinema" else "slot"
        mode_badge.configure(
            text="CINEMA" if choice == "cinema" else "SLOT",
            bg=THEME["cinema"] if choice == "cinema" else THEME["slot"],
        )
        status.set(_status_for_choice(choice))
        refresh_button_styles()
        redraw()

    def set_mode(mode: str) -> None:
        state["mode"] = mode
        if mode == "webcam":
            status.set("Drag on the frame to set the optional webcam crop.")
        elif mode == "cinema":
            status.set("Cinema mode. Drag on the frame to set the movie area, then Apply.")
        else:
            status.set("Slot mode. Drag on the frame to set the slot area, then Apply.")
        refresh_button_styles()

    def update_time_label(value: float | None = None) -> None:
        shown = state["preview_time_sec"] if value is None else float(value)
        time_label.set(f"Preview frame: {_fmt_timestamp(shown)} / {_fmt_timestamp(duration_sec)}")

    def update_preview_frame(target_time_sec: float, clear_selection: bool = True) -> None:
        frame, actual_time = _read_frame_at_time(cv2, video_path, video_info, target_time_sec)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        state["full_image"] = Image.fromarray(rgb)
        next_image = state["full_image"].copy()
        if (display_w, display_h) != (source_w, source_h):
            next_image = next_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
        state["photo"] = ImageTk.PhotoImage(next_image)
        state["preview_time_sec"] = actual_time
        canvas.itemconfigure(image_item, image=state["photo"])
        time_scale.set(actual_time)
        update_time_label(actual_time)
        if clear_selection:
            state["webcam"] = _manual_crop_from_config(config, "manual_webcam_crop", source_w, source_h) or _crop_from_webcam_result(auto_webcam_result)
            state["slot"] = _manual_crop_from_config(config, "manual_slot_crop", source_w, source_h) or _crop_from_content_result(auto_content_result)
            state["cinema"] = _manual_crop_from_config(config, "manual_cinema_crop", source_w, source_h)
            if state["cinema"] is None:
                state["cinema"] = _default_cinema_crop(source_w, source_h, state["slot"] or state["webcam"])
            state["drag_start"] = None
            state["drag_rect"] = None
            state["drag_kind"] = None
            state["drag_offset"] = None
            status.set(
                f"Frame changed to {_fmt_timestamp(actual_time)}. "
                "Selections were reset for this frame."
            )
        redraw()

    def on_time_preview(value: str) -> None:
        update_time_label(float(value))

    def on_time_release(_event) -> None:
        try:
            update_preview_frame(float(time_scale.get()), clear_selection=True)
        except RuntimeError as exc:
            status.set(str(exc))

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

    def current_target_crop() -> Optional[Crop]:
        key = active_target_key()
        if key == "webcam":
            return state["webcam"]
        if key == "cinema":
            return state["cinema"]
        return state["slot"]

    def set_current_target_crop(crop: Crop) -> None:
        key = active_target_key()
        if key == "webcam":
            state["webcam"] = crop
            status.set(f"Webcam selected: {crop}.")
        elif key == "cinema":
            state["cinema"] = crop
            status.set(f"Cinema area selected: {crop}.")
        else:
            state["slot"] = crop
            status.set(f"Slot selected: {crop}.")

    def redraw() -> None:
        canvas.delete("selection")
        if state["layout_choice"] == "slot_only" and state["slot"] is not None:
            canvas.create_rectangle(*source_to_display(state["slot"]), outline=THEME["slot"], width=4, tags="selection")
        if state["layout_choice"] == "cinema" and state["cinema"] is not None:
            canvas.create_rectangle(*source_to_display(state["cinema"]), outline=THEME["cinema"], width=4, tags="selection")
        if state["webcam"] is not None:
            canvas.create_rectangle(*source_to_display(state["webcam"]), outline=THEME["webcam"], width=4, tags="selection")
        if state["drag_rect"] is not None:
            outline = THEME["webcam"] if active_target_key() == "webcam" else THEME["cinema"] if active_target_key() == "cinema" else THEME["slot"]
            canvas.create_rectangle(*state["drag_rect"], outline=outline, width=3, dash=(8, 4), tags="selection")

    def on_press(event) -> None:
        x, y = clamp_display(event.x, event.y)
        current_crop = current_target_crop()
        if current_crop is not None:
            cx1, cy1, cx2, cy2 = source_to_display(current_crop)
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
            set_current_target_crop(display_to_source(drag_rect))
            redraw()
            return
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            redraw()
            return
        set_current_target_crop(display_to_source((x0, y0, x1, y1)))
        redraw()

    def on_apply() -> None:
        if state["layout_choice"] == "slot_only":
            if state["slot"] is None:
                status.set("Slot mode requires a slot crop.")
                return
            state["result"] = LayoutSelection(
                webcam_crop=state["webcam"],
                slot_crop=state["slot"],
                cinema_crop=None,
                banner_box=None,
                banner_start_sec=None,
                source_size=(source_w, source_h),
                preview_time_sec=state["preview_time_sec"],
                apply_mode="slot_only",
            )
            root.destroy()
            return

        crop = state["cinema"] or _default_cinema_crop(source_w, source_h, state["slot"] or state["webcam"])
        banner_box = None
        banner_start_sec = None
        if _banner_preview_enabled(config):
            edit_result = _open_cinema_banner_editor(
                root,
                state["full_image"],
                (source_w, source_h),
                crop,
                state["webcam"],
                config,
            )
            if edit_result is None:
                status.set("Cinema layout kept. Finish banner placement or press Apply again.")
                return
            banner_box, banner_start_sec = edit_result
        state["result"] = LayoutSelection(
            webcam_crop=state["webcam"],
            slot_crop=None,
            cinema_crop=crop,
            banner_box=banner_box,
            banner_start_sec=banner_start_sec,
            source_size=(source_w, source_h),
            preview_time_sec=state["preview_time_sec"],
            apply_mode="cinema",
        )
        root.destroy()

    def on_clear_webcam() -> None:
        if state["webcam"] is None:
            status.set("Webcam is already cleared.")
            return
        state["webcam"] = None
        status.set("Webcam cleared.")
        redraw()

    slot_layout_button = styled_button(
        toolbar,
        "Slot",
        THEME["slot"],
        THEME["slot_active"],
        lambda: set_layout_choice("slot_only"),
        12,
    )
    slot_layout_button.pack(side=tk.LEFT, padx=(8, 6), pady=8)
    cinema_layout_button = styled_button(
        toolbar,
        "Cinema",
        THEME["cinema"],
        THEME["cinema_active"],
        lambda: set_layout_choice("cinema"),
        12,
    )
    cinema_layout_button.pack(side=tk.LEFT, padx=(0, 12), pady=8)
    webcam_button = styled_button(
        toolbar,
        "Select webcam",
        THEME["webcam"],
        THEME["webcam_active"],
        lambda: set_mode("webcam"),
        16,
    )
    webcam_button.pack(side=tk.LEFT, padx=(0, 6), pady=8)
    clear_webcam_button = styled_button(
        toolbar,
        "Clear webcam",
        THEME["line"],
        THEME["panel_2"],
        on_clear_webcam,
        16,
    )
    clear_webcam_button.configure(fg=THEME["text"], activeforeground=THEME["text"])
    clear_webcam_button.pack(side=tk.LEFT, padx=(0, 6), pady=8)
    target_button = styled_button(
        toolbar,
        _toolbar_target_label(state["layout_choice"]),
        THEME["slot"],
        THEME["slot_active"],
        lambda: set_mode("cinema" if state["layout_choice"] == "cinema" else "slot"),
        16,
    )
    target_button.configure(fg=THEME["text"], activeforeground=THEME["text"])
    target_button.pack(side=tk.LEFT, padx=(0, 6), pady=8)
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
    buttons.update(
        {
            "layout_slot": slot_layout_button,
            "layout_cinema": cinema_layout_button,
            "webcam": webcam_button,
            "target": target_button,
        }
    )

    set_layout_choice(state["layout_choice"])
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

    Backend-compatible `auto`/split paths stay intact for saved older selections,
    but the UI only emits `slot_only` and `cinema`.
    """
    apply_mode = str(getattr(selection, "apply_mode", "auto") or "auto")
    has_webcam = selection.webcam_crop is not None
    has_slot = selection.slot_crop is not None

    if apply_mode == "slot_only":
        crop = selection.slot_crop
        if crop is None:
            return "none"
        config.layout_mode = "slot_only"
        config.manual_webcam_crop = list(selection.webcam_crop) if selection.webcam_crop is not None else None
        config.manual_slot_crop = list(crop)
        config.manual_cinema_crop = None
        config.webcam_detection = "auto" if selection.webcam_crop is not None else "off"
        config.subtitles_position = (
            "between_webcam_and_game" if selection.webcam_crop is not None else "slot_top"
        )
        if getattr(config, "banner", None) is not None:
            config.banner.manual_box = None
            config.banner.manual_start_sec = None
            setattr(config.banner, "selected_file", None)
        return "slot_only_with_webcam" if selection.webcam_crop is not None else "slot_only_no_webcam"

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
        if getattr(config, "banner", None) is not None:
            config.banner.manual_box = _banner_box_to_ratios(
                selection.banner_box,
                int(getattr(getattr(config, "export", None), "width", 1080) or 1080),
                int(getattr(getattr(config, "export", None), "height", 1920) or 1920),
            )
            config.banner.manual_start_sec = (
                round(float(selection.banner_start_sec), 3)
                if selection.banner_start_sec is not None
                else None
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
        if getattr(config, "banner", None) is not None:
            config.banner.manual_box = None
            config.banner.manual_start_sec = None
            setattr(config.banner, "selected_file", None)
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
    if getattr(config, "banner", None) is not None:
        config.banner.manual_box = None
        config.banner.manual_start_sec = None
        setattr(config.banner, "selected_file", None)
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
        "manual_banner_box": list(selection.banner_box) if selection.banner_box else None,
        "manual_banner_start_sec": selection.banner_start_sec,
        "effective_manual_webcam_crop": config.manual_webcam_crop,
        "effective_manual_slot_crop": config.manual_slot_crop,
        "effective_manual_cinema_crop": config.manual_cinema_crop,
        "effective_manual_banner_box": getattr(getattr(config, "banner", None), "manual_box", None),
        "effective_manual_banner_start_sec": getattr(getattr(config, "banner", None), "manual_start_sec", None),
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


def _open_cinema_banner_editor(
    parent,
    full_image,
    source_size: tuple[int, int],
    cinema_crop: Crop,
    webcam_crop: Optional[Crop],
    config: AppConfig,
) -> Optional[tuple[Crop, float]]:
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError:
        return None

    asset = pick_banner_asset(config)
    if asset is None:
        console.print("[yellow]Cinema banner editor skipped: no banner asset found.[/yellow]")
        return None
    if getattr(config, "banner", None) is not None:
        setattr(config.banner, "selected_file", asset.path)

    out_w, out_h = _export_size(config)
    banner_aspect = asset.crop[2] / max(1, asset.crop[3])
    saved_box = _banner_box_from_config(config, out_w, out_h)
    if saved_box is not None:
        default_box = _normalize_banner_box_for_asset(saved_box, banner_aspect, out_w, out_h)
    else:
        default_box = _default_banner_box_for_asset(config, out_w, out_h, banner_aspect)
    default_start = _banner_start_from_config(config, asset.start_sec)

    editor = tk.Toplevel(parent)
    editor.title("StreamCuter Cinema Banner")
    editor.configure(bg=THEME["bg"])
    editor.transient(parent)
    editor.grab_set()

    screen_h = max(720, int(editor.winfo_screenheight() * 0.84))
    preview_h = max(540, min(960, screen_h - 210))
    preview_w = max(2, int(round(preview_h * out_w / max(1, out_h))))
    scale_x = preview_w / max(1, out_w)
    scale_y = preview_h / max(1, out_h)

    state = {
        "banner_box": default_box,
        "banner_start_sec": default_start,
        "banner_action": None,
        "banner_drag_start": None,
        "banner_drag_offset": None,
        "base_image": None,
        "base_photo": None,
        "preview_photo": None,
        "banner_image": None,
        "banner_frame_sec": None,
        "result": None,
    }

    shell = tk.Frame(editor, bg=THEME["bg"])
    shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

    header = tk.Frame(shell, bg=THEME["bg"])
    header.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        header,
        text="Cinema Banner Editor",
        bg=THEME["bg"],
        fg=THEME["text"],
        font=("Segoe UI", 15, "bold"),
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Label(
        header,
        text="BANNER",
        bg=THEME["banner"],
        fg=THEME["panel_2"],
        font=("Segoe UI", 10, "bold"),
        padx=12,
        pady=4,
    ).pack(side=tk.RIGHT)

    status = tk.StringVar(
        value="Move or resize the banner on the ready vertical frame, then Apply."
    )
    tk.Label(
        shell,
        textvariable=status,
        anchor="w",
        bg=THEME["panel"],
        fg=THEME["muted"],
        font=("Segoe UI", 10),
        padx=12,
        pady=8,
    ).pack(fill=tk.X, pady=(0, 8))

    canvas_shell = tk.Frame(shell, bg=THEME["line"], padx=2, pady=2)
    canvas_shell.pack()
    canvas = tk.Canvas(
        canvas_shell,
        width=preview_w,
        height=preview_h,
        bg=THEME["panel_2"],
        highlightthickness=0,
        cursor="fleur",
    )
    canvas.pack()

    controls = tk.Frame(shell, bg=THEME["panel"])
    controls.pack(fill=tk.X, pady=(8, 0))
    phase_label = tk.StringVar(value=f"Banner phase: {banner_time_for_preview(asset, default_start):.2f}s")
    tk.Label(
        controls,
        textvariable=phase_label,
        width=18,
        anchor="w",
        bg=THEME["panel"],
        fg=THEME["text"],
        font=("Segoe UI", 10, "bold"),
        padx=10,
    ).pack(side=tk.LEFT)

    slider_max = max(0.1, float(getattr(asset, "duration_sec", 0.0) or 0.0))
    phase_scale = tk.Scale(
        controls,
        from_=0.0,
        to=slider_max,
        orient=tk.HORIZONTAL,
        showvalue=False,
        resolution=0.05 if slider_max <= 15 else 0.10,
        bg=THEME["panel"],
        fg=THEME["text"],
        activebackground=THEME["apply"],
        troughcolor=THEME["line"],
        highlightthickness=0,
        bd=0,
        length=max(240, preview_w - 280),
    )
    phase_scale.set(default_start)
    phase_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    footer = tk.Frame(shell, bg=THEME["panel"])
    footer.pack(fill=tk.X, pady=(8, 0))

    def build_banner_preview_rgba() -> Optional[Image.Image]:
        current_time = banner_time_for_preview(asset, float(state["banner_start_sec"] or 0.0))
        if state["banner_image"] is not None and state["banner_frame_sec"] == current_time:
            return state["banner_image"]
        rgba = load_banner_preview_rgba(
            asset,
            current_time,
            similarity=float(getattr(getattr(config, "banner", None), "chroma_similarity", 0.18) or 0.18),
        )
        if rgba is None:
            return None
        state["banner_frame_sec"] = current_time
        state["banner_image"] = Image.fromarray(rgba, mode="RGBA")
        return state["banner_image"]

    def build_base_preview(rebuild_box: Crop):
        state["base_image"], _ = _build_cinema_preview_image(
            full_image,
            source_size,
            config,
            cinema_crop,
            webcam_crop,
            rebuild_box,
        )

    def compose_preview_image() -> None:
        if state["base_image"] is None:
            build_base_preview(state["banner_box"])
        base_image = state["base_image"].copy()
        banner_image = build_banner_preview_rgba()
        if banner_image is not None:
            base_image = _composite_banner_on_preview(base_image, banner_image, state["banner_box"])
        preview_image = base_image.resize((preview_w, preview_h), Image.Resampling.LANCZOS)
        state["preview_photo"] = ImageTk.PhotoImage(preview_image)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor=tk.NW, image=state["preview_photo"])
        bx1, by1, bx2, by2 = _output_to_display_box(state["banner_box"], scale_x, scale_y)
        canvas.create_rectangle(bx1, by1, bx2, by2, outline=THEME["banner"], width=3)
        handle = max(10, min(18, int(round(min(bx2 - bx1, by2 - by1) * 0.16))))
        for hx, hy in (
            (bx1, by1),
            (bx2 - handle, by1),
            (bx1, by2 - handle),
            (bx2 - handle, by2 - handle),
        ):
            canvas.create_rectangle(
                hx,
                hy,
                hx + handle,
                hy + handle,
                outline=THEME["banner"],
                fill=THEME["banner"],
                width=0,
            )

    def refresh_editor(rebuild_base: bool = False) -> None:
        state["banner_start_sec"] = banner_time_for_preview(asset, float(phase_scale.get()))
        phase_label.set(f"Banner phase: {state['banner_start_sec']:.2f}s")
        if state["banner_frame_sec"] != state["banner_start_sec"]:
            state["banner_image"] = None
        if rebuild_base or state["base_image"] is None:
            build_base_preview(state["banner_box"])
        compose_preview_image()

    def banner_hit_test(x: int, y: int) -> str:
        bx1, by1, bx2, by2 = _output_to_display_box(state["banner_box"], scale_x, scale_y)
        handle = max(10, min(18, int(round(min(bx2 - bx1, by2 - by1) * 0.15))))
        if bx1 <= x <= bx1 + handle and by1 <= y <= by1 + handle:
            return "resize_nw"
        if bx2 - handle <= x <= bx2 and by1 <= y <= by1 + handle:
            return "resize_ne"
        if bx1 <= x <= bx1 + handle and by2 - handle <= y <= by2:
            return "resize_sw"
        if bx2 - handle <= x <= bx2 and by2 - handle <= y <= by2:
            return "resize_se"
        if bx1 <= x <= bx2 and by1 <= y <= by2:
            return "move"
        return "move"

    def on_phase_change(_value) -> None:
        refresh_editor(rebuild_base=False)

    def on_press(event) -> None:
        x = max(0, min(preview_w, int(event.x)))
        y = max(0, min(preview_h, int(event.y)))
        action = banner_hit_test(x, y)
        state["banner_action"] = action
        state["banner_drag_start"] = (x, y)
        if action == "move":
            bx1, by1, _, _ = _output_to_display_box(state["banner_box"], scale_x, scale_y)
            state["banner_drag_offset"] = (x - bx1, y - by1)
        else:
            state["banner_drag_offset"] = None

    def on_drag(event) -> None:
        if state["banner_action"] is None:
            return
        x = max(0, min(preview_w, int(event.x)))
        y = max(0, min(preview_h, int(event.y)))
        action = state["banner_action"]
        if action == "move":
            box = state["banner_box"]
            box_w, box_h = box[2], box[3]
            offset_x, offset_y = state.get("banner_drag_offset") or (0, 0)
            new_x = int(round((x - offset_x) / max(scale_x, 1e-6)))
            new_y = int(round((y - offset_y) / max(scale_y, 1e-6)))
            state["banner_box"] = _clamp_output_box(new_x, new_y, box_w, box_h, out_w, out_h)
        else:
            state["banner_box"] = _resize_banner_box(
                state["banner_box"],
                action,
                x,
                y,
                scale_x,
                scale_y,
                out_w,
                out_h,
                banner_aspect,
            )
        status.set(f"Banner box: {state['banner_box']}")
        compose_preview_image()

    def on_release(_event) -> None:
        if state["banner_action"] is None:
            return
        state["banner_box"] = _clamp_output_box(*state["banner_box"], out_w, out_h)
        state["banner_action"] = None
        state["banner_drag_start"] = None
        state["banner_drag_offset"] = None
        refresh_editor(rebuild_base=True)

    def on_reset() -> None:
        state["banner_box"] = _default_banner_box_for_asset(config, out_w, out_h, banner_aspect)
        phase_scale.set(default_start)
        refresh_editor(rebuild_base=True)
        status.set("Banner reset to default size, place and phase.")

    def on_back() -> None:
        state["result"] = None
        editor.destroy()

    def on_apply() -> None:
        state["result"] = (
            _clamp_output_box(*state["banner_box"], out_w, out_h),
            banner_time_for_preview(asset, float(state["banner_start_sec"] or 0.0)),
        )
        editor.destroy()

    back_button = tk.Button(
        footer,
        text="Back",
        command=on_back,
        width=12,
        bg=THEME["line"],
        fg=THEME["text"],
        activebackground=THEME["panel_2"],
        activeforeground=THEME["text"],
        relief=tk.FLAT,
        bd=0,
        padx=10,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    )
    back_button.pack(side=tk.LEFT, padx=(8, 6), pady=8)
    reset_button = tk.Button(
        footer,
        text="Reset banner",
        command=on_reset,
        width=14,
        bg=THEME["banner"],
        fg=THEME["panel_2"],
        activebackground=THEME["apply_active"],
        activeforeground=THEME["panel_2"],
        relief=tk.FLAT,
        bd=0,
        padx=10,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    )
    reset_button.pack(side=tk.LEFT, padx=(0, 6), pady=8)
    apply_button = tk.Button(
        footer,
        text="Apply",
        command=on_apply,
        width=12,
        bg=THEME["apply"],
        fg=THEME["apply_text"],
        activebackground=THEME["apply_active"],
        activeforeground=THEME["apply_text"],
        relief=tk.FLAT,
        bd=0,
        padx=10,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    )
    apply_button.pack(side=tk.RIGHT, padx=(6, 8), pady=8)

    phase_scale.configure(command=on_phase_change)
    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    editor.protocol("WM_DELETE_WINDOW", on_back)
    refresh_editor(rebuild_base=True)
    editor.wait_window()
    return state["result"]


def _build_cinema_preview_image(
    full_image,
    source_size: tuple[int, int],
    config: AppConfig,
    cinema_crop: Crop,
    webcam_crop: Optional[Crop],
    banner_box: Optional[Crop],
):
    from PIL import Image, ImageFilter

    source_w, source_h = source_size
    out_w, out_h = _export_size(config)

    preview_cfg = copy.deepcopy(config)
    preview_cfg.layout_mode = "cinema"
    preview_cfg.manual_cinema_crop = list(cinema_crop)
    preview_cfg.manual_webcam_crop = list(webcam_crop) if webcam_crop is not None else None
    preview_cfg.manual_slot_crop = None
    preview_cfg.webcam_detection = "auto" if webcam_crop is not None else "off"
    if _banner_preview_enabled(preview_cfg):
        preview_cfg.banner.manual_box = _banner_box_to_ratios(banner_box, out_w, out_h)

    webcam_region = None
    if webcam_crop is not None:
        wx, wy, ww, wh = webcam_crop
        webcam_region = WebcamRegion(wx, wy, ww, wh, 1.0)
    webcam_result = WebcamDetectionResult(has_webcam=webcam_crop is not None, region=webcam_region)
    layout = compute_layout(
        source_w,
        source_h,
        out_w,
        out_h,
        webcam_result,
        preview_cfg,
        suppress_logs=True,
    )

    def crop_image(crop: Crop):
        x, y, w, h = crop
        return full_image.crop((x, y, x + w, y + h))

    def fit_inside(image_in, box_w: int, box_h: int):
        ratio = min(box_w / max(1, image_in.width), box_h / max(1, image_in.height))
        dst_w = max(2, int(round(image_in.width * ratio)))
        dst_h = max(2, int(round(image_in.height * ratio)))
        return image_in.resize((dst_w, dst_h), Image.Resampling.LANCZOS)

    def fill_box(image_in, box_w: int, box_h: int):
        ratio = max(box_w / max(1, image_in.width), box_h / max(1, image_in.height))
        dst_w = max(2, int(round(image_in.width * ratio)))
        dst_h = max(2, int(round(image_in.height * ratio)))
        scaled = image_in.resize((dst_w, dst_h), Image.Resampling.LANCZOS)
        left = max(0, (scaled.width - box_w) // 2)
        top = max(0, (scaled.height - box_h) // 2)
        return scaled.crop((left, top, left + box_w, top + box_h))

    base_crop = crop_image(layout.content_src)
    background = fill_box(base_crop, out_w, out_h).filter(ImageFilter.GaussianBlur(radius=22)).convert("RGBA")

    if layout.has_webcam and layout.webcam_src is not None and layout.webcam_out is not None:
        wx, wy, ww, wh = layout.webcam_out
        webcam_image = crop_image(layout.webcam_src)
        webcam_fill = fill_box(webcam_image, ww, wh).convert("RGBA")
        background.alpha_composite(webcam_fill, (wx, wy))

    cx, cy, cw, ch = layout.content_out
    content_fit = fit_inside(base_crop, cw, ch).convert("RGBA")
    paste_x = cx + max(0, (cw - content_fit.width) // 2)
    paste_y = cy + max(0, (ch - content_fit.height) // 2)
    background.alpha_composite(content_fit, (paste_x, paste_y))
    return background, layout


def _composite_banner_on_preview(base_image, banner_image, banner_box: Crop):
    from PIL import Image

    bx, by, bw, bh = banner_box
    ratio = min(bw / max(1, banner_image.width), bh / max(1, banner_image.height))
    dst_w = max(2, int(round(banner_image.width * ratio)))
    dst_h = max(2, int(round(banner_image.height * ratio)))
    scaled = banner_image.resize((dst_w, dst_h), Image.Resampling.LANCZOS)
    paste_x = bx
    paste_y = by + bh - dst_h
    composed = base_image.copy()
    composed.alpha_composite(scaled, (paste_x, paste_y))
    return composed


def _toolbar_target_label(layout_choice: str) -> str:
    return "Select cinema" if layout_choice == "cinema" else "Select slot"


def _toolbar_button_labels(layout_choice: str) -> list[str]:
    return [
        "Select cinema" if layout_choice == "cinema" else "Select slot",
        "Select webcam",
        "Clear webcam",
        "Apply",
    ]


def _status_for_choice(layout_choice: str) -> str:
    if layout_choice == "cinema":
        return "Cinema mode. Mark the movie area, keep webcam only if you really need it, then Apply."
    return "Slot mode. Mark the slot area, keep webcam only if needed, then Apply."


def _output_to_display_box(box: Crop, scale_x: float, scale_y: float) -> tuple[int, int, int, int]:
    x, y, w, h = box
    return (
        int(round(x * scale_x)),
        int(round(y * scale_y)),
        int(round((x + w) * scale_x)),
        int(round((y + h) * scale_y)),
    )


def _display_to_output_box(
    rect: tuple[int, int, int, int],
    scale_x: float,
    scale_y: float,
    out_w: int,
    out_h: int,
) -> Crop:
    x1, y1, x2, y2 = rect
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x = int(round(x1 / max(scale_x, 1e-6)))
    y = int(round(y1 / max(scale_y, 1e-6)))
    w = int(round((x2 - x1) / max(scale_x, 1e-6)))
    h = int(round((y2 - y1) / max(scale_y, 1e-6)))
    return _clamp_output_box(x, y, w, h, out_w, out_h)


def _export_size(config: AppConfig) -> tuple[int, int]:
    return (
        int(getattr(getattr(config, "export", None), "width", 1080) or 1080),
        int(getattr(getattr(config, "export", None), "height", 1920) or 1920),
    )


def _banner_start_from_config(config: AppConfig, fallback: float) -> float:
    banner = getattr(config, "banner", None)
    raw = getattr(banner, "manual_start_sec", None) if banner is not None else None
    if raw is None:
        return max(0.0, float(fallback))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return max(0.0, float(fallback))


def _saved_layout_selection_path(config: AppConfig) -> Path:
    out_name = config.layout_preview_save_path or "layout_selection.json"
    out_path = Path(out_name)
    if not out_path.is_absolute():
        out_path = Path(config.output_dir) / out_path
    return out_path


def _restore_saved_banner_state(config: AppConfig) -> None:
    if not _banner_preview_enabled(config):
        return
    banner = getattr(config, "banner", None)
    if banner is None:
        return
    if getattr(banner, "manual_box", None) is not None and getattr(banner, "manual_start_sec", None) is not None:
        return

    save_path = _saved_layout_selection_path(config)
    if not save_path.exists():
        return
    try:
        payload = json.loads(save_path.read_text(encoding="utf-8"))
    except Exception:
        return

    saved_box = payload.get("effective_manual_banner_box") or payload.get("manual_banner_box")
    saved_start = payload.get("effective_manual_banner_start_sec")
    if saved_start is None:
        saved_start = payload.get("manual_banner_start_sec")

    if getattr(banner, "manual_box", None) is None and isinstance(saved_box, list) and len(saved_box) == 4:
        try:
            banner.manual_box = [float(value) for value in saved_box]
        except (TypeError, ValueError):
            pass
    if getattr(banner, "manual_start_sec", None) is None and saved_start is not None:
        try:
            banner.manual_start_sec = float(saved_start)
        except (TypeError, ValueError):
            pass


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


def _banner_preview_enabled(config: AppConfig) -> bool:
    banner = getattr(config, "banner", None)
    return bool(banner is not None and getattr(banner, "enabled", False))


def _banner_preview_guide_rect(
    display_w: int,
    display_h: int,
    config: AppConfig,
) -> Optional[tuple[int, int, int, int]]:
    banner = getattr(config, "banner", None)
    if banner is None or not getattr(banner, "enabled", False):
        return None

    out_w, out_h = _export_size(config)
    scale_x = display_w / max(1, out_w)
    scale_y = display_h / max(1, out_h)
    banner_box = _banner_box_from_config(config, out_w, out_h) or _default_banner_box(config, out_w, out_h)
    x, y, w, h = banner_box
    box_w = max(24, int(round(w * scale_x)))
    box_h = max(18, int(round(h * scale_y)))
    x1 = max(6, int(round(x * scale_x)))
    x2 = min(display_w - 6, x1 + box_w)
    y1 = max(6, int(round(y * scale_y)))
    y2 = min(display_h - 6, y1 + box_h)
    return x1, y1, x2, y2


def _default_banner_box(config: AppConfig, out_w: int, out_h: int) -> Crop:
    banner = getattr(config, "banner", None)
    width_ratio = float(getattr(banner, "width_ratio", 0.50)) if banner is not None else 0.50
    height_ratio = float(getattr(banner, "max_height_ratio", 0.14)) if banner is not None else 0.14
    margin_left = int(getattr(banner, "margin_left", 32)) if banner is not None else 32
    margin_bottom = int(getattr(banner, "margin_bottom", 56)) if banner is not None else 56
    box_w = int(round(out_w * max(0.14, min(0.90, width_ratio))))
    box_h = int(round(out_h * max(0.05, min(0.50, height_ratio))))
    x = margin_left
    y = out_h - box_h - margin_bottom
    return _clamp_output_box(x, y, box_w, box_h, out_w, out_h)


def _default_banner_box_for_asset(
    config: AppConfig,
    out_w: int,
    out_h: int,
    aspect_ratio: float,
) -> Crop:
    banner = getattr(config, "banner", None)
    width_ratio = float(getattr(banner, "width_ratio", 0.50)) if banner is not None else 0.50
    max_height_ratio = float(getattr(banner, "max_height_ratio", 0.14)) if banner is not None else 0.14
    margin_left = int(getattr(banner, "margin_left", 32)) if banner is not None else 32
    margin_bottom = int(getattr(banner, "margin_bottom", 56)) if banner is not None else 56

    box_w = max(48, int(round(out_w * max(0.16, min(0.85, width_ratio)))))
    box_h = max(36, int(round(box_w / max(0.5, aspect_ratio))))
    max_h = max(36, int(round(out_h * max(0.05, min(0.40, max_height_ratio)))))
    if box_h > max_h:
        box_h = max_h
        box_w = max(48, int(round(box_h * aspect_ratio)))
    x = margin_left
    y = out_h - box_h - margin_bottom
    return _clamp_output_box(x, y, box_w, box_h, out_w, out_h)


def _normalize_banner_box_for_asset(
    box: Crop,
    aspect_ratio: float,
    out_w: int,
    out_h: int,
) -> Crop:
    x, y, w, h = _clamp_output_box(*box, out_w, out_h)
    bottom = y + h
    width = max(48, w)
    height = max(36, int(round(width / max(0.5, aspect_ratio))))
    if height > out_h:
        height = out_h
        width = max(48, int(round(height * aspect_ratio)))
    new_y = max(0, min(out_h - height, bottom - height))
    return _clamp_output_box(x, new_y, width, height, out_w, out_h)


def _resize_banner_box(
    current_box: Crop,
    action: str,
    display_x: int,
    display_y: int,
    scale_x: float,
    scale_y: float,
    out_w: int,
    out_h: int,
    aspect_ratio: float,
) -> Crop:
    x, y, w, h = current_box
    if action == "resize_nw":
        anchor_x = x + w
        anchor_y = y + h
        dir_x = -1
        dir_y = -1
    elif action == "resize_ne":
        anchor_x = x
        anchor_y = y + h
        dir_x = 1
        dir_y = -1
    elif action == "resize_sw":
        anchor_x = x + w
        anchor_y = y
        dir_x = -1
        dir_y = 1
    else:
        anchor_x = x
        anchor_y = y
        dir_x = 1
        dir_y = 1

    target_x = int(round(display_x / max(scale_x, 1e-6)))
    target_y = int(round(display_y / max(scale_y, 1e-6)))
    width_from_x = abs(target_x - anchor_x)
    width_from_y = int(round(abs(target_y - anchor_y) * aspect_ratio))
    new_w = max(48, max(width_from_x, width_from_y))
    new_h = max(36, int(round(new_w / max(0.5, aspect_ratio))))

    new_x = anchor_x if dir_x > 0 else anchor_x - new_w
    new_y = anchor_y if dir_y > 0 else anchor_y - new_h
    return _clamp_output_box(new_x, new_y, new_w, new_h, out_w, out_h)


def _banner_box_from_config(config: AppConfig, out_w: int, out_h: int) -> Optional[Crop]:
    banner = getattr(config, "banner", None)
    raw = getattr(banner, "manual_box", None) if banner is not None else None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x_ratio, y_ratio, w_ratio, h_ratio = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    return _clamp_output_box(
        int(round(out_w * x_ratio)),
        int(round(out_h * y_ratio)),
        int(round(out_w * w_ratio)),
        int(round(out_h * h_ratio)),
        out_w,
        out_h,
    )


def _banner_box_to_ratios(box: Optional[Crop], out_w: int, out_h: int) -> Optional[list[float]]:
    if box is None:
        return None
    x, y, w, h = _clamp_output_box(*box, out_w, out_h)
    return [
        round(x / max(1, out_w), 6),
        round(y / max(1, out_h), 6),
        round(w / max(1, out_w), 6),
        round(h / max(1, out_h), 6),
    ]


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


def _clamp_output_box(
    x: int,
    y: int,
    w: int,
    h: int,
    out_w: int,
    out_h: int,
) -> Crop:
    w = max(48, min(int(w), out_w))
    h = max(36, min(int(h), out_h))
    x = max(0, min(int(x), out_w - w))
    y = max(0, min(int(y), out_h - h))
    return x, y, w, h
