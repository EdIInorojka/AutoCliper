"""Video/audio probe using ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional

from app.utils.console import get_console
from app.utils.helpers import ffprobe_exe

console = get_console()


@dataclass
class VideoInfo:
    path: str
    duration_sec: float
    fps: float
    width: int
    height: int
    audio_streams: list[dict]
    video_stream_index: int = 0


def probe_video(path: str) -> VideoInfo:
    """Extract video metadata using ffprobe."""
    cmd = [
        ffprobe_exe(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    data = json.loads(result.stdout)

    duration_sec = 0.0
    if "format" in data and "duration" in data["format"]:
        duration_sec = float(data["format"]["duration"])

    video_stream = None
    video_stream_index = 0
    audio_streams = []
    fps = 30.0
    width = 0
    height = 0

    for i, stream in enumerate(data.get("streams", [])):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video" and video_stream is None:
            video_stream = stream
            video_stream_index = i
            # Parse fps
            r_frame_rate = stream.get("r_frame_rate", "30/1")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                try:
                    fps = float(num) / float(den) if float(den) != 0 else 30.0
                except (ValueError, ZeroDivisionError):
                    fps = 30.0
            width = stream.get("width", 0)
            height = stream.get("height", 0)
        elif codec_type == "audio":
            audio_streams.append({
                "index": i,
                "codec_name": stream.get("codec_name", "unknown"),
                "channels": stream.get("channels", 2),
                "sample_rate": stream.get("sample_rate", "44100"),
            })

    if video_stream is None:
        raise ValueError(f"No video stream found in {path}")

    console.print(f"[dim]Video: {width}x{height}, {fps:.2f}fps, {duration_sec:.1f}s[/dim]")

    return VideoInfo(
        path=path,
        duration_sec=duration_sec,
        fps=fps,
        width=width,
        height=height,
        audio_streams=audio_streams,
        video_stream_index=video_stream_index,
    )
