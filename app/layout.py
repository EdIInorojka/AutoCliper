"""Layout computation for vertical video composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig
from app.content_detector import ContentDetectionResult, centered_content_crop
from app.webcam_types import WebcamDetectionResult

console = get_console()


@dataclass
class LayoutSpec:
    """Describes how to compose the vertical frame."""
    has_webcam: bool
    mode: str = "auto"
    # Webcam panel region in output (x, y, w, h)
    webcam_out: Optional[tuple[int, int, int, int]] = None
    # Source crop for webcam (x, y, w, h) in source video
    webcam_src: Optional[tuple[int, int, int, int]] = None
    # Main content source crop (x, y, w, h) in source video
    content_src: Optional[tuple[int, int, int, int]] = None
    # Main content output region (x, y, w, h)
    content_out: Optional[tuple[int, int, int, int]] = None
    # Optional banner region in output (x, y, w, h)
    banner_out: Optional[tuple[int, int, int, int]] = None
    # Final output size (w, h)
    output_size: tuple[int, int] = (0, 0)
    # Blur background fill filter string (ffmpeg)
    blur_bg_filter: str = ""
    # Subtitle safe zone (y position from bottom)
    subtitle_safe_y: int = 200


def _even(value: int) -> int:
    return max(2, int(value) - (int(value) % 2))


def _clamp_crop(
    x: int,
    y: int,
    w: int,
    h: int,
    src_w: int,
    src_h: int,
) -> tuple[int, int, int, int]:
    """Clamp a crop rectangle to the source frame and keep dimensions encoder-friendly."""
    w = _even(min(max(2, w), src_w))
    h = _even(min(max(2, h), src_h))
    x = max(0, min(int(x), src_w - w))
    y = max(0, min(int(y), src_h - h))
    return x, y, w, h


def _is_left_stream_webcam(wr, src_w: int, src_h: int) -> bool:
    """Detect the common casino/stream layout where webcam sits in the left overlay rail."""
    return (
        wr.x <= src_w * 0.08
        and src_h * 0.25 <= wr.y <= src_h * 0.70
        and wr.w <= src_w * 0.38
        and wr.h <= src_h * 0.42
    )


def _expand_left_webcam_crop(wr, src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Recover the whole 16:9 webcam panel from a face-driven left-overlay detection."""
    desired_w = max(wr.w, int(src_w * 0.252))
    desired_w = min(desired_w, int(src_w * 0.36))
    desired_h = int(desired_w * 9 / 16)

    x = 0
    if src_h * 0.36 <= wr.y <= src_h * 0.54:
        y = int(src_h * 0.43)
    else:
        y = wr.y + (wr.h - desired_h) // 2
    return _clamp_crop(x, y, desired_w, desired_h, src_w, src_h)


def _slot_crop_from_left_webcam(src_w: int, src_h: int, wr) -> tuple[int, int, int, int]:
    """
    Crop the actual game/slot viewport for the observed left-rail stream layout.

    The crop keeps the slot area, discards browser chrome and the left overlay rail,
    and leaves the composed lower panel with blurred slot-derived background around it.
    """
    left = max(int(src_w * 0.238), wr.x + int(wr.w * 0.94))
    top = int(src_h * 0.109)
    right = int(src_w * 0.985)
    bottom = int(src_h * 0.855)
    return _clamp_crop(left, top, right - left, bottom - top, src_w, src_h)


def _resolved_manual_slot_crop(config: AppConfig, src_w: int, src_h: int) -> Optional[tuple[int, int, int, int]]:
    crop = getattr(config, "manual_slot_crop", None)
    if not crop or len(crop) < 4:
        return None
    return _clamp_crop(int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3]), src_w, src_h)


def _resolved_manual_cinema_crop(config: AppConfig, src_w: int, src_h: int) -> Optional[tuple[int, int, int, int]]:
    crop = getattr(config, "manual_cinema_crop", None)
    if not crop or len(crop) < 4:
        return None
    return _clamp_crop(int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3]), src_w, src_h)


def _resolve_no_webcam_content_src(
    src_w: int,
    src_h: int,
    config: AppConfig,
    content_result: ContentDetectionResult | None,
) -> tuple[tuple[int, int, int, int], str]:
    manual_slot_crop = _resolved_manual_slot_crop(config, src_w, src_h)
    if manual_slot_crop is not None:
        return manual_slot_crop, "manual_slot_crop"
    if content_result is not None and content_result.has_content:
        return _clamp_crop(*content_result.crop, src_w, src_h), content_result.reason
    return centered_content_crop(src_w, src_h), "centered"


