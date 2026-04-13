"""CTA pause effect: freeze + grayscale + typewriter text."""

from __future__ import annotations

import os
import random
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
    escaped_text = _escape_drawtext_text(cta_text)
    font_option = _drawtext_font_option(config)
    font_size = max(40, min(140, int(getattr(config.cta, "font_size", 78))))
    font_color = getattr(config.cta, "font_color", "0xFFD200") or "0xFFD200"
    border_color = getattr(config.cta, "border_color", "black") or "black"
    shadow_color = getattr(config.cta, "shadow_color", "red@0.85") or "red@0.85"
    drawtext_style = (
        f"{font_option}"
        f"fontsize={font_size}:fontcolor={font_color}:"
        "x=(w-text_w)/2:y=h*0.42:"
        f"borderw=5:bordercolor={border_color}:"
        f"shadowcolor={shadow_color}:shadowx=5:shadowy=5:"
        "box=1:boxcolor=black@0.35:boxborderw=18:"
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
        for i in range(1, len(cta_text) + 1):
            t0 = start_delay + (i - 1) * per_char
            if t0 >= freeze_dur:
                break
            t1 = min(freeze_dur, start_delay + i * per_char)
            if i == len(cta_text) or t1 <= t0:
                t1 = freeze_dur
            partial = _escape_drawtext_text(cta_text[:i])
            parts.append(
                "drawtext="
                f"text='{partial}':"
                f"{drawtext_style}"
                f"enable='between(t,{t0:.3f},{t1:.3f})'"
            )
        if parts:
            drawtext_chain = "," + ",".join(parts)
    else:
        # Static text during the entire freeze window.
        drawtext_chain = (
            ",drawtext="
            f"text='{escaped_text}':"
            f"{drawtext_style.rstrip(':')}"
        )

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
