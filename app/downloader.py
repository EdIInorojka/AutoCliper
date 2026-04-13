"""Video downloader using yt-dlp."""

from __future__ import annotations

import os
from pathlib import Path

from app.utils.console import get_console

console = get_console()


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def download_video(url: str, temp_dir: str) -> str:
    """Download video via yt-dlp into temp_dir. Returns path to downloaded file."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is not installed. Install dependencies (pip install -r requirements.txt) "
            "or use a local video file."
        ) from e

    out_tmpl = os.path.join(temp_dir, "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": out_tmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "retries": 3,
        "fragment_retries": 3,
    }

    console.print(f"[cyan]Downloading from: {url}[/cyan]")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp merge_output_format may produce .mp4
        # Find the actual output file
        if "requested_downloads" in info and info["requested_downloads"]:
            for dl in info["requested_downloads"]:
                if dl.get("_filename"):
                    fn = dl["_filename"]
                    if os.path.exists(fn):
                        console.print(f"[green]Downloaded: {fn}[/green]")
                        return fn
        # Fallback: search temp_dir for most recent mp4
        p = Path(temp_dir)
        mp4s = list(p.glob("*.mp4"))
        if mp4s:
            mp4s.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            console.print(f"[green]Downloaded: {mp4s[0]}[/green]")
            return str(mp4s[0])

    raise RuntimeError(f"yt-dlp did not produce a file for {url}")


def resolve_input(input_str: str, temp_dir: str) -> str:
    """Resolve input to a local file path. Downloads if URL."""
    if is_url(input_str):
        return download_video(input_str, temp_dir)
    else:
        p = Path(input_str)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {input_str}")
        return str(p.resolve())
