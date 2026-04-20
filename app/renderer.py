"""Final video renderer - orchestrates the full pipeline."""

from __future__ import annotations

import os
import copy
import random
import subprocess
from pathlib import Path
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig, SUBTITLE_THEMES
from app.banner_ads import BannerAsset, pick_banner_asset
from app.layout import LayoutSpec, build_composite_filter
from app.probe import VideoInfo
from app.highlight_detector import HighlightSegment
from app.subtitles import generate_ass_file, generate_word_subtitles
from app.cta_pause import (
    build_cta_segment_filter,
    cta_effectively_enabled,
    pick_cta_text,
    pick_cta_trigger_time,
)
from app.audio_mix import pick_random_track, build_final_audio_mix
from app.utils.helpers import (
    cpu_thread_budget,
    ensure_dir,
    fmt_time,
    ffmpeg_exe,
    ffprobe_exe,
    safe_filename,
)

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
    cta_enabled = cta_effectively_enabled(config)
    voice_path = None
    voice_duration = None
    if cta_enabled and config.cta.voice_mp3_path:
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
    if cta_enabled:
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

    # Background music is intentionally cinema-only. Normal webcam/slot clips
    # stay clean even when legacy music config is enabled.
    (
        music_path,
        music_volume,
        music_ending_volume,
        music_ending_duration_sec,
    ) = _select_cinema_music(layout, config)
    banner_asset = _select_cinema_banner(layout, config)

    # Build filter complex
    banner_input_idx = 1 if banner_asset is not None else None
    music_idx = None
    voice_idx = None
    next_input_idx = 1
    if banner_asset is not None:
        next_input_idx += 1
    if music_path and os.path.exists(music_path):
        music_idx = next_input_idx
        next_input_idx += 1
    if voice_path and os.path.exists(voice_path):
        voice_idx = next_input_idx

    filter_complex, output_label, audio_meta = _build_filter_chain(
        video_path=video_path,
        video_info=video_info,
        segment=segment,
        layout=layout,
        config=config,
        ass_path=ass_path,
        music_path=music_path,
        music_volume=music_volume,
        music_ending_volume=music_ending_volume,
        music_ending_duration_sec=music_ending_duration_sec,
        voice_path=voice_path,
        banner_asset=banner_asset,
        banner_input_idx=banner_input_idx,
        music_input_idx=music_idx,
        voice_input_idx=voice_idx,
        clip_index=clip_index,
        cta_text=cta_text,
        cta_start_sec=cta_start,
        cta_freeze_duration_sec=cta_freeze_duration,
    )

    # Build ffmpeg command (PATH or tools/ffmpeg/bin)
    cmd = [ffmpeg_exe(), "-y"]
    cmd.extend(["-threads", str(cpu_thread_budget())])

    # Seek as *input* option so filter graph time starts at 0.
    cmd.extend(["-ss", str(segment.start_sec)])
    cmd.extend(["-t", str(clip_dur)])
    cmd.extend(["-i", video_path])

    if banner_asset and os.path.exists(banner_asset.path):
        cmd.extend(["-stream_loop", "-1", "-i", banner_asset.path])

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
    music_volume: Optional[float] = None,
    music_ending_volume: Optional[float] = None,
    music_ending_duration_sec: float = 0.0,
    voice_path: Optional[str] = None,
    banner_asset: Optional[BannerAsset] = None,
    banner_input_idx: Optional[int] = None,
    music_input_idx: Optional[int] = None,
    voice_input_idx: Optional[int] = None,
    clip_index: int = 0,
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
    if cta_effectively_enabled(config):
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
    if banner_asset is not None and layout.banner_out is not None and banner_input_idx is not None:
        bx, by, bw, bh = layout.banner_out
        crop_x, crop_y, crop_w, crop_h = banner_asset.crop
        banner_cfg = getattr(config, "banner", None)
        chroma_similarity = (
            float(getattr(banner_cfg, "chroma_similarity", 0.18)) if banner_cfg is not None else 0.18
        )
        chroma_blend = (
            float(getattr(banner_cfg, "chroma_blend", 0.08)) if banner_cfg is not None else 0.08
        )
        banner_start_raw = (
            getattr(banner_cfg, "manual_start_sec", None)
            if banner_cfg is not None
            else None
        )
        if banner_start_raw is None:
            banner_start_raw = getattr(banner_asset, "start_sec", 0.0)
        banner_start_sec = float(banner_start_raw or 0.0)
        banner_start_sec = max(0.0, banner_start_sec)
        final_visual_duration = clip_dur + cta_insert_duration
        parts_banner = [
            f"[{banner_input_idx}:v]trim=start={banner_start_sec:.3f}:"
            f"end={banner_start_sec + final_visual_duration:.3f},setpts=PTS-STARTPTS",
            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
            f"colorkey={banner_asset.key_hex}:{chroma_similarity:.3f}:{chroma_blend:.3f}",
            "format=rgba",
            f"scale={bw}:{bh}:force_original_aspect_ratio=decrease:force_divisible_by=2[banner_scaled]",
        ]
        filter_parts.append(",".join(parts_banner))
        filter_parts.append(
            f"[{current_label}][banner_scaled]overlay={bx}:{by}+{bh}-h:format=auto:shortest=1[banner_out]"
        )
        current_label = "banner_out"

    audio_filter = build_final_audio_mix(
        clip_duration=clip_dur,
        music_path=music_path if music_input_idx is not None else None,
        config=config,
        video_input_idx=0,
        music_input_idx=music_input_idx,
        voice_input_idx=voice_input_idx,
        voice_start_sec=float(cta_start or 0.0),
        voice_volume=1.0,
        has_original_audio=bool(video_info.audio_streams),
        final_duration_sec=clip_dur + cta_insert_duration,
        cta_insert_start_sec=cta_start,
        cta_insert_duration_sec=cta_insert_duration,
        music_volume=music_volume,
        music_ending_volume=music_ending_volume,
        music_ending_duration_sec=music_ending_duration_sec,
    )
    if audio_filter:
        for part in audio_filter.split(";"):
            part = part.strip()
            if part:
                filter_parts.append(part)

    # Combine all filter parts - ensure no empty parts
    full_filter = ";".join(p for p in filter_parts if p.strip())
    return full_filter, current_label, {"has_audio_out": True}


