"""Subtitle generation with word-level timing (ASS format)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig, SUBTITLE_THEMES

console = get_console()


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class SubtitleEvent:
    start: float
    end: float
    text: str
    # For word-by-word: list of (word, start, end)
    words: list[WordTiming] = None


def clean_text(text: str) -> str:
    """Clean ASR output text."""
    # Remove filler words and artifacts
    text = re.sub(r'\[.*?\]', '', text)  # [music], [laughter], etc.
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove common ASR artifacts
    text = re.sub(r'\b(um|uh|mm|hm|ah)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    # One-word captions should not carry punctuation such as ASR-added commas.
    text = text.replace(",", "").replace("،", "").replace("，", "")
    text = text.strip(" \t\r\n\"'“”‘’«».,!?;:…")
    return text


def generate_word_subtitles(
    asr_words: list[dict],
    config: AppConfig,
    clip_start: float = 0.0,
    cta_insert_start: Optional[float] = None,
    cta_insert_duration: float = 0.0,
) -> list[SubtitleEvent]:
    """
    Convert ASR word-level timings into subtitle events.
    Each word becomes a separate event for word-by-word display and stays until
    the next spoken word starts, capped at 3 seconds.
    """
    if not asr_words:
        return []

    max_words = max(1, int(config.subtitles_max_words_per_group))
    cta_shift_enabled = cta_insert_start is not None and cta_insert_duration > 0

    words: list[WordTiming] = []
    for word_info in asr_words:
        word = word_info.get("word", "").strip()
        start = float(word_info.get("start", 0.0))
        end = float(word_info.get("end", start))

        if not word:
            continue

        # Adjust timing relative to clip start
        adj_start = start - clip_start
        adj_end = end - clip_start

        if adj_end <= 0:
            continue  # Before clip start

        cleaned = clean_text(word)
        if not cleaned:
            continue

        adj_start = max(0.0, adj_start)
        adj_end = max(adj_start + 0.05, adj_end)

        if cta_shift_enabled and adj_start >= float(cta_insert_start):
            adj_start += cta_insert_duration
            adj_end += cta_insert_duration

        words.append(WordTiming(
            word=cleaned,
            start=adj_start,
            end=adj_end,
        ))

    if not words:
        return []

    words.sort(key=lambda item: item.start)
    min_word_gap = 0.08
    prev_start = -1.0
    for word in words:
        if word.start <= prev_start:
            shift = prev_start + min_word_gap - word.start
            word.start += shift
            word.end += shift
        word.end = max(word.end, word.start + 0.05)
        prev_start = word.start

    groups: list[list[WordTiming]] = [
        words[i : i + max_words] for i in range(0, len(words), max_words)
    ]
    events: list[SubtitleEvent] = []
    cta_start = float(cta_insert_start) if cta_insert_start is not None else None

    for idx, group in enumerate(groups):
        event_start = group[0].start
        next_start = groups[idx + 1][0].start if idx + 1 < len(groups) else None
        event_end = event_start + 3.0

        if next_start is not None and next_start > event_start:
            event_end = min(event_end, next_start)

        # Do not let regular subtitles sit underneath the CTA freeze text.
        if cta_shift_enabled and cta_start is not None and event_start < cta_start < event_end:
            event_end = cta_start

        if event_end <= event_start:
            event_end = event_start + 0.25

        event_words = [
            WordTiming(word=w.word, start=event_start, end=event_end)
            for w in group
        ]
        events.append(SubtitleEvent(
            start=event_start,
            end=event_end,
            text=" ".join(w.word for w in group),
            words=event_words,
        ))

    return events


def ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format: H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_file(
    events: list[SubtitleEvent],
    output_path: str,
    config: AppConfig,
    theme_override: Optional[str] = None,
) -> str:
    """
    Generate an ASS subtitle file with word-by-word animation.
    Uses CapCut-style appearance: each word pops in individually.
    """
    if not events:
        # Create empty ASS file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("[Script Info]\nTitle: Empty\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n")
            f.write("[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        return output_path

    # Determine vertical position based on config
    theme_name = theme_override or config.subtitles_theme
    theme = SUBTITLE_THEMES.get(theme_name, SUBTITLE_THEMES["red"])
    margin_v = theme.get("margin_v", 80)
    alignment = theme.get("alignment", 2)  # 2 = bottom-center
    position_override = ""
    if config.subtitles_position == "slot_middle":
        # Middle-center. Keep margin lower to avoid covering faces/webcam.
        alignment = 5
        margin_v = 0
    elif config.subtitles_position in ("between_webcam_and_game", "between"):
        alignment = 5
        margin_v = 0
        pos_x = int(config.export.width / 2)
        pos_y = int(config.export.height * float(config.subtitles_between_y_ratio))
        position_override = f"{{\\an5\\pos({pos_x},{pos_y})}}"
    elif config.subtitles_position in ("slot_top", "top"):
        alignment = 8
        margin_v = 0
        pos_x = int(config.export.width / 2)
        pos_y = int(config.export.height * 0.14)
        position_override = f"{{\\an8\\pos({pos_x},{pos_y})}}"
    elif config.subtitles_position == "slot_bottom":
        # Keep bottom subtitles inside the main slot area, above the CTA gap.
        margin_v = max(int(margin_v), int(config.export.height * 0.17))

    template = _load_subtitle_template(config)
    if template is not None:
        header, style_name, event_name = template
    else:
        font_name = _subtitle_font_name(config, theme)
        style_name = "Default"
        event_name = ""
        # Build ASS header
        header = f"""[Script Info]
