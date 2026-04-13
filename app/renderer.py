"""Final video renderer - orchestrates the full pipeline."""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig, SUBTITLE_THEMES
from app.layout import LayoutSpec, build_composite_filter
from app.probe import VideoInfo
from app.highlight_detector import HighlightSegment
from app.subtitles import generate_ass_file, generate_word_subtitles
from app.cta_pause import build_cta_segment_filter, pick_cta_text, pick_cta_trigger_time
from app.audio_mix import pick_random_track, build_final_audio_mix
from app.utils.helpers import ensure_dir, fmt_time, ffmpeg_exe, ffprobe_exe, safe_filename

console = get_console()


def render_clip(
    video_path: str,
    video_info: VideoInfo,
    segment: HighlightSegment,
    layout: LayoutSpec,
    config: AppConfig,
    output_path: str,
    temp_dir: str,
    asr_words: Optional[list[dict]] = None,
    clip_index: int = 0,
) -> bool:
    """
    Render a single highlight clip with all effects.

    Returns True on success.
    """
    clip_dur = segment.end_sec - segment.start_sec
    console.print(f"\n[cyan]Rendering clip {clip_index + 1}: "
                  f"{fmt_time(segment.start_sec)} - {fmt_time(segment.end_sec)} "
                  f"({clip_dur:.1f}s)[/cyan]")

    # Apply variation seed
    if config.variation.enabled:
        random.seed(42 + clip_index)

    # Pick subtitle theme variant
    theme = config.subtitles_theme
    if config.variation.enabled and config.variation.subtitle_style_variants:
        theme = random.choice(list(SUBTITLE_THEMES.keys()))

    # Optional CTA voice is resolved before subtitle timings and video filters,
    # because the freeze length should match the selected voiceover length.
    voice_path = None
    voice_duration = None
    if config.cta.enabled and config.cta.voice_mp3_path:
        voice_path = _resolve_existing_media_path(config.cta.voice_mp3_path)
        if voice_path:
            voice_duration = _probe_media_duration(voice_path)
            if voice_duration and voice_duration > 0:
                console.print(
                    f"[dim]CTA voice: {Path(voice_path).name} "
                    f"({voice_duration:.2f}s)[/dim]"
                )
            else:
                console.print(
                    f"[yellow]CTA voice duration could not be read, "
                    f"using config freeze duration: {voice_path}[/yellow]"
                )
                voice_duration = None
        else:
            console.print(
                f"[yellow]CTA voice file not found, continuing without voice: "
                f"{config.cta.voice_mp3_path}[/yellow]"
            )

    cta_text = None
    cta_start = None
    cta_insert_duration = 0.0
    cta_freeze_duration = None
    if config.cta.enabled:
        cta_text = pick_cta_text(config)
        cta_freeze_duration = _cta_freeze_duration(config, voice_duration)
        cta_start = pick_cta_trigger_time(
            clip_dur,
            config,
            freeze_duration_sec=cta_freeze_duration,
        )
        cta_insert_duration = cta_freeze_duration

    # Generate subtitles
    ass_path = None
    if config.subtitles_enabled and asr_words:
        clip_words = [
            w for w in asr_words
            if segment.start_sec <= w.get("start", 0) <= segment.end_sec
        ]
        events = generate_word_subtitles(
            clip_words,
            config,
            clip_start=segment.start_sec,
            cta_insert_start=cta_start,
            cta_insert_duration=cta_insert_duration,
        )
        if events:
            ass_path = os.path.join(temp_dir, f"subtitles_clip{clip_index}.ass")
            generate_ass_file(events, ass_path, config, theme_override=theme)
            console.print(f"[dim]Subtitles: {len(events)} events (theme={theme})[/dim]")

    # Pick music
    music_path = None
    if config.music.enabled:
        music_path = pick_random_track(config.music.folder, config)
        if music_path:
            console.print(f"[dim]Music: {Path(music_path).name}[/dim]")

    # Build filter complex
    filter_complex, output_label, audio_meta = _build_filter_chain(
        video_path=video_path,
        video_info=video_info,
        segment=segment,
        layout=layout,
        config=config,
        ass_path=ass_path,
        music_path=music_path,
        voice_path=voice_path,
        clip_index=clip_index,
        cta_text=cta_text,
        cta_start_sec=cta_start,
        cta_freeze_duration_sec=cta_freeze_duration,
    )

    # Build ffmpeg command (PATH or tools/ffmpeg/bin)
    cmd = [ffmpeg_exe(), "-y"]

    # Seek as *input* option so filter graph time starts at 0.
    cmd.extend(["-ss", str(segment.start_sec)])
    cmd.extend(["-t", str(clip_dur)])
    cmd.extend(["-i", video_path])

    if music_path and os.path.exists(music_path):
        cmd.extend(["-i", music_path])

    if voice_path and os.path.exists(voice_path):
        cmd.extend(["-i", voice_path])

    # Filters
    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex])

    # Output settings
    cmd.extend(["-map", f"[{output_label}]" if filter_complex else "0:v"])

    # Audio
    if audio_meta.get("has_audio_out"):
        cmd.extend(["-map", "[audio_out]"])
    else:
        cmd.extend(["-map", "0:a?"])

    cmd.extend(_video_encode_args(config))
    cmd.extend([
        "-c:a", config.export.audio_codec,
        "-b:a", config.export.audio_bitrate,
        "-r", str(config.export.fps),
        "-movflags", "+faststart",
        "-shortest",
    ])

    cmd.append(output_path)

    if config.debug:
        console.print(f"[dim]Filter: {filter_complex[:300]}...[/dim]")
    console.print(
        f"[dim]ffmpeg render: input={Path(video_path).name}, output={Path(output_path).name}[/dim]"
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # 10 min max per clip
        )
        if result.returncode != 0:
            console.print(f"[red]ffmpeg error: {result.stderr[-2000:]}[/red]")
            if config.debug:
                console.print(f"[dim]Full stderr: {result.stderr}[/dim]")
            return False

        if not os.path.exists(output_path):
            console.print("[red]Output file not created[/red]")
            return False

        console.print(f"[green]Created: {output_path}[/green]")
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]ffmpeg timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Render error: {e}[/red]")
        return False


