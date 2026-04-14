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

    webcam_result = None
    content_result = None

    if config.layout_preview_enabled:
        if getattr(config, "layout_preview_autofill", True):
            console.print("\n[step 2.4] Pre-filling layout preview with auto boxes...")
            webcam_result = _detect_webcam_with_cache(video_path, config)
            content_result = _detect_content_with_cache(
                video_path,
                video_info,
                webcam_result,
                config,
            )

        console.print("\n[step 2.5] Opening layout preview selector...")
        try:
            from app.layout_selector import (
                apply_layout_selection,
                save_layout_selection,
                select_layout_crops,
            )

            selection = select_layout_crops(
                video_path,
                video_info,
                config,
                auto_webcam_result=webcam_result,
                auto_content_result=content_result,
            )
            if selection is None:
                console.print("[yellow]Layout preview closed without selection; using automatic layout.[/yellow]")
            else:
                selection_mode = apply_layout_selection(config, selection)
                saved_path = save_layout_selection(config, selection, selection_mode, video_path=video_path)
                webcam_result = None
                content_result = None
                console.print(
                    "[cyan]Layout preview applied: "
                    f"mode={selection_mode}, webcam={config.manual_webcam_crop or 'none'}, "
                    f"slot={config.manual_slot_crop or 'none'}[/cyan]"
                )
                if saved_path is not None:
                    console.print(f"[dim]Layout selection saved: {saved_path}[/dim]")
        except Exception as e:
            console.print(f"[red]Layout preview failed: {e}[/red]")
            raise SystemExit(1)

    # Step 3: Webcam detection
    console.print("\n[step 3] Detecting webcam...")
    if webcam_result is None:
        webcam_result = _detect_webcam_with_cache(video_path, config)
    else:
        console.print("[dim]Using preview auto webcam result[/dim]")

    # Step 4: Main content / slot detection
    console.print("\n[step 4] Detecting main content...")
    from app.content_detector import write_layout_debug_preview
    if content_result is None:
        content_result = _detect_content_with_cache(video_path, video_info, webcam_result, config)
    else:
        console.print("[dim]Using preview auto slot result[/dim]")
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

    from app.highlight_detector import write_highlight_report
    write_highlight_report(video_info, segments, config)

    if config.quick_preview.enabled:
        console.print("\n[step 7.5] Rendering quick preview...")
        from app.renderer import render_quick_preview

        preview_paths = render_quick_preview(
            video_path=video_path,
            video_info=video_info,
            segments=segments,
            layout=layout,
            config=config,
            temp_dir=temp_dir,
            asr_words=asr_words if asr_words else None,
        )
        if config.quick_preview.only:
            if config.cleanup_temp_files:
                from app.cleanup import cleanup_temp_files

                cleanup_temp_files(temp_dir)
            console.print(
                f"\n[bold green]Quick preview ready: {preview_paths[0] if preview_paths else 'not created'}[/bold green]"
            )
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


def _detect_webcam_with_cache(video_path: str, config: AppConfig):
    if config.webcam_detection == "off":
        from app.webcam_types import WebcamDetectionResult

        console.print("[dim]Webcam detection disabled by config[/dim]")
        return WebcamDetectionResult(has_webcam=False)

    from app.cache import load_json_cache, save_json_cache
    from app.webcam_detector import detect_webcam
    from app.webcam_types import WebcamDetectionResult, WebcamRegion

    extra = {
        "version": 2,
        "edge_margin": config.webcam_edge_margin_ratio,
        "manual": config.manual_webcam_crop,
        "dataset": _layout_dataset_signature(config),
    }
    cached = load_json_cache(config, "layout", video_path, {"kind": "webcam", **extra})
    if cached:
        region = cached.get("region")
        if cached.get("has_webcam") and isinstance(region, dict):
            console.print("[green]Webcam cache hit[/green]")
            return WebcamDetectionResult(
                has_webcam=True,
                region=WebcamRegion(
                    x=int(region["x"]),
                    y=int(region["y"]),
                    w=int(region["w"]),
                    h=int(region["h"]),
                    confidence=float(region.get("confidence", cached.get("confidence", 0.0))),
                ),
                confidence=float(cached.get("confidence", 0.0)),
            )
        if cached.get("has_webcam") is False:
            console.print("[green]Webcam cache hit: none[/green]")
            return WebcamDetectionResult(has_webcam=False, confidence=float(cached.get("confidence", 0.0)))

    result = detect_webcam(video_path, config)
    payload = {"has_webcam": bool(result.has_webcam), "confidence": float(result.confidence)}
    if result.region is not None:
        payload["region"] = {
            "x": result.region.x,
            "y": result.region.y,
            "w": result.region.w,
            "h": result.region.h,
            "confidence": result.region.confidence,
        }
    save_json_cache(config, "layout", video_path, payload, {"kind": "webcam", **extra})
    return result


def _detect_content_with_cache(video_path: str, video_info, webcam_result, config: AppConfig):
    from app.cache import load_json_cache, save_json_cache
    from app.content_detector import ContentDetectionResult, detect_content_area

    webcam_crop = None
    if getattr(webcam_result, "has_webcam", False) and getattr(webcam_result, "region", None):
        wr = webcam_result.region
        webcam_crop = [wr.x, wr.y, wr.w, wr.h]
    extra = {
        "kind": "content",
        "version": 2,
        "manual": config.manual_slot_crop,
        "webcam_crop": webcam_crop,
        "dataset": _layout_dataset_signature(config),
    }
    cached = load_json_cache(config, "layout", video_path, extra)
    if cached and isinstance(cached.get("crop"), list):
        console.print("[green]Content/slot cache hit[/green]")
        return ContentDetectionResult(
            has_content=bool(cached.get("has_content", True)),
            crop=tuple(int(v) for v in cached["crop"]),
            confidence=float(cached.get("confidence", 0.0)),
            reason=str(cached.get("reason", "cache")),
        )

    result = detect_content_area(video_path, video_info, webcam_result, config)
    save_json_cache(
        config,
        "layout",
        video_path,
        {
            "has_content": result.has_content,
            "crop": list(result.crop),
            "confidence": result.confidence,
            "reason": result.reason,
        },
        extra,
    )
    return result


def _layout_dataset_signature(config: AppConfig) -> dict:
    from pathlib import Path

    if not getattr(config, "layout_annotation_dataset_enabled", True):
        return {"enabled": False}
    raw = getattr(config, "layout_annotation_dataset_path", "") or "layout_dataset/annotations.jsonl"
    path = Path(raw)
    if not path.is_absolute():
        from app.utils.helpers import project_root

        path = project_root() / path
    try:
        stat = path.stat()
        return {"enabled": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return {"enabled": True, "missing": True}


def main():
    """Direct entry for python -m app.main."""
    # Keep `python -m app.main` working even without click/rich installed.
    from app.cli import cli_entry
    cli_entry()


if __name__ == "__main__":
    main()