def _select_cinema_music(
    layout: LayoutSpec,
    config: AppConfig,
) -> tuple[Optional[str], Optional[float], Optional[float], float]:
    """Pick quiet cinema music plus an optional loud ending."""
    if not _is_cinema_render(layout, config):
        return None, None, None, 0.0

    cinema_music = getattr(config, "cinema_music", None)
    if cinema_music is None or not bool(getattr(cinema_music, "enabled", True)):
        console.print("[dim]Cinema music: disabled[/dim]")
        return None, None, None, 0.0

    folder = str(getattr(cinema_music, "folder", "musiccinema") or "musiccinema")
    music_path = pick_random_track(folder, config)
    if not music_path:
        console.print("[dim]Cinema music: no tracks, rendering without music[/dim]")
        return None, None, None, 0.0

    volume = _cinema_music_volume(config)
    ending_volume, ending_duration = _cinema_music_ending(config, volume)
    if ending_volume is None:
        console.print(f"[dim]Cinema music: {Path(music_path).name} at {volume:.0%}[/dim]")
    else:
        console.print(
            f"[dim]Cinema music: {Path(music_path).name} at {volume:.0%}, "
            f"ending {ending_duration:.1f}s at {ending_volume:.0%}[/dim]"
        )
    return music_path, volume, ending_volume, ending_duration


def _select_cinema_banner(layout: LayoutSpec, config: AppConfig) -> Optional[BannerAsset]:
    """Pick one chroma-keyed banner asset for cinema renders."""
    if not _is_cinema_render(layout, config):
        return None
    if getattr(layout, "banner_out", None) is None:
        return None
    banner_asset = pick_banner_asset(config)
    if banner_asset is None:
        return None
    console.print(f"[dim]Cinema banner: {Path(banner_asset.path).name}[/dim]")
    return banner_asset


def _is_cinema_render(layout: LayoutSpec, config: AppConfig) -> bool:
    layout_mode = str(getattr(layout, "mode", "") or "").lower()
    config_mode = str(getattr(config, "layout_mode", "auto") or "auto").lower()
    return layout_mode == "cinema" or config_mode == "cinema"