def _build_filter_chain(
    video_path: str,
    video_info: VideoInfo,
    segment: HighlightSegment,
    layout: LayoutSpec,
    config: AppConfig,
    ass_path: Optional[str],
    music_path: Optional[str],
    voice_path: Optional[str],
    clip_index: int,
    cta_text: Optional[str] = None,
    cta_start_sec: Optional[float] = None,
    cta_freeze_duration_sec: Optional[float] = None,
) -> tuple[str, str, dict]:
    """
    Build the complete ffmpeg filter complex for a clip.
    Returns (filter_string, output_label).
    """
    clip_dur = segment.end_sec - segment.start_sec
    filter_parts = []  # flat list of individual filter parts

    # 1) Composite layout filter (produces [composed])
    comp_filter, comp_label = build_composite_filter(layout, src_count=1, input_label="0:v")
    # comp_filter is already a chain with ; separators; split into parts
    for part in comp_filter.split(";"):
        part = part.strip()
        if part:
            filter_parts.append(part)

    # 2) CTA effect
    current_label = comp_label
    cta_start = None
    cta_insert_duration = 0.0
    if config.cta.enabled:
        cta_filter, cta_start, cta_end = build_cta_segment_filter(
            clip_duration=clip_dur,
            cta_text=cta_text or pick_cta_text(config),
            config=config,
            input_label=current_label,
            cta_start_sec=cta_start_sec,
            freeze_duration_sec=cta_freeze_duration_sec,
        )
        # CTA filter uses concat and outputs [cta_out]
        for part in cta_filter.split(";"):
            part = part.strip()
            if part:
                filter_parts.append(part)
        current_label = "cta_out"
        cta_insert_duration = max(0.0, float(cta_end - cta_start))
        console.print(f"[dim]CTA: freeze at {cta_start:.1f}s - {cta_end:.1f}s[/dim]")

    # 3) Subtitles overlay
    if ass_path and os.path.exists(ass_path):
        # Use absolute path with proper escaping for ffmpeg subtitles filter
        abs_path = os.path.abspath(ass_path)
        # Escape special characters for ffmpeg subtitles filter
        # Colon must be escaped on Windows: C\:/path
        escaped_path = _escape_filter_path(abs_path)
        font_dir = _subtitle_fonts_dir(config)
        if font_dir:
            escaped_font_dir = _escape_filter_path(font_dir)
            subs_filter = (
                f"[{current_label}]"
                f"subtitles=filename='{escaped_path}':fontsdir='{escaped_font_dir}'"
                "[subs_out]"
            )
        else:
            subs_filter = f"[{current_label}]subtitles='{escaped_path}'[subs_out]"
        filter_parts.append(subs_filter)
        current_label = "subs_out"
        console.print(f"[dim]Subtitles overlay: {abs_path}[/dim]")

    # 4) Audio mix
    music_idx = 1 if (music_path and os.path.exists(music_path)) else None
    voice_idx = None
    if voice_path and os.path.exists(voice_path):
        voice_idx = 2 if music_idx is not None else 1

    audio_filter = build_final_audio_mix(
        clip_duration=clip_dur,
        music_path=music_path if music_idx is not None else None,
        config=config,
        video_input_idx=0,
        music_input_idx=music_idx,
        voice_input_idx=voice_idx,
        voice_start_sec=float(cta_start or 0.0),
        voice_volume=1.0,
        has_original_audio=bool(video_info.audio_streams),
        final_duration_sec=clip_dur + cta_insert_duration,
        cta_insert_start_sec=cta_start,
        cta_insert_duration_sec=cta_insert_duration,
    )
    if audio_filter:
        for part in audio_filter.split(";"):
            part = part.strip()
            if part:
                filter_parts.append(part)

    # Combine all filter parts - ensure no empty parts
    full_filter = ";".join(p for p in filter_parts if p.strip())
    return full_filter, current_label, {"has_audio_out": True}