Title: StreamCuter Subtitles
ScriptType: v4.00+
PlayResX: {config.export.width}
PlayResY: {config.export.height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font_name},{theme['font_size']},{theme['primary_colour']},{theme['secondary_colour']},{theme['outline_colour']},{theme['back_colour']},{theme['bold']},{theme['italic']},{theme['underline']},{theme['strike_out']},{theme['scale_x']},{theme['scale_y']},{theme['spacing']},{theme['angle']},{theme['border_style']},{theme['outline']},{theme['shadow']},{alignment},{theme['margin_l']},{theme['margin_r']},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    for event in events:
        if event.words and len(event.words) == 1:
            # Word-by-word: single word event
            w = event.words[0]
            # Escape ASS special characters properly
            safe_word = _escape_ass_text(w.word)
            line = f"Dialogue: 0,{ass_time(w.start)},{ass_time(w.end)},{style_name},{event_name},0,0,0,,{position_override}{safe_word}"
            lines.append(line)
        else:
            # Multi-word fallback
            safe_text = _escape_ass_text(event.text)
            lines.append(f"Dialogue: 0,{ass_time(event.start)},{ass_time(event.end)},{style_name},{event_name},0,0,0,,{position_override}{safe_text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(lines))
        f.write("\n")

    return output_path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _subtitle_language(config: AppConfig) -> str:
    lang = (config.language or "auto").lower()
    return lang if lang in {"ru", "en"} else "en"


def _resolve_project_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return _project_root() / p


def _load_subtitle_template(config: AppConfig) -> Optional[tuple[str, str, str]]:
    """
    Load only one ASS template for the selected language and keep its style header.
    Dialogue rows from the template are ignored; real ASR events are generated below.
    """
    lang = _subtitle_language(config)
    template_path = (
        getattr(config, "subtitles_template_ru", "")
        if lang == "ru"
        else getattr(config, "subtitles_template_en", "")
    )
    if not template_path:
        return None

    path = _resolve_project_path(template_path)
    if not path.exists():
        console.print(f"[yellow]Subtitle template not found, using generated style: {path}[/yellow]")
        return None

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        console.print(f"[yellow]Could not read subtitle template {path}: {e}[/yellow]")
        return None

    header_lines: list[str] = []
    style_name = "Default"
    in_events = False
    found_event_format = False
    for line in raw_lines:
        stripped = line.strip()
        lower = stripped.lower()

        if lower.startswith("playresx:"):
            line = f"PlayResX: {config.export.width}"
        elif lower.startswith("playresy:"):
            line = f"PlayResY: {config.export.height}"
        elif lower.startswith("style:") and style_name == "Default":
            payload = stripped.split(":", 1)[1].strip()
            style_name = payload.split(",", 1)[0].strip() or "Default"

        header_lines.append(line)

        if lower == "[events]":
            in_events = True
        elif in_events and lower.startswith("format:"):
            found_event_format = True
            break

    if not found_event_format:
        console.print(f"[yellow]Subtitle template has no Events format, using generated style: {path}[/yellow]")
        return None

    if len(header_lines) < 2 or header_lines[-1].strip():
        header_lines.append("")
    return "\n".join(header_lines), style_name, lang


def _subtitle_font_name(config: AppConfig, theme: dict) -> str:
    """Pick the ASS font family. If a custom font file exists, use its stem as a best-effort family name."""
    font_path = getattr(config, "subtitles_font_path", "") or ""
    if font_path and os.path.exists(font_path):
        return Path(font_path).stem
    return getattr(config, "subtitles_font_name", "") or theme["font_name"]


def _escape_ass_text(text: str) -> str:
    """Escape special ASS characters in text."""
    # Escape backslashes first to avoid double-escaping
    text = text.replace("\\", "\\\\")
    # Escape ASS curly braces
    text = text.replace("{", "\\{").replace("}", "\\}")
    return text


def generate_simple_srt(
    events: list[SubtitleEvent],
    output_path: str,
) -> str:
    """Generate simple SRT as fallback."""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, event in enumerate(events, 1):
            def srt_time(s):
                if s < 0:
                    s = 0
                h = int(s // 3600)
                m = int((s % 3600) // 60)
                sec = int(s % 60)
                ms = int((s % 1) * 1000)
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

            f.write(f"{i}\n")
            f.write(f"{srt_time(event.start)} --> {srt_time(event.end)}\n")
            f.write(f"{event.text}\n\n")

    return output_path
