"""CTA pause effect: freeze + grayscale + typewriter text."""

from __future__ import annotations

import os
import random
import textwrap
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig

console = get_console()

# Cache for detected font paths by CTA language
_font_path_cache: dict[str, str] = {}
DEFAULT_CTA_TEXT_EN = "THE GAME IN BIO"


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _resolve_optional_path(path: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(_project_root(), path))


def _find_font_path(config: Optional[AppConfig] = None) -> str:
    """Find a usable font path for drawtext filter."""
    global _font_path_cache
    custom_font = ""
    if config is not None:
        custom_font = _resolve_optional_path(getattr(config.cta, "font_path", "") or "")
        if custom_font and os.path.exists(custom_font):
            return custom_font

    cache_key = _cta_language(config) if config is not None else "en"
    if cache_key in _font_path_cache:
        return _font_path_cache[cache_key]

    # Try common Windows font locations. Arial Black/Bold are safer for Cyrillic;
    # Impact stays available for punchy English CTA text.
    if config is not None and _cta_language(config) == "ru":
        windows_candidates = [
            "C:/Windows/Fonts/ariblk.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/impact.ttf",
        ]
    else:
        windows_candidates = [
            "C:/Windows/Fonts/impact.ttf",
            "C:/Windows/Fonts/ariblk.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]

    candidates = [
        os.path.join(_project_root(), "fonts", "cta.ttf"),
        *windows_candidates,
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/ARIAL.TTF",
    ]

    # Try to find any TTF font that exists
    for path in candidates:
        if os.path.exists(path):
            _font_path_cache[cache_key] = path
            return path

    # If no font found, return empty (drawtext will use default)
    _font_path_cache[cache_key] = ""
    return _font_path_cache[cache_key]


def _escape_drawtext_text(text: str) -> str:
    """Escape a string for ffmpeg drawtext text='...'."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("%", "\\%")
    )


def _drawtext_font_option(config: AppConfig) -> str:
    """Return a drawtext fontfile option that works in a Windows shell."""
    font = _find_font_path(config)
    if not font and getattr(config.cta, "font_name", ""):
        font_name = _escape_drawtext_text(config.cta.font_name)
        return f"font='{font_name}':"
    if not font:
        return ""
    font = font.replace("\\", "/").replace(":", "\\:")
    return f"fontfile='{font}':"


def _cta_language(config: AppConfig) -> str:
    cta_lang = (getattr(config.cta, "language", "auto") or "auto").lower()
    if cta_lang in {"ru", "en"}:
        return cta_lang
    language = (config.language or "auto").lower()
    return language if language in {"ru", "en"} else "en"


def pick_cta_text(config: AppConfig) -> str:
    """Pick CTA text, possibly from variants list."""
    lang = _cta_language(config)
    text_mode = (getattr(config.cta, "text_mode", "file") or "file").lower()
    custom_text = _clean_cta_text(getattr(config.cta, "custom_text", "") or "")
    if text_mode == "custom" and custom_text:
        return custom_text

    if text_mode == "file":
        file_variants = _load_cta_text_variants(config, lang)
        if file_variants:
            if config.variation.enabled:
                return random.choice(file_variants)
            return file_variants[0]

    if lang == "ru":
        variants = getattr(config.variation, "cta_text_variants_ru", [])
        if config.variation.enabled and variants:
            return random.choice(variants)
        return getattr(config.cta, "text_ru", "ИГРА В ОПИСАНИИ")

    variants = getattr(config.variation, "cta_text_variants", [])
    if config.variation.enabled and variants:
        return random.choice(variants)
    if config.cta.text and config.cta.text != DEFAULT_CTA_TEXT_EN:
        return config.cta.text
    return getattr(config.cta, "text_en", DEFAULT_CTA_TEXT_EN)


def _clean_cta_text(text: str) -> str:
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())


def _load_cta_text_variants(config: AppConfig, lang: str) -> list[str]:
    configured_path = getattr(config.cta, "text_file_path", "") or ""
    if configured_path:
        paths = [configured_path]
    elif lang == "ru":
        paths = [getattr(config.cta, "text_file_path_ru", "") or "cta_texts/ru.txt"]
    else:
        paths = [getattr(config.cta, "text_file_path_en", "") or "cta_texts/en.txt"]

    variants: list[str] = []
    for raw_path in paths:
        path = _resolve_optional_path(raw_path)
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    text = _clean_cta_text(line)
                    if text and not text.startswith("#"):
                        variants.append(text)
        except OSError:
            continue
    return variants


def prepare_cta_text_layout(
    text: str,
    config: AppConfig,
    output_width: Optional[int] = None,
) -> tuple[list[str], int]:
    """
    Wrap CTA text and choose a font size that fits inside the vertical frame.

    The estimate is intentionally conservative because ffmpeg drawtext cannot
    auto-fit text to a bounding box. This keeps long custom captions inside the
    video instead of letting them bleed past the edges.
    """
    clean = _clean_cta_text(text) or DEFAULT_CTA_TEXT_EN
    out_w = int(output_width or getattr(config.export, "width", 1080) or 1080)
    base_font_size = max(24, int(getattr(config.cta, "font_size", 78) or 78))
    min_font_size = max(18, int(getattr(config.cta, "min_font_size", 34) or 34))
    max_lines = max(1, int(getattr(config.cta, "max_text_lines", 3) or 3))
    width_ratio = float(getattr(config.cta, "max_text_width_ratio", 0.86) or 0.86)
    width_ratio = max(0.45, min(0.96, width_ratio))
    max_width_px = max(200, out_w * width_ratio)

    # Average uppercase/Cyrillic glyphs are wide in Impact/Arial Black.
    char_ratio = 0.62
    max_chars = max(6, int(max_width_px / max(1.0, base_font_size * char_ratio)))
    lines = _wrap_text_to_lines(clean, max_chars, max_lines)
    longest_line = max((len(line) for line in lines), default=len(clean))
    fit_size = int(max_width_px / max(1.0, longest_line * char_ratio))
    font_size = max(min_font_size, min(base_font_size, fit_size))

    # If a very long custom text still cannot fit, shrink all the way down to
    # the configured minimum. The line wrapping keeps it visually contained.
    return lines, font_size


def _wrap_text_to_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    width = max_chars
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    while len(lines) > max_lines and width < max(len(text), max_chars):
        width += 2
        lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)

    if len(lines) > max_lines or any(len(line) > width * 1.25 for line in lines):
        width = max(max_chars, int(len(text) / max_lines) + 1)
        lines = textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False)

    if len(lines) > max_lines:
        kept = lines[: max_lines - 1]
        kept.append(" ".join(lines[max_lines - 1:]))
        lines = kept
    return [line.strip() for line in lines if line.strip()] or [text]


def _partial_cta_lines(lines: list[str], visible_chars: int) -> list[str]:
    remaining = max(0, visible_chars)
    partials: list[str] = []
    for line in lines:
        take = min(len(line), remaining)
        partials.append(line[:take])
        remaining -= take
    return partials


def _line_y_expr(line_index: int, line_count: int, font_size: int) -> str:
    line_gap = font_size * 1.12
    total_height = (line_count - 1) * line_gap
    offset = line_index * line_gap - total_height / 2
    if offset >= 0:
        return f"(h*0.42)+{offset:.1f}"
    return f"(h*0.42)-{abs(offset):.1f}"


def _drawtext_for_lines(
    lines: list[str],
    drawtext_style: str,
    enable_expr: str = "",
) -> str:
    line_count = len(lines)
    filters: list[str] = []
    for idx, line in enumerate(lines):
        if not line:
            continue
        escaped = _escape_drawtext_text(line)
        y_expr = _line_y_expr(idx, line_count, _style_font_size(drawtext_style))
        enable_part = f"enable='{enable_expr}':" if enable_expr else ""
        filters.append(
            "drawtext="
            f"text='{escaped}':"
            f"{drawtext_style}"
            "x=(w-text_w)/2:"
            f"y={y_expr}:"
            f"{enable_part}"
            "borderw=5:"
            "box=1:boxcolor=black@0.35:boxborderw=18"
        )
    return ",".join(filters)


def _style_font_size(drawtext_style: str) -> int:
    marker = "fontsize="
    start = drawtext_style.find(marker)
    if start < 0:
        return 78
    start += len(marker)
    end = drawtext_style.find(":", start)
    raw = drawtext_style[start:] if end < 0 else drawtext_style[start:end]
    try:
        return int(float(raw))
    except ValueError:
        return 78


def _effective_freeze_duration(
    config: AppConfig,
    freeze_duration_sec: Optional[float] = None,
) -> float:
    freeze_dur = (
        config.cta.freeze_duration_sec
        if freeze_duration_sec is None
        else freeze_duration_sec
    )
    return max(0.1, float(freeze_dur))


def pick_cta_trigger_time(
    clip_duration: float,
    config: AppConfig,
    freeze_duration_sec: Optional[float] = None,
) -> float:
    """Pick when to trigger CTA within the allowed range."""
    low, high = config.cta.trigger_range_sec
    freeze_dur = _effective_freeze_duration(config, freeze_duration_sec)
    # Clamp to clip duration
    high = min(high, clip_duration - freeze_dur - 1.0)
    if high <= low:
        low = max(1.0, clip_duration * 0.2)
        high = min(clip_duration * 0.4, clip_duration - 1.0)
    if high <= low:
        return low

    if config.variation.enabled and config.variation.cta_time_randomization:
        return random.uniform(low, high)
    return low


def build_cta_filter(
    clip_duration: float,
    cta_text: str,
    config: AppConfig,
    has_voice_mp3: bool = False,
) -> tuple[str, float, float]:
    """
    Build ffmpeg filter for CTA effect.

    Returns:
        - filter_complex string (to be inserted into main filter)
        - cta_start_sec: when CTA begins
        - cta_end_sec: when CTA ends
    """
    cta_start = pick_cta_trigger_time(clip_duration, config)
    freeze_dur = config.cta.freeze_duration_sec
    cta_end = cta_start + freeze_dur

    grayscale = config.cta.grayscale_strength
    typewriter_speed = config.cta.typewriter_speed  # sec per char

    # Build the CTA effect as a separate filter chain
    # 1. Freeze frame at cta_start
    # 2. Apply grayscale
    # 3. Overlay typewriter text

    # We'll use the `trim` + `freeze` approach:
    # - Normal video 0..cta_start
    # - Frozen + grayscale cta_start..cta_end with text overlay
    # - Normal video cta_end..end

    # For the typewriter effect, we generate multiple text overlay events
    # Each character appears sequentially

    text_filters = []
    if config.cta.typewriter_enabled:
        chars = list(cta_text)
        for i, ch in enumerate(chars):
            char_start = cta_start + 0.3 + i * typewriter_speed
            if char_start >= cta_end:
                break
            # Escape special chars for drawtext
            escaped_ch = ch.replace("'", "\\'").replace(":", "\\:")
            # Build partial text up to this character
            partial = cta_text[:i+1]
            escaped_partial = partial.replace("'", "\\'").replace(":", "\\:")
            text_filters.append(
                f"drawtext=text='{escaped_partial}':"
                f"fontsize=60:fontcolor=white:fontfile=arial.ttf:"
                f"x=(w-text_w)/2:y=h*0.45:"
                f"enable='between(t,{char_start:.2f},{cta_end:.2f})':"
                f"shadowcolor=black:shadowx=2:shadowy=2"
            )
    else:
        # Static text
        escaped_text = cta_text.replace("'", "\\'").replace(":", "\\:")
        text_filters.append(
            f"drawtext=text='{escaped_text}':"
            f"fontsize=60:fontcolor=white:fontfile=arial.ttf:"
            f"x=(w-text_w)/2:y=h*0.45:"
            f"enable='between(t,{cta_start:.2f},{cta_end:.2f})':"
            f"shadowcolor=black:shadowx=2:shadowy=2"
        )

    # Build the full filter:
    # Split into pre, cta, post
    # CTA segment: freeze + hue (grayscale) + text
    # We use: trim, setpts, freeze via tpad, hue, text overlay

    # Simpler approach: use a single filter chain with enable conditions
    # Grayscale during CTA window
    grayscale_filter = (
        f"hue=s=1-{grayscale}:enable='between(t,{cta_start:.2f},{cta_end:.2f})'"
    )

    return grayscale_filter, text_filters, cta_start, cta_end


def build_cta_segment_filter(
    clip_duration: float,
    cta_text: str,
    config: AppConfig,
    input_label: str = "composed",
    cta_start_sec: Optional[float] = None,
    freeze_duration_sec: Optional[float] = None,
) -> tuple[str, float, float]:
    """
    Build a filter that applies CTA effect inline.
    Uses a simplified approach: freeze frame + grayscale + drawtext via trim/tpad/concat.

    Returns (filter_string, cta_start, cta_end).
    """
    cta_start = (
        float(cta_start_sec)
        if cta_start_sec is not None
        else pick_cta_trigger_time(
            clip_duration,
            config,
            freeze_duration_sec=freeze_duration_sec,
        )
    )
    freeze_dur = _effective_freeze_duration(config, freeze_duration_sec)
    cta_end = cta_start + freeze_dur

    grayscale_strength = float(config.cta.grayscale_strength)
    grayscale_strength = max(0.0, min(1.0, grayscale_strength))
    font_option = _drawtext_font_option(config)
    cta_lines, font_size = prepare_cta_text_layout(cta_text, config)
    font_color = getattr(config.cta, "font_color", "0xFFD200") or "0xFFD200"
    border_color = getattr(config.cta, "border_color", "black") or "black"
    shadow_color = getattr(config.cta, "shadow_color", "red@0.85") or "red@0.85"
    drawtext_style = (
        f"{font_option}"
        f"fontsize={font_size}:fontcolor={font_color}:"
        f"bordercolor={border_color}:"
        f"shadowcolor={shadow_color}:shadowx=5:shadowy=5:"
    )

    # Simplified approach: use trim + tpad for freeze, then concat
    # Connect from the input label (e.g., [composed]) and continue the chain
    # NOTE: freeze segment has PTS reset (setpts=PTS-STARTPTS), so its time starts at 0.
    # That allows clean "typewriter" enables using between(t, ...).

    # Build typewriter drawtext chain on the frozen segment.
    # We gradually reveal the string over the freeze duration.
    drawtext_chain = ""
    if config.cta.typewriter_enabled and config.cta.typewriter_speed > 0:
        per_char = float(config.cta.typewriter_speed)
        per_char = max(0.01, min(0.5, per_char))
        # Small initial delay so the freeze "lands" before text starts.
        start_delay = 0.15
        parts: list[str] = []
        total_chars = sum(len(line) for line in cta_lines)
        for i in range(1, total_chars + 1):
            t0 = start_delay + (i - 1) * per_char
            if t0 >= freeze_dur:
                break
            t1 = min(freeze_dur, start_delay + i * per_char)
            if i == total_chars or t1 <= t0:
                t1 = freeze_dur
            partial_lines = _partial_cta_lines(cta_lines, i)
            part = _drawtext_for_lines(
                partial_lines,
                drawtext_style,
                enable_expr=f"between(t,{t0:.3f},{t1:.3f})",
            )
            if part:
                parts.append(part)
        if parts:
            drawtext_chain = "," + ",".join(parts)
    else:
        # Static text during the entire freeze window.
        drawtext_chain = "," + _drawtext_for_lines(cta_lines, drawtext_style)

    # Grayscale: allow partial desaturation via hue saturation.
    # 1.0 => fully grayscale (s=0), 0.0 => no change (s=1).
    sat = 1.0 - grayscale_strength
    hue_filter = f"hue=s={sat:.3f}"

    frame_grab_end = min(clip_duration, cta_start + 0.08)

    filter_parts = [
        # Take input from previous filter and split into 3 streams
        f"[{input_label}]split=3[pre_cta][cta_frame][post_cta];",

        # 1) Pre-CTA: normal video from 0 to cta_start
        f"[pre_cta]trim=0:{cta_start:.3f},setpts=PTS-STARTPTS[pre_out];",

        # 2) CTA freeze: grab frame at cta_start, hold it, apply grayscale + text
        # Use drawtext without explicit font (will use default)
        f"[cta_frame]trim=start={cta_start:.3f}:end={frame_grab_end:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"tpad=stop_duration={freeze_dur:.3f}:stop_mode=clone,"
        f"trim=0:{freeze_dur:.3f},"
        f"scale='ceil(iw/2)*2:ceil(ih/2)*2',"
        f"{hue_filter}"
        f"{drawtext_chain},"
        f"setpts=PTS-STARTPTS[freeze_out];",

        # 3) Post-CTA: continue from the same frame so the freeze is inserted.
        f"[post_cta]trim=start={cta_start:.3f}:end=99999,setpts=PTS-STARTPTS[post_out];",

        # 4) Concatenate the 3 segments
        "[pre_out][freeze_out][post_out]concat=n=3:v=1:a=0[cta_out]"
    ]

    filter_str = ";".join(filter_parts)
    return filter_str, cta_start, cta_end