def _video_encode_args(config: AppConfig) -> list[str]:
    """Build video encoder args. CRF mode gives smaller files at near-identical visual quality."""
    codec = config.export.codec
    args = ["-c:v", codec]
    codec_lower = codec.lower()
    crf = getattr(config.export, "crf", None)

    if crf is not None and codec_lower in {"libx264", "libx265"}:
        args.extend(["-crf", str(int(crf))])
    elif config.export.bitrate:
        args.extend(["-b:v", config.export.bitrate])

    preset = getattr(config.export, "preset", "fast") or "fast"
    args.extend(["-preset", preset, "-pix_fmt", "yuv420p"])
    return args


def _cta_freeze_duration(config: AppConfig, voice_duration_sec: Optional[float]) -> float:
    """Use CTA voice duration when available, otherwise fall back to config."""
    if voice_duration_sec is not None and voice_duration_sec > 0:
        return float(voice_duration_sec)
    return max(0.1, float(config.cta.freeze_duration_sec))


def _resolve_existing_media_path(path: str) -> Optional[str]:
    """Resolve absolute or project-relative media path, returning None if missing."""
    if not path:
        return None

    candidates = [Path(path)]
    if not Path(path).is_absolute():
        root = Path(__file__).resolve().parent.parent
        candidates.extend([Path.cwd() / path, root / path])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
    return None


def _probe_media_duration(path: str) -> Optional[float]:
    """Return media duration in seconds via ffprobe, or None on any read failure."""
    try:
        result = subprocess.run(
            [
                ffprobe_exe(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        duration = float(result.stdout.strip())
    except Exception:
        return None
    return duration if duration > 0 else None


def _escape_filter_path(path: str) -> str:
    escaped = os.path.abspath(path).replace("\\", "/").replace(":", "\\:")
    return escaped.replace("'", "'\\''")


def _subtitle_fonts_dir(config: AppConfig) -> Optional[str]:
    font_path = getattr(config, "subtitles_font_path", "") or ""
    if not font_path:
        return None
    if not os.path.isabs(font_path):
        font_path = os.path.abspath(font_path)
    if not os.path.exists(font_path):
        return None
    return os.path.dirname(font_path)


def render_all_clips(
    video_path: str,
    video_info: VideoInfo,
    segments: list[HighlightSegment],
    layout: LayoutSpec,
    config: AppConfig,
    output_dir: str,
    temp_dir: str,
    asr_words: Optional[list[dict]] = None,
) -> list[str]:
    """Render all highlight clips. Returns list of output paths."""
    ensure_dir(output_dir)

    success_paths = []
    for i, segment in enumerate(segments):
        out_name = safe_filename(f"clip_{i+1}_{fmt_time(segment.start_sec)}_{fmt_time(segment.end_sec)}.mp4")
        out_path = os.path.join(output_dir, out_name)

        success = render_clip(
            video_path=video_path,
            video_info=video_info,
            segment=segment,
            layout=layout,
            config=config,
            output_path=out_path,
            temp_dir=temp_dir,
            asr_words=asr_words,
            clip_index=i,
        )

        if success:
            success_paths.append(out_path)

    console.print(f"\n[green]Successfully rendered {len(success_paths)}/{len(segments)} clips[/green]")
    return success_paths
