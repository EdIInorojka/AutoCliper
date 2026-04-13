"""Cleanup of temporary files after processing."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.utils.console import get_console

console = get_console()


def cleanup_temp_files(temp_dir: str, keep_patterns: list[str] | None = None) -> None:
    """
    Remove temporary files after processing.
    Keeps files matching keep_patterns.
    """
    if keep_patterns is None:
        keep_patterns = []

    p = Path(temp_dir)
    if not p.exists():
        return

    console.print("[cyan]Cleaning up temporary files...[/cyan]")

    removed = 0
    for item in p.iterdir():
        # Check if this file should be kept
        should_keep = False
        for pattern in keep_patterns:
            if item.match(pattern):
                should_keep = True
                break

        if should_keep:
            continue

        try:
            if item.is_file():
                item.unlink()
                removed += 1
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                removed += 1
        except OSError:
            pass  # Skip files in use

    console.print(f"[dim]Removed {removed} temp items[/dim]")


def safe_cleanup(temp_dir: str) -> None:
    """Aggressive cleanup - remove entire temp directory."""
    p = Path(temp_dir)
    if p.exists():
        console.print("[cyan]Removing temp directory...[/cyan]")
        shutil.rmtree(p, ignore_errors=True)


def delete_input_after_success(input_path: str, output_paths: list[str]) -> bool:
    """
    Delete the source video after successful render.
    This is intentionally separate from temp cleanup and only removes regular video files.
    """
    if not output_paths:
        console.print("[yellow]Skipping input deletion: no output clips were created[/yellow]")
        return False

    existing_outputs = [Path(p).resolve() for p in output_paths if Path(p).exists()]
    if len(existing_outputs) != len(output_paths):
        console.print("[yellow]Skipping input deletion: some output clips are missing[/yellow]")
        return False

    source = Path(input_path).resolve()
    if not source.exists():
        console.print("[dim]Input source already removed[/dim]")
        return False

    if not source.is_file():
        console.print(f"[yellow]Skipping input deletion: not a file: {source}[/yellow]")
        return False

    if source.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v"}:
        console.print(f"[yellow]Skipping input deletion: unsupported source extension: {source}[/yellow]")
        return False

    for output in existing_outputs:
        try:
            if source.samefile(output):
                console.print("[yellow]Skipping input deletion: source matches output file[/yellow]")
                return False
        except OSError:
            continue

    try:
        source.unlink()
    except OSError as e:
        console.print(f"[yellow]Could not delete input source: {e}[/yellow]")
        return False

    console.print(f"[green]Deleted input source after successful render: {source}[/green]")
    return True