def _cinema_music_volume(config: AppConfig) -> float:
    cinema_music = getattr(config, "cinema_music", None)
    raw = getattr(cinema_music, "volume", 0.05) if cinema_music is not None else 0.05
    try:
        volume = float(raw)
    except (TypeError, ValueError):
        volume = 0.05
    return max(0.0, min(0.10, volume))


def _cinema_music_ending(config: AppConfig, base_volume: float) -> tuple[Optional[float], float]:
    cinema_music = getattr(config, "cinema_music", None)
    if cinema_music is None or not bool(getattr(cinema_music, "ending_enabled", True)):
        return None, 0.0

    try:
        ending_duration = float(getattr(cinema_music, "ending_duration_sec", 4.5))
    except (TypeError, ValueError):
        ending_duration = 4.5
    ending_duration = max(0.0, min(5.0, ending_duration))
    if ending_duration <= 0.05:
        return None, 0.0

    try:
        ending_volume = float(getattr(cinema_music, "ending_volume", 0.09))
    except (TypeError, ValueError):
        ending_volume = 0.09

    base = max(0.0, min(0.10, float(base_volume)))
    max_allowed = min(0.14, base + 0.04)
    ending_volume = max(base, min(max_allowed, ending_volume))
    if ending_volume <= base + 0.001:
        return None, 0.0
    return ending_volume, ending_duration


def _video_encode_args(config: AppConfig) -> list[str]:
    """Build video encoder args. CRF mode gives smaller files at near-identical visual quality."""
    preset_name = (getattr(config.export, "render_preset", "quality") or "quality").lower()
    preset = _render_preset_values(preset_name)
    codec = preset.get("codec") or config.export.codec
    args = ["-c:v", codec]
    codec_lower = codec.lower()
    crf = preset.get("crf", getattr(config.export, "crf", None))

    if crf is not None and codec_lower in {"libx264", "libx265"}:
        args.extend(["-crf", str(int(crf))])
    elif codec_lower in {"h264_nvenc", "hevc_nvenc"}:
        cq = preset.get("cq", crf if crf is not None else 22)
        args.extend(["-rc", "vbr", "-cq", str(int(cq)), "-b:v", "0"])
    elif config.export.bitrate:
        args.extend(["-b:v", config.export.bitrate])

    encoder_preset = preset.get("preset") or getattr(config.export, "preset", "fast") or "fast"
    args.extend(["-preset", str(encoder_preset), "-pix_fmt", "yuv420p"])
    return args


def _render_preset_values(name: str) -> dict:
    if name == "custom":
        return {}
    presets = {
        "fast": {"codec": "libx264", "crf": 23, "preset": "veryfast"},
        "balanced": {"codec": "libx264", "crf": 21, "preset": "medium"},
        "quality": {"codec": "libx264", "crf": 19, "preset": "slower"},
        "small": {"codec": "libx264", "crf": 24, "preset": "slow"},
        "nvenc_fast": {"codec": "h264_nvenc", "cq": 22, "preset": "p5"},
    }
    return presets.get(name, presets["quality"])


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
    discovery_asr=None,
) -> list[str]:
    """Render all highlight clips. Returns list of output paths."""
    ensure_dir(output_dir)

    success_paths = []
    subtitle_session = None
    for i, segment in enumerate(segments):
        out_name = safe_filename(f"clip_{i+1}_{fmt_time(segment.start_sec)}_{fmt_time(segment.end_sec)}.mp4")
        out_path = os.path.join(output_dir, out_name)

        if config.render_resume_enabled and _is_existing_output_valid(out_path, segment):
            console.print(f"[green]Resume: keeping existing clip {Path(out_path).name}[/green]")
            success_paths.append(out_path)
            continue

        clip_asr_words = None
        if config.subtitles_enabled:
            from app.asr import run_clip_subtitle_asr

            clip_asr_words, subtitle_session = run_clip_subtitle_asr(
                video_path,
                segment,
                temp_dir,
                config,
                discovery_asr=discovery_asr,
                session=subtitle_session,
            )

        success = render_clip(
            video_path=video_path,
            video_info=video_info,
            segment=segment,
            layout=layout,
            config=config,
            output_path=out_path,
            temp_dir=temp_dir,
            asr_words=clip_asr_words,
            clip_index=i,
        )

        if success:
            success_paths.append(out_path)

    console.print(f"\n[green]Successfully rendered {len(success_paths)}/{len(segments)} clips[/green]")
    return success_paths


