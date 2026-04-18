"""CLI entry point and argument parsing."""

from __future__ import annotations


def _parse_time_sec(raw: str) -> float:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty time")
    if ":" not in raw:
        return max(0.0, float(raw.replace(",", ".")))
    parts = [float(part.replace(",", ".")) for part in raw.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return max(0.0, minutes * 60 + seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return max(0.0, hours * 3600 + minutes * 60 + seconds)
    raise ValueError(f"Invalid time format: {raw}")


def cli_entry():
    """Entry point for pyproject.toml script."""
    import argparse

    from app.utils.console import get_console
    console = get_console()

    parser = argparse.ArgumentParser(prog="streamcuter", description="StreamCuter - vertical clip generator")
    parser.add_argument("--input", "-i", dest="input_path", required=False, help="Path to video file or URL")
    parser.add_argument("--config", "-c", dest="config_path", required=False, help="Path to config YAML file")
    parser.add_argument("--output-dir", "-o", required=False, help="Output directory")
    parser.add_argument("--temp-dir", "-t", required=False, help="Temp directory")
    parser.add_argument("--clips", "-n", type=int, required=False, help="Number of clips to generate")
    parser.add_argument(
        "--render-preset",
        choices=["fast", "balanced", "quality", "small", "nvenc_fast", "custom"],
        required=False,
        help="Render preset: fast, balanced, quality, small, nvenc_fast, or custom",
    )
    parser.add_argument(
        "--input-start",
        required=False,
        help="Start offset within the input video in seconds, MM:SS, or HH:MM:SS",
    )
    parser.add_argument(
        "--input-end",
        required=False,
        help="End offset within the input video in seconds, MM:SS, or HH:MM:SS",
    )
    parser.add_argument("--no-cache", action="store_true", help="Disable persistent ASR/highlight/layout cache")
    parser.add_argument("--force-render", action="store_true", help="Re-render existing output clips instead of resuming")
    parser.add_argument("--lang", "-l", choices=["auto", "ru", "en"], required=False, help="Subtitle/ASR language")
    parser.add_argument("--subtitle-lang", choices=["auto", "ru", "en"], required=False, help="Alias for --lang")
    parser.add_argument("--cta-lang", choices=["auto", "ru", "en"], required=False, help="CTA text language")
    parser.add_argument("--cta-text", required=False, help="Custom CTA text for the freeze moment")
    parser.add_argument("--cta-text-file", required=False, help="Path to a file with CTA text variants, one per line")
    parser.add_argument(
        "--cookies-from-browser",
        required=False,
        help="Load yt-dlp cookies from a browser profile, for example chrome or chrome:Default",
    )
    parser.add_argument(
        "--cta-text-mode",
        choices=["file", "custom", "variants"],
        required=False,
        help="CTA text source: file, custom, or variants from config",
    )
    parser.add_argument("--cta-voice", required=False, help="Path to CTA voice mp3/wav file")
    parser.add_argument("--theme", choices=["red", "purple", "black", "yellow"], required=False, help="Subtitle theme")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without processing")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--preview-layout",
        action="store_true",
        help="Open a screenshot selector for manual webcam/slot crops before rendering",
    )
    parser.add_argument(
        "--preview-time",
        required=False,
        help="Initial layout preview time in seconds, MM:SS, or HH:MM:SS",
    )
    parser.add_argument(
        "--layout-mode",
        choices=["auto", "slot_only", "cinema"],
        required=False,
        help="Explicit no-webcam composition mode: auto, slot_only, or cinema",
    )
    parser.add_argument("--no-webcam", action="store_true", help="Force no webcam detection")
    music_group = parser.add_mutually_exclusive_group()
    music_group.add_argument(
        "--music",
        action="store_true",
        help="Enable Apply Cinema background music from musiccinema for this run",
    )
    music_group.add_argument(
        "--no-music",
        action="store_true",
        help="Disable Apply Cinema background music for this run",
    )
    parser.add_argument("--no-cta", action="store_true", help="Disable CTA pause effect")
    parser.add_argument("--no-subs", action="store_true", help="Disable subtitles")
    parser.add_argument(
        "--delete-input-after-success",
        action="store_true",
        help="Delete the source video file after clips are rendered successfully",
    )
    parser.add_argument(
        "--keep-input",
        action="store_true",
        help="Keep the source video file after rendering, overriding config",
    )

    args = parser.parse_args()

    from app.config import load_config

    try:
        config = load_config(args.config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    # Override with CLI args
    if args.input_path:
        config.input = args.input_path
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.temp_dir:
        config.temp_dir = args.temp_dir
    if args.clips:
        config.clips_override = args.clips
    if args.render_preset:
        config.export.render_preset = args.render_preset
    if args.no_cache:
        config.cache.enabled = False
    if args.force_render:
        config.render_resume_enabled = False
    subtitle_lang = args.subtitle_lang or args.lang
    if subtitle_lang:
        config.language = subtitle_lang
        if not args.cta_lang and (config.cta.language or "auto").lower() == "auto":
            config.cta.language = subtitle_lang
    if args.cta_lang:
        config.cta.language = args.cta_lang
    if args.cta_text_mode:
        config.cta.text_mode = args.cta_text_mode
    if args.cta_text:
        config.cta.custom_text = args.cta_text
        config.cta.text_mode = "custom"
    if args.cta_text_file:
        config.cta.text_file_path = args.cta_text_file
        config.cta.text_mode = "file"
    if args.cta_voice:
        config.cta.voice_mp3_path = args.cta_voice
    if args.cookies_from_browser:
        import os

        os.environ["STREAMCUTER_COOKIES_FROM_BROWSER"] = args.cookies_from_browser
    if args.theme:
        config.subtitles_theme = args.theme
    if args.debug:
        config.debug = True
    if args.preview_layout:
        config.layout_preview_enabled = True
    if args.preview_time:
        try:
            config.layout_preview_time_sec = _parse_time_sec(args.preview_time)
            config.layout_preview_enabled = True
        except ValueError as e:
            console.print(f"[red]Invalid --preview-time: {e}[/red]")
            raise SystemExit(2)
    if args.layout_mode:
        config.layout_mode = args.layout_mode
    if args.input_start:
        try:
            config.input_start_sec = _parse_time_sec(args.input_start)
        except ValueError as e:
            console.print(f"[red]Invalid --input-start: {e}[/red]")
            raise SystemExit(2)
    if args.input_end:
        try:
            config.input_end_sec = _parse_time_sec(args.input_end)
        except ValueError as e:
            console.print(f"[red]Invalid --input-end: {e}[/red]")
            raise SystemExit(2)
    if (
        config.input_end_sec is not None
        and config.input_start_sec is not None
        and config.input_end_sec <= config.input_start_sec
    ):
        console.print("[red]--input-end must be greater than --input-start.[/red]")
        raise SystemExit(2)
    if args.no_webcam:
        config.webcam_detection = "off"
    layout_mode = str(getattr(config, "layout_mode", "auto") or "auto").lower()
    if layout_mode == "slot_only":
        config.webcam_detection = "off"
        config.subtitles_position = "slot_top"
    elif layout_mode == "cinema":
        config.webcam_detection = "auto" if getattr(config, "manual_webcam_crop", None) else "off"
        config.subtitles_position = (
            "between_webcam_and_game" if getattr(config, "manual_webcam_crop", None) else "slot_top"
        )
    if args.music:
        config.music.enabled = True
        config.cinema_music.enabled = True
    elif args.no_music:
        config.music.enabled = False
        config.cinema_music.enabled = False
    if args.no_cta:
        config.cta.enabled = False
    if args.no_subs:
        config.subtitles_enabled = False
    if args.delete_input_after_success and args.keep_input:
        console.print("[red]Use only one of --delete-input-after-success or --keep-input.[/red]")
        raise SystemExit(2)
    if args.delete_input_after_success:
        config.delete_input_after_success = True
    elif args.keep_input:
        config.delete_input_after_success = False

    if not config.input:
        console.print("[red]No input specified. Use --input or set input in config.[/red]")
        raise SystemExit(1)

    if args.dry_run:
        console.print("[cyan]=== DRY RUN ===[/cyan]")
        console.print(f"Input: {config.input}")
        console.print(
            "Input range: "
            f"start={config.input_start_sec if config.input_start_sec is not None else 0.0}, "
            f"end={config.input_end_sec if config.input_end_sec is not None else 'source end'}"
        )
        console.print(f"Output: {config.output_dir}")
        console.print(f"Temp: {config.temp_dir}")
        console.print(f"Language: {config.language}")
        console.print(
            f"Subtitles: {config.subtitles_enabled} "
            f"(language={config.language}, theme={config.subtitles_theme}, position={config.subtitles_position})"
        )
        console.print(f"Webcam detection: {config.webcam_detection}")
        console.print(f"Layout mode: {config.layout_mode}")
        console.print(f"Manual webcam crop: {config.manual_webcam_crop or 'none'}")
        console.print(f"Manual slot crop: {config.manual_slot_crop or 'none'}")
        console.print(f"Manual cinema crop: {config.manual_cinema_crop or 'none'}")
        console.print(f"Layout preview selector: {config.layout_preview_enabled}")
        console.print(
            "Layout preview initial time: "
            f"{config.layout_preview_time_sec if config.layout_preview_time_sec is not None else 'middle'}"
        )
        console.print(f"Layout debug preview: {config.layout_debug_preview}")
        console.print(f"Layout selection save path: {config.layout_preview_save_path}")
        console.print(f"Music: {config.music.enabled}")
        console.print(
            "Cinema music: "
            f"{config.cinema_music.enabled} "
            f"(folder={config.cinema_music.folder}, "
            f"base_volume={min(config.cinema_music.volume, 0.10):.2f}, "
            f"ending={config.cinema_music.ending_duration_sec:.1f}s)"
        )
        from app.cta_pause import (
            cta_disabled_reason,
            cta_effectively_enabled,
            effective_cta_language,
            pick_cta_text,
        )

        cta_reason = cta_disabled_reason(config)
        cta_enabled = cta_effectively_enabled(config)

        console.print(
            f"CTA: {cta_enabled} "
            f"(language={config.cta.language}, effective_language={effective_cta_language(config)}, "
            f"text_mode={config.cta.text_mode}, disabled_reason={cta_reason or 'none'})"
        )
        if cta_reason == "cinema mode":
            console.print("CTA disabled by cinema mode")
        console.print(
            f"CTA effective text: {pick_cta_text(config) if cta_enabled else 'disabled'}"
        )
        console.print(f"CTA custom text: {config.cta.custom_text or 'none'}")
        console.print(f"CTA text file: {config.cta.text_file_path or 'language default'}")
        console.print(
            f"CTA voice: {(config.cta.voice_mp3_path or 'none') if cta_enabled else 'disabled'}"
        )
        console.print(f"Delete input after success: {config.delete_input_after_success}")
        console.print(
            f"Export: {config.export.width}x{config.export.height}@{config.export.fps} "
            f"render_preset={config.export.render_preset} "
            f"codec={config.export.codec} crf={config.export.crf} preset={config.export.preset}"
        )
        try:
            from app.renderer import _video_encode_args

            console.print(f"Effective video args: {' '.join(_video_encode_args(config))}")
        except Exception:
            pass
        console.print(
            f"Cache: {config.cache.enabled} "
            f"(asr={config.cache.asr}, highlights={config.cache.highlights}, layout={config.cache.layout}, dir={config.cache.dir})"
        )
        console.print(f"Resume render: {config.render_resume_enabled}")
        console.print(f"Highlight report: {config.highlight_report_path}")
        console.print(f"Clips override: {config.clips_override}")
        console.print("[cyan]=== END DRY RUN ===[/cyan]")
        return

    from app.main import run_pipeline
    run_pipeline(config)