def _cinema_focus_crop(
    base_src: tuple[int, int, int, int],
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    target_height_ratio: float = 0.68,
    max_upscale: float = 1.35,
    vertical_offset_px: int = 0,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    bx, by, bw, bh = _clamp_crop(*base_src, src_w, src_h)
    target_h = _even(int(round(out_h * target_height_ratio)))
    max_target_h = _even(int(round(bh * max_upscale)))
    target_h = max(2, min(out_h, target_h, max_target_h))
    target_aspect = out_w / max(2, target_h)

    focus_w = bw
    focus_h = bh
    base_aspect = bw / max(1, bh)
    if base_aspect > target_aspect:
        focus_w = max(2, _even(int(round(bh * target_aspect))))
    else:
        focus_h = max(2, _even(int(round(bw / max(target_aspect, 1e-6)))))
    focus_w = min(focus_w, bw)
    focus_h = min(focus_h, bh)
    focus_x = bx + (bw - focus_w) // 2
    focus_y = by + (bh - focus_h) // 2
    focus_src = _clamp_crop(focus_x, focus_y, focus_w, focus_h, src_w, src_h)

    scale = min(out_w / focus_src[2], target_h / focus_src[3], max_upscale)
    sharp_w = max(2, _even(int(round(focus_src[2] * scale))))
    sharp_h = max(2, _even(int(round(focus_src[3] * scale))))
    sharp_w = min(out_w, sharp_w)
    sharp_h = min(out_h, sharp_h)
    sharp_x = max(0, (out_w - sharp_w) // 2)
    sharp_y = max(0, (out_h - sharp_h) // 2)
    if vertical_offset_px > 0:
        sharp_y = max(0, min(out_h - sharp_h, sharp_y - int(vertical_offset_px)))
    return focus_src, (sharp_x, sharp_y, sharp_w, sharp_h)


def _banner_enabled(config: AppConfig) -> bool:
    banner = getattr(config, "banner", None)
    return bool(banner is not None and getattr(banner, "enabled", False))


def _resolved_manual_banner_box(
    out_w: int,
    out_h: int,
    config: AppConfig,
) -> Optional[tuple[int, int, int, int]]:
    banner = getattr(config, "banner", None)
    raw = getattr(banner, "manual_box", None) if banner is not None else None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x_ratio, y_ratio, w_ratio, h_ratio = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    box_w = _even(int(round(out_w * max(0.10, min(0.95, w_ratio)))))
    box_h = _even(int(round(out_h * max(0.04, min(0.50, h_ratio)))))
    box_w = max(2, min(out_w, box_w))
    box_h = max(2, min(out_h, box_h))
    x = int(round(out_w * max(0.0, min(1.0, x_ratio))))
    y = int(round(out_h * max(0.0, min(1.0, y_ratio))))
    x = max(0, min(out_w - box_w, x))
    y = max(0, min(out_h - box_h, y))
    return x, y, box_w, box_h


def _cinema_banner_box(
    out_w: int,
    out_h: int,
    region_top_y: int,
    region_height: int,
    config: AppConfig,
) -> tuple[int, int, int, int]:
    manual_box = _resolved_manual_banner_box(out_w, out_h, config)
    if manual_box is not None:
        return manual_box

    banner = getattr(config, "banner", None)
    width_ratio = float(getattr(banner, "width_ratio", 0.50)) if banner is not None else 0.50
    max_height_ratio = (
        float(getattr(banner, "max_height_ratio", 0.14)) if banner is not None else 0.14
    )
    margin_left = int(getattr(banner, "margin_left", 32)) if banner is not None else 32
    margin_bottom = int(getattr(banner, "margin_bottom", 56)) if banner is not None else 56

    box_w = _even(int(round(out_w * max(0.18, min(0.60, width_ratio)))))
    box_h = _even(int(round(out_h * max(0.06, min(0.25, max_height_ratio)))))
    x = max(0, margin_left)
    y = max(region_top_y, region_top_y + region_height - box_h - margin_bottom)
    return x, y, box_w, box_h


def compute_layout(
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    webcam_result: WebcamDetectionResult,
    config: AppConfig,
    content_result: ContentDetectionResult | None = None,
    suppress_logs: bool = False,
) -> LayoutSpec:
    """
    Compute the layout for vertical video.

    If webcam exists:
      - Top portion = webcam panel
      - Bottom portion = main content
    If no webcam:
      - Full vertical crop of main content with blur fill
    """
    top_ratio = config.webcam_top_ratio  # default 0.33
    layout_mode = str(getattr(config, "layout_mode", "auto") or "auto").lower()

    if layout_mode == "slot_only":
        if not suppress_logs:
            console.print("[cyan]Layout: slot-only mode (centered content with blur fill)[/cyan]")
        content_src, reason = _resolve_no_webcam_content_src(src_w, src_h, config, content_result)
        if not suppress_logs:
            console.print(f"[cyan]Layout: slot-only source={content_src}, reason={reason}[/cyan]")
        return LayoutSpec(
            has_webcam=False,
            mode="slot_only",
            content_src=content_src,
            content_out=(0, 0, out_w, out_h),
            banner_out=None,
            output_size=(out_w, out_h),
            blur_bg_filter="",
            subtitle_safe_y=int(out_h * 0.16),
        )

    if layout_mode == "cinema":
        manual_cinema_crop = _resolved_manual_cinema_crop(config, src_w, src_h)
        manual_slot_crop = _resolved_manual_slot_crop(config, src_w, src_h)
        if manual_cinema_crop is not None:
            base_src = manual_cinema_crop
            reason = "manual_cinema_crop"
        elif manual_slot_crop is not None:
            base_src = manual_slot_crop
            reason = "manual_slot_crop"
        else:
            base_src = (0, 0, src_w, src_h)
            reason = "full_frame"
        banner_out = None
        if _banner_enabled(config):
            if webcam_result.has_webcam and webcam_result.region is not None:
                wc_preview_h = int(round(out_h * top_ratio))
                if wc_preview_h % 2:
                    wc_preview_h += 1
                wc_preview_h = max(2, min(out_h - 2, wc_preview_h))
                banner_out = _cinema_banner_box(out_w, out_h, wc_preview_h, out_h - wc_preview_h, config)
            else:
                banner_out = _cinema_banner_box(out_w, out_h, 0, out_h, config)

        if webcam_result.has_webcam and webcam_result.region is not None:
            wr = webcam_result.region
            if not suppress_logs:
                console.print("[cyan]Layout: cinema mode with webcam[/cyan]")
            wc_out_h = int(round(out_h * top_ratio))
            if wc_out_h % 2:
                wc_out_h += 1
            wc_out_h = max(2, min(out_h - 2, wc_out_h))
            wc_src = _clamp_crop(wr.x, wr.y, wr.w, wr.h, src_w, src_h)
            content_panel_h = max(2, out_h - wc_out_h)
            content_src, sharp_box = _cinema_focus_crop(base_src, src_w, src_h, out_w, content_panel_h)
            if not suppress_logs:
                console.print(
                    f"[cyan]Layout: cinema source={content_src}, "
                    f"webcam_src={wc_src}, content_panel=(0,{wc_out_h},{out_w},{content_panel_h}), "
                    f"sharp_box={sharp_box}, reason={reason}[/cyan]"
                )
            return LayoutSpec(
                has_webcam=True,
                mode="cinema",
                webcam_out=(0, 0, out_w, wc_out_h),
                webcam_src=wc_src,
                content_src=content_src,
                content_out=(0, wc_out_h, out_w, content_panel_h),
                banner_out=banner_out,
                output_size=(out_w, out_h),
                blur_bg_filter="",
                subtitle_safe_y=wc_out_h + content_panel_h - 150,
            )

        if not suppress_logs:
            console.print("[cyan]Layout: cinema mode (zoomed no-webcam composition)[/cyan]")
        vertical_offset = 0
        if _banner_enabled(config):
            banner = getattr(config, "banner", None)
            vertical_offset = int(
                round(out_h * float(getattr(banner, "cinema_raise_ratio", 0.10)))
            )
        content_src, content_out = _cinema_focus_crop(
            base_src,
            src_w,
            src_h,
            out_w,
            out_h,
            vertical_offset_px=vertical_offset,
        )
        if not suppress_logs:
            console.print(
                f"[cyan]Layout: cinema source={content_src}, "
                f"sharp_out={content_out}, reason={reason}[/cyan]"
            )
        return LayoutSpec(
            has_webcam=False,
            mode="cinema",
            content_src=content_src,
            content_out=content_out,
            banner_out=banner_out,
            output_size=(out_w, out_h),
            blur_bg_filter="",
            subtitle_safe_y=int(out_h * 0.16),
        )

    if webcam_result.has_webcam and webcam_result.region is not None:
        wr = webcam_result.region
        if not suppress_logs:
            console.print(f"[cyan]Layout: webcam mode ({wr.w}x{wr.h} at {wr.x},{wr.y})[/cyan]")

        # Webcam panel in output: top portion
        wc_out_h = int(round(out_h * top_ratio))
        if wc_out_h % 2:
            wc_out_h += 1
        wc_out_h = max(2, min(out_h - 2, wc_out_h))
        wc_out_w = out_w
        wc_out_x = 0
        wc_out_y = 0

        wc_src = _clamp_crop(wr.x, wr.y, wr.w, wr.h, src_w, src_h)
        if content_result is not None and content_result.has_content:
            content_src = _clamp_crop(*content_result.crop, src_w, src_h)
            if not suppress_logs:
                console.print(
                    "[cyan]Layout: detected split "
                    f"webcam_src={wc_src}, slot_src={content_src}, "
                    f"reason={content_result.reason}[/cyan]"
                )
        else:
            content_src = centered_content_crop(src_w, src_h)
            if not suppress_logs:
                console.print(
                    "[cyan]Layout: detected webcam with centered content fallback "
                    f"webcam_src={wc_src}, slot_src={content_src}[/cyan]"
                )

        # Content output: bottom portion
        content_out_h = out_h - wc_out_h
        content_out_w = out_w
        content_out_x = 0
        content_out_y = wc_out_h

        # Build blur background filter for content area
        # Use the main content source scaled up for blur
        blur_bg = (
            f"[main]scale={content_out_w}:{content_out_h}:force_original_aspect_ratio=increase,"
            f"crop={content_out_w}:{content_out_h},"
            f"gblur=sigma=20[bg];"
        )

        return LayoutSpec(
            has_webcam=True,
            mode="auto",
            webcam_out=(wc_out_x, wc_out_y, wc_out_w, wc_out_h),
            webcam_src=wc_src,
            content_src=content_src,
            content_out=(content_out_x, content_out_y, content_out_w, content_out_h),
            banner_out=None,
            output_size=(out_w, out_h),
            blur_bg_filter=blur_bg,
            subtitle_safe_y=content_out_y + content_out_h - 150,
        )
    else:
        if not suppress_logs:
            console.print("[cyan]Layout: no-webcam mode (centered content with blur fill)[/cyan]")

        content_src, reason = _resolve_no_webcam_content_src(src_w, src_h, config, content_result)
        if not suppress_logs:
            console.print(
                f"[cyan]Layout: no-webcam slot_src={content_src}, "
                f"reason={reason}[/cyan]"
            )

        # Blur background fill: scale+crop source for blur, then overlay sharp content
        blur_bg = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},"
            f"gblur=sigma=20[bg];"
        )

        return LayoutSpec(
            has_webcam=False,
            mode="auto",
            content_src=content_src,
            content_out=(0, 0, out_w, out_h),
            banner_out=None,
            output_size=(out_w, out_h),
            blur_bg_filter=blur_bg,
            subtitle_safe_y=int(out_h * 0.16),
        )


def build_composite_filter(layout: LayoutSpec, src_count: int, input_label: str = "0:v") -> tuple[str, str]:
    """
    Build the ffmpeg filter complex for compositing.
    Returns (filter_string, output_label).
    """
    if layout.has_webcam:
        ws = layout.webcam_src
        wo = layout.webcam_out
        cs = layout.content_src
        co = layout.content_out

        # Split into 3: webcam, content, blur-bg
        filters = (
            f"[{input_label}]split=3[wc_src][content_src][blur_src];"
            # Webcam branch
            f"[wc_src]crop={ws[2]}:{ws[3]}:{ws[0]}:{ws[1]},"
            f"scale={wo[2]}:{wo[3]}:force_original_aspect_ratio=increase:force_divisible_by=2,"
            f"crop={wo[2]}:{wo[3]}[wc_scaled];"
            # Content branch
            f"[content_src]crop={cs[2]}:{cs[3]}:{cs[0]}:{cs[1]},"
            f"scale={co[2]}:{co[3]}:force_original_aspect_ratio=decrease:force_divisible_by=2[content_scaled];"
            # Blur background: use the same main content crop, not the full browser frame.
            f"[blur_src]crop={cs[2]}:{cs[3]}:{cs[0]}:{cs[1]},"
            f"scale={co[2]}:{co[3]}:force_original_aspect_ratio=increase,"
            f"crop={co[2]}:{co[3]},"
            f"gblur=sigma=20[bg];"
            # Overlay content on blur bg
            f"[bg][content_scaled]overlay=(W-w)/2:(H-h)/2[content_filled];"
            # Final 1080x1920 composition: webcam panel over content panel.
            f"[wc_scaled][content_filled]vstack=inputs=2[composed]"
        )
        return filters, "composed"
    else:
        cs = layout.content_src
        co = layout.content_out
        frame_w, frame_h = layout.output_size
        # Split source: one for content, one for blur bg
        # Use scale with force_divisible_by=2 for h264 compatibility
        filters = (
            f"[{input_label}]split=2[content_src][bg_src];"
            f"[content_src]crop={cs[2]}:{cs[3]}:{cs[0]}:{cs[1]},"
            f"scale={co[2]}:{co[3]}:force_original_aspect_ratio=decrease:force_divisible_by=2[content_scaled];"
            f"[bg_src]crop={cs[2]}:{cs[3]}:{cs[0]}:{cs[1]},"
            f"scale={frame_w}:{frame_h}:force_original_aspect_ratio=increase,"
            f"crop={frame_w}:{frame_h},"
            f"gblur=sigma=20[bg];"
            f"[bg][content_scaled]overlay={co[0]}+({co[2]}-w)/2:{co[1]}+({co[3]}-h)/2[composed]"
        )
        return filters, "composed"