def render_quick_preview(
    video_path: str,
    video_info: VideoInfo,
    segments: list[HighlightSegment],
    layout: LayoutSpec,
    config: AppConfig,
    temp_dir: str,
    asr_words: Optional[list[dict]] = None,
) -> list[str]:
    """Render a short 720x1280 preview clip for layout/subtitle/CTA checks."""
    if not segments:
        return []
    preview_settings = getattr(config, "quick_preview", None)
    preview_width = int(getattr(preview_settings, "width", 720))
    preview_height = int(getattr(preview_settings, "height", 1280))
    preview_duration = max(3.0, float(getattr(preview_settings, "duration_sec", 10.0) or 10.0))
    preview_output_dir = str(getattr(preview_settings, "output_dir", "output/preview") or "output/preview")

    preview_config = copy.deepcopy(config)
    preview_config.export.width = preview_width
    preview_config.export.height = preview_height
    preview_config.export.render_preset = "fast"
    preview_config.export.fps = min(int(config.export.fps or 30), 30)
    preview_config.render_resume_enabled = False
    preview_layout = _recompute_layout_for_output(
        layout,
        video_info,
        preview_config,
        preview_config.export.width,
        preview_config.export.height,
    )

    first = segments[0]
    end_sec = min(first.end_sec, first.start_sec + preview_duration)
    if end_sec <= first.start_sec:
        end_sec = min(video_info.duration_sec, first.start_sec + preview_duration)
    preview_segment = HighlightSegment(
        start_sec=first.start_sec,
        end_sec=end_sec,
        score=first.score,
        reasons=list(getattr(first, "reasons", []) or []) + ["quick_preview"],
        source="quick_preview",
    )

    out_dir = ensure_dir(preview_output_dir)
    out_path = out_dir / safe_filename(
        f"quick_preview_{fmt_time(preview_segment.start_sec)}_{fmt_time(preview_segment.end_sec)}.mp4"
    )
    success = render_clip(
        video_path=video_path,
        video_info=video_info,
        segment=preview_segment,
        layout=preview_layout,
        config=preview_config,
        output_path=str(out_path),
        temp_dir=temp_dir,
        asr_words=asr_words,
        clip_index=0,
    )
    return [str(out_path)] if success else []


def _recompute_layout_for_output(
    layout: LayoutSpec,
    video_info: VideoInfo,
    config: AppConfig,
    out_w: int,
    out_h: int,
) -> LayoutSpec:
    """Recompute output rectangles for a different preview resolution."""
    from app.content_detector import ContentDetectionResult
    from app.layout import compute_layout
    from app.webcam_types import WebcamDetectionResult, WebcamRegion

    if layout.has_webcam and layout.webcam_src is not None:
        x, y, w, h = layout.webcam_src
        webcam_result = WebcamDetectionResult(
            has_webcam=True,
            region=WebcamRegion(x=x, y=y, w=w, h=h, confidence=1.0),
            confidence=1.0,
        )
    else:
        webcam_result = WebcamDetectionResult(has_webcam=False)

    content_result = None
    if layout.content_src is not None:
        content_result = ContentDetectionResult(
            has_content=True,
            crop=layout.content_src,
            confidence=1.0,
            reason="quick_preview_layout",
        )

    return compute_layout(
        src_w=video_info.width,
        src_h=video_info.height,
        out_w=out_w,
        out_h=out_h,
        webcam_result=webcam_result,
        config=config,
        content_result=content_result,
    )


def _is_existing_output_valid(path: str, segment: HighlightSegment) -> bool:
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 1024:
        return False
    duration = _probe_media_duration(str(p))
    if duration is None:
        return False
    expected = max(0.1, float(segment.end_sec - segment.start_sec))
    # CTA freeze can extend the final output, so only reject obviously broken files.
    return duration >= min(5.0, expected * 0.50)
