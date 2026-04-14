"""Main pipeline orchestrator."""

from __future__ import annotations

from app.config import AppConfig
from app.utils.helpers import ensure_ffmpeg, ensure_dir
from app.utils.console import get_console

console = get_console()


def run_pipeline(config: AppConfig) -> None:
    """Execute the full StreamCuter pipeline."""
    console.print("\n[bold cyan]========================================[/bold cyan]")
    console.print("[bold cyan]       StreamCuter Pipeline               [/bold cyan]")
    console.print("[bold cyan]========================================[/bold cyan]\n")

    # Step 0: Prerequisites
    console.print("[step 0] Checking prerequisites...")
    if not ensure_ffmpeg():
        console.print("[red]ERROR: ffmpeg and ffprobe are required.[/red]")
        console.print("Either add them to PATH, or place ffmpeg.exe and ffprobe.exe in:")
        console.print("  tools\\ffmpeg\\bin\\")
        console.print("See: https://ffmpeg.org/download.html")
        raise SystemExit(1)

    # Setup directories
    temp_dir = config.temp_dir
    output_dir = config.output_dir
    ensure_dir(temp_dir)
    ensure_dir(output_dir)

    # Step 1: Ingest
    console.print("\n[step 1] Resolving input...")
    from app.downloader import resolve_input
    try:
        video_path = resolve_input(config.input, temp_dir)
    except Exception as e:
        console.print(f"[red]Ingest failed: {e}[/red]")
        raise SystemExit(1)

    # Step 2: Probe
    console.print("\n[step 2] Probing video...")
    from app.probe import probe_video
    try:
        video_info = probe_video(video_path)
    except Exception as e:
        console.print(f"[red]Probe failed: {e}[/red]")
        raise SystemExit(1)

    # Step 3: Webcam detection
    console.print("\n[step 3] Detecting webcam...")
    webcam_result = None
    if config.webcam_detection == "off":
        from app.webcam_types import WebcamDetectionResult
        webcam_result = WebcamDetectionResult(has_webcam=False)
        console.print("[dim]Webcam detection disabled by config[/dim]")
    else:
        from app.webcam_detector import detect_webcam
        webcam_result = detect_webcam(video_path, config)

    # Step 4: Main content / slot detection
    console.print("\n[step 4] Detecting main content...")
    from app.content_detector import detect_content_area, write_layout_debug_preview
    content_result = detect_content_area(video_path, video_info, webcam_result, config)
    if config.debug:
        write_layout_debug_preview(video_path, webcam_result, content_result, config)

    # Step 5: Layout computation
    console.print("\n[step 5] Computing layout...")
    from app.layout import compute_layout
    layout = compute_layout(
        src_w=video_info.width,
        src_h=video_info.height,
        out_w=config.export.width,
        out_h=config.export.height,
        webcam_result=webcam_result,
        config=config,
        content_result=content_result,
    )

    if (
        not layout.has_webcam
        and config.subtitles_position in ("between_webcam_and_game", "between")
    ):
        config.subtitles_position = "slot_top"
        console.print("[dim]No webcam: moving subtitles to top-safe position[/dim]")

    # Step 6: ASR
    console.print("\n[step 6] Running speech recognition...")
    asr_words = []
    if config.subtitles_enabled:
        from app.asr import run_asr
        try:
            asr_words = run_asr(video_path, temp_dir, config)
        except Exception as e:
            console.print(f"[yellow]ASR failed, continuing without subtitles: {e}[/yellow]")
            asr_words = []
    else:
        console.print("[dim]Subtitles disabled[/dim]")

    # Step 7: Highlight detection
    console.print("\n[step 7] Finding highlights...")
    from app.highlight_detector import find_highlights
    try:
        segments = find_highlights(
            video_path=video_path,
            video_info=video_info,
            config=config,
            temp_dir=temp_dir,
            asr_words=asr_words if asr_words else None,
        )
    except Exception as e:
        console.print(f"[red]Highlight detection failed: {e}[/red]")
        raise SystemExit(1)

    if not segments:
        console.print("[yellow]No highlights found. Video may be too short or silent.[/yellow]")
        # Cleanup
        if config.cleanup_temp_files:
            from app.cleanup import safe_cleanup
            safe_cleanup(temp_dir)
        return

    # Step 8: Render clips
    console.print("\n[step 8] Rendering clips...")
    from app.renderer import render_all_clips
    output_paths = render_all_clips(
        video_path=video_path,
        video_info=video_info,
        segments=segments,
        layout=layout,
        config=config,
        output_dir=output_dir,
        temp_dir=temp_dir,
        asr_words=asr_words if asr_words else None,
    )

    if not output_paths:
        if config.cleanup_temp_files:
            from app.cleanup import cleanup_temp_files
            cleanup_temp_files(temp_dir)
        console.print("[red]Rendering failed: no output clips were created.[/red]")
        raise SystemExit(1)

    # Step 9: Cleanup
    console.print("\n[step 9] Cleanup...")
    if config.cleanup_temp_files:
        from app.cleanup import cleanup_temp_files
        # Keep output files
        cleanup_temp_files(temp_dir)
    else:
        console.print("[dim]Temp cleanup disabled[/dim]")

    if config.delete_input_after_success:
        from app.cleanup import delete_input_after_success
        delete_input_after_success(video_path, output_paths)

    # Summary
    console.print(f"\n[bold green]Done! {len(output_paths)} clips saved to {output_dir}[/bold green]")
    for p in output_paths:
        console.print(f"  [dim]-> {p}[/dim]")


def main():
    """Direct entry for python -m app.main."""
    # Keep `python -m app.main` working even without click/rich installed.
    from app.cli import cli_entry
    cli_entry()


if __name__ == "__main__":
    main()
