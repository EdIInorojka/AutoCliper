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
    parser.add_argument("--lang", "-l", choices=["auto", "ru", "en"], required=False, help="Subtitle/ASR language")
    parser.add_argument("--subtitle-lang", choices=["auto", "ru", "en"], required=False, help="Alias for --lang")
    parser.add_argument("--cta-lang", choices=["auto", "ru", "en"], required=False, help="CTA text language")
    parser.add_argument("--cta-text", required=False, help="Custom CTA text for the freeze moment")
    parser.add_argument("--cta-text-file", required=False, help="Path to a file with CTA text variants, one per line")
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
    parser.add_argument("--no-webcam", action="store_true", help="Force no webcam detection")
    music_group = parser.add_mutually_exclusive_group()
    music_group.add_argument("--music", action="store_true", help="Enable background music for this run")
    music_group.add_argument("--no-music", action="store_true", help="Disable background music for this run")
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
    subtitle_lang = args.subtitle_lang or args.lang
    if subtitle_lang:
        config.language = subtitle_lang
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
    if args.no_webcam:
        config.webcam_detection = "off"
    if args.music:
        config.music.enabled = True
    elif args.no_music:
        config.music.enabled = False
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
        console.print(f"Output: {config.output_dir}")
        console.print(f"Temp: {config.temp_dir}")
        console.print(f"Language: {config.language}")
        console.print(
            f"Subtitles: {config.subtitles_enabled} "
            f"(language={config.language}, theme={config.subtitles_theme}, position={config.subtitles_position})"
        )
        console.print(f"Webcam detection: {config.webcam_detection}")
        console.print(f"Manual webcam crop: {config.manual_webcam_crop or 'none'}")
        console.print(f"Manual slot crop: {config.manual_slot_crop or 'none'}")
        console.print(f"Layout preview selector: {config.layout_preview_enabled}")
        console.print(
            "Layout preview initial time: "
            f"{config.layout_preview_time_sec if config.layout_preview_time_sec is not None else 'middle'}"
        )
        console.print(f"Layout debug preview: {config.layout_debug_preview}")
        console.print(f"Layout selection save path: {config.layout_preview_save_path}")
        console.print(f"Music: {config.music.enabled}")
        console.print(
            f"CTA: {config.cta.enabled} "
            f"(language={config.cta.language}, text_mode={config.cta.text_mode})"
        )
        console.print(f"CTA custom text: {config.cta.custom_text or 'none'}")
        console.print(f"CTA text file: {config.cta.text_file_path or 'language default'}")
        console.print(f"CTA voice: {config.cta.voice_mp3_path or 'none'}")
        console.print(f"Delete input after success: {config.delete_input_after_success}")
        console.print(
            f"Export: {config.export.width}x{config.export.height}@{config.export.fps} "
            f"codec={config.export.codec} crf={config.export.crf} preset={config.export.preset}"
        )
        console.print(f"Clips override: {config.clips_override}")
        console.print("[cyan]=== END DRY RUN ===[/cyan]")
        return

    from app.main import run_pipeline
    run_pipeline(config)
